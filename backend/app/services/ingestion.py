import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.collectors.base import CollectorAdapter
from app.models import Asset, RawPost, Signal, SignalAsset, SignalTag, Subscription
from app.services.assets import AssetCandidate, candidate_from_symbol
from app.services.notifications import dispatch_notifications
from app.services.structurer import FallbackStructurer, HeuristicStructurer, Structurer


@dataclass(frozen=True)
class IngestionResult:
    fetched_count: int
    inserted_count: int
    structured_count: int
    checkpoint: str | None


def _get_or_create_asset(session: Session, candidate: AssetCandidate) -> Asset:
    asset = session.scalar(
        select(Asset).where(Asset.symbol == candidate.symbol, Asset.market == candidate.market)
    )
    if asset is not None:
        return asset
    asset = Asset(
        symbol=candidate.symbol,
        name=candidate.name,
        market=candidate.market,
        asset_type=candidate.asset_type,
    )
    session.add(asset)
    session.flush()
    return asset


def _next_check(interval_minutes: int) -> datetime:
    return datetime.now(UTC) + timedelta(minutes=max(interval_minutes, 1))


def ingest_subscription(
    session: Session,
    subscription: Subscription,
    collector: CollectorAdapter,
    structurer: Structurer | HeuristicStructurer | FallbackStructurer,
    limit: int = 20,
) -> IngestionResult:
    posts = collector.fetch_new(subscription.platform_handle, subscription.checkpoint, limit=limit)
    inserted_count = 0
    structured_count = 0
    latest_checkpoint = subscription.checkpoint

    for post in posts:
        existing = session.scalar(
            select(RawPost).where(
                RawPost.platform == post.platform,
                RawPost.external_id == post.external_id,
            )
        )
        if existing is not None:
            latest_checkpoint = post.external_id
            continue

        raw_post = RawPost(
            platform=post.platform,
            external_id=post.external_id,
            url=post.url,
            author_handle=post.author_handle,
            author_name=post.author_name,
            published_at=post.published_at,
            raw_text=post.raw_text,
            raw_json=post.raw_json,
        )
        session.add(raw_post)
        try:
            session.flush()
        except IntegrityError:
            session.rollback()
            latest_checkpoint = post.external_id
            continue

        inserted_count += 1
        try:
            if subscription.output_schema_json:
                try:
                    output_schema = json.loads(subscription.output_schema_json)
                except json.JSONDecodeError:
                    output_schema = {}
            else:
                output_schema = None
            structured = structurer.structure(
                post.raw_text,
                system_prompt=subscription.system_prompt or subscription.prompt,
                user_prompt=subscription.user_prompt,
                output_schema=output_schema,
            )
            confidence_label = "高" if structured.confidence >= 75 else "中" if structured.confidence >= 45 else "低"
            prompt_version = subscription.prompt_version or (
                "custom-v1"
                if subscription.system_prompt or subscription.user_prompt or subscription.output_schema_json
                else "default-v2"
            )
            signal = Signal(
                raw_post_id=raw_post.id,
                subscription_id=subscription.id,
                actionable=structured.stance in {"bullish", "bearish"},
                stance=structured.stance,
                stance_cn=structured.stance_cn,
                summary=structured.summary_cn,
                summary_cn=structured.summary_cn,
                symbols_json=json.dumps(structured.symbols, ensure_ascii=False),
                market=structured.market,
                key_points_json=json.dumps(structured.key_points, ensure_ascii=False),
                evidence_json=json.dumps(structured.key_points, ensure_ascii=False),
                confidence=confidence_label,
                confidence_score=structured.confidence,
                importance=structured.importance,
                tags_json=json.dumps(structured.tags, ensure_ascii=False),
                action_hint=structured.action_hint,
                source_language=structured.source_language,
                translated_text_cn=structured.translated_text_cn,
                risk_warning=structured.risk_warning,
                risk_notes=structured.risk_warning,
                prompt_version=prompt_version,
                structured_json=structured.model_dump_json(),
                structured_status="fallback" if structured.used_fallback else "ok",
            )
        except Exception as exc:
            signal = Signal(
                raw_post_id=raw_post.id,
                subscription_id=subscription.id,
                actionable=False,
                stance="unclear",
                stance_cn="不明确",
                summary="结构化处理失败，请查看原文。",
                summary_cn="结构化处理失败，请查看原文。",
                symbols_json="[]",
                market="unknown",
                key_points_json="[]",
                evidence_json="[]",
                confidence="低",
                confidence_score=0,
                importance=1,
                tags_json="[]",
                action_hint="请人工复核原文。",
                source_language="unknown",
                translated_text_cn="结构化处理失败，暂时无法生成中文翻译。",
                risk_warning="自动处理失败，不构成投资建议。",
                risk_notes=str(exc),
                prompt_version=subscription.prompt_version or "default-v2",
                structured_json=None,
                structured_status="failed",
            )
        session.add(signal)
        session.flush()

        structured_payload = json.loads(signal.structured_json) if signal.structured_json else {}
        for symbol in structured_payload.get("symbols", []):
            asset = _get_or_create_asset(
                session,
                candidate_from_symbol(str(symbol), str(structured_payload.get("market", "unknown"))),
            )
            session.add(SignalAsset(signal_id=signal.id, asset_id=asset.id))
        for tag in structured_payload.get("tags", []):
            session.add(SignalTag(signal_id=signal.id, tag=str(tag), source="llm"))

        session.flush()
        dispatch_notifications(session, signal)
        structured_count += 1
        latest_checkpoint = post.external_id

    subscription.checkpoint = latest_checkpoint
    subscription.last_checked_at = datetime.now(UTC)
    if inserted_count or posts:
        subscription.last_success_at = datetime.now(UTC)
    subscription.next_check_at = _next_check(subscription.interval_minutes)
    session.commit()
    return IngestionResult(
        fetched_count=len(posts),
        inserted_count=inserted_count,
        structured_count=structured_count,
        checkpoint=latest_checkpoint,
    )
