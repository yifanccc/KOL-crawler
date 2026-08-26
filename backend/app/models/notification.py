from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class NotificationRule(Base):
    __tablename__ = "notification_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    subscription_id: Mapped[int | None] = mapped_column(ForeignKey("subscriptions.id"))
    ntfy_server: Mapped[str | None] = mapped_column(String(1024))
    ntfy_topic: Mapped[str | None] = mapped_column(String(255))
    ntfy_token_encrypted: Mapped[str | None] = mapped_column(Text)
    min_confidence: Mapped[str | None] = mapped_column(String(32))
    require_asset: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    allowed_markets_json: Mapped[str | None] = mapped_column(Text)
    allowed_stances_json: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class NotificationEvent(Base):
    __tablename__ = "notification_events"
    __table_args__ = (UniqueConstraint("signal_id", "notification_rule_id", name="uq_notification_event_signal_rule"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    signal_id: Mapped[int] = mapped_column(ForeignKey("signals.id"), nullable=False)
    notification_rule_id: Mapped[int | None] = mapped_column(ForeignKey("notification_rules.id"))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
