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


def valued_position_payload() -> dict:
    return {
        **position_payload("0.11"),
        "positionSide": "LONG",
        "side": "LONG",
        "entryPrice": "51000",
        "currentPrice": "52000",
        "notional": "5720.00",
        "leverage": "10",
        "positionMargin": "572.00",
        "estimatedPnl": "110.00",
        "priceUpdatedAt": "2026-08-12T15:08:00Z",
    }


def operation_payload(record_id: str, action: str, minute: int) -> dict:
    quantity = "0.10" if record_id == "1" else "0.05"
    price = "50000" if record_id == "1" else "53000"
    return {
        "sourceRecordId": record_id,
        "revision": "r1",
        "action": action,
        "effectiveAction": "INCREASE",
        "symbol": "BTCUSDT",
        "positionSide": "LONG",
        "quantity": quantity,
        "price": price,
        "amount": str(float(quantity) * float(price)),
        "leverage": "10",
        "realizedPnl": "0",
        "eventTime": f"2026-08-12T15:{minute:02d}:00Z",
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


def test_position_monitor_exposes_one_kol_summary_positions_and_paginated_operations() -> None:
    reset_database()
    with TestClient(app) as client:
        headers = auth_headers(client)
        subscription_id = create_trade_subscription(client, headers)
        upload = client.put(
            f"/api/v1/collector/subscriptions/{subscription_id}/positions",
            headers=COLLECTOR_HEADERS,
            json={
                "agentId": "home-mac-01",
                "account": {
                    "marginBalance": "137889.65",
                    "updatedAt": "2026-08-12T15:08:00Z",
                },
                "positions": [valued_position_payload()],
                "operations": [
                    operation_payload("1", "OPEN", 1),
                    operation_payload("2", "ADD", 2),
                ],
            },
        )
        summaries = client.get("/api/position-kols", headers=headers)
        detail = client.get(
            f"/api/position-kols/{subscription_id}", headers=headers
        )
        operations = client.get(
            f"/api/position-kols/{subscription_id}/operations?limit=1&offset=0",
            headers=headers,
        )

    assert upload.status_code == 200
    assert upload.json() == {"count": 1, "operationCount": 2}
    assert summaries.status_code == 200
    summary = summaries.json()["items"][0]
    assert summary == {
        "subscriptionId": subscription_id,
        "kol": {"id": summary["kol"]["id"], "displayName": "熬鹰资本"},
        "platform": "binance_copy",
        "accountId": "5075281354358777856",
        "marginBalance": "137889.65",
        "totalPositionNotional": "5720.00",
        "positionMargin": "572.00",
        "estimatedPnl": "110.00",
        "effectiveLeverage": "10",
        "activePositionCount": 1,
        "uncertainPositionCount": 0,
        "metricsStatus": "COMPLETE",
        "updatedAt": "2026-08-12T15:08:00Z",
    }
    assert detail.status_code == 200
    assert detail.json()["item"]["summary"] == summary
    assert detail.json()["item"]["positions"] == [
        {
            "symbol": "BTCUSDT",
            "positionSide": "LONG",
            "side": "LONG",
            "quantity": "0.11",
            "entryPrice": "51000",
            "currentPrice": "52000",
            "notional": "5720.00",
            "leverage": "10",
            "positionMargin": "572.00",
            "estimatedPnl": "110.00",
            "confidence": "LOW",
            "status": "ACTIVE",
            "asOfEventTime": "2026-08-12T15:07:01Z",
            "priceUpdatedAt": "2026-08-12T15:08:00Z",
            "staleSince": None,
            "updatedAt": "2026-08-12T15:07:01Z",
        }
    ]
    assert operations.status_code == 200
    assert operations.json() == {
        "items": [operation_payload("2", "ADD", 2)],
        "total": 2,
        "limit": 1,
        "offset": 0,
    }


def test_position_summary_marks_partial_metrics_when_inferred_rows_are_unknown() -> None:
    reset_database()
    with TestClient(app) as client:
        headers = auth_headers(client)
        subscription_id = create_trade_subscription(client, headers)
        upload = client.put(
            f"/api/v1/collector/subscriptions/{subscription_id}/positions",
            headers=COLLECTOR_HEADERS,
            json={
                "agentId": "home-mac-01",
                "positions": [
                    {
                        **position_payload(),
                        "side": "UNKNOWN",
                        "quantity": None,
                        "confidence": "UNKNOWN",
                        "status": "UNKNOWN",
                    }
                ],
            },
        )
        response = client.get("/api/position-kols", headers=headers)

    assert upload.status_code == 200
    item = response.json()["items"][0]
    assert item["activePositionCount"] == 0
    assert item["uncertainPositionCount"] == 1
    assert item["totalPositionNotional"] is None
    assert item["estimatedPnl"] is None
    assert item["metricsStatus"] == "UNKNOWN"


def test_position_summary_preserves_last_estimate_when_provider_marks_it_stale() -> None:
    reset_database()
    with TestClient(app) as client:
        headers = auth_headers(client)
        subscription_id = create_trade_subscription(client, headers)
        stale_position = {
            **valued_position_payload(),
            "status": "STALE",
            "staleSince": "2026-08-12T15:09:00Z",
        }
        upload = client.put(
            f"/api/v1/collector/subscriptions/{subscription_id}/positions",
            headers=COLLECTOR_HEADERS,
            json={"agentId": "home-mac-01", "positions": [stale_position]},
        )
        response = client.get("/api/position-kols", headers=headers)

    assert upload.status_code == 200
    item = response.json()["items"][0]
    assert item["activePositionCount"] == 1
    assert item["uncertainPositionCount"] == 1
    assert item["totalPositionNotional"] == "5720.00"
    assert item["estimatedPnl"] == "110.00"
    assert item["metricsStatus"] == "PARTIAL"
