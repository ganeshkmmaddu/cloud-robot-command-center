from cloud_robot_bridge.simulator import RobotSimulator


def test_simulator_moves_on_a_repeatable_path() -> None:
    simulator = RobotSimulator("test-bot")

    first = simulator.tick()
    second = simulator.tick()

    assert first.robot_id == "test-bot"
    assert first.status == "moving"
    assert first.pose != second.pose
    assert first.battery == 100
