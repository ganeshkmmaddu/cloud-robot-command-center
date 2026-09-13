"""Task scheduling primitives for robot work items."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from .protocol import Pose


@dataclass
class RobotTask:
    id: str
    robot_id: str
    action: str
    target: Pose | None = None
    status: str = "queued"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "robot_id": self.robot_id,
            "action": self.action,
            "target": self.target.as_dict() if self.target else None,
            "status": self.status,
            "created_at": self.created_at,
        }


class TaskStore:
    def __init__(self) -> None:
        self._tasks: dict[str, RobotTask] = {}

    def create(self, robot_id: str, action: str, target: Pose | None = None) -> RobotTask:
        task = RobotTask(
            id=f"task-{len(self._tasks) + 1:04d}",
            robot_id=robot_id,
            action=action,
            target=target,
        )
        self._tasks[task.id] = task
        return task

    def list(self) -> list[RobotTask]:
        return list(self._tasks.values())

    def update_status(self, task_id: str, status: str) -> RobotTask:
        task = self._tasks[task_id]
        task.status = status
        return task
