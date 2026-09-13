"""Transport boundary for cloud publishing and command delivery."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from .protocol import Command, Telemetry


class TelemetrySink(Protocol):
    def publish(self, telemetry: Telemetry) -> None: ...


class CommandSource(Protocol):
    def subscribe(self, handler: Callable[[Command], None]) -> None: ...


class MemoryTransport:
    """In-memory transport used by demos and integration tests."""

    def __init__(self) -> None:
        self.telemetry: list[Telemetry] = []
        self.commands: list[Command] = []
        self._handler: Callable[[Command], None] | None = None

    def publish(self, telemetry: Telemetry) -> None:
        self.telemetry.append(telemetry)

    def subscribe(self, handler: Callable[[Command], None]) -> None:
        self._handler = handler

    def inject_command(self, command: Command) -> None:
        self.commands.append(command)
        if self._handler:
            self._handler(command)
