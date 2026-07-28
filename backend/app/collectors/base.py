from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class CollectedPost:
    platform: str
    external_id: str
    url: str | None
    author_handle: str | None
    author_name: str | None
    published_at: datetime | None
    raw_text: str
    raw_json: str | None = None


class CollectorAdapter(Protocol):
    def fetch_new(
        self,
        handle: str,
        checkpoint: str | None = None,
        limit: int = 20,
    ) -> list[CollectedPost]:
        raise NotImplementedError
