from sqlalchemy import select
from sqlalchemy.orm import Session

from app.collectors.base import CollectorAdapter
from app.collectors.factory import build_x_collectors
from app.core.config import get_settings
from app.models import KolProfile, ModelConfig, NotificationRule, Subscription
from app.models.subscription import DEFAULT_MONITOR_INTERVAL_MINUTES
from app.services.ingestion import ingest_subscription
from app.services.structurer import HeuristicStructurer, build_structurer

ALL_MARKETS = ["crypto", "us_stock", "a_share", "hk_stock", "macro", "unknown"]


def ensure_defaults(session: Session) -> Subscription:
    settings = get_settings()
    model_config = session.scalar(select(ModelConfig).where(ModelConfig.is_default.is_(True)))
    if model_config is None:
        model_config = ModelConfig(
            name="DeepSeek",
            base_url=settings.openai_base_url,
            api_key_encrypted=None,
            model=settings.openai_model,
            temperature=0.2,
            is_default=True,
        )
        session.add(model_config)
        session.flush()

    kol = session.scalar(
        select(KolProfile).where(
            KolProfile.platform == "x",
            KolProfile.display_name == settings.x_target_handle,
        )
    )
    if kol is None:
        kol = KolProfile(
            platform="x",
            display_name=settings.x_target_handle,
            description="AI/Semi supply-chain KOL monitored from X.",
            primary_market="US_STOCK",
        )
        session.add(kol)
        session.flush()

    subscription = session.scalar(
        select(Subscription).where(
            Subscription.platform == "x",
            Subscription.platform_handle == settings.x_target_handle,
        )
    )
    if subscription is None:
        subscription = Subscription(
            kol_profile_id=kol.id,
            platform="x",
            platform_handle=settings.x_target_handle,
            interval_minutes=DEFAULT_MONITOR_INTERVAL_MINUTES,
            prompt=(
                "你是金融交易 KOL 监控系统。请聚焦美股、加密货币和 A 股标的，"
                "提取观点、标的、依据、时间周期和置信度。"
            ),
            markets_json=json.dumps(ALL_MARKETS, ensure_ascii=False),
            prompt_version="default-v2",
            model_config_id=model_config.id,
            enabled=True,
        )
        session.add(subscription)
        session.flush()

    rule = session.scalar(select(NotificationRule).where(NotificationRule.subscription_id == subscription.id))
    if rule is None:
        rule = NotificationRule(
                subscription_id=subscription.id,
                ntfy_server=settings.ntfy_server,
                ntfy_topic=settings.ntfy_topic,
                ntfy_token_encrypted=settings.ntfy_token,
                min_confidence="中",
                require_asset=True,
                enabled=True,
            )
        session.add(rule)
    else:
        if not rule.ntfy_server and settings.ntfy_server:
            rule.ntfy_server = settings.ntfy_server
        if not rule.ntfy_topic and settings.ntfy_topic:
            rule.ntfy_topic = settings.ntfy_topic
        if not rule.ntfy_token_encrypted and settings.ntfy_token:
            rule.ntfy_token_encrypted = settings.ntfy_token

    if not subscription.markets_json:
        subscription.markets_json = json.dumps(ALL_MARKETS, ensure_ascii=False)
    if not subscription.prompt_version:
        subscription.prompt_version = "default-v2"

    session.commit()
    return subscription


def backfill_subscription(session: Session, subscription: Subscription) -> None:
    settings = get_settings()
    structurer = build_structurer()
    collectors: list[CollectorAdapter] = build_x_collectors(include_bootstrap=True)
    for collector in collectors:
        try:
            result = ingest_subscription(
                session=session,
                subscription=subscription,
                collector=collector,
                structurer=structurer,
                limit=settings.backfill_limit,
            )
            if result.fetched_count:
                return
        except Exception:
            session.rollback()
            if not isinstance(structurer, HeuristicStructurer):
                structurer = HeuristicStructurer()
            continue
import json
