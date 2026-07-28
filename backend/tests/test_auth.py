from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Response
from fastapi.testclient import TestClient
from jose import jwt

from app.core.config import validate_runtime_settings
from app.main import app
from app.routers import auth


@pytest.fixture(autouse=True)
def reset_login_limiter():
    reset = getattr(auth, "reset_login_attempt_limiter", None)
    if reset is not None:
        reset()
    yield
    if reset is not None:
        reset()


def test_runtime_security_settings_require_credentials_and_reject_wildcard_cors() -> None:
    with pytest.raises(RuntimeError, match="ADMIN_USERNAME"):
        validate_runtime_settings(
            SimpleNamespace(
                admin_username=None,
                admin_password_hash="hash",
                jwt_secret="x" * 32,
                web_origin="http://localhost:3000",
                collector_agent_id="home",
                collector_token_hash="a" * 64,
            )
        )
    with pytest.raises(RuntimeError, match="wildcard"):
        validate_runtime_settings(
            SimpleNamespace(
                admin_username="admin",
                admin_password_hash="hash",
                jwt_secret="x" * 32,
                web_origin="*,http://localhost:3000",
                collector_agent_id="home",
                collector_token_hash="a" * 64,
            )
        )


def test_authenticate_checks_password_even_for_wrong_username(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    settings = SimpleNamespace(admin_username="admin", admin_password_hash="hash")
    monkeypatch.setattr(auth, "get_settings", lambda: settings)
    monkeypatch.setattr(
        auth,
        "verify_password",
        lambda password, password_hash: calls.append((password, password_hash)) or False,
    )

    with pytest.raises(HTTPException, match="Invalid username or password"):
        auth.authenticate("not-admin", "wrong-password")

    assert calls == [("wrong-password", "hash")]


def test_login_session_logout_and_protected_signals() -> None:
    with TestClient(app) as client:
        unauthenticated = client.get("/api/signals")
        wrong_username = client.post(
            "/api/auth/login", json={"username": "wrong", "password": "test-admin-password"}
        )
        wrong_password = client.post(
            "/api/auth/login", json={"username": "testadmin", "password": "wrong"}
        )
        login = client.post(
            "/api/auth/login",
            json={"username": "testadmin", "password": "test-admin-password"},
        )
        session = client.get("/api/auth/session")
        protected = client.get("/api/signals")
        logout = client.post("/api/auth/logout")
        logged_out = client.get("/api/signals")

    assert unauthenticated.status_code == 401
    assert wrong_username.status_code == 401
    assert wrong_password.status_code == 401
    assert login.status_code == 200
    cookie = login.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert session.json() == {"authenticated": True, "username": "testadmin"}
    assert protected.status_code == 200
    assert logout.status_code == 200
    assert logged_out.status_code == 401


def test_bearer_auth_rejects_invalid_and_expired_tokens() -> None:
    with TestClient(app) as client:
        token = client.post(
            "/api/auth/login",
            json={"username": "testadmin", "password": "test-admin-password"},
        ).json()["accessToken"]
        bearer = client.get("/api/signals", headers={"Authorization": f"Bearer {token}"})
        invalid = client.get("/api/signals", headers={"Authorization": "Bearer invalid"})
        expired_token = jwt.encode(
            {"sub": "testadmin", "exp": datetime.now(UTC) - timedelta(minutes=1)},
            "test-jwt-secret-that-is-long-enough-for-tests",
            algorithm="HS256",
        )
        expired = client.get("/api/signals", headers={"Authorization": f"Bearer {expired_token}"})

    assert bearer.status_code == 200
    assert invalid.status_code == 401
    assert expired.status_code == 401


def test_secure_cookie_configuration_sets_all_session_flags(monkeypatch) -> None:
    monkeypatch.setattr(
        auth,
        "get_settings",
        lambda: SimpleNamespace(
            auth_cookie_name="secure_session",
            access_token_expire_minutes=30,
            cookie_secure=True,
        ),
    )
    response = Response()

    auth.set_session_cookie(response, "token")

    cookie = response.headers["set-cookie"]
    assert "secure_session=token" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Secure" in cookie


def test_login_attempt_limiter_rejects_repeated_failures() -> None:
    with TestClient(app) as client:
        attempts = [
            client.post(
                "/api/auth/login",
                json={"username": "testadmin", "password": "wrong-password"},
            )
            for _ in range(5)
        ]
        blocked = client.post(
            "/api/auth/login",
            json={"username": "testadmin", "password": "wrong-password"},
        )

    assert [response.status_code for response in attempts] == [401] * 5
    assert blocked.status_code == 429
