# ros-mcp

[![Build](https://github.com/jonasneves/ros-mcp/actions/workflows/build-push.yml/badge.svg)](https://github.com/jonasneves/ros-mcp/actions/workflows/build-push.yml)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue)](LICENSE)

Connect AI agents to ROS robots. Exposes topics, services, nodes, parameters, and actions as MCP tools — usable from Claude Desktop, Claude Code, Cursor, or any MCP-compatible client.

| Mode | Best for |
|---|---|
| **Browser dashboard** | Quickest start, no install |
| **Python server — stdio** | Claude Code (local) |
| **Python server — HTTP** | Claude Desktop, Cursor, remote agents |
| **Remote CI server** | Shared / cloud-hosted setup |

## How it works

![ROS MCP Server Architecture](diagram.png)

The browser dashboard skips the Python server entirely — roslibjs connects directly to rosbridge from the browser, with an embedded AI chat panel.

## Quick start

```bash
git clone https://github.com/jonasneves/ros-mcp
cd ros-mcp
```

**Browser dashboard** — open [ros-mcp.github.io](https://ros-mcp.github.io), enter your rosbridge WebSocket URL, and connect. No install required.

**Claude Code (stdio)**
```bash
make configure
```

**Claude Desktop / Cursor (HTTP on :9000)**
```bash
ROSBRIDGE_IP=<robot-ip> make server-http
make configure-desktop
```

**Remote CI server**
```bash
make configure-remote
```

## Docker simulators

**3× Turtlesim** — simulators and rosbridge start automatically, MCP server at `http://localhost:9000/mcp`:
```bash
make turtlesim
```

**Isaac Sim** — requires Linux with NVIDIA GPU, Isaac Sim installed, and the ROS 2 Bridge extension enabled:
```bash
make isaac-sim                           # rosbridge (FastDDS, host network)
ROSBRIDGE_IP=127.0.0.1 make server-http  # MCP server, separate terminal
```

On macOS or a remote machine, point directly at a rosbridge already running alongside Isaac Sim: `ROSBRIDGE_IP=<host-ip> make server-http`.

## Tools

30+ tools covering topics, services, nodes, actions, parameters, robot description, joint states, images, and motion control. See [docs/tools.md](docs/tools.md) for the full reference.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `ROSBRIDGE_IP` | `127.0.0.1` | rosbridge host |
| `ROSBRIDGE_PORT` | `9090` | rosbridge port |
| `ROS_DEFAULT_TIMEOUT` | `5.0` | Timeout in seconds |

## License

Apache 2.0. See [LICENSE](LICENSE).
