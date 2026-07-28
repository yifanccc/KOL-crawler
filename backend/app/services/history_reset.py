from sqlalchemy import delete, update
from sqlalchemy.orm import Session

from app.models import (
    Asset,
    CollectorAgent,
    CrawlRun,
    NotificationEvent,
    RawPost,
    Signal,
    SignalAsset,
    SignalTag,
    Subscription,
)


def reset_signal_history(session: Session) -> dict[str, int]:
    models = (
        ("notification_events", NotificationEvent),
        ("signal_tags", SignalTag),
        ("signal_assets", SignalAsset),
        ("signals", Signal),
        ("raw_posts", RawPost),
        ("assets", Asset),
        ("crawl_runs", CrawlRun),
        ("collector_agents", CollectorAgent),
    )
    deleted: dict[str, int] = {}
    for name, model in models:
        result = session.execute(delete(model))
        deleted[name] = result.rowcount or 0
    session.execute(
        update(Subscription).values(
            checkpoint=None,
            next_check_at=None,
            last_checked_at=None,
            last_success_at=None,
        )
    )
    return deleted
