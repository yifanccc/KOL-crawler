from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderHealth:
    status: str
    message: str | None = None
