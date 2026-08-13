from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import RawPost, Subscription
from app.services.structurer import STANCE_CN, StructuredSignal


TradeAction = Literal["OPEN", "ADD", "REDUCE", "CLOSE", "REVERSE", "CORRECTION"]
EffectiveTradeAction = Literal[
    "INCREASE",
    "DECREASE",
    "OPEN",
    "ADD",
    "REDUCE",
    "CLOSE",
    "REVERSE",
]

MAX_DECIMAL_ABS = Decimal("1e30")


def _decimal_string(value: Any) -> Any:
    if value is None:
        return value
    if not isinstance(value, str) or not value or len(value) > 64:
        raise ValueError("decimal fields must be bounded JSON strings")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("decimal fields must be valid") from exc
    if not parsed.is_finite() or parsed < 0 or parsed > MAX_DECIMAL_ABS:
        raise ValueError("decimal fields must be finite and non-negative")
    return value


class PositionAfter(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    side: Literal["LONG", "SHORT", "FLAT", "UNKNOWN"]
    quantity: Decimal | None
    entry_price: Decimal | None = Field(default=None, alias="entryPrice")
    leverage: Decimal | None = None
    confidence: Literal["HIGH", "MEDIUM", "LOW", "UNKNOWN"]
    status: Literal["ACTIVE", "FLAT", "UNKNOWN", "STALE"]

    @field_validator("quantity", "entry_price", "leverage", mode="before")
    @classmethod
    def validate_decimal_string(cls, value: Any) -> Any:
        return _decimal_string(value)


class TradePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: Literal[1] = Field(alias="schemaVersion")
    platform: Literal["binance_copy"]
    account_id: str = Field(
        alias="accountId", min_length=8, max_length=32, pattern=r"^[0-9]+$"
    )
    source_record_id: str = Field(alias="sourceRecordId", min_length=1, max_length=255)
    revision: str = Field(min_length=1, max_length=128)
    action: TradeAction
    effective_action: EffectiveTradeAction = Field(alias="effectiveAction")
    symbol: str = Field(min_length=2, max_length=64, pattern=r"^[A-Z0-9._-]+$")
    position_side: Literal["LONG", "SHORT", "UNKNOWN"] = Field(
        alias="positionSide"
    )
    quantity: Decimal | None
    price: Decimal | None
    leverage: Decimal | None
    event_time: datetime = Field(alias="eventTime")
    position_after: PositionAfter = Field(alias="positionAfter")
    source_record: dict[str, Any] = Field(default_factory=dict, alias="sourceRecord")

    @field_validator("quantity", "price", "leverage", mode="before")
    @classmethod
    def validate_decimal_strings(cls, value: Any) -> Any:
        return _decimal_string(value)

    @field_validator("event_time")
    @classmethod
    def validate_event_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("eventTime must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_action_mapping(self) -> "TradePayload":
        compatible: dict[str, set[str]] = {
            "OPEN": {"OPEN", "INCREASE"},
            "ADD": {"ADD", "INCREASE"},
            "REDUCE": {"REDUCE", "DECREASE"},
            "CLOSE": {"CLOSE", "DECREASE"},
            "REVERSE": {"REVERSE"},
        }
        if self.action != "CORRECTION" and self.effective_action not in compatible[
            self.action
        ]:
            raise ValueError("action does not match effectiveAction")
        return self


@dataclass(frozen=True)
class TradeSignalFields:
    structured: StructuredSignal
    actionable: bool = True
    structured_status: Literal["deterministic"] = "deterministic"
    tag_source: Literal["deterministic"] = "deterministic"


def _decimal_text(value: Decimal | None) -> str:
    return format(value, "f") if value is not None else "未知"


def build_trade_signal_fields(
    raw_post: RawPost,
    subscription: Subscription | None,
) -> TradeSignalFields:
    if subscription is None:
        raise ValueError("Private trade subscription is required")
    if subscription.visibility != "private":
        raise ValueError("Trade subscription must be private")
    if raw_post.raw_json is None:
        raise ValueError("Trade payload is required")

    payload = TradePayload.model_validate_json(raw_post.raw_json)
    if raw_post.platform != payload.platform or subscription.platform != payload.platform:
        raise ValueError("Trade platform identity does not match")
    if subscription.platform_account_id != payload.account_id:
        raise ValueError("Trade account identity does not match")
    expected_external_id = (
        f"{payload.account_id}:{payload.source_record_id}:{payload.revision}"
    )
    if raw_post.external_id != expected_external_id:
        raise ValueError("Trade external identity does not match")

    action_labels = {
        "OPEN": "开仓",
        "ADD": "加仓",
        "REDUCE": "减仓",
        "CLOSE": "平仓",
        "REVERSE": "反手",
        "CORRECTION": "交易修订",
    }
    direction_labels = {"LONG": "多", "SHORT": "空", "UNKNOWN": "未知"}
    confidence_labels = {
        "HIGH": "高",
        "MEDIUM": "中",
        "LOW": "低",
        "UNKNOWN": "未知",
    }
    confidence_scores = {"HIGH": 90, "MEDIUM": 60, "LOW": 30, "UNKNOWN": 0}
    importance = {
        "OPEN": 4,
        "ADD": 3,
        "REDUCE": 3,
        "CLOSE": 4,
        "REVERSE": 4,
        "CORRECTION": 2,
    }
    stance = "neutral"
    if payload.action in {"OPEN", "ADD", "REVERSE"}:
        if payload.position_side == "LONG":
            stance = "bullish"
        elif payload.position_side == "SHORT":
            stance = "bearish"

    kol_name = raw_post.author_name or subscription.platform_handle
    action_label = action_labels[payload.action]
    direction_label = direction_labels[payload.position_side]
    position_confidence = confidence_labels[payload.position_after.confidence]
    summary = (
        f"{kol_name} {payload.symbol} {action_label}，方向 {direction_label}，"
        f"本次数量 {_decimal_text(payload.quantity)}；"
        f"推测持仓 {payload.position_after.side} "
        f"{_decimal_text(payload.position_after.quantity)}"
        f"（置信度 {position_confidence}）"
    )
    risk_warning = "持仓由交易记录推测，可能因记录缺失或延迟与实际不同。"
    structured = StructuredSignal(
        summary_cn=summary,
        stance=stance,
        stance_cn=STANCE_CN[stance],
        symbols=[payload.symbol],
        market="crypto",
        key_points=[
            f"已成交动作：{action_label}，方向 {direction_label}，数量 {_decimal_text(payload.quantity)}",
            (
                f"推测持仓：{payload.position_after.side} "
                f"{_decimal_text(payload.position_after.quantity)}，置信度 {position_confidence}"
            ),
        ],
        confidence=confidence_scores[payload.position_after.confidence],
        importance=importance[payload.action],
        tags=["Binance Copy", "交易记录", action_label],
        action_hint="仅用于跟踪已成交交易变化，不构成买卖建议。",
        source_language="zh",
        translated_text_cn=summary,
        risk_warning=risk_warning,
    )
    return TradeSignalFields(structured=structured)
