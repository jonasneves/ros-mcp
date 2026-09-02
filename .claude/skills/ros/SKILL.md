---
name: ros
description: Use when writing ROS 2 code — nodes, topic/service/action choice, QoS profiles, TF2 frames, or a URDF. Follow the REP or get silent failures.
user-invocable: false
---

# ROS 2

**Principle:** ROS 2 conventions (REPs), when violated, produce silent failures — wrong coordinate frames, dropped messages, timing bugs that only appear under load. Every deviation is a future debugging session.

Ask: *does this follow the REP, or is it ad-hoc?*

## Coordinate conventions (REP-103)

Right-handed, SI units throughout. X forward, Y left, Z up. Units: meters, radians, seconds, kilograms — no degrees, millimeters, or custom units. Euler angles discouraged (24 valid conventions; systems default differently); use quaternions for all rotation in messages. Differs from Three.js (Y-up) and some robot hardware; document deviations in project CLAUDE.md and verify with a coordinate transform before assuming.

## Frame conventions (REP-105)

Mobile-robot hierarchy: `map → odom → base_link → [sensor frames]`.

| Frame | Published by | Meaning |
|-------|-------------|---------|
| `map` | Localization node | World-fixed; corrected by localization |
| `odom` | Odometry source | World-fixed; continuous, no jumps, drifts over time |
| `base_link` | Robot center | Attached to robot body |
| `base_footprint` | Optional | Projection of base_link onto ground plane |

Localization publishes `map → odom`, not `map → base_link` — so `odom → base_link` stays continuous (no jumps) and corrections go into `map → odom`.

## TF2

Tree must be a tree: each frame exactly one parent; no loops, disconnected subtrees, or gaps.

```bash
ros2 run tf2_tools view_frames                          # visualize tree
ros2 run tf2_ros tf2_echo <source_frame> <target_frame> # check a transform
```

**Static vs dynamic:** unchanging frames (sensor on robot) → `StaticTransformBroadcaster`; changing frames (robot in world) → `TransformBroadcaster`. Dynamic-for-static wastes bandwidth; static-for-dynamic publishes stale transforms.

**Transform direction:** `parent → child` = position of child frame's origin expressed in parent frame. `lookupTransform(target, source, time)` returns the transform moving a point from `source` to `target`. Most common source of sign errors — verify direction before assuming.

**Timestamp:** `node.get_clock().now()` for live data. `rclpy.time.Time()` (zero) only for latest-available transform when staleness is acceptable.

## Communication primitive selection

| Use | When |
|-----|------|
| **Topic** | Continuous streams — sensor readings, robot state, odometry. Many pubs, many subs. |
| **Service** | Quick request/response — state queries, IK, parameter lookups. Milliseconds. Never long-running. |
| **Action** | Long-running ops needing feedback/cancellation — navigation goals, arm motion, anything >1s. |

Service calls block the caller; a navigation goal as a service blocks the whole node until the goal is reached. Use actions.

## QoS

Mismatched QoS between pub and sub = silent connection failure (no error/warning by default; messages just don't arrive).

| Profile | Use for | Reliability | Durability |
|---------|---------|------------|-----------|
| `SystemDefaultQoS` | General use | Reliable | Volatile |
| `SensorDataQoS` | High-freq sensors (LIDAR, cameras, IMU) | Best effort | Volatile |
| `ServicesQoS` | Service comms | Reliable | Volatile |
| `ParametersQoS` | Parameters | Reliable | Transient local |

**Reliability incompatibility:** a `BestEffort` publisher cannot connect to a `Reliable` subscriber (sub demands a higher guarantee than pub offers). Inspect with `ros2 topic info <topic> --verbose`. Reliable QoS on high-freq streams raises CPU/bandwidth — use `SensorDataQoS` above ~10Hz where occasional drops are acceptable.

## Naming and namespaces

Hardcoded topic names break node reuse and multi-robot deployments. Remap/namespace at launch, not in code.

```python
self.create_publisher(Twist, '/cmd_vel', 10)   # Bad — hardcoded, breaks under namespacing
self.create_publisher(Twist, 'cmd_vel', 10)     # Good — relative, inherits namespace
self.create_publisher(Twist, '~/cmd_vel', 10)   # Good — private, scoped to node
```

## Common silent failures

| Symptom | Likely cause |
|---------|-------------|
| Messages published but subscriber never fires | QoS mismatch |
| Transform lookup fails intermittently | Using `now()` instead of `Time(0)` for latest transform |
| Odometry-based navigation drifts or oscillates | Twist velocities in wrong frame (must be child frame, i.e. `base_link`) |
| TF tree error on startup | Static transform published after dynamic; tree temporarily disconnected |
| Node appears running but does nothing | Callback not registered, or executor not spinning |
| Localization jumps instead of correcting smoothly | `map → base_link` published directly instead of via `map → odom` |

## URDF and XACRO

Follow REP-103 in all joint/link definitions; common violation is assuming Y-up (from Blender etc.) when ROS expects Z-up. Inertia tensors must be physically plausible — near-zero inertia destabilizes physics sim; use standard formulas with actual dimensions. Set joint limits for all non-continuous joints; missing limits cause unconstrained sim behavior.

## Design rules the REPs don't state

Topic design: one topic, one coherent data type, one semantic. Node structure: one responsibility per node — combining control, sensing, and planning in one node makes behavior impossible to reason about in isolation.

Sources: REP-103; REP-105; ROS 2 Docs (Topics/Services/Actions; QoS); Karelics 2023.
