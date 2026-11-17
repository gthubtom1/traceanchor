"""Real finite reference→spec→independent candidate→difference→fix qualification.

Synthetic reference/candidates are separate original implementations for this demo.
No model inference, access-control change, copied upstream code or outside target.
"""
from pathlib import Path
from .core import Store, TraceError, canonical
from .service import dispatch

REFERENCE = '''import json,sys
from pathlib import Path
commands=json.loads(sys.stdin.read())
p=Path("state.json")
state={"value":0}
answers=[]
for c in commands:
    if c["op"]=="add": state["value"]+=c["amount"];answers.append({"ok":True,"value":state["value"]})
    elif c["op"]=="reset": state["value"]=0;answers.append({"ok":True,"value":0})
    elif c["op"]=="get": answers.append({"ok":True,"value":state["value"]})
    else: answers.append({"ok":False,"error":"unknown-operation"})
p.write_text(json.dumps(state,sort_keys=True),encoding="utf-8")
print(json.dumps(answers,sort_keys=True))
'''
CANDIDATE = '''import json,sys
from pathlib import Path
value=0
result=[]
for request in json.load(sys.stdin):
    operation=request.get("op")
    if operation in ("add","reset","get"):
        if operation=="add": value=value+request["amount"]
        if operation=="reset": value=0
        result.append(dict(ok=True,value=value))
    else: result.append(dict(error="unknown-operation",ok=False))
Path("state.json").write_text(json.dumps(dict(value=value),sort_keys=True),encoding="utf-8")
print(json.dumps(result,sort_keys=True))
'''


def run_demo(directory):
    root = Path(directory).absolute()
    if root.exists():
        raise TraceError("conflict", "Demo needs a new directory so prior artifacts are never overwritten")
    root.mkdir(parents=True)
    workspace = root / "evidence"
    Store(workspace, create=True)
    reference, candidate = root / "reference.py", root / "candidate.py"
    reference.write_text(REFERENCE, encoding="utf-8")
    candidate.write_text(CANDIDATE.replace('value=value+request["amount"]', 'value=value+abs(request["amount"])'), encoding="utf-8")
    def call(op, **args):
        return dispatch(workspace, op, args)
    case = call("case.create", mode="reconstruct", target_kind="protocol", objective="Independent finite JSON counter implementation including negative deltas, invalid operations and reset", non_goals=["Unbounded protocol equivalence", "GUI or Android runtime"], allowed_effects=["read", "execute", "write-candidate"])
    cid = case["id"]
    ref = call("source.add", case_id=cid, path=str(reference), role="reference")
    observation = call("analyze", case_id=cid, source_id=ref["id"])
    fixtures = [
        {"id": "normal-negative", "stdin": '[{"op":"add","amount":5},{"op":"add","amount":-2},{"op":"get"}]', "state_files": ["state.json"]},
        {"id": "reset-error", "stdin": '[{"op":"add","amount":-1},{"op":"reset"},{"op":"wat"},{"op":"get"}]', "state_files": ["state.json"]},
        {"id": "empty-boundary", "stdin": '[]', "state_files": ["state.json"]},
    ]
    plan = {"obligations": [
        {"id": "response", "dimension": "behavior", "comparator": "json", "blocking": True},
        {"id": "exit", "dimension": "behavior", "comparator": "exact", "selector": "exit_code", "blocking": True},
        {"id": "persisted-state", "dimension": "state", "comparator": "exact", "blocking": True},
        {"id": "owned-file-effects", "dimension": "side-effects", "comparator": "exact", "blocking": True},
        {"id": "output-shape", "dimension": "structure", "comparator": "json-shape", "blocking": True},
        {"id": "visual", "dimension": "visual", "comparator": "ppm", "blocking": False, "not_applicable_reason": "This frozen protocol task has no visual output"},
    ]}
    spec = call("spec.freeze", case_id=cid, reference_id=ref["id"], evidence_ids=[observation["id"]], requirements=["add signed integer", "reset", "get", "unknown operation error", "state file"], scope="Three frozen input sequences; not all possible programs", fixtures=fixtures, plan=plan)
    wrong = call("source.add", case_id=cid, path=str(candidate), role="candidate")
    failed = call("verify", case_id=cid, spec_id=spec["id"], candidate_id=wrong["id"])
    if failed["data"]["status"] != "fail":
        raise TraceError("demo-negative-control", "Wrong candidate did not yield a failing difference", {"status": failed["data"]["status"]})
    # Host-developed independent implementation repair, not comparator/threshold change.
    candidate.write_text(CANDIDATE, encoding="utf-8")
    fixed = call("source.refresh", case_id=cid, source_id=wrong["id"])
    passed = call("verify", case_id=cid, spec_id=spec["id"], candidate_id=fixed["id"])
    if passed["data"]["status"] != "pass":
        raise TraceError("demo-positive-control", "Repaired independent implementation did not pass", {"status": passed["data"]["status"], "verdict_id": passed["id"]})
    accepted = call("case.close", case_id=cid)
    summary = {"status": "passed-finite-scope", "case_id": cid, "negative_control": failed["id"], "final_verdict": passed["id"], "disposition": accepted["data"]["disposition"], "fixtures": len(fixtures), "actual_process_runs": 12, "model_calls": 0, "scope": spec["data"]["scope"], "limitations": ["Synthetic CLI/protocol task, not real desktop/APK/browser qualification", "Host repair is explicit code, not an autonomous internal model"]}
    (root / "summary.json").write_text(canonical(summary) + "\n", encoding="utf-8")
    return summary
