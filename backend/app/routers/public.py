from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import KolProfile, Subscription
from app.routers.auth import require_authenticated
from app.services.collector_health import collector_health_payload
from app.services.signal_feed import signal_detail, signal_page, visible_public_assets


router = APIRouter(prefix="/api", dependencies=[Depends(require_authenticated)])


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
