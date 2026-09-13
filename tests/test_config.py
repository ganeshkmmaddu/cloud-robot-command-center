from __future__ import annotations

import pytest

from cloud_robot_bridge.config import RuntimeConfig, load_runtime_config


def test_load_runtime_config_uses_defaults(monkeypatch):
    monkeypatch.delenv("COMMAND_CENTER_DB_PATH", raising=False)
    monkeypatch.setenv("COMMAND_CENTER_USERNAME", "ops")
    monkeypatch.setenv("COMMAND_CENTER_PASSWORD", "s3cr3t")
    monkeypatch.setenv("COMMAND_CENTER_ROLE", "ops")
    monkeypatch.setenv("COMMAND_CENTER_REQUIRE_AUTH", "true")

    config = load_runtime_config()

    assert isinstance(config, RuntimeConfig)
    assert config.db_path == "cloud_robot_command_center.db"
    assert config.username == "ops"
    assert config.password == "s3cr3t"
    assert config.role == "ops"
    assert config.require_auth is True


def test_load_runtime_config_rejects_invalid_webhook(monkeypatch):
    monkeypatch.setenv("COMMAND_CENTER_WEBHOOK_URL", "not-a-url")
    with pytest.raises(ValueError, match="COMMAND_CENTER_WEBHOOK_URL"):
        load_runtime_config()
