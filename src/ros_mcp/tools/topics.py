import math
import time

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ros_mcp.tools.images import convert_expects_image_hint
from ros_mcp.utils.websocket import (
    WebSocketManager,
    extract_service_failure_error,
    parse_input,
    parse_json,
)


def _parse_status_error(raw_response: str | bytes | None) -> str | None:
    """Return the error message if raw_response is a rosbridge status error, else None."""
    msg_data = parse_json(raw_response)
    if msg_data is None:
        return None
    if msg_data.get("op") == "status" and msg_data.get("level") == "error":
        return msg_data.get("msg", "Unknown error")
    return None


def _validate_nonneg_float(value, name: str) -> tuple[float, dict | None]:
    """Coerce to float >= 0. Returns (coerced_value, error_dict_or_None)."""
    try:
        value = float(value)
    except (ValueError, TypeError):
        return 0.0, {"error": f"{name} must be a number"}
    if value < 0:
        return 0.0, {"error": f"{name} must be >= 0"}
    return value, None


def _validate_pos_int(value, name: str) -> tuple[int, dict | None]:
    """Coerce to int >= 1. Returns (coerced_value, error_dict_or_None)."""
    try:
        value = int(value)
    except (ValueError, TypeError):
        return 0, {"error": f"{name} must be an integer"}
    if value < 1:
        return 0, {"error": f"{name} must be an integer >= 1"}
    return value, None


def _validate_nonneg_int(value, name: str) -> tuple[int, dict | None]:
    """Coerce to int >= 0. Returns (coerced_value, error_dict_or_None)."""
    try:
        value = int(value)
    except (ValueError, TypeError):
        return 0, {"error": f"{name} must be an integer"}
    if value < 0:
        return 0, {"error": f"{name} must be an integer >= 0"}
    return value, None


_TWIST_STOP = {"linear": {"x": 0.0}, "angular": {"z": 0.0}}
_STAMPED_HEADER = {"stamp": {"sec": 0, "nanosec": 0}, "frame_id": ""}


def _wrap_twist(msg_type: str, twist: dict) -> dict:
    """Wrap a Twist dict in a TwistStamped envelope when the msg_type requires it."""
    if "TwistStamped" in msg_type:
        return {"header": _STAMPED_HEADER, "twist": twist}
    return twist


def register_topic_tools(
    mcp: FastMCP,
    ws_manager: WebSocketManager,
) -> None:
    def _publish_motion(
        topic: str, msg_type: str, velocity_msg: dict, duration: float
    ) -> str | None:
        """Advertise, publish velocity for duration, publish stop, unadvertise.

        Returns an error string on failure, or None on success.
        """
        send_error = ws_manager.send({"op": "advertise", "topic": topic, "type": msg_type})
        if send_error:
            return f"Failed to advertise topic: {send_error}"

        try:
            ws_manager.send({"op": "publish", "topic": topic, "msg": _wrap_twist(msg_type, velocity_msg)})
            time.sleep(duration)
            ws_manager.send({"op": "publish", "topic": topic, "msg": _wrap_twist(msg_type, _TWIST_STOP)})
        finally:
            ws_manager.send({"op": "unadvertise", "topic": topic})
        return None

    @mcp.tool(
        description=("Get list of all available ROS topics.\nExample:\nget_topics()"),
        annotations=ToolAnnotations(
            title="Get Topics",
            readOnlyHint=True,
        ),
    )
    def get_topics() -> dict:
        message = {
            "op": "call_service",
            "service": "/rosapi/topics",
            "type": "rosapi/Topics",
            "args": {},
            "id": "get_topics_request_1",
        }

        with ws_manager:
            response = ws_manager.request(message)

        if err := extract_service_failure_error(response):
            return err

        if "values" in response:
            values = response["values"]
            topics = values.get("topics", [])
            types = values.get("types", [])
            return {"topics": topics, "types": types, "topic_count": len(topics)}

        return {"warning": "No topics found"}

    @mcp.tool(
        description=(
            "Get the message type for a specific topic.\nExample:\nget_topic_type('/cmd_vel')"
        ),
        annotations=ToolAnnotations(
            title="Get Topic Type",
            readOnlyHint=True,
        ),
    )
    def get_topic_type(topic: str) -> dict:
        if not topic or not topic.strip():
            return {"error": "Topic name cannot be empty"}

        message = {
            "op": "call_service",
            "service": "/rosapi/topic_type",
            "type": "rosapi/TopicType",
            "args": {"topic": topic},
            "id": f"get_topic_type_request_{topic.replace('/', '_')}",
        }

        with ws_manager:
            response = ws_manager.request(message)

        if err := extract_service_failure_error(response):
            return err

        if "values" in response:
            topic_type = response["values"].get("type", "")
            if topic_type:
                return {"topic": topic, "type": topic_type}
            return {"error": f"Topic {topic} does not exist or has no type"}

        return {"error": f"Failed to get type for topic {topic}"}

    @mcp.tool(
        description=(
            "Get detailed information about a specific topic including its type, publishers, and subscribers.\n"
            "Example:\n"
            "get_topic_details('/cmd_vel')"
        ),
        annotations=ToolAnnotations(
            title="Get Topic Details",
            readOnlyHint=True,
        ),
    )
    def get_topic_details(topic: str) -> dict:
        if not topic or not topic.strip():
            return {"error": "Topic name cannot be empty"}

        result = {
            "topic": topic,
            "type": "unknown",
            "publishers": [],
            "subscribers": [],
        }

        topic_slug = topic.replace("/", "_")

        with ws_manager:
            type_resp = ws_manager.request({
                "op": "call_service",
                "service": "/rosapi/topic_type",
                "type": "rosapi/TopicType",
                "args": {"topic": topic},
                "id": f"get_topic_type_{topic_slug}",
            })
            if "values" in type_resp:
                result["type"] = type_resp["values"].get("type", "unknown")

            pub_resp = ws_manager.request({
                "op": "call_service",
                "service": "/rosapi/publishers",
                "type": "rosapi/Publishers",
                "args": {"topic": topic},
                "id": f"get_publishers_{topic_slug}",
            })
            if "values" in pub_resp:
                result["publishers"] = pub_resp["values"].get("publishers", [])

            sub_resp = ws_manager.request({
                "op": "call_service",
                "service": "/rosapi/subscribers",
                "type": "rosapi/Subscribers",
                "args": {"topic": topic},
                "id": f"get_subscribers_{topic_slug}",
            })
            if "values" in sub_resp:
                result["subscribers"] = sub_resp["values"].get("subscribers", [])

        result["publisher_count"] = len(result["publishers"])
        result["subscriber_count"] = len(result["subscribers"])

        if result["type"] == "unknown" and not result["publishers"] and not result["subscribers"]:
            return {"error": f"Topic {topic} not found or has no details available"}

        return result

    @mcp.tool(
        description=(
            "Get the complete structure/definition of a message type.\n"
            "Example:\n"
            "get_message_details('geometry_msgs/Twist')"
        ),
        annotations=ToolAnnotations(
            title="Get Message Details",
            readOnlyHint=True,
        ),
    )
    def get_message_details(message_type: str) -> dict:
        if not message_type or not message_type.strip():
            return {"error": "Message type cannot be empty"}

        message = {
            "op": "call_service",
            "service": "/rosapi/message_details",
            "type": "rosapi/MessageDetails",
            "args": {"type": message_type},
            "id": f"get_message_details_request_{message_type.replace('/', '_')}",
        }

        with ws_manager:
            response = ws_manager.request(message)

        if err := extract_service_failure_error(response):
            return err

        if "values" in response:
            typedefs = response["values"].get("typedefs", [])
            if typedefs:
                structure = {}
                for typedef in typedefs:
                    type_name = typedef.get("type", message_type)
                    field_names = typedef.get("fieldnames", [])
                    field_types = typedef.get("fieldtypes", [])
                    fields = dict(zip(field_names, field_types))
                    structure[type_name] = {"fields": fields, "field_count": len(fields)}

                return {"message_type": message_type, "structure": structure}
            return {"error": f"Message type {message_type} not found or has no definition"}

        return {"error": f"Failed to get details for message type {message_type}"}

    @mcp.tool(
        description=(
            "Subscribe to a ROS topic and return the first message received.\n"
            "Example:\n"
            "subscribe_once(topic='/cmd_vel', msg_type='geometry_msgs/msg/TwistStamped')\n"
            "subscribe_once(topic='/slow_topic', msg_type='my_package/SlowMsg', timeout=10.0)  # Use longer timeout for slow topics\n"
            "subscribe_once(topic='/high_rate_topic', msg_type='sensor_msgs/Image', timeout=5.0, queue_length=5, throttle_rate_ms=100)  # Control message buffering and rate\n"
            "subscribe_once(topic='/camera/image_raw', msg_type='sensor_msgs/Image', expects_image='true')  # Hint that this is an image for faster processing\n"
            "subscribe_once(topic='/point_cloud', msg_type='sensor_msgs/PointCloud2', expects_image='false')  # Skip image detection for non-image data"
        ),
        annotations=ToolAnnotations(
            title="Subscribe Once",
            readOnlyHint=True,
        ),
    )
    def subscribe_once(
        topic: str = "",
        msg_type: str = "",
        expects_image: str = "auto",
        timeout: float = None,  # type: ignore[assignment]  # FastMCP doesn't support Optional[float]
        queue_length: int = None,  # type: ignore[assignment]  # FastMCP doesn't support Optional[int]
        throttle_rate_ms: int = None,  # type: ignore[assignment]  # FastMCP doesn't support Optional[int]
    ) -> dict:
        if not topic or not msg_type:
            return {"error": "Missing required arguments: topic and msg_type must be provided."}

        timeout, err = _validate_nonneg_float(
            ws_manager.default_timeout if timeout is None else timeout, "timeout"
        )
        if err:
            return err

        queue_length, err = _validate_pos_int(
            1 if queue_length is None else queue_length, "queue_length"
        )
        if err:
            return err

        throttle_rate_ms, err = _validate_nonneg_int(
            0 if throttle_rate_ms is None else throttle_rate_ms, "throttle_rate_ms"
        )
        if err:
            return err

        subscribe_msg: dict = {
            "op": "subscribe",
            "topic": topic,
            "type": msg_type,
            "queue_length": queue_length,
            "throttle_rate": throttle_rate_ms,
        }

        expects_image_bool = convert_expects_image_hint(expects_image)

        with ws_manager:
            send_error = ws_manager.send(subscribe_msg)
            if send_error:
                return {"error": f"Failed to subscribe: {send_error}"}

            end_time = time.time() + timeout
            while time.time() < end_time:
                response = ws_manager.receive(timeout=0.5)
                if response is None:
                    continue

                msg_data, was_parsed_as_image = parse_input(response, expects_image_bool)

                if not msg_data:
                    continue

                if msg_data.get("op") == "status" and msg_data.get("level") == "error":
                    return {"error": f"Rosbridge error: {msg_data.get('msg', 'Unknown error')}"}

                if msg_data.get("op") == "publish" and msg_data.get("topic") == topic:
                    ws_manager.send({"op": "unsubscribe", "topic": topic})
                    if was_parsed_as_image:
                        msg_content = msg_data.get("msg", {})
                        filtered_msg = {k: v for k, v in msg_content.items() if k != "data"}
                        return {
                            "msg": filtered_msg,
                            "message": "Image received successfully and saved in the MCP server. Run the 'analyze_previously_received_image' tool to analyze it",
                        }
                    return {"msg": msg_data.get("msg", {})}

            ws_manager.send({"op": "unsubscribe", "topic": topic})
            return {"error": "Timeout waiting for message from topic"}

    @mcp.tool(
        description=(
            "Subscribe to a topic for a duration and collect messages.\n"
            "Example:\n"
            "subscribe_for_duration(topic='/cmd_vel', msg_type='geometry_msgs/msg/TwistStamped', duration=5, max_messages=10)\n"
            "subscribe_for_duration(topic='/high_rate_topic', msg_type='sensor_msgs/Image', duration=10, queue_length=5, throttle_rate_ms=100)  # Control message buffering and rate\n"
            "subscribe_for_duration(topic='/camera/image_raw', msg_type='sensor_msgs/Image', duration=5, expects_image='true')  # Hint that this is an image for faster processing\n"
            "subscribe_for_duration(topic='/point_cloud', msg_type='sensor_msgs/PointCloud2', duration=5, expects_image='false')  # Skip image detection for non-image data"
        ),
        annotations=ToolAnnotations(
            title="Subscribe for Duration",
            readOnlyHint=True,
        ),
    )
    def subscribe_for_duration(
        topic: str = "",
        msg_type: str = "",
        duration: float = 5.0,
        max_messages: int = 100,
        queue_length: int = None,  # type: ignore[assignment]  # FastMCP doesn't support Optional[int]
        throttle_rate_ms: int = None,  # type: ignore[assignment]  # FastMCP doesn't support Optional[int]
        expects_image: str = "auto",
    ) -> dict:
        if not topic or not msg_type:
            return {"error": "Missing required arguments: topic and msg_type must be provided."}

        duration, err = _validate_nonneg_float(duration, "duration")
        if err:
            return err

        max_messages, err = _validate_pos_int(max_messages, "max_messages")
        if err:
            return err

        queue_length, err = _validate_pos_int(
            1 if queue_length is None else queue_length, "queue_length"
        )
        if err:
            return err

        throttle_rate_ms, err = _validate_nonneg_int(
            0 if throttle_rate_ms is None else throttle_rate_ms, "throttle_rate_ms"
        )
        if err:
            return err

        subscribe_msg: dict = {
            "op": "subscribe",
            "topic": topic,
            "type": msg_type,
            "queue_length": queue_length,
            "throttle_rate": throttle_rate_ms,
        }

        expects_image_bool = convert_expects_image_hint(expects_image)

        with ws_manager:
            send_error = ws_manager.send(subscribe_msg)
            if send_error:
                return {"error": f"Failed to subscribe: {send_error}"}

            collected_messages = []
            status_errors = []
            end_time = time.time() + duration

            while time.time() < end_time and len(collected_messages) < max_messages:
                response = ws_manager.receive(timeout=0.5)
                if response is None:
                    continue

                msg_data, was_parsed_as_image = parse_input(response, expects_image_bool)

                if not msg_data:
                    continue

                if msg_data.get("op") == "status" and msg_data.get("level") == "error":
                    status_errors.append(msg_data.get("msg", "Unknown error"))
                    continue

                if msg_data.get("op") == "publish" and msg_data.get("topic") == topic:
                    if was_parsed_as_image:
                        msg_content = msg_data.get("msg", {})
                        filtered_msg = {k: v for k, v in msg_content.items() if k != "data"}
                        collected_messages.append(
                            {
                                "image_message": "Image received and saved. Use 'analyze_previously_received_image' to analyze it.",
                                "msg": filtered_msg,
                            }
                        )
                    else:
                        collected_messages.append(msg_data.get("msg", {}))

            ws_manager.send({"op": "unsubscribe", "topic": topic})

        return {
            "topic": topic,
            "collected_count": len(collected_messages),
            "messages": collected_messages,
            "status_errors": status_errors,
        }

    @mcp.tool(
        description=(
            "Publish a sequence of messages with delays.\n"
            "Each message is published once; the robot holds that velocity for the given duration.\n"
            "For angular motion: duration = (angle_deg * π/180) / angular_velocity_rad_s.\n"
            "Example — rotate 90° at 1.0 rad/s: duration = (90 * π/180) / 1.0 = 1.571s.\n"
            "Always send a zero-velocity message as the final entry to stop the robot.\n"
            "Prefer turn_by_angle / move_by_distance when only rotating or translating — "
            "they compute duration automatically and stop the robot.\n"
            "Example:\n"
            "publish_for_durations(topic='/cmd_vel', msg_type='geometry_msgs/msg/TwistStamped', "
            "messages=[{'linear': {'x': 1.0}}, {'linear': {'x': 0.0}}], durations=[1, 0])"
        ),
        annotations=ToolAnnotations(
            title="Publish for Durations",
            destructiveHint=True,
        ),
    )
    def publish_for_durations(
        topic: str = "",
        msg_type: str = "",
        messages: list[dict] | None = None,
        durations: list[float] | None = None,
    ) -> dict:
        messages = list(messages or [])
        durations = list(durations or [])

        if not topic or not msg_type:
            return {"error": "Missing required arguments: topic and msg_type must be provided."}

        if not messages and not durations:
            return {
                "success": True,
                "published_count": 0,
                "total_messages": 0,
                "topic": topic,
                "msg_type": msg_type,
                "errors": [],
            }

        if len(messages) != len(durations):
            return {"error": "messages and durations must have the same length"}

        if any(d < 0 for d in durations):
            return {"error": "durations must be >= 0"}

        published_count = 0
        errors = []

        with ws_manager:
            advertise_msg = {"op": "advertise", "topic": topic, "type": msg_type}
            send_error = ws_manager.send(advertise_msg)
            if send_error:
                return {"error": f"Failed to advertise topic: {send_error}"}

            try:
                for i, (msg, delay) in enumerate(zip(messages, durations)):
                    publish_msg = {"op": "publish", "topic": topic, "msg": msg}

                    send_error = ws_manager.send(publish_msg)
                    if send_error:
                        errors.append(f"Message {i + 1}: {send_error}")
                        continue

                    response = ws_manager.receive(timeout=1.0)
                    status_err = _parse_status_error(response)
                    if status_err:
                        errors.append(f"Message {i + 1}: {status_err}")
                        continue

                    published_count += 1
                    if delay:
                        time.sleep(delay)

            finally:
                ws_manager.send({"op": "unadvertise", "topic": topic})

        return {
            "success": True,
            "published_count": published_count,
            "total_messages": len(messages),
            "topic": topic,
            "msg_type": msg_type,
            "errors": errors,
        }

    @mcp.tool(
        description=(
            "Rotate a robot by a specified angle. "
            "Calculates duration = |angle_deg| * π/180 / angular_velocity automatically.\n"
            "Positive angle = counterclockwise (left), negative = clockwise (right).\n"
            "Sends a stop command after the rotation completes.\n"
            "Turtlesim (namespaced): cmd_vel_topic='/ts1/turtle1/cmd_vel', msg_type='geometry_msgs/Twist'\n"
            "Example — spin 144° clockwise at 1.0 rad/s on Turtlesim:\n"
            "turn_by_angle(cmd_vel_topic='/ts1/turtle1/cmd_vel', msg_type='geometry_msgs/Twist', "
            "angle_deg=-144.0)"
        ),
        annotations=ToolAnnotations(
            title="Turn by Angle",
            destructiveHint=True,
        ),
    )
    def turn_by_angle(
        cmd_vel_topic: str = "",
        msg_type: str = "",
        angle_deg: float = 0.0,
        angular_velocity: float = 1.0,
    ) -> dict:
        if not cmd_vel_topic or not msg_type:
            return {"error": "cmd_vel_topic and msg_type are required"}
        if angular_velocity <= 0:
            return {"error": "angular_velocity must be > 0"}

        angle_rad = angle_deg * math.pi / 180.0
        duration = abs(angle_rad) / angular_velocity
        angular_z = math.copysign(angular_velocity, angle_rad)

        with ws_manager:
            error = _publish_motion(
                cmd_vel_topic, msg_type, {"angular": {"z": angular_z}}, duration
            )
            if error:
                return {"error": error}

        return {
            "success": True,
            "angle_deg": angle_deg,
            "angle_rad": round(angle_rad, 4),
            "angular_velocity": angular_velocity,
            "duration_s": round(duration, 4),
        }

    @mcp.tool(
        description=(
            "Move a robot forward or backward by a specified distance. "
            "Calculates duration = |distance_m| / linear_velocity automatically.\n"
            "Positive distance = forward, negative = backward.\n"
            "Sends a stop command after the movement completes.\n"
            "Turtlesim (namespaced): cmd_vel_topic='/ts1/turtle1/cmd_vel', msg_type='geometry_msgs/Twist'\n"
            "Example — move forward 1 metre at 0.5 m/s on Turtlesim:\n"
            "move_by_distance(cmd_vel_topic='/ts1/turtle1/cmd_vel', msg_type='geometry_msgs/Twist', "
            "distance_m=1.0)"
        ),
        annotations=ToolAnnotations(
            title="Move by Distance",
            destructiveHint=True,
        ),
    )
    def move_by_distance(
        cmd_vel_topic: str = "",
        msg_type: str = "",
        distance_m: float = 0.0,
        linear_velocity: float = 0.5,
    ) -> dict:
        if not cmd_vel_topic or not msg_type:
            return {"error": "cmd_vel_topic and msg_type are required"}
        if linear_velocity <= 0:
            return {"error": "linear_velocity must be > 0"}

        duration = abs(distance_m) / linear_velocity
        linear_x = math.copysign(linear_velocity, distance_m)

        with ws_manager:
            error = _publish_motion(cmd_vel_topic, msg_type, {"linear": {"x": linear_x}}, duration)
            if error:
                return {"error": error}

        return {
            "success": True,
            "distance_m": distance_m,
            "linear_velocity": linear_velocity,
            "duration_s": round(duration, 4),
        }

    @mcp.tool(
        description=(
            "Move multiple robots simultaneously by publishing to all their cmd_vel topics "
            "within a single connection. All robots start and stop at the same time.\n"
            "Each entry in robots requires: cmd_vel_topic, msg_type, and at least one of linear_x or angular_z.\n"
            "Use get_connected_robots() first to discover topics and message types.\n"
            "Turtlesim (namespaced): msg_type='geometry_msgs/Twist'\n"
            "Example — move all three turtlesim instances forward for 2 seconds:\n"
            "move_robots(robots=["
            "{'cmd_vel_topic': '/ts1/turtle1/cmd_vel', 'msg_type': 'geometry_msgs/Twist', 'linear_x': 1.0}, "
            "{'cmd_vel_topic': '/ts2/turtle1/cmd_vel', 'msg_type': 'geometry_msgs/Twist', 'linear_x': 1.0}, "
            "{'cmd_vel_topic': '/ts3/turtle1/cmd_vel', 'msg_type': 'geometry_msgs/Twist', 'linear_x': 1.0}"
            "], duration=2.0)"
        ),
        annotations=ToolAnnotations(
            title="Move Robots",
            destructiveHint=True,
        ),
    )
    def move_robots(robots: list[dict] | None = None, duration: float = 2.0) -> dict:
        robots = list(robots or [])

        if not robots:
            return {"error": "robots list cannot be empty"}

        duration, err = _validate_nonneg_float(duration, "duration")
        if err:
            return err

        prepared = []
        for i, robot in enumerate(robots):
            topic = str(robot.get("cmd_vel_topic", "")).strip()
            msg_type = str(robot.get("msg_type", "")).strip()
            if not topic or not msg_type:
                return {"error": f"Robot {i}: cmd_vel_topic and msg_type are required"}
            try:
                linear_x = float(robot.get("linear_x", 0.0))
                angular_z = float(robot.get("angular_z", 0.0))
            except (ValueError, TypeError):
                return {"error": f"Robot {i}: linear_x and angular_z must be numbers"}

            base_vel = {"linear": {"x": linear_x}, "angular": {"z": angular_z}}
            prepared.append({
                "topic": topic,
                "msg_type": msg_type,
                "vel_msg": _wrap_twist(msg_type, base_vel),
                "stop_msg": _wrap_twist(msg_type, _TWIST_STOP),
            })

        with ws_manager:
            for r in prepared:
                send_error = ws_manager.send({"op": "advertise", "topic": r["topic"], "type": r["msg_type"]})
                if send_error:
                    return {"error": f"Failed to advertise {r['topic']}: {send_error}"}
            try:
                for r in prepared:
                    ws_manager.send({"op": "publish", "topic": r["topic"], "msg": r["vel_msg"]})
                time.sleep(duration)
                for r in prepared:
                    ws_manager.send({"op": "publish", "topic": r["topic"], "msg": r["stop_msg"]})
            finally:
                for r in prepared:
                    ws_manager.send({"op": "unadvertise", "topic": r["topic"]})

        return {
            "success": True,
            "robots_moved": len(prepared),
            "duration_s": duration,
            "topics": [r["topic"] for r in prepared],
        }

    @mcp.tool(
        description=(
            "Publish a single message to a ROS topic.\n"
            "Example:\n"
            "publish_once(topic='/cmd_vel', msg_type='geometry_msgs/msg/TwistStamped', msg={'linear': {'x': 1.0}})"
        ),
        annotations=ToolAnnotations(
            title="Publish Once",
            destructiveHint=True,
        ),
    )
    def publish_once(topic: str = "", msg_type: str = "", msg: dict | None = None) -> dict:
        msg = dict(msg or {})

        if not topic or not topic.strip():
            return {"error": "topic is required and cannot be empty"}
        if not msg_type or not msg_type.strip():
            return {"error": "msg_type is required and cannot be empty"}
        if not msg:
            return {"error": "msg cannot be empty"}

        with ws_manager:
            send_error = ws_manager.send({"op": "advertise", "topic": topic, "type": msg_type})
            if send_error:
                return {"error": f"Failed to advertise topic: {send_error}"}

            status_err = _parse_status_error(ws_manager.receive(timeout=1.0))
            if status_err:
                return {"error": f"Advertise failed: {status_err}"}

            try:
                send_error = ws_manager.send({"op": "publish", "topic": topic, "msg": msg})
                if send_error:
                    return {"error": f"Failed to publish message: {send_error}"}

                status_err = _parse_status_error(ws_manager.receive(timeout=1.0))
                if status_err:
                    return {"error": f"Publish failed: {status_err}"}
            finally:
                ws_manager.send({"op": "unadvertise", "topic": topic})

        return {"success": True}
