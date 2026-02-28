"""Integration entry point for embedding ros-mcp into another FastMCP instance.

Environment variables:
    ROSBRIDGE_IP   -- rosbridge server address (default 127.0.0.1)
    ROSBRIDGE_PORT -- rosbridge server port    (default 9090)
    ROS_DEFAULT_TIMEOUT -- default timeout in seconds (default 5.0)
"""

import logging
from typing import Any

from fastmcp import FastMCP

from ros_mcp.server import init_server

logger = logging.getLogger(__name__)


def register(mcp: FastMCP, **kwargs: Any) -> None:
    logger.info("[ROS_MCP] Initializing")
    init_server(mcp)
    logger.info("[ROS_MCP] Registration complete")
