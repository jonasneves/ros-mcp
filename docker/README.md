# Docker demo — 3× Turtlesim

Runs three isolated turtlesim instances (ts1, ts2, ts3) with rosbridge and the MCP server, all in Docker. No ROS installation required. Display is served via noVNC in the browser.

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) with Docker Compose

## Quick start

```bash
make turtlesim
```

Or directly:

```bash
docker compose -f docker/docker-compose.yml up
```

## Services

| Service | URL | Description |
|---|---|---|
| MCP server | `http://localhost:9000/mcp` | Connect your AI client here |
| rosbridge | `ws://localhost:9090` | ROS WebSocket bridge |
| Turtlesim ts1 | `http://localhost:8080/vnc.html` | Browser display |
| Turtlesim ts2 | `http://localhost:8081/vnc.html` | Browser display |
| Turtlesim ts3 | `http://localhost:8082/vnc.html` | Browser display |

## Topics

| Instance | cmd_vel topic | Message type |
|---|---|---|
| ts1 | `/ts1/turtle1/cmd_vel` | `geometry_msgs/Twist` |
| ts2 | `/ts2/turtle1/cmd_vel` | `geometry_msgs/Twist` |
| ts3 | `/ts3/turtle1/cmd_vel` | `geometry_msgs/Twist` |

## Build images locally

```bash
docker compose -f docker/docker-compose.yml build
```

## Cleanup

```bash
docker compose -f docker/docker-compose.yml down
```
