from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ros_mcp.utils.websocket import (
    WebSocketManager,
    extract_provider_node,
    extract_service_failure_error,
)


def _parse_typedef_fields(typedefs: list) -> dict:
    """Parse the first rosbridge typedef into a fields summary dict."""
    if not typedefs:
        return {}
    typedef = typedefs[0]
    field_names = typedef.get("fieldnames", [])
    field_types = typedef.get("fieldtypes", [])
    fields = dict(zip(field_names, field_types))
    return {"fields": fields, "field_count": len(fields)}


def register_service_tools(
    mcp: FastMCP,
    ws_manager: WebSocketManager,
) -> None:
    @mcp.tool(
        description=("Get list of all available ROS services.\nExample:\nget_services()"),
        annotations=ToolAnnotations(
            title="Get Services",
            readOnlyHint=True,
        ),
    )
    def get_services() -> dict:
        message = {
            "op": "call_service",
            "service": "/rosapi/services",
            "type": "rosapi_msgs/srv/Services",
            "args": {},
            "id": "get_services_request_1",
        }

        with ws_manager:
            response = ws_manager.request(message)

        if err := extract_service_failure_error(response):
            return err

        if "values" in response:
            services = response["values"].get("services", [])
            return {"services": services, "service_count": len(services)}

        return {"warning": "No services found"}

    @mcp.tool(
        description=(
            "Get the service type for a specific service.\nExample:\nget_service_type('/rosapi/topics')"
        ),
        annotations=ToolAnnotations(
            title="Get Service Type",
            readOnlyHint=True,
        ),
    )
    def get_service_type(service: str) -> dict:
        if not service or not service.strip():
            return {"error": "Service name cannot be empty"}

        message = {
            "op": "call_service",
            "service": "/rosapi/service_type",
            "type": "rosapi_msgs/srv/ServiceType",
            "args": {"service": service},
            "id": f"get_service_type_request_{service.replace('/', '_')}",
        }

        with ws_manager:
            response = ws_manager.request(message)

        if err := extract_service_failure_error(response):
            return err

        if "values" in response:
            service_type = response["values"].get("type", "")
            if service_type:
                return {"service": service, "type": service_type}
            return {"error": f"Service {service} does not exist or has no type"}

        return {"error": f"Failed to get type for service {service}"}

    @mcp.tool(
        description=(
            "Get complete service details including request/response structures and provider nodes.\n"
            "Example:\n"
            "get_service_details('/rosapi/topics')"
        ),
        annotations=ToolAnnotations(
            title="Get Service Details",
            readOnlyHint=True,
        ),
    )
    def get_service_details(service: str) -> dict:
        if not service or not service.strip():
            return {"error": "Service name cannot be empty"}

        result = {
            "service": service,
            "type": "",
            "request": {},
            "response": {},
            "providers": [],
        }

        with ws_manager:
            type_resp = ws_manager.request({
                "op": "call_service",
                "service": "/rosapi/service_type",
                "type": "rosapi_msgs/srv/ServiceType",
                "args": {"service": service},
                "id": f"get_service_type_{service.replace('/', '_')}",
            })
            service_type = type_resp.get("values", {}).get("type", "")
            if not service_type:
                return {"error": f"Service {service} does not exist or has no type"}
            result["type"] = service_type

            type_slug = service_type.replace("/", "_")

            for direction in ("request", "response"):
                detail_resp = ws_manager.request({
                    "op": "call_service",
                    "service": f"/rosapi/service_{direction}_details",
                    "type": f"rosapi_msgs/srv/Service{direction.capitalize()}Details",
                    "args": {"type": service_type},
                    "id": f"get_service_details_{direction}_{type_slug}",
                })
                typedefs = detail_resp.get("values", {}).get("typedefs", [])
                if typedefs:
                    result[direction] = _parse_typedef_fields(typedefs)

            provider_resp = ws_manager.request({
                "op": "call_service",
                "service": "/rosapi/service_node",
                "type": "rosapi_msgs/srv/ServiceNode",
                "args": {"service": service},
                "id": f"get_service_providers_{service.replace('/', '_')}",
            })
            node = extract_provider_node(provider_resp)
            result["providers"] = [node] if node else []
            result["provider_count"] = len(result["providers"])

        if not result["request"] and not result["response"]:
            return {"error": f"Service {service} not found or has no definition"}

        result["note"] = (
            "Field names shown above are formatted for rosbridge (leading underscores removed). "
            "Use these exact field names when calling call_service()."
        )

        return result

    @mcp.tool(
        description=(
            "Call a ROS service with specified request data.\n"
            "Example:\n"
            "call_service('/rosapi/topics', 'rosapi/Topics', {})\n"
            "call_service('/slow_service', 'my_package/SlowService', {}, timeout=10.0)  # Specify timeout only for slow services\n"
            "\n"
            "IMPORTANT: Field names in the request dict should match the field names shown by get_service_details(), "
            "which are already formatted for rosbridge (without leading underscores). "
            "For example, use {'topic': '/image'} not {'_topic': '/image'}."
        ),
        annotations=ToolAnnotations(
            title="Call Service",
            destructiveHint=True,
        ),
    )
    def call_service(
        service_name: str,
        service_type: str,
        request: dict,
        timeout: float = None,  # type: ignore[assignment]  # FastMCP doesn't support Optional[float]
    ) -> dict:
        if timeout is None:
            timeout = ws_manager.default_timeout

        message = {
            "op": "call_service",
            "service": service_name,
            "type": service_type,
            "args": request,
            "id": f"call_service_request_{service_name.replace('/', '_')}",
        }

        with ws_manager:
            response = ws_manager.request(message, timeout=timeout)

        if err := extract_service_failure_error(response):
            return {"service": service_name, "service_type": service_type, "success": False, **err}

        if response.get("op") == "service_response":
            return {
                "service": service_name,
                "service_type": service_type,
                "success": response.get("result", True),
                "result": response.get("values", {}),
            }

        if response.get("op") == "status" and response.get("level") == "error":
            return {
                "service": service_name,
                "service_type": service_type,
                "success": False,
                "error": response.get("msg", "Unknown error"),
            }

        return {
            "service": service_name,
            "service_type": service_type,
            "success": False,
            "error": "Unexpected response format",
            "raw_response": response,
        }
