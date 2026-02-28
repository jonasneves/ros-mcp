from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ros_mcp.utils.websocket import WebSocketManager, extract_service_failure_error


def _get_response_data(response: dict) -> dict | None:
    """Extract result data from 'values' or 'result' key of a rosbridge response."""
    if "values" in response:
        return response["values"]
    return response.get("result")


def _is_empty_value(value: str) -> bool:
    """Check if a parameter value is effectively empty (handles '""' for non-existent params)."""
    return not value or not value.strip('"').strip("'")


def _safe_check_parameter_exists(
    name: str, ws_manager: WebSocketManager
) -> tuple[bool, str, dict | None]:
    """Check if a parameter exists via get_param (safe, unlike has_param which crashes rosapi_node).

    Returns (exists, reason, response).  The response is passed through when the
    parameter exists so the caller can avoid a redundant request.
    """
    message = {
        "op": "call_service",
        "service": "/rosapi/get_param",
        "type": "rosapi_msgs/srv/GetParam",
        "args": {"name": name},
        "id": f"check_param_exists_{name.replace('/', '_').replace(':', '_')}",
    }

    with ws_manager:
        response = ws_manager.request(message)

    if "error" in response:
        return False, response["error"], None

    result_data = _get_response_data(response)
    if isinstance(result_data, dict):
        value = result_data.get("value", "")
        if _is_empty_value(value):
            reason = result_data.get("reason", "Parameter does not exist")
            return False, reason, None
        return True, "", response
    if result_data:
        return True, "", response

    return False, "Unexpected response format", None


def _infer_param_type(param_value: str) -> str:
    """Infer a parameter type from its string value."""
    clean = param_value.strip('"')
    if clean.lower() in ("true", "false"):
        return "bool"
    if clean.lstrip("-").isdigit():
        return "int"
    try:
        float(clean)
        return "float" if "." in clean else "int"
    except ValueError:
        return "string"


def register_parameter_tools(
    mcp: FastMCP,
    ws_manager: WebSocketManager,
) -> None:
    @mcp.tool(
        description=(
            "Get a single ROS parameter value by name. Works only with ROS 2.\n"
            "Example:\nget_parameter('/turtlesim:background_b')"
        ),
        annotations=ToolAnnotations(
            title="Get Parameter",
            readOnlyHint=True,
        ),
    )
    def get_parameter(name: str) -> dict:
        if not name or not name.strip():
            return {"error": "Parameter name cannot be empty"}

        exists, reason, response = _safe_check_parameter_exists(name, ws_manager)
        if not exists:
            return {
                "name": name,
                "value": "",
                "successful": False,
                "reason": reason or f"Parameter {name} does not exist",
                "exists": False,
            }

        result_data = _get_response_data(response)
        if isinstance(result_data, dict):
            value = result_data.get("value", "")
            return {
                "name": name,
                "value": value,
                "successful": result_data.get("successful", False) or bool(value),
                "reason": result_data.get("reason", ""),
            }
        if result_data is not None:
            return {
                "name": name,
                "value": str(result_data),
                "successful": True,
                "reason": "",
            }

        return {"error": f"Failed to get parameter {name}: unexpected response format"}

    @mcp.tool(
        description=(
            "Set a single ROS parameter value. Works only with ROS 2.\n"
            "Example:\nset_parameter('/turtlesim:background_b', '255')"
        ),
        annotations=ToolAnnotations(
            title="Set Parameter",
            destructiveHint=True,
        ),
    )
    def set_parameter(name: str, value: str) -> dict:
        if not name or not name.strip():
            return {"error": "Parameter name cannot be empty"}

        message = {
            "op": "call_service",
            "service": "/rosapi/set_param",
            "type": "rosapi_msgs/srv/SetParam",
            "args": {"name": name, "value": value},
            "id": f"set_param_{name.replace('/', '_').replace(':', '_')}",
        }

        with ws_manager:
            response = ws_manager.request(message)

        if "error" in response:
            return {
                "name": name,
                "value": value,
                "successful": False,
                "reason": response["error"],
            }

        result_data = _get_response_data(response)
        if isinstance(result_data, dict):
            return {
                "name": name,
                "value": value,
                "successful": result_data.get("successful", True),
                "reason": result_data.get("reason", ""),
            }
        if result_data is not None:
            return {
                "name": name,
                "value": value,
                "successful": bool(result_data),
                "reason": "",
            }

        return {"error": f"Failed to set parameter {name}: unexpected response format"}

    @mcp.tool(
        description=(
            "Check if a ROS parameter exists. Works only with ROS 2.\n"
            "Example:\nhas_parameter('/turtlesim:background_b')"
        ),
        annotations=ToolAnnotations(
            title="Has Parameter",
            readOnlyHint=True,
        ),
    )
    def has_parameter(name: str) -> dict:
        if not name or not name.strip():
            return {"error": "Parameter name cannot be empty"}

        exists, reason, _ = _safe_check_parameter_exists(name, ws_manager)

        return {
            "name": name,
            "exists": exists,
            "successful": True,
            "reason": reason if not exists else "",
        }

    @mcp.tool(
        description=(
            "Delete a ROS parameter. Works only with ROS 2.\n"
            "Example:\ndelete_parameter('/turtlesim:background_b')"
        ),
        annotations=ToolAnnotations(
            title="Delete Parameter",
            destructiveHint=True,
        ),
    )
    def delete_parameter(name: str) -> dict:
        if not name or not name.strip():
            return {"error": "Parameter name cannot be empty"}

        exists, reason, _ = _safe_check_parameter_exists(name, ws_manager)
        if not exists:
            return {
                "name": name,
                "successful": False,
                "reason": reason or f"Parameter {name} does not exist",
                "exists": False,
            }

        message = {
            "op": "call_service",
            "service": "/rosapi/delete_param",
            "type": "rosapi_msgs/srv/DeleteParam",
            "args": {"name": name},
            "id": f"delete_param_{name.replace('/', '_').replace(':', '_')}",
        }

        with ws_manager:
            response = ws_manager.request(message)

        if "error" in response:
            return {
                "name": name,
                "successful": False,
                "reason": response["error"],
            }

        result_data = _get_response_data(response)
        if isinstance(result_data, dict):
            return {
                "name": name,
                "successful": result_data.get("successful", False),
                "reason": result_data.get("reason", ""),
            }
        if result_data:
            return {"name": name, "successful": bool(result_data), "reason": ""}

        return {"error": f"Failed to delete parameter {name}: unexpected response format"}

    @mcp.tool(
        description=(
            "Get list of all ROS parameter names for a specific node. Works only with ROS 2.\n"
            "Example:\nget_parameters('cam2image')\nget_parameters('/cam2image')"
        ),
        annotations=ToolAnnotations(
            title="Get Parameters",
            readOnlyHint=True,
        ),
    )
    def get_parameters(node_name: str) -> dict:
        if not node_name or not node_name.strip():
            return {"error": "Node name cannot be empty"}

        normalized_node = node_name.strip().rstrip("/")
        if not normalized_node.startswith("/"):
            normalized_node = f"/{normalized_node}"

        service_name = f"{normalized_node}/list_parameters"

        message = {
            "op": "call_service",
            "service": service_name,
            "type": "rcl_interfaces/srv/ListParameters",
            "args": {},
            "id": f"get_parameters_{normalized_node.replace('/', '_')}",
        }

        with ws_manager:
            response = ws_manager.request(message)

        if err := extract_service_failure_error(response):
            return err

        names = []
        result_data = _get_response_data(response)
        if isinstance(result_data, dict):
            result_obj = result_data.get("result", {})
            if isinstance(result_obj, dict):
                names = result_obj.get("names", [])
            else:
                names = result_data.get("names", [])

        formatted_names = [f"{normalized_node}:{name}" for name in names]

        return {
            "node": normalized_node,
            "parameters": formatted_names,
            "parameter_count": len(formatted_names),
        }

    @mcp.tool(
        description=(
            "Get comprehensive details about a specific ROS parameter including value, type, and metadata. "
            "Works only with ROS 2.\n"
            "Example:\n"
            "get_parameter_details('/turtlesim:background_r')"
        ),
        annotations=ToolAnnotations(
            title="Get Parameter Details",
            readOnlyHint=True,
        ),
    )
    def get_parameter_details(name: str) -> dict:
        if not name or not name.strip():
            return {"error": "Parameter name cannot be empty"}

        node_part, _, param_part = name.partition(":")
        if not param_part:
            node_part, param_part = "", name

        def _error_response(reason: str) -> dict:
            return {
                "name": name,
                "value": "",
                "type": "unknown",
                "exists": False,
                "description": "",
                "node": node_part,
                "parameter": param_part,
                "reason": reason,
            }

        exists, reason, value_response = _safe_check_parameter_exists(name, ws_manager)
        if not exists:
            return _error_response(reason or f"Parameter {name} does not exist")

        if value_response is None:
            value_message = {
                "op": "call_service",
                "service": "/rosapi/get_param",
                "type": "rosapi_msgs/srv/GetParam",
                "args": {"name": name},
                "id": f"get_param_details_{name.replace('/', '_').replace(':', '_')}",
            }

            with ws_manager:
                value_response = ws_manager.request(value_message)

        param_value = ""
        param_successful = False
        reason = ""

        value_data = _get_response_data(value_response)
        if isinstance(value_data, dict):
            param_value = value_data.get("value", "")
            param_successful = value_data.get("successful", False) or bool(param_value)
            reason = value_data.get("reason", "")
        elif value_data is not None:
            param_value = str(value_data)
            param_successful = bool(param_value)

        if not param_successful and not param_value:
            return _error_response(reason or f"Parameter {name} does not exist")

        type_message = {
            "op": "call_service",
            "service": "/rosapi/describe_parameters",
            "type": "rcl_interfaces/DescribeParameters",
            "args": {"names": [name]},
            "id": f"describe_param_details_{name.replace('/', '_').replace(':', '_')}",
        }

        with ws_manager:
            type_response = ws_manager.request(type_message)

        param_type = "unknown"
        param_description = ""

        type_data = _get_response_data(type_response)
        if isinstance(type_data, dict):
            descriptors = type_data.get("descriptors", [])
            if descriptors:
                descriptor = descriptors[0]
                param_type = descriptor.get("type", "unknown")
                param_description = descriptor.get("description", "")

        if param_type == "unknown" and param_value:
            param_type = _infer_param_type(param_value)

        return {
            "name": name,
            "value": param_value,
            "type": param_type,
            "exists": param_successful,
            "description": param_description,
            "node": node_part,
            "parameter": param_part,
        }
