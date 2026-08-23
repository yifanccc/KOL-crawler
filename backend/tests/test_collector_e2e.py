from datetime import UTC, datetime
from unittest.mock import Mock

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.main import app
from app.models import (
    KolProfile,
    NotificationEvent,
    NotificationRule,
    RawPost,
    Signal,
    SignalAsset,
    SignalTag,
    Subscription,
)
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


def test_binance_trade_upload_is_deterministic_and_private(monkeypatch) -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    account_id = "5075281354358777856"
    with SessionLocal.begin() as session:
        kol = KolProfile(platform="binance_copy", display_name="熬鹰资本")
        session.add(kol)
        session.flush()
        subscription = Subscription(
            platform="binance_copy",
            platform_account_id=account_id,
            platform_handle="熬鹰资本",
            visibility="private",
            interval_minutes=10,
            kol_profile_id=kol.id,
        )
        session.add(subscription)
        session.flush()
        subscription_id = subscription.id
        session.add(
            NotificationRule(
                subscription_id=subscription_id,
                ntfy_server="https://ntfy.invalid",
                ntfy_topic="trade-e2e",
                min_confidence="低",
                require_asset=True,
            )
        )

    batch_id = "c" * 64
    raw_payload = {
        "schemaVersion": 2,
        "platform": "binance_copy",
        "accountId": account_id,
        "sourceRecordId": "2",
        "revision": "r1",
        "action": "ADD",
        "effectiveAction": "INCREASE",
        "symbol": "BTCUSDT",
        "positionSide": "LONG",
        "quantity": "0.05",
        "price": "50000",
        "leverage": "10",
        "eventTime": "2026-08-09T01:02:00Z",
        "positionAfter": {
            "side": "LONG",
            "quantity": "0.15",
            "confidence": "LOW",
            "status": "ACTIVE",
        },
        "sourceRecord": {"id": "2"},
        "collectionBatchId": batch_id,
        "collectionBatchSize": 1,
        "positionChanges": [
            {
                "symbol": "BTCUSDT",
                "positionSide": "LONG",
                "before": {
                    "side": "LONG",
                    "quantity": "0.10",
                    "entryPrice": "50000",
                    "leverage": "10",
                    "confidence": "LOW",
                    "status": "ACTIVE",
                },
                "after": {
                    "side": "LONG",
                    "quantity": "0.15",
                    "entryPrice": "50000",
                    "leverage": "10",
                    "confidence": "LOW",
                    "status": "ACTIVE",
                },
            }
        ],
    }
    external_id = f"{account_id}:2:r1"
    post = {
        "subscriptionId": subscription_id,
        "platform": "binance_copy",
        "externalId": external_id,
        "authorHandle": "熬鹰资本",
        "authorName": "熬鹰资本",
        "publishedAt": raw_payload["eventTime"],
        "url": (
            "https://www.binance.com/zh-CN/copy-trading/lead-details/"
            f"{account_id}"
        ),
        "rawContent": "熬鹰资本 BTCUSDT 加仓 多头",
        "rawPayload": raw_payload,
        "batchId": batch_id,
        "batchSize": 1,
    }

    model = Mock()
    model.structure.side_effect = AssertionError("LLM must not run")
    ntfy = FakeNtfyClient()
    monkeypatch.setattr(
        "app.services.analysis_queue.dispatch_notifications",
        lambda session, signal: dispatch_notifications(session, signal, client=ntfy),
    )
    with TestClient(app) as client:
        upload = client.post(
            "/api/v1/collector/posts",
            headers=HEADERS,
            json={"agentId": "home-mac-01", "posts": [post]},
        )
        assert upload.json()["items"] == [
            {"externalId": external_id, "status": "accepted"}
        ]

        with SessionLocal() as session:
            assert process_pending_posts(session, model) == 1
            assert session.scalar(
                select(func.count()).select_from(NotificationEvent)
            ) == 1
            stored_post = session.scalar(select(RawPost))
            assert stored_post.notification_batch_id == batch_id
            assert stored_post.notification_batch_size == 1
        model.structure.assert_not_called()
        assert len(ntfy.calls) == 1

        login = client.post(
            "/api/auth/login",
            json={"username": "testadmin", "password": "test-admin-password"},
        )
        assert login.status_code == 200
        regular = client.get("/api/signals")
        private = client.get("/api/admin/signals")

    assert regular.json()["items"] == []
    assert regular.json()["overallTotal"] == 0
    private_items = private.json()["items"]
    assert len(private_items) == 1
    assert private_items[0]["platform"] == "BINANCE_COPY"
    assert private_items[0]["structuredStatus"] == "deterministic"
    assert private_items[0]["actionable"] is True
