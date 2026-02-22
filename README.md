# MQTT AI Dashboard

Browser dashboard for controlling physical robots with AI. The AI chat calls Claude directly from the browser — no backend, no MCP server, no Python.

## Architecture

The browser runs everything: MQTT.js connects to a broker over WebSocket. Claude is called directly from the browser with MQTT tool definitions, and when Claude responds with a tool call, the dashboard publishes to the broker. The ESP32 subscribes to the same broker over TCP.

By default both sides connect to a public cloud broker — no Docker or local setup needed.

![Architecture and sequence diagrams](diagrams.jpg)

## Prerequisites

- [Homebrew](https://brew.sh/) — to install host dependencies
- Anthropic API key — for the AI chat

## Quickstart

**1. Install host dependencies** (once per machine)
```bash
make setup
```
After install, macOS will prompt you to allow the CP210x driver in **System Preferences > Privacy & Security**. Do that before flashing.

**2. Configure credentials** (first time only)
```bash
cp config.mk.example config.mk
```
Edit `config.mk` with your WiFi SSID and password.

**3. Flash firmware** (first time, via USB)
```bash
make flash
```
After boot, the ESP32 prints its unique topic (e.g. `devices/d4e9f4a2a044/led/command`) and its local IP. Add the IP to `config.mk` as `ESP32_IP` to enable OTA updates.

**4. Open the dashboard**

Go to [neevs.io/mqtt-ai](https://neevs.io/mqtt-ai) and click **Connect** — it defaults to the public HiveMQ broker, the same one the ESP32 connects to. Topics appear automatically.

**5. Control your robot**

Browse topics and publish manually, or open the AI chat panel, enter your Anthropic API key, and describe what you want the robot to do.

## OTA updates

After the first USB flash, subsequent firmware updates go over WiFi:

```bash
make ota
```

Requires `ESP32_IP` set in `config.mk` (printed by the ESP32 on boot).

## Local broker (optional)

For offline use or private data, run a local Mosquitto broker:

```bash
make mqtt
```

Then set in `config.mk`:
```
MQTT_IP = <your local IP>
```

And connect the dashboard to `ws://<your local IP>:9001`.

## Repo structure

```
dashboard/   Static web app — AI chat (Claude API) + MQTT topic browser
docker/      Mosquitto config for local broker (optional)
firmware/    ESP32 Arduino sketch — LED control via MQTT, OTA support
Makefile     make setup    — install host dependencies (once per machine)
             make flash    — compile and upload firmware over USB (first time)
             make ota      — upload firmware over WiFi (requires ESP32_IP)
             make monitor  — open serial console
             make mqtt     — start local Mosquitto broker (optional)
             make preview  — serve dashboard at http://localhost:8080
```

## Notes

The dashboard also registers MQTT tools via the [W3C WebMCP spec](https://github.com/webmachinelearning/webmcp) (`navigator.modelContext`), which exposes them to native browser AI agents. This requires Chrome 146+ Canary with `chrome://flags/#webmcp-for-testing`. The AI chat works without this — it's an optional enhancement.
