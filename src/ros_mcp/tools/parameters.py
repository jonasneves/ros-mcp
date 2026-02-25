from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ros_mcp.utils.websocket import WebSocketManager


def _get_response_data(response: dict | None) -> dict | None:
    """Extract result data from 'values' or 'result' key of a rosbridge response."""
    if not response:
        return None
    if "values" in response:
        return response["values"]
    return response.get("result")


def _is_empty_value(value: str) -> bool:
    """Check if a parameter value is effectively empty (handles '""' for non-existent params)."""
    if not value:
        return True
    stripped = value.strip('"').strip("'")
    return not stripped


def _safe_check_parameter_exists(
    name: str, ws_manager: WebSocketManager
) -> tuple[bool, str, dict | None]:
    """
    Safely check if a parameter exists using get_param (which doesn't crash rosapi_node).
    Also returns the full response if the parameter exists, to avoid redundant calls.

    Returns:
        tuple: (exists: bool, reason: str, response: dict | None)
    """
    message = {
        "op": "call_service",
        "service": "/rosapi/get_param",
        "type": "rosapi_msgs/srv/GetParam",
        "args": {"name": name},
        "id": f"check_param_exists_{name.replace('/', '_').replace(':', '_')}",
    }

    try:
        with ws_manager:
            response = ws_manager.request(message)

        if not response:
            return False, "No response from service", None

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
    except Exception as e:
        return False, f"Error checking parameter: {str(e)}", None


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

        # get_param is safe (unlike has_param which crashes rosapi_node).
        exists, reason, response = _safe_check_parameter_exists(name, ws_manager)
        if not exists:
            return {
                "name": name,
                "value": "",
                "successful": False,
                "reason": reason or f"Parameter {name} does not exist",
                "exists": False,
            }

        if isinstance(response, str):
            return {
                "name": name,
                "value": "",
                "successful": False,
                "reason": f"Unexpected response format: {response}",
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

        try:
            with ws_manager:
                response = ws_manager.request(message)
        except Exception as e:
            return {
                "name": name,
                "value": value,
                "successful": False,
                "reason": f"Error setting parameter: {str(e)}",
            }

        if isinstance(response, str):
            return {
                "name": name,
                "value": value,
                "successful": False,
                "reason": f"Unexpected response format: {response}",
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

        # /rosapi/has_param crashes rosapi_node for non-existent params; use get_param instead
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

        try:
            with ws_manager:
                response = ws_manager.request(message)
        except Exception as e:
            return {
                "name": name,
                "successful": False,
                "reason": f"Error deleting parameter: {str(e)}",
            }

        if isinstance(response, str):
            return {
                "name": name,
                "successful": False,
                "reason": f"Unexpected response format: {response}",
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

        normalized_node = node_name.strip()
        if not normalized_node.startswith("/"):
            normalized_node = f"/{normalized_node}"
        if normalized_node.endswith("/") and len(normalized_node) > 1:
            normalized_node = normalized_node[:-1]

        service_name = f"{normalized_node}/list_parameters"

        message = {
            "op": "call_service",
            "service": service_name,
            "type": "rcl_interfaces/srv/ListParameters",
            "args": {},
            "id": f"get_parameters_{normalized_node.replace('/', '_')}",
        }

        try:
            with ws_manager:
                response = ws_manager.request(message)
        except Exception as e:
            return {"error": f"Failed to get parameters for node {normalized_node}: {str(e)}"}

        if isinstance(response, str):
            return {
                "error": f"Failed to get parameters for node {normalized_node}: Unexpected response format: {response}"
            }

        if not response:
            return {
                "error": f"Failed to get parameters for node {normalized_node}: No response or timeout from rosbridge"
            }

        if isinstance(response, dict) and "error" in response:
            error_msg = response.get("error", "Service call failed")
            return {"error": f"Failed to get parameters for node {normalized_node}: {error_msg}"}

        if response and "result" in response and not response["result"]:
            error_msg = response.get("values", {}).get("message", "Service call failed")
            return {"error": f"Failed to get parameters for node {normalized_node}: {error_msg}"}

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

        def _error_response(reason: str) -> dict:
            return {
                "name": name,
                "value": "",
                "type": "unknown",
                "exists": False,
                "description": "",
                "node": name.split(":")[0] if ":" in name else "",
                "parameter": name.split(":")[1] if ":" in name else name,
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

            try:
                with ws_manager:
                    value_response = ws_manager.request(value_message)
            except Exception as e:
                return _error_response(f"Error getting parameter details: {str(e)}")

        if isinstance(value_response, str):
            return _error_response(f"Unexpected response format: {value_response}")

        if not value_response:
            return _error_response("No response from service")

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

        try:
            with ws_manager:
                type_response = ws_manager.request(type_message)
        except Exception:
            type_response = None  # describe_parameters is optional; fall back to type inference

        param_type = "unknown"
        param_description = ""

        if isinstance(type_response, dict):
            type_data = _get_response_data(type_response)
            if isinstance(type_data, dict):
                descriptors = type_data.get("descriptors", [])
                if descriptors:
                    descriptor = descriptors[0]
                    param_type = descriptor.get("type", "unknown")
                    param_description = descriptor.get("description", "")

        if param_type == "unknown" and param_value:
            clean_value = param_value.strip('"')
            if clean_value.lower() in ("true", "false"):
                param_type = "bool"
            elif clean_value.isdigit() or (
                clean_value.startswith("-") and clean_value[1:].isdigit()
            ):
                param_type = "int"
            elif "." in clean_value and clean_value.replace(".", "").replace("-", "").isdigit():
                param_type = "float"
            else:
                param_type = "string"

        return {
            "name": name,
            "value": param_value,
            "type": param_type,
            "exists": param_successful,
            "description": param_description,
            "node": name.split(":")[0] if ":" in name else "",
            "parameter": name.split(":")[1] if ":" in name else name,
        }
