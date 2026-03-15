.DEFAULT_GOAL := server

COMPOSE := docker compose -f docker/docker-compose.yml
COMPOSE_ISAAC := docker compose -f docker/docker-compose.isaac-sim.yml

.PHONY: help server server-http proxy turtlesim robots esp32 isaac-sim configure configure-desktop configure-remote deploy-webmcp status-webmcp

help:
	@echo ""
	@echo "\033[2mServer\033[0m"
	@echo "  \033[36mserver\033[0m             Start the ROS MCP server (stdio)"
	@echo "  \033[36mserver-http\033[0m        Start the ROS MCP server (HTTP on :9000, CORS enabled)"
	@echo "  \033[36mproxy\033[0m              Start local Claude proxy (personal account, port 7337)"
	@echo ""
	@echo "\033[2mDocker\033[0m"
	@echo "  \033[36mturtlesim\033[0m          Launch 3 turtles + MCP server via Docker"
	@echo "  \033[36mrobots\033[0m             Launch simulators + rosbridge only (connect via dashboard)"
	@echo "  \033[36mesp32\033[0m              Launch rosbridge only. For physical ESP32 hardware"
	@echo "  \033[36misaac-sim\033[0m          Launch rosbridge for Isaac Sim (FastDDS, host network)"
	@echo ""
	@echo "\033[2mConfigure\033[0m"
	@echo "  \033[36mconfigure\033[0m          Add this server to Claude Code (local stdio)"
	@echo "  \033[36mconfigure-desktop\033[0m  Add this server to Claude Desktop"
	@echo "  \033[36mconfigure-remote\033[0m   Add the live CI server to Claude (reads URL from git notes)"
	@echo ""
	@echo "\033[2mDashboard\033[0m"
	@echo "  \033[36mdeploy-webmcp\033[0m      Deploy dashboard to GitHub Pages"
	@echo "  \033[36mstatus-webmcp\033[0m      Show last 3 dashboard deploy runs"
	@echo ""

server:
	uv run server.py

server-http:
	uv run server.py --transport streamable-http --host 0.0.0.0 --port 9000

proxy:
	@printf "\n\033[1;36m  Claude proxy: http://127.0.0.1:7337\033[0m\n\n"
	node local-proxy.js

.ghcr-login:
	@gh auth token | docker login ghcr.io -u "$$(gh api user --jq .login)" --password-stdin 2>/dev/null

turtlesim: .ghcr-login
	@echo "ts1: http://localhost:8080/vnc.html  rosbridge: ws://localhost:9090"
	@echo "ts2: http://localhost:8081/vnc.html"
	@echo "ts3: http://localhost:8082/vnc.html"
	@echo "mcp: http://localhost:9000/mcp"
	@echo ""
	$(COMPOSE) up --pull always

robots: .ghcr-login
	@echo "ts1: http://localhost:8080/vnc.html  rosbridge: ws://localhost:9090"
	@echo "ts2: http://localhost:8081/vnc.html"
	@echo "ts3: http://localhost:8082/vnc.html"
	@echo ""
	$(COMPOSE) up --pull always rosbridge turtlesim1 turtlesim2 turtlesim3

esp32:
	@echo "Rosbridge: ws://localhost:9090"
	@echo "ESP32 target IP: $$(ipconfig getifaddr en0)"
	@echo ""
	$(COMPOSE) up --build rosbridge

isaac-sim: .ghcr-login
	@echo "Rosbridge: ws://localhost:9090"
	@echo "MCP server: ROSBRIDGE_IP=127.0.0.1 make server-http"
	@echo ""
	$(COMPOSE_ISAAC) up --build rosbridge

configure:
	claude mcp add --transport stdio ros-mcp -- uv --directory $(shell pwd) run server.py

configure-desktop:
	@python3 -c "\
import json, os, shutil, sys; \
uv = shutil.which('uv'); \
sys.exit('Error: uv not found in PATH') if not uv else None; \
p = os.path.expanduser('~/Library/Application Support/Claude/claude_desktop_config.json'); \
cfg = json.load(open(p)) if os.path.exists(p) else {}; \
cfg.setdefault('mcpServers', {})['ros-mcp'] = {'command': uv, 'args': ['--directory', '$(shell pwd)', 'run', 'server.py']}; \
os.makedirs(os.path.dirname(p), exist_ok=True); \
json.dump(cfg, open(p, 'w'), indent=2); \
print('Configured Claude Desktop with uv=' + uv + ' — restart the app to apply.')"

configure-remote:
	@git fetch origin refs/notes/commits:refs/notes/commits 2>/dev/null || true
	@URL=$$(git notes show $$(git rev-list --max-parents=0 HEAD) 2>/dev/null | grep "^mcp:" | cut -d' ' -f2); \
	if [ -z "$$URL" ]; then echo "No remote URL found in git notes. Trigger the GitHub Actions workflow first."; exit 1; fi; \
	echo "Configuring Claude with $${URL}/mcp"; \
	claude mcp add --transport http ros-mcp $${URL}/mcp

deploy-webmcp:
	cd dashboard && node build.mjs
	git add dashboard/
	git diff --staged --quiet || git commit -m "chore: build dashboard"
	git push

status-webmcp:
	gh run list --repo jonasneves/ros-mcp --workflow deploy.yml --limit 3
