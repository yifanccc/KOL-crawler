from unittest.mock import Mock

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.main import app
from app.models import KolProfile, RawPost, Signal, SignalAsset, SignalTag, Subscription
from app.services.analysis_queue import process_pending_posts
from app.services.structurer import HeuristicStructurer


HEADERS = {"Authorization": "Bearer collector-test-token"}


def test_analysis_queue_retries_notifications_without_pending_posts(monkeypatch) -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    retry_calls = []
    monkeypatch.setattr(
        "app.services.analysis_queue.retry_failed_notifications",
        lambda session: retry_calls.append(session) or 0,
    )

    with SessionLocal() as session:
        assert process_pending_posts(session, HeuristicStructurer()) == 0
        assert retry_calls == [session]


def test_collector_upload_is_per_item_idempotent_and_analysis_runs_once(monkeypatch) -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with SessionLocal.begin() as session:
        kol = KolProfile(display_name="senerity", avatar_url="https://example.com/old.jpg")
        session.add(kol)
        session.flush()
        kol_id = kol.id
        subscription = Subscription(platform="x", platform_handle="senerity", interval_minutes=1)
        subscription.kol_profile_id = kol.id
        session.add(subscription)
        session.flush()
        subscription_id = subscription.id
    post = {
        "subscriptionId": subscription_id,
        "platform": "x",
        "externalId": "post-1",
        "authorHandle": "senerity",
        "authorName": "Senerity",
        "authorAvatarUrl": "https://example.com/avatar.jpg",
        "publishedAt": "2026-07-10T10:20:00Z",
        "url": "https://x.com/senerity/status/post-1",
        "rawContent": "$BTC 看多，等待突破。",
        "rawPayload": {"id": "post-1"},
        "contentHash": "a" * 64,
    }
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/collector/posts",
            headers=HEADERS,
            json={"agentId": "home-mac-01", "posts": [post, post, {**post, "externalId": "bad", "platform": "binance_square"}]},
        )
    assert [item["status"] for item in response.json()["items"]] == ["accepted", "duplicate", "invalid"]
    dispatched_signal_ids: list[int] = []
    monkeypatch.setattr(
        "app.services.analysis_queue.dispatch_notifications",
        lambda _session, signal: dispatched_signal_ids.append(signal.id) or 0,
    )
    with SessionLocal() as session:
        assert session.scalar(select(RawPost).where(RawPost.external_id == "post-1")).analysis_status == "pending"
        assert process_pending_posts(session, HeuristicStructurer()) == 1
        assert process_pending_posts(session, HeuristicStructurer()) == 0
        assert len(session.scalars(select(RawPost)).all()) == 1
        assert len(session.scalars(select(Signal)).all()) == 1
        assert len(session.scalars(select(SignalAsset)).all()) == 1
        assert len(session.scalars(select(SignalTag)).all()) == 1
        assert session.get(KolProfile, kol_id).avatar_url == "https://example.com/avatar.jpg"
    assert dispatched_signal_ids == [1]


def test_collector_rejects_oversized_content_without_rolling_back_siblings() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with SessionLocal.begin() as session:
        subscription = Subscription(platform="x", platform_handle="senerity", interval_minutes=1)
        session.add(subscription)
        session.flush()
        subscription_id = subscription.id
    valid = {
        "subscriptionId": subscription_id,
        "platform": "x",
        "externalId": "small",
        "rawContent": "BTC 观察",
    }
    oversized = {**valid, "externalId": "large", "rawContent": "x" * 50_001}
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/collector/posts",
            headers=HEADERS,
            json={"agentId": "home-mac-01", "posts": [valid, oversized]},
        )
    assert [item["status"] for item in response.json()["items"]] == ["accepted", "invalid"]
    with SessionLocal() as session:
        assert [row.external_id for row in session.scalars(select(RawPost)).all()] == ["small"]


def test_collector_trade_upload_uses_deterministic_analysis(monkeypatch) -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    account_id = "5075281354358777856"
    with SessionLocal.begin() as session:
        subscription = Subscription(
            platform="binance_copy",
            platform_account_id=account_id,
            platform_handle="熬鹰资本",
            visibility="private",
            interval_minutes=10,
        )
        session.add(subscription)
        session.flush()
        subscription_id = subscription.id
    payload = {
        "schemaVersion": 1,
        "platform": "binance_copy",
        "accountId": account_id,
        "sourceRecordId": "record-3",
        "revision": "r1",
        "action": "OPEN",
        "effectiveAction": "INCREASE",
        "symbol": "ETHUSDT",
        "positionSide": "SHORT",
        "quantity": "2.0",
        "price": "3200.0",
        "leverage": None,
        "eventTime": "2026-08-09T04:00:00Z",
        "positionAfter": {
            "side": "SHORT",
            "quantity": "2.0",
            "confidence": "LOW",
            "status": "ACTIVE",
        },
        "sourceRecord": {"orderUpdateTime": 1786248000000},
    }
    post = {
        "subscriptionId": subscription_id,
        "platform": "binance_copy",
        "externalId": f"{account_id}:record-3:r1",
        "authorHandle": "熬鹰资本",
        "authorName": "熬鹰资本",
        "publishedAt": payload["eventTime"],
        "url": (
            "https://www.binance.com/zh-CN/copy-trading/lead-details/"
            f"{account_id}"
        ),
        "rawContent": "熬鹰资本 ETHUSDT 开仓 空头",
        "rawPayload": payload,
    }
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/collector/posts",
            headers=HEADERS,
            json={"agentId": "home-mac-01", "posts": [post]},
        )
    assert response.json()["items"] == [
        {"externalId": post["externalId"], "status": "accepted"}
    ]

    structurer = Mock()
    structurer.structure.side_effect = AssertionError("LLM must not run")
    monkeypatch.setattr(
        "app.services.analysis_queue.dispatch_notifications", lambda *_args: 0
    )
    with SessionLocal() as session:
        assert process_pending_posts(session, structurer) == 1
        signal = session.scalar(select(Signal))

    structurer.structure.assert_not_called()
    assert signal is not None
    assert signal.stance == "bearish"
    assert signal.actionable is True
    assert signal.structured_status == "deterministic"
