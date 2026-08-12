from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal


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
