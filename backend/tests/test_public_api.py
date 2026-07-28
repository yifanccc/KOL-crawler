from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.main import app
from app.models import Asset, CollectorAgent, KolProfile, RawPost, Signal, SignalAsset, SignalTag, Subscription


def reset_database() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def seed_paginated_signals() -> None:
    base = datetime(2026, 7, 1, tzinfo=timezone.utc)
    with SessionLocal.begin() as session:
        for index in range(105):
            raw_post = RawPost(
                platform="x",
                external_id=f"page-{index}",
                published_at=base + timedelta(minutes=index),
                raw_text=f"post {index}",
            )
            session.add(raw_post)
            session.flush()
            session.add(
                Signal(
                    raw_post_id=raw_post.id,
                    actionable=index == 0,
                    stance="bullish" if index == 0 else "neutral",
                    summary=f"signal {index}",
                    importance=5 if index == 0 else 1,
                )
            )


def test_signals_endpoint_returns_true_totals_and_pagination() -> None:
    reset_database()
    seed_paginated_signals()

    with TestClient(app) as client:
        client.post(
            "/api/auth/login",
            json={"username": "testadmin", "password": "test-admin-password"},
        )
        first = client.get("/api/signals")
        tail = client.get("/api/signals", params={"limit": 5, "offset": 100})

    assert first.status_code == 200
    assert tail.status_code == 200
    assert len(first.json()["items"]) == 100
    assert {
        key: first.json()[key]
        for key in ("total", "overallTotal", "actionableTotal", "limit", "offset")
    } == {
        "total": 105,
        "overallTotal": 105,
        "actionableTotal": 1,
        "limit": 100,
        "offset": 0,
    }
    assert [item["summary"] for item in tail.json()["items"]] == [
        "signal 4",
        "signal 3",
        "signal 2",
        "signal 1",
        "signal 0",
    ]


def test_actionable_filter_runs_before_pagination() -> None:
    reset_database()
    seed_paginated_signals()

    with TestClient(app) as client:
        client.post(
            "/api/auth/login",
            json={"username": "testadmin", "password": "test-admin-password"},
        )
        response = client.get("/api/signals", params={"actionable": "true"})

    assert response.status_code == 200
    assert [item["summary"] for item in response.json()["items"]] == ["signal 0"]
    assert response.json()["total"] == 1
    assert response.json()["overallTotal"] == 105
    assert response.json()["actionableTotal"] == 1


def test_platform_time_and_importance_filters_run_before_pagination() -> None:
    reset_database()
    now = datetime.now(timezone.utc)
    fixtures = [
        ("recent-match", "x", now - timedelta(hours=1), 4, True),
        ("low-importance", "x", now - timedelta(minutes=30), 2, False),
        ("outside-window", "x", now - timedelta(days=8), 5, True),
        ("other-platform", "binance_square", now - timedelta(minutes=10), 5, True),
    ]
    with SessionLocal.begin() as session:
        for summary, platform, published_at, importance, actionable in fixtures:
            raw_post = RawPost(
                platform=platform,
                external_id=f"filter-{summary}",
                published_at=published_at,
                raw_text=summary,
            )
            session.add(raw_post)
            session.flush()
            session.add(
                Signal(
                    raw_post_id=raw_post.id,
                    actionable=actionable,
                    stance="bullish" if actionable else "neutral",
                    summary=summary,
                    importance=importance,
                )
            )

    with TestClient(app) as client:
        client.post(
            "/api/auth/login",
            json={"username": "testadmin", "password": "test-admin-password"},
        )
        response = client.get(
            "/api/signals",
            params={
                "platform": "X",
                "time_range": "24h",
                "min_importance": 4,
                "limit": 1,
            },
        )

    assert response.status_code == 200
    assert [item["summary"] for item in response.json()["items"]] == ["recent-match"]
    assert response.json()["total"] == 1
    assert response.json()["overallTotal"] == 4
    assert response.json()["actionableTotal"] == 1


def test_signals_endpoint_validates_pagination_bounds() -> None:
    reset_database()

    with TestClient(app) as client:
        client.post(
            "/api/auth/login",
            json={"username": "testadmin", "password": "test-admin-password"},
        )
        responses = [
            client.get("/api/signals", params={"limit": 0}),
            client.get("/api/signals", params={"limit": 101}),
            client.get("/api/signals", params={"offset": -1}),
        ]

    assert [response.status_code for response in responses] == [422, 422, 422]


def test_signals_endpoint_filters_by_kol_asset_stance_and_tag() -> None:
    reset_database()
    session = SessionLocal()
    try:
        kol = KolProfile(
            display_name="aleabitoreddit",
            avatar_url="https://example.com/avatar.jpg",
            primary_market="US_STOCK",
        )
        session.add(kol)
        session.flush()
        subscription = Subscription(
            kol_profile_id=kol.id,
            platform="x",
            platform_handle="aleabitoreddit",
            interval_minutes=1,
        )
        session.add(subscription)
        session.flush()
        raw_post = RawPost(
            platform="x",
            external_id="1",
            url="https://x.com/aleabitoreddit/status/1",
            author_handle="aleabitoreddit",
            published_at=datetime(2026, 7, 9, tzinfo=timezone.utc),
            raw_text="$AXTI supply chain",
        )
        session.add(raw_post)
        session.flush()
        signal = Signal(
            raw_post_id=raw_post.id,
            subscription_id=subscription.id,
            actionable=True,
            stance="bullish",
            stance_cn="多",
            summary="AXTI supply-chain pricing signal",
            translated_text_cn="AXTI 供应链定价信号",
            evidence_json='["供应链"]',
            confidence="高",
            confidence_score=88,
            importance=5,
            structured_status="ok",
        )
        session.add(signal)
        session.flush()
        asset = Asset(symbol="AXTI", market="US_STOCK", asset_type="stock")
        session.add(asset)
        session.flush()
        session.add(SignalAsset(signal_id=signal.id, asset_id=asset.id))
        session.add(SignalTag(signal_id=signal.id, tag="供应链", source="llm"))
        session.commit()
        kol_id = kol.id
    finally:
        session.close()

    with TestClient(app) as client:
        client.post(
            "/api/auth/login",
            json={"username": "testadmin", "password": "test-admin-password"},
        )
        response = client.get(
            "/api/signals",
            params={"kol_id": kol_id, "asset": "AXTI", "stance": "多", "tag": "供应链"},
        )
        frontend_style = client.get(
            "/api/signals",
            params={"symbol": "AXTI", "stance": "long", "actionable": "true"},
        )
        filtered_out = client.get("/api/signals", params={"asset": "BTC"})

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["kol"]["avatarUrl"] == "https://example.com/avatar.jpg"
    assert item["kol"]["handle"] == "aleabitoreddit"
    assert item["assets"] == ["$AXTI"]
    assert item["evidence"] == ["供应链"]
    assert item["rawText"] == "$AXTI supply chain"
    assert item["translation"] == "AXTI 供应链定价信号"
    assert item["stanceRaw"] == "bullish"
    assert item["importance"] == 5
    assert frontend_style.status_code == 200
    assert frontend_style.json()["items"][0]["stance"] == "多"
    assert filtered_out.status_code == 200
    assert filtered_out.json()["items"] == []


def test_signals_are_sorted_by_published_time_and_return_utc_timestamps() -> None:
    reset_database()
    with SessionLocal.begin() as session:
        newer_post = RawPost(
            platform="x",
            external_id="newer-published",
            published_at=datetime(2026, 7, 13, 10, tzinfo=timezone.utc),
            raw_text="newer post",
        )
        older_post = RawPost(
            platform="x",
            external_id="older-published",
            published_at=datetime(2026, 7, 13, 9, tzinfo=timezone.utc),
            raw_text="older post analyzed later",
        )
        session.add_all([newer_post, older_post])
        session.flush()
        session.add(
            Signal(
                raw_post_id=newer_post.id,
                actionable=False,
                stance="neutral",
                summary="newer",
            )
        )
        session.flush()
        session.add(
            Signal(
                raw_post_id=older_post.id,
                actionable=False,
                stance="neutral",
                summary="older",
            )
        )

    with TestClient(app) as client:
        client.post(
            "/api/auth/login",
            json={"username": "testadmin", "password": "test-admin-password"},
        )
        response = client.get("/api/signals")

    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["summary"] for item in items] == ["newer", "older"]
    assert [item["publishedAt"] for item in items] == [
        "2026-07-13T10:00:00Z",
        "2026-07-13T09:00:00Z",
    ]


def test_collector_health_requires_auth_and_returns_latest_heartbeat() -> None:
    reset_database()
    with SessionLocal.begin() as session:
        session.add(
            CollectorAgent(
                agent_id="home-mac-01",
                version="0.1.0",
                status="healthy",
                providers_json='[{"platform":"x","status":"authenticated"}]',
                outbox_pending=2,
                last_heartbeat_at=datetime(2026, 7, 10, tzinfo=timezone.utc),
            )
        )
    with TestClient(app) as client:
        unauthenticated = client.get("/api/collector-health")
        client.post("/api/auth/login", json={"username": "testadmin", "password": "test-admin-password"})
        response = client.get("/api/collector-health")
    assert unauthenticated.status_code == 401
    assert response.json()["item"] == {
        "agentId": "home-mac-01",
        "status": "healthy",
        "providers": [{"platform": "x", "status": "authenticated"}],
        "outboxPending": 2,
        "lastSeenAt": "2026-07-10T00:00:00Z",
    }
