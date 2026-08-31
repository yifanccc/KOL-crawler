from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.db.base import Base
from app.db.session import engine
from app.main import app
from app.models import CollectorAgent, Subscription


COLLECTOR_HEADERS = {"Authorization": "Bearer collector-test-token"}


def reset_database() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def test_collector_and_dashboard_authentication_are_isolated() -> None:
    reset_database()
    with TestClient(app) as client:
        login = client.post(
            "/api/auth/login",
            json={"username": "testadmin", "password": "test-admin-password"},
        )
        cookie_only = client.get("/api/v1/collector/config")
        collector_dashboard = client.get("/api/signals", headers=COLLECTOR_HEADERS)

    assert login.status_code == 200
    assert cookie_only.status_code == 401
    assert collector_dashboard.status_code == 401


def test_collector_config_limits_fields_and_heartbeat_replaces_latest_state() -> None:
    reset_database()
    with engine.begin() as connection:
        connection.execute(
            Subscription.__table__.insert(),
            {
                "platform": "x",
                "platform_handle": "senerity",
                "interval_minutes": 1,
                "enabled": True,
                "system_prompt": "private prompt",
                "user_prompt": "private user prompt",
                "output_schema_json": '{"private": true}',
            },
        )
        connection.execute(
            Subscription.__table__.insert(),
            {
                "platform": "binance_copy",
                "platform_account_id": "5075281354358777856",
                "platform_handle": "熬鹰资本",
                "visibility": "private",
                "position_start_at": datetime(2026, 8, 18, 16, tzinfo=UTC),
                "interval_minutes": 1,
                "enabled": True,
            },
        )

    heartbeat = {
        "agentId": "home-mac-01",
        "version": "0.1.0",
        "status": "healthy",
        "providers": [{"platform": "x", "status": "authenticated", "message": None}],
        "outboxPending": 2,
        "checkedAt": "2026-07-10T10:21:00Z",
    }
    with TestClient(app) as client:
        config = client.get("/api/v1/collector/config", headers=COLLECTOR_HEADERS)
        first = client.post("/api/v1/collector/heartbeat", headers=COLLECTOR_HEADERS, json=heartbeat)
        heartbeat["outboxPending"] = 0
        heartbeat["status"] = "degraded"
        second = client.post("/api/v1/collector/heartbeat", headers=COLLECTOR_HEADERS, json=heartbeat)
        mismatched = client.post(
            "/api/v1/collector/heartbeat",
            headers=COLLECTOR_HEADERS,
            json={**heartbeat, "agentId": "other-machine"},
        )

    assert config.status_code == 200
    assert config.json()["agentId"] == "home-mac-01"
    assert config.json()["pollSeconds"] == 60
    subscriptions = config.json()["subscriptions"]
    assert all(
        set(subscription)
        == {
            "id",
            "platform",
            "handle",
            "accountId",
            "positionStartAt",
            "intervalMinutes",
            "enabled",
        }
        for subscription in subscriptions
    )
    trade_target = next(
        subscription
        for subscription in subscriptions
        if subscription["platform"] == "binance_copy"
    )
    assert trade_target["accountId"] == "5075281354358777856"
    assert trade_target["positionStartAt"] == "2026-08-18T16:00:00+00:00"
    assert trade_target["intervalMinutes"] == 1
    regular_target = next(
        subscription for subscription in subscriptions if subscription["platform"] == "x"
    )
    assert regular_target["accountId"] is None
    assert regular_target["positionStartAt"] is None
    assert regular_target["intervalMinutes"] == 1
    assert regular_target["enabled"] is True
    assert first.status_code == 200
    assert second.status_code == 200
    assert mismatched.status_code == 403
    with engine.connect() as connection:
        row = connection.execute(CollectorAgent.__table__.select()).one()
    assert row.agent_id == "home-mac-01"
    assert row.status == "degraded"
    assert row.outbox_pending == 0
