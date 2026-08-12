import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Callable

import httpx

from collector_agent.models import ProviderTarget
from collector_agent.providers.base import ProviderHealth, TradeHistoryGap
from collector_agent.trade_models import (
    NormalizedTradeRecord,
    TradeCheckpoint,
    TradeOperation,
    TradeRecordFetchResult,
)


BINANCE_COPY_URL = (
    "https://www.binance.com/bapi/futures/v1/friendly/future/"
    "copy-trade/lead-portfolio/order-history"
)
OVERLAP_RECORDS = 100
WINDOW_DAYS = 30
MAX_RESPONSE_BYTES = 2_000_000


class BinanceCopyProvider:
    def __init__(
        self,
        http: httpx.Client | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._owns_http = http is None
        self.http = http or httpx.Client(
            timeout=20,
            follow_redirects=False,
            headers={"User-Agent": "kol-collector-agent/0.1.0"},
        )
        self.now = now or (lambda: datetime.now(UTC))
        self._health = ProviderHealth("healthy")

    def fetch(
        self,
        target: ProviderTarget,
        checkpoint: str | None,
        limit: int,
    ) -> TradeRecordFetchResult:
        del limit  # Binance overlap is fixed by the verified source contract.
        if target.platform != "binance_copy" or target.account_id is None:
            self._health = ProviderHealth("failed", "Binance Copy target is invalid")
            return TradeRecordFetchResult([], checkpoint, history_complete=False)

        observed_at = self.now()
        if observed_at.tzinfo is None:
            self._health = ProviderHealth("failed", "Collector clock is not timezone-aware")
            return TradeRecordFetchResult([], checkpoint, history_complete=False)
        observed_at = observed_at.astimezone(UTC)
        request_payload = {
            "portfolioId": target.account_id,
            "startTime": int((observed_at - timedelta(days=WINDOW_DAYS)).timestamp() * 1000),
            "endTime": int(observed_at.timestamp() * 1000),
            "pageSize": OVERLAP_RECORDS,
        }
        try:
            response = self.http.post(BINANCE_COPY_URL, json=request_payload)
            response.raise_for_status()
        except httpx.HTTPError:
            self._health = ProviderHealth("failed", "Binance Copy request failed")
            return TradeRecordFetchResult([], checkpoint, history_complete=False)
        if len(response.content) > MAX_RESPONSE_BYTES:
            self._health = ProviderHealth("schema_changed", "Binance Copy response is too large")
            return TradeRecordFetchResult([], checkpoint, history_complete=False)
        try:
            payload = json.loads(response.text, parse_float=Decimal)
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._health = ProviderHealth("schema_changed", "Invalid Binance Copy JSON")
            return TradeRecordFetchResult([], checkpoint, history_complete=False)
        if (
            not isinstance(payload, dict)
            or payload.get("code") != "000000"
            or payload.get("success") is not True
        ):
            self._health = ProviderHealth("access_limited", "Binance Copy read was rejected")
            return TradeRecordFetchResult([], checkpoint, history_complete=False)

        try:
            records = self._normalize_response(payload, target, observed_at)
        except (KeyError, TypeError, ValueError):
            self._health = ProviderHealth("schema_changed", "Binance Copy schema changed")
            return TradeRecordFetchResult([], checkpoint, history_complete=False)

        if checkpoint is not None:
            checkpoint_record_id = TradeCheckpoint.decode(checkpoint).record_id
            if checkpoint_record_id not in {
                record.source_record_id for record in records
            }:
                self._health = ProviderHealth(
                    "access_limited", "Binance Copy checkpoint is outside the overlap window"
                )
                raise TradeHistoryGap("Binance Copy checkpoint is outside the overlap window")

        candidate_checkpoint = checkpoint
        if records:
            latest = records[-1]
            candidate_checkpoint = TradeCheckpoint(
                event_time=latest.event_time,
                record_id=latest.source_record_id,
            ).encode()
        self._health = ProviderHealth("healthy")
        return TradeRecordFetchResult(
            records=records,
            candidate_checkpoint=candidate_checkpoint,
            history_complete=False,
        )

    def _normalize_response(
        self,
        payload: dict[str, Any],
        target: ProviderTarget,
        observed_at: datetime,
    ) -> list[NormalizedTradeRecord]:
        data = payload["data"]
        if not isinstance(data, dict):
            raise ValueError("data must be an object")
        rows = data["list"]
        total = data["total"]
        index_value = data["indexValue"]
        if not isinstance(rows, list) or len(rows) > OVERLAP_RECORDS:
            raise ValueError("list must be bounded")
        if isinstance(total, bool) or not isinstance(total, int) or total < len(rows):
            raise ValueError("total must be an integer")
        if not isinstance(index_value, str):
            raise ValueError("indexValue must be a string")
        records = [self._normalize_row(row, target, observed_at) for row in rows]
        records.sort(
            key=lambda record: (
                record.event_time,
                record.source_record_id,
                record.revision,
            )
        )
        return records

    @staticmethod
    def _normalize_row(
        row: Any,
        target: ProviderTarget,
        observed_at: datetime,
    ) -> NormalizedTradeRecord:
        if not isinstance(row, dict):
            raise ValueError("trade row must be an object")
        string_fields = {
            key: row[key]
            for key in (
                "symbol",
                "baseAsset",
                "quoteAsset",
                "side",
                "type",
                "positionSide",
            )
        }
        if any(not isinstance(value, str) or not value for value in string_fields.values()):
            raise ValueError("trade strings are invalid")
        side = string_fields["side"]
        position_side = string_fields["positionSide"]
        if side not in {"BUY", "SELL"} or position_side not in {"LONG", "SHORT"}:
            raise ValueError("trade direction is invalid")

        order_time = row["orderTime"]
        order_update_time = row["orderUpdateTime"]
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
            for value in (order_time, order_update_time)
        ):
            raise ValueError("trade timestamp is invalid")
        executed_qty = _decimal_value(row["executedQty"], positive=True)
        avg_price = _decimal_value(row["avgPrice"], positive=False)
        total_pnl = _decimal_value(row["totalPnl"], positive=False, allow_negative=True)

        operation: TradeOperation = (
            "INCREASE"
            if (side, position_side) in {("BUY", "LONG"), ("SELL", "SHORT")}
            else "DECREASE"
        )
        core = {
            "orderTime": order_time,
            "orderUpdateTime": order_update_time,
            "symbol": string_fields["symbol"],
            "side": side,
            "type": string_fields["type"],
            "positionSide": position_side,
            "executedQty": _decimal_text(executed_qty),
            "avgPrice": _decimal_text(avg_price),
        }
        source_record_id = hashlib.sha256(
            (
                "binance_copy_order_history:v1|"
                + json.dumps(core, separators=(",", ":"), sort_keys=True)
            ).encode()
        ).hexdigest()
        revision_payload = {
            key: core[key]
            for key in (
                "orderUpdateTime",
                "side",
                "positionSide",
                "executedQty",
                "avgPrice",
            )
        }
        revision = hashlib.sha256(
            json.dumps(
                revision_payload, separators=(",", ":"), sort_keys=True
            ).encode()
        ).hexdigest()
        source_payload = {
            **string_fields,
            "executedQty": _decimal_text(executed_qty),
            "avgPrice": _decimal_text(avg_price),
            "totalPnl": _decimal_text(total_pnl),
            "orderUpdateTime": order_update_time,
            "orderTime": order_time,
        }
        return NormalizedTradeRecord(
            platform="binance_copy",
            account_id=target.account_id or "",
            source_record_id=source_record_id,
            revision=revision,
            operation=operation,
            symbol=string_fields["symbol"],
            position_side=position_side,
            quantity=executed_qty,
            price=avg_price,
            leverage=None,
            event_time=_datetime_from_milliseconds(order_update_time),
            observed_at=observed_at,
            source_url=(
                "https://www.binance.com/zh-CN/copy-trading/lead-details/"
                f"{target.account_id}"
            ),
            source_payload=source_payload,
        )

    def health(self) -> ProviderHealth:
        return self._health

    def close(self) -> None:
        if self._owns_http:
            self.http.close()


def _decimal_value(
    value: Any,
    *,
    positive: bool,
    allow_negative: bool = False,
) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        raise ValueError("trade decimal is invalid")
    decimal_value = Decimal(value)
    if positive and decimal_value <= 0:
        raise ValueError("trade decimal must be positive")
    if not positive and not allow_negative and decimal_value < 0:
        raise ValueError("trade decimal cannot be negative")
    return decimal_value


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


def _datetime_from_milliseconds(value: int) -> datetime:
    seconds, milliseconds = divmod(value, 1000)
    return datetime.fromtimestamp(seconds, UTC) + timedelta(milliseconds=milliseconds)
