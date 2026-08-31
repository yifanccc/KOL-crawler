from sqlalchemy import select
from fastapi.testclient import TestClient

from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.main import app
from app.models import (
    Asset,
    KolProfile,
    NotificationRule,
    RawPost,
    Signal,
    SignalAsset,
    Subscription,
)
from app.services.structurer import (
    DEFAULT_OUTPUT_SCHEMA,
    DEFAULT_SYSTEM_PROMPT,
    DEFAULT_USER_PROMPT,
)


def reset_database() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def auth_headers(client: TestClient) -> dict[str, str]:
    token = client.post(
        "/api/auth/login",
        json={"username": "testadmin", "password": "test-admin-password"},
    ).json()["accessToken"]
    return {"Authorization": f"Bearer {token}"}


def seed_signal(
    *,
    visibility: str,
    platform: str,
    summary: str,
    signal_has_subscription: bool = True,
    account_id: str = "5075281354358777856",
) -> tuple[int, int]:
    with SessionLocal.begin() as session:
        kol = KolProfile(platform=platform, display_name=f"{platform}-{summary}")
        session.add(kol)
        session.flush()
        subscription = Subscription(
            kol_profile_id=kol.id,
            platform=platform,
            platform_account_id=(
                account_id if platform == "binance_copy" else None
            ),
            platform_handle=kol.display_name,
            visibility=visibility,
            interval_minutes=10,
        )
        session.add(subscription)
        session.flush()
        raw_post = RawPost(
            subscription_id=subscription.id,
            platform=platform,
            external_id=f"{platform}-{summary}",
            author_name=kol.display_name,
            raw_text=summary,
            analysis_status="completed",
        )
        session.add(raw_post)
        session.flush()
        signal = Signal(
            raw_post_id=raw_post.id,
            subscription_id=subscription.id if signal_has_subscription else None,
            actionable=True,
            stance="neutral",
            summary=summary,
            structured_status=(
                "deterministic" if visibility == "private" else "ok"
            ),
        )
        session.add(signal)
        session.flush()
        return signal.id, kol.id


def test_login_sets_http_only_cookie_and_logout_revokes_access() -> None:
    reset_database()
    with TestClient(app) as client:
        wrong_password = client.post(
            "/api/auth/login",
            json={"username": "testadmin", "password": "wrong"},
        )
        correct_password = client.post(
            "/api/auth/login",
            json={"username": "testadmin", "password": "test-admin-password"},
        )
        protected = client.get("/api/admin/health")
        logout = client.post("/api/auth/logout")
        logged_out = client.get("/api/admin/health")

    assert wrong_password.status_code == 401
    assert correct_password.status_code == 200
    assert "accessToken" in correct_password.json()
    cookie = correct_password.headers["set-cookie"]
    assert "kol_session=" in cookie
    assert "HttpOnly" in cookie
    assert protected.status_code == 200
    assert logout.status_code == 200
    assert logged_out.status_code == 401


def test_admin_can_create_and_update_subscription() -> None:
    reset_database()
    with TestClient(app) as client:
        headers = auth_headers(client)
        create_response = client.post(
            "/api/admin/subscriptions",
            headers=headers,
            json={
                "platform": "x",
                "handle": "senerity",
                "intervalMinutes": 2,
                "systemPrompt": "你是加密交易观点分析师。",
                "userPrompt": "分析以下内容：{raw_content}",
                "outputSchema": DEFAULT_OUTPUT_SCHEMA,
                "markets": ["crypto", "us_stock"],
                "ntfyServer": "https://ntfy.sh",
                "ntfyTopic": "kol-test",
            },
        )

        assert create_response.status_code == 200
        item = create_response.json()["item"]
        assert item["handle"] == "senerity"
        assert item["intervalMinutes"] == 2
        assert item["systemPrompt"] == "你是加密交易观点分析师。"
        assert item["userPrompt"] == "分析以下内容：{raw_content}"
        assert item["markets"] == ["crypto", "us_stock"]
        assert item["effectiveSystemPrompt"]
        assert item["effectiveUserPrompt"]
        assert item["effectiveOutputSchema"]

        update_response = client.patch(
            f"/api/admin/subscriptions/{item['id']}",
            headers=headers,
            json={
                "intervalMinutes": 1,
                "enabled": False,
                "systemPrompt": "只提取明确交易观点。",
                "markets": ["a_share"],
            },
        )
        list_response = client.get("/api/admin/subscriptions", headers=headers)
    with SessionLocal() as session:
        notification_rule = session.scalar(
            select(NotificationRule).where(
                NotificationRule.subscription_id == item["id"]
            )
        )

    assert update_response.status_code == 200
    updated = update_response.json()["item"]
    assert updated["intervalMinutes"] == 1
    assert updated["enabled"] is False
    assert updated["systemPrompt"] == "只提取明确交易观点。"
    assert updated["markets"] == ["a_share"]
    assert notification_rule is not None
    assert notification_rule.min_confidence == "中"
    assert any(row["handle"] == "senerity" for row in list_response.json()["items"])


def test_new_subscription_uses_ten_minute_and_fixed_prompt_defaults() -> None:
    reset_database()
    with TestClient(app) as client:
        headers = auth_headers(client)
        options = client.get("/api/admin/config-options", headers=headers)
        created = client.post(
            "/api/admin/subscriptions",
            headers=headers,
            json={"platform": "x", "handle": "new-defaults"},
        )

    assert options.status_code == 200
    assert options.json()["defaultIntervalMinutes"] == 10
    assert created.status_code == 200
    item = created.json()["item"]
    assert item["intervalMinutes"] == 10
    assert item["systemPrompt"] == DEFAULT_SYSTEM_PROMPT
    assert item["userPrompt"] == DEFAULT_USER_PROMPT
    assert item["outputSchema"] == DEFAULT_OUTPUT_SCHEMA
    assert "内容简洁，不需要增加作者认为" in item["systemPrompt"]


def test_binance_copy_subscription_uses_fixed_account_identity_and_visibility() -> None:
    reset_database()
    with TestClient(app) as client:
        headers = auth_headers(client)
        missing_account = client.post(
            "/api/admin/subscriptions",
            headers=headers,
            json={"platform": "binance_copy", "handle": "熬鹰资本"},
        )
        invalid_account = client.post(
            "/api/admin/subscriptions",
            headers=headers,
            json={
                "platform": "binance_copy",
                "handle": "熬鹰资本",
                "accountId": "not-a-number",
            },
        )
        invalid_interval = client.post(
            "/api/admin/subscriptions",
            headers=headers,
            json={
                "platform": "binance_copy",
                "handle": "熬鹰资本",
                "accountId": "5075281354358777856",
                "intervalMinutes": 10,
            },
        )
        invalid_prompt = client.post(
            "/api/admin/subscriptions",
            headers=headers,
            json={
                "platform": "binance_copy",
                "handle": "不应使用提示词",
                "accountId": "5075281354358777857",
                "systemPrompt": "交易订阅不应配置模型",
            },
        )
        invalid_start = client.post(
            "/api/admin/subscriptions",
            headers=headers,
            json={
                "platform": "binance_copy",
                "handle": "无时区起算",
                "accountId": "5075281354358777858",
                "positionStartAt": "2026-08-19T00:00:00",
            },
        )
        created = client.post(
            "/api/admin/subscriptions",
            headers=headers,
            json={
                "platform": "binance_copy",
                "handle": "熬鹰资本",
                "accountId": "5075281354358777856",
                "positionStartAt": "2026-08-19T00:00:00+08:00",
            },
        )
        duplicate = client.post(
            "/api/admin/subscriptions",
            headers=headers,
            json={
                "platform": "binance_copy",
                "handle": "仿冒昵称",
                "accountId": "5075281354358777856",
            },
        )

        assert created.status_code == 200
        item = created.json()["item"]
        mutable_interval = client.patch(
            f"/api/admin/subscriptions/{item['id']}",
            headers=headers,
            json={"intervalMinutes": 1},
        )
        invalid_mutable_interval = client.patch(
            f"/api/admin/subscriptions/{item['id']}",
            headers=headers,
            json={"intervalMinutes": 10},
        )
        mutable_account = client.patch(
            f"/api/admin/subscriptions/{item['id']}",
            headers=headers,
            json={"accountId": "11111111"},
        )
        mutable_prompt = client.patch(
            f"/api/admin/subscriptions/{item['id']}",
            headers=headers,
            json={"systemPrompt": "交易订阅不应配置模型"},
        )
    with SessionLocal() as session:
        notification_rule = session.scalar(
            select(NotificationRule).where(
                NotificationRule.subscription_id == item["id"]
            )
        )
        stored_subscription = session.get(Subscription, item["id"])

    assert missing_account.status_code == 422
    assert invalid_account.status_code == 422
    assert invalid_interval.status_code == 422
    assert invalid_prompt.status_code == 422
    assert invalid_start.status_code == 422
    assert item["accountId"] == "5075281354358777856"
    assert item["positionStartAt"] == "2026-08-18T16:00:00+00:00"
    assert item["visibility"] == "private"
    assert item["intervalMinutes"] == 1
    assert item["systemPrompt"] is None
    assert item["userPrompt"] is None
    assert item["outputSchema"] is None
    assert item["effectiveSystemPrompt"] == ""
    assert item["effectiveUserPrompt"] == ""
    assert item["effectiveOutputSchema"] == {}
    assert stored_subscription is not None
    assert stored_subscription.model_config_id is None
    assert notification_rule is not None
    assert notification_rule.min_confidence == "低"
    assert duplicate.status_code == 409
    assert mutable_interval.status_code == 200
    assert invalid_mutable_interval.status_code == 422
    assert mutable_account.status_code == 422
    assert mutable_prompt.status_code == 422


def test_private_trade_data_only_appears_in_admin_scope() -> None:
    reset_database()
    public_signal_id, public_kol_id = seed_signal(
        visibility="public", platform="x", summary="公开信号"
    )
    private_signal_id, private_kol_id = seed_signal(
        visibility="private",
        platform="binance_copy",
        summary="私有交易变化",
    )
    fallback_private_id, fallback_private_kol_id = seed_signal(
        visibility="private",
        platform="binance_copy",
        summary="私有回退关联",
        signal_has_subscription=False,
        account_id="5075281354358777857",
    )
    with SessionLocal.begin() as session:
        public_signal = session.get(Signal, public_signal_id)
        private_signal = session.get(Signal, private_signal_id)
        fallback_private = session.get(Signal, fallback_private_id)
        shared = Asset(symbol="BTCUSDT", market="CRYPTO", asset_type="crypto")
        private_only = Asset(
            symbol="ETHUSDT", market="CRYPTO", asset_type="crypto"
        )
        orphan = Asset(symbol="LEGACY", market="CRYPTO", asset_type="crypto")
        session.add_all([shared, private_only, orphan])
        session.flush()
        session.add_all(
            [
                SignalAsset(signal_id=public_signal.id, asset_id=shared.id),
                SignalAsset(signal_id=private_signal.id, asset_id=shared.id),
                SignalAsset(signal_id=fallback_private.id, asset_id=private_only.id),
            ]
        )

    with TestClient(app) as client:
        headers = auth_headers(client)
        regular = client.get("/api/signals", headers=headers)
        private = client.get("/api/admin/signals", headers=headers)
        leaked_detail = client.get(
            f"/api/signals/{private_signal_id}", headers=headers
        )
        fallback_leaked_detail = client.get(
            f"/api/signals/{fallback_private_id}", headers=headers
        )
        kols = client.get("/api/kols", headers=headers)
        assets = client.get("/api/assets", headers=headers)
    with TestClient(app) as anonymous_client:
        anonymous = anonymous_client.get("/api/admin/signals")

    assert [item["summary"] for item in regular.json()["items"]] == ["公开信号"]
    assert {item["summary"] for item in private.json()["items"]} == {
        "私有交易变化",
        "私有回退关联",
    }
    assert regular.json()["overallTotal"] == 1
    assert private.json()["overallTotal"] == 2
    assert leaked_detail.json()["item"] is None
    assert fallback_leaked_detail.json()["item"] is None
    visible_kol_ids = {item["id"] for item in kols.json()["items"]}
    assert public_kol_id in visible_kol_ids
    assert private_kol_id not in visible_kol_ids
    assert fallback_private_kol_id not in visible_kol_ids
    assert {item["symbol"] for item in assets.json()["items"]} == {
        "BTCUSDT",
        "LEGACY",
    }
    assert anonymous.status_code == 401


def test_regular_subscription_rejects_trade_account_id() -> None:
    reset_database()
    with TestClient(app) as client:
        response = client.post(
            "/api/admin/subscriptions",
            headers=auth_headers(client),
            json={
                "platform": "x",
                "handle": "regular-kol",
                "accountId": "5075281354358777856",
            },
        )

    assert response.status_code == 422


def test_admin_rejects_incompatible_custom_output_schema() -> None:
    reset_database()
    with TestClient(app) as client:
        response = client.post(
            "/api/admin/subscriptions",
            headers=auth_headers(client),
            json={
                "platform": "x",
                "handle": "schema-check",
                "intervalMinutes": 1,
                "outputSchema": {"type": "object", "properties": {}},
            },
        )
    assert response.status_code == 422


def test_same_handle_on_different_platforms_creates_distinct_kols() -> None:
    reset_database()
    with TestClient(app) as client:
        headers = auth_headers(client)
        for platform in ("x", "binance_square"):
            response = client.post(
                "/api/admin/subscriptions",
                headers=headers,
                json={
                    "platform": platform,
                    "handle": "shared-handle",
                    "intervalMinutes": 1,
                },
            )
            assert response.status_code == 200
        kols_response = client.get("/api/kols", headers=headers)

    assert kols_response.status_code == 200
    shared_kols = {
        (item["platform"], item["handle"])
        for item in kols_response.json()["items"]
        if item["handle"] == "shared-handle"
    }
    assert shared_kols == {
        ("x", "shared-handle"),
        ("binance_square", "shared-handle"),
    }
    with SessionLocal() as session:
        subscriptions = session.scalars(
            select(Subscription)
            .where(Subscription.platform_handle == "shared-handle")
            .order_by(Subscription.id)
        ).all()
        assert subscriptions[0].kol_profile_id != subscriptions[1].kol_profile_id


def test_binance_profile_url_is_normalized_to_handle() -> None:
    reset_database()
    with TestClient(app) as client:
        response = client.post(
            "/api/admin/subscriptions",
            headers=auth_headers(client),
            json={
                "platform": "binance_square",
                "handle": "https://www.binance.com/zh-CN/square/profile/btc7873/",
                "intervalMinutes": 1,
            },
        )

    assert response.status_code == 200
    assert response.json()["item"]["handle"] == "btc7873"


def test_admin_delete_subscription_hides_kol_and_preserves_signal_history() -> None:
    reset_database()
    with TestClient(app) as client:
        headers = auth_headers(client)
        created = client.post(
            "/api/admin/subscriptions",
            headers=headers,
            json={"platform": "x", "handle": "delete-me", "intervalMinutes": 1},
        ).json()["item"]
        with SessionLocal.begin() as session:
            raw_post = RawPost(
                subscription_id=created["id"],
                platform="x",
                external_id="delete-history",
                author_handle="delete-me",
                raw_text="$BTC long",
                analysis_status="completed",
            )
            session.add(raw_post)
            session.flush()
            session.add(
                Signal(
                    raw_post_id=raw_post.id,
                    subscription_id=created["id"],
                    actionable=True,
                    stance="bullish",
                    stance_cn="多",
                    summary="BTC 看多",
                    structured_status="ok",
                )
            )

        delete_response = client.delete(
            f"/api/admin/subscriptions/{created['id']}",
            headers=headers,
        )
        subscriptions_response = client.get("/api/admin/subscriptions", headers=headers)
        kols_response = client.get("/api/kols", headers=headers)
        signals_response = client.get("/api/signals", headers=headers)

    assert delete_response.status_code == 204
    assert all(
        item["handle"] != "delete-me" for item in subscriptions_response.json()["items"]
    )
    assert all(item["handle"] != "delete-me" for item in kols_response.json()["items"])
    assert "BTC 看多" in [item["summary"] for item in signals_response.json()["items"]]
    with SessionLocal() as session:
        subscription = session.get(Subscription, created["id"])
        assert subscription is not None
        assert subscription.enabled is False
        assert subscription.deleted_at is not None
    reset_database()
