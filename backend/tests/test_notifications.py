from datetime import UTC, datetime

from sqlalchemy import select

from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models import Asset, NotificationEvent, NotificationRule, RawPost, Signal, SignalAsset
from app.services.notifications import NtfyClient, _format_notification, dispatch_notifications


class FakeNtfyClient:
    def __init__(self) -> None:
        self.calls = []

    def publish(self, server, topic, title, message, token=None) -> None:
        self.calls.append((server, topic, title, message, token))


def reset_database() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def test_ntfy_client_uses_json_for_utf8_title_and_message(mocker) -> None:
    response = mocker.Mock()
    publish = mocker.patch("app.services.notifications.httpx.post", return_value=response)

    NtfyClient().publish(
        server="https://ntfy.sh/",
        topic="private-topic",
        title="BTC 多 | 中文摘要",
        message="摘要：中文摘要\n标的：BTC\n方向：多",
        token="secret-token",
    )

    publish.assert_called_once_with(
        "https://ntfy.sh",
        json={
            "topic": "private-topic",
            "title": "BTC 多 | 中文摘要",
            "message": "摘要：中文摘要\n标的：BTC\n方向：多",
        },
        headers={"Authorization": "Bearer secret-token"},
        timeout=15,
    )
    response.raise_for_status.assert_called_once_with()


def test_dispatch_notifications_sends_matching_ntfy_rule_and_records_event() -> None:
    reset_database()
    session = SessionLocal()
    try:
        raw_post = RawPost(
            platform="x",
            external_id="1",
            author_handle="aleabitoreddit",
            author_name="Serenity",
            published_at=datetime(2026, 7, 9, tzinfo=UTC),
            raw_text="$AXTI demand improving",
        )
        session.add(raw_post)
        session.flush()
        signal = Signal(
            raw_post_id=raw_post.id,
            actionable=True,
            stance="多",
            stance_cn="多",
            summary="AXTI demand improving",
            summary_cn="AXTI 需求改善",
            symbols_json='["AXTI"]',
            key_points_json='["订单需求回升", "关注产能兑现"]',
            confidence="高",
            structured_status="ok",
        )
        session.add(signal)
        session.flush()
        asset = Asset(symbol="AXTI", market="US_STOCK", asset_type="stock")
        session.add(asset)
        session.flush()
        session.add(SignalAsset(signal_id=signal.id, asset_id=asset.id))
        rule = NotificationRule(
            ntfy_server="https://ntfy.sh",
            ntfy_topic="kol-test",
            min_confidence="中",
            require_asset=True,
            enabled=True,
        )
        session.add(rule)
        session.commit()

        client = FakeNtfyClient()
        sent_count = dispatch_notifications(session, signal, client=client)
        events = session.scalars(select(NotificationEvent)).all()
    finally:
        session.close()

    assert sent_count == 1
    assert len(client.calls) == 1
    assert events[0].status == "sent"
    title = client.calls[0][2]
    message = client.calls[0][3]
    assert title == "X | Serenity | 2026-07-09 08:00"
    assert "aleabitoreddit" not in title
    assert message == "摘要：AXTI 需求改善\n标的：AXTI\n方向：多"
    assert "KOL：" not in message
    assert "要点：" not in message
    assert "来源：" not in message


def test_notification_title_never_falls_back_to_account_handle() -> None:
    reset_database()
    session = SessionLocal()
    try:
        raw_post = RawPost(
            platform="x",
            external_id="missing-nickname",
            author_handle="account-name",
            author_name=None,
            published_at=None,
            raw_text="$BTC 看多",
        )
        session.add(raw_post)
        session.flush()
        signal = Signal(
            raw_post_id=raw_post.id,
            actionable=True,
            stance="bullish",
            stance_cn="多",
            summary="BTC bullish",
            summary_cn="BTC 看多",
            symbols_json='["BTC"]',
            structured_status="ok",
        )
        session.add(signal)
        session.flush()

        title, message = _format_notification(session, signal)
    finally:
        session.close()

    assert title == "X | 未知 KOL | 时间未知"
    assert "account-name" not in title
    assert message == "摘要：BTC 看多\n标的：BTC\n方向：多"


def test_repeated_dispatch_creates_one_event_and_one_publish_call() -> None:
    reset_database()
    session = SessionLocal()
    try:
        raw_post = RawPost(platform="x", external_id="duplicate", raw_text="$BTC 看多", url="https://x.com/a/status/1")
        session.add(raw_post); session.flush()
        signal = Signal(raw_post_id=raw_post.id, actionable=True, stance="bullish", stance_cn="多", summary="BTC 看多", confidence="高", structured_status="ok")
        session.add(signal); session.flush()
        asset = Asset(symbol="BTC", market="CRYPTO", asset_type="crypto")
        session.add(asset); session.flush(); session.add(SignalAsset(signal_id=signal.id, asset_id=asset.id))
        rule = NotificationRule(ntfy_server="https://ntfy.sh", ntfy_topic="kol-test", min_confidence="中", require_asset=True, enabled=True)
        session.add(rule); session.commit()
        client = FakeNtfyClient()
        assert dispatch_notifications(session, signal, client) == 1
        assert dispatch_notifications(session, signal, client) == 0
        assert len(session.scalars(select(NotificationEvent)).all()) == 1
        assert len(client.calls) == 1
    finally:
        session.close()
