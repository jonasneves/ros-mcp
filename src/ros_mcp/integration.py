"""Integration entry point for embedding ros-mcp into another FastMCP instance.

Reads configuration from environment variables:
    ROSBRIDGE_IP: IP address of rosbridge server (default: 127.0.0.1)
    ROSBRIDGE_PORT: Port of rosbridge server (default: 9090)
    ROS_DEFAULT_TIMEOUT: Default timeout for ROS operations (default: 5.0)
"""

import logging

from fastmcp import FastMCP

from ros_mcp.server import init_server

logger = logging.getLogger(__name__)


def register(mcp: FastMCP, **kwargs) -> None:
    logger.info("[ROS_MCP] Initializing")
    init_server(mcp)
    logger.info("[ROS_MCP] Registration complete")
