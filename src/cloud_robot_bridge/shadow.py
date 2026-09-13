"""Device shadow model for offline robot state and queued commands."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .protocol import Pose


@dataclass
class DeviceShadow:
    reported: dict[str, Any] = field(default_factory=dict)
    desired: dict[str, Any] = field(default_factory=dict)

    def update_reported(self, robot_id: str, status: str, battery: int, pose: Pose | None) -> None:
        self.reported = {
            "robot_id": robot_id,
            "status": status,
            "battery": battery,
            "position": pose.as_dict() if pose else {"x": 0.0, "y": 0.0, "theta": 0.0},
        }

    def set_desired_task(self, action: str, target: Pose | None = None) -> None:
        self.desired = {
            "task": {
                "action": action,
                "target": target.as_dict() if target else None,
            }
        }

    def snapshot(self) -> dict[str, Any]:
        return {
            "state": {
                "reported": self.reported,
                "desired": self.desired,
            }
        }
