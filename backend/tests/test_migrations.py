import pytest
from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.exc import IntegrityError

import app.models  # noqa: F401
from app.db.base import Base
from app.db.migrations import run_schema_migrations


RAW_POST_ANALYSIS_COLUMNS = {
    "subscription_id",
    "notification_batch_id",
    "notification_batch_size",
    "analysis_status",
    "analysis_error",
    "analysis_attempts",
    "analyzed_at",
}

SUBSCRIPTION_LIFECYCLE_COLUMNS = {"deleted_at"}
SUBSCRIPTION_TRADE_COLUMNS = {
    "platform_account_id",
    "position_start_at",
    "visibility",
}
KOL_IDENTITY_COLUMNS = {"platform"}


def column_names(engine, table_name: str) -> set[str]:
    return {column["name"] for column in inspect(engine).get_columns(table_name)}


def test_migrations_are_idempotent_for_fresh_schema() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    run_schema_migrations(engine)
    run_schema_migrations(engine)

    assert RAW_POST_ANALYSIS_COLUMNS <= column_names(engine, "raw_posts")
    assert {"avatar_url", *KOL_IDENTITY_COLUMNS} <= column_names(engine, "kol_profiles")
    assert {
        *SUBSCRIPTION_LIFECYCLE_COLUMNS,
        *SUBSCRIPTION_TRADE_COLUMNS,
    } <= column_names(engine, "subscriptions")
    subscription_constraints = inspect(engine).get_unique_constraints("subscriptions")
    assert any(
        set(constraint["column_names"] or []) == {"platform", "platform_account_id"}
        for constraint in subscription_constraints
    )
    unique_constraints = inspect(engine).get_unique_constraints("raw_posts")
    assert any(
        set(constraint["column_names"] or []) == {"platform", "external_id"}
        for constraint in unique_constraints
    )
    indexes = inspect(engine).get_indexes("raw_posts")
    assert any(
        index["name"] == "ix_raw_posts_subscription_notification_batch"
        and index["column_names"] == ["subscription_id", "notification_batch_id"]
        for index in indexes
    )


def test_migrations_add_binance_copy_identity_and_private_visibility() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata = MetaData()
    Table(
        "subscriptions",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("platform", String(32), nullable=False),
        Column("platform_handle", String(255), nullable=False),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO subscriptions (id, platform, platform_handle) VALUES "
                "(1, 'x', 'legacy'), (2, 'binance_copy', '熬鹰资本')"
            )
        )

    run_schema_migrations(engine)
    run_schema_migrations(engine)

    assert SUBSCRIPTION_TRADE_COLUMNS <= column_names(engine, "subscriptions")
    with engine.connect() as connection:
        visibility = connection.execute(
            text("SELECT id, visibility FROM subscriptions ORDER BY id")
        ).all()
    assert visibility == [(1, "public"), (2, "private")]

    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE subscriptions SET platform_account_id = "
                "'5075281354358777856' WHERE id = 2"
            )
        )
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO subscriptions "
                    "(id, platform, platform_handle, platform_account_id) VALUES "
                    "(3, 'binance_copy', 'duplicate', '5075281354358777856')"
                )
            )


def test_migrations_split_legacy_shared_kol_profiles_by_platform() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata = MetaData()
    Table(
        "kol_profiles",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("display_name", String(255), nullable=False),
        Column("avatar_url", String(1024)),
        Column("description", Text),
        Column("primary_market", String(64)),
    )
    Table(
        "subscriptions",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("kol_profile_id", Integer),
        Column("platform", String(32), nullable=False),
        Column("platform_handle", String(255), nullable=False),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO kol_profiles (id, display_name, description) "
                "VALUES (1, 'same-handle', 'legacy profile')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO subscriptions "
                "(id, kol_profile_id, platform, platform_handle) VALUES "
                "(1, 1, 'x', 'same-handle'), "
                "(2, 1, 'binance_square', 'same-handle')"
            )
        )

    run_schema_migrations(engine)
    run_schema_migrations(engine)

    with engine.connect() as connection:
        subscriptions = connection.execute(
            text(
                "SELECT subscriptions.platform, subscriptions.kol_profile_id, kol_profiles.platform "
                "FROM subscriptions JOIN kol_profiles "
                "ON kol_profiles.id = subscriptions.kol_profile_id "
                "ORDER BY subscriptions.id"
            )
        ).all()
        kol_count = connection.execute(text("SELECT COUNT(*) FROM kol_profiles")).scalar_one()
    assert kol_count == 2
    assert subscriptions[0][1] != subscriptions[1][1]
    assert [(row[0], row[2]) for row in subscriptions] == [
        ("x", "x"),
        ("binance_square", "binance_square"),
    ]


def test_migrations_upgrade_previous_schema_and_backfill_analysis_state() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata = MetaData()
    Table(
        "raw_posts",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("platform", String(32), nullable=False),
        Column("external_id", String(255), nullable=False),
        Column("raw_text", Text, nullable=False),
        Column("created_at", DateTime),
        UniqueConstraint("platform", "external_id", name="uq_raw_posts_platform_external"),
    )
    Table(
        "signals",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("raw_post_id", Integer, nullable=False),
    )
    Table("subscriptions", metadata, Column("id", Integer, primary_key=True))
    Table("kol_profiles", metadata, Column("id", Integer, primary_key=True))
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO raw_posts (id, platform, external_id, raw_text, created_at) "
                "VALUES (1, 'x', 'completed-post', '已有信号', '2026-07-10 00:00:00'), "
                "(2, 'x', 'pending-post', '尚未分析', '2026-07-10 00:00:00')"
            )
        )
        connection.execute(text("INSERT INTO signals (id, raw_post_id) VALUES (1, 1)"))

    run_schema_migrations(engine)
    run_schema_migrations(engine)

    assert RAW_POST_ANALYSIS_COLUMNS <= column_names(engine, "raw_posts")
    assert {"avatar_url", *KOL_IDENTITY_COLUMNS} <= column_names(engine, "kol_profiles")
    assert SUBSCRIPTION_LIFECYCLE_COLUMNS <= column_names(engine, "subscriptions")
    with engine.connect() as connection:
        states = dict(
            connection.execute(text("SELECT external_id, analysis_status FROM raw_posts")).all()
        )
    assert states == {"completed-post": "completed", "pending-post": "pending"}
    unique_constraints = inspect(engine).get_unique_constraints("raw_posts")
    assert any(
        set(constraint["column_names"] or []) == {"platform", "external_id"}
        for constraint in unique_constraints
    )
