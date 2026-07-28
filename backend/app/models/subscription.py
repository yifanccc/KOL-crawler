from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


DEFAULT_MONITOR_INTERVAL_MINUTES = 10


class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (CheckConstraint("interval_minutes >= 1", name="ck_subscription_interval_min"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    kol_profile_id: Mapped[int | None] = mapped_column(ForeignKey("kol_profiles.id"))
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    platform_account_id: Mapped[str | None] = mapped_column(String(255))
    platform_handle: Mapped[str] = mapped_column(String(255), nullable=False)
    interval_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=DEFAULT_MONITOR_INTERVAL_MINUTES,
    )
    prompt: Mapped[str | None] = mapped_column(Text)
    system_prompt: Mapped[str | None] = mapped_column(Text)
    user_prompt: Mapped[str | None] = mapped_column(Text)
    output_schema_json: Mapped[str | None] = mapped_column(Text)
    markets_json: Mapped[str | None] = mapped_column(Text)
    prompt_version: Mapped[str | None] = mapped_column(String(64))
    model_config_id: Mapped[int | None] = mapped_column(ForeignKey("model_configs.id"))
    checkpoint: Mapped[str | None] = mapped_column(Text)
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
