"""Bounded JSON-RPC/MCP stdio adapter; service remains the effect authority.

No target code is executed here. Each admitted tool call has its own cancellation
Event. There is deliberately no executor submission queue.
"""
from __future__ import annotations

import contextlib
import json
import sys
import threading
import time

MAX_MESSAGE_BYTES = 1024 * 1024
MAX_WORKERS = 2
JOIN_SECONDS = 1.0
PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
TOOL_GROUPS = {
    "traceanchor_case": ("case.create", "case.get", "case.list", "case.revise", "case.close", "subtask.create", "subtask.result"),
    "traceanchor_source": ("source.add", "source.get", "source.refresh", "source.derive", "analyze", "version-diff"),
    "traceanchor_research": ("observability.set", "observe.http", "plan", "unknown.add", "unknown.resolve", "report"),
    "traceanchor_spec": ("spec.freeze", "spec.get", "compare", "verify"),
    "traceanchor_run": ("capture", "run.get", "run.list", "run.cancel", "run.reconcile"),
    "traceanchor_storage": ("storage.usage", "storage.register", "storage.preview", "storage.clean", "storage.promote", "storage.pin"),
    "traceanchor_exchange": ("export", "import"),
    "traceanchor_system": ("doctor",),
}


def tools():
    """Fresh catalog objects; callers cannot mutate the operation allowlists."""
    return [{"name": name, "description": "TraceAnchor service operations: " + ", ".join(ops),
             "inputSchema": {"type": "object", "properties": {
                 "operation": {"type": "string", "enum": list(ops)},
                 "arguments": {"type": "object"}},
                 "required": ["operation", "arguments"], "additionalProperties": False}}
            for name, ops in TOOL_GROUPS.items()]


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _loads(data):
    return json.loads(data, object_pairs_hook=_object,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError("non-finite JSON number")))


def _valid_id(value):
    return isinstance(value, (str, int)) and not isinstance(value, bool)


def _shape(value, required=(), optional=()):
    return (isinstance(value, dict) and set(required) <= value.keys()
            and not (value.keys() - set(required) - set(optional))
            and ("_meta" not in value or isinstance(value["_meta"], dict)))


def _dispatch(root, operation, arguments, *, cancel):
    from .service import dispatch
    return dispatch(root, operation, arguments, cancel=cancel)


def serve(root):
    """Serve newline-delimited UTF-8 MCP until EOF, cancelling active work.

    stdout is exclusively protocol output. Service diagnostics using print are
    redirected to stderr for the entire adapter lifetime, not per worker.
    """
    output = sys.stdout.buffer
    with contextlib.redirect_stdout(sys.stderr):
        return _serve(root, sys.stdin.buffer, output, _dispatch)


def _serve(root, incoming, outgoing, dispatcher, *, join_seconds=JOIN_SECONDS):
    """Stream/dispatcher injection is a protocol-test seam, not a second service."""
    lock = threading.RLock()
    active = {}
    closed = False
    state = "new"

    def emit(message):
        nonlocal closed
        with lock:
            if closed:
                return
            try:
                payload = json.dumps(message, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
                if len(payload) > MAX_MESSAGE_BYTES:
                    payload = json.dumps({"jsonrpc": "2.0", "id": message.get("id"), "error": {
                        "code": -32603, "message": "Response exceeds transport limit; use a bounded service query"}}, separators=(",", ":")).encode("utf-8")
                outgoing.write(payload + b"\n")
                outgoing.flush()
            except (BrokenPipeError, OSError):
                closed = True
                for event, _ in active.values():
                    event.set()

    def error(request_id, code, message):
        emit({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}})

    def result(request_id, value):
        emit({"jsonrpc": "2.0", "id": request_id, "result": value})

    def run(request_id, operation, arguments, cancel):
        try:
            try:
                value = dispatcher(root, operation, arguments, cancel=cancel)
                if cancel.is_set():
                    value = {"error": {"code": "cancelled", "message": "Request cancelled", "details": {}}}
                    failed = True
                else:
                    failed = False
                text = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
                response = {"content": [{"type": "text", "text": text}], "isError": failed}
            except Exception as exc:
                # Lazy import permits protocol testing before the core is present.
                from .core import TraceError
                if not isinstance(exc, TraceError):
                    error(request_id, -32603, "Internal service error")
                    return
                details = {"error": {"code": exc.code, "message": exc.message, "details": exc.details}}
                response = {"content": [{"type": "text", "text": json.dumps(details, ensure_ascii=False, allow_nan=False)}], "isError": True}
            result(request_id, response)
        except Exception:
            error(request_id, -32603, "Internal service error")
        finally:
            with lock:
                active.pop(request_id, None)

    try:
        while not closed:
            line = incoming.readline(MAX_MESSAGE_BYTES + 2)
            if not line:
                break
            if len(line) > MAX_MESSAGE_BYTES or not line.endswith(b"\n"):
                # Drain the complete oversized frame. Never parse its prefix or
                # mistake a suffix (including valid-looking JSON) for a message.
                while line and not line.endswith(b"\n"):
                    line = incoming.readline(MAX_MESSAGE_BYTES + 2)
                error(None, -32700, "Oversized or unterminated JSON message")
                continue
            try:
                message = _loads(line.decode("utf-8", errors="strict"))
            except (ValueError, UnicodeError, RecursionError):
                error(None, -32700, "Invalid JSON")
                continue
            if not _shape(message, ("jsonrpc", "method"), ("id", "params")) or message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
                error(None, -32600, "Invalid Request")
                continue
            request_id = message.get("id")
            notification = "id" not in message
            if not notification and not _valid_id(request_id):
                error(None, -32600, "Invalid request ID")
                continue
            method = message["method"]
            params = message.get("params", {})
            if notification:
                if method == "notifications/initialized" and state == "initializing" and _shape(params, (), ("_meta",)):
                    state = "ready"
                elif method == "notifications/cancelled" and _shape(params, ("requestId",), ("reason", "_meta")) and _valid_id(params["requestId"]) and ("reason" not in params or isinstance(params["reason"], str)):
                    with lock:
                        item = active.get(params["requestId"])
                        if item:
                            item[0].set()
                # JSON-RPC notifications never receive responses, even unknown ones.
                continue
            with lock:
                duplicate = request_id in active
            if duplicate:
                error(request_id, -32600, "Request ID is already active")
                continue
            if method == "initialize":
                if state != "new":
                    error(request_id, -32600, "Already initialized")
                elif not (_shape(params, ("protocolVersion", "capabilities", "clientInfo"), ("_meta",))
                          and isinstance(params["protocolVersion"], str)
                          and isinstance(params["capabilities"], dict)
                          and _shape(params["clientInfo"], ("name", "version"), ("title", "websiteUrl", "icons", "description"))
                          and isinstance(params["clientInfo"]["name"], str)
                          and isinstance(params["clientInfo"]["version"], str)):
                    error(request_id, -32602, "Invalid initialize params")
                else:
                    version = params["protocolVersion"]
                    state = "initializing"
                    result(request_id, {"protocolVersion": version if version in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                                        "capabilities": {"tools": {"listChanged": False}},
                                        "serverInfo": {"name": "traceanchor", "version": "0.1.0"}})
            elif method == "ping":
                if _shape(params, (), ("_meta",)):
                    result(request_id, {})
                else:
                    error(request_id, -32602, "Invalid ping params")
            elif method not in ("tools/list", "tools/call"):
                error(request_id, -32601, "Method not found")
            elif state != "ready":
                error(request_id, -32600, "Initialize and send notifications/initialized first")
            elif method == "tools/list":
                if _shape(params, (), ("_meta",)):
                    result(request_id, {"tools": tools()})
                else:
                    error(request_id, -32602, "Invalid tools/list params; pagination is not used")
            elif not _shape(params, ("name", "arguments"), ("_meta",)) or not isinstance(params["name"], str) or params["name"] not in TOOL_GROUPS:
                error(request_id, -32602, "Unknown tool or invalid tools/call params")
            else:
                args = params["arguments"]
                if not _shape(args, ("operation", "arguments")) or not isinstance(args["operation"], str) or args["operation"] not in TOOL_GROUPS[params["name"]] or not isinstance(args["arguments"], dict):
                    error(request_id, -32602, "Tool requires a group-allowed operation and arguments object only")
                    continue
                with lock:
                    if len(active) >= MAX_WORKERS:
                        error(request_id, -32001, "Server busy; at most two concurrent tool calls")
                        continue
                    cancel = threading.Event()
                    thread = threading.Thread(target=run, args=(request_id, args["operation"], args["arguments"], cancel), daemon=True)
                    active[request_id] = (cancel, thread)
                    try:
                        thread.start()
                    except (RuntimeError, OSError):
                        active.pop(request_id, None)
                        error(request_id, -32603, "Worker could not start")
    finally:
        with lock:
            remaining = list(active.values())
            for cancel, _ in remaining:
                cancel.set()
        deadline = time.monotonic() + max(0.0, join_seconds)
        for _, thread in remaining:
            thread.join(max(0.0, deadline - time.monotonic()))
        with lock:
            closed = True
    return 0
