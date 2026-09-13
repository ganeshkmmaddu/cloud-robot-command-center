# Architecture

```mermaid
flowchart LR
  ROS[ROS 2 /pose] --> Adapter[ROS adapter]
  Sim[Local simulator] --> Contract[Typed protocol]
  Adapter --> Contract
  Contract --> Bridge[RobotBridge]
  Bridge --> Memory[Memory transport]
  Bridge --> MQTT[AWS IoT MQTT adapter]
  MQTT --> Cloud[AWS IoT Core]
  Cloud --> Dashboard[Future operator dashboard]
```

## Boundaries

`protocol.py` owns the wire format. `bridge.py` owns orchestration. `transport.py` defines the small interfaces that real MQTT and test transports implement. `simulator.py` is deliberately deterministic so demos and regression tests do not require physical hardware.

## Reliability rules

- Keep credentials in environment variables or mounted certificate files.
- Keep transport failures at the adapter boundary.
- Validate command identity with `action` and `request_id` before dispatch.
- Preserve timestamps in UTC ISO-8601 format.
- Add retries and offline shadow reconciliation in the AWS adapter rather than in the protocol model.
