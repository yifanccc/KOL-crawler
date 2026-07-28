import json
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Asset, NotificationEvent, NotificationRule, RawPost, Signal, SignalAsset

CONFIDENCE_RANK = {"低": 1, "中": 2, "高": 3, None: 0}
PLATFORM_LABELS = {"x": "X", "binance_square": "Binance Square"}
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
