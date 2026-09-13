"""FastAPI dashboard and command endpoints for the local robot control center."""

from __future__ import annotations

import argparse
import uuid
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

from .bridge import RobotBridge
from .protocol import Command, Pose, Telemetry
from .transport import MemoryTransport


class PoseTarget(BaseModel):
    x: float
    y: float
    theta: float


class CommandRequest(BaseModel):
    action: str
    request_id: str | None = None
    target: PoseTarget | None = None


class TelemetryRecord(BaseModel):
    robot_id: str
    status: str = "idle"
    battery: int = 0
    pose: PoseTarget
    timestamp: str | None = None


class CommandCenterStore:
    def __init__(self) -> None:
        self.telemetry_history: list[Telemetry] = []
        self.command_history: list[Command] = []

    def handle_telemetry(self, telemetry: Telemetry) -> None:
        self.telemetry_history.append(telemetry)

    def handle_command(self, command: Command) -> None:
        self.command_history.append(command)

    def latest_telemetry(self) -> Telemetry | None:
        if not self.telemetry_history:
            return None
        return self.telemetry_history[-1]

    def snapshot(self) -> dict[str, Any]:
        latest = self.latest_telemetry()
        return {
            "robot_id": latest.robot_id if latest else None,
            "status": latest.status if latest else "idle",
            "battery": latest.battery if latest else 0,
            "pose": latest.pose.as_dict() if latest else {"x": 0.0, "y": 0.0, "theta": 0.0},
            "telemetry_count": len(self.telemetry_history),
            "command_count": len(self.command_history),
            "latest_command": self.command_history[-1].as_dict() if self.command_history else None,
            "history": [entry.as_dict() for entry in self.telemetry_history[-10:]],
        }


class StoreTelemetrySink:
    def __init__(self, store: CommandCenterStore) -> None:
        self.store = store

    def publish(self, telemetry: Telemetry) -> None:
        self.store.handle_telemetry(telemetry)


def create_app() -> FastAPI:
    store = CommandCenterStore()
    transport = MemoryTransport()
    bridge = RobotBridge(StoreTelemetrySink(store), transport)
    bridge.on_command(store.handle_command)

    app = FastAPI(title="Cloud Robot Command Center", version="0.2.0")

    @app.get("/")
    async def root() -> str:
        return """
        <!doctype html>
        <html lang="en">
        <head>
            <meta charset="utf-8" />
            <meta name="viewport" content="width=device-width, initial-scale=1" />
            <title>Cloud Robot Command Center</title>
            <style>
                :root { color-scheme: dark; }
                * { box-sizing: border-box; }
                body {
                    margin: 0; font-family: Arial, sans-serif; background: #0f172a; color: #e2e8f0;
                    padding: 24px;
                }
                .card {
                    max-width: 900px; margin: 0 auto; background: #111827; border: 1px solid #334155;
                    border-radius: 12px; padding: 24px; box-shadow: 0 20px 40px rgba(15, 23, 42, 0.35);
                }
                h1 { margin-top: 0; }
                .status {
                    display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
                    gap: 12px; margin: 20px 0; 
                }
                .tile {
                    background: #1f2937; border-radius: 10px; padding: 16px; border: 1px solid #374151;
                }
                .controls { display: flex; gap: 12px; flex-wrap: wrap; margin: 20px 0; }
                button {
                    background: #22c55e; border: 0; color: #062b12; font-weight: 700; padding: 10px 16px;
                    border-radius: 8px; cursor: pointer;
                }
                button.secondary { background: #fbbf24; color: #4a3000; }
                pre {
                    background: rgba(15, 23, 42, 0.8); border-radius: 8px; padding: 16px; overflow-x: auto;
                    border: 1px solid #334155;
                }
            </style>
        </head>
        <body>
            <div class="card">
                <h1>Cloud Robot Command Center</h1>
                <div class="status" id="status"></div>
                <div class="controls">
                    <button id="move-btn">Send move</button>
                    <button id="stop-btn" class="secondary">Send stop</button>
                </div>
                <h2>Recent telemetry</h2>
                <pre id="telemetry"></pre>
            </div>
            <script>
                async function loadState() {
                    const response = await fetch('/api/state');
                    const state = await response.json();
                    const status = document.getElementById('status');
                    status.innerHTML = `
                        <div class="tile"><strong>Robot</strong><br>${state.robot_id || 'unknown'}</div>
                        <div class="tile"><strong>Status</strong><br>${state.status}</div>
                        <div class="tile"><strong>Battery</strong><br>${state.battery}%</div>
                        <div class="tile"><strong>Position</strong><br>x=${state.pose.x.toFixed(2)}, y=${state.pose.y.toFixed(2)}</div>
                        <div class="tile"><strong>Telemetry</strong><br>${state.telemetry_count}</div>
                        <div class="tile"><strong>Commands</strong><br>${state.command_count}</div>
                    `;
                    document.getElementById('telemetry').textContent = JSON.stringify(state.history.slice(-5), null, 2);
                }

                async function sendCommand(action, target) {
                    const payload = { action, request_id: crypto.randomUUID(), target };
                    const response = await fetch('/api/commands', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload)
                    });
                    if (!response.ok) {
                        alert('Command failed');
                        return;
                    }
                    await loadState();
                }

                document.getElementById('move-btn').addEventListener('click', () => sendCommand('navigate', { x: 1.5, y: 2.5, theta: 0.4 }));
                document.getElementById('stop-btn').addEventListener('click', () => sendCommand('stop', null));
                setInterval(loadState, 2000);
                loadState();
            </script>
        </body>
        </html>
        """

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "service": "cloud-robot-command-center"}

    @app.get("/api/state")
    async def state() -> dict[str, Any]:
        return store.snapshot()

    @app.get("/api/telemetry")
    async def telemetry() -> list[dict[str, Any]]:
        return [entry.as_dict() for entry in store.telemetry_history[-20:]]

    @app.get("/api/commands")
    async def commands() -> list[dict[str, Any]]:
        return [entry.as_dict() for entry in store.command_history[-20:]]

    @app.post("/api/commands")
    async def submit_command(payload: CommandRequest) -> dict[str, Any]:
        command = Command(
            action=payload.action,
            request_id=payload.request_id or f"cmd-{uuid.uuid4().hex[:8]}",
            target=Pose(**payload.target.model_dump()) if payload.target else None,
        )
        transport.inject_command(command)
        return {"status": "accepted", "command": command.as_dict()}

    @app.post("/api/telemetry")
    async def submit_telemetry(payload: TelemetryRecord) -> dict[str, Any]:
        telemetry = Telemetry(
            robot_id=payload.robot_id,
            pose=Pose(payload.pose.x, payload.pose.y, payload.pose.theta),
            battery=payload.battery,
            status=payload.status,
            timestamp=payload.timestamp or "",
        )
        bridge.publish_telemetry(telemetry)
        return {"status": "accepted", "telemetry": telemetry.as_dict()}

    return app


app = create_app()


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the cloud robot command center dashboard")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
