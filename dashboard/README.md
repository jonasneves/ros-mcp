# ROS WebMCP Dashboard

A static browser app for monitoring and controlling a ROS 2 robot. No Python server, no build step — just open the file and connect to rosbridge.

## What it does

- Connects to rosbridge via WebSocket (roslibjs)
- Browses topics, nodes, and services; subscribes, publishes, calls services
- **AI chat panel** — ask an AI to inspect or control the robot using the same 13 ROS tools, powered by Claude or GitHub Models via their APIs
- **WebMCP registration** (optional) — exposes those same tools to native browser AI agents via `navigator.modelContext.registerTool`

## How the tools work

The same 13 ROS tools are shared by both paths:

```
TOOLS[]  (name + description + handler)
  │
  ├── AI chat panel  — you call Claude/GitHub Models API directly with your key;
  │                    the page's agentic loop executes tool.handler() in JS.
  │                    Works in any browser, no flags needed.
  │
  └── WebMCP registration — registers tools with the browser's AI context so
                            external agents (e.g. a Claude browser integration)
                            can call them without the chat panel.
                            Requires Chrome 146+ Canary + WebMCP flag.
```

The **WebMCP badge** at the bottom of the sidebar is always clickable — it explains this relationship and lists all tools regardless of whether WebMCP is active.

## Requirements

**Always required:**
- rosbridge reachable from the browser:
  ```bash
  ros2 launch rosbridge_server rosbridge_websocket_launch.xml
  # default: ws://localhost:9090
  ```
- A static file server:
  ```bash
  python3 -m http.server 8080
  ```

**For AI chat:**
- Claude: an [Anthropic API key](https://console.anthropic.com)
- GitHub Models: a GitHub account (OAuth login built in)

**For WebMCP tool registration (optional):**
- Chrome 146+ Canary
- `chrome://flags/#webmcp-for-testing` → Enabled

## Usage

1. Serve the directory and open `http://localhost:8080`
2. Enter the rosbridge URL and click **Connect**
3. Browse topics, nodes, and services in the left panel
4. Click **AI Chat** in the topbar — select a model, authenticate, and ask anything about your robot

## Tools

| Tool | Description |
|---|---|
| `connect_to_robot` | Set rosbridge WebSocket URL and reconnect |
| `get_topics` | List all topics |
| `get_topic_type` | Get message type for a topic |
| `get_topic_details` | Publishers, subscribers, type |
| `subscribe_once` | Receive the first message on a topic |
| `subscribe_for_duration` | Collect messages for N seconds |
| `publish_once` | Publish a single message |
| `publish_for_durations` | Publish a sequence of messages with delays |
| `get_services` | List all services |
| `get_service_details` | Request/response types for a service |
| `call_service` | Call a ROS service with a request payload |
| `get_nodes` | List all nodes |
| `get_node_details` | Publishers, subscribers, services for a node |

## References

- [roslibjs](http://robotwebtools.org/roslibjs/)
- [rosbridge_suite](https://github.com/RobotWebTools/rosbridge_suite)
- [W3C WebMCP spec](https://github.com/nicholasgasior/webmcp)
- [ros-mcp](../../README.md)
