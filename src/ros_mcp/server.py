import argparse
import os
import sys

import uvicorn
from fastmcp import FastMCP
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware

from ros_mcp.tools import register_all_tools
from ros_mcp.utils.websocket import WebSocketManager

_CORS_MIDDLEWARE = [
    Middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
]


def init_server(mcp: FastMCP) -> None:
    """Wire up the WebSocket manager and register all ROS tools."""
    rosbridge_ip = os.getenv("ROSBRIDGE_IP", "127.0.0.1")
    rosbridge_port = int(os.getenv("ROSBRIDGE_PORT", "9090"))
    default_timeout = float(os.getenv("ROS_DEFAULT_TIMEOUT", "5.0"))

    ws_manager = WebSocketManager(rosbridge_ip, rosbridge_port, default_timeout=default_timeout)
    register_all_tools(mcp, ws_manager, rosbridge_ip=rosbridge_ip, rosbridge_port=rosbridge_port)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="ROS MCP Server - Connect to ROS robots via MCP protocol"
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "http", "streamable-http"],
        default="stdio",
        help="MCP transport protocol to use (default: stdio)",
    )
    parser.add_argument(
        "--host", default="127.0.0.1", help="Host for HTTP transports (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--port", type=int, default=9000, help="Port for HTTP transports (default: 9000)"
    )
    return parser


def main() -> None:
    args = _build_arg_parser().parse_args()

    mcp = FastMCP("ros-mcp")
    init_server(mcp)

    if args.transport == "stdio":
        mcp.run(transport="stdio")
        return

    print(f"Transport: {args.transport} -> http://{args.host}:{args.port}", file=sys.stderr)

    if args.transport == "streamable-http":
        app = mcp.streamable_http_app(middleware=_CORS_MIDDLEWARE)
    else:
        app = mcp.http_app(middleware=_CORS_MIDDLEWARE)

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
