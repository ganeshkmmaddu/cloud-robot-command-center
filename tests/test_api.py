from fastapi.testclient import TestClient

from cloud_robot_bridge.api import create_app


def test_api_health_and_command_round_trip() -> None:
    app = create_app()
    client = TestClient(app)

    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    command = client.post(
        "/api/commands",
        json={"action": "navigate", "request_id": "req-77", "target": {"x": 3.0, "y": 4.0, "theta": 0.5}},
    )
    assert command.status_code == 200
    assert command.json()["command"]["action"] == "navigate"

    state = client.get("/api/state")
    assert state.status_code == 200
    assert state.json()["command_count"] == 1
    assert state.json()["latest_command"]["request_id"] == "req-77"


def test_api_accepts_telemetry_submission() -> None:
    app = create_app()
    client = TestClient(app)

    response = client.post(
        "/api/telemetry",
        json={"robot_id": "bot-01", "status": "moving", "battery": 43, "pose": {"x": 1.1, "y": 2.2, "theta": 0.3}},
    )
    assert response.status_code == 200
    data = response.json()["telemetry"]
    assert data["robot_id"] == "bot-01"
    assert data["battery"] == 43

    state = client.get("/api/state")
    assert state.json()["robot_id"] == "bot-01"
    assert state.json()["telemetry_count"] == 1
