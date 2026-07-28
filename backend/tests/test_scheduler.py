from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects import mysql

from app.collectors.base import CollectedPost
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models import CrawlRun, RawPost, Subscription
from app.services.scheduler import MemoryLockManager, due_subscriptions_statement, run_due_once
from app.services.structurer import HeuristicStructurer


class FakeCollector:
    def fetch_new(self, handle: str, checkpoint: str | None = None, limit: int = 20):
        return [
            CollectedPost(
                platform="x",
                external_id=str(index),
                url=f"https://x.com/{handle}/status/{index}",
                author_handle=handle,
                author_name=handle,
                published_at=datetime(2026, 7, 9, 12, index, tzinfo=UTC),
                raw_text=f"$AXTI supply-chain price update {index}",
            )
            for index in range(10)
        ]


def reset_database() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def test_run_due_once_crawls_due_subscription_and_records_checkpoint() -> None:
    reset_database()
    session = SessionLocal()
    try:
        subscription = Subscription(
            platform="x",
            platform_handle="aleabitoreddit",
            interval_minutes=1,
            next_check_at=datetime.now(UTC) - timedelta(minutes=1),
            enabled=True,
        )
        session.add(subscription)
        session.commit()
        subscription_id = subscription.id
    finally:
        session.close()

    processed = run_due_once(
        session_factory=SessionLocal,
        collectors={"x": [FakeCollector()]},
        lock_manager=MemoryLockManager(),
        structurer=HeuristicStructurer(),
        limit=10,
    )

    session = SessionLocal()
    try:
        crawl_run = session.scalar(select(CrawlRun))
        stored_subscription = session.get(Subscription, subscription_id)
        raw_posts = session.scalars(select(RawPost)).all()
    finally:
        session.close()

    assert processed == 1
    assert crawl_run is not None
    assert crawl_run.status == "success"
    assert len(raw_posts) == 10
    assert stored_subscription is not None
    assert stored_subscription.checkpoint == "9"


def test_due_subscriptions_query_is_mysql_compatible() -> None:
    statement = due_subscriptions_statement(datetime(2026, 7, 9, tzinfo=UTC))

    compiled = str(statement.compile(dialect=mysql.dialect()))

    assert "NULLS FIRST" not in compiled
    assert "subscriptions.next_check_at IS NOT NULL" in compiled


def test_due_subscription_without_live_collector_is_recorded_as_failed() -> None:
    reset_database()
    session = SessionLocal()
    try:
        session.add(
            Subscription(
                platform="x",
                platform_handle="senerity",
                interval_minutes=1,
                next_check_at=datetime.now(UTC) - timedelta(minutes=1),
                enabled=True,
            )
        )
        session.commit()
    finally:
        session.close()

    processed = run_due_once(
        session_factory=SessionLocal,
        collectors={"x": []},
        lock_manager=MemoryLockManager(),
        structurer=HeuristicStructurer(),
    )

    session = SessionLocal()
    try:
        crawl_run = session.scalar(select(CrawlRun))
    finally:
        session.close()

    assert processed == 0
    assert crawl_run is not None
    assert crawl_run.status == "failed"
    assert "No live collector configured" in (crawl_run.error_message or "")
