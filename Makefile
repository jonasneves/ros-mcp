.DEFAULT_GOAL := help

-include config.mk

FQBN      ?= esp32:esp32:esp32cam:PartitionScheme=default
PORT      ?= $(shell ls /dev/cu.usbserial-* 2>/dev/null | head -1)
MQTT_IP   ?= broker.hivemq.com
ESP32_IP  ?=
BUILD_DIR := /tmp/esp32-led-build
ESPOTA    := $(shell find ~/Library/Arduino15/packages/esp32 -name espota.py 2>/dev/null | sort -V | tail -1)

BUILD_FLAGS := 'build.extra_flags=-DWIFI_SSID="$(strip $(WIFI_SSID))" -DWIFI_PASS="$(strip $(WIFI_PASS))" -DMQTT_IP="$(strip $(MQTT_IP))"'

.PHONY: help setup mqtt preview compile flash ota monitor flash-monitor

help:
	@echo ""
	@echo "Setup"
	@echo "  \033[36msetup\033[0m          Install host dependencies (run once per machine)"
	@echo ""
	@echo "Dev"
	@echo "  \033[36mmqtt\033[0m           Start local Mosquitto broker (optional — cloud broker used by default)"
	@echo "  \033[36mpreview\033[0m        Serve dashboard at http://localhost:8080"
	@echo ""
	@echo "Firmware"
	@echo "  \033[36mflash\033[0m          Compile + upload over USB (first time)"
	@echo "  \033[36mota\033[0m            Compile + upload over WiFi (set ESP32_IP in config.mk)"
	@echo "  \033[36mmonitor\033[0m        Open serial monitor"
	@echo "  \033[36mflash-monitor\033[0m  flash + open serial monitor"
	@echo ""

setup:
	@echo "Installing host dependencies..."
	@echo ""
	@echo "1/2 Installing CP210x USB driver (enables ESP32 USB connection)..."
	brew install --cask silicon-labs-vcp-driver
	@echo ""
	@echo "2/2 Installing arduino-cli (for firmware compilation and upload)..."
	brew install arduino-cli
	arduino-cli core update-index
	arduino-cli core install esp32:esp32
	arduino-cli lib install "PubSubClient"
	@echo ""
	@echo "Done. After install, macOS may prompt you to allow the driver in"
	@echo "System Preferences > Privacy & Security. Do that before running make flash."

mqtt:
	@echo "Local MQTT broker: mqtt://localhost:1883"
	@echo "Local WebSocket:   ws://localhost:9001"
	@echo "To use locally, set in config.mk:"
	@echo "  MQTT_IP = $$(ipconfig getifaddr en0)"
	@echo ""
	docker compose -f docker/docker-compose.yml up mqtt

preview:
	@printf "\n\033[1;36m  Dashboard: http://localhost:8080\033[0m\n\n"
	python3 -m http.server 8080 --directory dashboard

compile:
	@echo "Compiling firmware..."
	@arduino-cli compile \
		--fqbn "$(FQBN)" \
		--build-property $(BUILD_FLAGS) \
		--build-path "$(BUILD_DIR)" \
		firmware/esp32_led

flash: compile
	@echo "Uploading over USB..."
	@arduino-cli upload \
		--fqbn "$(FQBN)" \
		--port "$(PORT)" \
		firmware/esp32_led

ota: compile
	@test -n "$(ESP32_IP)" || (echo "Error: set ESP32_IP in config.mk (shown in Serial Monitor after boot)"; exit 1)
	@test -n "$(ESPOTA)"   || (echo "Error: espota.py not found — run make setup"; exit 1)
	@echo "Uploading over WiFi to $(ESP32_IP)..."
	@python3 "$(ESPOTA)" -i "$(ESP32_IP)" -f "$(BUILD_DIR)/esp32_led_ros.ino.bin"

monitor:
	arduino-cli monitor --port "$(PORT)" --config baudrate=115200,dtr=off,rts=off

flash-monitor: flash
	@echo "Waiting for ESP32 to boot..."
	@sleep 2
	arduino-cli monitor --port "$(PORT)" --config baudrate=115200,dtr=off,rts=off
