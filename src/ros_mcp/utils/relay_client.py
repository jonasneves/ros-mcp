"""Python client for the MCP relay (https://relay.kandue.app); the counterpart of relay-client.js.

Copy this file into an app the internet cannot reach. Two ways in:

    # an existing MCP server (FastMCP from the official SDK, or the fastmcp package):
    await serve_mcp(mcp, key=key, allow=["github-login"])

    # or tools by hand:
    await serve(key=key, server={"name": "my-app", "version": "1"}, tools=[...],
                on_call=async_fn(name, args) -> CallToolResult dict, allow=[...])

Either runs until cancelled, reconnecting with backoff. `mcp_url(key, signed=True)` is the
address to add as a connector; with `allow`, only that address answers, after a GitHub
sign-in as one of those accounts. Needs `websockets` (and `mcp` for serve_mcp).
"""

import asyncio
import base64
import hashlib
import json
import os
import secrets
import sys
from typing import Any, Awaitable, Callable, Optional

RELAY = "https://relay.kandue.app"
PING_S = 20
MAX_BACKOFF_S = 30


def new_key() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")


def load_or_create_key(path) -> str:
    """The app's private key at `path`, created on first use. Created owner-only (0600) in
    the same call that makes the file, never chmod'ed after, so no other user can read it
    in between."""
    path = os.path.expanduser(str(path))
    try:
        with open(path) as f:
            key = f.read().strip()
        if key:
            return key
    except FileNotFoundError:
        pass
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    key = new_key()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(key + "\n")
    return key


def address_of(key: str) -> str:
    """The app's public address: a one-way hash of its key, as the relay computes it."""
    digest = hashlib.sha256(f"mcp-relay:{key}".encode()).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def mcp_url(key: str, signed: bool = False, relay: str = RELAY) -> str:
    """The connector URL. It carries address_of(key), never the key: whoever sees it can call
    the app but cannot connect as it."""
    return f"{relay}{'/s' if signed else ''}/mcp/{address_of(key)}"


def _log(msg: str) -> None:
    print(f"[relay] {msg}", file=sys.stderr, flush=True)


async def serve(*, key: str, server: dict, tools: list, on_call: Callable[[str, dict], Awaitable[dict]],
                allow: Optional[list] = None, instructions: Optional[str] = None, offline: Optional[str] = None,
                relay: str = RELAY, on_status: Callable[[str], Any] = _log) -> None:
    import websockets  # imported here so new_key/mcp_url work without it

    hello = json.dumps({"type": "hello", "server": server, "tools": tools, "instructions": instructions,
                        "offline": offline, "allow": allow})
    url = relay.replace("http", "ws", 1) + f"/connect/{key}"
    backoff = 1
    while True:
        on_status("connecting")
        try:
            async with websockets.connect(url, ping_interval=None, max_size=None) as ws:
                await ws.send(hello)

                async def pinger():
                    while True:
                        await asyncio.sleep(PING_S)
                        await ws.send("ping")

                ping_task = asyncio.create_task(pinger())
                try:
                    async for data in ws:
                        if data == "pong":
                            continue
                        frame = json.loads(data)
                        if frame.get("type") == "ready":
                            backoff = 1
                            on_status("connected")
                        elif frame.get("type") == "call":
                            asyncio.create_task(_answer(ws, frame, on_call))
                finally:
                    ping_task.cancel()
                code = ws.close_code
        except (OSError, Exception) as error:  # network errors and websockets' own
            code = getattr(error, "code", None) or getattr(getattr(error, "rcvd", None), "code", None)
        # 4000: another copy took the key; 4001: the relay refused the announcement. Either way
        # reconnecting would fight or repeat it.
        if code == 4000:
            on_status("replaced")
            return
        if code == 4001:
            on_status("rejected")
            return
        on_status("offline")
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, MAX_BACKOFF_S)


async def _answer(ws, frame: dict, on_call) -> None:
    try:
        reply = {"type": "result", "id": frame["id"], "result": await on_call(frame["name"], frame.get("arguments") or {})}
    except Exception as error:  # a failing tool answers with its message
        reply = {"type": "error", "id": frame["id"], "message": str(error) or type(error).__name__}
    try:
        await ws.send(json.dumps(reply))
    except Exception:
        pass


async def serve_mcp(mcp: Any, *, key: str, allow: Optional[list] = None, name: Optional[str] = None,
                    version: str = "1", instructions: Optional[str] = None, offline: Optional[str] = None,
                    relay: str = RELAY, on_status: Callable[[str], Any] = _log) -> None:
    """Serve an existing FastMCP server through the relay, unchanged: tools are listed and
    called over an in-memory MCP session to it, so they behave exactly as over stdio."""
    from mcp.shared.memory import create_connected_server_and_client_session

    low = getattr(mcp, "_mcp_server", mcp)  # FastMCP (either package) wraps the low-level server
    async with create_connected_server_and_client_session(low) as session:
        listed = await session.list_tools()
        tools = [t.model_dump(by_alias=True, exclude_none=True) for t in listed.tools]

        async def on_call(tool: str, args: dict) -> dict:
            result = await session.call_tool(tool, args)
            return result.model_dump(by_alias=True, exclude_none=True)

        await serve(key=key, server={"name": name or getattr(mcp, "name", "mcp"), "version": version}, tools=tools,
                    on_call=on_call, allow=allow, instructions=instructions, offline=offline, relay=relay,
                    on_status=on_status)
