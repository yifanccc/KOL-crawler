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
    PositionAccountSnapshot,
    PositionEstimate,
    PositionOperation,
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
    entryPrice: Decimal | None = Field(default=None, gt=0)
    currentPrice: Decimal | None = Field(default=None, gt=0)
    notional: Decimal | None = Field(default=None, ge=0)
    leverage: Decimal | None = Field(default=None, gt=0)
    positionMargin: Decimal | None = Field(default=None, ge=0)
    estimatedPnl: Decimal | None = None
    priceUpdatedAt: datetime | None = None
    confidence: Literal["HIGH", "MEDIUM", "LOW", "UNKNOWN"]
    status: Literal["ACTIVE", "FLAT", "UNKNOWN", "STALE"]
    asOfEventTime: datetime | None = None
    staleSince: datetime | None = None
    updatedAt: datetime

    @field_validator(
        "asOfEventTime",
        "staleSince",
        "priceUpdatedAt",
        "updatedAt",
    )
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
        if self.notional is not None:
            if self.quantity is None or self.currentPrice is None:
                raise ValueError("position notional requires quantity and currentPrice")
            if self.notional != abs(self.quantity * self.currentPrice):
                raise ValueError("position notional does not match quantity and price")
        if self.positionMargin is not None:
            if self.notional is None or self.leverage is None:
                raise ValueError("position margin requires notional and leverage")
            if self.positionMargin != self.notional / self.leverage:
                raise ValueError("position margin does not match notional and leverage")
        if self.estimatedPnl is not None:
            if (
                self.quantity is None
                or self.entryPrice is None
                or self.currentPrice is None
                or self.side not in {"LONG", "SHORT"}
            ):
                raise ValueError("estimated PnL requires an active valued position")
            price_delta = (
                self.currentPrice - self.entryPrice
                if self.side == "LONG"
                else self.entryPrice - self.currentPrice
            )
            if self.estimatedPnl != price_delta * self.quantity:
                raise ValueError("estimated PnL does not match position inputs")
        return self


class UploadedPositionAccount(BaseModel):
    marginBalance: Decimal | None = Field(default=None, ge=0)
    updatedAt: datetime

    @field_validator("updatedAt")
    @classmethod
    def validate_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("account snapshot timestamp must include a timezone")
        return value


class UploadedPositionOperation(BaseModel):
    sourceRecordId: str = Field(min_length=1, max_length=255)
    revision: str = Field(min_length=1, max_length=128)
    action: Literal["OPEN", "ADD", "REDUCE", "CLOSE", "REVERSE", "CORRECTION"]
    effectiveAction: Literal[
        "INCREASE", "DECREASE", "OPEN", "ADD", "REDUCE", "CLOSE", "REVERSE"
    ]
    symbol: str = Field(min_length=1, max_length=64, pattern=r"^[A-Z0-9._-]+$")
    positionSide: Literal["LONG", "SHORT", "UNKNOWN"]
    quantity: Decimal | None = Field(default=None, ge=0)
    price: Decimal | None = Field(default=None, ge=0)
    amount: Decimal | None = Field(default=None, ge=0)
    leverage: Decimal | None = Field(default=None, gt=0)
    realizedPnl: Decimal | None = None
    eventTime: datetime

    @field_validator("eventTime")
    @classmethod
    def validate_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("operation timestamp must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_amount(self) -> "UploadedPositionOperation":
        if self.amount is not None:
            if self.quantity is None or self.price is None:
                raise ValueError("operation amount requires quantity and price")
            if self.amount != self.quantity * self.price:
                raise ValueError("operation amount does not match quantity and price")
        return self


class PositionSnapshotRequest(BaseModel):
    agentId: str = Field(min_length=1, max_length=255)
    account: UploadedPositionAccount | None = None
    positions: list[UploadedPosition] = Field(max_length=1000)
    operations: list[UploadedPositionOperation] | None = Field(
        default=None, max_length=2000
    )

    @model_validator(mode="after")
    def validate_unique_positions(self) -> "PositionSnapshotRequest":
        keys = [(item.symbol, item.positionSide) for item in self.positions]
        if len(keys) != len(set(keys)):
            raise ValueError("position snapshot contains duplicate symbol/side keys")
        if self.operations is not None:
            operation_keys = [
                (item.sourceRecordId, item.revision) for item in self.operations
            ]
            if len(operation_keys) != len(set(operation_keys)):
                raise ValueError("position snapshot contains duplicate operation keys")
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
                entry_price=format(item.entryPrice, "f")
                if item.entryPrice is not None
                else None,
                mark_price=format(item.currentPrice, "f")
                if item.currentPrice is not None
                else None,
                notional=format(item.notional, "f")
                if item.notional is not None
                else None,
                leverage=format(item.leverage, "f")
                if item.leverage is not None
                else None,
                position_margin=format(item.positionMargin, "f")
                if item.positionMargin is not None
                else None,
                estimated_pnl=format(item.estimatedPnl, "f")
                if item.estimatedPnl is not None
                else None,
                price_updated_at=item.priceUpdatedAt,
                confidence=item.confidence,
                status=item.status,
                as_of_event_time=item.asOfEventTime,
                stale_since=item.staleSince,
                source_updated_at=item.updatedAt.astimezone(UTC),
            )
        )
    if payload.account is not None:
        account = db.get(PositionAccountSnapshot, subscription_id)
        if account is None:
            account = PositionAccountSnapshot(subscription_id=subscription_id)
            db.add(account)
        account.margin_balance = (
            format(payload.account.marginBalance, "f")
            if payload.account.marginBalance is not None
            else None
        )
        account.source_updated_at = payload.account.updatedAt.astimezone(UTC)
    if payload.operations is not None:
        existing_operations = {
            (operation.source_record_id, operation.revision): operation
            for operation in db.scalars(
                select(PositionOperation).where(
                    PositionOperation.subscription_id == subscription_id
                )
            ).all()
        }
        incoming_keys = {
            (item.sourceRecordId, item.revision) for item in payload.operations
        }
        for key, operation in existing_operations.items():
            if key not in incoming_keys:
                db.delete(operation)
        for item in payload.operations:
            key = (item.sourceRecordId, item.revision)
            operation = existing_operations.get(key)
            if operation is None:
                operation = PositionOperation(
                    subscription_id=subscription_id,
                    source_record_id=item.sourceRecordId,
                    revision=item.revision,
                )
                db.add(operation)
            operation.action = item.action
            operation.effective_action = item.effectiveAction
            operation.symbol = item.symbol
            operation.position_side = item.positionSide
            operation.quantity = (
                format(item.quantity, "f") if item.quantity is not None else None
            )
            operation.price = (
                format(item.price, "f") if item.price is not None else None
            )
            operation.amount = (
                format(item.amount, "f") if item.amount is not None else None
            )
            operation.leverage = (
                format(item.leverage, "f") if item.leverage is not None else None
            )
            operation.realized_pnl = (
                format(item.realizedPnl, "f")
                if item.realizedPnl is not None
                else None
            )
            operation.event_time = item.eventTime.astimezone(UTC)
    db.commit()
    response = {"count": len(payload.positions)}
    if payload.operations is not None:
        response["operationCount"] = len(payload.operations)
    return response
