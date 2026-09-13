"""FastAPI dashboard and command endpoints for the local robot control center."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .auth import AuthService
from .bridge import RobotBridge
from .protocol import Command, Pose, Telemetry
from .shadow import DeviceShadow
from .tasks import RobotTask
from .transport import MemoryTransport


class Alert:
    def __init__(self, robot_id: str, severity: str, message: str) -> None:
        self.robot_id = robot_id
        self.severity = severity
        self.message = message

    def as_dict(self) -> dict[str, str]:
        return {
            "robot_id": self.robot_id,
            "severity": self.severity,
            "message": self.message,
        }


class EventRecord:
    def __init__(
        self,
        category: str,
        message: str,
        severity: str = "info",
        robot_id: str | None = None,
        timestamp: str | None = None,
    ) -> None:
        self.category = category
        self.message = message
        self.severity = severity
        self.robot_id = robot_id
        self.timestamp = timestamp or datetime.now(timezone.utc).isoformat()

    def as_dict(self) -> dict[str, str | None]:
        return {
            "category": self.category,
            "severity": self.severity,
            "robot_id": self.robot_id,
            "message": self.message,
            "timestamp": self.timestamp,
        }


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


class RobotRecord:
    def __init__(self, robot_id: str, status: str = "idle", battery: int = 0, pose: Pose | None = None) -> None:
        self.robot_id = robot_id
        self.status = status
        self.battery = battery
        self.pose = pose or Pose(0.0, 0.0, 0.0)

    def as_dict(self) -> dict[str, Any]:
        return {
            "robot_id": self.robot_id,
            "status": self.status,
            "battery": self.battery,
            "pose": self.pose.as_dict(),
        }


class CommandCenterStore:
    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path or os.getenv("COMMAND_CENTER_DB_PATH", "cloud_robot_command_center.db")
        self.telemetry_history: list[Telemetry] = []
        self.command_history: list[Command] = []
        self.tasks: list[RobotTask] = []
        self.robots: dict[str, RobotRecord] = {}
        self.shadows: dict[str, DeviceShadow] = {}
        self.alerts: list[Alert] = []
        self.events: list[EventRecord] = []
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
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
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
            event_rows = connection.execute(
                "SELECT payload FROM events ORDER BY id ASC"
            ).fetchall()

            self.telemetry_history = [self._deserialize_telemetry(row["payload"]) for row in telemetry_rows]
            self.command_history = [self._deserialize_command(row["payload"]) for row in command_rows]
            self.tasks = [self._deserialize_task(row["payload"]) for row in task_rows]
            self.events = [self._deserialize_event(row["payload"]) for row in event_rows]

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

    @staticmethod
    def _deserialize_event(payload: str) -> EventRecord:
        data = json.loads(payload)
        return EventRecord(
            category=data["category"],
            message=data["message"],
            severity=data.get("severity", "info"),
            robot_id=data.get("robot_id"),
            timestamp=data.get("timestamp"),
        )

    def register_robot(self, robot_id: str, status: str = "idle", battery: int = 0, pose: Pose | None = None) -> RobotRecord:
        robot = self.robots.get(robot_id)
        if robot is None:
            robot = RobotRecord(robot_id=robot_id, status=status, battery=battery, pose=pose)
            self.robots[robot_id] = robot
        else:
            robot.status = status
            robot.battery = battery
            if pose is not None:
                robot.pose = pose

        shadow = self.shadows.setdefault(robot_id, DeviceShadow())
        shadow.update_reported(robot_id, status, battery, pose)
        return robot

    def add_alert(self, robot_id: str, severity: str, message: str) -> Alert:
        alert = Alert(robot_id=robot_id, severity=severity, message=message)
        self.alerts.append(alert)
        return alert

    def log_event(self, category: str, message: str, severity: str = "info", robot_id: str | None = None) -> EventRecord:
        event = EventRecord(category=category, message=message, severity=severity, robot_id=robot_id)
        self.events.append(event)
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO events (payload) VALUES (?)",
                (json.dumps(event.as_dict()),),
            )
        return event

    def handle_telemetry(self, telemetry: Telemetry) -> None:
        self.telemetry_history.append(telemetry)
        self.register_robot(
            telemetry.robot_id,
            status=telemetry.status,
            battery=telemetry.battery,
            pose=telemetry.pose,
        )
        self.log_event(
            "telemetry",
            f"Robot {telemetry.robot_id} reported status={telemetry.status} battery={telemetry.battery}%",
            "info",
            telemetry.robot_id,
        )
        if telemetry.battery <= 15:
            self.add_alert(telemetry.robot_id, "critical", f"Battery critical at {telemetry.battery}%")
            self.log_event(
                "alert",
                f"Battery critical at {telemetry.battery}% for {telemetry.robot_id}",
                "critical",
                telemetry.robot_id,
            )
        elif telemetry.status == "error":
            self.add_alert(telemetry.robot_id, "warning", "Robot reported an error state")
            self.log_event(
                "alert",
                f"Robot {telemetry.robot_id} reported an error state",
                "warning",
                telemetry.robot_id,
            )
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
        shadow = self.shadows.setdefault(robot_id, DeviceShadow())
        shadow.set_desired_task(action, target)
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
        robot_list = [robot.as_dict() for robot in self.robots.values()]
        health = {
            "battery": latest.battery if latest else 0,
            "cpu_percent": max(10, min(100, (100 - (latest.battery if latest else 0)) + 15)) if latest else 0,
            "status": latest.status if latest else "idle",
            "errors": sum(1 for entry in self.telemetry_history if entry.status == "error"),
            "health_score": max(0, min(100, (latest.battery if latest else 0) + 15)) if latest else 0,
        }
        return {
            "robot_id": latest.robot_id if latest else None,
            "status": latest.status if latest else "idle",
            "battery": latest.battery if latest else 0,
            "pose": latest.pose.as_dict() if latest else {"x": 0.0, "y": 0.0, "theta": 0.0},
            "telemetry_count": len(self.telemetry_history),
            "command_count": len(self.command_history),
            "task_count": len(self.tasks),
            "event_count": len(self.events),
            "robot_count": len(robot_list),
            "robots": robot_list,
            "alerts": [alert.as_dict() for alert in self.alerts[-10:]],
            "events": [event.as_dict() for event in self.events[-10:]],
            "health": health,
            "shadows": {robot_id: shadow.snapshot() for robot_id, shadow in self.shadows.items()},
            "latest_command": self.command_history[-1].as_dict() if self.command_history else None,
            "latest_event": self.events[-1].as_dict() if self.events else None,
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
    auth = AuthService()
    websocket_clients: list[WebSocket] = []
    auth_required = os.getenv("COMMAND_CENTER_REQUIRE_AUTH", "false").lower() == "true"

    def extract_bearer_token(authorization: str | None) -> str | None:
        if not authorization:
            return None
        if authorization.lower().startswith("bearer "):
            return authorization.split(" ", 1)[1].strip()
        return None

    async def require_auth(authorization: str | None = Header(default=None, alias="Authorization")) -> None:
        if not auth_required:
            return
        token = extract_bearer_token(authorization)
        if not auth.validate_token(token):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")

    async def broadcast_state() -> None:
        snapshot = store.snapshot()
        for client in list(websocket_clients):
            try:
                await client.send_json(snapshot)
            except RuntimeError:
                websocket_clients.remove(client)

    app = FastAPI(title="Cloud Robot Command Center", version="0.2.0")

    @app.middleware("http")
    async def enforce_auth(request, call_next):
        public_paths = {"/", "/docs", "/openapi.json", "/redoc", "/api/login", "/api/health"}
        if request.url.path in public_paths or not auth_required:
            return await call_next(request)
        token = extract_bearer_token(request.headers.get("authorization"))
        if not auth.validate_token(token):
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"detail": "Authentication required"})
        return await call_next(request)

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
                .health-bar {
                    height: 8px; border-radius: 999px; overflow: hidden; background: rgba(148, 163, 184, 0.2);
                    margin-top: 8px;
                }
                .health-fill {
                    height: 100%; background: linear-gradient(90deg, #22c55e, #facc15, #ef4444);
                }
                .alert-list {
                    list-style: none; padding: 0; margin: 12px 0 0; display: grid; gap: 10px;
                }
                .alert-item {
                    border-radius: 10px; padding: 10px 12px; border: 1px solid rgba(148, 163, 184, 0.2);
                    background: rgba(30, 41, 59, 0.8);
                }
                .critical { border-color: rgba(239, 68, 68, 0.7); }
                .warning { border-color: rgba(250, 204, 21, 0.7); }
                .robot-list {
                    display: flex; flex-wrap: wrap; gap: 8px; margin: 16px 0 0;
                }
                .robot-chip {
                    padding: 8px 12px; border-radius: 999px; border: 1px solid rgba(148,163,184,0.2);
                    background: rgba(15, 23, 42, 0.9); color: #e2e8f0; font-size: 0.9rem;
                }
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
                <div class="robot-list" id="robot-list"></div>
                <div class="panel" style="margin-top: 18px;">
                    <h3>Robot health</h3>
                    <div id="health"></div>
                </div>
                <div class="panel" style="margin-top: 18px;">
                    <h3>Alerts</h3>
                    <ul class="alert-list" id="alerts"></ul>
                </div>
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
                        <h3 style="margin-top: 18px;">Recent events</h3>
                        <pre id="events"></pre>
                    </div>
                </div>
            </div>
            <script>
                const canvas = document.getElementById('map');
                const ctx = canvas.getContext('2d');

                function drawRobotList(state) {
                    const robotList = document.getElementById('robot-list');
                    robotList.innerHTML = '';
                    (state.robots || []).forEach(robot => {
                        const chip = document.createElement('div');
                        chip.className = 'robot-chip';
                        chip.textContent = `${robot.robot_id} • ${robot.status} • ${robot.battery}%`;
                        robotList.appendChild(chip);
                    });
                }

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

                    (state.robots || []).forEach(robot => {
                        const pose = robot.pose || { x: 0, y: 0, theta: 0 };
                        const px = 60 + (pose.x + 5) * 30;
                        const py = height - 60 - (pose.y + 5) * 30;
                        const color = robot.robot_id === (state.robot_id || '') ? '#22c55e' : '#60a5fa';

                        ctx.beginPath();
                        ctx.arc(px, py, 12, 0, Math.PI * 2);
                        ctx.fillStyle = color;
                        ctx.fill();

                        ctx.beginPath();
                        ctx.moveTo(px, py);
                        const headingX = px + Math.cos(pose.theta) * 18;
                        const headingY = py + Math.sin(pose.theta) * 18;
                        ctx.lineTo(headingX, headingY);
                        ctx.strokeStyle = '#f8fafc';
                        ctx.lineWidth = 3;
                        ctx.stroke();

                        ctx.fillStyle = '#f8fafc';
                        ctx.font = '11px sans-serif';
                        ctx.fillText(robot.robot_id, px + 14, py - 10);
                    });

                    const pose = state.pose || { x: 0, y: 0, theta: 0 };
                    const px = 60 + (pose.x + 5) * 30;
                    const py = height - 60 - (pose.y + 5) * 30;
                    ctx.fillStyle = '#f8fafc';
                    ctx.font = '14px sans-serif';
                    ctx.fillText(`active robot: ${state.robot_id || 'unknown'}`, 20, 28);
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

                    const health = document.getElementById('health');
                    const healthScore = state.health && state.health.health_score !== undefined ? state.health.health_score : 0;
                    health.innerHTML = `
                        <div><strong>Health score</strong> ${healthScore}%</div>
                        <div class="health-bar"><div class="health-fill" style="width:${healthScore}%"></div></div>
                        <div style="margin-top: 8px;">CPU: ${state.health ? state.health.cpu_percent : 0}% • Errors: ${state.health ? state.health.errors : 0}</div>
                    `;

                    const alertList = document.getElementById('alerts');
                    alertList.innerHTML = '';
                    (state.alerts || []).slice(-5).reverse().forEach(alert => {
                        const item = document.createElement('li');
                        item.className = `alert-item ${alert.severity}`;
                        item.textContent = `[${alert.severity.toUpperCase()}] ${alert.robot_id}: ${alert.message}`;
                        alertList.appendChild(item);
                    });
                    const eventLog = document.getElementById('events');
                    if (eventLog) {
                        eventLog.textContent = JSON.stringify((state.events || []).slice(-5), null, 2);
                    }
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

                    drawRobotList(state);
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

    @app.post("/api/login")
    async def login(payload: dict[str, str] | None = None) -> dict[str, Any]:
        data = payload or {}
        username = data.get("username")
        password = data.get("password")
        if username is None or password is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="username and password are required")
        if not auth.validate(username, password):
            return {"authenticated": False, "token": None, "username": None, "role": None}
        token = auth.issue_token(username)
        return {
            "authenticated": True,
            "token": token,
            "username": username,
            "role": auth.role_for_token(token),
        }

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

    @app.get("/api/events")
    async def events() -> list[dict[str, Any]]:
        return [event.as_dict() for event in store.events[-20:]]

    @app.get("/api/tasks")
    async def tasks() -> list[dict[str, Any]]:
        return [task.as_dict() for task in store.tasks[-20:]]

    @app.get("/api/shadow/{robot_id}")
    async def shadow(robot_id: str) -> dict[str, Any]:
        return store.shadows.get(robot_id, DeviceShadow()).snapshot()

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
