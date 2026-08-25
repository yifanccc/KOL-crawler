import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from collector_agent.models import ProviderTarget
from collector_agent.providers.base import TradeHistoryGap
from collector_agent.providers.binance_copy import BinanceCopyProvider
from collector_agent.trade_models import TradeCheckpoint


NOW = datetime(2026, 8, 10, tzinfo=UTC)
TARGET = ProviderTarget(21, "binance_copy", "5075281354358777856", "熬鹰资本")
FIXTURE = Path(__file__).parent / "fixtures/binance_copy_trade_records.json"


def fixture_transport(
    payload: dict | None = None, start_at: datetime | None = None
):
    response_payload = payload or json.loads(FIXTURE.read_text())

    def handler(request: httpx.Request) -> httpx.Response:
        assert "authorization" not in request.headers
        assert "cookie" not in request.headers
        if request.url.path.endswith("/order-history"):
            assert request.method == "POST"
            assert json.loads(request.content) == {
                "portfolioId": "5075281354358777856",
                "startTime": int(
                    (start_at or NOW - timedelta(days=30)).timestamp() * 1000
                ),
                "endTime": int(NOW.timestamp() * 1000),
                "pageSize": 100,
            }
            return httpx.Response(200, json=response_payload)
        if request.url.path.endswith("/lead-portfolio/detail"):
            assert request.method == "GET"
            assert dict(request.url.params) == {
                "portfolioId": "5075281354358777856"
            }
            return httpx.Response(
                200,
                json={
                    "code": "000000",
                    "success": True,
                    "data": {
                        "leadPortfolioId": "5075281354358777856",
                        "marginBalance": "137889.65601689",
                    },
                },
            )
        if request.url.path == "/fapi/v1/premiumIndex":
            assert request.method == "GET"
            return httpx.Response(
                200,
                json=[
                    {"symbol": "BTCUSDT", "markPrice": "52000.25"},
                    {"symbol": "ETHUSDT", "markPrice": "3200.5"},
                ],
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    return httpx.MockTransport(handler)


def provider_for(
    payload: dict | None = None, start_at: datetime | None = None
) -> BinanceCopyProvider:
    http = httpx.Client(transport=fixture_transport(payload, start_at))
    return BinanceCopyProvider(http=http, now=lambda: NOW)


def test_binance_copy_provider_maps_fixture_to_stable_normalized_records() -> None:
    provider = provider_for()

    result = provider.fetch(TARGET, None, limit=1)

    assert [record.symbol for record in result.records] == [
        "BTCUSDT",
        "BTCUSDT",
        "ETHUSDT",
    ]
    assert [record.operation for record in result.records] == [
        "INCREASE",
        "DECREASE",
        "INCREASE",
    ]
    assert result.records[0].source_record_id == (
        "9e6edbdc046870e02e98af267a3bba756169524a1708af6f14532b26b3aa2bce"
    )
    assert result.records[0].revision == (
        "7c49b244cb32bced88db24843aa79847db349456efe59653f86f4bacb5b1e195"
    )
    assert result.records[-1].source_record_id == (
        "00bfcc7b403c9b4adb74433913c644000a580fe5ca10d238b2835e1136e68a80"
    )
    assert result.records[0].quantity == Decimal("0.25")
    assert result.records[0].price == Decimal("60000.0")
    assert result.records[0].leverage is None
    assert result.records[0].source_payload["executedQty"] == "0.25"
    assert result.records[0].source_payload["totalPnl"] == "0.0"
    assert result.account_snapshot is not None
    assert result.account_snapshot.margin_balance == Decimal("137889.65601689")
    assert result.account_snapshot.observed_at == NOW
    assert result.mark_prices == {
        "BTCUSDT": Decimal("52000.25"),
        "ETHUSDT": Decimal("3200.5"),
    }
    assert result.history_complete is False
    assert TradeCheckpoint.decode(result.candidate_checkpoint).record_id == (
        result.records[-1].source_record_id
    )
    assert provider.health().status == "healthy"


def test_binance_copy_provider_keeps_checkpoint_for_empty_success() -> None:
    payload = {
        "code": "000000",
        "message": None,
        "messageDetail": None,
        "success": True,
        "data": {"list": [], "total": 0, "indexValue": ""},
    }
    provider = provider_for(payload)

    result = provider.fetch(TARGET, None, limit=5)

    assert result.records == []
    assert result.candidate_checkpoint is None
    assert provider.health().status == "healthy"


def test_binance_copy_provider_does_not_advance_on_schema_or_bapi_failure() -> None:
    malformed = json.loads(FIXTURE.read_text())
    malformed["data"]["list"][0].pop("avgPrice")
    current = TradeCheckpoint(NOW - timedelta(minutes=1), "current").encode()

    schema_provider = provider_for(malformed)
    schema_result = schema_provider.fetch(TARGET, current, limit=5)
    assert schema_result.records == []
    assert schema_result.candidate_checkpoint == current
    assert schema_provider.health().status == "schema_changed"

    failed_provider = provider_for(
        {
            "code": "11012005",
            "message": "busy",
            "messageDetail": None,
            "success": False,
            "data": None,
        }
    )
    failed_result = failed_provider.fetch(TARGET, current, limit=5)
    assert failed_result.records == []
    assert failed_result.candidate_checkpoint == current
    assert failed_provider.health().status == "access_limited"


def test_binance_copy_provider_does_not_advance_on_network_failure() -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    provider = BinanceCopyProvider(
        http=httpx.Client(transport=httpx.MockTransport(fail)),
        now=lambda: NOW,
    )
    current = TradeCheckpoint(NOW - timedelta(minutes=1), "current").encode()

    result = provider.fetch(TARGET, current, limit=5)

    assert result.records == []
    assert result.candidate_checkpoint == current
    assert provider.health().status == "failed"


def test_binance_copy_provider_requires_old_checkpoint_in_overlap_window() -> None:
    provider = provider_for()
    missing = TradeCheckpoint(NOW - timedelta(minutes=1), "missing-record").encode()

    with pytest.raises(TradeHistoryGap):
        provider.fetch(TARGET, missing, limit=5)

    assert provider.health().status == "access_limited"


def test_binance_copy_provider_accepts_checkpoint_present_in_overlap_window() -> None:
    provider = provider_for()
    baseline = provider.fetch(TARGET, None, limit=5)

    update = provider.fetch(TARGET, baseline.candidate_checkpoint, limit=5)

    assert update.candidate_checkpoint == baseline.candidate_checkpoint
    assert provider.health().status == "healthy"


def test_binance_copy_provider_uses_cutoff_filters_old_rows_and_marks_complete() -> None:
    position_start_at = datetime(2026, 8, 9, 3, tzinfo=UTC)
    payload = json.loads(FIXTURE.read_text())
    payload["data"]["total"] = len(payload["data"]["list"])
    provider = provider_for(payload, start_at=position_start_at)

    result = provider.fetch(
        replace(TARGET, position_start_at=position_start_at), None, limit=1
    )

    assert [record.event_time for record in result.records] == [
        datetime(2026, 8, 9, 3, tzinfo=UTC),
        datetime(2026, 8, 9, 4, tzinfo=UTC),
    ]
    assert result.history_complete is True
    assert provider.health().status == "healthy"


def test_binance_copy_provider_refuses_truncated_cutoff_history() -> None:
    position_start_at = datetime(2026, 8, 8, tzinfo=UTC)
    provider = provider_for(start_at=position_start_at)

    with pytest.raises(TradeHistoryGap, match="exceeds one page"):
        provider.fetch(
            replace(TARGET, position_start_at=position_start_at), None, limit=1
        )

    assert provider.health().status == "access_limited"


def test_binance_copy_provider_does_not_fetch_before_cutoff() -> None:
    def unexpected(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    provider = BinanceCopyProvider(
        http=httpx.Client(transport=httpx.MockTransport(unexpected)),
        now=lambda: NOW,
    )
    result = provider.fetch(
        replace(TARGET, position_start_at=NOW + timedelta(minutes=1)),
        None,
        limit=1,
    )

    assert result.records == []
    assert result.history_complete is True
    assert provider.health().status == "healthy"
