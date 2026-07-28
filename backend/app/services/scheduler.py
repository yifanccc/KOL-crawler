import asyncio
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm import Session

from app.collectors.base import CollectorAdapter
from app.collectors.factory import build_collectors_for_platform
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import CrawlRun, Subscription
from app.services.ingestion import ingest_subscription
from app.services.structurer import Structurer, build_structurer


def due_subscriptions_statement(now: datetime):
    return (
        select(Subscription)
        .where(Subscription.enabled.is_(True))
        .where((Subscription.next_check_at.is_(None)) | (Subscription.next_check_at <= now))
        .order_by(
            Subscription.next_check_at.is_not(None).asc(),
            Subscription.next_check_at.asc(),
            Subscription.id.asc(),
        )
    )


def due_subscriptions(session: Session, now: datetime) -> list[Subscription]:
    statement = due_subscriptions_statement(now)
    return list(session.scalars(statement).all())


def compute_next_check(now: datetime, interval_minutes: int) -> datetime:
    if interval_minutes < 1:
        raise ValueError("interval_minutes must be at least 1")
    return now + timedelta(minutes=interval_minutes)


@dataclass(frozen=True)
class LockHandle:
    key: str
    token: str


class MemoryLockManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tokens: dict[str, tuple[str, datetime]] = {}

    def acquire(self, key: str, ttl_seconds: int = 300) -> LockHandle | None:
        now = datetime.now(UTC)
        token = uuid4().hex
        expires_at = now + timedelta(seconds=ttl_seconds)
        with self._lock:
            current = self._tokens.get(key)
            if current and current[1] > now:
                return None
            self._tokens[key] = (token, expires_at)
        return LockHandle(key=key, token=token)

    def release(self, handle: LockHandle) -> None:
        with self._lock:
            current = self._tokens.get(handle.key)
            if current and current[0] == handle.token:
                self._tokens.pop(handle.key, None)


class RedisLockManager:
    def __init__(self, redis_url: str) -> None:
        import redis

        self.redis = redis.Redis.from_url(redis_url, decode_responses=True)
        self.fallback = MemoryLockManager()

    def acquire(self, key: str, ttl_seconds: int = 300) -> LockHandle | None:
        token = uuid4().hex
        try:
            acquired = self.redis.set(key, token, nx=True, ex=ttl_seconds)
        except Exception:
            return self.fallback.acquire(key, ttl_seconds)
        if not acquired:
            return None
        return LockHandle(key=key, token=token)

    def release(self, handle: LockHandle) -> None:
        try:
            if self.redis.get(handle.key) == handle.token:
                self.redis.delete(handle.key)
        except Exception:
            self.fallback.release(handle)


def build_lock_manager() -> RedisLockManager:
    return RedisLockManager(get_settings().redis_url)


def run_due_once(
    session_factory: sessionmaker[Session] = SessionLocal,
    collectors: dict[str, list[CollectorAdapter]] | None = None,
    lock_manager: MemoryLockManager | RedisLockManager | None = None,
    structurer: Structurer | None = None,
    limit: int | None = None,
) -> int:
    settings = get_settings()
    lock_manager = lock_manager or build_lock_manager()
    structurer = structurer or build_structurer()
    limit = limit or settings.backfill_limit
    processed = 0

    session = session_factory()
    try:
        subscriptions = due_subscriptions(session, datetime.now(UTC))
        for subscription in subscriptions:
            lock = lock_manager.acquire(
                f"crawl:{subscription.platform}:{subscription.id}",
                ttl_seconds=settings.lock_ttl_seconds,
            )
            if lock is None:
                continue
            crawl_run = CrawlRun(
                subscription_id=subscription.id,
                status="running",
                started_at=datetime.now(UTC),
            )
            session.add(crawl_run)
            session.commit()
            try:
                platform_collectors = (
                    collectors.get(subscription.platform, []) if collectors is not None else None
                )
                if platform_collectors is None:
                    platform_collectors = build_collectors_for_platform(subscription.platform)
                if not platform_collectors:
                    raise RuntimeError(
                        f"No live collector configured for {subscription.platform}; "
                        "configure the platform credentials"
                    )
                last_error: Exception | None = None
                result = None
                for collector in platform_collectors:
                    try:
                        result = ingest_subscription(
                            session=session,
                            subscription=subscription,
                            collector=collector,
                            structurer=structurer,
                            limit=limit,
                        )
                    except Exception as exc:
                        session.rollback()
                        last_error = exc
                        continue
                    if result.fetched_count:
                        break
                if result is None and last_error is not None:
                    raise last_error
                crawl_run.status = "success"
                crawl_run.finished_at = datetime.now(UTC)
                if result is not None:
                    crawl_run.fetched_count = result.fetched_count
                    crawl_run.inserted_count = result.inserted_count
                    crawl_run.structured_count = result.structured_count
                session.commit()
                processed += 1
            except Exception as exc:
                session.rollback()
                crawl_run = session.get(CrawlRun, crawl_run.id)
                if crawl_run is not None:
                    crawl_run.status = "failed"
                    crawl_run.error_message = str(exc)
                    crawl_run.finished_at = datetime.now(UTC)
                    session.commit()
            finally:
                lock_manager.release(lock)
    finally:
        session.close()
    return processed


async def scheduler_loop(stop_event: asyncio.Event) -> None:
    settings = get_settings()
    while not stop_event.is_set():
        try:
            await asyncio.to_thread(run_due_once)
        except Exception:
            # Keep the scheduler alive after collector or database edge cases.
            pass
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=max(settings.scheduler_poll_seconds, 1))
        except TimeoutError:
            continue
