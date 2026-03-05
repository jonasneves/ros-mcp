---
name: ros-mcp
description: >
  Activate when working in the ros-mcp project — any file under src/ros_mcp/,
  dashboard/, or the project root. Also activate when the user mentions rosbridge,
  FastMCP tool registration, or ROS MCP tools.
---

# ros-mcp conventions

## Architecture

Tools live in `src/ros_mcp/tools/<domain>.py`. Each file owns one domain (topics, services, nodes, actions, parameters, images, robot_config, connection). After adding or renaming a tool, register it in `src/ros_mcp/tools/__init__.py` via `register_all_tools`.

## Tool checklist — every tool must satisfy all of these

1. **Annotations** — every `@mcp.tool()` must include `ToolAnnotations`:
   - `readOnlyHint=True` for anything that only reads state
   - `destructiveHint=True` for anything that publishes, mutates, or moves the robot
   - Never omit both — the absence is a bug, not a default

2. **Description format** — must include:
   - What the tool does
   - Units for every numeric parameter (e.g. `angle_deg` in degrees, `linear_velocity` in m/s)
   - At least one concrete example call showing real argument values

3. **Motion tools** (anything that publishes cmd_vel or controls actuation):
   - Must send a zero-velocity stop command as the last action before returning
   - Use `turn_by_angle` / `move_by_distance` for pure rotation and straight-line motion
   - Do NOT use `publish_for_durations` for simple rotation/translation — it forces the caller to compute duration, which is error-prone
   - If `publish_for_durations` is used for angular motion: `duration = (angle_deg × π/180) / angular_velocity_rad_s`

## Dashboard sync — the highest-cost rule to forget

The dashboard (`dashboard/ros-webmcp.js`) has its own parallel JavaScript implementation of every tool. The Python server and the JS dashboard are two independent codepaths for the same logic.

**Any fix to a tool in `src/ros_mcp/tools/` must also be applied to the corresponding handler in `dashboard/ros-webmcp.js`.**

After updating `ros-webmcp.js`:
```bash
cd dashboard && node build.mjs
make deploy-webmcp
```

The user interacts with ROS via the deployed dashboard at https://ros-mcp.github.io — not the Python server directly. A bug fixed in Python but not in JS will silently persist in production.

## DDS networking — turtlesim vs Isaac Sim

These two setups are incompatible. Never reuse compose files between them.

**Turtlesim (CycloneDDS)**
- rosbridge container needs `RMW_IMPLEMENTATION=rmw_cyclonedds_cpp` in `docker-compose.yml`
- Without it, rosbridge defaults to FastDDS and cannot see simulator topics
- `cyclonedds.xml` is baked into images — config changes require `docker compose build` before `--force-recreate`

**Isaac Sim (FastDDS)**
- Isaac Sim uses FastDDS (ROS 2 default)
- Use `docker/docker-compose.isaac-sim.yml` — it sets `network_mode: host` and omits `RMW_IMPLEMENTATION`
- MCP server runs separately: `ROSBRIDGE_IP=127.0.0.1 make server-http`

## Simulator quick reference

| Instance   | cmd_vel topic              | msg_type              |
|------------|----------------------------|-----------------------|
| turtlesim1 | `/ts1/turtle1/cmd_vel`     | `geometry_msgs/Twist` |
| turtlesim2 | `/ts2/turtle1/cmd_vel`     | `geometry_msgs/Twist` |
| turtlesim3 | `/ts3/turtle1/cmd_vel`     | `geometry_msgs/Twist` |

**Nova Carter (Isaac Sim)**

| Topic                                    | Type                        |
|------------------------------------------|-----------------------------|
| `/cmd_vel`                               | `geometry_msgs/Twist`       |
| `/odom`                                  | `nav_msgs/Odometry`         |
| `/scan`                                  | `sensor_msgs/LaserScan`     |
| `/front_3d_lidar/lidar_points`           | `sensor_msgs/PointCloud2`   |
| `/front_stereo_camera/left/image_raw`    | `sensor_msgs/Image`         |
| `/chassis_imu`                           | `sensor_msgs/Imu`           |

## Commands

```bash
uv run server.py              # run MCP server (stdio)
make configure                # add to Claude Code (local/stdio)
ROSBRIDGE_IP=<ip> make server-http && make configure-desktop  # Claude Desktop / Cursor
make turtlesim                # start 3× turtlesim with rosbridge
cd dashboard && node build.mjs  # rebuild dashboard bundle
make deploy-webmcp            # deploy dashboard to GitHub Pages
```
