import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.collector_security import require_collector
from app.core.config import get_settings
from app.db.session import get_db
from app.models import (
    CollectorAgent,
    KolProfile,
    PositionEstimate,
    RawPost,
    Subscription,
)
from app.models.subscription import TRADE_PLATFORMS

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


class UploadedPosition(BaseModel):
    symbol: str = Field(min_length=1, max_length=64, pattern=r"^[A-Z0-9._-]+$")
    positionSide: Literal["LONG", "SHORT", "UNKNOWN"]
    side: Literal["LONG", "SHORT", "FLAT", "UNKNOWN"]
    quantity: Decimal | None = Field(default=None, ge=0)
    confidence: Literal["HIGH", "MEDIUM", "LOW", "UNKNOWN"]
    status: Literal["ACTIVE", "FLAT", "UNKNOWN", "STALE"]
    asOfEventTime: datetime | None = None
    staleSince: datetime | None = None
    updatedAt: datetime

    @field_validator("asOfEventTime", "staleSince", "updatedAt")
    @classmethod
    def validate_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("position timestamps must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_state(self) -> "UploadedPosition":
        if self.status == "ACTIVE":
            if self.side != self.positionSide or self.side not in {"LONG", "SHORT"}:
                raise ValueError("active position side must match positionSide")
            if self.quantity is not None and self.quantity <= 0:
                raise ValueError("active position quantity must be positive")
        elif self.status == "FLAT":
            if self.side != "FLAT" or self.quantity != 0:
                raise ValueError("flat position must have FLAT side and zero quantity")
        elif self.status == "UNKNOWN":
            if self.side != "UNKNOWN" or self.quantity is not None:
                raise ValueError("unknown position cannot include a quantity")
        return self


class PositionSnapshotRequest(BaseModel):
    agentId: str = Field(min_length=1, max_length=255)
    positions: list[UploadedPosition] = Field(max_length=1000)

    @model_validator(mode="after")
    def validate_unique_positions(self) -> "PositionSnapshotRequest":
        keys = [(item.symbol, item.positionSide) for item in self.positions]
        if len(keys) != len(set(keys)):
            raise ValueError("position snapshot contains duplicate symbol/side keys")
        return self


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


@router.put("/subscriptions/{subscription_id}/positions")
def replace_subscription_positions(
    subscription_id: int,
    payload: PositionSnapshotRequest,
    _: str = Depends(require_collector),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    if payload.agentId != get_settings().collector_agent_id:
        raise HTTPException(
            status_code=403,
            detail="Collector agent ID does not match configuration",
        )
    subscription = db.get(Subscription, subscription_id)
    if (
        subscription is None
        or subscription.deleted_at is not None
        or subscription.platform not in TRADE_PLATFORMS
    ):
        raise HTTPException(status_code=404, detail="Trade subscription not found")

    db.execute(
        delete(PositionEstimate).where(
            PositionEstimate.subscription_id == subscription_id
        )
    )
    for item in payload.positions:
        db.add(
            PositionEstimate(
                subscription_id=subscription_id,
                symbol=item.symbol,
                position_side=item.positionSide,
                side=item.side,
                quantity=format(item.quantity, "f")
                if item.quantity is not None
                else None,
                confidence=item.confidence,
                status=item.status,
                as_of_event_time=item.asOfEventTime,
                stale_since=item.staleSince,
                source_updated_at=item.updatedAt.astimezone(UTC),
            )
        )
    db.commit()
    return {"count": len(payload.positions)}
