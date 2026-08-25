import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from collector_agent.models import CollectedPost, OutboxPost, ProviderTarget, collected_post_payload
from collector_agent.trade_models import PositionEstimate, TradePositionSide, TradeRecordFetchResult
from collector_agent.trade_store import (
    account_snapshot_for,
    initialize_trade_store,
    mark_trade_positions_unknown,
    mark_trade_positions_stale,
    position_for,
    record_trade_fetch,
    trade_operation_snapshots_for,
)


class CollectorStore:
    def __init__(self, path: Path) -> None:
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS subscription_state (subscription_id INTEGER PRIMARY KEY, checkpoint TEXT, next_check_at TEXT, trade_start_at TEXT, trade_baseline_initialized INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS outbox_posts (id INTEGER PRIMARY KEY, subscription_id INTEGER NOT NULL, external_id TEXT NOT NULL, payload_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', UNIQUE(subscription_id, external_id));
            CREATE TABLE IF NOT EXISTS dead_letters (id INTEGER PRIMARY KEY, external_id TEXT NOT NULL, payload_json TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS alert_cooldowns (key TEXT PRIMARY KEY, sent_at TEXT NOT NULL);
        """)
        initialize_trade_store(self.connection)
        state_columns = {
            row[1]
            for row in self.connection.execute("PRAGMA table_info(subscription_state)")
        }
        if "trade_start_at" not in state_columns:
            self.connection.execute(
                "ALTER TABLE subscription_state ADD COLUMN trade_start_at TEXT"
            )
        if "trade_baseline_initialized" not in state_columns:
            self.connection.execute(
                "ALTER TABLE subscription_state ADD COLUMN "
                "trade_baseline_initialized INTEGER NOT NULL DEFAULT 0"
            )
            self.connection.execute(
                "UPDATE subscription_state SET trade_baseline_initialized = 1 "
                "WHERE checkpoint IS NOT NULL OR EXISTS ("
                "SELECT 1 FROM trade_events "
                "WHERE trade_events.subscription_id = subscription_state.subscription_id"
                ")"
            )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def checkpoint_for(self, subscription_id: int) -> str | None:
        row = self.connection.execute("SELECT checkpoint FROM subscription_state WHERE subscription_id = ?", (subscription_id,)).fetchone()
        return row["checkpoint"] if row else None

    def ensure_trade_start(
        self, subscription_id: int, position_start_at: datetime | None
    ) -> bool:
        if position_start_at is not None:
            if position_start_at.tzinfo is None:
                raise ValueError("position start time must be timezone-aware")
            requested = position_start_at.astimezone(UTC).isoformat()
        else:
            requested = None
        row = self.connection.execute(
            "SELECT trade_start_at FROM subscription_state WHERE subscription_id = ?",
            (subscription_id,),
        ).fetchone()
        stored = row["trade_start_at"] if row else None
        if stored is not None:
            try:
                stored = datetime.fromisoformat(stored).astimezone(UTC).isoformat()
            except ValueError:
                pass
        if stored == requested and (row is not None or requested is None):
            return False
        with self.connection:
            self.connection.execute(
                "DELETE FROM trade_events WHERE subscription_id = ?",
                (subscription_id,),
            )
            self.connection.execute(
                "DELETE FROM position_estimates WHERE subscription_id = ?",
                (subscription_id,),
            )
            self.connection.execute(
                "DELETE FROM trade_account_snapshots WHERE subscription_id = ?",
                (subscription_id,),
            )
            self.connection.execute(
                "DELETE FROM outbox_posts WHERE subscription_id = ?",
                (subscription_id,),
            )
            self.connection.execute(
                "INSERT INTO subscription_state "
                "(subscription_id, checkpoint, next_check_at, trade_start_at, "
                "trade_baseline_initialized) VALUES (?, NULL, NULL, ?, 0) "
                "ON CONFLICT(subscription_id) DO UPDATE SET "
                "checkpoint = NULL, next_check_at = NULL, "
                "trade_start_at = excluded.trade_start_at, "
                "trade_baseline_initialized = 0",
                (subscription_id, requested),
            )
        return True

    def trade_start_for(self, subscription_id: int) -> datetime | None:
        row = self.connection.execute(
            "SELECT trade_start_at FROM subscription_state WHERE subscription_id = ?",
            (subscription_id,),
        ).fetchone()
        return (
            datetime.fromisoformat(row["trade_start_at"])
            if row and row["trade_start_at"]
            else None
        )

    def trade_baseline_initialized_for(self, subscription_id: int) -> bool:
        row = self.connection.execute(
            "SELECT trade_baseline_initialized FROM subscription_state "
            "WHERE subscription_id = ?",
            (subscription_id,),
        ).fetchone()
        return bool(row and row["trade_baseline_initialized"])

    def record_fetch(self, subscription_id: int, checkpoint: str | None, posts: list[CollectedPost]) -> int:
        inserted = 0
        with self.connection:
            for post in posts:
                payload = collected_post_payload(subscription_id, post)
                cursor = self.connection.execute("INSERT OR IGNORE INTO outbox_posts (subscription_id, external_id, payload_json) VALUES (?, ?, ?)", (subscription_id, post.external_id, json.dumps(payload, ensure_ascii=False)))
                inserted += cursor.rowcount
            if checkpoint is not None:
                self.connection.execute("INSERT INTO subscription_state (subscription_id, checkpoint) VALUES (?, ?) ON CONFLICT(subscription_id) DO UPDATE SET checkpoint = excluded.checkpoint", (subscription_id, checkpoint))
        return inserted

    def record_trade_fetch(
        self,
        subscription_id: int,
        target: ProviderTarget,
        result: TradeRecordFetchResult,
    ) -> int:
        return record_trade_fetch(self.connection, subscription_id, target, result)

    def mark_trade_positions_stale(
        self, subscription_id: int, stale_since
    ) -> None:
        mark_trade_positions_stale(self.connection, subscription_id, stale_since)

    def mark_trade_positions_unknown(self, subscription_id: int, gap_at) -> None:
        mark_trade_positions_unknown(self.connection, subscription_id, gap_at)

    def position_for(
        self,
        subscription_id: int,
        symbol: str,
        position_side: TradePositionSide,
    ) -> PositionEstimate | None:
        return position_for(self.connection, subscription_id, symbol, position_side)

    def position_snapshots_for(self, subscription_id: int) -> list[dict]:
        rows = self.connection.execute(
            "SELECT symbol, position_side, side, quantity, entry_price, mark_price, "
            "notional, leverage, position_margin, estimated_pnl, price_updated_at, "
            "confidence, status, as_of_event_time, stale_since, updated_at "
            "FROM position_estimates "
            "WHERE subscription_id = ? ORDER BY symbol, position_side",
            (subscription_id,),
        ).fetchall()
        return [
            {
                "symbol": row["symbol"],
                "positionSide": row["position_side"],
                "side": row["side"],
                "quantity": row["quantity"],
                "entryPrice": row["entry_price"],
                "currentPrice": row["mark_price"],
                "notional": row["notional"],
                "leverage": row["leverage"],
                "positionMargin": row["position_margin"],
                "estimatedPnl": row["estimated_pnl"],
                "priceUpdatedAt": row["price_updated_at"],
                "confidence": row["confidence"],
                "status": row["status"],
                "asOfEventTime": row["as_of_event_time"],
                "staleSince": row["stale_since"],
                "updatedAt": row["updated_at"],
            }
            for row in rows
        ]

    def account_snapshot_for(self, subscription_id: int) -> dict | None:
        return account_snapshot_for(self.connection, subscription_id)

    def trade_operation_snapshots_for(self, subscription_id: int) -> list[dict]:
        return trade_operation_snapshots_for(self.connection, subscription_id)

    def pending_posts(self, limit: int = 100) -> list[OutboxPost]:
        rows = self.connection.execute("SELECT id, subscription_id, external_id, payload_json FROM outbox_posts WHERE status = 'pending' ORDER BY id LIMIT ?", (limit,)).fetchall()
        return [OutboxPost(id=row["id"], subscription_id=row["subscription_id"], external_id=row["external_id"], payload=json.loads(row["payload_json"])) for row in rows]

    def apply_upload_results(self, results: list[dict]) -> None:
        with self.connection:
            for result in results:
                external_id = result.get("externalId")
                status = result.get("status")
                row = self.connection.execute(
                    "SELECT id, payload_json FROM outbox_posts "
                    "WHERE external_id = ? AND status = 'pending' ORDER BY id LIMIT 1",
                    (external_id,),
                ).fetchone()
                if row is None:
                    continue
                if status in {"accepted", "duplicate"}:
                    self.connection.execute("DELETE FROM outbox_posts WHERE id = ?", (row["id"],))
                elif status == "invalid":
                    self.connection.execute("INSERT INTO dead_letters (external_id, payload_json, reason) VALUES (?, ?, ?)", (external_id, row["payload_json"], result.get("reason") or "invalid"))
                    self.connection.execute("DELETE FROM outbox_posts WHERE id = ?", (row["id"],))

    def dead_letter_count(self) -> int:
        return self.connection.execute("SELECT COUNT(*) FROM dead_letters").fetchone()[0]
