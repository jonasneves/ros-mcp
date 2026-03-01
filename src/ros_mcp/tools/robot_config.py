import time

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ros_mcp.utils.config import get_verified_robot_spec_util, get_verified_robots_list_util
from ros_mcp.utils.websocket import WebSocketManager, parse_json


def _detect_ros_version(ws_manager: WebSocketManager) -> dict:
    """Detect ROS version and distro via rosbridge WebSocket."""
    with ws_manager:
        response = ws_manager.request({
            "op": "call_service",
            "id": "ros2_version_check",
            "service": "/rosapi/get_ros_version",
            "args": {},
        })
        values = response.get("values") if response else None
        if isinstance(values, dict) and "version" in values:
            return {"version": values["version"], "distro": values.get("distro")}

        response = ws_manager.request({
            "op": "call_service",
            "id": "ros1_distro_check",
            "service": "/rosapi/get_param",
            "args": {"name": "/rosdistro"},
        })
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
        try:
            robot_config = get_verified_robot_spec_util(name)
        except (FileNotFoundError, ValueError):
            return {
                "error": f"No configuration found for robot '{name}'. "
                "Please check the name and try again. "
                "Or you can set the IP/port manually using the 'connect_to_robot' tool."
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
        description=(
            "Fetch the robot's URDF from the /robot_description ROS parameter. "
            "Returns the URDF XML describing the robot's links, joints, and geometry. "
            "Requires robot_state_publisher to be running.\n"
            "Example:\nget_robot_description()"
        ),
        annotations=ToolAnnotations(
            title="Get Robot Description",
            readOnlyHint=True,
        ),
    )
    def get_robot_description() -> dict:
        message = {
            "op": "call_service",
            "service": "/rosapi/get_param",
            "type": "rosapi_msgs/srv/GetParam",
            "args": {"name": "/robot_description"},
            "id": "get_robot_description",
        }

        with ws_manager:
            response = ws_manager.request(message)

        if "error" in response:
            return {"error": response["error"]}

        result = response.get("values") or response.get("result")
        if not isinstance(result, dict):
            return {"error": "Unexpected response format"}

        urdf = result.get("value", "").strip().strip('"')
        if not urdf:
            return {"error": "Robot description not found. Is robot_state_publisher running?"}

        return {"urdf": urdf, "length": len(urdf)}

    @mcp.tool(
        description=(
            "Read the current joint positions, velocities, and efforts from /joint_states. "
            "Useful for any articulated robot (arms, humanoids). "
            "Positions are in radians, velocities in rad/s, efforts in N·m.\n"
            "Example:\nget_joint_states()\n"
            "get_joint_states(topic='/my_robot/joint_states')"
        ),
        annotations=ToolAnnotations(
            title="Get Joint States",
            readOnlyHint=True,
        ),
    )
    def get_joint_states(
        topic: str = "/joint_states",
        timeout: float = None,  # type: ignore[assignment]
    ) -> dict:
        timeout_val = ws_manager.default_timeout if timeout is None else float(timeout)

        with ws_manager:
            send_error = ws_manager.send({
                "op": "subscribe",
                "topic": topic,
                "type": "sensor_msgs/JointState",
                "queue_length": 1,
            })
            if send_error:
                return {"error": f"Failed to subscribe: {send_error}"}

            msg = None
            end_time = time.time() + timeout_val
            while time.time() < end_time:
                raw = ws_manager.receive(timeout=0.5)
                if raw is None:
                    continue
                data = parse_json(raw)
                if data and data.get("op") == "publish" and data.get("topic") == topic:
                    msg = data.get("msg", {})
                    break

            ws_manager.send({"op": "unsubscribe", "topic": topic})

        if msg is None:
            return {"error": f"Timeout waiting for joint states on {topic}"}

        names = msg.get("name", [])
        positions = msg.get("position", [])
        velocities = msg.get("velocity", [])
        efforts = msg.get("effort", [])

        joints = []
        for i, name in enumerate(names):
            joint: dict = {
                "name": name,
                "position_rad": positions[i] if i < len(positions) else None,
            }
            if velocities:
                joint["velocity_rad_s"] = velocities[i] if i < len(velocities) else None
            if efforts:
                joint["effort_nm"] = efforts[i] if i < len(efforts) else None
            joints.append(joint)

        return {"topic": topic, "joint_count": len(joints), "joints": joints}

    @mcp.tool(
        description="Detect the ROS version and distribution via rosbridge.\nExample:\ndetect_ros_version()",
        annotations=ToolAnnotations(
            title="Detect ROS Version",
            readOnlyHint=True,
        ),
    )
    def detect_ros_version() -> dict:
        return _detect_ros_version(ws_manager)
