import json
import sqlite3
from pathlib import Path

from collector_agent.models import CollectedPost, OutboxPost


class CollectorStore:
    def __init__(self, path: Path) -> None:
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS subscription_state (subscription_id INTEGER PRIMARY KEY, checkpoint TEXT, next_check_at TEXT);
            CREATE TABLE IF NOT EXISTS outbox_posts (id INTEGER PRIMARY KEY, subscription_id INTEGER NOT NULL, external_id TEXT NOT NULL, payload_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', UNIQUE(subscription_id, external_id));
            CREATE TABLE IF NOT EXISTS dead_letters (id INTEGER PRIMARY KEY, external_id TEXT NOT NULL, payload_json TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS alert_cooldowns (key TEXT PRIMARY KEY, sent_at TEXT NOT NULL);
        """)
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def checkpoint_for(self, subscription_id: int) -> str | None:
        row = self.connection.execute("SELECT checkpoint FROM subscription_state WHERE subscription_id = ?", (subscription_id,)).fetchone()
        return row["checkpoint"] if row else None

    def record_fetch(self, subscription_id: int, checkpoint: str | None, posts: list[CollectedPost]) -> int:
        inserted = 0
        with self.connection:
            for post in posts:
                payload = {"subscriptionId": subscription_id, "platform": post.platform, "externalId": post.external_id, "authorHandle": post.author_handle, "authorName": post.author_name, "authorAvatarUrl": post.author_avatar_url, "publishedAt": post.published_at.isoformat() if post.published_at else None, "url": post.url, "rawContent": post.raw_content, "rawPayload": post.raw_payload, "contentHash": post.content_hash}
                cursor = self.connection.execute("INSERT OR IGNORE INTO outbox_posts (subscription_id, external_id, payload_json) VALUES (?, ?, ?)", (subscription_id, post.external_id, json.dumps(payload, ensure_ascii=False)))
                inserted += cursor.rowcount
            self.connection.execute("INSERT INTO subscription_state (subscription_id, checkpoint) VALUES (?, ?) ON CONFLICT(subscription_id) DO UPDATE SET checkpoint = excluded.checkpoint", (subscription_id, checkpoint))
        return inserted

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
