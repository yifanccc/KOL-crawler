import json
from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    Asset,
    KolProfile,
    NotificationEvent,
    NotificationRule,
    PositionAccountSnapshot,
    PositionEstimate,
    RawPost,
    Signal,
    SignalAsset,
    Subscription,
)
from app.services.position_monitor import position_summary_payload
from app.services.trade_structurer import TradePayload

CONFIDENCE_RANK = {"低": 1, "中": 2, "高": 3, None: 0}
PLATFORM_LABELS = {
    "x": "X",
    "binance_square": "Binance Square",
    "binance_copy": "Binance Copy",
}
SHANGHAI = ZoneInfo("Asia/Shanghai")


def _json_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    return [str(item) for item in payload]


def should_notify(signal: Signal, rule: NotificationRule, asset_markets: list[str]) -> bool:
    if not rule.enabled or not signal.actionable:
        return False
    if rule.require_asset and not asset_markets:
        return False
    allowed_markets = _json_list(rule.allowed_markets_json)
    if allowed_markets and not any(market in allowed_markets for market in asset_markets):
        return False
    allowed_stances = _json_list(rule.allowed_stances_json)
    if allowed_stances and signal.stance not in allowed_stances:
        return False
    min_rank = CONFIDENCE_RANK.get(rule.min_confidence, 0)
    signal_rank = CONFIDENCE_RANK.get(signal.confidence, 0)
    return signal_rank >= min_rank


class NtfyClient:
    def publish(
        self,
        server: str,
        topic: str,
        title: str,
        message: str,
        token: str | None = None,
    ) -> None:
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        response = httpx.post(
            server.rstrip("/"),
            json={"topic": topic, "title": title, "message": message},
            headers=headers,
            timeout=15,
        )
        response.raise_for_status()


def _asset_markets(session: Session, signal: Signal) -> list[str]:
    return list(
        session.execute(
            select(Asset.market)
            .join(SignalAsset, SignalAsset.asset_id == Asset.id)
            .where(SignalAsset.signal_id == signal.id)
        )
        .scalars()
        .all()
    )


def _money(value: Decimal | str | None, *, signed: bool = False) -> str:
    if value is None:
        return "数据源未提供"
    decimal_value = value if isinstance(value, Decimal) else Decimal(value)
    sign = "+" if signed and decimal_value > 0 else ""
    return f"{sign}{decimal_value:,.2f} USDT"


def _number(value: Decimal | str | None, decimals: int = 2) -> str:
    if value is None:
        return "数据源未提供"
    decimal_value = value if isinstance(value, Decimal) else Decimal(value)
    return f"{decimal_value:,.{decimals}f}"


def _quantity(value: Decimal | str | None) -> str:
    if value is None:
        return "数据源未提供"
    decimal_value = value if isinstance(value, Decimal) else Decimal(value)
    return format(decimal_value.normalize(), "f")


def _account_multiple(
    total_notional: Decimal | str | None,
    margin_balance: Decimal | str | None,
) -> str:
    if total_notional is None or margin_balance is None:
        return "暂不可估算"
    notional_value = (
        total_notional if isinstance(total_notional, Decimal) else Decimal(total_notional)
    )
    margin_value = (
        margin_balance if isinstance(margin_balance, Decimal) else Decimal(margin_balance)
    )
    if margin_value <= 0:
        return "暂不可估算"
    return f"{notional_value / margin_value:,.2f}x"


def _trade_notification(
    session: Session,
    signal: Signal,
    raw_post: RawPost,
) -> str | None:
    if raw_post.raw_json is None or signal.subscription_id is None:
        return None
    try:
        trade = TradePayload.model_validate_json(raw_post.raw_json)
    except ValueError:
        return None
    subscription = session.get(Subscription, signal.subscription_id)
    if subscription is None or subscription.kol_profile_id is None:
        return None
    kol = session.get(KolProfile, subscription.kol_profile_id)
    if kol is None:
        return None
    positions = list(
        session.scalars(
            select(PositionEstimate).where(
                PositionEstimate.subscription_id == subscription.id
            )
        ).all()
    )
    account = session.get(PositionAccountSnapshot, subscription.id)
    summary = position_summary_payload(subscription, kol, account, positions)
    current = next(
        (
            position
            for position in positions
            if position.symbol == trade.symbol
            and position.position_side == trade.position_side
        ),
        None,
    )
    action_labels = {
        "OPEN": "开仓",
        "ADD": "加仓",
        "REDUCE": "减仓",
        "CLOSE": "平仓",
        "REVERSE": "反手",
        "CORRECTION": "交易修订",
    }
    side_labels = {
        "LONG": "多",
        "SHORT": "空",
        "FLAT": "空仓",
        "UNKNOWN": "未知",
    }
    amount = (
        trade.quantity * trade.price
        if trade.quantity is not None and trade.price is not None
        else None
    )
    current_side = (
        side_labels.get(current.side, current.side)
        if current is not None
        else side_labels.get(trade.position_after.side, trade.position_after.side)
    )
    current_quantity = (
        current.quantity if current is not None else trade.position_after.quantity
    )
    entry_price = (
        current.entry_price if current is not None else trade.position_after.entry_price
    )
    account_multiple = _account_multiple(
        summary["totalPositionNotional"], summary["marginBalance"]
    )
    return "\n".join(
        [
            (
                f"操作：{trade.symbol} {action_labels[trade.action]} "
                f"{side_labels[trade.position_side]}"
            ),
            (
                f"成交价格 {_number(trade.price)}｜成交数量 {_quantity(trade.quantity)}｜"
                f"操作金额 {_money(amount)}"
            ),
            f"品种当前：{current_side} {_quantity(current_quantity)}",
            (
                f"开仓 {_number(entry_price)}｜"
                f"现价 {_number(current.mark_price if current else None)}｜"
                f"预计盈亏 {_money(current.estimated_pnl if current else None, signed=True)}"
            ),
            f"KOL 当前：账户保证金余额 {_money(summary['marginBalance'])}",
            (
                f"已估算持仓总额 {_money(summary['totalPositionNotional'])}｜"
                f"仓位倍数（估算） {account_multiple}｜"
                f"预计盈亏 {_money(summary['estimatedPnl'], signed=True)}"
            ),
        ]
    )


def _format_notification(session: Session, signal: Signal) -> tuple[str, str]:
    raw_post = session.get(RawPost, signal.raw_post_id)
    platform = PLATFORM_LABELS.get(raw_post.platform, raw_post.platform) if raw_post else "未知平台"
    kol_name = (raw_post.author_name if raw_post else None) or "未知 KOL"
    published_at = raw_post.published_at if raw_post else None
    if published_at is not None:
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=UTC)
        published_text = published_at.astimezone(SHANGHAI).strftime("%Y-%m-%d %H:%M")
    else:
        published_text = "时间未知"
    if raw_post is not None and raw_post.platform == "binance_copy":
        trade_message = _trade_notification(session, signal, raw_post)
        if trade_message is not None:
            return f"{platform} | {kol_name} | {published_text}", trade_message
    symbols = _json_list(signal.symbols_json)
    summary = signal.summary_cn or signal.summary
    stance = signal.stance_cn or signal.stance
    asset_text = ", ".join(symbols) or "无"
    lines = [
        f"摘要：{summary}",
        f"标的：{asset_text}",
        f"方向：{stance}",
    ]
    return f"{platform} | {kol_name} | {published_text}", "\n".join(lines)


def dispatch_notifications(
    session: Session,
    signal: Signal,
    client: NtfyClient | None = None,
) -> int:
    client = client or NtfyClient()
    markets = _asset_markets(session, signal)
    rules = session.scalars(
        select(NotificationRule).where(
            (NotificationRule.subscription_id == signal.subscription_id)
            | (NotificationRule.subscription_id.is_(None))
        )
    ).all()
    sent_count = 0
    for rule in rules:
        if not should_notify(signal, rule, markets):
            continue
        if not rule.ntfy_server or not rule.ntfy_topic:
            continue
        try:
            with session.begin_nested():
                event = NotificationEvent(signal_id=signal.id, notification_rule_id=rule.id, status="pending")
                session.add(event)
                session.flush()
        except IntegrityError:
            continue
        try:
            title, message = _format_notification(session, signal)
            client.publish(
                server=rule.ntfy_server,
                topic=rule.ntfy_topic,
                title=title,
                message=message,
                token=rule.ntfy_token_encrypted,
            )
        except Exception as exc:
            event.status = "failed"
            event.error_message = str(exc)
            continue
        event.status = "sent"
        event.sent_at = datetime.now(UTC)
        sent_count += 1
    return sent_count
