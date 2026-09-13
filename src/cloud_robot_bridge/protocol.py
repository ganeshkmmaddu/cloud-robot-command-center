"""Wire messages shared by the simulator, ROS adapter, and cloud transport."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class Pose:
    x: float
    y: float
    theta: float

    def as_dict(self) -> dict[str, float]:
        return {"x": round(self.x, 4), "y": round(self.y, 4), "theta": round(self.theta, 4)}


@dataclass(frozen=True)
class Telemetry:
    robot_id: str
    pose: Pose
    battery: int
    status: str = "idle"
    timestamp: str = ""

    def as_dict(self) -> dict[str, Any]:
        timestamp = self.timestamp or datetime.now(timezone.utc).isoformat()
        return {
            "robot_id": self.robot_id,
            "timestamp": timestamp,
            "status": self.status,
            "battery": self.battery,
            "pose": self.pose.as_dict(),
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), separators=(",", ":"), sort_keys=True)


@dataclass(frozen=True)
class Command:
    action: str
    request_id: str
    target: Pose | None = None

    @classmethod
    def from_json(cls, payload: str) -> Command:
        data = json.loads(payload)
        if not isinstance(data, dict) or not data.get("action") or not data.get("request_id"):
            raise ValueError("command requires action and request_id")
        target_data = data.get("target")
        target = Pose(**target_data) if target_data else None
        return cls(action=str(data["action"]), request_id=str(data["request_id"]), target=target)
