import json
from unittest.mock import Mock

import pytest
from sqlalchemy import select

from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models import RawPost, Signal, SignalTag, Subscription
from app.services.analysis_queue import process_pending_posts
from app.services.trade_structurer import build_trade_signal_fields


ACCOUNT_ID = "5075281354358777856"


def trade_payload(**overrides) -> dict:
    payload = {
        "schemaVersion": 1,
        "platform": "binance_copy",
        "accountId": ACCOUNT_ID,
        "sourceRecordId": "record-2",
        "revision": "r1",
        "action": "REDUCE",
        "effectiveAction": "DECREASE",
        "symbol": "BTCUSDT",
        "positionSide": "LONG",
        "quantity": "0.04",
        "price": "50000",
        "leverage": None,
        "eventTime": "2026-08-09T02:00:00Z",
        "positionAfter": {
            "side": "LONG",
            "quantity": "0.11",
            "confidence": "HIGH",
            "status": "ACTIVE",
        },
        "sourceRecord": {"orderUpdateTime": 1786240800000},
    }
    payload.update(overrides)
    return payload


def add_trade_post(
    session,
    *,
    payload: dict | None = None,
    visibility: str = "private",
    subscription_platform: str = "binance_copy",
    raw_platform: str = "binance_copy",
    external_id: str = f"{ACCOUNT_ID}:record-2:r1",
    with_subscription: bool = True,
) -> RawPost:
    subscription_id = None
    if with_subscription:
        subscription = Subscription(
            platform=subscription_platform,
            platform_account_id=ACCOUNT_ID,
            platform_handle="熬鹰资本",
            visibility=visibility,
            interval_minutes=10,
        )
        session.add(subscription)
        session.flush()
        subscription_id = subscription.id
    raw_post = RawPost(
        subscription_id=subscription_id,
        platform=raw_platform,
        external_id=external_id,
        author_handle="熬鹰资本",
        author_name="熬鹰资本",
        raw_text="熬鹰资本 BTCUSDT 减仓",
        raw_json=json.dumps(payload or trade_payload(), ensure_ascii=False),
        analysis_status="pending",
    )
    session.add(raw_post)
    session.commit()
    return raw_post


def reset_database() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def test_trade_post_is_structured_deterministically_without_model_call(
    monkeypatch,
) -> None:
    reset_database()
    structurer = Mock()
    structurer.structure.side_effect = AssertionError("LLM must not run")
    monkeypatch.setattr(
        "app.services.analysis_queue.dispatch_notifications", lambda *_args: 0
    )

    with SessionLocal() as session:
        add_trade_post(session)

        assert process_pending_posts(session, structurer) == 1

        signal = session.scalar(select(Signal))
        assert signal is not None
        tags = session.scalars(select(SignalTag).where(SignalTag.signal_id == signal.id)).all()

    structurer.structure.assert_not_called()
    assert signal.actionable is True
    assert signal.stance == "neutral"
    assert signal.stance_cn == "中性"
    assert signal.structured_status == "deterministic"
    assert signal.confidence == "高"
    assert signal.confidence_score == 90
    assert signal.importance == 3
    assert signal.symbols_json == '["BTCUSDT"]'
    assert signal.summary_cn == (
        "熬鹰资本 BTCUSDT 减仓，方向 多，本次数量 0.04；"
        "推测持仓 LONG 0.11（置信度 高）"
    )
    assert "持仓由交易记录推测" in signal.risk_warning
    assert tags
    assert {tag.source for tag in tags} == {"deterministic"}


@pytest.mark.parametrize(
    ("action", "effective_action", "side", "stance", "importance"),
    [
        ("OPEN", "INCREASE", "LONG", "bullish", 4),
        ("ADD", "INCREASE", "SHORT", "bearish", 3),
        ("REVERSE", "REVERSE", "LONG", "bullish", 4),
        ("REDUCE", "DECREASE", "LONG", "neutral", 3),
        ("CLOSE", "DECREASE", "SHORT", "neutral", 4),
        ("CORRECTION", "INCREASE", "LONG", "neutral", 2),
    ],
)
def test_trade_action_mapping_matches_reconciled_binance_events(
    action: str,
    effective_action: str,
    side: str,
    stance: str,
    importance: int,
) -> None:
    subscription = Subscription(
        platform="binance_copy",
        platform_account_id=ACCOUNT_ID,
        platform_handle="熬鹰资本",
        visibility="private",
        interval_minutes=10,
    )
    raw_post = RawPost(
        platform="binance_copy",
        external_id=f"{ACCOUNT_ID}:record-2:r1",
        author_name="熬鹰资本",
        raw_text="trade",
        raw_json=json.dumps(
            trade_payload(
                action=action,
                effectiveAction=effective_action,
                positionSide=side,
            )
        ),
    )

    fields = build_trade_signal_fields(raw_post, subscription)

    assert fields.actionable is True
    assert fields.structured.stance == stance
    assert fields.structured.importance == importance
    assert fields.structured_status == "deterministic"
    assert fields.tag_source == "deterministic"


@pytest.mark.parametrize(
    "case",
    [
        "schema_version",
        "numeric_decimal",
        "missing_source_record_id",
        "action_mismatch",
        "account_mismatch",
        "external_id_mismatch",
        "raw_platform_mismatch",
        "subscription_platform_mismatch",
        "public_subscription",
        "missing_subscription",
    ],
)
def test_invalid_trade_integrity_fails_without_model_fallback(case: str) -> None:
    reset_database()
    structurer = Mock()
    structurer.structure.side_effect = AssertionError("LLM must not run")
    payload = trade_payload()
    kwargs = {}
    if case == "schema_version":
        payload["schemaVersion"] = 2
    elif case == "numeric_decimal":
        payload["quantity"] = 0.04
    elif case == "missing_source_record_id":
        payload.pop("sourceRecordId")
    elif case == "action_mismatch":
        payload["effectiveAction"] = "INCREASE"
    elif case == "account_mismatch":
        payload["accountId"] = "11111111"
    elif case == "external_id_mismatch":
        kwargs["external_id"] = "wrong"
    elif case == "raw_platform_mismatch":
        kwargs["raw_platform"] = "x"
    elif case == "subscription_platform_mismatch":
        kwargs["subscription_platform"] = "x"
    elif case == "public_subscription":
        kwargs["visibility"] = "public"
    elif case == "missing_subscription":
        kwargs["with_subscription"] = False

    with SessionLocal() as session:
        raw_post = add_trade_post(session, payload=payload, **kwargs)

        assert process_pending_posts(session, structurer) == 0

        session.refresh(raw_post)
        assert raw_post.analysis_status == "failed"
        assert raw_post.analysis_error
        assert session.scalar(select(Signal)) is None

    structurer.structure.assert_not_called()
