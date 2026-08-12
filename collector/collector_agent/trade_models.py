import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal


TradeOperation = Literal[
    "INCREASE",
    "DECREASE",
    "OPEN",
    "ADD",
    "REDUCE",
    "CLOSE",
    "REVERSE",
]
TradeEventAction = Literal["OPEN", "ADD", "REDUCE", "CLOSE", "REVERSE", "CORRECTION"]
TradePositionSide = Literal["LONG", "SHORT", "UNKNOWN"]
EstimatedPositionSide = Literal["LONG", "SHORT", "FLAT", "UNKNOWN"]
PositionConfidence = Literal["HIGH", "MEDIUM", "LOW", "UNKNOWN"]
PositionStatus = Literal["ACTIVE", "FLAT", "UNKNOWN", "STALE"]
PositionKey = tuple[str, TradePositionSide]


@dataclass(frozen=True)
class TradeCheckpoint:
    event_time: datetime
    record_id: str

    def encode(self) -> str:
        return json.dumps(
            {
                "v": 1,
                "eventTime": self.event_time.astimezone(UTC)
                .isoformat()
                .replace("+00:00", "Z"),
                "recordId": self.record_id,
            },
            separators=(",", ":"),
            sort_keys=True,
        )

    @classmethod
    def decode(cls, value: str) -> "TradeCheckpoint":
        try:
            payload = json.loads(value)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ValueError("invalid trade checkpoint") from exc
        if not isinstance(payload, dict) or payload.get("v") != 1:
            raise ValueError("unsupported trade checkpoint version")
        try:
            event_time = datetime.fromisoformat(
                str(payload["eventTime"]).replace("Z", "+00:00")
            )
            record_id = str(payload["recordId"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("invalid trade checkpoint") from exc
        if event_time.tzinfo is None or not record_id:
            raise ValueError("invalid trade checkpoint")
        return cls(event_time=event_time, record_id=record_id)


@dataclass(frozen=True)
class NormalizedTradeRecord:
    platform: str
    account_id: str
    source_record_id: str
    revision: str
    operation: TradeOperation
    symbol: str
    position_side: TradePositionSide
    quantity: Decimal | None
    price: Decimal | None
    leverage: Decimal | None
    event_time: datetime
    observed_at: datetime
    source_url: str | None
    source_payload: dict[str, Any]


@dataclass(frozen=True)
class PositionEstimate:
    symbol: str
    position_side: TradePositionSide
    side: EstimatedPositionSide
    quantity: Decimal | None
    confidence: PositionConfidence
    status: PositionStatus
    as_of_event_time: datetime | None
    stale_since: datetime | None = None


@dataclass(frozen=True)
class TradeEvent:
    record: NormalizedTradeRecord
    action: TradeEventAction
    position_after: PositionEstimate


@dataclass(frozen=True)
class Reconciliation:
    events: list[TradeEvent]
    positions: dict[PositionKey, PositionEstimate]

    def position_for(
        self, symbol: str, position_side: TradePositionSide
    ) -> PositionEstimate:
        return self.positions[(symbol, position_side)]


@dataclass(frozen=True)
class TradeRecordFetchResult:
    records: list[NormalizedTradeRecord]
    candidate_checkpoint: str | None
    history_complete: bool
    kind: Literal["trade_records"] = "trade_records"
