from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ros_mcp.utils.network import ping_ip_and_port
from ros_mcp.utils.websocket import WebSocketManager


def register_connection_tools(
    mcp: FastMCP,
    ws_manager: WebSocketManager,
    default_ip: str,
    default_port: int,
) -> None:
    @mcp.tool(
        description=(
            "Connect to the robot by setting the IP/port. This tool also tests connectivity to confirm that the robot is reachable and the port is open.\n"
            "Example:\nconnect_to_robot(ip='192.168.1.100', port=9090)"
        ),
        annotations=ToolAnnotations(
            title="Connect to Robot",
            destructiveHint=False,
        ),
    )
    def connect_to_robot(
        ip: str = default_ip,
        port: int | str = default_port,
        ping_timeout: float = 2.0,
        port_timeout: float = 2.0,
    ) -> dict:
        resolved_ip = str(ip).strip() or default_ip
        resolved_port = int(port) if port else default_port

        ws_manager.set_ip(resolved_ip, resolved_port)

        return {
            "message": f"WebSocket IP set to {resolved_ip}:{resolved_port}",
            "connectivity_test": ping_ip_and_port(resolved_ip, resolved_port, ping_timeout, port_timeout),
        }

    @mcp.tool(
        description=(
            "Ping a robot's IP address and check if a specific port is open.\n"
            "A successful ping to the IP but not the port can indicate that ROSbridge is not running.\n"
            "Example:\n"
            "ping_robot(ip='192.168.1.100', port=9090)"
        ),
        annotations=ToolAnnotations(
            title="Ping Robot",
            readOnlyHint=True,
        ),
    )
    def ping_robot(
        ip: str,
        port: int,
        ping_timeout: float = 2.0,
        port_timeout: float = 2.0,
    ) -> dict:
        return ping_ip_and_port(ip, port, ping_timeout, port_timeout)
