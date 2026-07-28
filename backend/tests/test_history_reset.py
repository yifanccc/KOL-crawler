from datetime import UTC, datetime

from sqlalchemy import func, select

from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models import (
    Asset,
    CollectorAgent,
    CrawlRun,
    KolProfile,
    ModelConfig,
    NotificationEvent,
    NotificationRule,
    RawPost,
    Signal,
    SignalAsset,
    SignalTag,
    Subscription,
)
from app.services.history_reset import reset_signal_history


def test_reset_signal_history_deletes_derived_data_and_preserves_configuration() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with SessionLocal.begin() as session:
        model = ModelConfig(
            name="custom",
            base_url="https://api.openai.com/v1",
            model="gpt-test",
            is_default=True,
        )
        kol = KolProfile(platform="x", display_name="configured-kol")
        session.add_all([model, kol])
        session.flush()
        subscription = Subscription(
            kol_profile_id=kol.id,
            platform="x",
            platform_handle="configured-kol",
            interval_minutes=1,
            system_prompt="用户修改的 system prompt",
            user_prompt="用户修改的 user prompt {raw_content}",
            prompt_version="custom-v1",
            model_config_id=model.id,
            checkpoint="old-checkpoint",
            last_checked_at=datetime(2026, 7, 12, tzinfo=UTC),
            last_success_at=datetime(2026, 7, 12, tzinfo=UTC),
            enabled=True,
        )
        session.add(subscription)
        session.flush()
        rule = NotificationRule(
            subscription_id=subscription.id,
            ntfy_server="https://ntfy.sh",
            ntfy_topic="private-topic",
            enabled=True,
        )
        session.add(rule)
        raw = RawPost(
            subscription_id=subscription.id,
            platform="x",
            external_id="dirty-post",
            raw_text="$BTC dirty",
            analysis_status="completed",
        )
        session.add(raw)
        session.flush()
        signal = Signal(
            raw_post_id=raw.id,
            subscription_id=subscription.id,
            actionable=True,
            stance="bullish",
            summary="dirty",
            structured_status="fallback",
        )
        asset = Asset(symbol="BTC", market="CRYPTO", asset_type="crypto")
        session.add_all([signal, asset])
        session.flush()
        session.add_all(
            [
                SignalAsset(signal_id=signal.id, asset_id=asset.id),
                SignalTag(signal_id=signal.id, tag="dirty", source="llm"),
                NotificationEvent(
                    signal_id=signal.id,
                    notification_rule_id=rule.id,
                    status="sent",
                ),
                CrawlRun(
                    subscription_id=subscription.id,
                    status="completed",
                    started_at=datetime(2026, 7, 12, tzinfo=UTC),
                ),
                CollectorAgent(
                    agent_id="home",
                    status="degraded",
                    providers_json="[]",
                    last_heartbeat_at=datetime(2026, 7, 12, tzinfo=UTC),
                ),
            ]
        )

    with SessionLocal.begin() as session:
        deleted = reset_signal_history(session)

    assert deleted == {
        "notification_events": 1,
        "signal_tags": 1,
        "signal_assets": 1,
        "signals": 1,
        "raw_posts": 1,
        "assets": 1,
        "crawl_runs": 1,
        "collector_agents": 1,
    }
    with SessionLocal() as session:
        for model_type in (
            NotificationEvent,
            SignalTag,
            SignalAsset,
            Signal,
            RawPost,
            Asset,
            CrawlRun,
            CollectorAgent,
        ):
            assert session.scalar(select(func.count()).select_from(model_type)) == 0
        preserved = session.scalar(select(Subscription))
        preserved_rule = session.scalar(select(NotificationRule))
        assert preserved.system_prompt == "用户修改的 system prompt"
        assert preserved.user_prompt == "用户修改的 user prompt {raw_content}"
        assert preserved.prompt_version == "custom-v1"
        assert preserved.checkpoint is None
        assert preserved.last_checked_at is None
        assert preserved.last_success_at is None
        assert preserved_rule.ntfy_server == "https://ntfy.sh"
        assert preserved_rule.ntfy_topic == "private-topic"
        assert session.scalar(select(func.count()).select_from(KolProfile)) == 1
        assert session.scalar(select(func.count()).select_from(ModelConfig)) == 1
