"""AWS IoT MQTT transport for publishing telemetry and receiving commands."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from .protocol import Command, Telemetry


class MQTTClient(Protocol):
    def publish(self, topic: str, payload: str, qos: int = 1) -> None: ...

    def subscribe(self, topic: str, callback: Callable[[str, str], None]) -> None: ...

    def connect(self) -> None: ...

    def disconnect(self) -> None: ...


@dataclass
class MQTTConfig:
    endpoint: str = ""
    client_id: str = "cloud-robot-command-center"
    robot_id: str = "simulator-01"
    region: str = "us-east-1"
    cert_path: str | None = None
    key_path: str | None = None
    ca_path: str | None = None
    topic_prefix: str = "robot"
    command_topic: str = "sub/command/#"
    telemetry_topic: str = "pub/monitoring/telemetry"
    use_websocket: bool = False

    @classmethod
    def from_env(cls, robot_id: str | None = None) -> MQTTConfig:
        return cls(
            endpoint=os.getenv("IOT_ENDPOINT", ""),
            client_id=os.getenv("MQTT_CLIENT_ID", "cloud-robot-command-center"),
            robot_id=robot_id or os.getenv("ROBOT_ID", "simulator-01"),
            region=os.getenv("AWS_REGION", "us-east-1"),
            cert_path=os.getenv("CERT_PATH"),
            key_path=os.getenv("KEY_PATH"),
            ca_path=os.getenv("CA_PATH"),
            use_websocket=os.getenv("MQTT_USE_WEBSOCKET", "0") == "1",
        )

    @property
    def telemetry_topic_name(self) -> str:
        return f"{self.topic_prefix}/{self.robot_id}/{self.telemetry_topic}"

    @property
    def command_topic_name(self) -> str:
        return f"{self.topic_prefix}/{self.robot_id}/{self.command_topic}"


class FakeMQTTClient:
    def __init__(self) -> None:
        self.published: list[tuple[str, str, int]] = []
        self.subscriptions: list[str] = []
        self._callbacks: dict[str, Callable[[str, str], None]] = {}

    def connect(self) -> None:
        return None

    def disconnect(self) -> None:
        return None

    def publish(self, topic: str, payload: str, qos: int = 1) -> None:
        self.published.append((topic, payload, qos))

    def subscribe(self, topic: str, callback: Callable[[str, str], None]) -> None:
        self.subscriptions.append(topic)
        self._callbacks[topic] = callback

    def inject_message(self, topic: str, payload: str) -> None:
        callback = self._callbacks.get(topic)
        if callback:
            callback(topic, payload)


class AWSIoTMQTTTransport:
    """Cloud transport bound to an AWS IoT MQTT client."""

    def __init__(
        self,
        config: MQTTConfig | None = None,
        client: MQTTClient | None = None,
    ) -> None:
        self.config = config or MQTTConfig.from_env()
        self._client = client or self._build_client()
        self._handlers: list[Callable[[Command], None]] = []

    def _build_client(self) -> MQTTClient:
        if not self.config.endpoint:
            raise RuntimeError("IOT_ENDPOINT must be set before creating the AWS IoT transport")
        try:
            from awsiotsdk import mqtt5_client
        except ImportError as exc:  # pragma: no cover - only triggered when optional deps are absent
            raise RuntimeError(
                "Install the MQTT extras to use the AWS IoT transport: pip install -e '.[mqtt]'"
            ) from exc

        client = mqtt5_client.Mqtt5Client(
            endpoint=self.config.endpoint,
            client_id=self.config.client_id,
            region=self.config.region,
            cert_file=self.config.cert_path,
            key_file=self.config.key_path,
            ca_file=self.config.ca_path,
        )
        return client

    def connect(self) -> None:
        self._client.connect()

    def disconnect(self) -> None:
        self._client.disconnect()

    def subscribe(self, handler: Callable[[Command], None]) -> None:
        self._handlers.append(handler)

        def _on_message(topic: str, payload: str) -> None:
            if not payload:
                return
            command = Command.from_json(payload)
            for registered in self._handlers:
                registered(command)

        self._client.subscribe(self.config.command_topic_name, _on_message)

    def publish(self, telemetry: Telemetry) -> None:
        self._client.publish(self.config.telemetry_topic_name, telemetry.to_json(), qos=1)

    def inject_command(self, command: Command) -> None:
        for handler in self._handlers:
            handler(command)
