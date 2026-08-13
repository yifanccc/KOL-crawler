from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from app.models import (
    KolProfile,
    PositionAccountSnapshot,
    PositionEstimate,
    PositionOperation,
    Subscription,
)


def utc_text(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def decimal_value(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        return None
    return parsed if parsed.is_finite() else None


def decimal_text(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None


def position_payload(position: PositionEstimate) -> dict:
    return {
        "symbol": position.symbol,
        "positionSide": position.position_side,
        "side": position.side,
        "quantity": position.quantity,
        "entryPrice": position.entry_price,
        "currentPrice": position.mark_price,
        "notional": position.notional,
        "leverage": position.leverage,
        "positionMargin": position.position_margin,
        "estimatedPnl": position.estimated_pnl,
        "confidence": position.confidence,
        "status": position.status,
        "asOfEventTime": utc_text(position.as_of_event_time),
        "priceUpdatedAt": utc_text(position.price_updated_at),
        "staleSince": utc_text(position.stale_since),
        "updatedAt": utc_text(position.source_updated_at),
    }


def operation_payload(operation: PositionOperation) -> dict:
    return {
        "sourceRecordId": operation.source_record_id,
        "revision": operation.revision,
        "action": operation.action,
        "effectiveAction": operation.effective_action,
        "symbol": operation.symbol,
        "positionSide": operation.position_side,
        "quantity": operation.quantity,
        "price": operation.price,
        "amount": operation.amount,
        "leverage": operation.leverage,
        "realizedPnl": operation.realized_pnl,
        "eventTime": utc_text(operation.event_time),
    }


def _sum_values(
    positions: list[PositionEstimate],
    attribute: str,
) -> tuple[Decimal | None, bool]:
    if not positions:
        return None, False
    values = [decimal_value(getattr(position, attribute)) for position in positions]
    complete = all(value is not None for value in values)
    known = [value for value in values if value is not None]
    return (sum(known, Decimal("0")) if known else None), complete


def position_summary_payload(
    subscription: Subscription,
    kol: KolProfile,
    account: PositionAccountSnapshot | None,
    positions: list[PositionEstimate],
) -> dict:
    current = [position for position in positions if position.status != "FLAT"]
    exposed = [
        position for position in current if position.status in {"ACTIVE", "STALE"}
    ]
    uncertain = [
        position for position in current if position.status in {"STALE", "UNKNOWN"}
    ]
    total_notional, notional_complete = _sum_values(exposed, "notional")
    estimated_pnl, pnl_complete = _sum_values(exposed, "estimated_pnl")
    position_margin, margin_complete = _sum_values(exposed, "position_margin")
    effective_leverage = None
    if (
        total_notional is not None
        and position_margin is not None
        and position_margin > 0
        and margin_complete
    ):
        effective_leverage = total_notional / position_margin

    if not current or not exposed:
        metrics_status = "UNKNOWN"
        total_notional = None
        estimated_pnl = None
        position_margin = None
    elif uncertain or not all(
        [notional_complete, pnl_complete, margin_complete, effective_leverage is not None]
    ):
        metrics_status = "PARTIAL"
        if not margin_complete:
            position_margin = None
            effective_leverage = None
    else:
        metrics_status = "COMPLETE"

    timestamps = [
        value
        for value in [
            account.source_updated_at if account is not None else None,
            *(position.source_updated_at for position in positions),
            *(position.price_updated_at for position in positions),
        ]
        if value is not None
    ]
    latest = max(
        (
            value.replace(tzinfo=UTC) if value.tzinfo is None else value
            for value in timestamps
        ),
        default=None,
    )
    return {
        "subscriptionId": subscription.id,
        "kol": {"id": kol.id, "displayName": kol.display_name},
        "platform": subscription.platform,
        "accountId": subscription.platform_account_id,
        "marginBalance": account.margin_balance if account is not None else None,
        "totalPositionNotional": decimal_text(total_notional),
        "positionMargin": decimal_text(position_margin),
        "estimatedPnl": decimal_text(estimated_pnl),
        "effectiveLeverage": decimal_text(effective_leverage),
        "activePositionCount": len(exposed),
        "uncertainPositionCount": len(uncertain),
        "metricsStatus": metrics_status,
        "updatedAt": utc_text(latest),
    }
