"""Run the original finite P03 fixture with owned raw evidence; no downloads/models."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from traceanchor.process import run_process
from traceanchor.web_adapter import observe


def save(path, value):
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8"))


def qualify(node=None):
    directory = ROOT / ".validation" / ("web-" + uuid.uuid4().hex)
    directory.mkdir(parents=True)
    ownership = {"schema_version": 1, "owner": "web-r3", "tier": "L2",
                 "reason": "P03 original fixture runtime qualification with raw tool evidence",
                 "status": "running", "cleanup": {"processes": "pending", "files": "retained-for-evidence"}}
    save(directory / "ownership.json", ownership)
    results = []
    calls = []
    source = ROOT / "examples" / "web" / "reservation.mjs"
    selected = directory / "reservation.mjs"
    selected.write_bytes(source.read_bytes())
    scenario = json.loads((ROOT / "examples" / "web" / "scenario.json").read_bytes())
    save(directory / "scenario.json", scenario)
    tool = node or shutil.which("node")

    def execute(argv, input_bytes=b"", env=None):
        number = len(calls) + 1
        result = run_process(argv, cwd=str(directory), input_bytes=input_bytes, env=env,
                             timeout=25, idle_timeout=10, output_limit=4 * 1024 * 1024)
        (directory / f"tool-{number}.stdin.bin").write_bytes(input_bytes)
        (directory / f"tool-{number}.stdout.bin").write_bytes(result["stdout"])
        (directory / f"tool-{number}.stderr.bin").write_bytes(result["stderr"])
        receipt = {k: value for k, value in result.items() if k not in {"stdout", "stderr"}}
        receipt["argv"] = argv
        save(directory / f"tool-{number}.json", receipt)
        calls.append(receipt)
        return result

    try:
        positive = directory / "positive"
        positive.mkdir()
        result = observe(selected, positive, execute, node=tool, scenario=scenario)
        results.append(result)
        save(directory / "observation.json", result)
        trace_path = positive / "web-trace.json"
        trace = json.loads(trace_path.read_bytes()) if trace_path.exists() else {}
        network = trace.get("network", [])
        steps = {item["id"]: item for item in trace.get("steps", [])}
        checks = {
            "managed_execution_complete": result["status"] == "succeeded" and all(item.get("cleanup", {}).get("state") == "complete" for item in calls),
            "inspector_source_matches_selected_bytes": trace.get("inspector", {}).get("source_verified") is True and trace.get("source_sha256") == hashlib.sha256(selected.read_bytes()).hexdigest(),
            "executed_dispatch_and_service_locations": {"dispatch", "handle"} <= {item["name"] for item in trace.get("inspector", {}).get("function_coverage", [])},
            "real_http_request_and_response": len(network) == 4 and all(item.get("received") and item.get("server_request", {}).get("method") == item["method"] and item.get("server_response") == item.get("response") for item in network),
            "step_network_function_causality": bool(network) and all(item.get("step_id") in steps and item.get("request_stack") and any(frame["function"] == "dispatch" for frame in item["request_stack"]) for item in network),
            "domain_state_transition": steps.get("reserve", {}).get("after", {}).get("phase") == "reserved" and steps.get("commit", {}).get("after", {}).get("phase") == "committed" and trace.get("final_service_state", {}).get("available") == 4,
            "boundary_and_error_observed": steps.get("commit-before-reserve", {}).get("outcome", {}).get("status") == "threw" and steps.get("invalid-quantity", {}).get("outcome", {}).get("value", {}).get("error") == "invalid-reservation" and steps.get("stock-boundary", {}).get("outcome", {}).get("value", {}).get("error") == "insufficient-stock",
            "business_error_is_not_collector_error": steps.get("repeated-commit", {}).get("outcome", {}).get("status") == "threw" and trace.get("status") == "completed",
            "browser_and_extension_not_overclaimed": result["qualification"]["browser_dom"] == "unqualified" and result["qualification"]["extension_runtime"] == "unqualified",
        }
        negative = directory / "negative"
        negative.mkdir()
        invalid = directory / "invalid.mjs"
        invalid.write_bytes(b"export function createSession() { throw new Error('deliberate-fixture-failure'); }\n")
        failed = observe(invalid, negative, execute, node=tool, scenario={"steps": [{"id": "one", "action": {"type": "reserve"}}]})
        results.append(failed)
        save(directory / "negative-observation.json", failed)
        checks["tool_failure_preserves_raw_and_blocks"] = failed["status"] == "blocked" and (negative / "node.stdout.bin").is_file() and bool(failed["unknowns"])
        status = "passed" if all(checks.values()) else "failed"
        summary = {"schema_version": 1, "status": status, "capability": "finite-node-inspector-state-network",
                   "checks": checks, "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                   "adapter_sha256": hashlib.sha256((ROOT / "traceanchor" / "web_adapter.py").read_bytes()).hexdigest(),
                   "helper_sha256": hashlib.sha256((ROOT / "traceanchor" / "resources" / "inspect_web.cjs").read_bytes()).hexdigest(),
                   "node_version": trace.get("node_version"), "actual_tool_runs": len(calls),
                   "model_calls": 0, "directory": str(directory),
                   "scope": "Self-created script/service fixture; no browser DOM/extension or P04 holdout/model-effectiveness qualification"}
        save(directory / "summary.json", summary)
        return summary
    finally:
        ownership["status"] = "terminal"
        ownership["cleanup"]["processes"] = "complete" if calls and all(item.get("cleanup", {}).get("state") == "complete" for item in calls) else "unverified-or-no-process"
        ownership["artifacts"] = [{"relative_path": p.relative_to(directory).as_posix(), "size": p.stat().st_size,
                                   "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                                  for p in sorted(directory.rglob("*")) if p.is_file() and p.name != "ownership.json"]
        save(directory / "ownership.json", ownership)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", help="Explicit installed Node executable; otherwise resolve PATH")
    options = parser.parse_args()
    summary = qualify(options.node)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    sys.exit(0 if summary["status"] == "passed" else 1)
