import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse
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
from app.services.trade_structurer import PositionAfter, TradePayload

CONFIDENCE_RANK = {"低": 1, "中": 2, "高": 3, None: 0}
PLATFORM_LABELS = {
    "x": "X",
    "binance_square": "Binance Square",
    "binance_copy": "Binance Copy",
}
SHANGHAI = ZoneInfo("Asia/Shanghai")
NOTIFICATION_MAX_ATTEMPTS = 8
NOTIFICATION_RETRY_BASE_SECONDS = 60
NOTIFICATION_RETRY_MAX_SECONDS = 3600
NOTIFICATION_RETRY_AFTER_MAX_SECONDS = 86400


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
            trust_env=urlparse(server).hostname != "ntfy.sh",
        )
        response.raise_for_status()


def _utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _retry_after_seconds(exc: Exception, attempted_at: datetime) -> int | None:
    if not isinstance(exc, httpx.HTTPStatusError):
        return None
    value = exc.response.headers.get("Retry-After")
    if not value:
        return None
    try:
        seconds = int(value)
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
        seconds = int((_utc_datetime(retry_at) - attempted_at).total_seconds())
    return max(0, min(seconds, NOTIFICATION_RETRY_AFTER_MAX_SECONDS))


def _next_notification_attempt_at(
    exc: Exception,
    attempt_count: int,
    attempted_at: datetime,
) -> datetime | None:
    if attempt_count >= NOTIFICATION_MAX_ATTEMPTS:
        return None
    exponential_delay = min(
        NOTIFICATION_RETRY_BASE_SECONDS * (2 ** max(0, attempt_count - 1)),
        NOTIFICATION_RETRY_MAX_SECONDS,
    )
    retry_after = _retry_after_seconds(exc, attempted_at)
    delay_seconds = max(exponential_delay, retry_after or 0)
    return attempted_at + timedelta(seconds=delay_seconds)


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
        return "—"
    decimal_value = value if isinstance(value, Decimal) else Decimal(value)
    sign = "+" if signed and decimal_value > 0 else ""
    return f"{sign}{decimal_value:,.2f} USDT"


def _price(value: Decimal | str | None) -> str:
    if value is None:
        return "—"
    decimal_value = value if isinstance(value, Decimal) else Decimal(value)
    absolute = abs(decimal_value)
    decimals = 2 if absolute >= 100 else 4 if absolute >= 1 else 8
    return f"{decimal_value:,.{decimals}f}".rstrip("0").rstrip(".")


def _quantity(value: Decimal | str | None) -> str:
    if value is None:
        return "—"
    decimal_value = value if isinstance(value, Decimal) else Decimal(value)
    return format(decimal_value.normalize(), "f")


def _account_multiple(
    total_notional: Decimal | str | None,
    margin_balance: Decimal | str | None,
) -> str:
    if total_notional is None or margin_balance is None:
        return "—"
    notional_value = (
        total_notional if isinstance(total_notional, Decimal) else Decimal(total_notional)
    )
    margin_value = (
        margin_balance if isinstance(margin_balance, Decimal) else Decimal(margin_balance)
    )
    if margin_value <= 0:
        return "—"
    return f"{notional_value / margin_value:,.2f}x"


def _decimal_or_none(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _percentage(value: Decimal | None) -> str:
    if value is None:
        return "—"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:,.2f}%"


def _batch_time_text(trades: list[TradePayload]) -> str:
    times = sorted(trade.event_time.astimezone(SHANGHAI) for trade in trades)
    first = times[0].strftime("%Y-%m-%d %H:%M:%S")
    last = times[-1].strftime("%Y-%m-%d %H:%M:%S")
    if first == last:
        return first
    if times[0].date() == times[-1].date():
        return f"{first}–{times[-1].strftime('%H:%M:%S')}"
    return f"{first}–{last}"


def _operation_kind(trade: TradePayload) -> str:
    if trade.effective_action in {"INCREASE", "OPEN", "ADD"}:
        return "开"
    if trade.effective_action in {"DECREASE", "REDUCE", "CLOSE"}:
        return "平"
    return "反手"


def _trade_totals(
    trades: list[TradePayload],
) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    if any(trade.quantity is None or trade.price is None for trade in trades):
        return None, None, None
    total_quantity = sum(
        (trade.quantity for trade in trades if trade.quantity is not None),
        Decimal("0"),
    )
    total_amount = sum(
        (
            trade.quantity * trade.price
            for trade in trades
            if trade.quantity is not None and trade.price is not None
        ),
        Decimal("0"),
    )
    average_price = total_amount / total_quantity if total_quantity > 0 else None
    return total_quantity, average_price, total_amount


def _realized_pnl(trades: list[TradePayload]) -> Decimal | None:
    values = [_decimal_or_none(trade.source_record.get("totalPnl")) for trade in trades]
    if any(value is None for value in values):
        return None
    return sum((value for value in values if value is not None), Decimal("0"))


def _operation_lines(
    trades: list[TradePayload],
    margin_balance: Decimal | str | None,
) -> list[str]:
    side_labels = {"LONG": "多", "SHORT": "空", "UNKNOWN": "未知"}
    grouped: dict[tuple[str, str, str], list[TradePayload]] = {}
    for trade in sorted(
        trades,
        key=lambda item: (item.event_time, item.source_record_id, item.revision),
    ):
        key = (_operation_kind(trade), trade.position_side, trade.symbol)
        grouped.setdefault(key, []).append(trade)

    lines = [f"操作（{len(trades)}笔）"]
    for (kind, position_side, symbol), group in grouped.items():
        quantity, average_price, amount = _trade_totals(group)
        count = f"｜{len(group)}笔" if len(group) > 1 else ""
        price_label = "建仓价" if kind == "开" else "平仓价"
        lines.extend(
            [
                f"{kind} {side_labels[position_side]} {symbol}{count}",
                f"数量 {_quantity(quantity)}｜{price_label} {_price(average_price)}",
            ]
        )
        multiple = _account_multiple(amount, margin_balance)
        if kind == "平":
            lines.append(
                f"杠杆 {multiple}｜盈亏 {_money(_realized_pnl(group), signed=True)}"
            )
        else:
            lines.append(f"杠杆 {multiple}")
    return lines


def _position_pnl_ratio(position: PositionEstimate) -> Decimal | None:
    quantity = _decimal_or_none(position.quantity)
    entry_price = _decimal_or_none(position.entry_price)
    estimated_pnl = _decimal_or_none(position.estimated_pnl)
    if quantity is None or entry_price is None or estimated_pnl is None:
        return None
    entry_notional = abs(quantity * entry_price)
    if entry_notional <= 0:
        return None
    return estimated_pnl / entry_notional * Decimal("100")


def _position_lines(
    positions: list[PositionEstimate],
    margin_balance: Decimal | str | None,
) -> list[str]:
    side_labels = {
        "LONG": "多",
        "SHORT": "空",
        "UNKNOWN": "待确认",
    }
    current = sorted(
        (position for position in positions if position.status != "FLAT"),
        key=lambda position: (position.symbol, position.position_side),
    )
    lines = [f"持仓（{len(current)}）"]
    if not current:
        return ["持仓", "空仓"]
    for index, position in enumerate(current):
        if index:
            lines.append("")
        stale = "｜数据陈旧" if position.status == "STALE" else ""
        lines.extend(
            [
                (
                    f"{position.symbol} {side_labels.get(position.side, '待确认')}"
                    f"｜数量 {_quantity(position.quantity)}{stale}"
                ),
                (
                    f"均价 {_price(position.entry_price)}｜"
                    f"标记价 {_price(position.mark_price)}"
                ),
                (
                    f"盈亏 {_money(position.estimated_pnl, signed=True)}"
                    f"（{_percentage(_position_pnl_ratio(position))}）｜"
                    f"杠杆 {_account_multiple(position.notional, margin_balance)}"
                ),
            ]
        )
    return lines


def _mobile_trade_message(
    kol_name: str,
    trades: list[TradePayload],
    positions: list[PositionEstimate],
    margin_balance: Decimal | str | None,
    *,
    snapshot_is_current: bool,
) -> str:
    lines = [
        f"谁：{kol_name}",
        f"时间：{_batch_time_text(trades)}",
        "",
        *_operation_lines(trades, margin_balance),
        "",
    ]
    if snapshot_is_current:
        lines.extend(_position_lines(positions, margin_balance))
    else:
        lines.extend(["持仓", "快照同步中，以本次操作为准"])
    return "\n".join(lines)


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
    margin_balance = account.margin_balance if account is not None else None
    title = f"{kol.display_name}｜仓位变动 {len(trades)}笔"
    return title, _mobile_trade_message(
        kol.display_name,
        trades,
        positions,
        margin_balance,
        snapshot_is_current=snapshot_is_current,
    )


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
    current = next(
        (
            position
            for position in positions
            if position.symbol == trade.symbol
            and position.position_side == trade.position_side
        ),
        None,
    )
    return _mobile_trade_message(
        kol.display_name,
        [trade],
        positions,
        account.margin_balance if account is not None else None,
        snapshot_is_current=_snapshot_matches(current, trade.position_after),
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
            return f"{kol_name}｜仓位变动 1笔", trade_message
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
    *,
    now: datetime | None = None,
) -> int:
    client = client or NtfyClient()
    attempted_at = _utc_datetime(now or datetime.now(UTC))
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
        event = session.scalar(
            select(NotificationEvent)
            .where(
                NotificationEvent.signal_id == anchor_signal.id,
                NotificationEvent.notification_rule_id == rule.id,
            )
            .with_for_update()
        )
        if event is None:
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
        else:
            next_attempt_at = (
                _utc_datetime(event.next_attempt_at)
                if event.next_attempt_at is not None
                else None
            )
            if (
                event.status != "failed"
                or next_attempt_at is None
                or next_attempt_at > attempted_at
            ):
                continue
            event.status = "pending"
            event.error_message = None
            event.next_attempt_at = None

        event.attempt_count = (event.attempt_count or 0) + 1
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
            event.error_message = str(exc)[:2000]
            event.next_attempt_at = _next_notification_attempt_at(
                exc,
                event.attempt_count,
                attempted_at,
            )
            continue
        event.status = "sent"
        event.error_message = None
        event.next_attempt_at = None
        event.sent_at = attempted_at
        sent_count += 1
    return sent_count


def retry_failed_notifications(
    session: Session,
    client: NtfyClient | None = None,
    *,
    limit: int = 10,
    now: datetime | None = None,
) -> int:
    attempted_at = _utc_datetime(now or datetime.now(UTC))
    due_events = list(
        session.scalars(
            select(NotificationEvent)
            .where(
                NotificationEvent.status == "failed",
                NotificationEvent.next_attempt_at.is_not(None),
                NotificationEvent.next_attempt_at <= attempted_at,
            )
            .order_by(NotificationEvent.next_attempt_at, NotificationEvent.id)
            .limit(limit)
        ).all()
    )
    grouped: dict[int, list[NotificationEvent]] = {}
    for event in due_events:
        grouped.setdefault(event.signal_id, []).append(event)

    sent_count = 0
    for signal_id, events in grouped.items():
        signal = session.get(Signal, signal_id)
        if signal is None:
            for event in events:
                event.next_attempt_at = None
                event.error_message = "Notification retry stopped: signal is missing"
            continue
        attempts_before = {event.id: event.attempt_count for event in events}
        sent_count += dispatch_notifications(
            session,
            signal,
            client=client,
            now=attempted_at,
        )
        for event in events:
            if (
                event.status == "failed"
                and event.attempt_count == attempts_before[event.id]
            ):
                event.next_attempt_at = None
                event.error_message = (
                    "Notification retry stopped: rule is no longer eligible"
                )
    return sent_count
