from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Signal(Base):
    __tablename__ = "signals"
    __table_args__ = (UniqueConstraint("raw_post_id", name="uq_signals_raw_post"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    raw_post_id: Mapped[int] = mapped_column(ForeignKey("raw_posts.id"), nullable=False)
    subscription_id: Mapped[int | None] = mapped_column(ForeignKey("subscriptions.id"))
    actionable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    stance: Mapped[str] = mapped_column(String(32), nullable=False)
    stance_cn: Mapped[str | None] = mapped_column(String(32))
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    summary_cn: Mapped[str | None] = mapped_column(Text)
    symbols_json: Mapped[str | None] = mapped_column(Text)
    market: Mapped[str | None] = mapped_column(String(32))
    key_points_json: Mapped[str | None] = mapped_column(Text)
    evidence_json: Mapped[str | None] = mapped_column(Text)
    horizon: Mapped[str | None] = mapped_column(String(32))
    confidence: Mapped[str | None] = mapped_column(String(32))
    confidence_score: Mapped[int | None] = mapped_column(Integer)
    importance: Mapped[int | None] = mapped_column(Integer)
    tags_json: Mapped[str | None] = mapped_column(Text)
    action_hint: Mapped[str | None] = mapped_column(Text)
    source_language: Mapped[str | None] = mapped_column(String(64))
    translated_text_cn: Mapped[str | None] = mapped_column(Text)
    risk_warning: Mapped[str | None] = mapped_column(Text)
    risk_notes: Mapped[str | None] = mapped_column(Text)
    prompt_version: Mapped[str | None] = mapped_column(String(64))
    structured_json: Mapped[str | None] = mapped_column(Text)
    structured_status: Mapped[str] = mapped_column(String(32), nullable=False, default="ok")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
