import json
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.models import CrawlRun, KolProfile, ModelConfig, NotificationEvent, NotificationRule, Subscription
from app.models.subscription import DEFAULT_MONITOR_INTERVAL_MINUTES, TRADE_PLATFORMS
from app.routers.auth import authenticate, require_authenticated, set_session_cookie
from app.services.collector_health import collector_health_payload
from app.services.signal_feed import signal_page
from app.services.structurer import (
    DEFAULT_OUTPUT_SCHEMA,
    DEFAULT_SYSTEM_PROMPT,
    DEFAULT_USER_PROMPT,
    _validate_output_schema,
)

router = APIRouter(prefix="/api/admin")

PLATFORMS = {"x", "binance_square", *TRADE_PLATFORMS}
MARKETS = {"crypto", "us_stock", "a_share", "hk_stock", "macro", "unknown"}
ALL_MARKETS = ["crypto", "us_stock", "a_share", "hk_stock", "macro", "unknown"]


def _normalize_handle(platform: str, value: str) -> str:
    handle = value.strip().rstrip("/")
    if platform == "binance_square" and "://" in handle:
        parsed = urlparse(handle)
        parts = [part for part in parsed.path.split("/") if part]
        if not parsed.hostname or not parsed.hostname.endswith("binance.com"):
            raise HTTPException(status_code=422, detail="Invalid Binance Square profile URL")
        if len(parts) < 3 or parts[-2] != "profile":
            raise HTTPException(status_code=422, detail="Invalid Binance Square profile URL")
        handle = parts[-1]
    handle = handle.lstrip("@")
    if not handle or "/" in handle:
        raise HTTPException(status_code=422, detail="Invalid KOL handle")
    return handle


class SubscriptionCreate(BaseModel):
    platform: str = Field(default="x", min_length=1, max_length=32)
    handle: str = Field(min_length=1, max_length=255)
    accountId: str | None = Field(default=None, pattern=r"^[0-9]{8,32}$")
    intervalMinutes: int = Field(default=DEFAULT_MONITOR_INTERVAL_MINUTES, ge=1)
    prompt: str | None = None
    primaryMarket: str | None = None
    systemPrompt: str | None = None
    userPrompt: str | None = None
    outputSchema: dict | None = None
    markets: list[str] = Field(default_factory=lambda: list(ALL_MARKETS))
    ntfyServer: str | None = None
    ntfyTopic: str | None = None
    ntfyToken: str | None = None

    @field_validator("platform")
    @classmethod
    def validate_platform(cls, value: str) -> str:
        if value not in PLATFORMS:
            raise ValueError(f"platform must be one of {sorted(PLATFORMS)}")
        return value

    @model_validator(mode="after")
    def validate_trade_account_id(self) -> "SubscriptionCreate":
        if self.platform in TRADE_PLATFORMS:
            if self.accountId is None:
                raise ValueError("accountId is required for private trade platforms")
            if self.intervalMinutes != DEFAULT_MONITOR_INTERVAL_MINUTES:
                raise ValueError("private trade platforms require a 10 minute interval")
        elif self.accountId is not None:
            raise ValueError("accountId is only valid for private trade platforms")
        return self

    @field_validator("markets")
    @classmethod
    def validate_markets(cls, values: list[str]) -> list[str]:
        invalid = set(values) - MARKETS
        if invalid:
            raise ValueError(f"unsupported markets: {sorted(invalid)}")
        return list(dict.fromkeys(values)) or list(ALL_MARKETS)

    @field_validator("outputSchema")
    @classmethod
    def validate_output_schema(cls, value: dict | None) -> dict | None:
        if value is not None:
            _validate_output_schema(value)
        return value


class SubscriptionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intervalMinutes: int | None = Field(default=None, ge=1)
    prompt: str | None = None
    systemPrompt: str | None = None
    userPrompt: str | None = None
    outputSchema: dict | None = None
    markets: list[str] | None = None
    enabled: bool | None = None
    ntfyServer: str | None = None
    ntfyTopic: str | None = None
    ntfyToken: str | None = None

    @field_validator("markets")
    @classmethod
    def validate_markets(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        invalid = set(values) - MARKETS
        if invalid:
            raise ValueError(f"unsupported markets: {sorted(invalid)}")
        return list(dict.fromkeys(values)) or list(ALL_MARKETS)

    @field_validator("outputSchema")
    @classmethod
    def validate_output_schema(cls, value: dict | None) -> dict | None:
        if value is not None:
            _validate_output_schema(value)
        return value


class LegacyLoginRequest(BaseModel):
    username: str | None = None
    password: str = Field(min_length=1)


require_admin = require_authenticated


@router.post("/login")
def legacy_login(payload: LegacyLoginRequest, response: Response) -> dict:
    username = payload.username or get_settings().admin_username or ""
    token = authenticate(username, payload.password)
    set_session_cookie(response, token)
    return {"accessToken": token, "username": username}


@router.get("/health")
def admin_health(_: str = Depends(require_admin)) -> dict:
    return {"status": "ok"}


@router.get("/config-options")
def config_options(db: Session = Depends(get_db), _: str = Depends(require_admin)) -> dict:
    settings = get_settings()
    return {
        "platforms": sorted(PLATFORMS),
        "markets": list(ALL_MARKETS),
        "defaultIntervalMinutes": DEFAULT_MONITOR_INTERVAL_MINUTES,
        "defaultSystemPrompt": DEFAULT_SYSTEM_PROMPT,
        "defaultUserPrompt": DEFAULT_USER_PROMPT,
        "defaultOutputSchema": DEFAULT_OUTPUT_SCHEMA,
        "defaultNtfyServer": settings.ntfy_server or "",
        "defaultNtfyTopic": settings.ntfy_topic or "",
        "collectorHealth": collector_health_payload(db),
    }


@router.get("/subscriptions")
def subscriptions(db: Session = Depends(get_db), _: str = Depends(require_admin)) -> dict:
    rows = db.scalars(
        select(Subscription)
        .where(Subscription.deleted_at.is_(None))
        .order_by(Subscription.id)
    ).all()
    return {"items": [_subscription_payload(db, row) for row in rows]}


def _default_model_config(db: Session) -> ModelConfig:
    model_config = db.scalar(select(ModelConfig).where(ModelConfig.is_default.is_(True)))
    if model_config is not None:
        return model_config
    settings = get_settings()
    model_config = ModelConfig(
        name="DeepSeek",
        base_url=settings.openai_base_url,
        model=settings.openai_model,
        is_default=True,
    )
    db.add(model_config)
    db.flush()
    return model_config


def _subscription_payload(db: Session, subscription: Subscription) -> dict:
    rule = db.scalar(select(NotificationRule).where(NotificationRule.subscription_id == subscription.id))
    try:
        output_schema = json.loads(subscription.output_schema_json) if subscription.output_schema_json else None
    except json.JSONDecodeError:
        output_schema = None
    try:
        markets = json.loads(subscription.markets_json) if subscription.markets_json else list(ALL_MARKETS)
    except json.JSONDecodeError:
        markets = list(ALL_MARKETS)
    return {
        "id": subscription.id,
        "platform": subscription.platform,
        "handle": subscription.platform_handle,
        "accountId": subscription.platform_account_id,
        "visibility": subscription.visibility,
        "intervalMinutes": subscription.interval_minutes,
        "enabled": subscription.enabled,
        "checkpoint": subscription.checkpoint,
        "prompt": subscription.prompt,
        "systemPrompt": subscription.system_prompt,
        "userPrompt": subscription.user_prompt,
        "outputSchema": output_schema,
        "markets": markets,
        "promptVersion": subscription.prompt_version or "default-v2",
        "effectiveSystemPrompt": subscription.system_prompt or subscription.prompt or DEFAULT_SYSTEM_PROMPT,
        "effectiveUserPrompt": subscription.user_prompt or DEFAULT_USER_PROMPT,
        "effectiveOutputSchema": output_schema or DEFAULT_OUTPUT_SCHEMA,
        "ntfyServer": rule.ntfy_server if rule else None,
        "ntfyTopic": rule.ntfy_topic if rule else None,
        "lastSuccessAt": subscription.last_success_at.isoformat()
        if subscription.last_success_at
        else None,
    }


@router.post("/subscriptions")
def create_subscription(
    payload: SubscriptionCreate,
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
) -> dict:
    handle = _normalize_handle(payload.platform, payload.handle)
    identity_filter = (
        Subscription.platform_account_id == payload.accountId
        if payload.platform in TRADE_PLATFORMS
        else Subscription.platform_handle == handle
    )
    existing = db.scalar(
        select(Subscription).where(
            Subscription.platform == payload.platform,
            identity_filter,
        )
    )
    if existing is not None and existing.deleted_at is None:
        raise HTTPException(status_code=409, detail="Subscription already exists")

    kol = db.scalar(
        select(KolProfile).where(
            KolProfile.platform == payload.platform,
            KolProfile.display_name == handle,
        )
    )
    if kol is None:
        kol = KolProfile(
            platform=payload.platform,
            display_name=handle,
            description=f"Monitored {payload.platform} financial KOL.",
            primary_market=payload.primaryMarket,
        )
        db.add(kol)
        db.flush()

    system_prompt = payload.systemPrompt or DEFAULT_SYSTEM_PROMPT
    user_prompt = payload.userPrompt or DEFAULT_USER_PROMPT
    output_schema = payload.outputSchema or DEFAULT_OUTPUT_SCHEMA

    if existing is not None:
        existing.kol_profile_id = kol.id
        existing.platform_account_id = payload.accountId
        existing.platform_handle = handle
        existing.visibility = (
            "private" if payload.platform in TRADE_PLATFORMS else "public"
        )
        existing.interval_minutes = payload.intervalMinutes
        existing.prompt = payload.prompt
        existing.system_prompt = system_prompt
        existing.user_prompt = user_prompt
        existing.output_schema_json = json.dumps(output_schema, ensure_ascii=False)
        existing.markets_json = json.dumps(payload.markets, ensure_ascii=False)
        existing.prompt_version = "custom-v1"
        existing.model_config_id = _default_model_config(db).id
        existing.enabled = True
        existing.deleted_at = None
        rule = db.scalar(
            select(NotificationRule).where(NotificationRule.subscription_id == existing.id)
        )
        if rule is None:
            rule = NotificationRule(subscription_id=existing.id)
            db.add(rule)
        rule.ntfy_server = payload.ntfyServer
        rule.ntfy_topic = payload.ntfyTopic
        rule.ntfy_token_encrypted = payload.ntfyToken
        rule.min_confidence = "中"
        rule.require_asset = True
        rule.enabled = True
        db.commit()
        db.refresh(existing)
        return {"item": _subscription_payload(db, existing)}

    subscription = Subscription(
        kol_profile_id=kol.id,
        platform=payload.platform,
        platform_account_id=payload.accountId,
        platform_handle=handle,
        visibility="private" if payload.platform in TRADE_PLATFORMS else "public",
        interval_minutes=payload.intervalMinutes,
        prompt=payload.prompt,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        output_schema_json=json.dumps(output_schema, ensure_ascii=False),
        markets_json=json.dumps(payload.markets, ensure_ascii=False),
        prompt_version="custom-v1",
        model_config_id=_default_model_config(db).id,
        enabled=True,
    )
    db.add(subscription)
    db.flush()
    db.add(
        NotificationRule(
            subscription_id=subscription.id,
            ntfy_server=payload.ntfyServer,
            ntfy_topic=payload.ntfyTopic,
            ntfy_token_encrypted=payload.ntfyToken,
            min_confidence="中",
            require_asset=True,
            enabled=True,
        )
    )
    db.commit()
    db.refresh(subscription)
    return {"item": _subscription_payload(db, subscription)}


@router.patch("/subscriptions/{subscription_id}")
def update_subscription(
    subscription_id: int,
    payload: SubscriptionUpdate,
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
) -> dict:
    subscription = db.get(Subscription, subscription_id)
    if subscription is None or subscription.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    if payload.intervalMinutes is not None:
        if (
            subscription.platform in TRADE_PLATFORMS
            and payload.intervalMinutes != DEFAULT_MONITOR_INTERVAL_MINUTES
        ):
            raise HTTPException(
                status_code=422,
                detail="private trade platforms require a 10 minute interval",
            )
        subscription.interval_minutes = payload.intervalMinutes
    if payload.prompt is not None:
        subscription.prompt = payload.prompt
    if "systemPrompt" in payload.model_fields_set:
        subscription.system_prompt = payload.systemPrompt
    if "userPrompt" in payload.model_fields_set:
        subscription.user_prompt = payload.userPrompt
    if "outputSchema" in payload.model_fields_set:
        subscription.output_schema_json = (
            json.dumps(payload.outputSchema, ensure_ascii=False) if payload.outputSchema else None
        )
    if payload.markets is not None:
        subscription.markets_json = json.dumps(payload.markets, ensure_ascii=False)
    if any(
        field in payload.model_fields_set
        for field in {"systemPrompt", "userPrompt", "outputSchema"}
    ):
        subscription.prompt_version = "custom-v1" if any(
            [subscription.system_prompt, subscription.user_prompt, subscription.output_schema_json]
        ) else "default-v2"
    if payload.enabled is not None:
        subscription.enabled = payload.enabled
    rule = db.scalar(select(NotificationRule).where(NotificationRule.subscription_id == subscription.id))
    if rule is None:
        rule = NotificationRule(subscription_id=subscription.id, min_confidence="中", require_asset=True)
        db.add(rule)
    if payload.ntfyServer is not None:
        rule.ntfy_server = payload.ntfyServer
    if payload.ntfyTopic is not None:
        rule.ntfy_topic = payload.ntfyTopic
    if payload.ntfyToken is not None:
        rule.ntfy_token_encrypted = payload.ntfyToken
    db.commit()
    db.refresh(subscription)
    return {"item": _subscription_payload(db, subscription)}


@router.delete("/subscriptions/{subscription_id}", status_code=204)
def delete_subscription(
    subscription_id: int,
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
) -> Response:
    subscription = db.get(Subscription, subscription_id)
    if subscription is None or subscription.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    subscription.enabled = False
    subscription.deleted_at = datetime.now(UTC)
    rule = db.scalar(
        select(NotificationRule).where(NotificationRule.subscription_id == subscription.id)
    )
    if rule is not None:
        rule.enabled = False
    db.commit()
    return Response(status_code=204)


@router.get("/signals")
def private_signals(
    kol_id: int | None = None,
    asset: str | None = None,
    symbol: str | None = None,
    tag: str | None = None,
    stance: str | None = None,
    actionable: bool | None = None,
    platform: str | None = None,
    time_range: Literal["all", "1h", "6h", "24h", "7d"] = "all",
    min_importance: int = Query(default=1, ge=1, le=5),
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
) -> dict:
    return signal_page(
        db,
        visibility="private",
        kol_id=kol_id,
        platform=platform,
        asset=asset or symbol,
        tag=tag,
        stance=stance,
        actionable=actionable,
        time_range=time_range,
        min_importance=min_importance,
        limit=limit,
        offset=offset,
    )


@router.get("/crawl-runs")
def crawl_runs(db: Session = Depends(get_db), _: str = Depends(require_admin)) -> dict:
    rows = db.scalars(select(CrawlRun).order_by(desc(CrawlRun.id)).limit(50)).all()
    return {"items": [{"id": row.id, "status": row.status, "error": row.error_message} for row in rows]}


@router.get("/notification-events")
def notification_events(db: Session = Depends(get_db), _: str = Depends(require_admin)) -> dict:
    rows = db.scalars(select(NotificationEvent).order_by(desc(NotificationEvent.id)).limit(50)).all()
    return {"items": [{"id": row.id, "status": row.status, "error": row.error_message} for row in rows]}
