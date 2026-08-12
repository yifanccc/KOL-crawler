from datetime import UTC, datetime
from decimal import Decimal

from collector_agent.models import ProviderTarget
from collector_agent.trade_models import (
    NormalizedTradeRecord,
    TradeCheckpoint,
    TradeOperation,
    TradePositionSide,
    TradeRecordFetchResult,
)


ACCOUNT_ID = "5075281354358777856"


def checkpoint(record_id: str) -> str:
    return TradeCheckpoint(
        event_time=datetime(2026, 8, 9, 1, int(record_id), tzinfo=UTC),
        record_id=record_id,
    ).encode()


def trade_target() -> ProviderTarget:
    return ProviderTarget(7, "binance_copy", ACCOUNT_ID, "熬鹰资本")


def sample_record(
    record_id: str,
    operation: TradeOperation,
    side: TradePositionSide,
    quantity: str | None,
    *,
    revision: str = "r1",
    observed_minute: int = 0,
    symbol: str = "BTCUSDT",
) -> NormalizedTradeRecord:
    return NormalizedTradeRecord(
        platform="binance_copy",
        account_id=ACCOUNT_ID,
        source_record_id=record_id,
        revision=revision,
        operation=operation,
        symbol=symbol,
        position_side=side,
        quantity=Decimal(quantity) if quantity is not None else None,
        price=Decimal("50000"),
        leverage=Decimal("10"),
        event_time=datetime(2026, 8, 9, 1, int(record_id), tzinfo=UTC),
        observed_at=datetime(2026, 8, 9, 2, observed_minute, tzinfo=UTC),
        source_url=None,
        source_payload={"id": record_id},
    )


def trade_result(
    records: list[NormalizedTradeRecord],
    record_id: str,
    *,
    history_complete: bool = True,
) -> TradeRecordFetchResult:
    return TradeRecordFetchResult(records, checkpoint(record_id), history_complete)
