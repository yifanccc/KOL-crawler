from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


MIGRATION_COLUMNS = {
    "subscriptions": {
        "platform_account_id": "VARCHAR(255) NULL",
        "visibility": "VARCHAR(16) NOT NULL DEFAULT 'public'",
        "system_prompt": "LONGTEXT NULL",
        "user_prompt": "LONGTEXT NULL",
        "output_schema_json": "LONGTEXT NULL",
        "markets_json": "LONGTEXT NULL",
        "prompt_version": "VARCHAR(64) NULL",
        "deleted_at": "DATETIME NULL",
    },
    "signals": {
        "stance_cn": "VARCHAR(32) NULL",
        "summary_cn": "LONGTEXT NULL",
        "symbols_json": "LONGTEXT NULL",
        "market": "VARCHAR(32) NULL",
        "key_points_json": "LONGTEXT NULL",
        "confidence_score": "INT NULL",
        "importance": "INT NULL",
        "tags_json": "LONGTEXT NULL",
        "action_hint": "LONGTEXT NULL",
        "source_language": "VARCHAR(64) NULL",
        "translated_text_cn": "LONGTEXT NULL",
        "risk_warning": "LONGTEXT NULL",
        "prompt_version": "VARCHAR(64) NULL",
    },
    "raw_posts": {
        "subscription_id": "BIGINT NULL",
        "notification_batch_id": "VARCHAR(64) NULL",
        "notification_batch_size": "INT NULL",
        "analysis_status": "VARCHAR(32) NOT NULL DEFAULT 'pending'",
        "analysis_error": "LONGTEXT NULL",
        "analysis_attempts": "INT NOT NULL DEFAULT 0",
        "analyzed_at": "DATETIME NULL",
    },
    "kol_profiles": {
        "avatar_url": "VARCHAR(1024) NULL",
        "platform": "VARCHAR(32) NULL",
    },
    "position_estimates": {
        "entry_price": "VARCHAR(64) NULL",
        "mark_price": "VARCHAR(64) NULL",
        "notional": "VARCHAR(64) NULL",
        "leverage": "VARCHAR(64) NULL",
        "position_margin": "VARCHAR(64) NULL",
        "estimated_pnl": "VARCHAR(64) NULL",
        "price_updated_at": "DATETIME NULL",
    },
}


def _repair_kol_platform_identity(connection) -> None:
    inspector = inspect(connection)
    required_kol_columns = {
        "id",
        "platform",
        "display_name",
        "avatar_url",
        "description",
        "primary_market",
    }
    required_subscription_columns = {
        "id",
        "kol_profile_id",
        "platform",
        "platform_handle",
    }
    if not required_kol_columns <= {
        column["name"] for column in inspector.get_columns("kol_profiles")
    }:
        return
    if not required_subscription_columns <= {
        column["name"] for column in inspector.get_columns("subscriptions")
    }:
        return

    profiles = {
        row["id"]: dict(row)
        for row in connection.execute(
            text(
                "SELECT id, platform, display_name, avatar_url, description, primary_market "
                "FROM kol_profiles ORDER BY id"
            )
        ).mappings()
    }
    subscriptions = list(
        connection.execute(
            text(
                "SELECT id, kol_profile_id, platform, platform_handle "
                "FROM subscriptions WHERE kol_profile_id IS NOT NULL ORDER BY id"
            )
        ).mappings()
    )

    first_platform_by_profile: dict[int, str] = {}
    for subscription in subscriptions:
        first_platform_by_profile.setdefault(
            subscription["kol_profile_id"], subscription["platform"]
        )
    for profile_id, profile in profiles.items():
        if not profile.get("platform"):
            platform = first_platform_by_profile.get(profile_id, "x")
            connection.execute(
                text("UPDATE kol_profiles SET platform = :platform WHERE id = :profile_id"),
                {"platform": platform, "profile_id": profile_id},
            )
            profile["platform"] = platform

    profiles_by_identity = {
        (profile["platform"], profile["display_name"]): profile
        for profile in profiles.values()
    }
    for subscription in subscriptions:
        identity = (subscription["platform"], subscription["platform_handle"])
        target = profiles_by_identity.get(identity)
        if target is None:
            source = profiles[subscription["kol_profile_id"]]
            result = connection.execute(
                text(
                    "INSERT INTO kol_profiles "
                    "(platform, display_name, avatar_url, description, primary_market) "
                    "VALUES (:platform, :display_name, :avatar_url, :description, :primary_market)"
                ),
                {
                    "platform": subscription["platform"],
                    "display_name": subscription["platform_handle"],
                    "avatar_url": source.get("avatar_url"),
                    "description": source.get("description"),
                    "primary_market": source.get("primary_market"),
                },
            )
            target = {
                **source,
                "id": result.lastrowid,
                "platform": subscription["platform"],
                "display_name": subscription["platform_handle"],
            }
            profiles[target["id"]] = target
            profiles_by_identity[identity] = target
        if subscription["kol_profile_id"] != target["id"]:
            connection.execute(
                text(
                    "UPDATE subscriptions SET kol_profile_id = :kol_profile_id "
                    "WHERE id = :subscription_id"
                ),
                {
                    "kol_profile_id": target["id"],
                    "subscription_id": subscription["id"],
                },
            )


def run_schema_migrations(engine: Engine) -> None:
    inspector = inspect(engine)
    with engine.begin() as connection:
        existing_tables = set(inspector.get_table_names())
        for table, definitions in MIGRATION_COLUMNS.items():
            if table not in existing_tables:
                continue
            existing = {column["name"] for column in inspector.get_columns(table)}
            for column, definition in definitions.items():
                if column not in existing:
                    connection.execute(text(f"ALTER TABLE `{table}` ADD COLUMN `{column}` {definition}"))
        if "subscriptions" in existing_tables:
            subscription_identity = {"platform", "platform_account_id"}
            subscription_inspector = inspect(connection)
            subscription_columns = {
                item["name"]
                for item in subscription_inspector.get_columns("subscriptions")
            }
            if subscription_identity <= subscription_columns:
                connection.execute(
                    text(
                        "UPDATE subscriptions SET visibility = 'private' "
                        "WHERE platform = 'binance_copy'"
                    )
                )
                trade_reset_values = {
                    "prompt": "NULL",
                    "system_prompt": "NULL",
                    "user_prompt": "NULL",
                    "output_schema_json": "NULL",
                    "prompt_version": "NULL",
                    "model_config_id": "NULL",
                    "markets_json": "'[\"crypto\"]'",
                }
                trade_reset_assignments = [
                    f"`{column}` = {value}"
                    for column, value in trade_reset_values.items()
                    if column in subscription_columns
                ]
                if trade_reset_assignments:
                    connection.execute(
                        text(
                            "UPDATE subscriptions SET "
                            + ", ".join(trade_reset_assignments)
                            + " WHERE platform = 'binance_copy'"
                        )
                    )
                has_identity_constraint = any(
                    set(item["column_names"] or []) == subscription_identity
                    for item in subscription_inspector.get_unique_constraints("subscriptions")
                ) or any(
                    item.get("unique")
                    and set(item["column_names"] or []) == subscription_identity
                    for item in subscription_inspector.get_indexes("subscriptions")
                )
                if not has_identity_constraint:
                    if engine.dialect.name == "sqlite":
                        connection.execute(
                            text(
                                "CREATE UNIQUE INDEX uq_subscriptions_platform_account "
                                "ON subscriptions (platform, platform_account_id)"
                            )
                        )
                    elif engine.dialect.name == "mysql":
                        connection.execute(
                            text(
                                "ALTER TABLE subscriptions ADD CONSTRAINT "
                                "uq_subscriptions_platform_account "
                                "UNIQUE (platform, platform_account_id)"
                            )
                        )
        if {"kol_profiles", "subscriptions"} <= existing_tables:
            _repair_kol_platform_identity(connection)
        if {"raw_posts", "signals"} <= existing_tables:
            connection.execute(
                text(
                    "UPDATE raw_posts SET analysis_status = 'pending' "
                    "WHERE analysis_status IS NULL OR analysis_status = ''"
                )
            )
            connection.execute(
                text(
                    "UPDATE raw_posts SET analysis_status = 'completed', "
                    "analyzed_at = COALESCE(analyzed_at, created_at) "
                    "WHERE EXISTS (SELECT 1 FROM signals "
                    "WHERE signals.raw_post_id = raw_posts.id)"
                )
            )
        if "raw_posts" in existing_tables:
            raw_post_indexes = {
                item["name"] for item in inspect(connection).get_indexes("raw_posts")
            }
            if "ix_raw_posts_subscription_notification_batch" not in raw_post_indexes:
                connection.execute(
                    text(
                        "CREATE INDEX ix_raw_posts_subscription_notification_batch "
                        "ON raw_posts (subscription_id, notification_batch_id)"
                    )
                )
        if engine.dialect.name == "mysql" and "notification_events" in existing_tables:
            names = {item["name"] for item in inspector.get_unique_constraints("notification_events")}
            if "uq_notification_event_signal_rule" not in names:
                connection.execute(text("ALTER TABLE notification_events ADD CONSTRAINT uq_notification_event_signal_rule UNIQUE (signal_id, notification_rule_id)"))
        if engine.dialect.name == "mysql" and "kol_profiles" in existing_tables:
            names = {item["name"] for item in inspect(connection).get_unique_constraints("kol_profiles")}
            if "uq_kol_profiles_platform_handle" not in names:
                connection.execute(
                    text(
                        "ALTER TABLE kol_profiles ADD CONSTRAINT "
                        "uq_kol_profiles_platform_handle UNIQUE (platform, display_name)"
                    )
                )
