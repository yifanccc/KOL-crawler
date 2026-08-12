import json
import sqlite3
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
          confidence TEXT NOT NULL,
          status TEXT NOT NULL,
          as_of_event_time TEXT,
          stale_since TEXT,
          updated_at TEXT NOT NULL,
          PRIMARY KEY(subscription_id, symbol, position_side)
        );
        """
    )


def _datetime_text(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("trade timestamps must be timezone-aware")
    return value.astimezone(UTC).isoformat()


def _parse_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _decimal_text(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None


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
    for record in result.records:
        if record.platform != target.platform or record.account_id != target.account_id:
            raise ValueError("trade target does not match normalized record")
        if not record.source_record_id or not record.revision:
            raise ValueError("trade record identity is required")
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
            "SELECT checkpoint FROM subscription_state WHERE subscription_id = ?",
            (subscription_id,),
        ).fetchone()
        checkpoint_before = checkpoint_row["checkpoint"] if checkpoint_row else None
        baseline = checkpoint_before is None
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
            connection.execute(
                "DELETE FROM position_estimates WHERE subscription_id = ?",
                (subscription_id,),
            )
            updated_at = _datetime_text(max(record.observed_at for record in records))
            for position in reconciliation.positions.values():
                connection.execute(
                    "INSERT INTO position_estimates "
                    "(subscription_id, symbol, position_side, side, quantity, confidence, "
                    "status, as_of_event_time, stale_since, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        subscription_id,
                        position.symbol,
                        position.position_side,
                        position.side,
                        _decimal_text(position.quantity),
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

            if not baseline:
                for event in reconciliation.events:
                    key = (event.record.source_record_id, event.record.revision)
                    if key not in inserted_keys:
                        continue
                    post = build_collected_post(target, event)
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

        if result.candidate_checkpoint is not None:
            connection.execute(
                "INSERT INTO subscription_state (subscription_id, checkpoint) VALUES (?, ?) "
                "ON CONFLICT(subscription_id) DO UPDATE SET checkpoint = excluded.checkpoint",
                (subscription_id, result.candidate_checkpoint),
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
        "SELECT symbol, position_side, side, quantity, confidence, status, "
        "as_of_event_time, stale_since FROM position_estimates "
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
    )
