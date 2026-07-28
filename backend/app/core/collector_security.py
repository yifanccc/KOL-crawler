import hashlib
import hmac

from fastapi import Header, HTTPException

from app.core.config import get_settings


def require_collector(authorization: str | None = Header(default=None)) -> str:
    settings = get_settings()
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Collector authentication required")
    token_hash = hashlib.sha256(authorization.removeprefix("Bearer ").strip().encode("utf-8")).hexdigest()
    if not settings.collector_token_hash or not hmac.compare_digest(
        token_hash, settings.collector_token_hash
    ):
        raise HTTPException(status_code=401, detail="Invalid collector token")
    return settings.collector_agent_id or ""
