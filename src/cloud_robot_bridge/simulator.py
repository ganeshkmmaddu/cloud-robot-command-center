"""Deterministic robot simulator for local development and demos."""

from __future__ import annotations

import argparse
import math
import time

from .protocol import Pose, Telemetry


class RobotSimulator:
    def __init__(self, robot_id: str = "simulator-01") -> None:
        self.robot_id = robot_id
        self.step = 0

    def tick(self) -> Telemetry:
        self.step += 1
        angle = self.step * 0.1
        return Telemetry(
            robot_id=self.robot_id,
            pose=Pose(3.0 * math.cos(angle), 3.0 * math.sin(angle), angle),
            battery=max(0, 100 - self.step // 20),
            status="moving",
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Emit simulated robot telemetry")
    parser.add_argument("--robot-id", default="simulator-01")
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--interval", type=float, default=0.5)
    args = parser.parse_args()
    simulator = RobotSimulator(args.robot_id)
    for _ in range(args.count):
        print(simulator.tick().to_json(), flush=True)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
