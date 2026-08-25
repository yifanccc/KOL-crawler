import hashlib
import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

from collector_agent.models import ProviderTarget, collected_post_payload
from collector_agent.trade_models import (
    NormalizedTradeRecord,
    PositionEstimate,
    TradeCheckpoint,
    TradePositionSide,
    TradeRecordFetchResult,
)
from collector_agent.trade_reconciler import build_collected_post, reconcile_records


def initialize_trade_store(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS trade_events (
          id INTEGER PRIMARY KEY,
          subscription_id INTEGER NOT NULL,
          source_record_id TEXT NOT NULL,
          revision TEXT NOT NULL,
          event_time TEXT NOT NULL,
          first_observed_at TEXT NOT NULL,
          last_observed_at TEXT NOT NULL,
          normalized_json TEXT NOT NULL,
          UNIQUE(subscription_id, source_record_id, revision)
        );
        CREATE TABLE IF NOT EXISTS position_estimates (
          subscription_id INTEGER NOT NULL,
          symbol TEXT NOT NULL,
          position_side TEXT NOT NULL,
          side TEXT NOT NULL,
          quantity TEXT,
          entry_price TEXT,
          mark_price TEXT,
          notional TEXT,
          leverage TEXT,
          position_margin TEXT,
          estimated_pnl TEXT,
          price_updated_at TEXT,
          confidence TEXT NOT NULL,
          status TEXT NOT NULL,
          as_of_event_time TEXT,
          stale_since TEXT,
          updated_at TEXT NOT NULL,
          PRIMARY KEY(subscription_id, symbol, position_side)
        );
        CREATE TABLE IF NOT EXISTS trade_account_snapshots (
          subscription_id INTEGER PRIMARY KEY,
          margin_balance TEXT,
          updated_at TEXT NOT NULL
        );
        """
    )
    existing_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(position_estimates)")
    }
    for column in (
        "entry_price",
        "mark_price",
        "notional",
        "leverage",
        "position_margin",
        "estimated_pnl",
        "price_updated_at",
    ):
        if column not in existing_columns:
            connection.execute(
                f"ALTER TABLE position_estimates ADD COLUMN {column} TEXT"
            )


def _datetime_text(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("trade timestamps must be timezone-aware")
    return value.astimezone(UTC).isoformat()


def _parse_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _decimal_text(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None


def _position_from_row(row: sqlite3.Row) -> PositionEstimate:
    return PositionEstimate(
        symbol=row["symbol"],
        position_side=row["position_side"],
        side=row["side"],
        quantity=Decimal(row["quantity"]) if row["quantity"] is not None else None,
        entry_price=(
            Decimal(row["entry_price"]) if row["entry_price"] is not None else None
        ),
        leverage=Decimal(row["leverage"]) if row["leverage"] is not None else None,
        confidence=row["confidence"],
        status=row["status"],
        as_of_event_time=_parse_datetime(row["as_of_event_time"]),
    )


def _missing_position(symbol: str, position_side: TradePositionSide) -> PositionEstimate:
    return PositionEstimate(
        symbol=symbol,
        position_side=position_side,
        side="FLAT",
        quantity=Decimal("0"),
        confidence="HIGH",
        status="FLAT",
        as_of_event_time=None,
    )


def _position_signature(position: PositionEstimate) -> tuple:
    return (
        position.side,
        position.quantity,
        position.entry_price,
        position.leverage,
    )


def _position_state_payload(position: PositionEstimate) -> dict:
    return {
        "side": position.side,
        "quantity": _decimal_text(position.quantity),
        "entryPrice": _decimal_text(position.entry_price),
        "leverage": _decimal_text(position.leverage),
        "confidence": position.confidence,
        "status": position.status,
    }


def _position_changes(
    before: dict[tuple[str, TradePositionSide], PositionEstimate],
    after: dict[tuple[str, TradePositionSide], PositionEstimate],
) -> list[dict]:
    changes = []
    for symbol, position_side in sorted(set(before) | set(after)):
        previous = before.get((symbol, position_side)) or _missing_position(
            symbol, position_side
        )
        current = after.get((symbol, position_side)) or _missing_position(
            symbol, position_side
        )
        if _position_signature(previous) == _position_signature(current):
            continue
        changes.append(
            {
                "symbol": symbol,
                "positionSide": position_side,
                "before": _position_state_payload(previous),
                "after": _position_state_payload(current),
            }
        )
    return changes


def _batch_id(target: ProviderTarget, events) -> str:
    identity = {
        "platform": target.platform,
        "accountId": target.account_id,
        "records": [
            [event.record.source_record_id, event.record.revision] for event in events
        ],
    }
    encoded = json.dumps(identity, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _canonical_record(record: NormalizedTradeRecord) -> str:
    payload = {
        "platform": record.platform,
        "accountId": record.account_id,
        "sourceRecordId": record.source_record_id,
        "revision": record.revision,
        "operation": record.operation,
        "symbol": record.symbol,
        "positionSide": record.position_side,
        "quantity": _decimal_text(record.quantity),
        "price": _decimal_text(record.price),
        "leverage": _decimal_text(record.leverage),
        "eventTime": _datetime_text(record.event_time),
        "sourceUrl": record.source_url,
        "sourcePayload": record.source_payload,
    }
    try:
        return json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("normalized trade record is not JSON-safe") from exc


def _value_position(
    position: PositionEstimate,
    mark_price: Decimal | None,
    price_updated_at: datetime | None,
) -> PositionEstimate:
    if (
        position.status != "ACTIVE"
        or position.quantity is None
        or mark_price is None
    ):
        return replace(
            position,
            mark_price=mark_price,
            price_updated_at=price_updated_at,
        )
    notional = abs(position.quantity * mark_price)
    estimated_pnl = None
    if position.entry_price is not None:
        price_delta = (
            mark_price - position.entry_price
            if position.side == "LONG"
            else position.entry_price - mark_price
        )
        estimated_pnl = price_delta * position.quantity
    position_margin = None
    if position.leverage is not None and position.leverage > 0:
        position_margin = notional / position.leverage
    return replace(
        position,
        mark_price=mark_price,
        notional=notional,
        position_margin=position_margin,
        estimated_pnl=estimated_pnl,
        price_updated_at=price_updated_at,
    )


def _record_from_row(row: sqlite3.Row) -> NormalizedTradeRecord:
    payload = json.loads(row["normalized_json"])
    return NormalizedTradeRecord(
        platform=payload["platform"],
        account_id=payload["accountId"],
        source_record_id=payload["sourceRecordId"],
        revision=payload["revision"],
        operation=payload["operation"],
        symbol=payload["symbol"],
        position_side=payload["positionSide"],
        quantity=Decimal(payload["quantity"]) if payload["quantity"] is not None else None,
        price=Decimal(payload["price"]) if payload["price"] is not None else None,
        leverage=Decimal(payload["leverage"])
        if payload["leverage"] is not None
        else None,
        event_time=datetime.fromisoformat(payload["eventTime"]),
        observed_at=datetime.fromisoformat(row["last_observed_at"]),
        source_url=payload["sourceUrl"],
        source_payload=payload["sourcePayload"],
    )


def _checkpoint_order(value: str) -> tuple[datetime, str]:
    checkpoint = TradeCheckpoint.decode(value)
    return checkpoint.event_time.astimezone(UTC), checkpoint.record_id


def _validate_fetch(
    subscription_id: int,
    target: ProviderTarget,
    result: TradeRecordFetchResult,
    checkpoint_before: str | None,
) -> None:
    if target.subscription_id != subscription_id or target.account_id is None:
        raise ValueError("trade target does not match subscription")
    position_start_at = target.position_start_at
    if position_start_at is not None:
        if position_start_at.tzinfo is None:
            raise ValueError("position start time must be timezone-aware")
        position_start_at = position_start_at.astimezone(UTC)
    for record in result.records:
        if record.platform != target.platform or record.account_id != target.account_id:
            raise ValueError("trade target does not match normalized record")
        if not record.source_record_id or not record.revision:
            raise ValueError("trade record identity is required")
        if (
            position_start_at is not None
            and record.event_time.astimezone(UTC) < position_start_at
        ):
            raise ValueError("trade record is before position start time")
    if result.candidate_checkpoint is not None:
        candidate_order = _checkpoint_order(result.candidate_checkpoint)
        if checkpoint_before is not None and candidate_order < _checkpoint_order(
            checkpoint_before
        ):
            raise ValueError("trade checkpoint cannot move backwards")


def record_trade_fetch(
    connection: sqlite3.Connection,
    subscription_id: int,
    target: ProviderTarget,
    result: TradeRecordFetchResult,
) -> int:
    with connection:
        checkpoint_row = connection.execute(
            "SELECT checkpoint, trade_baseline_initialized FROM subscription_state "
            "WHERE subscription_id = ?",
            (subscription_id,),
        ).fetchone()
        checkpoint_before = checkpoint_row["checkpoint"] if checkpoint_row else None
        baseline = (
            checkpoint_row is None
            or checkpoint_row["trade_baseline_initialized"] == 0
        )
        _validate_fetch(subscription_id, target, result, checkpoint_before)

        inserted_keys: set[tuple[str, str]] = set()
        for record in result.records:
            normalized_json = _canonical_record(record)
            key = (record.source_record_id, record.revision)
            existing = connection.execute(
                "SELECT normalized_json, last_observed_at FROM trade_events "
                "WHERE subscription_id = ? AND source_record_id = ? AND revision = ?",
                (subscription_id, *key),
            ).fetchone()
            observed_at = _datetime_text(record.observed_at)
            if existing is not None:
                if existing["normalized_json"] != normalized_json:
                    raise ValueError("trade revision collision")
                if observed_at > existing["last_observed_at"]:
                    connection.execute(
                        "UPDATE trade_events SET last_observed_at = ? "
                        "WHERE subscription_id = ? AND source_record_id = ? AND revision = ?",
                        (observed_at, subscription_id, *key),
                    )
                continue
            connection.execute(
                "INSERT INTO trade_events "
                "(subscription_id, source_record_id, revision, event_time, "
                "first_observed_at, last_observed_at, normalized_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    subscription_id,
                    record.source_record_id,
                    record.revision,
                    _datetime_text(record.event_time),
                    observed_at,
                    observed_at,
                    normalized_json,
                ),
            )
            inserted_keys.add(key)

        inserted_outbox = 0
        rows = connection.execute(
            "SELECT normalized_json, last_observed_at FROM trade_events "
            "WHERE subscription_id = ? ORDER BY event_time, source_record_id, revision",
            (subscription_id,),
        ).fetchall()
        if rows:
            records = [_record_from_row(row) for row in rows]
            reconciliation = reconcile_records(records, result.history_complete)
            previous_rows = connection.execute(
                "SELECT symbol, position_side, side, quantity, entry_price, leverage, "
                "mark_price, price_updated_at, confidence, status, as_of_event_time "
                "FROM position_estimates WHERE subscription_id = ?",
                (subscription_id,),
            ).fetchall()
            previous_positions = {
                (row["symbol"], row["position_side"]): _position_from_row(row)
                for row in previous_rows
            }
            previous_prices = {
                (row["symbol"], row["position_side"]): (
                    Decimal(row["mark_price"])
                    if row["mark_price"] is not None
                    else None,
                    _parse_datetime(row["price_updated_at"]),
                )
                for row in previous_rows
            }
            connection.execute(
                "DELETE FROM position_estimates WHERE subscription_id = ?",
                (subscription_id,),
            )
            updated_at = _datetime_text(max(record.observed_at for record in records))
            valuation_time = (
                result.account_snapshot.observed_at
                if result.account_snapshot is not None
                else max(record.observed_at for record in records)
            )
            for inferred_position in reconciliation.positions.values():
                position_key = (
                    inferred_position.symbol,
                    inferred_position.position_side,
                )
                previous_mark, previous_mark_time = previous_prices.get(
                    position_key, (None, None)
                )
                if inferred_position.symbol in result.mark_prices:
                    mark_price = result.mark_prices[inferred_position.symbol]
                    price_updated_at = valuation_time
                else:
                    mark_price = previous_mark
                    price_updated_at = previous_mark_time
                position = _value_position(
                    inferred_position,
                    mark_price,
                    price_updated_at,
                )
                connection.execute(
                    "INSERT INTO position_estimates "
                    "(subscription_id, symbol, position_side, side, quantity, entry_price, "
                    "mark_price, notional, leverage, position_margin, estimated_pnl, "
                    "price_updated_at, confidence, status, as_of_event_time, stale_since, "
                    "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        subscription_id,
                        position.symbol,
                        position.position_side,
                        position.side,
                        _decimal_text(position.quantity),
                        _decimal_text(position.entry_price),
                        _decimal_text(position.mark_price),
                        _decimal_text(position.notional),
                        _decimal_text(position.leverage),
                        _decimal_text(position.position_margin),
                        _decimal_text(position.estimated_pnl),
                        _datetime_text(position.price_updated_at)
                        if position.price_updated_at
                        else None,
                        position.confidence,
                        position.status,
                        _datetime_text(position.as_of_event_time)
                        if position.as_of_event_time
                        else None,
                        _datetime_text(position.stale_since)
                        if position.stale_since
                        else None,
                        updated_at,
                    ),
                )

            if result.account_snapshot is not None:
                connection.execute(
                    "INSERT INTO trade_account_snapshots "
                    "(subscription_id, margin_balance, updated_at) VALUES (?, ?, ?) "
                    "ON CONFLICT(subscription_id) DO UPDATE SET "
                    "margin_balance = excluded.margin_balance, updated_at = excluded.updated_at",
                    (
                        subscription_id,
                        _decimal_text(result.account_snapshot.margin_balance),
                        _datetime_text(result.account_snapshot.observed_at),
                    ),
                )

            if not baseline:
                new_events = [
                    event
                    for event in reconciliation.events
                    if (event.record.source_record_id, event.record.revision)
                    in inserted_keys
                ]
                batch_size = len(new_events)
                batch_id = _batch_id(target, new_events) if new_events else None
                position_changes = _position_changes(
                    previous_positions, reconciliation.positions
                )
                for event in new_events:
                    post = build_collected_post(
                        target,
                        event,
                        batch_id=batch_id,
                        batch_size=batch_size,
                        position_changes=position_changes,
                    )
                    cursor = connection.execute(
                        "INSERT OR IGNORE INTO outbox_posts "
                        "(subscription_id, external_id, payload_json) VALUES (?, ?, ?)",
                        (
                            subscription_id,
                            post.external_id,
                            json.dumps(
                                collected_post_payload(subscription_id, post),
                                ensure_ascii=False,
                            ),
                        ),
                    )
                    inserted_outbox += cursor.rowcount

        if not rows and result.account_snapshot is not None:
            connection.execute(
                "INSERT INTO trade_account_snapshots "
                "(subscription_id, margin_balance, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(subscription_id) DO UPDATE SET "
                "margin_balance = excluded.margin_balance, updated_at = excluded.updated_at",
                (
                    subscription_id,
                    _decimal_text(result.account_snapshot.margin_balance),
                    _datetime_text(result.account_snapshot.observed_at),
                ),
            )

        if result.candidate_checkpoint is not None:
            connection.execute(
                "INSERT INTO subscription_state "
                "(subscription_id, checkpoint, trade_baseline_initialized) "
                "VALUES (?, ?, 1) ON CONFLICT(subscription_id) DO UPDATE SET "
                "checkpoint = excluded.checkpoint, trade_baseline_initialized = 1",
                (subscription_id, result.candidate_checkpoint),
            )
        else:
            connection.execute(
                "INSERT INTO subscription_state "
                "(subscription_id, trade_baseline_initialized) VALUES (?, 1) "
                "ON CONFLICT(subscription_id) DO UPDATE SET "
                "trade_baseline_initialized = 1",
                (subscription_id,),
            )
        return inserted_outbox


def mark_trade_positions_stale(
    connection: sqlite3.Connection,
    subscription_id: int,
    stale_since: datetime,
) -> None:
    timestamp = _datetime_text(stale_since)
    with connection:
        connection.execute(
            "UPDATE position_estimates SET status = 'STALE', stale_since = ?, updated_at = ? "
            "WHERE subscription_id = ?",
            (timestamp, timestamp, subscription_id),
        )


def mark_trade_positions_unknown(
    connection: sqlite3.Connection,
    subscription_id: int,
    gap_at: datetime,
) -> None:
    timestamp = _datetime_text(gap_at)
    with connection:
        connection.execute(
            "UPDATE position_estimates SET side = 'UNKNOWN', quantity = NULL, "
            "entry_price = NULL, notional = NULL, leverage = NULL, "
            "position_margin = NULL, estimated_pnl = NULL, "
            "confidence = 'UNKNOWN', status = 'UNKNOWN', stale_since = ?, updated_at = ? "
            "WHERE subscription_id = ?",
            (timestamp, timestamp, subscription_id),
        )


def position_for(
    connection: sqlite3.Connection,
    subscription_id: int,
    symbol: str,
    position_side: TradePositionSide,
) -> PositionEstimate | None:
    row = connection.execute(
        "SELECT symbol, position_side, side, quantity, entry_price, mark_price, "
        "notional, leverage, position_margin, estimated_pnl, price_updated_at, "
        "confidence, status, as_of_event_time, stale_since FROM position_estimates "
        "WHERE subscription_id = ? AND symbol = ? AND position_side = ?",
        (subscription_id, symbol, position_side),
    ).fetchone()
    if row is None:
        return None
    return PositionEstimate(
        symbol=row["symbol"],
        position_side=row["position_side"],
        side=row["side"],
        quantity=Decimal(row["quantity"]) if row["quantity"] is not None else None,
        confidence=row["confidence"],
        status=row["status"],
        as_of_event_time=_parse_datetime(row["as_of_event_time"]),
        stale_since=_parse_datetime(row["stale_since"]),
        entry_price=Decimal(row["entry_price"])
        if row["entry_price"] is not None
        else None,
        leverage=Decimal(row["leverage"])
        if row["leverage"] is not None
        else None,
        mark_price=Decimal(row["mark_price"])
        if row["mark_price"] is not None
        else None,
        notional=Decimal(row["notional"])
        if row["notional"] is not None
        else None,
        position_margin=Decimal(row["position_margin"])
        if row["position_margin"] is not None
        else None,
        estimated_pnl=Decimal(row["estimated_pnl"])
        if row["estimated_pnl"] is not None
        else None,
        price_updated_at=_parse_datetime(row["price_updated_at"]),
    )


def account_snapshot_for(
    connection: sqlite3.Connection,
    subscription_id: int,
) -> dict | None:
    row = connection.execute(
        "SELECT margin_balance, updated_at FROM trade_account_snapshots "
        "WHERE subscription_id = ?",
        (subscription_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "marginBalance": row["margin_balance"],
        "updatedAt": row["updated_at"],
    }


def trade_operation_snapshots_for(
    connection: sqlite3.Connection,
    subscription_id: int,
) -> list[dict]:
    rows = connection.execute(
        "SELECT normalized_json, last_observed_at FROM trade_events "
        "WHERE subscription_id = ? ORDER BY event_time, source_record_id, revision",
        (subscription_id,),
    ).fetchall()
    if not rows:
        return []
    state = connection.execute(
        "SELECT trade_start_at FROM subscription_state WHERE subscription_id = ?",
        (subscription_id,),
    ).fetchone()
    reconciliation = reconcile_records(
        [_record_from_row(row) for row in rows],
        history_complete=bool(state and state["trade_start_at"]),
    )
    snapshots = []
    for event in reconciliation.events:
        record = event.record
        realized_pnl = record.source_payload.get("totalPnl")
        if not isinstance(realized_pnl, str):
            realized_pnl = None
        amount = (
            record.quantity * record.price
            if record.quantity is not None and record.price is not None
            else None
        )
        snapshots.append(
            {
                "sourceRecordId": record.source_record_id,
                "revision": record.revision,
                "action": event.action,
                "effectiveAction": record.operation,
                "symbol": record.symbol,
                "positionSide": record.position_side,
                "quantity": _decimal_text(record.quantity),
                "price": _decimal_text(record.price),
                "amount": _decimal_text(amount),
                "leverage": _decimal_text(record.leverage),
                "realizedPnl": realized_pnl,
                "eventTime": _datetime_text(record.event_time),
            }
        )
    return snapshots[-2000:]
