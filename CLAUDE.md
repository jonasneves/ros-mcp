# ROS MCP Server

## Commands

- Run server: `uv run server.py`
- Add to Claude (local): `make configure`

## Architecture

Tools are registered in `src/ros_mcp/tools/` and wired up in `src/ros_mcp/server.py`. Each tool file owns one domain (topics, services, nodes, etc.). New tools go in the relevant file and must be registered in `server.py`.

## Tool conventions

- `readOnlyHint=True` for read-only tools, `destructiveHint=True` for anything that publishes or mutates state
- Tool descriptions must include units and a concrete example call
- Motion tools must send a zero-velocity stop command as their last action
- Use `turn_by_angle` / `move_by_distance` for rotation and straight-line motion — do not use `publish_for_durations` for these; it requires the caller to compute `duration = angle_rad / angular_velocity` and is error-prone
- When using `publish_for_durations` for angular motion: `duration = (angle_deg × π/180) / angular_velocity_rad_s`

## Simulator cmd_vel topics

The bundled setup runs 3 namespaced turtlesim instances (`ts1`, `ts2`, `ts3`):

| Instance   | Topic                    | Message type          |
|------------|--------------------------|-----------------------|
| turtlesim1 | `/ts1/turtle1/cmd_vel`   | `geometry_msgs/Twist` |
| turtlesim2 | `/ts2/turtle1/cmd_vel`   | `geometry_msgs/Twist` |
| turtlesim3 | `/ts3/turtle1/cmd_vel`   | `geometry_msgs/Twist` |

## Docker / DDS networking

All containers must use the same DDS middleware. The rosbridge container requires `RMW_IMPLEMENTATION=rmw_cyclonedds_cpp` in `docker-compose.yml` — without it, rosbridge defaults to FastDDS and cannot discover topics from the simulator containers (which use CycloneDDS via `entrypoint.sh`).

`cyclonedds.xml` is baked into images via `COPY`, so changes require `docker compose build` before `--force-recreate`.

## Isaac Sim

Isaac Sim uses FastDDS (ROS 2 default). The turtlesim setup forces CycloneDDS on rosbridge — do not reuse that compose file for Isaac Sim.

`docker/docker-compose.isaac-sim.yml` starts rosbridge with:
- `network_mode: host` — container shares host network, sees Isaac Sim DDS multicast
- No `RMW_IMPLEMENTATION` — falls back to FastDDS, matching Isaac Sim

The MCP server runs separately: `ROSBRIDGE_IP=127.0.0.1 make server-http`.

### Nova Carter topics

| Topic | Type | Notes |
|---|---|---|
| `/cmd_vel` | `geometry_msgs/Twist` | Motion control |
| `/odom` | `nav_msgs/Odometry` | Wheel odometry |
| `/scan` | `sensor_msgs/LaserScan` | 2D lidar |
| `/front_3d_lidar/lidar_points` | `sensor_msgs/PointCloud2` | 3D lidar |
| `/front_stereo_camera/left/image_raw` | `sensor_msgs/Image` | Left stereo camera |
| `/chassis_imu` | `sensor_msgs/Imu` | IMU |

## WebMCP dashboard

Source in `dashboard/`. Build: `cd dashboard && node build.mjs`. Deploy: `make deploy-webmcp`.

**The dashboard has its own parallel JS implementation of every tool** (`dashboard/ros-webmcp.js`). Any fix to a tool in `src/ros_mcp/tools/` must also be applied to the corresponding handler in `ros-webmcp.js`, then rebuilt and redeployed. The user interacts with ROS via the deployed dashboard at https://ros-mcp.github.io — not via the Python server directly.
