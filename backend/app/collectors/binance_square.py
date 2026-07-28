from datetime import UTC, datetime
import hashlib
import json
import re

import httpx

from app.collectors.base import CollectedPost


class BinanceSquareCollector:
    """Best-effort public collector. It returns no posts if Binance changes page markup."""

    def fetch_new(
        self,
        handle: str,
        checkpoint: str | None = None,
        limit: int = 20,
    ) -> list[CollectedPost]:
        response = httpx.get(
            f"https://www.binance.com/en/square/profile/{handle.lstrip('@')}",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=20,
        )
        response.raise_for_status()
        html = response.text
        seen: set[str] = set()
        posts: list[CollectedPost] = []
        for match in re.finditer(r"/en/square/post/([A-Za-z0-9_-]+)", html):
            post_id = match.group(1)
            if post_id in seen:
                continue
            seen.add(post_id)
            if checkpoint and post_id <= checkpoint:
                continue
            text_start = max(match.start() - 280, 0)
            text_end = min(match.end() + 280, len(html))
            snippet = re.sub(r"<[^>]+>", " ", html[text_start:text_end])
            snippet = re.sub(r"\s+", " ", snippet).strip()
            if not snippet:
                digest = hashlib.sha256(post_id.encode("utf-8")).hexdigest()[:12]
                snippet = f"Binance Square post {digest}"
            posts.append(
                CollectedPost(
                    platform="binance_square",
                    external_id=post_id,
                    url=f"https://www.binance.com/en/square/post/{post_id}",
                    author_handle=handle.lstrip("@"),
                    author_name=handle.lstrip("@"),
                    published_at=datetime.now(UTC),
                    raw_text=snippet,
                    raw_json=json.dumps({"post_id": post_id}, ensure_ascii=False),
                )
            )
            if len(posts) >= limit:
                break
        return posts
