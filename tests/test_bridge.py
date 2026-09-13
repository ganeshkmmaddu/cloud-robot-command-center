from cloud_robot_bridge.bridge import RobotBridge
from cloud_robot_bridge.protocol import Command, Pose, Telemetry
from cloud_robot_bridge.transport import MemoryTransport


def test_bridge_forwards_telemetry_and_commands() -> None:
    transport = MemoryTransport()
    bridge = RobotBridge(transport, transport)
    handled: list[Command] = []
    bridge.on_command(handled.append)

    telemetry = Telemetry("r-1", Pose(0, 1, 0), 99)
    command = Command("stop", "req-1")
    bridge.publish_telemetry(telemetry)
    transport.inject_command(command)

    assert transport.telemetry == [telemetry]
    assert bridge.received_commands == [command]
    assert handled == [command]
