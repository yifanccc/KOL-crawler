from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderHealth:
    status: str
    message: str | None = None


class TradeHistoryGap(RuntimeError):
    """The fixed overlap window no longer contains the saved checkpoint."""
