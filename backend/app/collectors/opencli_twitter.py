from datetime import datetime
import json
import subprocess
from typing import Any

import yaml

from app.collectors.base import CollectedPost


def _parse_x_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%a %b %d %H:%M:%S %z %Y", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def parse_opencli_tweets(data: str, handle: str, limit: int = 20) -> list[CollectedPost]:
    payload: Any = yaml.safe_load(data) or []
    if isinstance(payload, dict):
        payload = payload.get("items", [])
    posts = []
    for item in payload[:limit]:
        if not isinstance(item, dict):
            continue
        post_id = str(item.get("id") or item.get("tweet_id") or "")
        text = str(item.get("text") or "").strip()
        if not post_id or not text:
            continue
        author = str(item.get("author") or handle).lstrip("@")
        posts.append(
            CollectedPost(
                platform="x",
                external_id=post_id,
                url=item.get("url") or f"https://x.com/{author}/status/{post_id}",
                author_handle=author,
                author_name=author,
                published_at=_parse_x_datetime(item.get("created_at")),
                raw_text=text,
                raw_json=json.dumps(item, ensure_ascii=False),
            )
        )
    return sorted(posts, key=lambda post: post.published_at or datetime.min.replace(tzinfo=None))


class OpenCliTwitterCollector:
    def __init__(self, command: str = "opencli") -> None:
        self.command = command

    def fetch_new(
        self,
        handle: str,
        checkpoint: str | None = None,
        limit: int = 20,
    ) -> list[CollectedPost]:
        result = subprocess.run(
            [
                self.command,
                "twitter",
                "tweets",
                handle.lstrip("@"),
                "--limit",
                str(limit),
                "-f",
                "yaml",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=45,
        )
        posts = parse_opencli_tweets(result.stdout, handle, limit=limit)
        if checkpoint:
            posts = [post for post in posts if post.external_id > checkpoint]
        return posts[:limit]
