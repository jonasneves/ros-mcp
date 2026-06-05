# ros-mcp

[![Build](https://github.com/jonasneves/ros-mcp/actions/workflows/build-push.yml/badge.svg)](https://github.com/jonasneves/ros-mcp/actions/workflows/build-push.yml)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue)](LICENSE)

Drive ROS robots from an AI agent: a FastMCP server that reaches a robot over the [rosbridge](https://github.com/RobotWebTools/rosbridge_suite) WebSocket and exposes its topics, services, nodes, parameters, and actions as 37 MCP tools — usable from Claude Code, Claude Desktop, Cursor, or any MCP client.

```
MCP client ──stdio/HTTP──▶ ros-mcp ──ws :9090──▶ rosbridge ──▶ ROS graph
(Claude, Cursor)                                              (topics, services,
                                                               nodes, actions, params)
```

The browser dashboard skips the Python server: [roslibjs](https://github.com/RobotWebTools/roslibjs) connects straight to rosbridge from the page, with an embedded AI chat panel.

| Mode | Best for | Bridge path |
|---|---|---|
| **Browser dashboard** | Quickest start, no install | page → rosbridge |
| **Python server — stdio** | Claude Code (local) | client → ros-mcp → rosbridge |
| **Python server — HTTP** | Claude Desktop, Cursor, remote | client → ros-mcp `:9000` → rosbridge |
| **Remote CI server** | Shared / cloud-hosted | client → hosted ros-mcp → rosbridge |

See [diagram.png](diagram.png) for the full picture.

## Quick start

You need a running rosbridge (`ros2 launch rosbridge_server rosbridge_websocket_launch.xml`, default port `9090`) — or use the bundled simulators below.

```bash
git clone https://github.com/jonasneves/ros-mcp && cd ros-mcp
```

**Browser dashboard** — open [ros-mcp.github.io](https://ros-mcp.github.io), enter your rosbridge WebSocket URL, connect. No install.

**Claude Code (stdio)**
```bash
make configure
```

**Claude Desktop / Cursor (HTTP on :9000)**
```bash
ROSBRIDGE_IP=<robot-ip> make server-http
make configure-desktop
```

**Remote CI server** — uses the URL published by the GitHub Actions workflow:
```bash
make configure-remote
```

## Docker simulators

**3× Turtlesim** — simulators and rosbridge start automatically; MCP server at `http://localhost:9000/mcp`:
```bash
make turtlesim
```

**Isaac Sim** — Linux + NVIDIA GPU, Isaac Sim installed, ROS 2 Bridge extension enabled:
```bash
make isaac-sim                           # rosbridge (FastDDS, host network)
ROSBRIDGE_IP=127.0.0.1 make server-http  # MCP server, separate terminal
```
On macOS or a remote host, point at a rosbridge already running alongside Isaac Sim: `ROSBRIDGE_IP=<host-ip> make server-http`.

## Tools

| Group | Tools |
|---|---|
| Connection | `connect_to_robot`, `ping_robot` |
| Topics | `get_topics`, `get_topic_type`, `get_topic_details`, `get_message_details`, `subscribe_once`, `subscribe_for_duration`, `publish_once`, `publish_for_durations` |
| Motion | `turn_by_angle`, `move_by_distance`, `move_robots` |
| Services | `get_services`, `get_service_type`, `get_service_details`, `call_service` |
| Nodes | `get_nodes`, `get_connected_robots`, `get_node_details` |
| Actions | `get_actions`, `get_action_details`, `send_action_goal`, `get_action_status`, `cancel_action_goal` |
| Parameters | `get_parameter`, `set_parameter`, `has_parameter`, `delete_parameter`, `get_parameters`, `get_parameter_details` |
| Robot config | `detect_ros_version`, `get_verified_robots_list`, `get_verified_robot_spec`, `get_robot_description`, `get_joint_states` |
| Images | `analyze_previously_received_image` |

Full signatures, units, and examples: [docs/tools.md](docs/tools.md).

## Configuration

| Variable | Default | Description |
|---|---|---|
| `ROSBRIDGE_IP` | `127.0.0.1` | rosbridge host |
| `ROSBRIDGE_PORT` | `9090` | rosbridge port |
| `ROS_DEFAULT_TIMEOUT` | `5.0` | Tool timeout in seconds |

## License

Apache 2.0. See [LICENSE](LICENSE).
