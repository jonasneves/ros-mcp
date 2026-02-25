from fastmcp import FastMCP

from ros_mcp.tools.actions import register_action_tools
from ros_mcp.tools.connection import register_connection_tools
from ros_mcp.tools.images import register_image_tools
from ros_mcp.tools.nodes import register_node_tools
from ros_mcp.tools.parameters import register_parameter_tools
from ros_mcp.tools.robot_config import register_robot_config_tools
from ros_mcp.tools.services import register_service_tools
from ros_mcp.tools.topics import register_topic_tools
from ros_mcp.utils.websocket import WebSocketManager


def register_all_tools(
    mcp: FastMCP,
    ws_manager: WebSocketManager,
    rosbridge_ip: str = "127.0.0.1",
    rosbridge_port: int = 9090,
) -> None:
    register_action_tools(mcp, ws_manager)
    register_connection_tools(mcp, ws_manager, rosbridge_ip, rosbridge_port)
    register_robot_config_tools(mcp, ws_manager)
    register_image_tools(mcp)
    register_node_tools(mcp, ws_manager)
    register_parameter_tools(mcp, ws_manager)
    register_service_tools(mcp, ws_manager)
    register_topic_tools(mcp, ws_manager)
