from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import (
    KolProfile,
    PositionAccountSnapshot,
    PositionEstimate,
    PositionOperation,
    Subscription,
)
from app.models.subscription import TRADE_PLATFORMS
from app.routers.auth import require_authenticated
from app.services.collector_health import collector_health_payload
from app.services.signal_feed import signal_detail, signal_page, visible_public_assets
from app.services.position_monitor import (
    operation_payload,
    position_payload,
    position_summary_payload,
)


router = APIRouter(prefix="/api", dependencies=[Depends(require_authenticated)])


def _utc_text(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


@router.get("/signals")
def list_signals(
    kol_id: int | None = None,
    asset: str | None = None,
    symbol: str | None = None,
    tag: str | None = None,
    stance: str | None = None,
    actionable: bool | None = None,
    platform: str | None = None,
    time_range: Literal["all", "1h", "6h", "24h", "7d"] = "all",
    min_importance: int = Query(default=1, ge=1, le=5),
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    return signal_page(
        db,
        visibility="public",
        kol_id=kol_id,
        platform=platform,
        asset=asset or symbol,
        tag=tag,
        stance=stance,
        actionable=actionable,
        time_range=time_range,
        min_importance=min_importance,
        limit=limit,
        offset=offset,
    )


@router.get("/signals/{signal_id}")
def get_signal(signal_id: int, db: Session = Depends(get_db)) -> dict:
    return {
        "item": signal_detail(db, visibility="public", signal_id=signal_id)
    }


@router.get("/kols")
def list_kols(db: Session = Depends(get_db)) -> dict:
    rows = db.scalars(
        select(KolProfile)
        .join(Subscription, Subscription.kol_profile_id == KolProfile.id)
        .where(
            Subscription.deleted_at.is_(None),
            Subscription.visibility == "public",
        )
        .distinct()
        .order_by(KolProfile.id)
    ).all()
    return {
        "items": [
            {
                "id": row.id,
                "platform": row.platform,
                "displayName": row.display_name,
                "handle": row.display_name,
                "avatarUrl": row.avatar_url,
                "description": row.description,
                "primaryMarket": row.primary_market,
            }
            for row in rows
        ]
    }


@router.get("/collector-health")
def collector_health(db: Session = Depends(get_db)) -> dict:
    return {"item": collector_health_payload(db)}


@router.get("/positions")
def list_positions(db: Session = Depends(get_db)) -> dict:
    rows = db.execute(
        select(PositionEstimate, Subscription, KolProfile)
        .join(
            Subscription,
            Subscription.id == PositionEstimate.subscription_id,
        )
        .join(KolProfile, KolProfile.id == Subscription.kol_profile_id)
        .where(
            Subscription.deleted_at.is_(None),
            Subscription.visibility == "private",
        )
        .order_by(
            PositionEstimate.symbol,
            PositionEstimate.position_side,
        )
    ).all()
    return {
        "items": [
            {
                "subscriptionId": subscription.id,
                "kol": {"id": kol.id, "displayName": kol.display_name},
                "platform": subscription.platform,
                "accountId": subscription.platform_account_id,
                "symbol": position.symbol,
                "positionSide": position.position_side,
                "side": position.side,
                "quantity": position.quantity,
                "confidence": position.confidence,
                "status": position.status,
                "asOfEventTime": _utc_text(position.as_of_event_time),
                "staleSince": _utc_text(position.stale_since),
                "updatedAt": _utc_text(position.source_updated_at),
            }
            for position, subscription, kol in rows
        ]
    }


def _trade_subscription(
    db: Session,
    subscription_id: int,
) -> tuple[Subscription, KolProfile]:
    row = db.execute(
        select(Subscription, KolProfile)
        .join(KolProfile, KolProfile.id == Subscription.kol_profile_id)
        .where(
            Subscription.id == subscription_id,
            Subscription.deleted_at.is_(None),
            Subscription.visibility == "private",
            Subscription.platform.in_(TRADE_PLATFORMS),
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Position KOL not found")
    return row


def _position_summary(
    db: Session,
    subscription: Subscription,
    kol: KolProfile,
) -> tuple[dict, list[PositionEstimate]]:
    positions = list(
        db.scalars(
            select(PositionEstimate)
            .where(PositionEstimate.subscription_id == subscription.id)
            .order_by(PositionEstimate.symbol, PositionEstimate.position_side)
        ).all()
    )
    account = db.get(PositionAccountSnapshot, subscription.id)
    return position_summary_payload(subscription, kol, account, positions), positions


@router.get("/position-kols")
def list_position_kols(db: Session = Depends(get_db)) -> dict:
    rows = db.execute(
        select(Subscription, KolProfile)
        .join(KolProfile, KolProfile.id == Subscription.kol_profile_id)
        .where(
            Subscription.deleted_at.is_(None),
            Subscription.visibility == "private",
            Subscription.platform.in_(TRADE_PLATFORMS),
        )
        .order_by(KolProfile.display_name, Subscription.id)
    ).all()
    subscription_ids = [subscription.id for subscription, _ in rows]
    positions_by_subscription: dict[int, list[PositionEstimate]] = {
        subscription_id: [] for subscription_id in subscription_ids
    }
    accounts_by_subscription: dict[int, PositionAccountSnapshot] = {}
    if subscription_ids:
        for position in db.scalars(
            select(PositionEstimate).where(
                PositionEstimate.subscription_id.in_(subscription_ids)
            )
        ).all():
            positions_by_subscription[position.subscription_id].append(position)
        accounts_by_subscription = {
            account.subscription_id: account
            for account in db.scalars(
                select(PositionAccountSnapshot).where(
                    PositionAccountSnapshot.subscription_id.in_(subscription_ids)
                )
            ).all()
        }
    return {
        "items": [
            position_summary_payload(
                subscription,
                kol,
                accounts_by_subscription.get(subscription.id),
                positions_by_subscription[subscription.id],
            )
            for subscription, kol in rows
        ]
    }


@router.get("/position-kols/{subscription_id}")
def get_position_kol(
    subscription_id: int,
    db: Session = Depends(get_db),
) -> dict:
    subscription, kol = _trade_subscription(db, subscription_id)
    summary, positions = _position_summary(db, subscription, kol)
    return {
        "item": {
            "summary": summary,
            "positions": [
                position_payload(position)
                for position in positions
                if position.status != "FLAT"
            ],
        }
    }


@router.get("/position-kols/{subscription_id}/operations")
def list_position_operations(
    subscription_id: int,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    _trade_subscription(db, subscription_id)
    predicate = PositionOperation.subscription_id == subscription_id
    total = db.scalar(
        select(func.count()).select_from(PositionOperation).where(predicate)
    ) or 0
    rows = db.scalars(
        select(PositionOperation)
        .where(predicate)
        .order_by(desc(PositionOperation.event_time), desc(PositionOperation.id))
        .limit(limit)
        .offset(offset)
    ).all()
    return {
        "items": [operation_payload(row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/assets")
def list_assets(db: Session = Depends(get_db)) -> dict:
    rows = visible_public_assets(db)
    return {
        "items": [
            {
                "id": row.id,
                "symbol": row.symbol,
                "name": row.name,
                "market": row.market,
                "assetType": row.asset_type,
            }
            for row in rows
        ]
    }
