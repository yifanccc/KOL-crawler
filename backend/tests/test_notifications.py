from datetime import UTC, datetime

from sqlalchemy import select

from app.db.base import Base
from app.db.session import SessionLocal, engine
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


def test_notification_uses_binance_copy_platform_label() -> None:
    reset_database()
    session = SessionLocal()
    try:
        raw_post = RawPost(
            platform="binance_copy",
            external_id="copy-trade",
            author_name="熬鹰资本",
            published_at=datetime(2026, 8, 9, tzinfo=UTC),
            raw_text="BTCUSDT 减仓",
        )
        session.add(raw_post)
        session.flush()
        signal = Signal(
            raw_post_id=raw_post.id,
            actionable=True,
            stance="neutral",
            stance_cn="中性",
            summary="BTCUSDT 减仓",
            symbols_json='["BTCUSDT"]',
            structured_status="deterministic",
        )
        session.add(signal)
        session.flush()

        title, _ = _format_notification(session, signal)
    finally:
        session.close()

    assert title == "Binance Copy | 熬鹰资本 | 2026-08-09 08:00"


def test_binance_copy_notification_contains_operation_symbol_position_and_kol_summary() -> None:
    reset_database()
    session = SessionLocal()
    try:
        kol = KolProfile(platform="binance_copy", display_name="熬鹰资本")
        session.add(kol)
        session.flush()
        subscription = Subscription(
            kol_profile_id=kol.id,
            platform="binance_copy",
            platform_account_id="5075281354358777856",
            platform_handle="熬鹰资本",
            visibility="private",
            interval_minutes=10,
        )
        session.add(subscription)
        session.flush()
        session.add(
            PositionAccountSnapshot(
                subscription_id=subscription.id,
                margin_balance="137889.65",
                source_updated_at=datetime(2026, 8, 9, 2, 5, tzinfo=UTC),
            )
        )
        session.add(
            PositionEstimate(
                subscription_id=subscription.id,
                symbol="BTCUSDT",
                position_side="LONG",
                side="LONG",
                quantity="0.15",
                entry_price="51000",
                mark_price="52000",
                notional="7800.00",
                estimated_pnl="150.00",
                confidence="LOW",
                status="ACTIVE",
                source_updated_at=datetime(2026, 8, 9, 2, 5, tzinfo=UTC),
                price_updated_at=datetime(2026, 8, 9, 2, 5, tzinfo=UTC),
            )
        )
        payload = {
            "schemaVersion": 1,
            "platform": "binance_copy",
            "accountId": "5075281354358777856",
            "sourceRecordId": "2",
            "revision": "r1",
            "action": "ADD",
            "effectiveAction": "INCREASE",
            "symbol": "BTCUSDT",
            "positionSide": "LONG",
            "quantity": "0.05",
            "price": "53000",
            "leverage": None,
            "eventTime": "2026-08-09T01:02:00Z",
            "positionAfter": {
                "side": "LONG",
                "quantity": "0.15",
                "entryPrice": "51000",
                "confidence": "LOW",
                "status": "ACTIVE",
            },
            "sourceRecord": {"totalPnl": "0"},
        }
        raw_post = RawPost(
            subscription_id=subscription.id,
            platform="binance_copy",
            external_id="5075281354358777856:2:r1",
            author_name="熬鹰资本",
            published_at=datetime(2026, 8, 9, 1, 2, tzinfo=UTC),
            raw_text="BTCUSDT 加仓",
            raw_json=__import__("json").dumps(payload),
        )
        session.add(raw_post)
        session.flush()
        signal = Signal(
            subscription_id=subscription.id,
            raw_post_id=raw_post.id,
            actionable=True,
            stance="bullish",
            stance_cn="多",
            summary="BTCUSDT 加仓",
            symbols_json='["BTCUSDT"]',
            structured_status="deterministic",
        )
        session.add(signal)
        session.flush()

        title, message = _format_notification(session, signal)
    finally:
        session.close()

    assert title == "Binance Copy | 熬鹰资本 | 2026-08-09 09:02"
    assert "操作：BTCUSDT 加仓 多" in message
    assert "成交价格 53,000.00" in message
    assert "成交数量 0.05" in message
    assert "操作金额 2,650.00 USDT" in message
    assert "品种当前：多 0.15" in message
    assert "开仓 51,000.00" in message
    assert "现价 52,000.00" in message
    assert "预计盈亏 +150.00 USDT" in message
    assert "KOL 当前：账户保证金余额 137,889.65 USDT" in message
    assert "已估算持仓总额 7,800.00 USDT" in message
    assert "仓位倍数（估算） 0.06x" in message
    assert "持仓保证金" not in message
    assert "有效杠杆" not in message


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


def test_binance_copy_batch_waits_then_sends_one_aggregated_position_change() -> None:
    reset_database()
    session = SessionLocal()
    try:
        kol = KolProfile(platform="binance_copy", display_name="熬鹰资本")
        session.add(kol)
        session.flush()
        subscription = Subscription(
            kol_profile_id=kol.id,
            platform="binance_copy",
            platform_account_id="5075281354358777856",
            platform_handle="熬鹰资本",
            visibility="private",
            interval_minutes=10,
        )
        session.add(subscription)
        session.flush()
        session.add_all(
            [
                PositionAccountSnapshot(
                    subscription_id=subscription.id,
                    margin_balance="10000",
                    source_updated_at=datetime(2026, 8, 9, 2, 5, tzinfo=UTC),
                ),
                PositionEstimate(
                    subscription_id=subscription.id,
                    symbol="BTCUSDT",
                    position_side="LONG",
                    side="LONG",
                    quantity="0.18",
                    entry_price="51222.22222222",
                    mark_price="53000",
                    notional="9540",
                    leverage="10",
                    position_margin="954",
                    estimated_pnl="320",
                    confidence="HIGH",
                    status="ACTIVE",
                    source_updated_at=datetime(2026, 8, 9, 2, 5, tzinfo=UTC),
                ),
            ]
        )
        rule = NotificationRule(
            subscription_id=subscription.id,
            ntfy_server="https://ntfy.sh",
            ntfy_topic="kol-test",
            min_confidence="中",
            require_asset=True,
            enabled=True,
        )
        session.add(rule)
        asset = Asset(symbol="BTCUSDT", market="CRYPTO", asset_type="crypto")
        session.add(asset)
        session.flush()

        batch_id = "a" * 64
        position_changes = [
            {
                "symbol": "BTCUSDT",
                "positionSide": "LONG",
                "before": {
                    "side": "LONG",
                    "quantity": "0.10",
                    "entryPrice": "50000",
                    "leverage": "10",
                    "confidence": "HIGH",
                    "status": "ACTIVE",
                },
                "after": {
                    "side": "LONG",
                    "quantity": "0.18",
                    "entryPrice": "51222.22222222",
                    "leverage": "10",
                    "confidence": "HIGH",
                    "status": "ACTIVE",
                },
            }
        ]

        def add_batch_post(record_id: str, quantity: str, price: str, minute: int):
            payload = {
                "schemaVersion": 2,
                "platform": "binance_copy",
                "accountId": "5075281354358777856",
                "sourceRecordId": record_id,
                "revision": "r1",
                "action": "ADD",
                "effectiveAction": "INCREASE",
                "symbol": "BTCUSDT",
                "positionSide": "LONG",
                "quantity": quantity,
                "price": price,
                "leverage": "10",
                "eventTime": f"2026-08-09T01:0{minute}:00Z",
                "positionAfter": {
                    "side": "LONG",
                    "quantity": "0.18",
                    "entryPrice": "51222.22222222",
                    "leverage": "10",
                    "confidence": "HIGH",
                    "status": "ACTIVE",
                },
                "sourceRecord": {"id": record_id},
                "collectionBatchId": batch_id,
                "collectionBatchSize": 2,
                "positionChanges": position_changes,
            }
            raw_post = RawPost(
                subscription_id=subscription.id,
                platform="binance_copy",
                external_id=f"5075281354358777856:{record_id}:r1",
                author_name="熬鹰资本",
                published_at=datetime(2026, 8, 9, 1, minute, tzinfo=UTC),
                raw_text="BTCUSDT 加仓",
                raw_json=__import__("json").dumps(payload),
                notification_batch_id=batch_id,
                notification_batch_size=2,
            )
            session.add(raw_post)
            session.flush()
            return raw_post

        first_post = add_batch_post("2", "0.05", "52000", 2)
        second_post = add_batch_post("3", "0.03", "54000", 3)
        first_signal = Signal(
            subscription_id=subscription.id,
            raw_post_id=first_post.id,
            actionable=True,
            stance="bullish",
            stance_cn="多",
            summary="BTCUSDT 加仓",
            symbols_json='["BTCUSDT"]',
            confidence="高",
            structured_status="deterministic",
        )
        session.add(first_signal)
        session.flush()
        session.add(SignalAsset(signal_id=first_signal.id, asset_id=asset.id))
        session.flush()

        client = FakeNtfyClient()
        assert dispatch_notifications(session, first_signal, client) == 0

        second_signal = Signal(
            subscription_id=subscription.id,
            raw_post_id=second_post.id,
            actionable=True,
            stance="bullish",
            stance_cn="多",
            summary="BTCUSDT 加仓",
            symbols_json='["BTCUSDT"]',
            confidence="高",
            structured_status="deterministic",
        )
        session.add(second_signal)
        session.flush()
        session.add(SignalAsset(signal_id=second_signal.id, asset_id=asset.id))
        session.flush()

        assert dispatch_notifications(session, second_signal, client) == 1
        assert dispatch_notifications(session, second_signal, client) == 0
        assert len(client.calls) == 1
        assert len(session.scalars(select(NotificationEvent)).all()) == 1
        title = client.calls[0][2]
        message = client.calls[0][3]
        assert title == "Binance Copy | 熬鹰资本 | 仓位变动 2 笔"
        assert "共 2 笔成交" in message
        assert "仓位：多 0.1 → 多 0.18（+0.08）" in message
        assert "操作汇总：加仓 2 笔" in message
        assert "成交数量合计 0.08" in message
        assert "成交均价 52,750.00" in message
        assert "成交额合计 4,220.00 USDT" in message

        no_change_payload = {
            **__import__("json").loads(first_post.raw_json),
            "sourceRecordId": "4",
            "collectionBatchId": "b" * 64,
            "collectionBatchSize": 1,
            "positionChanges": [],
        }
        no_change_post = RawPost(
            subscription_id=subscription.id,
            platform="binance_copy",
            external_id="5075281354358777856:4:r1",
            author_name="熬鹰资本",
            raw_text="BTCUSDT 交易修订",
            raw_json=__import__("json").dumps(no_change_payload),
            notification_batch_id="b" * 64,
            notification_batch_size=1,
        )
        session.add(no_change_post)
        session.flush()
        no_change_signal = Signal(
            subscription_id=subscription.id,
            raw_post_id=no_change_post.id,
            actionable=True,
            stance="neutral",
            stance_cn="中性",
            summary="BTCUSDT 交易修订",
            symbols_json='["BTCUSDT"]',
            confidence="高",
            structured_status="deterministic",
        )
        session.add(no_change_signal)
        session.flush()
        session.add(SignalAsset(signal_id=no_change_signal.id, asset_id=asset.id))
        session.flush()

        assert dispatch_notifications(session, no_change_signal, client) == 0
        assert len(client.calls) == 1
    finally:
        session.close()
