# ROS AI Dashboard

Browser dashboard for controlling physical robots with AI. The AI chat calls Claude directly from the browser — no backend, no MCP server, no Python.

## Architecture

![Architecture diagram](diagram.png)

The browser runs everything: it calls the Claude API with ROS tool definitions, and when Claude responds with a tool call, roslibjs executes it locally and forwards it to rosbridge over WebSocket. Claude never talks to rosbridge directly.

The only thing that needs to run locally is rosbridge (via Docker), which bridges WebSocket to your ROS topics and hardware.

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) — for rosbridge
- [Homebrew](https://brew.sh/) — to install host dependencies
- Anthropic API key — for the AI chat

## Host vs Docker split

USB and firmware flashing run on your host machine. Rosbridge runs in Docker. They're kept separate intentionally:

```
Host machine (macOS)
  ├── CP210x driver       ← kernel extension, talks to USB hardware
  ├── arduino-cli         ← compiles and uploads firmware over USB
  └── Docker
        └── rosbridge     ← bridges WebSocket to ROS network over WiFi
```

`make setup` installs the host-side dependencies. Docker handles everything else.

## Quickstart

**1. Install host dependencies** (once per machine)
```bash
make setup
```
After install, macOS will prompt you to allow the CP210x driver in **System Preferences > Privacy & Security**. Do that before proceeding.

**2. Start rosbridge**
```bash
make rosbridge
```
Note the IP it prints — you'll need it in the next step.

**3. Configure credentials** (first time only)

```bash
cp config.mk.example config.mk
```

Edit `config.mk` with your WiFi credentials, the IP from step 2, and your ESP32 USB port.

**4. Flash firmware** (first time only)
```bash
make flash
```

**5. Open the dashboard**

Go to [neevs.io/ros](https://neevs.io/ros) and connect to `ws://localhost:9090`.

**6. Control your robot**

Browse topics and publish manually, or open the AI chat panel, enter your Anthropic API key, and describe what you want the robot to do.

## Repo Structure

```
dashboard/   Static web app — AI chat (Claude API) + ROS topic/node/service browser
docker/      Minimal rosbridge Docker setup (rosbridge + rosapi, no simulation)
firmware/    ESP32 Arduino sketch + flash script
Makefile     make setup     — install host dependencies (once per machine)
             make rosbridge — start rosbridge
             make flash     — compile and upload ESP32 firmware
```

## Notes

The dashboard also attempts to register ROS tools via the [W3C WebMCP spec](https://github.com/webmachinelearning/webmcp) (`navigator.modelContext`), which would expose them to native browser AI agents. This requires Chrome 146+ Canary with `chrome://flags/#webmcp-for-testing`. The AI chat works without this — it's an optional enhancement for when browsers natively support AI agents.
