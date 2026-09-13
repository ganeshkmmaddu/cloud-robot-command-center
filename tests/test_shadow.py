from cloud_robot_bridge.protocol import Pose
from cloud_robot_bridge.shadow import DeviceShadow


def test_device_shadow_tracks_reported_and_desired_state() -> None:
    shadow = DeviceShadow()
    shadow.update_reported("bot-shadow", "moving", 76, Pose(1.0, 2.0, 0.4))
    shadow.set_desired_task("navigate", Pose(5.0, 6.0, 0.9))

    snapshot = shadow.snapshot()
    assert snapshot["state"]["reported"]["status"] == "moving"
    assert snapshot["state"]["reported"]["battery"] == 76
    assert snapshot["state"]["desired"]["task"]["action"] == "navigate"
    assert snapshot["state"]["desired"]["task"]["target"]["x"] == 5.0
