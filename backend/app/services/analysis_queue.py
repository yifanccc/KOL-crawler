import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import RawPost, Signal, SignalAsset, SignalTag, Subscription
from app.services.assets import candidate_from_symbol
from app.services.ingestion import _get_or_create_asset
from app.services.notifications import dispatch_notifications
from app.services.structurer import FallbackStructurer, HeuristicStructurer, Structurer


def process_pending_posts(
    session: Session,
    structurer: Structurer | HeuristicStructurer | FallbackStructurer,
    limit: int = 10,
) -> int:
    rows = session.scalars(
        select(RawPost).where(RawPost.analysis_status == "pending").order_by(RawPost.id).limit(limit)
    ).all()
    completed = 0
    for raw_post in rows:
        if session.scalar(select(Signal).where(Signal.raw_post_id == raw_post.id)) is not None:
            raw_post.analysis_status = "completed"
            raw_post.analyzed_at = datetime.now(UTC)
            continue
        raw_post.analysis_status = "processing"
        raw_post.analysis_attempts += 1
        try:
            subscription = session.get(Subscription, raw_post.subscription_id)
            try:
                output_schema = (
                    json.loads(subscription.output_schema_json)
                    if subscription and subscription.output_schema_json
                    else None
                )
            except json.JSONDecodeError:
                output_schema = None
            structured = structurer.structure(
                raw_post.raw_text,
                system_prompt=subscription.system_prompt if subscription else None,
                user_prompt=subscription.user_prompt if subscription else None,
                output_schema=output_schema,
            )
            signal = Signal(
                raw_post_id=raw_post.id, subscription_id=raw_post.subscription_id,
                actionable=structured.stance in {"bullish", "bearish"}, stance=structured.stance,
                stance_cn=structured.stance_cn, summary=structured.summary_cn, summary_cn=structured.summary_cn,
                symbols_json=json.dumps(structured.symbols, ensure_ascii=False), market=structured.market,
                key_points_json=json.dumps(structured.key_points, ensure_ascii=False),
                evidence_json=json.dumps(structured.key_points, ensure_ascii=False),
                confidence="高" if structured.confidence >= 75 else "中" if structured.confidence >= 45 else "低",
                confidence_score=structured.confidence, importance=structured.importance,
                tags_json=json.dumps(structured.tags, ensure_ascii=False), action_hint=structured.action_hint,
                source_language=structured.source_language, translated_text_cn=structured.translated_text_cn,
                risk_warning=structured.risk_warning, risk_notes=structured.risk_warning,
                structured_json=structured.model_dump_json(), structured_status="fallback" if structured.used_fallback else "ok",
            )
            session.add(signal)
            session.flush()
            for symbol in structured.symbols:
                asset = _get_or_create_asset(session, candidate_from_symbol(symbol, structured.market))
                session.add(SignalAsset(signal_id=signal.id, asset_id=asset.id))
            for tag in structured.tags:
                session.add(SignalTag(signal_id=signal.id, tag=tag, source="llm"))
            session.flush()
            dispatch_notifications(session, signal)
            raw_post.analysis_status = "completed"
            raw_post.analysis_error = None
            raw_post.analyzed_at = datetime.now(UTC)
            completed += 1
        except Exception as exc:
            raw_post.analysis_status = "failed"
            raw_post.analysis_error = str(exc)[:2000]
        session.commit()
    return completed
