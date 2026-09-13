"""Runtime configuration for the command center."""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class RuntimeConfig:
    db_path: str
    username: str
    password: str
    role: str
    require_auth: bool
    webhook_url: str | None


def load_runtime_config(db_path: str | None = None) -> RuntimeConfig:
    resolved_db_path = db_path or os.getenv("COMMAND_CENTER_DB_PATH", "cloud_robot_command_center.db")
    username = os.getenv("COMMAND_CENTER_USERNAME", "admin")
    password = os.getenv("COMMAND_CENTER_PASSWORD", "admin123")
    role = os.getenv("COMMAND_CENTER_ROLE", "admin")
    require_auth = os.getenv("COMMAND_CENTER_REQUIRE_AUTH", "false").lower() == "true"
    webhook_url = os.getenv("COMMAND_CENTER_WEBHOOK_URL") or None

    if not resolved_db_path.strip():
        raise ValueError("COMMAND_CENTER_DB_PATH cannot be empty")
    if require_auth and not username.strip():
        raise ValueError("COMMAND_CENTER_USERNAME cannot be empty when auth is required")
    if require_auth and not password.strip():
        raise ValueError("COMMAND_CENTER_PASSWORD cannot be empty when auth is required")
    if webhook_url and not urlparse(webhook_url).scheme:
        raise ValueError("COMMAND_CENTER_WEBHOOK_URL must be a full URL when set")

    return RuntimeConfig(
        db_path=resolved_db_path,
        username=username,
        password=password,
        role=role,
        require_auth=require_auth,
        webhook_url=webhook_url,
    )
