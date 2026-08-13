from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from collector_agent.trade_models import TradeCheckpoint
from collector_agent.trade_reconciler import build_collected_post, reconcile_records
from tests.trade_samples import sample_record, trade_target


def test_trade_checkpoint_round_trips_versioned_json() -> None:
    checkpoint = TradeCheckpoint(
        event_time=datetime(2026, 8, 9, 1, 2, tzinfo=UTC),
        record_id="2",
    )

    assert TradeCheckpoint.decode(checkpoint.encode()) == checkpoint
    with pytest.raises(ValueError, match="checkpoint version"):
        TradeCheckpoint.decode(
            '{"v":2,"eventTime":"2026-08-09T01:02:00Z","recordId":"2"}'
        )


def test_reconcile_explicit_operations_with_decimal_quantity() -> None:
    reconciliation = reconcile_records(
        [
            sample_record("1", "OPEN", "LONG", "0.10"),
            sample_record("2", "ADD", "LONG", "0.05"),
            sample_record("3", "REDUCE", "LONG", "0.04"),
        ],
        history_complete=True,
    )

    position = reconciliation.position_for("BTCUSDT", "LONG")
    assert position.quantity == Decimal("0.11")
    assert position.side == "LONG"
    assert position.status == "ACTIVE"
    assert reconciliation.events[1].position_after.quantity == Decimal("0.15")

    closed = reconcile_records(
        [
            sample_record("1", "OPEN", "LONG", "0.10"),
            sample_record("2", "CLOSE", "LONG", None),
        ],
        history_complete=True,
    )
    closed_position = closed.position_for("BTCUSDT", "LONG")
    assert closed_position.side == "FLAT"
    assert closed_position.quantity == Decimal("0")
    assert closed_position.status == "FLAT"


def test_reconcile_tracks_weighted_entry_price_and_preserves_it_on_reduce() -> None:
    reconciliation = reconcile_records(
        [
            sample_record("1", "OPEN", "LONG", "0.10", price="50000"),
            sample_record("2", "ADD", "LONG", "0.05", price="53000"),
            sample_record("3", "REDUCE", "LONG", "0.04", price="54000"),
        ],
        history_complete=True,
    )

    added = reconciliation.events[1].position_after
    reduced = reconciliation.position_for("BTCUSDT", "LONG")
    assert added.entry_price == Decimal("51000")
    assert added.leverage == Decimal("10")
    assert reduced.entry_price == Decimal("51000")
    assert reduced.leverage == Decimal("10")


def test_reconcile_directional_changes_infers_user_visible_actions() -> None:
    reconciliation = reconcile_records(
        [
            sample_record("1", "INCREASE", "LONG", "0.10"),
            sample_record("2", "INCREASE", "LONG", "0.05"),
            sample_record("3", "DECREASE", "LONG", "0.05"),
            sample_record("4", "DECREASE", "LONG", "0.10"),
        ],
        history_complete=True,
    )

    assert [event.action for event in reconciliation.events] == [
        "OPEN",
        "ADD",
        "REDUCE",
        "CLOSE",
    ]
    assert reconciliation.position_for("BTCUSDT", "LONG").status == "FLAT"


def test_reconcile_keeps_long_and_short_position_buckets_independent() -> None:
    reconciliation = reconcile_records(
        [
            sample_record("1", "INCREASE", "LONG", "0.10"),
            sample_record("2", "INCREASE", "SHORT", "0.20"),
        ],
        history_complete=True,
    )

    assert reconciliation.position_for("BTCUSDT", "LONG").quantity == Decimal("0.10")
    assert reconciliation.position_for("BTCUSDT", "SHORT").quantity == Decimal("0.20")


def test_new_revision_emits_correction_but_replays_effective_operation() -> None:
    reconciliation = reconcile_records(
        [
            sample_record("1", "OPEN", "LONG", "0.10"),
            sample_record(
                "1",
                "OPEN",
                "LONG",
                "0.12",
                revision="r2",
                observed_minute=1,
            ),
        ],
        history_complete=True,
    )

    assert len(reconciliation.events) == 1
    assert reconciliation.events[0].action == "CORRECTION"
    assert reconciliation.events[0].record.operation == "OPEN"
    assert reconciliation.position_for("BTCUSDT", "LONG").quantity == Decimal("0.12")


def test_reverse_flattens_old_side_and_opens_new_side() -> None:
    reconciliation = reconcile_records(
        [
            sample_record("1", "OPEN", "LONG", "0.10"),
            sample_record("2", "REVERSE", "SHORT", "0.20"),
        ],
        history_complete=True,
    )

    assert reconciliation.position_for("BTCUSDT", "LONG").status == "FLAT"
    assert reconciliation.position_for("BTCUSDT", "SHORT").quantity == Decimal("0.20")
    assert reconciliation.events[-1].action == "REVERSE"


def test_reconcile_caps_confidence_and_marks_contradictions_unknown() -> None:
    missing_quantity = reconcile_records(
        [sample_record("1", "OPEN", "LONG", None)],
        history_complete=True,
    ).position_for("BTCUSDT", "LONG")
    assert missing_quantity.quantity is None
    assert missing_quantity.confidence == "MEDIUM"

    incomplete = reconcile_records(
        [sample_record("1", "OPEN", "LONG", "0.10")],
        history_complete=False,
    ).position_for("BTCUSDT", "LONG")
    assert incomplete.confidence == "LOW"

    contradictory = reconcile_records(
        [
            sample_record("1", "OPEN", "LONG", "0.10"),
            sample_record("2", "REDUCE", "LONG", "0.11"),
        ],
        history_complete=True,
    ).position_for("BTCUSDT", "LONG")
    assert contradictory.side == "UNKNOWN"
    assert contradictory.quantity is None
    assert contradictory.status == "UNKNOWN"
    assert contradictory.confidence == "UNKNOWN"

    empty = reconcile_records([], history_complete=True)
    assert empty.events == []
    assert empty.positions == {}


def test_build_collected_post_serializes_decimal_contract_and_rejects_unsafe_source() -> None:
    record = sample_record("1", "OPEN", "LONG", "0.10")
    event = reconcile_records([record], history_complete=True).events[0]

    post = build_collected_post(trade_target(), event)

    assert post.external_id == "5075281354358777856:1:r1"
    assert post.raw_payload == {
        "schemaVersion": 1,
        "platform": "binance_copy",
        "accountId": "5075281354358777856",
        "sourceRecordId": "1",
        "revision": "r1",
        "action": "OPEN",
        "effectiveAction": "OPEN",
        "symbol": "BTCUSDT",
        "positionSide": "LONG",
        "quantity": "0.10",
        "price": "50000",
        "leverage": "10",
        "eventTime": "2026-08-09T01:01:00+00:00",
        "positionAfter": {
            "side": "LONG",
            "quantity": "0.10",
            "entryPrice": "50000",
            "leverage": "10",
            "confidence": "HIGH",
            "status": "ACTIVE",
        },
        "sourceRecord": {"id": "1"},
    }
    assert post.content_hash is not None
    assert "推测持仓" in post.raw_content

    unsafe = replace(record, source_payload={"quantity": Decimal("0.10")})
    unsafe_event = replace(event, record=unsafe)
    with pytest.raises(ValueError, match="JSON-safe"):
        build_collected_post(trade_target(), unsafe_event)
