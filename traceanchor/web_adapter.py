"""Finite Node inspector observations, not browser/DOM qualification.

The caller owns admission, execution, source identity and storage. This module
only uses the supplied execute function; it never starts a process or opens a
network connection itself. Targets explicitly implement the fixture protocol.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from .core import TraceError, canonical, child_path, no_links, parse_json, read_regular

MAX_SOURCE_BYTES = 1024 * 1024
MAX_TRACE_BYTES = 4 * 1024 * 1024
HELPER = Path(__file__).with_name("resources") / "inspect_web.cjs"


def _scenario(value):
    if not isinstance(value, dict) or set(value) - {"steps"}:
        raise TraceError("web-scenario", "Scenario accepts a steps array only")
    steps = value.get("steps")
    if not isinstance(steps, list) or not 1 <= len(steps) <= 12:
        raise TraceError("web-scenario", "Scenario requires 1-12 finite interaction steps")
    seen = set()
    for step in steps:
        if not isinstance(step, dict) or set(step) != {"id", "action"}:
            raise TraceError("web-scenario", "Each step requires id and action only")
        identity = step["id"]
        if not isinstance(identity, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", identity) or identity in seen:
            raise TraceError("web-scenario", "Step IDs must be unique bounded identifiers")
        seen.add(identity)
        if not isinstance(step["action"], dict):
            raise TraceError("web-scenario", "Interaction action must be a JSON object")
    if len(canonical(value).encode("utf-8")) > 64 * 1024:
        raise TraceError("web-scenario", "Scenario exceeds 64 KiB")
    return value


def _write(directory, name, raw):
    path = child_path(directory, name)
    # One output directory per invocation; never overwrite another run's evidence.
    with path.open("xb") as stream:
        stream.write(raw)
    return {"path": name, "relative_path": name, "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}


def observe(target: Path, directory: Path, execute, *, node: str | None, scenario: dict) -> dict:
    """Observe an admitted self-created JS module through a managed executor.

    Protocol: exports createSession({request, baseUrl}) and createService();
    session.dispatch(action) and session.snapshot(), service.handle(request) and
    service.snapshot(). The helper starts a finite loopback JSON HTTP service and
    records actual inspector/function/state/network observations. No arbitrary
    expression, shell command or URL is accepted in the scenario.
    """
    scenario = _scenario(scenario)
    target = no_links(target)
    directory = no_links(directory)
    if not directory.is_dir():
        raise TraceError("web-directory", "Caller must create and register the owned output directory")
    if target.suffix.lower() not in {".mjs", ".js", ".cjs"}:
        raise TraceError("web-target", "Node runtime fixture requires a JS module")
    source = read_regular(target, MAX_SOURCE_BYTES)
    source_sha = hashlib.sha256(source).hexdigest()
    limits = [
        "Node JavaScript runtime only; browser DOM, rendering, extension and device runtimes are unqualified.",
        "Only the finite steps and instrumented loopback requests are observed; no global behavior equivalence.",
        "The fixture request wrapper is loopback-only; target imports or direct I/O are not an OS sandbox.",
        "Source dependency closure and ambient Node dependencies are not sealed by this adapter.",
    ]
    result = {"schema_version": 1, "capability": "web.runtime.node-inspector", "status": "blocked",
              "facts": [], "artifacts": [], "limitations": limits, "unknowns": [],
              "source_sha256": source_sha,
              "qualification": {"javascript_runtime": "pending", "browser_dom": "unqualified",
                                "extension_runtime": "unqualified", "manifest_static": "separate-capability"}}
    if not isinstance(node, str) or not node.strip():
        result["unknowns"].append({"question": "Node inspector availability", "reason": "Explicit Node executable required; no installation attempted"})
        return result
    helper = read_regular(HELPER, 256 * 1024)
    request = canonical({"target": str(target), "scenario": scenario}).encode("utf-8")
    run = execute([node, "--unhandled-rejections=strict", str(HELPER)], input_bytes=request)
    raw_out, raw_err = run.get("stdout", b""), run.get("stderr", b"")
    if isinstance(raw_out, str):
        raw_out = raw_out.encode("utf-8")
    if isinstance(raw_err, str):
        raw_err = raw_err.encode("utf-8")
    if not isinstance(raw_out, bytes) or not isinstance(raw_err, bytes):
        raise TraceError("web-executor", "Executor must return raw stdout/stderr bytes")
    for name, raw in (("node.stdout.bin", raw_out), ("node.stderr.bin", raw_err)):
        result["artifacts"].append(_write(directory, name, raw))
    outcome = {k: v for k, v in run.items() if k not in {"stdout", "stderr"}}
    # Preserve the managed process outcome even when no JSON can be decoded.
    # Otherwise a startup failure/cancellation/timeout is obscured as parsing.
    result["execution"] = outcome
    result["artifacts"].append(_write(directory, "node-run.json", canonical(outcome).encode("utf-8")))
    result["tool"] = {"name": "node", "executable": node, "helper_sha256": hashlib.sha256(helper).hexdigest()}
    quality = (run.get("status") in {"succeeded", "completed"} and run.get("exit_code") == 0
               and run.get("cleanup", {}).get("state") == "complete"
               and not run.get("output_truncated") and not run.get("error"))
    if len(raw_out) > MAX_TRACE_BYTES:
        result["unknowns"].append({"question": "Runtime observation", "reason": "Helper output exceeded trace budget"})
        return result
    try:
        trace = parse_json(raw_out)
    except TraceError as exc:
        result["unknowns"].append({"question": "Runtime observation", "reason": exc.code,
                                   "process_status": run.get("status"), "exit_code": run.get("exit_code"),
                                   "cleanup": run.get("cleanup"), "process_error": run.get("error")})
        return result
    if not isinstance(trace, dict) or trace.get("schema_version") != 1:
        result["unknowns"].append({"question": "Runtime observation", "reason": "Invalid helper trace schema"})
        return result
    result["artifacts"].append(_write(directory, "web-trace.json", canonical(trace).encode("utf-8")))
    if not quality or trace.get("status") != "completed":
        result["unknowns"].append({"question": "Runtime observation", "reason": "Tool execution/collection failed", "error": trace.get("error"), "process_status": run.get("status")})
        return result
    inspector = trace.get("inspector", {})
    if not inspector.get("source_verified") or not inspector.get("function_coverage") or not inspector.get("pauses"):
        result["unknowns"].append({"question": "Professional runtime evidence", "reason": "Inspector source, executed function coverage or call-stack observations missing"})
        return result
    if trace.get("source_sha256") != source_sha or hashlib.sha256(read_regular(target, MAX_SOURCE_BYTES)).hexdigest() != source_sha:
        result["unknowns"].append({"question": "Source identity", "reason": "Target changed during observation"})
        result["status"] = "stale"
        return result
    steps = trace.get("steps", [])
    if [s.get("id") for s in steps] != [s["id"] for s in scenario["steps"]]:
        result["unknowns"].append({"question": "Scenario coverage", "reason": "Observed steps do not cover the requested sequence"})
        return result
    network = trace.get("network", [])
    causal = [entry for entry in network if entry.get("received") and entry.get("response")
              and entry.get("step_id") and entry.get("request_stack")]
    changed = [s for s in steps if s.get("before") != s.get("after")]
    contract = {"schema_version": 1, "authority": "observed-finite-trace-not-universal-spec",
                "source_sha256": source_sha, "node_version": trace.get("node_version"),
                "scenario": scenario, "interactions": steps, "http_observations": network,
                "function_locations": inspector["function_coverage"], "limitations": limits,
                "unknowns": ["Unseen inputs, uninstrumented I/O and browser/extension behavior remain unverified."]}
    result["artifacts"].append(_write(directory, "web-contract.json", canonical(contract).encode("utf-8")))
    result["tool"]["version"] = trace.get("node_version")
    result["tool"]["inspected_source_sha256"] = inspector.get("source_sha256")
    result["observed_step_ids"] = [s["id"] for s in steps]
    result["causal_request_ids"] = [r["id"] for r in causal]
    result["facts"] = [
        {"kind": "runtime-interaction-sequence", "evidence": "web-trace.json", "step_ids": [s["id"] for s in steps], "confidence": "observed"},
        {"kind": "runtime-state-transitions", "evidence": "web-trace.json", "changed_step_ids": [s["id"] for s in changed], "confidence": "observed"},
        {"kind": "loopback-http-causality", "evidence": "web-trace.json", "request_ids": [r["id"] for r in causal], "confidence": "observed", "binding": "step + actual request ID header + inspector request stack + server receipt"},
        {"kind": "executed-function-locations", "evidence": "web-trace.json", "functions": inspector["function_coverage"], "confidence": "observed"},
    ]
    if not changed or not causal:
        result["unknowns"].append({"question": "P03 finite interaction/state/network chain", "reason": "No changed state or correlated HTTP request observed"})
        return result
    result["status"] = "succeeded"
    result["qualification"]["javascript_runtime"] = "finite-node-inspector-chain-observed"
    return result
