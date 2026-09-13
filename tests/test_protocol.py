import json

import pytest

from cloud_robot_bridge.protocol import Command, Pose, Telemetry


def test_telemetry_is_json_safe_and_deterministic() -> None:
    telemetry = Telemetry("r-1", Pose(1.23456, -2.0, 0.5), 87, timestamp="2026-01-01T00:00:00+00:00")

    assert json.loads(telemetry.to_json()) == {
        "battery": 87,
        "pose": {"theta": 0.5, "x": 1.2346, "y": -2.0},
        "robot_id": "r-1",
        "status": "idle",
        "timestamp": "2026-01-01T00:00:00+00:00",
    }


def test_command_parses_optional_target() -> None:
    command = Command.from_json('{"action":"navigate","request_id":"req-7","target":{"x":2,"y":3,"theta":0}}')

    assert command.action == "navigate"
    assert command.target == Pose(2, 3, 0)


def test_command_rejects_missing_identity() -> None:
    with pytest.raises(ValueError, match="action and request_id"):
        Command.from_json('{"action":"stop"}')
