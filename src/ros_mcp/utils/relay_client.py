"""Python client for the MCP relay (https://relay.site-mcp.com); the counterpart of relay-client.js.

Copy this file into an app the internet cannot reach. Three ways in:

    # an existing MCP server (FastMCP from the official SDK, or the fastmcp package); its
    # tools' ctx.elicit() asks the user in the client, through the relay:
    await serve_mcp(mcp, key=key, allow=["github-login"])

    # tools by hand:
    await serve(key=key, server={"name": "my-app", "version": "1"}, tools=[...],
                on_call=async_fn(name, args) -> CallToolResult dict, allow=[...])

    # or every JSON-RPC message by hand (passthrough), as relay-client.js's onRpc:
    await serve(key=key, server=..., tools=[...], on_rpc=async_fn(message, ctx) -> response or None)
    # where, while answering a request, await ctx.request(method, params) asks the client
    # something (elicitation/create) and returns its result, and await ctx.notify(method, params)
    # tells it something. Both reach a client that takes a stream; ctx is None for a notification.

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

RELAY = "https://relay.site-mcp.com"
PING_S = 20
MAX_BACKOFF_S = 30
# The relay keeps a stream open this long from the app's first question, so no answer comes later.
ASK_TIMEOUT_S = 10 * 60


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


class ClientError(Exception):
    """The client refused something the app asked it (ctx.request), or could not take it."""

    def __init__(self, message: str, code: Optional[int] = None):
        super().__init__(message)
        self.code = code


class _Context:
    """What a passthrough handler can send the client while relay frame `frame_id` is open."""

    def __init__(self, ws, frame_id: str, asked: dict):
        self._ws, self._frame_id, self._asked = ws, frame_id, asked

    async def request(self, method: str, params: Optional[dict] = None, timeout: float = ASK_TIMEOUT_S) -> dict:
        # Unguessable: the relay passes on an answer only to an id it saw asked, so a counter
        # would let anyone else at the door answer in the client's place.
        rid = f"app-{new_key()}"
        answer = asyncio.get_running_loop().create_future()
        self._asked[rid] = answer
        try:
            await self._push({"jsonrpc": "2.0", "id": rid, "method": method, **({"params": params} if params is not None else {})})
            message = await asyncio.wait_for(answer, timeout)
        finally:
            self._asked.pop(rid, None)
        if "error" in message:
            error = message["error"] or {}
            raise ClientError(error.get("message") or "The client refused.", error.get("code"))
        return message.get("result") or {}

    async def notify(self, method: str, params: Optional[dict] = None) -> None:
        try:
            await self._push({"jsonrpc": "2.0", "method": method, **({"params": params} if params is not None else {})})
        except Exception:
            pass

    async def _push(self, message: dict) -> None:
        await self._ws.send(json.dumps({"type": "push", "id": self._frame_id, "message": message}))


async def serve(*, key: str, server: dict, tools: list, on_call: Optional[Callable[[str, dict], Awaitable[dict]]] = None,
                on_rpc: Optional[Callable[[dict, Optional[_Context]], Awaitable[Optional[dict]]]] = None,
                allow: Optional[list] = None, instructions: Optional[str] = None, offline: Optional[str] = None,
                relay: str = RELAY, on_status: Callable[[str], Any] = _log) -> None:
    import websockets  # imported here so new_key/mcp_url work without it

    hello = json.dumps({"type": "hello", "server": server, "tools": tools, "instructions": instructions,
                        "offline": offline, "allow": allow, "passthrough": on_rpc is not None})
    url = relay.replace("http", "ws", 1) + f"/connect/{key}"
    backoff = 1
    while True:
        on_status("connecting")
        # The app's own requests to the client, by JSON-RPC id, until the client answers.
        asked: dict = {}
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
                        kind = frame.get("type")
                        message = frame.get("message") if kind == "rpc" else None
                        if kind == "ready":
                            backoff = 1
                            on_status("connected")
                        elif isinstance(message, dict) and "method" not in message and message.get("id") in asked:
                            answer = asked.pop(message["id"])
                            if not answer.done():
                                answer.set_result(message)
                        elif kind == "rpc" and on_rpc:
                            asyncio.create_task(_answer_rpc(ws, frame, on_rpc, asked))
                        elif kind == "call" and on_call:
                            asyncio.create_task(_answer(ws, frame, on_call))
                finally:
                    ping_task.cancel()
                    for answer in asked.values():
                        if not answer.done():
                            answer.set_exception(ClientError("The relay connection closed before the client answered."))
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


async def _answer_rpc(ws, frame: dict, on_rpc, asked: dict) -> None:
    message = frame.get("message") or {}
    ctx = _Context(ws, frame["id"], asked) if frame.get("id") else None
    try:
        reply = await on_rpc(message, ctx)
    except Exception as error:
        reply = ({"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32603, "message": str(error) or type(error).__name__}}
                 if message.get("id") is not None else None)
    if frame.get("id"):
        try:
            await ws.send(json.dumps({"type": "rpc", "id": frame["id"], "message": reply}))
        except Exception:
            pass


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
                    relay: str = RELAY, on_status: Callable[[str], Any] = _log,
                    ask_timeout: float = ASK_TIMEOUT_S) -> None:
    """Serve an existing FastMCP server through the relay, unchanged: every request reaches it
    over an in-memory MCP connection, so tools, prompts and resources behave as over stdio. A
    tool's ctx.elicit() goes to the client on that call's stream, and raises when the client
    cannot take it (it does not accept a stream) or does not answer within ask_timeout."""
    import anyio
    from mcp.shared.memory import create_client_server_memory_streams

    low = getattr(mcp, "_mcp_server", mcp)  # FastMCP (either package) wraps the low-level server
    async with create_client_server_memory_streams() as ((read, write), (server_read, server_write)):
        async with anyio.create_task_group() as tg:
            tg.start_soon(low.run, server_read, server_write, low.create_initialization_options())
            bridge = _Bridge(read, write, ask_timeout)
            tg.start_soon(bridge.route)
            init = await bridge.start()
            tools = (await bridge.call("tools/list", {})).get("result", {}).get("tools", [])
            info = {**(init.get("serverInfo") or {}), "name": name or getattr(mcp, "name", "mcp"), "version": version}
            bridge.info = {**init, "serverInfo": info, **({"instructions": instructions} if instructions else {})}
            await serve(key=key, server=info, tools=tools, on_rpc=bridge.on_rpc, allow=allow,
                        instructions=bridge.info.get("instructions"), offline=offline, relay=relay, on_status=on_status)
            tg.cancel_scope.cancel()


class _Bridge:
    """The relay's client side of an in-memory MCP connection to a server. Each forwarded request
    goes in under an id of the bridge's own (callers pick theirs, and two can both send 1), and a
    request the server sends back about it (elicitation/create, tagged with that id) goes out on
    the relay stream of the call that caused it."""

    PROTOCOL_VERSION = "2025-11-25"

    def __init__(self, read, write, ask_timeout: float):
        self._read, self._write, self._ask_timeout = read, write, ask_timeout
        self._next = 0
        self._answers: dict = {}  # bridge id -> future of the server's response
        self._calls: dict = {}    # bridge id -> (caller's id, relay context) while forwarded
        self.info: dict = {}

    async def start(self) -> dict:
        # Declares forms: whether this client can show one is known only per call, by trying.
        init = await self.call("initialize", {"protocolVersion": self.PROTOCOL_VERSION, "capabilities": {"elicitation": {"form": {}}},
                                              "clientInfo": {"name": "mcp-relay", "version": "1"}})
        await self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        if "error" in init:
            raise RuntimeError(f"The MCP server refused initialize: {init['error']}")
        return init["result"]

    async def call(self, method: str, params: dict, ctx: Optional[_Context] = None, caller_id: Any = None) -> dict:
        self._next += 1
        rid = f"relay-{self._next}"
        answer = asyncio.get_running_loop().create_future()
        self._answers[rid] = answer
        if ctx is not None:
            self._calls[rid] = (caller_id, ctx)
        try:
            await self._send({"jsonrpc": "2.0", "id": rid, "method": method, **({"params": params} if params is not None else {})})
            return await answer
        finally:
            self._answers.pop(rid, None)
            self._calls.pop(rid, None)

    async def on_rpc(self, message: dict, ctx: Optional[_Context]) -> Optional[dict]:
        method, mid, params = message.get("method"), message.get("id"), message.get("params")
        if mid is None:
            # A client's cancel names its own id; it is passed on only when one call has that id.
            if method == "notifications/cancelled" and isinstance(params, dict):
                ours = [rid for rid, (cid, _) in self._calls.items() if cid == params.get("requestId")]
                if len(ours) == 1:
                    await self._send({**message, "params": {**params, "requestId": ours[0]}})
            return None
        if method is None:
            return None
        def ok(result):
            return {"jsonrpc": "2.0", "id": mid, "result": result}

        # The 2026-07-28 revision (stateless, version in _meta) is not one this server speaks:
        # refused as the spec says, so the client falls back to initialize.
        requested = (params or {}).get("_meta", {}).get("io.modelcontextprotocol/protocolVersion") if isinstance(params, dict) else None
        if isinstance(requested, str):
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32022, "message": f"Unsupported protocol version: {requested}",
                                                           "data": {"supported": self._versions(), "requested": requested}}}
        if method == "initialize":
            asked = (params or {}).get("protocolVersion")
            return ok({**self.info, "protocolVersion": asked if asked in self._versions() else self.PROTOCOL_VERSION})
        if method == "ping":
            return ok({})
        answer = await self.call(method, params, ctx, mid)
        return {**answer, "id": mid}

    def _versions(self) -> list:
        try:
            from mcp.shared.version import SUPPORTED_PROTOCOL_VERSIONS
            return list(SUPPORTED_PROTOCOL_VERSIONS)
        except ImportError:
            return [self.PROTOCOL_VERSION]

    async def route(self) -> None:
        async for item in self._read:
            if isinstance(item, Exception):
                continue
            message = item.message.model_dump(by_alias=True, mode="json", exclude_none=True)
            related = getattr(item.metadata, "related_request_id", None)
            call = self._calls.get(str(related)) if related is not None else None
            if "method" not in message:
                answer = self._answers.get(str(message.get("id")))
                if answer and not answer.done():
                    answer.set_result(message)
            elif "id" in message:
                asyncio.create_task(self._ask(message, call[1] if call else None))
            elif call:
                asyncio.create_task(call[1].notify(message["method"], message.get("params")))

    async def _ask(self, message: dict, ctx: Optional[_Context]) -> None:
        mid = message["id"]
        try:
            if ctx is None:
                raise ClientError("There is no client request to ask this in.", -32601)
            reply = {"jsonrpc": "2.0", "id": mid, "result": await ctx.request(message["method"], message.get("params"), self._ask_timeout)}
        except ClientError as error:
            reply = {"jsonrpc": "2.0", "id": mid, "error": {"code": error.code or -32000, "message": str(error)}}
        except asyncio.TimeoutError:
            reply = {"jsonrpc": "2.0", "id": mid, "error": {"code": -32001, "message": "The client did not answer in time."}}
        await self._send(reply)

    async def _send(self, message: dict) -> None:
        import mcp.types as types
        from mcp.shared.message import SessionMessage

        await self._write.send(SessionMessage(types.JSONRPCMessage.model_validate(message)))
