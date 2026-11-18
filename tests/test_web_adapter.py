"""P03 finite inspector/state/network tests; preserve raw tool evidence locally."""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sys
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from traceanchor.core import TraceError
from traceanchor.process import run_process
from traceanchor.web_adapter import observe


class WebAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.area = ROOT / ".validation" / ("web-tests-" + uuid.uuid4().hex)
        cls.area.mkdir(parents=True)
        cls.manifest = {"schema_version": 1, "owner": "web-r3", "tier": "L2",
                        "reason": "P03 unit and real Node runtime boundary evidence",
                        "status": "running", "cleanup": {"processes": "pending", "files": "retained-for-evidence"}}
        cls.save(cls.area / "ownership.json", cls.manifest)
        cls.runs = []

    @staticmethod
    def save(path, value):
        path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8"))

    @classmethod
    def tearDownClass(cls):
        cls.manifest["status"] = "terminal"
        cls.manifest["cleanup"]["processes"] = "complete" if all(run.get("cleanup", {}).get("state") == "complete" for run in cls.runs) else "unverified"
        cls.manifest["tool_runs"] = len(cls.runs)
        cls.manifest["artifacts"] = [{"relative_path": p.relative_to(cls.area).as_posix(), "size": p.stat().st_size,
                                     "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                                    for p in sorted(cls.area.rglob("*")) if p.is_file() and p.name != "ownership.json"]
        cls.save(cls.area / "ownership.json", cls.manifest)

    def setUp(self):
        self.base = self.area / self._testMethodName
        self.base.mkdir()
        self.target = self.base / "reservation.mjs"
        self.target.write_bytes((ROOT / "examples" / "web" / "reservation.mjs").read_bytes())
        self.output = self.base / "observation"
        self.output.mkdir()
        self.scenario = json.loads((ROOT / "examples" / "web" / "scenario.json").read_bytes())

    def execute(self, argv, input_bytes=b"", env=None):
        run = run_process(argv, cwd=str(self.base), input_bytes=input_bytes, env=env,
                          # The collector emits one JSON trace only at completion;
                          # quiet execution is not evidence of absent progress.
                          timeout=25, idle_timeout=25, output_limit=4 * 1024 * 1024)
        number = len(self.runs) + 1
        (self.base / f"tool-{number}.stdin.bin").write_bytes(input_bytes)
        (self.base / f"tool-{number}.stdout.bin").write_bytes(run["stdout"])
        (self.base / f"tool-{number}.stderr.bin").write_bytes(run["stderr"])
        receipt = {k: value for k, value in run.items() if k not in {"stdout", "stderr"}}
        receipt["argv"] = argv
        self.save(self.base / f"tool-{number}.json", receipt)
        self.runs.append(receipt)
        return run

    def never_execute(self, *args, **kwargs):
        self.fail("Invalid admission must not start a tool")

    def test_missing_node_is_blocked_without_execution(self):
        result = observe(self.target, self.output, self.never_execute, node=None, scenario=self.scenario)
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(result["unknowns"])
        self.assertFalse(list(self.output.iterdir()))

    def test_scenario_is_finite_data_not_eval_or_shell(self):
        cases = [{"steps": []}, {"steps": [{"id": "one", "action": {}}] * 2},
                 {"steps": [{"id": "one", "action": {}, "expression": "1+1"}]},
                 {"steps": [{"id": "one", "action": {}}], "shell": "node"},
                 {"steps": [{"id": f"step-{i}", "action": {}} for i in range(13)]},
                 {"steps": [{"id": "one", "action": {"bad": float("nan")}}]}]
        for value in cases:
            with self.subTest(value=value), self.assertRaises(TraceError):
                observe(self.target, self.output, self.never_execute, node="node", scenario=value)

    def test_malformed_tool_output_preserves_raw_and_blocks(self):
        def malformed(argv, input_bytes=b""):
            return {"stdout": b"not JSON\n", "stderr": b"diagnostic\n", "status": "succeeded", "exit_code": 0, "cleanup": {"state": "complete"}}
        result = observe(self.target, self.output, malformed, node="node", scenario=self.scenario)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual((self.output / "node.stdout.bin").read_bytes(), b"not JSON\n")
        self.assertEqual((self.output / "node.stderr.bin").read_bytes(), b"diagnostic\n")
        self.assertTrue(all(a["path"] == a["relative_path"] for a in result["artifacts"]))

    def test_process_failure_never_becomes_success_from_payload(self):
        def bad_quality(argv, input_bytes=b""):
            return {"stdout": b'{"schema_version":1,"status":"completed"}', "stderr": b"",
                    "status": "timed_out", "exit_code": 0, "cleanup": {"state": "unknown"}}
        result = observe(self.target, self.output, bad_quality, node="node", scenario=self.scenario)
        self.assertEqual(result["status"], "blocked")
        self.assertTrue((self.output / "web-trace.json").is_file())
        self.assertFalse((self.output / "web-contract.json").exists())

    def test_empty_failed_trace_preserves_managed_process_cause(self):
        for status in ('timed_out', 'cancelled', 'failed'):
            with self.subTest(status=status):
                directory=self.output/status;directory.mkdir()
                def empty(argv,input_bytes=b''):
                    return {'stdout':b'', 'stderr':b'', 'status':status, 'exit_code':None,
                            'cleanup':{'state':'complete'}, 'error':{'code':'fixture-process-cause'}}
                observed=observe(self.target,directory,empty,node='node',scenario=self.scenario)
                self.assertEqual(observed['status'],'blocked')
                self.assertEqual(observed['execution']['status'],status)
                self.assertEqual(observed['unknowns'][0]['process_error']['code'],'fixture-process-cause')
                self.assertFalse((directory/'web-trace.json').exists())

    def test_inspector_evidence_is_required_not_status_alone(self):
        def no_inspector(argv, input_bytes=b""):
            return {"stdout": b'{"schema_version":1,"status":"completed","inspector":{}}', "stderr": b"",
                    "status": "succeeded", "exit_code": 0, "cleanup": {"state": "complete"}}
        result = observe(self.target, self.output, no_inspector, node="node", scenario=self.scenario)
        self.assertEqual(result["status"], "blocked")
        self.assertIn("Professional runtime evidence", [item["question"] for item in result["unknowns"]])

    @unittest.skipUnless(os.name == "nt" and shutil.which("node"), "Windows managed Node runtime required")
    def test_real_domain_state_http_and_inspector_causality(self):
        result = observe(self.target, self.output, self.execute, node=shutil.which("node"), scenario=self.scenario)
        self.assertEqual(result["status"], "succeeded", result)
        trace = json.loads((self.output / "web-trace.json").read_bytes())
        self.assertTrue(trace["inspector"]["source_verified"])
        self.assertEqual(result["tool"]["inspected_source_sha256"], result["source_sha256"])
        self.assertTrue({"dispatch", "handle"} <= {item["name"] for item in trace["inspector"]["function_coverage"]})
        self.assertEqual(len(trace["network"]), 4)
        for request in trace["network"]:
            self.assertTrue(request["received"])
            self.assertEqual(request["response"], request["server_response"])
            self.assertTrue(any(frame["function"] == "dispatch" and frame["line"] > 0 for frame in request["request_stack"]))
            step = next(item for item in trace["steps"] if item["id"] == request["step_id"])
            self.assertIn(request["id"], step["network_ids"])
        by_id = {item["id"]: item for item in trace["steps"]}
        self.assertEqual(by_id["reserve"]["after"]["phase"], "reserved")
        self.assertEqual(by_id["commit"]["after"]["phase"], "committed")
        self.assertEqual(by_id["commit-before-reserve"]["outcome"]["status"], "threw")
        self.assertEqual(by_id["stock-boundary"]["outcome"]["value"]["error"], "insufficient-stock")
        self.assertEqual(result["qualification"]["browser_dom"], "unqualified")
        self.assertEqual(result["qualification"]["extension_runtime"], "unqualified")
        for artifact in result["artifacts"]:
            self.assertEqual(hashlib.sha256((self.output / artifact["path"]).read_bytes()).hexdigest(), artifact["sha256"])
        self.assertEqual(trace["cleanup"], {"server": "complete", "inspector": "complete"})

    @unittest.skipUnless(os.name == "nt" and shutil.which("node"), "Windows managed Node runtime required")
    def test_real_bad_fixture_preserves_failure_and_cleanup(self):
        self.target.write_bytes(b"export const createSession = () => ({});\n")
        result = observe(self.target, self.output, self.execute, node=shutil.which("node"), scenario=self.scenario)
        self.assertEqual(result["status"], "blocked")
        self.assertTrue((self.output / "web-trace.json").is_file(),result)
        trace = json.loads((self.output / "web-trace.json").read_bytes())
        self.assertEqual(trace["status"], "failed")
        self.assertIn("createService", trace["error"]["message"])
        self.assertEqual(trace["cleanup"]["inspector"], "complete")
        self.assertEqual(self.runs[-1]["cleanup"]["state"], "complete")

    @unittest.skipUnless(os.name == "nt" and shutil.which("node"), "Windows managed Node runtime required")
    def test_real_no_network_or_changed_state_is_not_p03_success(self):
        self.target.write_bytes(b"export function createService(){return {snapshot(){return {}},handle(){return {status:200,body:{}}}}}\nexport function createSession(){return {snapshot(){return {}},async dispatch(){return {ok:true}}}}\n")
        result = observe(self.target, self.output, self.execute, node=shutil.which("node"), scenario={"steps": [{"id": "noop", "action": {}}]})
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["causal_request_ids"], [])
        self.assertTrue((self.output / "web-contract.json").is_file())
        self.assertEqual(result["qualification"]["javascript_runtime"], "pending")

    @unittest.skipUnless(os.name == "nt" and shutil.which("node"), "Windows managed Node runtime required")
    def test_real_non_json_result_is_collection_failure_not_business_error(self):
        self.target.write_bytes(b"export function createService(){return {snapshot(){return {}},handle(){return {status:200,body:{}}}}}\nexport function createSession(){return {snapshot(){return {}},async dispatch(){return {value:NaN}}}}\n")
        result = observe(self.target, self.output, self.execute, node=shutil.which("node"), scenario={"steps": [{"id": "non-json", "action": {}}]})
        self.assertEqual(result["status"], "blocked")
        self.assertTrue((self.output / "web-trace.json").is_file(),result)
        trace = json.loads((self.output / "web-trace.json").read_bytes())
        self.assertEqual(trace["status"], "failed")
        self.assertIn("Non-finite", trace["error"]["message"])
        self.assertEqual(trace["steps"], [])

    @unittest.skipUnless(os.name == "nt" and shutil.which("node"), "Windows managed Node runtime required")
    def test_real_source_change_after_execution_is_stale(self):
        def change_after_run(argv, input_bytes=b""):
            outcome = self.execute(argv, input_bytes)
            self.target.write_bytes(self.target.read_bytes() + b"\n// changed after measured run\n")
            return outcome
        result = observe(self.target, self.output, change_after_run, node=shutil.which("node"), scenario=self.scenario)
        self.assertEqual(result["status"], "stale")
        self.assertFalse((self.output / "web-contract.json").exists())


if __name__ == "__main__":
    output = io.StringIO()
    result = unittest.TextTestRunner(stream=output, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(WebAdapterTests))
    text = output.getvalue()
    (WebAdapterTests.area / "unittest.txt").write_bytes(text.encode("utf-8"))
    WebAdapterTests.save(WebAdapterTests.area / "tests.json", {"run": result.testsRun, "failures": len(result.failures),
                         "errors": len(result.errors), "skipped": len(result.skipped), "successful": result.wasSuccessful()})
    print(text, end="")
    print("Evidence directory:", WebAdapterTests.area)
    sys.exit(0 if result.wasSuccessful() else 1)
