from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
import sqlite3

import pytest

from collector_agent.db import CollectorStore
from collector_agent.models import ProviderTarget
from collector_agent.trade_models import TradeAccountSnapshot, TradeCheckpoint
from tests.trade_samples import sample_record, trade_result, trade_target


def test_first_trade_fetch_builds_baseline_without_outbox(tmp_path) -> None:
    store = CollectorStore(tmp_path / "collector.sqlite3")
    result = trade_result(
        [sample_record("1", "OPEN", "LONG", "0.10")],
        "1",
    )

    inserted = store.record_trade_fetch(7, trade_target(), result)

    assert inserted == 0
    assert store.pending_posts() == []
    assert TradeCheckpoint.decode(store.checkpoint_for(7)).record_id == "1"
    position = store.position_for(7, "BTCUSDT", "LONG")
    assert position is not None
    assert position.quantity == Decimal("0.10")


def test_trade_baseline_exposes_current_position_snapshots(tmp_path) -> None:
    store = CollectorStore(tmp_path / "collector.sqlite3")
    store.record_trade_fetch(
        7,
        trade_target(),
        trade_result([sample_record("1", "OPEN", "LONG", "0.10")], "1"),
    )

    assert store.position_snapshots_for(7) == [
        {
            "symbol": "BTCUSDT",
            "positionSide": "LONG",
            "side": "LONG",
            "quantity": "0.10",
            "entryPrice": "50000",
            "currentPrice": None,
            "notional": None,
            "leverage": "10",
            "positionMargin": None,
            "estimatedPnl": None,
            "priceUpdatedAt": None,
            "confidence": "HIGH",
            "status": "ACTIVE",
            "asOfEventTime": "2026-08-09T01:01:00+00:00",
            "staleSince": None,
            "updatedAt": "2026-08-09T02:00:00+00:00",
        }
    ]


def test_trade_snapshot_values_positions_and_exposes_account_and_operations(tmp_path) -> None:
    store = CollectorStore(tmp_path / "collector.sqlite3")
    result = trade_result(
        [
            sample_record("1", "OPEN", "LONG", "0.10", price="50000"),
            sample_record("2", "ADD", "LONG", "0.05", price="53000"),
            sample_record("3", "REDUCE", "LONG", "0.04", price="54000"),
        ],
        "3",
    )
    result = replace(
        result,
        account_snapshot=TradeAccountSnapshot(
            margin_balance=Decimal("137889.65"),
            observed_at=datetime(2026, 8, 9, 2, 5, tzinfo=UTC),
        ),
        mark_prices={"BTCUSDT": Decimal("52000")},
    )

    store.record_trade_fetch(7, trade_target(), result)

    assert store.account_snapshot_for(7) == {
        "marginBalance": "137889.65",
        "updatedAt": "2026-08-09T02:05:00+00:00",
    }
    assert store.position_snapshots_for(7) == [
        {
            "symbol": "BTCUSDT",
            "positionSide": "LONG",
            "side": "LONG",
            "quantity": "0.11",
            "entryPrice": "51000",
            "currentPrice": "52000",
            "notional": "5720.00",
            "leverage": "10",
            "positionMargin": "572.00",
            "estimatedPnl": "110.00",
            "priceUpdatedAt": "2026-08-09T02:05:00+00:00",
            "confidence": "HIGH",
            "status": "ACTIVE",
            "asOfEventTime": "2026-08-09T01:03:00+00:00",
            "staleSince": None,
            "updatedAt": "2026-08-09T02:00:00+00:00",
        }
    ]
    operations = store.trade_operation_snapshots_for(7)
    assert [item["action"] for item in operations] == ["OPEN", "ADD", "REDUCE"]
    assert operations[-1] == {
        "sourceRecordId": "3",
        "revision": "r1",
        "action": "REDUCE",
        "effectiveAction": "REDUCE",
        "symbol": "BTCUSDT",
        "positionSide": "LONG",
        "quantity": "0.04",
        "price": "54000",
        "amount": "2160.00",
        "leverage": "10",
        "realizedPnl": None,
        "eventTime": "2026-08-09T01:03:00+00:00",
    }


def test_second_trade_fetch_is_atomic_idempotent_and_survives_restart(tmp_path) -> None:
    path = tmp_path / "collector.sqlite3"
    store = CollectorStore(path)
    store.record_trade_fetch(
        7,
        trade_target(),
        trade_result([sample_record("1", "OPEN", "LONG", "0.10")], "1"),
    )
    update = trade_result(
        [
            sample_record("1", "OPEN", "LONG", "0.10"),
            sample_record("2", "ADD", "LONG", "0.05"),
        ],
        "2",
    )

    assert store.record_trade_fetch(7, trade_target(), update) == 1
    assert store.record_trade_fetch(7, trade_target(), update) == 0
    assert len(store.pending_posts()) == 1
    store.close()

    restarted = CollectorStore(path)
    assert TradeCheckpoint.decode(restarted.checkpoint_for(7)).record_id == "2"
    position = restarted.position_for(7, "BTCUSDT", "LONG")
    assert position is not None
    assert position.quantity == Decimal("0.15")


def test_trade_outbox_preserves_event_time_order(tmp_path) -> None:
    store = CollectorStore(tmp_path / "collector.sqlite3")
    store.record_trade_fetch(
        7,
        trade_target(),
        trade_result([sample_record("1", "OPEN", "LONG", "0.10")], "1"),
    )

    store.record_trade_fetch(
        7,
        trade_target(),
        trade_result(
            [
                sample_record("10", "ADD", "LONG", "0.01"),
                sample_record("2", "ADD", "LONG", "0.01"),
            ],
            "10",
        ),
    )

    assert [post.external_id for post in store.pending_posts()] == [
        "5075281354358777856:2:r1",
        "5075281354358777856:10:r1",
    ]


def test_trade_fetch_rolls_back_ledger_position_outbox_and_checkpoint_together(
    tmp_path,
) -> None:
    store = CollectorStore(tmp_path / "collector.sqlite3")
    store.record_trade_fetch(
        7,
        trade_target(),
        trade_result([sample_record("1", "OPEN", "LONG", "0.10")], "1"),
    )
    store.connection.executescript(
        """
        CREATE TRIGGER fail_trade_outbox
        BEFORE INSERT ON outbox_posts
        BEGIN
          SELECT RAISE(ABORT, 'forced outbox failure');
        END;
        """
    )

    with pytest.raises(sqlite3.IntegrityError, match="forced outbox failure"):
        store.record_trade_fetch(
            7,
            trade_target(),
            trade_result(
                [
                    sample_record("1", "OPEN", "LONG", "0.10"),
                    sample_record("2", "ADD", "LONG", "0.05"),
                ],
                "2",
            ),
        )

    assert TradeCheckpoint.decode(store.checkpoint_for(7)).record_id == "1"
    assert store.connection.execute("SELECT COUNT(*) FROM trade_events").fetchone()[0] == 1
    position = store.position_for(7, "BTCUSDT", "LONG")
    assert position is not None
    assert position.quantity == Decimal("0.10")
    assert store.pending_posts() == []


def test_trade_fetch_rejects_target_checkpoint_and_revision_integrity_failures(
    tmp_path,
) -> None:
    store = CollectorStore(tmp_path / "collector.sqlite3")
    baseline = trade_result(
        [sample_record("2", "OPEN", "LONG", "0.10")],
        "2",
    )
    store.record_trade_fetch(7, trade_target(), baseline)

    wrong_target = ProviderTarget(7, "binance_copy", "11111111", "熬鹰资本")
    with pytest.raises(ValueError, match="target"):
        store.record_trade_fetch(7, wrong_target, baseline)

    with pytest.raises(ValueError, match="checkpoint"):
        store.record_trade_fetch(
            7,
            trade_target(),
            trade_result([sample_record("1", "ADD", "LONG", "0.01")], "1"),
        )

    collision = replace(
        sample_record("2", "OPEN", "LONG", "0.10"),
        quantity=Decimal("0.20"),
    )
    with pytest.raises(ValueError, match="revision collision"):
        store.record_trade_fetch(
            7,
            trade_target(),
            trade_result([collision], "2"),
        )

    assert TradeCheckpoint.decode(store.checkpoint_for(7)).record_id == "2"
    position = store.position_for(7, "BTCUSDT", "LONG")
    assert position is not None
    assert position.quantity == Decimal("0.10")
    assert store.pending_posts() == []


def test_mark_trade_positions_stale_preserves_estimate_and_checkpoint(tmp_path) -> None:
    store = CollectorStore(tmp_path / "collector.sqlite3")
    store.record_trade_fetch(
        7,
        trade_target(),
        trade_result([sample_record("1", "OPEN", "SHORT", "0.25")], "1"),
    )
    stale_since = datetime(2026, 8, 9, 3, 0, tzinfo=UTC)

    store.mark_trade_positions_stale(7, stale_since)

    position = store.position_for(7, "BTCUSDT", "SHORT")
    assert position is not None
    assert position.side == "SHORT"
    assert position.quantity == Decimal("0.25")
    assert position.status == "STALE"
    assert position.stale_since == stale_since
    assert TradeCheckpoint.decode(store.checkpoint_for(7)).record_id == "1"


def test_mark_trade_positions_unknown_clears_unreliable_quantity_only(tmp_path) -> None:
    store = CollectorStore(tmp_path / "collector.sqlite3")
    store.record_trade_fetch(
        7,
        trade_target(),
        trade_result([sample_record("1", "OPEN", "LONG", "0.25")], "1"),
    )
    gap_at = datetime(2026, 8, 9, 3, 0, tzinfo=UTC)

    store.mark_trade_positions_unknown(7, gap_at)

    position = store.position_for(7, "BTCUSDT", "LONG")
    assert position is not None
    assert position.side == "UNKNOWN"
    assert position.quantity is None
    assert position.confidence == "UNKNOWN"
    assert position.status == "UNKNOWN"
    assert position.stale_since == gap_at
    assert TradeCheckpoint.decode(store.checkpoint_for(7)).record_id == "1"
