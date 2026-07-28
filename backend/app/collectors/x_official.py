from collections.abc import Callable
from datetime import datetime
import json

import httpx

from app.collectors.base import CollectedPost


class XOfficialCollector:
    def __init__(self, bearer_token: str, user_id_resolver: Callable[[str], str]) -> None:
        self.bearer_token = bearer_token
        self.user_id_resolver = user_id_resolver

    def fetch_new(
        self,
        handle: str,
        checkpoint: str | None = None,
        limit: int = 20,
    ) -> list[CollectedPost]:
        user_id = self.user_id_resolver(handle)
        params = {
            "max_results": str(min(max(limit, 5), 100)),
            "tweet.fields": "created_at",
            "exclude": "replies",
        }
        if checkpoint:
            params["since_id"] = checkpoint
        response = httpx.get(
            f"https://api.x.com/2/users/{user_id}/tweets",
            params=params,
            headers={"Authorization": f"Bearer {self.bearer_token}"},
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        posts = []
        for item in payload.get("data", []):
            post_id = item["id"]
            created_at = item.get("created_at")
            posts.append(
                CollectedPost(
                    platform="x",
                    external_id=post_id,
                    url=f"https://x.com/{handle.lstrip('@')}/status/{post_id}",
                    author_handle=handle.lstrip("@"),
                    author_name=handle.lstrip("@"),
                    published_at=datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    if created_at
                    else None,
                    raw_text=item["text"],
                    raw_json=json.dumps(item, ensure_ascii=False),
                )
            )
        return sorted(posts, key=lambda post: post.published_at or datetime.min)
