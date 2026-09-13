# Cloud Robot Command Center

A local-first robot control bridge inspired by the architecture of [ros2-cloud-robot-control](https://github.com/Alisherka7/ros2-cloud-robot-control). It keeps the robot message contract and orchestration testable without ROS 2 or AWS, then provides adapters for both environments.

## What is included

- Typed telemetry and command protocol with deterministic JSON output
- Deterministic circular-path simulator for demos and development
- Transport-neutral bridge with in-memory and AWS IoT MQTT implementations
- Interactive HTTP dashboard with a live map, telemetry history, command controls, robot status cards, SQLite-backed persistence, and device-shadow state tracking
- ROS 2 Humble Python package that maps `/pose` to bridge telemetry
- Docker and Compose entry points for the simulator and dashboard
- GitHub Actions checks for tests and linting
- AWS IoT certificate environment template, with secrets excluded from Git

## Quick start

Requires Python 3.10 or newer.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -e ".[dev]"
py -m pytest -q
py -m ruff check .
```

Run a local robot stream:

```powershell
robot-simulator --robot-id demo-bot --count 20 --interval 0.25
```

Start the dashboard:

```powershell
robot-command-center --host 0.0.0.0 --port 8000
```

Then open http://localhost:8000 in a browser.

Run with Docker:

```powershell
docker compose up --build
```

## ROS 2 adapter

On a ROS 2 Humble host, build the package from the repository root:

```bash
colcon build --base-paths ros --packages-select mqtt_bridge
source install/setup.bash
ros2 run mqtt_bridge bridge_node
```

The adapter subscribes to `geometry_msgs/PoseStamped` on `/pose` and publishes JSON strings on `/bridge/telemetry`. Commands can be integrated through `/bridge/commands` as the cloud transport is enabled.

## AWS IoT integration

Copy `.env.example` to `.env`, set `IOT_ENDPOINT`, and mount certificates under `config/certificates/`. Certificates are intentionally ignored. The message topics are designed for AWS IoT Core conventions:

- `robot/{robot_id}/pub/monitoring/telemetry`
- `robot/{robot_id}/sub/command/#`

The transport boundary means the cloud adapter can be added without changing simulator, protocol, or bridge tests.

A ready-to-use MQTT transport is available in the Python package via `cloud_robot_bridge.mqtt`. It publishes telemetry on `robot/{robot_id}/pub/monitoring/telemetry` and listens on `robot/{robot_id}/sub/command/#` when the AWS IoT endpoint and certificate paths are configured.

The command center also exposes a lightweight device-shadow model via `cloud_robot_bridge.shadow` and `/api/shadow/{robot_id}` so reported telemetry and desired tasks stay available while robots are offline.

## Design notes

See [docs/architecture.md](docs/architecture.md) for the data flow and extension points. This repository is an original implementation based on the reference system's publicly described concepts, not a copy of its source.
