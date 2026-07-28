from datetime import datetime
import json
from pathlib import Path

from app.collectors.base import CollectedPost


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class BootstrapCollector:
    def __init__(self, path: Path) -> None:
        self.path = path

    def fetch_new(
        self,
        handle: str,
        checkpoint: str | None = None,
        limit: int = 20,
    ) -> list[CollectedPost]:
        if not self.path.exists():
            return []
        payload = json.loads(self.path.read_text())
        posts = []
        for item in payload:
            if item.get("author_handle") != handle.lstrip("@"):
                continue
            posts.append(
                CollectedPost(
                    platform=item.get("platform", "x"),
                    external_id=str(item["external_id"]),
                    url=item.get("url"),
                    author_handle=item.get("author_handle"),
                    author_name=item.get("author_name"),
                    published_at=_parse_iso(item.get("published_at")),
                    raw_text=item["raw_text"],
                    raw_json=json.dumps(item, ensure_ascii=False),
                )
            )
        posts.sort(key=lambda post: post.published_at or datetime.min)
        if checkpoint:
            posts = [post for post in posts if post.external_id > checkpoint]
        return posts[:limit]
