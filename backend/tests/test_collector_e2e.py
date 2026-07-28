from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.main import app
from app.models import NotificationEvent, NotificationRule, RawPost, Signal, SignalAsset, SignalTag, Subscription
from app.services.analysis_queue import process_pending_posts
from app.services.notifications import dispatch_notifications
from app.services.structurer import FallbackStructurer, HeuristicStructurer, Structurer


HEADERS = {"Authorization": "Bearer collector-test-token"}


class BrokenModel:
    def complete(self, *_args, **_kwargs) -> str:
        return "this is deliberately malformed model output"


class FakeNtfyClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def publish(self, server: str, topic: str, **_kwargs) -> None:
        self.calls.append((server, topic))


def test_fixture_upload_to_analysis_is_idempotent(monkeypatch) -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with SessionLocal.begin() as session:
        x = Subscription(platform="x", platform_handle="senerity", interval_minutes=1)
        binance = Subscription(platform="binance_square", platform_handle="binance", interval_minutes=2)
        session.add_all([x, binance])
        session.flush()
        x_id, binance_id = x.id, binance.id
        session.add_all(
            [
                NotificationRule(
                    subscription_id=x_id,
                    ntfy_server="https://ntfy.invalid",
                    ntfy_topic="fixture",
                    min_confidence="低",
                    require_asset=True,
                ),
                NotificationRule(
                    subscription_id=binance_id,
                    ntfy_server="https://ntfy.invalid",
                    ntfy_topic="fixture",
                    min_confidence="低",
                    require_asset=True,
                ),
            ]
        )

    posts = [
        {"subscriptionId": x_id, "platform": "x", "externalId": "100", "rawContent": "$BTC breakout, staying long", "publishedAt": "2026-07-10T10:00:00Z"},
        {"subscriptionId": x_id, "platform": "x", "externalId": "101", "rawContent": "中文观点：$SPX 看空，等待确认。"},
        {"subscriptionId": binance_id, "platform": "binance_square", "externalId": "200", "rawContent": "$ETH funding remains elevated"},
        {"subscriptionId": x_id, "platform": "x", "externalId": "102", "rawContent": "没有明确标的，只是市场观察。"},
        {"subscriptionId": x_id, "platform": "x", "externalId": "103", "rawContent": "$AAPL 关注突破后的量能"},
    ]
    with TestClient(app) as client:
        first = client.post(
            "/api/v1/collector/posts",
            headers=HEADERS,
            json={"agentId": "home-mac-01", "posts": posts},
        )
        second = client.post(
            "/api/v1/collector/posts",
            headers=HEADERS,
            json={"agentId": "home-mac-01", "posts": posts},
        )
    assert [item["status"] for item in first.json()["items"]] == ["accepted"] * len(posts)
    assert [item["status"] for item in second.json()["items"]] == ["duplicate"] * len(posts)

    ntfy = FakeNtfyClient()
    monkeypatch.setattr(
        "app.services.analysis_queue.dispatch_notifications",
        lambda session, signal: dispatch_notifications(session, signal, client=ntfy),
    )
    fallback_structurer = FallbackStructurer(Structurer(BrokenModel()), HeuristicStructurer())
    with SessionLocal() as session:
        assert process_pending_posts(session, fallback_structurer, limit=10) == len(posts)
        assert process_pending_posts(session, fallback_structurer, limit=10) == 0
        assert session.scalar(select(func.count()).select_from(RawPost)) == len(posts)
        assert session.scalar(select(func.count()).select_from(Signal)) == len(posts)
        assert session.scalar(select(func.count()).select_from(SignalTag)) >= 1
        no_symbol_signal = session.scalar(
            select(Signal).join(RawPost, RawPost.id == Signal.raw_post_id).where(RawPost.external_id == "102")
        )
        assert no_symbol_signal is not None
        assert session.scalar(
            select(func.count()).select_from(SignalAsset).where(SignalAsset.signal_id == no_symbol_signal.id)
        ) == 0
        expected_notifications = session.scalar(
            select(func.count())
            .select_from(Signal)
            .join(SignalAsset, SignalAsset.signal_id == Signal.id)
            .where(Signal.actionable.is_(True))
        )
        assert session.scalar(select(func.count()).select_from(NotificationEvent)) == expected_notifications
        assert all(row.analysis_status == "completed" for row in session.scalars(select(RawPost)).all())
        assert all(signal.structured_status == "fallback" for signal in session.scalars(select(Signal)).all())
    assert len(ntfy.calls) == expected_notifications
