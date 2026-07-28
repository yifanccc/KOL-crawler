from datetime import UTC, datetime

from collector_agent.models import CollectedPost
from collector_agent.providers.base import ProviderHealth


def _published_at(value: object) -> datetime | None:
    if not isinstance(value, (int, float)):
        return None
    return datetime.fromtimestamp(value / 1000, UTC)


class BinanceSquareProvider:
    def __init__(self, client) -> None:
        self.client = client
        self._health = ProviderHealth("healthy")

    def fetch(self, handle: str, checkpoint: str | None, limit: int) -> list[CollectedPost]:
        try:
            profile = self.client.user_by_username(handle)
            if not profile or not profile.get("squareUid"):
                self._health = ProviderHealth(
                    "failed", "Binance Square profile was not found"
                )
                return []
            payload = self.client.user_posts(profile["squareUid"])
            rows = payload.get("contents", []) if isinstance(payload, dict) else []
            posts = []
            for row in rows:
                if not isinstance(row, dict) or not row.get("id") or not row.get("bodyTextOnly"):
                    continue
                external_id = str(row["id"])
                if checkpoint is not None and int(external_id) <= int(checkpoint):
                    continue
                posts.append(
                    CollectedPost(
                        platform="binance_square",
                        external_id=external_id,
                        author_handle=row.get("username") or handle,
                        author_name=row.get("displayName") or profile.get("displayName"),
                        author_avatar_url=row.get("avatar") or profile.get("avatar"),
                        published_at=_published_at(
                            row.get("firstReleaseTime") or row.get("createTime")
                        ),
                        url=row.get("webLink")
                        or f"https://www.binance.com/zh-CN/square/post/{external_id}",
                        raw_content=row["bodyTextOnly"].strip(),
                        raw_payload={
                            key: row[key]
                            for key in (
                                "id",
                                "bodyTextOnly",
                                "firstReleaseTime",
                                "webLink",
                                "tradingPairs",
                            )
                            if key in row
                        },
                        content_hash=None,
                    )
                )
        except (KeyError, TypeError, ValueError):
            self._health = ProviderHealth("failed", "Invalid Binance Square response")
            return []
        except Exception:
            self._health = ProviderHealth("failed", "Binance Square request failed")
            return []
        self._health = ProviderHealth("healthy")
        ordered = sorted(posts, key=lambda post: int(post.external_id))
        return ordered[-limit:]

    def health(self) -> ProviderHealth:
        return self._health

    def close(self) -> None:
        close = getattr(self.client, "close", None)
        if close is not None:
            close()
