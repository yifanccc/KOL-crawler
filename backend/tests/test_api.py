from fastapi.testclient import TestClient

from app.main import app


def test_signals_endpoint_requires_login_and_returns_items_after_login():
    with TestClient(app) as client:
        unauthenticated = client.get("/api/signals")
        login = client.post(
            "/api/auth/login",
            json={"username": "testadmin", "password": "test-admin-password"},
        )
        response = client.get("/api/signals")

    assert unauthenticated.status_code == 401
    assert login.status_code == 200
    assert login.cookies.get("kol_session")
    assert response.status_code == 200
    assert response.json()["items"] == []


def test_admin_health_requires_login():
    with TestClient(app) as client:
        response = client.get("/api/admin/health")

    assert response.status_code == 401
