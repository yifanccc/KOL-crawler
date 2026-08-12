from fastapi.testclient import TestClient

from app.db.base import Base
from app.db.session import engine
from app.main import app


COLLECTOR_HEADERS = {"Authorization": "Bearer collector-test-token"}


def reset_database() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def auth_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"username": "testadmin", "password": "test-admin-password"},
    )
    return {"Authorization": f"Bearer {response.json()['accessToken']}"}


def create_trade_subscription(client: TestClient, headers: dict[str, str]) -> int:
    response = client.post(
        "/api/admin/subscriptions",
        headers=headers,
        json={
            "platform": "binance_copy",
            "handle": "熬鹰资本",
            "accountId": "5075281354358777856",
        },
    )
    assert response.status_code == 200
    return response.json()["item"]["id"]


def position_payload(quantity: str = "10.43100000") -> dict:
    return {
        "symbol": "BTCUSDT",
        "positionSide": "SHORT",
        "side": "SHORT",
        "quantity": quantity,
        "confidence": "LOW",
        "status": "ACTIVE",
        "asOfEventTime": "2026-08-12T15:07:01Z",
        "staleSince": None,
        "updatedAt": "2026-08-12T15:07:01Z",
    }


def test_collector_replaces_current_positions_and_dashboard_reads_them() -> None:
    reset_database()
    with TestClient(app) as client:
        headers = auth_headers(client)
        subscription_id = create_trade_subscription(client, headers)
        first = client.put(
            f"/api/v1/collector/subscriptions/{subscription_id}/positions",
            headers=COLLECTOR_HEADERS,
            json={
                "agentId": "home-mac-01",
                "positions": [
                    position_payload(),
                    {
                        **position_payload("0"),
                        "symbol": "ETHUSDT",
                        "positionSide": "LONG",
                        "side": "FLAT",
                        "confidence": "LOW",
                        "status": "FLAT",
                    },
                ],
            },
        )
        replacement = client.put(
            f"/api/v1/collector/subscriptions/{subscription_id}/positions",
            headers=COLLECTOR_HEADERS,
            json={
                "agentId": "home-mac-01",
                "positions": [position_payload("9.75000000")],
            },
        )
        dashboard = client.get("/api/positions", headers=headers)

    assert first.status_code == 200
    assert first.json() == {"count": 2}
    assert replacement.status_code == 200
    assert replacement.json() == {"count": 1}
    assert dashboard.status_code == 200
    kol_id = dashboard.json()["items"][0]["kol"]["id"]
    assert isinstance(kol_id, int)
    assert dashboard.json() == {
        "items": [
            {
                "subscriptionId": subscription_id,
                "kol": {"id": kol_id, "displayName": "熬鹰资本"},
                "platform": "binance_copy",
                "accountId": "5075281354358777856",
                **position_payload("9.75000000"),
            }
        ]
    }


def test_positions_require_login_and_reject_invalid_or_non_trade_snapshots() -> None:
    reset_database()
    with TestClient(app) as client:
        headers = auth_headers(client)
        trade_subscription_id = create_trade_subscription(client, headers)
        content_subscription = client.post(
            "/api/admin/subscriptions",
            headers=headers,
            json={"platform": "x", "handle": "content-only"},
        ).json()["item"]["id"]
        invalid = client.put(
            f"/api/v1/collector/subscriptions/{trade_subscription_id}/positions",
            headers=COLLECTOR_HEADERS,
            json={
                "agentId": "home-mac-01",
                "positions": [position_payload("-1")],
            },
        )
        wrong_platform = client.put(
            f"/api/v1/collector/subscriptions/{content_subscription}/positions",
            headers=COLLECTOR_HEADERS,
            json={"agentId": "home-mac-01", "positions": []},
        )
    with TestClient(app) as anonymous:
        unauthenticated = anonymous.get("/api/positions")

    assert invalid.status_code == 422
    assert wrong_platform.status_code == 404
    assert unauthenticated.status_code == 401
