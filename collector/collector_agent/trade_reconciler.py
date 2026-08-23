import hashlib
import json
from decimal import Decimal
from typing import Any

from collector_agent.models import CollectedPost, ProviderTarget
from collector_agent.trade_models import (
    NormalizedTradeRecord,
    PositionEstimate,
    PositionKey,
    Reconciliation,
    TradeEvent,
    TradeEventAction,
    TradePositionSide,
)


def _confidence(quantity: Decimal | None, history_complete: bool) -> str:
    if not history_complete:
        return "LOW"
    return "HIGH" if quantity is not None else "MEDIUM"


def _active_position(
    record: NormalizedTradeRecord,
    quantity: Decimal | None,
    history_complete: bool,
    entry_price: Decimal | None,
    leverage: Decimal | None,
) -> PositionEstimate:
    if record.position_side not in {"LONG", "SHORT"}:
        return _unknown_position(record)
    return PositionEstimate(
        symbol=record.symbol,
        position_side=record.position_side,
        side=record.position_side,
        quantity=quantity,
        confidence=_confidence(quantity, history_complete),
        status="ACTIVE",
        as_of_event_time=record.event_time,
        entry_price=entry_price,
        leverage=leverage,
    )


def _flat_position(
    record: NormalizedTradeRecord, history_complete: bool
) -> PositionEstimate:
    return PositionEstimate(
        symbol=record.symbol,
        position_side=record.position_side,
        side="FLAT",
        quantity=Decimal("0"),
        confidence="HIGH" if history_complete else "LOW",
        status="FLAT",
        as_of_event_time=record.event_time,
    )


def _unknown_position(record: NormalizedTradeRecord) -> PositionEstimate:
    return PositionEstimate(
        symbol=record.symbol,
        position_side=record.position_side,
        side="UNKNOWN",
        quantity=None,
        confidence="UNKNOWN",
        status="UNKNOWN",
        as_of_event_time=record.event_time,
    )


def _position_key(record: NormalizedTradeRecord) -> PositionKey:
    return (record.symbol, record.position_side)


def _weighted_entry_price(
    current: PositionEstimate,
    record: NormalizedTradeRecord,
) -> Decimal | None:
    if (
        current.quantity is None
        or current.entry_price is None
        or record.quantity is None
        or record.price is None
    ):
        return None
    new_quantity = current.quantity + record.quantity
    if new_quantity <= 0:
        return None
    return (
        current.quantity * current.entry_price + record.quantity * record.price
    ) / new_quantity


def _apply_record(
    record: NormalizedTradeRecord,
    positions: dict[PositionKey, PositionEstimate],
    history_complete: bool,
) -> tuple[TradeEventAction, PositionEstimate]:
    key = _position_key(record)
    current = positions.get(key)

    if record.operation == "OPEN":
        position = _active_position(
            record,
            record.quantity,
            history_complete,
            record.price,
            record.leverage,
        )
        action: TradeEventAction = "OPEN"
    elif record.operation in {"ADD", "INCREASE"}:
        if current is None or current.status == "FLAT":
            if record.operation == "ADD" and current is None:
                position = _unknown_position(record)
                action = "ADD"
            else:
                position = _active_position(
                    record,
                    record.quantity,
                    history_complete,
                    record.price,
                    record.leverage,
                )
                action = "OPEN"
        elif current.status != "ACTIVE" or current.side != record.position_side:
            position = _unknown_position(record)
            action = "ADD"
        else:
            quantity = (
                current.quantity + record.quantity
                if current.quantity is not None and record.quantity is not None
                else None
            )
            position = _active_position(
                record,
                quantity,
                history_complete,
                _weighted_entry_price(current, record),
                record.leverage if record.leverage is not None else current.leverage,
            )
            action = "ADD"
    elif record.operation in {"REDUCE", "DECREASE"}:
        action = "REDUCE"
        if current is None or current.status != "ACTIVE":
            position = _unknown_position(record)
        elif current.quantity is None or record.quantity is None:
            position = _active_position(
                record,
                None,
                history_complete,
                current.entry_price,
                current.leverage,
            )
        elif record.quantity > current.quantity:
            position = _unknown_position(record)
        elif record.quantity == current.quantity:
            position = _flat_position(record, history_complete)
            action = "CLOSE"
        else:
            position = _active_position(
                record,
                current.quantity - record.quantity,
                history_complete,
                current.entry_price,
                current.leverage,
            )
    elif record.operation == "CLOSE":
        position = _flat_position(record, history_complete)
        action = "CLOSE"
    elif record.operation == "REVERSE":
        opposite_keys = [
            position_key
            for position_key, estimate in positions.items()
            if position_key[0] == record.symbol
            and position_key != key
            and estimate.status == "ACTIVE"
        ]
        if record.position_side not in {"LONG", "SHORT"} or not opposite_keys:
            position = _unknown_position(record)
        else:
            for opposite_key in opposite_keys:
                opposite = positions[opposite_key]
                positions[opposite_key] = PositionEstimate(
                    symbol=opposite.symbol,
                    position_side=opposite.position_side,
                    side="FLAT",
                    quantity=Decimal("0"),
                    confidence="HIGH" if history_complete else "LOW",
                    status="FLAT",
                    as_of_event_time=record.event_time,
                )
            position = _active_position(
                record,
                record.quantity,
                history_complete,
                record.price,
                record.leverage,
            )
        action = "REVERSE"
    else:
        raise ValueError(f"unsupported trade operation: {record.operation}")

    positions[key] = position
    return action, position


def reconcile_records(
    records: list[NormalizedTradeRecord], history_complete: bool
) -> Reconciliation:
    revisions: dict[str, list[NormalizedTradeRecord]] = {}
    for record in records:
        revisions.setdefault(record.source_record_id, []).append(record)

    effective_records: list[tuple[NormalizedTradeRecord, bool]] = []
    for group in revisions.values():
        selected = max(group, key=lambda item: (item.observed_at, item.revision))
        corrected = len({item.revision for item in group}) > 1
        effective_records.append((selected, corrected))
    effective_records.sort(
        key=lambda item: (
            item[0].event_time,
            item[0].source_record_id,
            item[0].revision,
        )
    )

    positions: dict[PositionKey, PositionEstimate] = {}
    events: list[TradeEvent] = []
    for record, corrected in effective_records:
        action, position_after = _apply_record(record, positions, history_complete)
        events.append(
            TradeEvent(
                record=record,
                action="CORRECTION" if corrected else action,
                position_after=position_after,
            )
        )
    return Reconciliation(events=events, positions=positions)


def _decimal_text(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None


def _ensure_json_safe(value: Any) -> None:
    if value is None or isinstance(value, (str, int, bool)):
        return
    if isinstance(value, list):
        for item in value:
            _ensure_json_safe(item)
        return
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        for item in value.values():
            _ensure_json_safe(item)
        return
    raise ValueError("sourceRecord must contain JSON-safe values")


def build_collected_post(
    target: ProviderTarget,
    event: TradeEvent,
    *,
    batch_id: str | None = None,
    batch_size: int | None = None,
    position_changes: list[dict[str, Any]] | None = None,
) -> CollectedPost:
    record = event.record
    if target.platform != record.platform or target.account_id != record.account_id:
        raise ValueError("trade target does not match normalized record")
    _ensure_json_safe(record.source_payload)

    position = event.position_after
    raw_payload = {
        "schemaVersion": 2 if batch_id is not None else 1,
        "platform": record.platform,
        "accountId": record.account_id,
        "sourceRecordId": record.source_record_id,
        "revision": record.revision,
        "action": event.action,
        "effectiveAction": record.operation,
        "symbol": record.symbol,
        "positionSide": record.position_side,
        "quantity": _decimal_text(record.quantity),
        "price": _decimal_text(record.price),
        "leverage": _decimal_text(record.leverage),
        "eventTime": record.event_time.isoformat(),
        "positionAfter": {
            "side": position.side,
            "quantity": _decimal_text(position.quantity),
            "entryPrice": _decimal_text(position.entry_price),
            "leverage": _decimal_text(position.leverage),
            "confidence": position.confidence,
            "status": position.status,
        },
        "sourceRecord": record.source_payload,
    }
    if batch_id is not None:
        if batch_size is None or batch_size <= 0 or position_changes is None:
            raise ValueError("trade batch metadata is incomplete")
        _ensure_json_safe(position_changes)
        raw_payload.update(
            {
                "collectionBatchId": batch_id,
                "collectionBatchSize": batch_size,
                "positionChanges": position_changes,
            }
        )
    canonical_payload = json.dumps(
        raw_payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    action_labels = {
        "OPEN": "开仓",
        "ADD": "加仓",
        "REDUCE": "减仓",
        "CLOSE": "平仓",
        "REVERSE": "反手",
        "CORRECTION": "交易修订",
    }
    side_labels = {"LONG": "多头", "SHORT": "空头", "FLAT": "空仓", "UNKNOWN": "未知"}
    raw_content = (
        f"{target.handle} {record.symbol} {action_labels[event.action]}"
        f" {side_labels.get(record.position_side, '未知')}"
        f"，成交数量 {_decimal_text(record.quantity) or '未知'}"
        f"，成交均价 {_decimal_text(record.price) or '未知'}；"
        f"推测持仓 {side_labels[position.side]} "
        f"{_decimal_text(position.quantity) or '数量未知'}"
        f"（置信度 {position.confidence}）"
    )
    source_url = record.source_url or (
        "https://www.binance.com/zh-CN/copy-trading/lead-details/"
        f"{record.account_id}"
    )
    return CollectedPost(
        platform=record.platform,
        external_id=(
            f"{record.account_id}:{record.source_record_id}:{record.revision}"
        ),
        author_handle=target.handle,
        author_name=target.handle,
        author_avatar_url=None,
        published_at=record.event_time,
        url=source_url,
        raw_content=raw_content,
        raw_payload=raw_payload,
        content_hash=hashlib.sha256(canonical_payload.encode()).hexdigest(),
    )
