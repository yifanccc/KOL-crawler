from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal


TRADE_PLATFORMS = frozenset({"binance_copy"})


@dataclass(frozen=True)
class CollectedPost:
    platform: str
    external_id: str
    author_handle: str
    author_name: str | None
    author_avatar_url: str | None
    published_at: datetime | None
    url: str
    raw_content: str
    raw_payload: dict[str, Any] | None
    content_hash: str | None


@dataclass(frozen=True)
class OutboxPost:
    id: int
    subscription_id: int
    external_id: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class ProviderTarget:
    subscription_id: int
    platform: str
    account_id: str | None
    handle: str


@dataclass(frozen=True)
class PostFetchResult:
    posts: list[CollectedPost]
    candidate_checkpoint: str | None
    kind: Literal["posts"] = "posts"


def collected_post_payload(subscription_id: int, post: CollectedPost) -> dict[str, Any]:
    return {
        "subscriptionId": subscription_id,
        "platform": post.platform,
        "externalId": post.external_id,
        "authorHandle": post.author_handle,
        "authorName": post.author_name,
        "authorAvatarUrl": post.author_avatar_url,
        "publishedAt": post.published_at.isoformat() if post.published_at else None,
        "url": post.url,
        "rawContent": post.raw_content,
        "rawPayload": post.raw_payload,
        "contentHash": post.content_hash,
    }
