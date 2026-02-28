import asyncio
import json
import time
import uuid

from fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations

from ros_mcp.utils.websocket import WebSocketManager, extract_service_failure_error

ACTION_TYPE_MAP = {
    "/turtle1/rotate_absolute": "turtlesim/action/RotateAbsolute",
}

ACTION_STATUS_MAP = {
    0: "STATUS_UNKNOWN",
    1: "STATUS_ACCEPTED",
    2: "STATUS_EXECUTING",
    3: "STATUS_CANCELING",
    4: "STATUS_SUCCEEDED",
    5: "STATUS_CANCELED",
    6: "STATUS_ABORTED",
}


def _parse_typedef(typedefs: list) -> dict:
    """Parse the first rosbridge typedef into fields/field_details/constants dict."""
    if not typedefs:
        return {}

    typedef = typedefs[0]
    field_names = typedef.get("fieldnames", [])
    field_types = typedef.get("fieldtypes", [])
    field_array_len = typedef.get("fieldarraylen", [])
    examples = typedef.get("examples", [])
    const_names = typedef.get("constnames", [])
    const_values = typedef.get("constvalues", [])

    fields = dict(zip(field_names, field_types))
    field_details = {
        name: {
            "type": ftype,
            "array_length": field_array_len[i] if i < len(field_array_len) else -1,
            "example": examples[i] if i < len(examples) else None,
        }
        for i, (name, ftype) in enumerate(zip(field_names, field_types))
    }

    return {
        "fields": fields,
        "field_count": len(fields),
        "field_details": field_details,
        "message_type": typedef.get("type", ""),
        "examples": examples,
        "constants": dict(zip(const_names, const_values)) if const_names else {},
    }


def _get_available_services(ws_manager: WebSocketManager) -> list | None:
    """Return the list of available rosbridge services, or None on error."""
    with ws_manager:
        response = ws_manager.request({
            "op": "call_service",
            "service": "/rosapi/services",
            "type": "rosapi/Services",
            "args": {},
            "id": "check_available_services",
        })
    if extract_service_failure_error(response):
        return None
    return response.get("values", {}).get("services", [])


def _check_required_services(
    ws_manager: WebSocketManager,
    required: list[str],
    feature_name: str,
    filter_keyword: str = "",
) -> tuple[list[str] | None, dict | None]:
    """Check that required rosbridge services are available.

    Returns (available_services, error_response).  When error_response is not
    None the caller should return it immediately.
    """
    available = _get_available_services(ws_manager)
    if available is None:
        return None, {
            "warning": "Cannot check service availability",
            "compatibility": {
                "issue": "Cannot determine available services",
                "required_services": required,
                "suggestion": "Ensure rosbridge is running and rosapi is available",
            },
        }

    missing = [svc for svc in required if svc not in available]
    if missing:
        return available, {
            "warning": f"{feature_name} not supported by this rosbridge/rosapi version",
            "compatibility": {
                "issue": f"Required {feature_name.lower()} services are not available",
                "missing_services": missing,
                "required_services": required,
                "available_services": (
                    [s for s in available if filter_keyword in s] if filter_keyword else []
                ),
                "suggestion": f"This rosbridge version doesn't support {feature_name.lower()} services",
            },
        }

    return available, None


def register_action_tools(
    mcp: FastMCP,
    ws_manager: WebSocketManager,
) -> None:
    @mcp.tool(
        description=(
            "Get list of all available ROS actions. Works only with ROS 2.\nExample:\nget_actions()"
        ),
        annotations=ToolAnnotations(
            title="Get Actions",
            readOnlyHint=True,
        ),
    )
    def get_actions() -> dict:
        _, err = _check_required_services(
            ws_manager, ["/rosapi/action_servers"], "Action listing", "action"
        )
        if err:
            return err

        message = {
            "op": "call_service",
            "service": "/rosapi/action_servers",
            "type": "rosapi/ActionServers",
            "args": {},
            "id": "get_actions_request_1",
        }

        with ws_manager:
            response = ws_manager.request(message)

        if err := extract_service_failure_error(response):
            return err

        if "values" in response:
            actions = response["values"].get("action_servers", [])
            return {"actions": actions, "action_count": len(actions)}

        return {"warning": "No actions found or /rosapi/action_servers service not available"}

    @mcp.tool(
        description=(
            "Get complete action details including type, goal, result, and feedback structures. Works only with ROS 2.\n"
            "Example:\nget_action_details('/turtle1/rotate_absolute')"
        ),
        annotations=ToolAnnotations(
            title="Get Action Details",
            readOnlyHint=True,
        ),
    )
    def get_action_details(action: str) -> dict:
        if not action or not action.strip():
            return {"error": "Action name cannot be empty"}

        available_services, err = _check_required_services(
            ws_manager, ["/rosapi/interfaces"], "Action type resolution", "interface"
        )
        if err:
            err["action"] = action
            return err

        action_type = ACTION_TYPE_MAP.get(action, "unknown")
        action_interfaces = []

        if action_type == "unknown":
            interfaces_message = {
                "op": "call_service",
                "service": "/rosapi/interfaces",
                "type": "rosapi/Interfaces",
                "args": {},
                "id": f"get_interfaces_for_action_{action.replace('/', '_')}",
            }

            with ws_manager:
                interfaces_response = ws_manager.request(interfaces_message)

            if "values" in interfaces_response:
                interfaces = interfaces_response["values"].get("interfaces", [])
                action_interfaces = [iface for iface in interfaces if "/action/" in iface]
                action_name_part = action.split("/")[-1]
                for iface in action_interfaces:
                    if action_name_part.lower() in iface.lower():
                        action_type = iface
                        break

        if action_type == "unknown":
            return {
                "error": f"Action type for {action} not found",
                "action": action,
                "available_action_types": action_interfaces,
                "suggestion": "This action might not be available or use a different naming pattern",
            }

        # Check that detail services are available before querying them
        detail_service_names = [
            "/rosapi/action_goal_details",
            "/rosapi/action_result_details",
            "/rosapi/action_feedback_details",
        ]
        missing = [svc for svc in detail_service_names if svc not in available_services]
        if missing:
            return {
                "action": action,
                "action_type": action_type,
                "goal": {},
                "result": {},
                "feedback": {},
                "compatibility": {
                    "issue": "Required action detail services are not available",
                    "missing_services": missing,
                    "required_services": detail_service_names,
                    "available_services": [s for s in available_services if "action" in s],
                    "note": "Action type found, but detailed structures are not available",
                },
            }

        result = {
            "action": action,
            "action_type": action_type,
            "goal": {},
            "result": {},
            "feedback": {},
        }

        detail_services = {
            "goal": ("action_goal_details", "ActionGoalDetails"),
            "result": ("action_result_details", "ActionResultDetails"),
            "feedback": ("action_feedback_details", "ActionFeedbackDetails"),
        }
        type_slug = action_type.replace("/", "_")

        for key, (service_suffix, type_suffix) in detail_services.items():
            detail_message = {
                "op": "call_service",
                "service": f"/rosapi/{service_suffix}",
                "type": f"rosapi_msgs/srv/{type_suffix}",
                "args": {"type": action_type},
                "id": f"get_{service_suffix}_{type_slug}",
            }

            detail_response = ws_manager.request(detail_message)
            if "values" in detail_response and "error" not in detail_response:
                typedefs = detail_response["values"].get("typedefs", [])
                if typedefs:
                    result[key] = _parse_typedef(typedefs)

        if not result["goal"] and not result["result"] and not result["feedback"]:
            return {
                "action": action,
                "action_type": action_type,
                "error": f"Action type {action_type} found but has no definition",
            }

        return result

    @mcp.tool(
        description=(
            "Get action status for a specific action name. Works only with ROS 2.\n"
            "Example:\nget_action_status('/fibonacci')"
        ),
        annotations=ToolAnnotations(
            title="Get Action Status",
            readOnlyHint=True,
        ),
    )
    def get_action_status(action_name: str) -> dict:
        if not action_name or not action_name.strip():
            return {"error": "Action name cannot be empty"}

        if not action_name.startswith("/"):
            action_name = f"/{action_name}"

        status_topic = f"{action_name}/_action/status"

        with ws_manager:
            send_error = ws_manager.send({
                "op": "subscribe",
                "topic": status_topic,
                "type": "action_msgs/msg/GoalStatusArray",
                "id": f"get_action_status_{action_name.replace('/', '_')}",
            })
            if send_error:
                return {
                    "action_name": action_name,
                    "success": False,
                    "error": f"Failed to subscribe to status topic: {send_error}",
                }

            response = ws_manager.receive(timeout=3.0)
            if not response:
                return {
                    "action_name": action_name,
                    "success": False,
                    "error": "No response from action status topic",
                }

            try:
                response_data = json.loads(response)
            except json.JSONDecodeError as e:
                return {"error": f"Failed to parse status response: {e}"}

            if response_data.get("op") == "status" and response_data.get("level") == "error":
                return {"error": f"Action status error: {response_data.get('msg', 'Unknown error')}"}

            status_list = response_data.get("msg", {}).get("status_list")
            if status_list is None:
                return {
                    "action_name": action_name,
                    "success": True,
                    "active_goals": [],
                    "goal_count": 0,
                    "note": f"No active goals found for action {action_name}",
                }

            active_goals = []
            for item in status_list:
                goal_info = item.get("goal_info", {})
                status = item.get("status", -1)
                stamp = goal_info.get("stamp", {})
                active_goals.append({
                    "goal_id": goal_info.get("goal_id", {}).get("uuid", "unknown"),
                    "status": status,
                    "status_text": ACTION_STATUS_MAP.get(status, "UNKNOWN"),
                    "timestamp": f"{stamp.get('sec', 0)}.{stamp.get('nanosec', 0)}",
                })

            ws_manager.send({"op": "unsubscribe", "topic": status_topic})

        return {
            "action_name": action_name,
            "success": True,
            "active_goals": active_goals,
            "goal_count": len(active_goals),
            "note": f"Found {len(active_goals)} active goal(s) for action {action_name}",
        }

    @mcp.tool(
        description=(
            "Send a goal to a ROS action server. Works only with ROS 2.\n"
            "Example:\nsend_action_goal('/turtle1/rotate_absolute', 'turtlesim/action/RotateAbsolute', {'theta': 1.57})"
        ),
        annotations=ToolAnnotations(
            title="Send Action Goal",
            destructiveHint=True,
        ),
    )
    async def send_action_goal(
        action_name: str,
        action_type: str,
        goal: dict,
        timeout: float = None,  # type: ignore[assignment]  # FastMCP doesn't support Optional[float]
        ctx: Context = None,  # type: ignore[assignment]  # FastMCP injects ctx at runtime
    ) -> dict:
        if not action_name or not action_name.strip():
            return {"error": "Action name cannot be empty"}
        if not action_type or not action_type.strip():
            return {"error": "Action type cannot be empty"}
        if not goal:
            return {"error": "Goal cannot be empty"}

        if timeout is None:
            timeout = ws_manager.default_timeout

        async def report_progress(progress: int, message: str) -> None:
            """Best-effort progress reporting via MCP context."""
            if ctx:
                try:
                    await ctx.report_progress(progress=progress, total=None, message=message)
                except Exception:
                    pass

        goal_id = f"goal_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"

        with ws_manager:
            send_error = ws_manager.send({
                "op": "send_action_goal",
                "id": goal_id,
                "action": action_name,
                "action_type": action_type,
                "args": goal,
                "feedback": True,
            })
            if send_error:
                return {
                    "action": action_name,
                    "action_type": action_type,
                    "success": False,
                    "error": f"Failed to send action goal: {send_error}",
                }

            start_time = time.time()
            last_feedback = None
            feedback_count = 0

            while time.time() - start_time < timeout:
                remaining = timeout - (time.time() - start_time)
                response = ws_manager.receive(remaining)

                if response:
                    try:
                        msg_data = json.loads(response)
                    except json.JSONDecodeError:
                        await asyncio.sleep(0.1)
                        continue

                    if msg_data.get("op") == "action_result":
                        await report_progress(
                            feedback_count,
                            f"Action completed (received {feedback_count} feedback messages)",
                        )
                        return {
                            "action": action_name,
                            "action_type": action_type,
                            "success": True,
                            "goal_id": goal_id,
                            "status": msg_data.get("status", "unknown"),
                            "result": msg_data.get("values", {}),
                        }

                    if msg_data.get("op") == "action_feedback":
                        feedback_count += 1
                        last_feedback = msg_data
                        feedback_values = msg_data.get("values", {})
                        await report_progress(
                            feedback_count,
                            f"Action feedback #{feedback_count}: {str(feedback_values)[:100]}...",
                        )

                await asyncio.sleep(0.1)

            if feedback_count > 0:
                await report_progress(
                    feedback_count,
                    f"Action timed out after {timeout}s ({feedback_count} feedback messages)",
                )

            result = {
                "action": action_name,
                "action_type": action_type,
                "success": False,
                "goal_id": goal_id,
                "error": f"Action timed out after {timeout} seconds",
            }

            if last_feedback:
                result["success"] = True
                result["last_feedback"] = last_feedback.get("values", {})
                result["note"] = "Action timed out, but partial progress was made"

            return result

    @mcp.tool(
        description=(
            "Cancel a specific action goal. Works only with ROS 2.\n"
            "Example:\ncancel_action_goal('/turtle1/rotate_absolute', 'goal_1758653551839_21acd486')"
        ),
        annotations=ToolAnnotations(
            title="Cancel Action Goal",
            destructiveHint=True,
        ),
    )
    def cancel_action_goal(action_name: str, goal_id: str) -> dict:
        if not action_name or not action_name.strip():
            return {"error": "Action name cannot be empty"}
        if not goal_id or not goal_id.strip():
            return {"error": "Goal ID cannot be empty"}

        with ws_manager:
            send_error = ws_manager.send({
                "op": "cancel_action_goal",
                "id": goal_id,
                "action": action_name,
                "feedback": True,
            })
            if send_error:
                return {
                    "action": action_name,
                    "goal_id": goal_id,
                    "success": False,
                    "error": f"Failed to send cancel request: {send_error}",
                }

        return {
            "action": action_name,
            "goal_id": goal_id,
            "success": True,
            "note": "Cancel request sent successfully. Action may still be executing.",
        }
