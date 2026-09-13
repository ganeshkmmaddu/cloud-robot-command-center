from cloud_robot_bridge.mqtt import AWSIoTMQTTTransport, FakeMQTTClient, MQTTConfig
from cloud_robot_bridge.protocol import Command, Pose, Telemetry


def test_mqtt_config_builds_expected_topics() -> None:
    config = MQTTConfig(robot_id="bot-42")

    assert config.telemetry_topic_name == "robot/bot-42/pub/monitoring/telemetry"
    assert config.command_topic_name == "robot/bot-42/sub/command/#"


def test_aws_iot_transport_publishes_and_receives_commands() -> None:
    client = FakeMQTTClient()
    transport = AWSIoTMQTTTransport(config=MQTTConfig(robot_id="bot-7"), client=client)
    handled: list[Command] = []

    transport.subscribe(handled.append)
    transport.publish(Telemetry("bot-7", Pose(1, 2, 0.3), 99, status="moving"))
    transport.inject_command(Command("stop", "req-9"))

    assert client.published[0][0] == "robot/bot-7/pub/monitoring/telemetry"
    assert client.subscriptions == ["robot/bot-7/sub/command/#"]
    assert handled[-1].action == "stop"
    assert handled[-1].request_id == "req-9"

    client.inject_message("robot/bot-7/sub/command/#", '{"action":"navigate","request_id":"req-10","target":{"x":2,"y":3,"theta":0}}')
    assert handled[-1].action == "navigate"
    assert handled[-1].target == Pose(2, 3, 0)
