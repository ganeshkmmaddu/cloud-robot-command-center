"""Orchestrates robot telemetry and cloud commands without binding to a vendor."""

from __future__ import annotations

from collections.abc import Callable

from .protocol import Command, Telemetry
from .transport import CommandSource, TelemetrySink


class RobotBridge:
    def __init__(self, telemetry_sink: TelemetrySink, command_source: CommandSource) -> None:
        self.telemetry_sink = telemetry_sink
        self.command_source = command_source
        self.received_commands: list[Command] = []
        self._command_handler: Callable[[Command], None] | None = None
        command_source.subscribe(self._receive_command)

    def publish_telemetry(self, telemetry: Telemetry) -> None:
        self.telemetry_sink.publish(telemetry)

    def on_command(self, handler: Callable[[Command], None]) -> None:
        self._command_handler = handler

    def _receive_command(self, command: Command) -> None:
        self.received_commands.append(command)
        if self._command_handler:
            self._command_handler(command)
