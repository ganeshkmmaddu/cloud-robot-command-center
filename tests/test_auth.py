from fastapi.testclient import TestClient

from cloud_robot_bridge.api import create_app
from cloud_robot_bridge.auth import AuthService, User


def test_auth_service_validates_default_credentials() -> None:
    service = AuthService()

    assert service.validate("admin", "admin123") is True
    assert service.validate("admin", "wrong") is False


def test_auth_service_issues_and_validates_tokens() -> None:
    service = AuthService()
    token = service.issue_token("admin")

    assert service.validate_token(token) is True
    assert service.validate_token(token, "admin") is True
    assert service.username_for_token(token) == "admin"
    assert service.role_for_token(token) == "admin"


def test_auth_service_supports_roles() -> None:
    service = AuthService(users=[User("ops", "ops123", "operator")])
    token = service.issue_token("ops")

    assert service.validate("ops", "ops123") is True
    assert service.validate_token(token, "operator") is True
    assert service.validate_token(token, "admin") is False


def test_dashboard_requires_bearer_token_when_enforced(monkeypatch) -> None:
    monkeypatch.setenv("COMMAND_CENTER_REQUIRE_AUTH", "true")
    app = create_app(db_path="dashboard-auth.db")
    client = TestClient(app)

    blocked = client.get("/api/state")
    assert blocked.status_code == 401

    login = client.post("/api/login", json={"username": "admin", "password": "admin123"})
    assert login.status_code == 200
    token = login.json()["token"]
    assert token is not None
    assert login.json()["role"] == "admin"

    authorized = client.get("/api/state", headers={"Authorization": f"Bearer {token}"})
    assert authorized.status_code == 200

    command = client.post(
        "/api/commands",
        headers={"Authorization": f"Bearer {token}"},
        json={"action": "navigate", "request_id": "auth-cmd", "target": {"x": 1.0, "y": 2.0, "theta": 0.0}},
    )
    assert command.status_code == 200
    assert command.json()["command"]["request_id"] == "auth-cmd"
