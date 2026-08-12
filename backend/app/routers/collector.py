import json
from typing import Any
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.collector_security import require_collector
from app.core.config import get_settings
from app.db.session import get_db
from app.models import CollectorAgent, KolProfile, RawPost, Subscription

router = APIRouter(prefix="/api/v1/collector", tags=["collector"])


class ProviderHeartbeat(BaseModel):
    platform: str = Field(min_length=1, max_length=32)
    status: str = Field(min_length=1, max_length=32)
    message: str | None = Field(default=None, max_length=1000)


class HeartbeatRequest(BaseModel):
    agentId: str = Field(min_length=1, max_length=255)
    version: str = Field(min_length=1, max_length=64)
    status: str = Field(min_length=1, max_length=32)
    providers: list[ProviderHeartbeat]
    outboxPending: int = Field(ge=0)
    checkedAt: datetime


class UploadRequest(BaseModel):
    agentId: str = Field(min_length=1, max_length=255)
    posts: list[dict[str, Any]] = Field(max_length=100)


class UploadedPost(BaseModel):
    subscriptionId: int = Field(gt=0)
    platform: str = Field(min_length=1, max_length=32)
    externalId: str = Field(min_length=1, max_length=255)
    authorHandle: str | None = Field(default=None, max_length=255)
    authorName: str | None = Field(default=None, max_length=255)
    authorAvatarUrl: str | None = Field(default=None, max_length=1024)
    publishedAt: datetime | None = None
    url: str | None = Field(default=None, max_length=1024)
    rawContent: str = Field(min_length=1, max_length=50000)
    rawPayload: dict[str, Any] | None = None
    contentHash: str | None = Field(default=None, max_length=64)


@router.get("/config")
def collector_config(
    _: str = Depends(require_collector), db: Session = Depends(get_db)
) -> dict:
    settings = get_settings()
    rows = db.scalars(
        select(Subscription)
        .where(Subscription.deleted_at.is_(None))
        .order_by(Subscription.id)
    ).all()
    return {
        "agentId": settings.collector_agent_id,
        "pollSeconds": settings.collector_poll_seconds,
        "subscriptions": [
            {
                "id": row.id,
                "platform": row.platform,
                "handle": row.platform_handle,
                "accountId": row.platform_account_id,
                "intervalMinutes": row.interval_minutes,
                "enabled": row.enabled,
            }
            for row in rows
        ],
    }


@router.post("/heartbeat")
def collector_heartbeat(
    payload: HeartbeatRequest,
    _: str = Depends(require_collector),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    settings = get_settings()
    if payload.agentId != settings.collector_agent_id:
        raise HTTPException(status_code=403, detail="Collector agent ID does not match configuration")
    agent = db.scalar(select(CollectorAgent).where(CollectorAgent.agent_id == payload.agentId))
    if agent is None:
        agent = CollectorAgent(
            agent_id=payload.agentId,
            version=payload.version,
            status=payload.status,
            providers_json=json.dumps([provider.model_dump() for provider in payload.providers]),
            outbox_pending=payload.outboxPending,
            last_heartbeat_at=payload.checkedAt,
        )
        db.add(agent)
    else:
        agent.version = payload.version
        agent.status = payload.status
        agent.providers_json = json.dumps([provider.model_dump() for provider in payload.providers])
        agent.outbox_pending = payload.outboxPending
        agent.last_heartbeat_at = payload.checkedAt
    db.commit()
    return {"ok": True}


@router.post("/posts")
def collector_posts(
    payload: UploadRequest, _: str = Depends(require_collector), db: Session = Depends(get_db)
) -> dict:
    if payload.agentId != get_settings().collector_agent_id:
        raise HTTPException(status_code=403, detail="Collector agent ID does not match configuration")
    items = []
    for item in payload.posts:
        try:
            post = UploadedPost.model_validate(item)
            subscription = db.get(Subscription, post.subscriptionId)
            if subscription is None or subscription.platform != post.platform:
                raise ValueError("subscription/platform mismatch")
        except (ValidationError, ValueError) as exc:
            items.append({"externalId": item.get("externalId") if isinstance(item, dict) else None, "status": "invalid", "reason": str(exc)})
            continue
        try:
            with db.begin_nested():
                db.add(RawPost(
                    subscription_id=subscription.id, platform=post.platform, external_id=post.externalId,
                    url=post.url, author_handle=post.authorHandle, author_name=post.authorName,
                    published_at=post.publishedAt, raw_text=post.rawContent,
                    raw_json=json.dumps(post.rawPayload, ensure_ascii=False) if post.rawPayload else None,
                    content_hash=post.contentHash, analysis_status="pending",
                ))
                db.flush()
                avatar_url = (post.authorAvatarUrl or "").strip()
                if avatar_url and subscription.kol_profile_id:
                    kol = db.get(KolProfile, subscription.kol_profile_id)
                    if kol is not None:
                        kol.avatar_url = avatar_url
            items.append({"externalId": post.externalId, "status": "accepted"})
        except IntegrityError:
            items.append({"externalId": post.externalId, "status": "duplicate"})
    db.commit()
    return {"items": items}
