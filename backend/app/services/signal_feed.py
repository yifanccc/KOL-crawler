import json
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import and_, desc, exists, func, or_, select
from sqlalchemy.orm import Session

from app.models import (
    Asset,
    KolProfile,
    RawPost,
    Signal,
    SignalAsset,
    SignalTag,
    Subscription,
)


SignalVisibility = Literal["public", "private"]

STANCE_TO_CN = {
    "bullish": "多",
    "bearish": "空",
    "neutral": "中性",
    "unclear": "不明确",
    "多": "多",
    "空": "空",
    "中性": "中性",
    "无明确观点": "不明确",
    "不明确": "不明确",
}

STANCE_TO_RAW = {
    "多": "bullish",
    "空": "bearish",
    "中性": "neutral",
    "无明确观点": "unclear",
    "不明确": "unclear",
}

STANCE_FILTERS = {
    "long": "bullish",
    "short": "bearish",
    "neutral": "neutral",
    "watch": "neutral",
    "unknown": "unclear",
    "多": "bullish",
    "空": "bearish",
    "中性": "neutral",
    "不明确": "unclear",
}

TIME_RANGE_HOURS = {
    "1h": 1,
    "6h": 6,
    "24h": 24,
    "7d": 24 * 7,
}


def _json_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return []
    return [str(item) for item in payload] if isinstance(payload, list) else []


def _utc_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    else:
        value = value.astimezone(UTC)
    return value.isoformat().replace("+00:00", "Z")


def _importance(confidence: str | None, actionable: bool, assets: list[Asset]) -> int:
    score = 1
    if confidence == "高":
        score += 2
    elif confidence == "中":
        score += 1
    if actionable:
        score += 1
    if assets:
        score += 1
    return min(score, 5)


def _count_signals(db: Session, query) -> int:
    count_query = select(func.count()).select_from(query.order_by(None).subquery())
    return int(db.scalar(count_query) or 0)


def _scoped_signals_query(visibility: SignalVisibility):
    effective_subscription_id = func.coalesce(
        Signal.subscription_id, RawPost.subscription_id
    )
    query = select(Signal).join(RawPost, RawPost.id == Signal.raw_post_id)
    if visibility == "private":
        return query.join(
            Subscription, Subscription.id == effective_subscription_id
        ).where(Subscription.visibility == "private")
    return query.outerjoin(
        Subscription, Subscription.id == effective_subscription_id
    ).where(
        or_(
            Subscription.visibility == "public",
            and_(
                Signal.subscription_id.is_(None),
                RawPost.subscription_id.is_(None),
            ),
        )
    )


def _filtered_signals_query(
    *,
    visibility: SignalVisibility,
    kol_id: int | None,
    platform: str | None,
    requested_asset: str | None,
    tag: str | None,
    stance: str | None,
    time_range: str,
    min_importance: int,
):
    query = _scoped_signals_query(visibility)
    if kol_id is not None:
        query = query.where(Subscription.kol_profile_id == kol_id)
    if platform:
        query = query.where(func.lower(RawPost.platform) == platform.lower())
    if requested_asset:
        normalized_asset = requested_asset.lstrip("$").upper()
        query = query.where(
            exists(
                select(1)
                .select_from(SignalAsset)
                .join(Asset, Asset.id == SignalAsset.asset_id)
                .where(
                    SignalAsset.signal_id == Signal.id,
                    func.upper(Asset.symbol) == normalized_asset,
                )
            )
        )
    if tag:
        query = query.where(
            exists(
                select(1).where(
                    SignalTag.signal_id == Signal.id,
                    SignalTag.tag == tag,
                )
            )
        )
    if stance:
        query = query.where(Signal.stance == STANCE_FILTERS.get(stance, stance))
    if time_range != "all":
        query = query.where(
            RawPost.published_at
            >= datetime.now(UTC) - timedelta(hours=TIME_RANGE_HOURS[time_range])
        )
    if min_importance > 1:
        query = query.where(func.coalesce(Signal.importance, 1) >= min_importance)
    return query


def _signal_payload(session: Session, signal: Signal) -> dict:
    raw_post = session.get(RawPost, signal.raw_post_id)
    effective_subscription_id = signal.subscription_id or (
        raw_post.subscription_id if raw_post else None
    )
    subscription = (
        session.get(Subscription, effective_subscription_id)
        if effective_subscription_id is not None
        else None
    )
    assets = (
        session.execute(
            select(Asset)
            .join(SignalAsset, SignalAsset.asset_id == Asset.id)
            .where(SignalAsset.signal_id == signal.id)
        )
        .scalars()
        .all()
    )
    signal_tags = (
        session.execute(
            select(SignalTag.tag).where(SignalTag.signal_id == signal.id)
        )
        .scalars()
        .all()
    )
    evidence = _json_list(signal.key_points_json or signal.evidence_json)
    kol = (
        session.get(KolProfile, subscription.kol_profile_id)
        if subscription and subscription.kol_profile_id
        else None
    )
    tags = list(dict.fromkeys(_json_list(signal.tags_json) + list(signal_tags)))
    stance_cn = signal.stance_cn or STANCE_TO_CN.get(signal.stance, "不明确")
    stance_raw = (
        signal.stance
        if signal.stance in STANCE_TO_CN
        else STANCE_TO_RAW.get(signal.stance, "unclear")
    )
    summary_cn = signal.summary_cn or signal.summary
    confidence_score = signal.confidence_score
    return {
        "id": signal.id,
        "title": f"{', '.join(asset.symbol for asset in assets) or 'Market'} {stance_cn}",
        "sourceName": raw_post.author_handle if raw_post else "unknown",
        "kol": {
            "id": kol.id,
            "platform": subscription.platform,
            "displayName": (raw_post.author_name if raw_post else None)
            or kol.display_name,
            "handle": (raw_post.author_handle if raw_post else None)
            or kol.display_name,
            "avatarUrl": kol.avatar_url,
            "description": kol.description,
            "primaryMarket": kol.primary_market,
        }
        if kol
        else None,
        "platform": (raw_post.platform if raw_post else "x").upper(),
        "summary": summary_cn,
        "summaryCn": summary_cn,
        "translation": signal.translated_text_cn or summary_cn,
        "stance": stance_cn,
        "stanceRaw": stance_raw,
        "confidence": (
            confidence_score
            if confidence_score is not None
            else signal.confidence or "低"
        ),
        "modelConfidence": (
            f"{confidence_score}%"
            if confidence_score is not None
            else signal.confidence or "低"
        ),
        "promptVersion": signal.prompt_version or "default-v1",
        "ageLabel": "live",
        "tags": tags,
        "evidence": evidence,
        "rawText": raw_post.raw_text if raw_post else None,
        "importance": signal.importance
        or _importance(signal.confidence, signal.actionable, assets),
        "assets": [
            asset.symbol if asset.market != "US_STOCK" else f"${asset.symbol}"
            for asset in assets
        ],
        "url": raw_post.url if raw_post else None,
        "publishedAt": _utc_iso(raw_post.published_at if raw_post else None),
        "kolId": subscription.kol_profile_id if subscription else None,
        "actionable": signal.actionable,
        "market": signal.market or "unknown",
        "actionHint": signal.action_hint,
        "sourceLanguage": signal.source_language,
        "riskWarning": signal.risk_warning or signal.risk_notes,
        "structuredStatus": signal.structured_status,
    }


def signal_page(
    db: Session,
    *,
    visibility: SignalVisibility,
    kol_id: int | None,
    platform: str | None,
    asset: str | None,
    tag: str | None,
    stance: str | None,
    actionable: bool | None,
    time_range: str,
    min_importance: int,
    limit: int,
    offset: int,
) -> dict:
    scope_query = _scoped_signals_query(visibility)
    base_query = _filtered_signals_query(
        visibility=visibility,
        kol_id=kol_id,
        platform=platform,
        requested_asset=asset,
        tag=tag,
        stance=stance,
        time_range=time_range,
        min_importance=min_importance,
    )
    overall_total = _count_signals(db, scope_query)
    actionable_total = _count_signals(
        db,
        base_query.where(Signal.actionable.is_(True)),
    )
    filtered_query = (
        base_query.where(Signal.actionable.is_(actionable))
        if actionable is not None
        else base_query
    )
    total = _count_signals(db, filtered_query)
    signals = db.scalars(
        filtered_query
        .order_by(desc(RawPost.published_at), desc(Signal.id))
        .offset(offset)
        .limit(limit)
    ).all()
    return {
        "items": [_signal_payload(db, signal) for signal in signals],
        "total": total,
        "overallTotal": overall_total,
        "actionableTotal": actionable_total,
        "limit": limit,
        "offset": offset,
    }


def signal_detail(
    db: Session, *, visibility: SignalVisibility, signal_id: int
) -> dict | None:
    signal = db.scalar(
        _scoped_signals_query(visibility).where(Signal.id == signal_id)
    )
    return _signal_payload(db, signal) if signal is not None else None


def visible_public_assets(db: Session) -> list[Asset]:
    public_signal_ids = _scoped_signals_query("public").with_only_columns(Signal.id)
    has_any_signal = exists(
        select(1).where(SignalAsset.asset_id == Asset.id)
    )
    has_public_signal = exists(
        select(1).where(
            SignalAsset.asset_id == Asset.id,
            SignalAsset.signal_id.in_(public_signal_ids),
        )
    )
    return db.scalars(
        select(Asset)
        .where(or_(~has_any_signal, has_public_signal))
        .order_by(Asset.market, Asset.symbol)
    ).all()
