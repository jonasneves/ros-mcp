from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ros_mcp.utils.websocket import WebSocketManager, extract_service_failure_error


def register_node_tools(
    mcp: FastMCP,
    ws_manager: WebSocketManager,
) -> None:
    @mcp.tool(
        description=("Get list of all currently running ROS nodes.\nExample:\nget_nodes()"),
        annotations=ToolAnnotations(
            title="Get Nodes",
            readOnlyHint=True,
        ),
    )
    def get_nodes() -> dict:
        message = {
            "op": "call_service",
            "service": "/rosapi/nodes",
            "type": "rosapi/Nodes",
            "args": {},
            "id": "get_nodes_request_1",
        }

        with ws_manager:
            response = ws_manager.request(message)

        if err := extract_service_failure_error(response):
            return err

        if "values" in response:
            nodes = response["values"].get("nodes", [])
            return {"nodes": nodes, "node_count": len(nodes)}

        return {"warning": "No nodes found"}

    @mcp.tool(
        description=(
            "Detect connected robots by finding active cmd_vel topics on the ROS network.\n"
            "Works with any robot — no hardcoded names.\n"
            "Returns the cmd_vel topic and message type for each robot, ready to pass "
            "directly to move_by_distance / turn_by_angle / move_robots.\n"
            "Call this when you need to discover robot topics before issuing motion commands.\n"
            "Example:\nget_connected_robots()"
        ),
        annotations=ToolAnnotations(
            title="Get Connected Robots",
            readOnlyHint=True,
        ),
    )
    def get_connected_robots() -> dict:
        with ws_manager:
            response = ws_manager.request({
                "op": "call_service",
                "service": "/rosapi/topics",
                "type": "rosapi/Topics",
                "args": {},
                "id": "get_robots_topics",
            })

        if err := extract_service_failure_error(response):
            return err

        values = response.get("values", {})
        topics = values.get("topics", [])
        types = values.get("types", [])

        robots = [
            {"cmd_vel_topic": t, "cmd_vel_type": ty}
            for t, ty in zip(topics, types)
            if t == "/cmd_vel" or t.endswith("/cmd_vel")
        ]
        return {"robots": robots, "count": len(robots)}

    @mcp.tool(
        description=(
            "Get detailed information about a specific node including its publishers, subscribers, and services.\n"
            "Example:\n"
            "get_node_details('/turtlesim')"
        ),
        annotations=ToolAnnotations(
            title="Get Node Details",
            readOnlyHint=True,
        ),
    )
    def get_node_details(node: str) -> dict:
        if not node or not node.strip():
            return {"error": "Node name cannot be empty"}

        message = {
            "op": "call_service",
            "service": "/rosapi/node_details",
            "type": "rosapi/NodeDetails",
            "args": {"node": node},
            "id": f"get_node_details_{node.replace('/', '_')}",
        }

        with ws_manager:
            response = ws_manager.request(message)

        if err := extract_service_failure_error(response):
            return err

        values = response.get("values", {})
        publishers = values.get("publishing", [])
        subscribers = values.get("subscribing", [])
        services = values.get("services", [])

        if not publishers and not subscribers and not services:
            return {"error": f"Node {node} not found or has no details available"}

        return {
            "node": node,
            "publishers": publishers,
            "subscribers": subscribers,
            "services": services,
            "publisher_count": len(publishers),
            "subscriber_count": len(subscribers),
            "service_count": len(services),
        }
