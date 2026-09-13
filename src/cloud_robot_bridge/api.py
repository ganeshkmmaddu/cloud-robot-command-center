"""FastAPI dashboard and command endpoints for the local robot control center."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import uuid
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from .bridge import RobotBridge
from .protocol import Command, Pose, Telemetry
from .tasks import RobotTask
from .transport import MemoryTransport


class PoseTarget(BaseModel):
    x: float
    y: float
    theta: float


class CommandRequest(BaseModel):
    action: str
    request_id: str | None = None
    target: PoseTarget | None = None


class TaskRequest(BaseModel):
    robot_id: str
    action: str
    target: PoseTarget | None = None


class TelemetryRecord(BaseModel):
    robot_id: str
    status: str = "idle"
    battery: int = 0
    pose: PoseTarget
    timestamp: str | None = None


class CommandCenterStore:
    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path or os.getenv("COMMAND_CENTER_DB_PATH", "cloud_robot_command_center.db")
        self.telemetry_history: list[Telemetry] = []
        self.command_history: list[Command] = []
        self.tasks: list[RobotTask] = []
        self._init_db()
        self._load_from_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS telemetry (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    payload TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS commands (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    payload TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    payload TEXT NOT NULL
                )
                """
            )

    def _load_from_db(self) -> None:
        with self._connect() as connection:
            telemetry_rows = connection.execute(
                "SELECT payload FROM telemetry ORDER BY id ASC"
            ).fetchall()
            command_rows = connection.execute(
                "SELECT payload FROM commands ORDER BY id ASC"
            ).fetchall()
            task_rows = connection.execute(
                    "SELECT payload FROM tasks ORDER BY id ASC"
                ).fetchall()

            self.telemetry_history = [self._deserialize_telemetry(row["payload"]) for row in telemetry_rows]
            self.command_history = [self._deserialize_command(row["payload"]) for row in command_rows]
            self.tasks = [self._deserialize_task(row["payload"]) for row in task_rows]

    @staticmethod
    def _deserialize_telemetry(payload: str) -> Telemetry:
        data = json.loads(payload)
        pose = data.get("pose") or {"x": 0.0, "y": 0.0, "theta": 0.0}
        return Telemetry(
            robot_id=data["robot_id"],
            pose=Pose(**pose),
            battery=data.get("battery", 0),
            status=data.get("status", "idle"),
            timestamp=data.get("timestamp", ""),
        )

    @staticmethod
    def _deserialize_command(payload: str) -> Command:
        data = json.loads(payload)
        target = data.get("target")
        return Command(
            action=data["action"],
            request_id=data["request_id"],
            target=Pose(**target) if target else None,
        )

    @staticmethod
    def _deserialize_task(payload: str) -> RobotTask:
        data = json.loads(payload)
        target = data.get("target")
        return RobotTask(
            id=data["id"],
            robot_id=data["robot_id"],
            action=data["action"],
            target=Pose(**target) if target else None,
            status=data.get("status", "queued"),
            created_at=data.get("created_at", ""),
        )

    def handle_telemetry(self, telemetry: Telemetry) -> None:
        self.telemetry_history.append(telemetry)
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO telemetry (payload) VALUES (?)",
                (json.dumps(telemetry.as_dict()),),
            )

    def handle_command(self, command: Command) -> None:
        self.command_history.append(command)
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO commands (payload) VALUES (?)",
                (json.dumps(command.as_dict()),),
            )

    def add_task(self, robot_id: str, action: str, target: Pose | None = None) -> RobotTask:
        task = RobotTask(
            id=f"task-{len(self.tasks) + 1:04d}",
            robot_id=robot_id,
            action=action,
            target=target,
        )
        self.tasks.append(task)
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO tasks (payload) VALUES (?)",
                (json.dumps(task.as_dict()),),
            )
        return task

    def update_task_status(self, task_id: str, status: str) -> RobotTask:
        task = next(item for item in self.tasks if item.id == task_id)
        task.status = status
        with self._connect() as connection:
            rows = connection.execute("SELECT id, payload FROM tasks").fetchall()
            for row in rows:
                data = json.loads(row["payload"])
                if data.get("id") == task_id:
                    data["status"] = status
                    connection.execute(
                        "UPDATE tasks SET payload = ? WHERE id = ?",
                        (json.dumps(data), row["id"]),
                    )
                    break
        return task

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
            "task_count": len(self.tasks),
            "latest_command": self.command_history[-1].as_dict() if self.command_history else None,
            "history": [entry.as_dict() for entry in self.telemetry_history[-10:]],
            "tasks": [task.as_dict() for task in self.tasks[-10:]],
        }


class StoreTelemetrySink:
    def __init__(self, store: CommandCenterStore) -> None:
        self.store = store

    def publish(self, telemetry: Telemetry) -> None:
        self.store.handle_telemetry(telemetry)


def create_app(db_path: str | None = None) -> FastAPI:
    store = CommandCenterStore(db_path=db_path)
    transport = MemoryTransport()
    bridge = RobotBridge(StoreTelemetrySink(store), transport)
    bridge.on_command(store.handle_command)
    websocket_clients: list[WebSocket] = []

    async def broadcast_state() -> None:
        snapshot = store.snapshot()
        for client in list(websocket_clients):
            try:
                await client.send_json(snapshot)
            except RuntimeError:
                websocket_clients.remove(client)

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
                    margin: 0; font-family: Arial, sans-serif; background: linear-gradient(180deg, #020817 0%, #0f172a 100%);
                    color: #e2e8f0; padding: 24px;
                }
                .shell {
                    max-width: 1200px; margin: 0 auto; background: rgba(15, 23, 42, 0.82);
                    border: 1px solid rgba(148, 163, 184, 0.25); border-radius: 20px; padding: 24px;
                    box-shadow: 0 30px 60px rgba(2, 6, 23, 0.55);
                }
                h1 { margin: 0 0 12px; font-size: 2rem; }
                .row { display: grid; grid-template-columns: 1.4fr 0.8fr; gap: 18px; }
                .panel {
                    background: rgba(15, 23, 42, 0.96); border: 1px solid rgba(148, 163, 184, 0.2);
                    border-radius: 16px; padding: 18px;
                }
                .status-grid {
                    display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
                    gap: 12px; margin: 18px 0;
                }
                .tile {
                    background: rgba(30, 41, 59, 0.9); border-radius: 12px; padding: 16px; border: 1px solid rgba(148, 163, 184, 0.15);
                }
                .tile strong { display: block; margin-bottom: 6px; color: #93c5fd; }
                canvas {
                    width: 100%; height: 420px; border-radius: 12px; background: linear-gradient(180deg, rgba(15, 23, 42, 0.9), rgba(3, 7, 18, 0.9));
                    border: 1px solid rgba(148, 163, 184, 0.2);
                }
                .controls { display: flex; gap: 12px; flex-wrap: wrap; margin-top: 16px; }
                button {
                    background: linear-gradient(180deg, #22c55e, #16a34a); border: none; color: #062b12;
                    font-weight: 700; border-radius: 10px; padding: 10px 16px; cursor: pointer;
                }
                button.secondary { background: linear-gradient(180deg, #fbbf24, #f59e0b); color: #3b2b00; }
                .log {
                    list-style: none; padding: 0; margin: 0; display: grid; gap: 10px;
                    max-height: 220px; overflow: auto; font-size: 0.95rem;
                }
                .log li {
                    background: rgba(30, 41, 59, 0.75); border: 1px solid rgba(148, 163, 184, 0.15);
                    border-radius: 10px; padding: 10px 12px;
                }
                pre {
                    margin: 14px 0 0; background: rgba(2, 6, 23, 0.9); border-radius: 10px; padding: 14px;
                    border: 1px solid rgba(148, 163, 184, 0.2); overflow-x: auto; font-size: 0.85rem;
                }
            </style>
        </head>
        <body>
            <div class="shell">
                <h1>Cloud Robot Command Center</h1>
                <div class="status-grid" id="status"></div>
                <div class="row">
                    <div class="panel">
                        <canvas id="map" width="720" height="420"></canvas>
                        <div class="controls">
                            <button id="move-btn">Send move</button>
                            <button id="patrol-btn" class="secondary">Patrol</button>
                            <button id="stop-btn" class="secondary">Stop</button>
                        </div>
                    </div>
                    <div class="panel">
                        <h3>Recent commands</h3>
                        <ul class="log" id="commands"></ul>
                        <h3 style="margin-top: 18px;">Recent telemetry</h3>
                        <pre id="telemetry"></pre>
                    </div>
                </div>
            </div>
            <script>
                const canvas = document.getElementById('map');
                const ctx = canvas.getContext('2d');

                function drawMap(state) {
                    const width = canvas.width;
                    const height = canvas.height;
                    ctx.clearRect(0, 0, width, height);
                    ctx.fillStyle = '#020817';
                    ctx.fillRect(0, 0, width, height);

                    ctx.strokeStyle = 'rgba(148,163,184,0.18)';
                    ctx.lineWidth = 1;
                    for (let x = 30; x < width; x += 40) {
                        ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, height); ctx.stroke();
                    }
                    for (let y = 30; y < height; y += 40) {
                        ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(width, y); ctx.stroke();
                    }

                    const pose = state.pose || { x: 0, y: 0, theta: 0 };
                    const px = 60 + (pose.x + 5) * 30;
                    const py = height - 60 - (pose.y + 5) * 30;

                    ctx.beginPath();
                    ctx.arc(px, py, 16, 0, Math.PI * 2);
                    ctx.fillStyle = '#22c55e';
                    ctx.fill();

                    ctx.beginPath();
                    ctx.moveTo(px, py);
                    const headingX = px + Math.cos(pose.theta) * 22;
                    const headingY = py + Math.sin(pose.theta) * 22;
                    ctx.lineTo(headingX, headingY);
                    ctx.strokeStyle = '#f8fafc';
                    ctx.lineWidth = 4;
                    ctx.stroke();

                    ctx.fillStyle = '#f8fafc';
                    ctx.font = '14px sans-serif';
                    ctx.fillText(`robot: ${state.robot_id || 'unknown'}`, 20, 28);
                }

                const socket = new WebSocket(`ws://${location.host}/ws`);

                socket.addEventListener('message', (event) => {
                    const state = JSON.parse(event.data);
                    renderState(state);
                });

                function renderState(state) {
                    const status = document.getElementById('status');
                    status.innerHTML = `
                        <div class="tile"><strong>Robot</strong>${state.robot_id || 'unknown'}</div>
                        <div class="tile"><strong>Status</strong>${state.status}</div>
                        <div class="tile"><strong>Battery</strong>${state.battery}%</div>
                        <div class="tile"><strong>Pose</strong>x=${Number(state.pose.x).toFixed(2)} y=${Number(state.pose.y).toFixed(2)}</div>
                        <div class="tile"><strong>Telemetry</strong>${state.telemetry_count}</div>
                        <div class="tile"><strong>Commands</strong>${state.command_count}</div>
                    `;
                    document.getElementById('telemetry').textContent = JSON.stringify(state.history.slice(-5), null, 2);

                    const commands = document.getElementById('commands');
                    commands.innerHTML = '';
                    const latest = state.latest_command ? [state.latest_command] : [];
                    latest.forEach(command => {
                        const item = document.createElement('li');
                        item.textContent = `${command.action} • ${command.request_id}`;
                        commands.appendChild(item);
                    });

                        if (state.tasks && state.tasks.length) {
                            const taskList = document.createElement('ul');
                            taskList.className = 'log';
                            state.tasks.slice(-3).forEach(task => {
                                const taskItem = document.createElement('li');
                                taskItem.textContent = `${task.action} • ${task.robot_id} • ${task.status}`;
                                taskList.appendChild(taskItem);
                            });
                            commands.appendChild(taskList);
                        }

                        drawMap(state);
                    }

                    async function loadState() {
                    const response = await fetch('/api/state');
                    const state = await response.json();
                    renderState(state);
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

                document.getElementById('move-btn').addEventListener('click', () => sendCommand('navigate', { x: 2.0, y: 2.5, theta: 0.7 }));
                document.getElementById('patrol-btn').addEventListener('click', () => sendCommand('patrol', { x: -1.2, y: 1.5, theta: 1.0 }));
                document.getElementById('stop-btn').addEventListener('click', () => sendCommand('stop', null));
                setInterval(loadState, 2000);
                loadState();
            </script>
        </body>
        </html>
        """

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await websocket.accept()
        websocket_clients.append(websocket)
        try:
            await websocket.send_json(store.snapshot())
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            websocket_clients.remove(websocket)

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

    @app.get("/api/tasks")
    async def tasks() -> list[dict[str, Any]]:
        return [task.as_dict() for task in store.tasks[-20:]]

    @app.post("/api/tasks")
    async def create_task(payload: TaskRequest) -> dict[str, Any]:
        task = store.add_task(
            robot_id=payload.robot_id,
            action=payload.action,
            target=Pose(payload.target.x, payload.target.y, payload.target.theta) if payload.target else None,
        )
        await broadcast_state()
        return {"status": "accepted", "task": task.as_dict()}

    @app.patch("/api/tasks/{task_id}")
    async def update_task(task_id: str, status: str) -> dict[str, Any]:
        task = store.update_task_status(task_id, status)
        await broadcast_state()
        return {"status": "updated", "task": task.as_dict()}

    @app.post("/api/commands")
    async def submit_command(payload: CommandRequest) -> dict[str, Any]:
        command = Command(
            action=payload.action,
            request_id=payload.request_id or f"cmd-{uuid.uuid4().hex[:8]}",
            target=Pose(**payload.target.model_dump()) if payload.target else None,
        )
        transport.inject_command(command)
        await broadcast_state()
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
        await broadcast_state()
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
