import json
from collections import Counter
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
from app.services.trade_structurer import PositionAfter, PositionChange, TradePayload

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


def _leverage(value: Decimal | str | None) -> str:
    return f"{_quantity(value)}x" if value is not None else "数据源未提供"


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


def _position_state(state: PositionAfter) -> str:
    side_labels = {
        "LONG": "多",
        "SHORT": "空",
        "FLAT": "空仓",
        "UNKNOWN": "未知",
    }
    label = side_labels[state.side]
    if state.side == "FLAT":
        return label
    return f"{label} {_quantity(state.quantity)}"


def _position_delta(change: PositionChange) -> str:
    if change.before.quantity is None or change.after.quantity is None:
        return ""
    delta = change.after.quantity - change.before.quantity
    if delta == 0:
        return ""
    sign = "+" if delta > 0 else ""
    return f"（{sign}{_quantity(delta)}）"


def _batch_time_text(trades: list[TradePayload]) -> str:
    times = sorted(trade.event_time.astimezone(SHANGHAI) for trade in trades)
    first = times[0].strftime("%Y-%m-%d %H:%M:%S")
    last = times[-1].strftime("%Y-%m-%d %H:%M:%S")
    return first if first == last else f"{first} 至 {last}"


def _snapshot_matches(position: PositionEstimate | None, state: PositionAfter) -> bool:
    if position is None or position.side != state.side:
        return False

    def equal_decimal(stored: str | None, expected: Decimal | None) -> bool:
        return (
            stored is None and expected is None
        ) or (
            stored is not None
            and expected is not None
            and Decimal(stored) == expected
        )

    return all(
        [
            equal_decimal(position.quantity, state.quantity),
            equal_decimal(position.entry_price, state.entry_price),
            equal_decimal(position.leverage, state.leverage),
        ]
    )


def _trade_batch_notification(
    session: Session,
    raw_posts: list[RawPost],
    trades: list[TradePayload],
) -> tuple[str, str] | None:
    if not trades or not trades[0].position_changes:
        return None
    reference_changes = trades[0].position_changes
    if any(trade.position_changes != reference_changes for trade in trades[1:]):
        return None

    subscription_id = raw_posts[0].subscription_id
    if subscription_id is None:
        return None
    subscription = session.get(Subscription, subscription_id)
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
    positions_by_key = {
        (position.symbol, position.position_side): position for position in positions
    }
    snapshot_is_current = all(
        _snapshot_matches(
            positions_by_key.get((change.symbol, change.position_side)),
            change.after,
        )
        for change in reference_changes
    )
    account = session.get(PositionAccountSnapshot, subscription.id)
    summary = position_summary_payload(subscription, kol, account, positions)
    action_labels = {
        "OPEN": "开仓",
        "ADD": "加仓",
        "REDUCE": "减仓",
        "CLOSE": "平仓",
        "REVERSE": "反手",
        "CORRECTION": "交易修订",
    }
    side_labels = {"LONG": "多", "SHORT": "空", "UNKNOWN": "未知"}
    trades_by_key: dict[tuple[str, str], list[TradePayload]] = {}
    for trade in trades:
        trades_by_key.setdefault((trade.symbol, trade.position_side), []).append(trade)

    lines = [f"变动时间：{_batch_time_text(trades)}｜共 {len(trades)} 笔成交"]
    for change in reference_changes:
        key = (change.symbol, change.position_side)
        grouped_trades = trades_by_key.get(key, [])
        current = positions_by_key.get(key) if snapshot_is_current else None
        lines.extend(
            [
                "",
                f"{change.symbol} {side_labels[change.position_side]}",
                (
                    f"仓位：{_position_state(change.before)} → "
                    f"{_position_state(change.after)}{_position_delta(change)}"
                ),
                (
                    f"推测开仓均价：{_number(change.before.entry_price)} → "
                    f"{_number(change.after.entry_price)}"
                ),
            ]
        )
        if grouped_trades:
            action_counts = Counter(action_labels[trade.action] for trade in grouped_trades)
            action_text = "、".join(
                f"{action} {count} 笔" for action, count in action_counts.items()
            )
            quantities = [trade.quantity for trade in grouped_trades]
            total_quantity = (
                sum(quantities, Decimal("0"))
                if all(quantity is not None for quantity in quantities)
                else None
            )
            amounts = [
                trade.quantity * trade.price
                if trade.quantity is not None and trade.price is not None
                else None
                for trade in grouped_trades
            ]
            total_amount = (
                sum(amounts, Decimal("0"))
                if all(amount is not None for amount in amounts)
                else None
            )
            average_price = (
                total_amount / total_quantity
                if total_amount is not None
                and total_quantity is not None
                and total_quantity > 0
                else None
            )
            lines.append(f"操作汇总：{action_text}")
            lines.append(
                f"成交数量合计 {_quantity(total_quantity)}｜"
                f"成交均价 {_number(average_price)}｜成交额合计 {_money(total_amount)}"
            )
        else:
            lines.append("操作汇总：由反手操作联动关闭")

        current_state = (
            f"{side_labels.get(current.side, current.side)} {_quantity(current.quantity)}"
            if current is not None
            else _position_state(change.after)
        )
        current_entry = current.entry_price if current is not None else change.after.entry_price
        current_leverage = current.leverage if current is not None else change.after.leverage
        lines.append(
            f"当前：{current_state}｜开仓 {_number(current_entry)}｜"
            f"现价 {_number(current.mark_price if current else None)}"
        )
        lines.append(
            f"持仓金额 {_money(current.notional if current else None)}｜"
            f"杠杆 {_leverage(current_leverage)}｜"
            f"预计盈亏 {_money(current.estimated_pnl if current else None, signed=True)}"
        )

    if snapshot_is_current:
        lines.extend(
            [
                "",
                f"KOL 当前：保证金余额 {_money(summary['marginBalance'])}",
                (
                    f"持仓总额（估算） {_money(summary['totalPositionNotional'])}｜"
                    f"仓位倍数（估算） "
                    f"{_account_multiple(summary['totalPositionNotional'], summary['marginBalance'])}｜"
                    f"预计盈亏 {_money(summary['estimatedPnl'], signed=True)}"
                ),
            ]
        )
    else:
        lines.extend(["", "KOL 当前：仓位快照尚未同步，本批变动以交易账本为准"])
    title = f"Binance Copy | {kol.display_name} | 仓位变动 {len(trades)} 笔"
    return title, "\n".join(lines)


def _ready_trade_batch(
    session: Session,
    raw_post: RawPost,
) -> tuple[list[RawPost], list[Signal], list[TradePayload]] | None:
    if (
        raw_post.subscription_id is None
        or raw_post.notification_batch_id is None
        or raw_post.notification_batch_size is None
    ):
        return None
    raw_posts = list(
        session.scalars(
            select(RawPost)
            .where(
                RawPost.subscription_id == raw_post.subscription_id,
                RawPost.notification_batch_id == raw_post.notification_batch_id,
            )
            .order_by(RawPost.id)
        ).all()
    )
    expected_size = raw_post.notification_batch_size
    if len(raw_posts) != expected_size or any(
        item.notification_batch_size != expected_size for item in raw_posts
    ):
        return None
    signals = list(
        session.scalars(
            select(Signal).where(
                Signal.raw_post_id.in_([item.id for item in raw_posts])
            )
        ).all()
    )
    signals_by_post = {signal.raw_post_id: signal for signal in signals}
    if len(signals_by_post) != expected_size:
        return None
    ordered_signals = [signals_by_post[item.id] for item in raw_posts]
    try:
        trades = [
            TradePayload.model_validate_json(item.raw_json)
            for item in raw_posts
            if item.raw_json is not None
        ]
    except ValueError:
        return None
    if len(trades) != expected_size or any(
        trade.collection_batch_id != raw_post.notification_batch_id
        or trade.collection_batch_size != expected_size
        for trade in trades
    ):
        return None
    return raw_posts, ordered_signals, trades


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
    raw_post = session.get(RawPost, signal.raw_post_id)
    eligible_signals = [signal]
    anchor_signal = signal
    formatted: tuple[str, str] | None = None
    if (
        raw_post is not None
        and raw_post.platform == "binance_copy"
        and raw_post.notification_batch_id is not None
    ):
        batch = _ready_trade_batch(session, raw_post)
        if batch is None:
            return 0
        raw_posts, eligible_signals, trades = batch
        anchor_signal = eligible_signals[0]
        formatted = _trade_batch_notification(session, raw_posts, trades)
        if formatted is None:
            return 0

    markets_by_signal = {
        item.id: _asset_markets(session, item) for item in eligible_signals
    }
    rules = session.scalars(
        select(NotificationRule).where(
            (NotificationRule.subscription_id == anchor_signal.subscription_id)
            | (NotificationRule.subscription_id.is_(None))
        )
    ).all()
    sent_count = 0
    for rule in rules:
        if not any(
            should_notify(item, rule, markets_by_signal[item.id])
            for item in eligible_signals
        ):
            continue
        if not rule.ntfy_server or not rule.ntfy_topic:
            continue
        try:
            with session.begin_nested():
                event = NotificationEvent(
                    signal_id=anchor_signal.id,
                    notification_rule_id=rule.id,
                    status="pending",
                )
                session.add(event)
                session.flush()
        except IntegrityError:
            continue
        try:
            title, message = formatted or _format_notification(session, signal)
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
