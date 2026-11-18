"""Protocol isolation tests: real framing/threads, deliberately stubbed service.

These tests are not service end-to-end qualification.
"""
import io
import json
import threading
import time
import unittest
from traceanchor import mcp
from traceanchor.core import TraceError


def frame(value):
    return json.dumps(value, separators=(",", ":")).encode() + b"\n"


def request(method, id=1, params=None):
    value = {"jsonrpc": "2.0", "method": method, "id": id}
    if params is not None:
        value["params"] = params
    return value


def initialize(version="2025-11-25"):
    return request("initialize", 1, {"protocolVersion": version, "capabilities": {}, "clientInfo": {"name": "fixture", "version": "1"}})


def ready():
    return [initialize(), {"jsonrpc": "2.0", "method": "notifications/initialized"}]


def call(id=2, operation="doctor", group="traceanchor_system", arguments=None):
    return request("tools/call", id, {"name": group, "arguments": {"operation": operation, "arguments": {} if arguments is None else arguments}})


class ScriptedInput:
    def __init__(self, chunks):
        self.chunks = iter(chunks)

    def readline(self, limit):
        value = next(self.chunks, b"")
        if callable(value):
            value = value()
        if len(value) > limit:
            raise AssertionError("fixture exceeds stream limit")
        return value


class ProtocolTests(unittest.TestCase):
    def invoke(self, messages, dispatcher=None):
        output = io.BytesIO()
        mcp._serve("fixture-workspace", io.BytesIO(b"".join(frame(m) for m in messages)), output,
                   dispatcher or (lambda *a, **kw: {"status": "ok"}))
        return [json.loads(line) for line in output.getvalue().splitlines()]

    def test_initialize_negotiates_and_requires_initialized(self):
        out = self.invoke([initialize("future"), request("tools/list", 2), ready()[1], request("tools/list", 3)])
        from traceanchor import __version__
        self.assertEqual(out[0]["result"]["serverInfo"]["version"], __version__)
        self.assertEqual(out[0]["result"]["protocolVersion"], mcp.PROTOCOL_VERSIONS[0])
        self.assertEqual(out[1]["error"]["code"], -32600)
        self.assertEqual(len(out[2]["result"]["tools"]), len(mcp.TOOL_GROUPS))
        for version in mcp.PROTOCOL_VERSIONS:
            self.assertEqual(self.invoke([initialize(version)])[0]["result"]["protocolVersion"], version)

    def test_ping_unknown_and_notification_silence(self):
        out = self.invoke([request("ping"), request("missing", 2), {"jsonrpc": "2.0", "method": "missing"},
                           request("ping", 3, {"extra": 1})])
        self.assertEqual(len(out), 3)
        self.assertEqual(out[0]["result"], {})
        self.assertEqual(out[1]["error"]["code"], -32601)
        self.assertEqual(out[2]["error"]["code"], -32602)

    def test_group_allowlist_and_strict_envelope(self):
        bad = call(operation="storage.clean")
        extra = call(3)
        extra["params"]["arguments"]["surprise"] = True
        out = self.invoke(ready() + [bad, extra, call(4, arguments=[]), request("tools/call", 5, {"name": "foreign", "arguments": {}})])
        self.assertTrue(all("error" in value for value in out[1:3]))
        self.assertEqual(out[-1]["error"]["code"], -32602)
        schema = mcp.tools()[0]["inputSchema"]
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["required"], ["operation", "arguments"])

    def test_invalid_envelopes(self):
        out = self.invoke([[], {"jsonrpc": "2.0", "method": "ping", "id": True},
                           request("initialize", 3, {}), request("ping", None)])
        self.assertEqual([x["error"]["code"] for x in out], [-32600, -32600, -32602, -32600])

    def test_service_error_is_tool_error(self):
        done = threading.Event()
        def dispatch(root, op, args, cancel):
            done.set()
            raise TraceError("fixture.policy", "effect denied", {"effect": "execute"})
        output = io.BytesIO()
        stream = ScriptedInput([*(frame(m) for m in ready()), frame(call()), lambda: (done.wait(1) and b"")])
        mcp._serve("root", stream, output, dispatch)
        value = json.loads(output.getvalue().splitlines()[-1])
        self.assertTrue(value["result"]["isError"])
        self.assertEqual(json.loads(value["result"]["content"][0]["text"])["error"]["code"], "fixture.policy")
        self.assertNotIn("error", value)

    def test_success_dispatch_root_operation_and_arguments(self):
        seen = []
        def dispatch(root, operation, arguments, cancel):
            seen.append((root, operation, arguments, isinstance(cancel, threading.Event)))
            return {"meaning": 42}
        out = self.invoke(ready() + [call(arguments={"x": 1})], dispatch)
        self.assertEqual(seen, [("fixture-workspace", "doctor", {"x": 1}, True)])
        self.assertFalse(out[-1]["result"]["isError"])

    def test_unexpected_exception_is_rpc_internal_error(self):
        def dispatch(*a, **kw):
            raise RuntimeError("private-path-not-for-client")
        out = self.invoke(ready() + [call()], dispatch)
        self.assertEqual(out[-1]["error"]["code"], -32603)
        self.assertNotIn("private-path", str(out))

    def test_duplicate_keys_nonfinite_bad_utf8_and_unterminated(self):
        output = io.BytesIO()
        mcp._serve("root", io.BytesIO(b'{"a":1,"a":2}\n{"a":NaN}\n\xff\n{"jsonrpc":"2.0","method":"ping","id":1}'), output, lambda *a, **kw: {})
        values = [json.loads(x) for x in output.getvalue().splitlines()]
        self.assertEqual([v["error"]["code"] for v in values], [-32700] * 4)

    def test_oversized_frame_drained_not_parsed_as_suffix(self):
        output = io.BytesIO()
        huge = b"x" * (mcp.MAX_MESSAGE_BYTES + 20) + frame(request("ping", 99))
        mcp._serve("root", io.BytesIO(huge + frame(request("ping", 2))), output, lambda *a, **kw: {})
        values = [json.loads(x) for x in output.getvalue().splitlines()]
        self.assertEqual(len(values), 2)
        self.assertEqual(values[0]["error"]["code"], -32700)
        self.assertEqual(values[1]["id"], 2)

    def test_cancel_notification_and_eof(self):
        for explicit in (True, False):
            started, stopped = threading.Event(), threading.Event()
            def dispatch(root, op, args, cancel):
                started.set()
                if cancel.wait(1):
                    stopped.set()
                return {"status": "cancelled"}
            chunks = [*(frame(m) for m in ready()), frame(call())]
            def wait_started():
                self.assertTrue(started.wait(1))
                return frame({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 2}}) if explicit else b""
            chunks.append(wait_started)
            output = io.BytesIO()
            mcp._serve("root", ScriptedInput(chunks), output, dispatch)
            self.assertTrue(stopped.is_set())
            self.assertTrue(json.loads(output.getvalue().splitlines()[-1])["result"]["isError"])

    def test_two_workers_no_pending_queue_and_duplicate_id(self):
        entered = [threading.Event(), threading.Event()]
        calls = []
        def dispatch(root, op, args, cancel):
            index = len(calls)
            calls.append(op)
            entered[index].set()
            cancel.wait(1)
            return {}
        def wait_both():
            self.assertTrue(all(e.wait(1) for e in entered))
            return frame(call(4))
        output = io.BytesIO()
        chunks = [*(frame(m) for m in ready()), frame(call(2)), frame(call(3)), wait_both,
                  frame(call(2)), frame(request("ping", 5))]
        mcp._serve("root", ScriptedInput(chunks), output, dispatch)
        results = [json.loads(x) for x in output.getvalue().splitlines()]
        self.assertEqual(len(calls), 2)
        self.assertTrue(any(v.get("error", {}).get("code") == -32001 for v in results))
        self.assertTrue(any(v.get("error", {}).get("code") == -32600 for v in results))
        self.assertTrue(any(v.get("id") == 5 and v.get("result") == {} for v in results))

    def test_eof_join_is_bounded_and_late_output_suppressed(self):
        release, started = threading.Event(), threading.Event()
        def dispatch(*a, **kw):
            started.set()
            release.wait(2)
            return {}
        output = io.BytesIO()
        chunks = [*(frame(m) for m in ready()), frame(call()), lambda: (started.wait(1) and b"")]
        before = time.monotonic()
        mcp._serve("root", ScriptedInput(chunks), output, dispatch, join_seconds=.02)
        self.assertLess(time.monotonic() - before, .5)
        previous = output.getvalue()
        release.set()
        self.assertTrue(started.is_set())
        self.assertEqual(previous, output.getvalue())

    def test_worker_start_failure_and_metadata_validation(self):
        from unittest.mock import patch
        with patch.object(threading.Thread, "start", side_effect=RuntimeError("synthetic thread failure")):
            out = self.invoke(ready() + [call(), request("ping", 3)])
        self.assertEqual(out[1]["error"]["code"], -32603)
        self.assertEqual(out[2]["result"], {})
        out = self.invoke([request("ping", 1, {"_meta": []})])
        self.assertEqual(out[0]["error"]["code"], -32602)

    def test_response_size_limit(self):
        out = self.invoke(ready() + [call()], lambda *a, **kw: {"large": "x" * mcp.MAX_MESSAGE_BYTES})
        self.assertEqual(out[-1]["error"]["code"], -32603)


class ServiceIntegrationTests(unittest.TestCase):
    """Actual subprocess stdio + actual service/Store/managed synthetic runner."""
    def setUp(self):
        import queue
        import subprocess
        import sys
        import tempfile
        from pathlib import Path
        from traceanchor.core import Store
        self.temporary = tempfile.TemporaryDirectory(prefix="traceanchor-real-mcp-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "workspace"
        self.store = Store(self.root, create=True)
        self.output = queue.Queue()
        product = str(Path(__file__).resolve().parents[1])
        code = "import sys; sys.path.insert(0,sys.argv[1]); from traceanchor.mcp import serve; serve(sys.argv[2])"
        self.process = subprocess.Popen([sys.executable, "-I", "-B", "-c", code, product, str(self.root)],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        cwd=self.temporary.name)
        self.reader = threading.Thread(target=lambda: [self.output.put(line) for line in self.process.stdout], daemon=True)
        self.reader.start()
        self.addCleanup(self.stop)
        self.send(initialize())
        self.assertIn("result", self.receive())
        self.send(ready()[1])

    def send(self, message):
        self.process.stdin.write(frame(message))
        self.process.stdin.flush()

    def receive(self):
        return json.loads(self.output.get(timeout=12))

    def stop(self):
        import subprocess
        if self.process.stdin and not self.process.stdin.closed:
            self.process.stdin.close()
        try:
            self.process.wait(timeout=6)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=3)
        self.reader.join(timeout=1)
        self.process.stdout.close()
        self.process.stderr.close()

    def operation(self, id, group, operation, arguments=None):
        self.send(call(id, operation, group, arguments))
        answer = self.receive()
        self.assertEqual(answer["id"], id)
        return answer

    def value(self, answer):
        self.assertFalse(answer["result"]["isError"], answer)
        return json.loads(answer["result"]["content"][0]["text"])

    def test_real_initialize_catalog_case_and_service_error(self):
        self.send(request("tools/list", 2))
        catalog = self.receive()["result"]["tools"]
        doctor = self.value(self.operation(3, "traceanchor_system", "doctor"))
        advertised = {operation for tool in catalog for operation in tool["inputSchema"]["properties"]["operation"]["enum"]}
        self.assertEqual(advertised, set(doctor["operations"]))
        case = self.value(self.operation(4, "traceanchor_case", "case.create", {"objective": "Synthetic actual MCP case"}))
        self.assertEqual(self.store.get("case", case["id"])["data"]["objective"], "Synthetic actual MCP case")
        fetched = self.value(self.operation(5, "traceanchor_case", "case.get", {"case_id": case["id"]}))
        self.assertEqual(fetched["id"], case["id"])
        failure = self.operation(6, "traceanchor_case", "case.create", {})
        self.assertTrue(failure["result"]["isError"])
        self.assertEqual(json.loads(failure["result"]["content"][0]["text"])["error"]["code"], "invalid-input")
        self.send(request("unknown", 7))
        self.assertEqual(self.receive()["error"]["code"], -32601)
        self.send(call(8, "storage.clean"))
        self.assertEqual(self.receive()["error"]["code"], -32602)
        self.send(request("ping", 9))
        self.assertEqual(self.receive()["result"], {})

    def test_real_transport_bounds_and_case_effect_denial(self):
        self.process.stdin.write(b"x" * (mcp.MAX_MESSAGE_BYTES + 20) + b"\n")
        self.process.stdin.flush()
        self.assertEqual(self.receive()["error"]["code"], -32700)
        self.process.stdin.write(b'{"jsonrpc":"2.0","method":"ping","id":2,"id":3}\n')
        self.process.stdin.flush()
        self.assertEqual(self.receive()["error"]["code"], -32700)
        case = self.value(self.operation(4, "traceanchor_case", "case.create", {"objective": "Read-only effect negative control"}))
        denied = self.operation(5, "traceanchor_run", "capture", {"case_id": case["id"], "source_id": "not-opened"})
        self.assertTrue(denied["result"]["isError"])
        self.assertEqual(json.loads(denied["result"]["content"][0]["text"])["error"]["code"], "effect-not-granted")
        self.assertEqual(self.store.list("run", case["id"]), [])
        self.send(request("ping", 6))
        self.assertEqual(self.receive()["result"], {})

    def prepare_running_capture(self):
        from pathlib import Path
        case = self.value(self.operation(10, "traceanchor_case", "case.create", {
            "objective": "Observe cancellation of owned synthetic sleeper", "allowed_effects": ["read", "execute"]}))
        fixture = Path(self.temporary.name) / "synthetic_sleeper.py"
        fixture.write_bytes(b"import time\nprint('started', flush=True)\ntime.sleep(10)\n")
        source = self.value(self.operation(11, "traceanchor_source", "source.add", {
            "case_id": case["id"], "path": str(fixture), "role": "reference"}))
        self.send(call(12, "capture", "traceanchor_run", {"case_id": case["id"], "source_id": source["id"],
                  "fixture": {"id": "sleeper", "timeout": 5, "idle_timeout": 5}}))
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            runs = self.store.list("run", case["id"])
            if runs and runs[-1]["data"]["status"] == "running":
                return case["id"], runs[-1]["id"]
            threading.Event().wait(.01)
        self.fail("Actual service did not reach owned running state")

    def test_real_notification_cancel_managed_capture(self):
        _, run_id = self.prepare_running_capture()
        self.send({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 12}})
        answer = self.receive()
        self.assertEqual(answer["id"], 12)
        self.assertTrue(answer["result"]["isError"])
        run = self.store.get("run", run_id)
        self.assertEqual(run["data"]["status"], "cancelled")
        self.assertEqual(run["data"]["cleanup"]["state"], "complete")

    def test_real_eof_cancels_managed_capture(self):
        _, run_id = self.prepare_running_capture()
        self.process.stdin.close()
        self.process.wait(timeout=6)
        self.assertEqual(self.process.returncode, 0)
        run = self.store.get("run", run_id)
        self.assertEqual(run["data"]["status"], "cancelled")
        self.assertEqual(run["data"]["cleanup"]["state"], "complete")


if __name__ == "__main__":
    unittest.main()
