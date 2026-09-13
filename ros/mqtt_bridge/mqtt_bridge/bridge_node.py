"""Small ROS 2 node that exposes the bridge contract for robot integrations."""

import json

import rclpy
from geometry_msgs.msg import PoseStamped
from rclpy.node import Node
from std_msgs.msg import String


class BridgeNode(Node):
    def __init__(self) -> None:
        super().__init__("cloud_robot_bridge")
        self.pose_subscription = self.create_subscription(
            PoseStamped, "/pose", self._on_pose, 10
        )
        self.command_publisher = self.create_publisher(String, "/bridge/commands", 10)
        self.telemetry_publisher = self.create_publisher(String, "/bridge/telemetry", 10)

    def _on_pose(self, message: PoseStamped) -> None:
        telemetry = {
            "frame_id": message.header.frame_id or "map",
            "pose": {
                "x": message.pose.position.x,
                "y": message.pose.position.y,
                "theta": message.pose.orientation.z,
            },
        }
        output = String()
        output.data = json.dumps(telemetry, separators=(",", ":"))
        self.telemetry_publisher.publish(output)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = BridgeNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
