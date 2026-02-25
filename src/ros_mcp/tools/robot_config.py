from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ros_mcp.utils.config import get_verified_robot_spec_util, get_verified_robots_list_util
from ros_mcp.utils.websocket import WebSocketManager


def _detect_ros_version(ws_manager: WebSocketManager) -> dict:
    """Detect ROS version and distro via rosbridge WebSocket."""
    ros2_request = {
        "op": "call_service",
        "id": "ros2_version_check",
        "service": "/rosapi/get_ros_version",
        "args": {},
    }
    with ws_manager:
        response = ws_manager.request(ros2_request)
        values = response.get("values") if response else None
        if isinstance(values, dict) and "version" in values:
            return {"version": values.get("version"), "distro": values.get("distro")}

        ros1_request = {
            "op": "call_service",
            "id": "ros1_distro_check",
            "service": "/rosapi/get_param",
            "args": {"name": "/rosdistro"},
        }
        response = ws_manager.request(ros1_request)
        value = response.get("values") if response else None
        if value:
            distro = value.get("value") if isinstance(value, dict) else value
            distro_clean = str(distro).strip('"').replace("\\n", "").replace("\n", "")
            return {"version": "1", "distro": distro_clean}
    return {"error": "Could not detect ROS version"}


def register_robot_config_tools(mcp: FastMCP, ws_manager: WebSocketManager) -> None:
    @mcp.tool(
        description=(
            "Load specifications and usage context for a verified robot model. "
            "ONLY use if the robot model is in the verified list (use get_verified_robots_list first to check). "
            "Most robots won't have a spec - that's OK, connect directly using connect_to_robot instead."
        ),
        annotations=ToolAnnotations(
            title="Get Verified Robot Spec",
            readOnlyHint=True,
        ),
    )
    def get_verified_robot_spec(name: str) -> dict:
        robot_config = get_verified_robot_spec_util(name)

        if len(robot_config) > 1:
            return {
                "error": f"Multiple configurations found for robot '{name}'. Please specify a more precise name."
            }
        elif not robot_config:
            return {
                "error": f"No configuration found for robot '{name}'. Please check the name and try again. Or you can set the IP/port manually using the 'connect_to_robot' tool."
            }
        return {"robot_config": robot_config}

    @mcp.tool(
        description=(
            "List pre-verified robot models that have specification files with usage guidance available. "
            "Use this to check if a robot model has additional context available before calling get_verified_robot_spec. "
            "If your robot is not in this list, you can still connect to it directly using connect_to_robot."
        ),
        annotations=ToolAnnotations(
            title="Get Verified Robots List",
            readOnlyHint=True,
        ),
    )
    def get_verified_robots_list() -> dict:
        return get_verified_robots_list_util()

    @mcp.tool(
        description="Detect the ROS version and distribution via rosbridge.",
        annotations=ToolAnnotations(
            title="Detect ROS Version",
            readOnlyHint=True,
        ),
    )
    def detect_ros_version() -> dict:
        return _detect_ros_version(ws_manager)
