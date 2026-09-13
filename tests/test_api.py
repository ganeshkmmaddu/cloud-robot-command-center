from fastapi.testclient import TestClient

from cloud_robot_bridge.api import CommandCenterStore, create_app
from cloud_robot_bridge.protocol import Command, Pose, Telemetry


def test_api_health_and_command_round_trip(tmp_path) -> None:
    app = create_app(db_path=str(tmp_path / "health.db"))
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

    telemetry = client.post(
        "/api/telemetry",
        json={"robot_id": "bot-main", "status": "moving", "battery": 88, "pose": {"x": 1.0, "y": 2.0, "theta": 0.1}},
    )
    assert telemetry.status_code == 200

    state = client.get("/api/state")
    assert state.status_code == 200
    assert state.json()["command_count"] == 1
    assert state.json()["latest_command"]["request_id"] == "req-77"
    assert state.json()["robot_count"] == 1
    assert state.json()["robots"][0]["robot_id"] == "bot-main"
    assert state.json()["health"]["battery"] == 88
    assert state.json()["health"]["cpu_percent"] > 0


def test_api_accepts_telemetry_submission(tmp_path) -> None:
    app = create_app(db_path=str(tmp_path / "telemetry.db"))
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


def test_store_persists_history_to_sqlite(tmp_path) -> None:
    db_path = tmp_path / "history.db"
    store = CommandCenterStore(db_path=str(db_path))
    store.handle_telemetry(Telemetry("persisted", Pose(1, 2, 0.1), 67, status="moving"))
    store.handle_command(Command("navigate", "req-88", Pose(3, 4, 0.5)))
    store.add_task("r-1", "patrol", Pose(1, 2, 0.2))

    reloaded = CommandCenterStore(db_path=str(db_path))
    assert reloaded.telemetry_history[-1].robot_id == "persisted"
    assert reloaded.command_history[-1].request_id == "req-88"
    assert reloaded.snapshot()["task_count"] == 1


def test_alerts_are_generated_on_low_battery_and_errors(tmp_path) -> None:
    app = create_app(db_path=str(tmp_path / "alerts.db"))
    client = TestClient(app)

    response = client.post(
        "/api/telemetry",
        json={"robot_id": "bot-alert", "status": "error", "battery": 12, "pose": {"x": 8, "y": 9, "theta": 1.2}},
    )
    assert response.status_code == 200

    state = client.get("/api/state")
    assert state.json()["alerts"][0]["robot_id"] == "bot-alert"
    assert any(item["severity"] == "critical" for item in state.json()["alerts"])


def test_event_log_tracks_alerts_and_status_updates(tmp_path) -> None:
    app = create_app(db_path=str(tmp_path / "events.db"))
    client = TestClient(app)

    response = client.post(
        "/api/telemetry",
        json={"robot_id": "bot-event", "status": "moving", "battery": 14, "pose": {"x": 3.0, "y": 4.0, "theta": 0.1}},
    )
    assert response.status_code == 200

    event_response = client.get("/api/events")
    assert event_response.status_code == 200
    assert event_response.json()[-1]["robot_id"] == "bot-event"

    state = client.get("/api/state")
    assert state.json()["event_count"] >= 2
    assert any(item["category"] == "alert" for item in state.json()["events"])


def test_task_api_runs_queue_workflow(tmp_path) -> None:
    app = create_app(db_path=str(tmp_path / "tasks.db"))
    client = TestClient(app)

    created = client.post(
        "/api/tasks",
        json={"robot_id": "bot-task", "action": "inspect", "target": {"x": 1.5, "y": 2.0, "theta": 0.3}},
    )
    assert created.status_code == 200
    task_id = created.json()["task"]["id"]

    updated = client.patch(f"/api/tasks/{task_id}?status=in_progress")
    assert updated.status_code == 200
    assert updated.json()["task"]["status"] == "in_progress"

    state = client.get("/api/state")
    assert state.json()["task_count"] == 1


def test_websocket_streams_state_updates(tmp_path) -> None:
    app = create_app(db_path=str(tmp_path / "ws.db"))
    client = TestClient(app)

    with client.websocket_connect("/ws") as websocket:
        first_payload = websocket.receive_json()
        assert first_payload["telemetry_count"] == 0

        client.post(
            "/api/telemetry",
            json={"robot_id": "bot-web", "status": "idle", "battery": 77, "pose": {"x": 4.0, "y": 5.0, "theta": 0.2}},
        )
        update = websocket.receive_json()
        assert update["robot_id"] == "bot-web"
        assert update["battery"] == 77
        assert update["robot_count"] == 1


def test_multi_robot_registry_tracks_several_robots(tmp_path) -> None:
    app = create_app(db_path=str(tmp_path / "robots.db"))
    client = TestClient(app)

    client.post(
        "/api/telemetry",
        json={"robot_id": "bot-a", "status": "moving", "battery": 50, "pose": {"x": 1, "y": 2, "theta": 0.1}},
    )
    client.post(
        "/api/telemetry",
        json={"robot_id": "bot-b", "status": "idle", "battery": 70, "pose": {"x": 3, "y": 4, "theta": 0.3}},
    )

    state = client.get("/api/state")
    assert state.json()["robot_count"] == 2
    robot_ids = {robot["robot_id"] for robot in state.json()["robots"]}
    assert {"bot-a", "bot-b"}.issubset(robot_ids)
