"""Single application authority shared by CLI and MCP. Host reasoning stays outside."""
from __future__ import annotations

import base64
import contextlib
import json
import os
import platform
import shutil
import sys
import threading
import time
from pathlib import Path

from .core import Store, TraceError, canonical, child_path, digest, new_id, no_links, parse_json, read_regular, value_digest
from . import lifecycle

VERSION = "0.1.0"
MODES = {"analysis", "protocol", "reconstruct", "diagnose-modify", "version-diff", "dev-subtask"}
TARGETS = {"desktop", "native", "apk", "extension", "javascript", "web", "protocol", "development-component", "file"}
EFFECTS = {"read", "execute", "network", "derive", "write-candidate"}
BUDGETS = {"max_runs": 100, "max_seconds": 300, "max_bytes": 64 * 1024 * 1024, "output_limit": 1024 * 1024}
_OPERATIONS = {
    "case.create", "case.get", "case.list", "case.revise", "case.close", "source.add", "source.refresh", "source.derive", "source.get",
    "analyze", "observability.set", "plan", "subtask.create", "subtask.result", "spec.freeze", "spec.get", "capture", "compare", "verify",
    "run.get", "run.list", "run.cancel", "run.reconcile", "unknown.add", "unknown.resolve", "storage.usage", "storage.preview", "storage.clean", "storage.promote", "storage.pin",
    "report", "export", "import", "doctor", "version-diff", "observe.http", "storage.register",
}


def _need(args, key, typ=str):
    value = args.get(key)
    if not isinstance(value, typ) or isinstance(value, bool) and typ in (int, float) or typ is str and not value.strip():
        raise TraceError("invalid-input", f"{key} must be a nonempty {typ.__name__}")
    return value


def _case(store, identity):
    return store.get("case", identity)


def _effect(case, effect):
    if case["data"].get("status") == "closed":
        raise TraceError("case-closed", "Closed case is read-only; explicitly revise/reopen before new work")
    if effect not in case["data"]["allowed_effects"]:
        raise TraceError("effect-not-granted", "Task contract does not admit this effect", {"required_effect": effect})


def _source(store, case_id, identity):
    source = store.check_source(identity)
    if source["case_id"] != case_id:
        raise TraceError("source-mismatch", "Source belongs to another case; explicitly register it for this task")
    return source


def _all(store, kind, case_id=None):
    result = store.list(kind, case_id)
    if len(result) == 1000:
        raise TraceError("over-limit", "Case record view reached its 1000-record limit; export or start a new case")
    return result


def _register_source(store, case_id, path, role, parent_id=None, description=None):
    case = _case(store, case_id)
    if role not in {"reference", "candidate", "derived", "fixture", "component"}:
        raise TraceError("invalid-input", "Unknown source role")
    _effect(case, "write-candidate" if role == "candidate" else "derive" if role == "derived" else "read")
    data = read_regular(path, case["data"]["budgets"]["max_bytes"])
    blob = store.put_bytes(case_id, data, "L1", "source-snapshot", metadata={"source_role": role})
    source = store.create("source", {"role": role, "name": Path(path).name, "path": str(no_links(path)), "sha256": digest(data), "size": len(data), "digest_scope": "complete-file", "material_id": blob["id"], "parent_id": parent_id, "description": description or "", "trust": "caller-selected-local-file"}, case_id)
    store.add_ref(source["id"], blob["id"], "source-snapshot")
    if parent_id:
        store.add_ref(source["id"], parent_id, "derived-from")
    store.invalidate(case_id, "source-registered:" + source["id"])
    return source


def _source_name(name):
    if not isinstance(name, str) or not name or name in {'.', '..'} or any(c in name for c in '/\\\\:\x00') or Path(name).name != name:
        raise TraceError('unsafe-source-name', 'Source name must be one non-special filename component')
    return name


def _environment():
    # No hostnames, usernames, credentials or ambient environment dump.
    info = {"os": sys.platform, "architecture": platform.machine(), "python": list(sys.version_info[:3]), "executable_sha256": digest(read_regular(sys.executable, 64 * 1024 * 1024)), "encoding": "utf-8", "runner_version": VERSION}
    return {**info, "digest": value_digest(info), "limitations": ["Process containment is not an OS filesystem or network sandbox; ambient library/system dependencies are not fully sealed"]}


def _shape(value):
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, (int, float)):
        return {"type": "number"}
    if isinstance(value, str):
        return {"type": "string"}
    if isinstance(value, list):
        shapes = {canonical(_shape(v)): _shape(v) for v in value}
        return {"type": "array", "items": [shapes[k] for k in sorted(shapes)]}
    if isinstance(value, dict):
        return {"type": "object", "properties": {k: _shape(v) for k, v in sorted(value.items())}}
    raise TraceError("invalid-json", "Unsupported structure value")


def _files(root, *, limit=1000, max_bytes=16 * 1024 * 1024):
    result = {}
    total = 0
    examined = 0
    pending = [Path(root)]
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                examined += 1
                if examined > limit:
                    return result, False
                path = no_links(entry.path)
                if entry.is_dir(follow_symlinks=False):
                    pending.append(path)
                    continue
                if path.stat().st_size + total > max_bytes:
                    return result, False
                data = read_regular(path, max_bytes - total)
                total += len(data)
                result[path.relative_to(root).as_posix()] = digest(data)
    return dict(sorted(result.items())), True


def _capture(store, case_id, source_id, fixture, cancel=None):
    from .process import run_process
    case = _case(store, case_id)
    _effect(case, "execute")
    source = _source(store, case_id, source_id)
    if source["data"].get("portable_snapshot") or (not source["data"].get("path") and source["data"].get("trust") != "local-managed-derivation"):
        raise TraceError("imported-execution-not-admitted", "Imported evidence may be inspected; reattach a caller-selected local file before executing")
    if source["data"]["role"] == "derived" and not fixture.get("allow_derived", False):
        raise TraceError("derived-reference", "Derived reference needs an explicit diagnostic experiment, not an independent-original verdict")
    budgets = case["data"]["budgets"]
    timeout = fixture.get("timeout", 10)
    idle = fixture.get("idle_timeout", min(timeout, 5))
    if not isinstance(timeout, (int, float)) or not 0 < timeout <= 30 or not isinstance(idle, (int, float)) or not 0 < idle <= timeout:
        raise TraceError("invalid-input", "Capture timeout/idle must be positive and bounded to 30 seconds")
    arguments = fixture.get("arguments", [])
    if not isinstance(arguments, list) or len(arguments) > 64 or any(not isinstance(v, str) or len(v) > 4096 for v in arguments):
        raise TraceError("invalid-input", "Arguments must be a bounded string list")
    input_text = fixture.get("stdin", "")
    if not isinstance(input_text, str) or len(input_text.encode("utf-8")) > 1024 * 1024:
        raise TraceError("invalid-input", "stdin exceeds capture input limit")
    state_files = fixture.get("state_files", [])
    if not isinstance(state_files, list) or len(state_files) > 20 or any(not isinstance(v, str) for v in state_files):
        raise TraceError("invalid-input", "state_files must be a bounded relative-path list")
    expected_exit = fixture.get("expect_exit", 0)
    if not isinstance(expected_exit, int) or isinstance(expected_exit, bool):
        raise TraceError("invalid-input", "expect_exit must be an integer fixed by the fixture")
    run_id = new_id("run")
    resource = "case-execution:" + case_id
    store.acquire(resource, run_id)
    try:
        run = store.create("run", {"status": "preparing", "cleanup": {"state": "pending"}, "source_id": source_id, "source_sha256": source["data"]["sha256"], "fixture_digest": value_digest(fixture), "cancel_requested": False, "environment": _environment()}, case_id, id=run_id)
    except BaseException:
        store.release(resource, run_id)
        raise
    owned = child_path(store.root, "work/" + run["id"])
    try:
        # Serialize run admissions across independent CLI/MCP processes.
        with store.transaction() as db:
            rows = db.execute("SELECT data FROM records WHERE kind='run' AND case_id=? AND id<>?", (case_id, run["id"])).fetchall()
            previous = [parse_json(r[0]) for r in rows]
            charged = sum(r.get("reserved_seconds", r.get("elapsed_seconds", 0)) for r in previous)
            if len(previous) >= budgets["max_runs"] or charged + timeout > budgets["max_seconds"]:
                raise TraceError("task-budget", "Cumulative run/time budget exhausted; no target launched", {"runs": len(previous), "charged_seconds": charged})
        store.update("run", run["id"], {"reserved_seconds": timeout})
        owned.mkdir()
        work = owned / "cwd"
        work.mkdir()
        snapshot = child_path(owned, _source_name(source["data"]["name"]))
        snapshot.write_bytes(store.read_material(source["data"]["material_id"]))
        if source["data"]["name"].lower().endswith(".py"):
            argv = [sys.executable, "-I", "-B", str(snapshot), *arguments]
        else:
            if os.name != "nt":
                snapshot.chmod(snapshot.stat().st_mode | 0o100)
            argv = [str(snapshot), *arguments]
        for rel in state_files:
            child_path(work, rel)
        def started(identity):
            store.update("run", run["id"], {"status": "running", "identity": identity})
        def cancelled():
            return bool(cancel is not None and cancel.is_set()) or store.get("run", run["id"])["data"].get("cancel_requested", False)
        outcome = run_process(argv, cwd=str(work), input_bytes=input_text.encode("utf-8"), timeout=timeout, idle_timeout=idle, output_limit=budgets["output_limit"], cancelled=cancelled, on_start=started)
        store.update("run", run["id"], {"status": "collecting"})
        stdout = outcome.pop("stdout", b"")
        stderr = outcome.pop("stderr", b"")
        if isinstance(stdout, str):
            stdout = stdout.encode("utf-8")
        if isinstance(stderr, str):
            stderr = stderr.encode("utf-8")
        effects, effects_complete = _files(work, max_bytes=min(16 * 1024 * 1024, budgets["max_bytes"]))
        state = {}
        for rel in state_files:
            try:
                state[rel] = parse_json(read_regular(child_path(work, rel), 1024 * 1024))
            except TraceError as exc:
                state[rel] = {"error": exc.code}
        visual = None
        if fixture.get("visual_file"):
            try:
                visual = read_regular(child_path(work, fixture["visual_file"]), 4 * 1024 * 1024).decode("ascii")
            except (TraceError, UnicodeError):
                visual = None
        encoding_complete = True
        try:
            text = stdout.decode("utf-8")
            error_text = stderr.decode("utf-8")
        except UnicodeDecodeError:
            encoding_complete = False
            text = stdout.decode("utf-8", "replace")
            error_text = stderr.decode("utf-8", "replace")
        try:
            from .analysis import json_shape
            structure = json_shape(parse_json(text))
        except TraceError:
            structure = None
        clean = outcome.get("cleanup", {"state": "unknown"})
        expected_business_exit = outcome.get("exit_code") == expected_exit and outcome.get("status") in {"succeeded", "success", "completed", "failed"} and not outcome.get("output_truncated") and clean.get("state") == "complete"
        observed = {**outcome, "process_status": outcome.get("status"), "status": "completed" if expected_business_exit and effects_complete and encoding_complete else "blocked", "stdout": text, "stderr": error_text, "utf8_complete": encoding_complete, "stdout_sha256": digest(stdout), "stderr_sha256": digest(stderr), "state": state, "effects": effects, "structure": structure, "visual": visual, "effects_complete": effects_complete, "cleanup": clean, "source_id": source_id, "source_sha256": source["data"]["sha256"], "source_role": source["data"]["role"], "fixture": fixture, "coverage": {"input_sequences": 1, "filesystem_scope": "owned-workdir-only", "network_observed": False}, "limitations": ["No assertion about filesystem writes outside the declared working directory or network side effects"]}
        # Finalize the raw execution before publishing observations; a publication error
        # is recoverable but never turns the run into an unobserved success.
        terminal = outcome.get("status", "failed")
        if terminal not in {"succeeded", "failed", "cancelled", "timed_out", "output_limit"}:
            terminal = "succeeded" if terminal in {"success", "completed"} else "failed"
        store.update("run", run["id"], {**outcome, "status": terminal, "cleanup": clean, "elapsed_seconds": outcome.get("elapsed_seconds", 0), "reserved_seconds": outcome.get("elapsed_seconds", timeout)})
        out_blob = store.put_bytes(case_id, stdout, "L1", "raw-stdout", run["id"])
        err_blob = store.put_bytes(case_id, stderr, "L1", "raw-stderr", run["id"])
        obs = store.create("observation", {"capture": observed, "run_id": run["id"], "source_id": source_id, "source_sha256": source["data"]["sha256"], "environment": run["data"]["environment"], "producer": "managed-runner-" + VERSION, "stdout_material": out_blob["id"], "stderr_material": err_blob["id"], "trust": "local-managed-execution"}, case_id)
        for target in (source_id, out_blob["id"], err_blob["id"]):
            store.add_ref(obs["id"], target)
        retained = []
        for rel in effects:
            path = child_path(work, rel)
            raw = read_regular(path, budgets["max_bytes"])
            important = rel in state_files or rel == fixture.get("visual_file")
            item = store.put_bytes(case_id, raw, "L1" if important else "L2", "observed-state" if important else "rebuildable-work", run["id"], {"relative_path": rel, "regeneration": "replay-frozen-fixture", "recovery_use": not important})
            retained.append(item["id"])
            if important:
                store.add_ref(obs["id"], item["id"], "observed-state")
            if clean.get("state") == "complete":
                path.unlink()
        temporary = store.put_bytes(case_id, snapshot.read_bytes(), "L3", "execution-snapshot-copy", run["id"], {"regeneration": "source-snapshot", "source_id": source_id})
        retained.append(temporary["id"])
        if clean.get("state") == "complete" and effects_complete:
            snapshot.unlink()
            for directory, dirs, files in os.walk(work, topdown=False):
                if not files:
                    try:
                        Path(directory).rmdir()
                    except OSError:
                        pass  # Unknown concurrent files are retained, never recursively removed.
            try:
                owned.rmdir()
            except OSError:
                pass
        store.update("run", run["id"], {"observation_id": obs["id"], "publication": "complete", "material_ids": retained})
        return obs
    except BaseException as exc:
        current = store.get("run", run["id"])
        if current["data"]["status"] in {"preparing", "running", "collecting"}:
            identity = current["data"].get("identity")
            store.update("run", run["id"], {"status": "failed", "cleanup": {"state": "unknown" if identity else "complete"}, "error": exc.as_dict() if isinstance(exc, TraceError) else {"code": "capture-error", "message": str(exc)}})
        raise
    finally:
        final = store.get("run", run["id"])
        if final["data"].get("cleanup", {}).get("state") == "complete":
            store.release(resource, run["id"])
            # Work files are not guessed as garbage: keep them as explicit recovery
            # material until archive, while temporary executable copy can be removed.
            if owned.exists():
                store.event(case_id, "working-directory-retained", {"run_id": run["id"], "relative_path": owned.relative_to(store.root).as_posix(), "reason": "explicit recovery; not automatic garbage"})


def _binding(store, spec, reference, candidate):
    from . import comparison
    data = spec["data"]
    engine = {name: digest(read_regular(Path(__file__).with_name(name), 4 * 1024 * 1024)) for name in ("service.py", "core.py", "analysis.py", "process.py", "winjob.py")}
    return {"engine": value_digest(engine), "spec_digest": data["digest"], "reference": reference["data"]["sha256"], "candidate": candidate["data"]["sha256"], "environment": _environment()["digest"], "comparator": digest(read_regular(comparison.__file__, 4 * 1024 * 1024)), "runner": digest(read_regular(Path(__file__).with_name("process.py"), 4 * 1024 * 1024)), "fixtures": value_digest(data["fixtures"]), "case_contract": value_digest({k: _case(store, spec["case_id"])["data"].get(k) for k in ("mode", "objective", "allowed_effects", "budgets", "acceptance_revision", "current_spec_id")})}


def _verify(store, case_id, spec_id, candidate_id, cancel=None):
    from .comparison import compare_observations
    spec = store.get("spec", spec_id)
    if spec["case_id"] != case_id:
        raise TraceError("source-mismatch", "Specification belongs to another case")
    case = _case(store, case_id)
    if spec_id != case["data"].get("current_spec_id") or spec["data"]["acceptance_revision"] != case["data"]["acceptance_revision"]:
        raise TraceError("stale-specification", "Task acceptance contract changed; explicitly freeze a reviewed specification for the new revision")
    if not _check_dependencies(store, case_id):
        raise TraceError("stale-dependency", "A consumed subtask source changed; review the child evidence before verification")
    reference = _source(store, case_id, spec["data"]["reference_id"])
    candidate = _source(store, case_id, candidate_id)
    if reference["data"]["role"] != "reference" or candidate["data"]["role"] != "candidate":
        raise TraceError("role-mismatch", "Independent verification requires original reference and independent candidate roles")
    known_derived = {s["data"].get("sha256") for s in _all(store, "source") if s["data"].get("role") == "derived" or s["data"].get("parent_id")}
    if reference["data"]["sha256"] == candidate["data"]["sha256"] or candidate["data"].get("parent_id") or candidate["data"]["sha256"] in known_derived or reference["data"]["sha256"] in known_derived:
        raise TraceError("not-independent", "Same-content or known reference-derived object is not independent reconstruction")
    before = _binding(store, spec, reference, candidate)
    prior = _all(store, "verdict", case_id)
    unchanged_failures = [v for v in prior if v["data"].get("binding") == before and v["data"].get("status") in {"fail", "blocked", "inconclusive"}]
    if len(unchanged_failures) >= 2:
        raise TraceError("no-progress", "Two unchanged unsuccessful verifications already exist; change evidence or candidate instead of repeating")
    pairs, overall = [], "pass"
    for fixture in spec["data"]["fixtures"]:
        if cancel is not None and cancel.is_set():
            raise TraceError("cancelled", "Verification cancelled before its next experiment")
        left = _capture(store, case_id, reference["id"], fixture, cancel)
        right = _capture(store, case_id, candidate["id"], fixture, cancel)
        comparison = compare_observations(left["data"]["capture"], right["data"]["capture"], spec["data"]["plan"])
        pairs.append({"fixture_id": fixture["id"], "left": left["id"], "right": right["id"], "result": comparison})
        status = comparison["status"]
        if status == "fail":
            overall = "fail"
        elif status != "pass" and overall != "fail":
            overall = "blocked" if status == "blocked" else "inconclusive"
    # A producer must not attach results to whatever revision happened to be last.
    reference = _source(store, case_id, reference["id"])
    candidate = _source(store, case_id, candidate["id"])
    after = _binding(store, spec, reference, candidate)
    if before != after:
        overall = "stale"
    unknowns = [u["id"] for u in _all(store, "unknown", case_id) if u["data"].get("blocking") and u["data"].get("status") == "open"]
    if unknowns and overall == "pass":
        overall = "blocked"
    verdict = store.create("verdict", {"status": overall, "current": True, "spec_id": spec_id, "candidate_id": candidate_id, "binding": before, "pairs": pairs, "blocking_unknown_ids": unknowns, "scope": "Only the frozen fixtures, observation surfaces and obligations; no global software equivalence", "created_at": time.time()}, case_id)
    for item in pairs:
        store.add_ref(verdict["id"], item["left"])
        store.add_ref(verdict["id"], item["right"])
    store.add_ref(verdict["id"], spec_id)
    store.add_ref(verdict["id"], candidate_id)
    return verdict


def _check_dependencies(store, case_id):
    """Refresh every consumed child source without requiring a prior child read."""
    pending = [case_id]
    visited = set()
    cases = _all(store, "case")
    fresh = True
    while pending:
        current = pending.pop()
        if current in visited:
            continue
        visited.add(current)
        for result in _all(store, "subtask-result", current):
            if not result["data"].get("current", True):
                continue
            for identity in result["data"].get("applicable_source_ids", []):
                try:
                    store.check_source(identity)
                except TraceError:
                    fresh = False
                    store.invalidate(case_id, "subtask-source-unavailable:" + identity)
        pending.extend(c["id"] for c in cases if c["data"].get("parent_id") == current)
    return fresh


def _report(store, case_id):
    _check_dependencies(store, case_id)
    case = _case(store, case_id)
    verdicts = _all(store, "verdict", case_id)
    for verdict in verdicts:
        if not verdict["data"].get("current", True):
            continue
        try:
            spec = store.get("spec", verdict["data"]["spec_id"])
            ref = _source(store, case_id, spec["data"]["reference_id"])
            cand = _source(store, case_id, verdict["data"]["candidate_id"])
            if _binding(store, spec, ref, cand) != verdict["data"]["binding"]:
                store.invalidate(case_id, "verification-inputs-changed")
        except TraceError:
            store.invalidate(case_id, "verification-identity-unavailable")
    verdicts = _all(store, "verdict", case_id)
    current = [v for v in verdicts if v["data"].get("current", True)]
    latest = current[-1] if current else None
    blocking_unknowns = [u for u in _all(store, "unknown", case_id) if u["data"].get("blocking") and u["data"].get("status") == "open"]
    acceptance = latest["data"]["status"] if latest else "stale" if verdicts else "not-verified"
    if blocking_unknowns and acceptance == "pass":
        acceptance = "blocked"
    return {"case": case, "acceptance": acceptance, "latest_verdict": latest, "sources": _all(store, "source", case_id), "unknowns": _all(store, "unknown", case_id), "runs": _all(store, "run", case_id), "scope": "No unexecuted or unsupported route is represented as passed", "storage": lifecycle.usage(store)}


def dispatch(root, operation, args, cancel=None):
    if operation not in _OPERATIONS or not isinstance(args, dict):
        raise TraceError("invalid-operation", "Unknown operation or non-object arguments", {"supported": sorted(_OPERATIONS)})
    if operation == "doctor":
        return {"version": VERSION, "python": list(sys.version_info[:3]), "platform": sys.platform, "core": "available", "runtime_dependencies": [], "model_loop": "host-owned; no external model calls", "process_containment": "windows-job" if os.name == "nt" else "posix-session", "qualification": "See release qualification records; this diagnostic does not certify runtime success", "unsupported": ["general desktop automation", "Android device runtime", "browser runtime and screenshots", "memory dump and decompilation"], "operations": sorted(_OPERATIONS)}
    if operation == "case.create":
        store = Store(root)
        mode = args.get("mode", "analysis")
        target = args.get("target_kind", "file")
        effects = args.get("allowed_effects", ["read"])
        if mode not in MODES or target not in TARGETS or not isinstance(effects, list) or not set(effects).issubset(EFFECTS) or "read" not in effects:
            raise TraceError("invalid-input", "Unknown task mode/target/effect or missing read effect")
        budgets = {**BUDGETS, **args.get("budgets", {})}
        if set(budgets) != set(BUDGETS) or any(not isinstance(v, int) or isinstance(v, bool) or v <= 0 for v in budgets.values()) or budgets["output_limit"] > 8 * 1024 * 1024 or budgets["max_runs"] > 1000:
            raise TraceError("invalid-budget", "Budget values must be positive and bounded")
        parent = args.get("parent_id")
        if parent:
            parent_case = _case(store, parent)
            _effect(parent_case, "read")
            if not set(effects).issubset(parent_case["data"]["allowed_effects"]):
                raise TraceError("effect-not-granted", "Linked child cannot expand the parent effect contract")
        return store.create("case", {"mode": mode, "target_kind": target, "objective": _need(args, "objective"), "non_goals": args.get("non_goals", []), "allowed_effects": effects, "budgets": budgets, "parent_id": parent, "status": "active", "acceptance_revision": 1, "observability": {}, "stops": ["budget", "missing-prerequisite", "unsupported-capability", "no-progress", "user-cancel"]})
    store = Store(root)
    if operation == "case.list":
        return {"items": store.list("case"), "limit": 1000}
    if operation.startswith("storage."):
        if operation == "storage.register":
            cid = _need(args, "case_id")
            _effect(_case(store, cid), "read")
            relative = _need(args, "relative_path")
            if not relative.startswith("work/"):
                raise TraceError("ownership-unknown", "Only explicitly selected owned work files can be registered")
            data = read_regular(child_path(store.root, relative), store.limits()["hard_bytes"])
            return store.put_bytes(cid, data, args.get("tier", "L2"), _need(args, "reason"), metadata={"original_owned_path": relative, "regeneration": args.get("regeneration", "unknown"), "regeneration_cost": args.get("regeneration_cost", "unknown"), "recovery_use": args.get("recovery_use", False)})
        if operation == "storage.usage":
            return lifecycle.usage(store)
        if operation == "storage.preview":
            return lifecycle.preview(store, **args)
        if operation == "storage.clean":
            return lifecycle.clean(store, cancel=cancel, **args)
        if operation == "storage.promote":
            return lifecycle.promote(store, _need(args, "material_id"), owner=args.get("owner"))
        return lifecycle.pin(store, _need(args, "material_id"), args.get("pinned", True))
    if operation in {"run.get", "source.get", "spec.get"}:
        kind = operation.split(".")[0]
        return store.get(kind, _need(args, kind + "_id"))
    if operation == "run.cancel":
        return store.update("run", _need(args, "run_id"), {"cancel_requested": True})
    if operation == "run.reconcile":
        run = store.get("run", _need(args, "run_id"))
        if run["data"]["status"] not in {"preparing", "running", "collecting"}:
            return run
        # Never kill by stale PID or replay a side effect. Strong kernel containment
        # closes on owner death; absence must still be independently established.
        return store.update("run", run["id"], {"status": "abandoned", "cleanup": {"state": "unknown", "details": "Owner interrupted; inspect recorded identity, do not blindly replay"}, "recovery": "reconcile-external-effects-before-retry"})
    if operation == "export":
        case_id = _need(args, "case_id")
        records = []
        from .core import RECORD_KINDS
        records = [_case(store, case_id)]
        for kind in sorted(RECORD_KINDS - {"case", "gc"}):
            records.extend(_all(store, kind, case_id))
        with contextlib.closing(store.connect()) as db:
            materials = [dict(r) for r in db.execute("SELECT * FROM materials WHERE case_id=? AND deleted=0", (case_id,))]
            refs = [dict(r) for r in db.execute("SELECT * FROM refs WHERE owner IN (SELECT id FROM records WHERE case_id=? OR id=?)", (case_id, case_id))]
        objects = {m["id"]: base64.b64encode(store.read_material(m["id"])).decode("ascii") for m in materials}
        # Portable source identities: external paths are not needed to inspect/export
        # and must be explicitly reattached before live freshness checks on another host.
        for record in records:
            if record["kind"] == "source":
                record["data"]["path"] = None
                record["data"]["portable_snapshot"] = True
        payload = {"schema_version": 1, "records": records, "materials": materials, "refs": refs, "objects": objects}
        return {"payload": payload, "sha256": value_digest(payload)}
    if operation == "import":
        from .exchange import import_bundle
        return import_bundle(store, _need(args, "payload", dict), args.get("sha256"))
    case_id = _need(args, "case_id")
    case = _case(store, case_id)
    if operation == "case.get":
        return case
    if case["data"].get("status") != "active" and operation not in {"case.revise", "case.close", "report", "run.list", "compare", "version-diff"}:
        raise TraceError("case-inactive", "Explicitly revise/reopen the task before new work")
    if operation == "case.revise":
        changes = args.get("changes", {})
        allowed = {"objective", "non_goals", "allowed_effects", "status", "budgets"}
        if not isinstance(changes, dict) or not set(changes).issubset(allowed):
            raise TraceError("invalid-input", "Only explicit task-contract fields can be revised")
        if "allowed_effects" in changes and (not isinstance(changes["allowed_effects"], list) or not set(changes["allowed_effects"]).issubset(EFFECTS)):
            raise TraceError("invalid-input", "Unknown effect")
        if "budgets" in changes:
            raise TraceError("budget-frozen", "Start a new request/case for a different budget; retries do not reset cumulative limits")
        changes["acceptance_revision"] = case["data"]["acceptance_revision"] + 1
        result = store.update("case", case_id, changes, args.get("expected_revision"))
        store.invalidate(case_id, "task-contract-revised")
        return result
    if operation == "case.close":
        report = _report(store, case_id)
        if report["acceptance"] != "pass":
            raise TraceError("acceptance-not-passed", "Case cannot be accepted without a current passing finite verdict")
        if any(r["data"].get("cleanup", {}).get("state") != "complete" for r in report["runs"]):
            raise TraceError("cleanup-incomplete", "Unresolved execution resources block acceptance")
        archive = store.put_bytes(case_id, canonical(report).encode("utf-8"), "L1", "accepted-case-archive")
        store.add_ref(case_id, archive["id"], "archive")
        return store.update("case", case_id, {"status": "closed", "disposition": "accepted", "archive_id": archive["id"]})
    if operation in {"source.add", "source.refresh"}:
        role = args.get("role", "reference")
        if operation == "source.refresh":
            prior = store.get("source", _need(args, "source_id"))
            if prior["case_id"] != case_id:
                raise TraceError("source-mismatch", "Source belongs to another case")
            path = args.get("path") or prior["data"]["path"]
            role = prior["data"]["role"]
        else:
            path = _need(args, "path")
        if not path:
            raise TraceError("local-path-required", "Select an explicit local file to refresh a snapshot-only source")
        return _register_source(store, case_id, path, role, parent_id=prior["data"].get("parent_id") if operation == "source.refresh" else None, description=args.get("description"))
    if operation == "source.derive":
        _effect(case, "derive")
        original = _source(store, case_id, _need(args, "source_id"))
        raw = store.read_material(original["data"]["material_id"])
        offset = _need(args, "offset", int)
        try:
            expected, replacement = bytes.fromhex(_need(args, "expected_hex")), bytes.fromhex(_need(args, "replacement_hex"))
        except ValueError as exc:
            raise TraceError("invalid-input", "Patch bytes must be hexadecimal") from exc
        if offset < 0 or not expected or len(expected) != len(replacement) or raw[offset:offset + len(expected)] != expected:
            raise TraceError("precondition-failed", "Derived diagnostic byte patch must match original bytes and length")
        output = raw[:offset] + replacement + raw[offset + len(expected):]
        blob = store.put_bytes(case_id, output, "L1", "derived-source-snapshot", metadata={"source_role": "derived"})
        derived = store.create("source", {"role": "derived", "name": original["data"]["name"], "path": None, "sha256": digest(output), "size": len(output), "digest_scope": "complete-file", "material_id": blob["id"], "parent_id": original["id"], "description": "Controlled byte derivation, not independent reconstruction", "trust": "local-managed-derivation"}, case_id)
        store.add_ref(derived["id"], blob["id"], "source-snapshot")
        store.add_ref(derived["id"], original["id"], "derived-from")
        store.invalidate(case_id, "source-derived:" + derived["id"])
        return derived
    if operation == "analyze":
        from .analysis import analyze_path
        source = _source(store, case_id, _need(args, "source_id"))
        data = source["data"]
        staging = child_path(store.root, "work/" + new_id("analysis"))
        staging.mkdir()
        selected = child_path(staging, _source_name(data["name"]))
        selected.write_bytes(store.read_material(data["material_id"]))
        try:
            result = analyze_path(str(selected), max_bytes=min(args.get("max_bytes", 1024 * 1024), case["data"]["budgets"]["max_bytes"]))
        finally:
            selected.unlink()
            staging.rmdir()
        observation = store.create("observation", {"source_id": source["id"], "source_sha256": data["sha256"], "analysis": result, "confidence": "static-facts-and-labelled-inferences", "producer": "static-analyzer-" + VERSION, "trust": "local-managed-read"}, case_id)
        store.add_ref(observation["id"], source["id"])
        return observation
    if operation == "observability.set":
        features = _need(args, "features", list)
        for feature in features:
            if not isinstance(feature, dict) or not feature.get("id") or feature.get("reachable") not in {"unobserved", "startup", "ui", "function", "verified", "blocked"}:
                raise TraceError("invalid-input", "Every feature needs ID and explicit reachability level")
            for evidence_id in feature.get("evidence_ids", []):
                obs = store.get("observation", evidence_id)
                if obs["case_id"] != case_id:
                    raise TraceError("source-mismatch", "Observability evidence belongs to another case")
            if feature["reachable"] == "verified":
                raise TraceError("authority-mismatch", "Verified is derived from current acceptance, not caller-declared reachability")
            if any(key in canonical(feature).lower() for key in ('"password"', '"token"', '"card_key"', '"account"')):
                raise TraceError("secret-field", "Store secret references, not account/session credential fields")
        return store.update("case", case_id, {"observability": {"features": features}}, args.get("expected_revision"))
    if operation == "plan":
        features = case["data"].get("observability", {}).get("features", [])
        gaps = []
        for feature in features:
            prerequisites = feature.get("prerequisites", [])
            missing = [p for p in prerequisites if isinstance(p, dict) and p.get("status") != "available"]
            if missing or feature["reachable"] in {"unobserved", "blocked", "startup", "ui"}:
                gaps.append({"feature_id": feature["id"], "question": feature.get("question", "Observe required behavior"), "missing": missing, "affected_obligations": feature.get("obligations", []), "next_experiment": feature.get("next_experiment", "Obtain bounded reference observation"), "stop": "missing prerequisite or budget exhausted"})
        execute = "execute" in case["data"]["allowed_effects"]
        missing_external = any(g["missing"] for g in gaps)
        route = "static" if not gaps else "combined" if execute and not missing_external else "static-with-observation-gap"
        data = {"route": route, "mode": case["data"]["mode"], "target_kind": case["data"]["target_kind"], "gaps": gaps, "status": "blocked" if missing_external else "ready", "reason": "Evidence/requirements and admitted effects select route, not keywords", "excluded": [] if execute else [{"route": "dynamic", "reason": "execute effect not granted"}], "dynamic_supported": case["data"]["target_kind"] in {"protocol", "development-component", "file"}, "stops": case["data"]["stops"], "limitations": ["No device/browser/debugger runtime is implicitly supplied", "Static facts cannot discharge runtime obligations"]}
        return store.create("route", data, case_id)
    if operation == "subtask.create":
        data = {**args, "mode": "dev-subtask", "parent_id": case_id, "objective": _need(args, "question"), "target_kind": args.get("target_kind", "development-component"), "allowed_effects": args.get("allowed_effects", ["read"])}
        if not set(data["allowed_effects"]).issubset(case["data"]["allowed_effects"]):
            raise TraceError("effect-not-granted", "Child task cannot expand parent effects")
        return dispatch(root, "case.create", data, cancel)
    if operation == "subtask.result":
        if not case["data"].get("parent_id"):
            raise TraceError("invalid-input", "Case is not a linked development subtask")
        evidence = _need(args, "evidence_ids", list)
        applicable = set()
        for identity in evidence:
            observation = store.get("observation", identity)
            if observation["case_id"] != case_id:
                raise TraceError("source-mismatch", "Subtask evidence must come from that subtask")
            source_id = observation["data"].get("source_id")
            _source(store, case_id, source_id)
            applicable.add(source_id)
        for identity in args.get("fixture_source_ids", []):
            _source(store, case_id, identity)
            applicable.add(identity)
        for old in _all(store, "subtask-result", case["data"]["parent_id"]):
            if old["data"].get("child_id") == case_id:
                store.update("subtask-result", old["id"], {"current": False})
        result = store.create("subtask-result", {"child_id": case_id, "current": True, "contract": _need(args, "contract", dict), "evidence_ids": evidence, "fixture_source_ids": args.get("fixture_source_ids", []), "unknowns": args.get("unknowns", []), "applicable_source_ids": sorted(applicable), "limitations": args.get("limitations", [])}, case["data"]["parent_id"])
        for identity in evidence:
            store.add_ref(result["id"], identity, "subtask-evidence")
        store.invalidate(case["data"]["parent_id"], "subtask-result-updated")
        return result
    if operation == "spec.freeze":
        from .comparison import compare_observations
        reference = _source(store, case_id, _need(args, "reference_id"))
        if reference["data"]["role"] != "reference":
            raise TraceError("role-mismatch", "Frozen independent spec must refer to unmodified original")
        fixtures = _need(args, "fixtures", list)
        plan = _need(args, "plan", dict)
        obligations = plan.get("obligations")
        if not fixtures or len(fixtures) > 20 or not isinstance(obligations, list) or not obligations or len(obligations) > 50:
            raise TraceError("invalid-input", "Specification needs 1-20 fixtures and 1-50 obligations")
        ids = [f.get("id") for f in fixtures if isinstance(f, dict)]
        if len(ids) != len(fixtures) or any(not isinstance(v, str) or not v for v in ids) or len(set(ids)) != len(ids):
            raise TraceError("invalid-input", "Fixtures require unique IDs")
        required_evidence = _need(args, "evidence_ids", list)
        if not required_evidence:
            raise TraceError("evidence-required", "Specification needs reference evidence, not just a filled template")
        for identity in required_evidence:
            obs = store.get("observation", identity)
            if obs["case_id"] != case_id or obs["data"].get("source_id") != reference["id"]:
                raise TraceError("source-mismatch", "Specification evidence must describe selected original reference")
        # Call comparator validation on unavailable observations; no fabricated pass.
        compare_observations({}, {}, plan)
        data = {"reference_id": reference["id"], "fixtures": fixtures, "plan": plan, "evidence_ids": required_evidence, "requirements": _need(args, "requirements", list), "scope": _need(args, "scope"), "acceptance_revision": case["data"]["acceptance_revision"]}
        data["digest"] = value_digest(data)
        spec = store.create("spec", data, case_id)
        for identity in [reference["id"], *required_evidence]:
            store.add_ref(spec["id"], identity)
        store.update("case", case_id, {"current_spec_id": spec["id"]})
        store.invalidate(case_id, "new-frozen-specification")
        return spec
    if operation == "observe.http":
        from .http_observer import observe
        _effect(case, "network")
        source = _source(store, case_id, _need(args, "source_id"))
        timeout = args.get("timeout", 5)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 10:
            raise TraceError("invalid-input", "HTTP deadline must be positive and at most 10 seconds")
        url = _need(args, "url")
        identity = new_id("run")
        resource = "case-execution:" + case_id
        store.acquire(resource, identity)
        started = time.monotonic()
        admitted = False
        try:
            previous = _all(store, "run", case_id)
            charged = sum(r["data"].get("reserved_seconds", r["data"].get("elapsed_seconds", 0)) for r in previous)
            if len(previous) >= case["data"]["budgets"]["max_runs"] or charged + timeout > case["data"]["budgets"]["max_seconds"]:
                raise TraceError("task-budget", "Cumulative run/time budget exhausted; no HTTP request sent")
            store.create("run", {"kind": "loopback-http", "status": "running", "source_id": source["id"], "reserved_seconds": timeout, "cleanup": {"state": "pending"}}, case_id, id=identity)
            admitted = True
            result = observe(url, timeout=timeout, max_bytes=min(args.get("max_bytes", 1048576), case["data"]["budgets"]["output_limit"]), cancel=cancel)
            body = result.pop("body")
            material = store.put_bytes(case_id, body, "L1", "http-body", identity)
            observation = store.create("observation", {"source_id": source["id"], "source_sha256": source["data"]["sha256"], "http": result, "run_id": identity, "body_material": material["id"], "producer": "loopback-http-" + VERSION, "trust": "local-managed-observation", "confidence": "observed"}, case_id)
            store.add_ref(observation["id"], material["id"])
            store.add_ref(observation["id"], source["id"])
            store.update("run", identity, {"status": "succeeded", "observation_id": observation["id"], "publication": "complete"})
            return observation
        except BaseException as exc:
            if admitted:
                store.update("run", identity, {"status": "cancelled" if cancel is not None and cancel.is_set() else "failed", "error": exc.as_dict() if isinstance(exc, TraceError) else {"code": "observation-error", "message": str(exc)}})
            raise
        finally:
            if admitted:
                elapsed = time.monotonic() - started
                store.update("run", identity, {"cleanup": {"state": "complete"}, "elapsed_seconds": elapsed, "reserved_seconds": elapsed})
            store.release(resource, identity)
    if operation == "capture":
        return _capture(store, case_id, _need(args, "source_id"), args.get("fixture", {"id": "single"}), cancel)
    if operation == "verify":
        return _verify(store, case_id, _need(args, "spec_id"), _need(args, "candidate_id"), cancel)
    if operation == "compare":
        from .comparison import compare_observations
        left = store.get("observation", _need(args, "left_id"))
        right = store.get("observation", _need(args, "right_id"))
        if left["case_id"] != case_id or right["case_id"] != case_id or left["id"] == right["id"] or left["data"].get("source_sha256") == right["data"].get("source_sha256"):
            raise TraceError("not-independent", "Comparison requires distinct observations and source identities in this case")
        return compare_observations(left["data"].get("capture", {}), right["data"].get("capture", {}), _need(args, "plan", dict))
    if operation == "run.list":
        return {"items": _all(store, "run", case_id)}
    if operation == "unknown.add":
        _effect(case, "read")
        store.invalidate(case_id, "new-unknown-requires-acceptance-review")
        return store.create("unknown", {"question": _need(args, "question"), "reason": _need(args, "reason"), "blocking": args.get("blocking", True), "status": "open", "affected_obligations": args.get("affected_obligations", []), "next_experiment": args.get("next_experiment", "Explicit input or observation required")}, case_id)
    if operation == "unknown.resolve":
        unknown = store.get("unknown", _need(args, "unknown_id"))
        evidence = _need(args, "evidence_ids", list)
        if unknown["case_id"] != case_id or not evidence:
            raise TraceError("evidence-required", "Unknown resolution needs same-case observation evidence")
        for identity in evidence:
            if store.get("observation", identity)["case_id"] != case_id:
                raise TraceError("source-mismatch", "Resolution evidence belongs to another case")
        store.invalidate(case_id, "unknown-resolution-changed")
        return store.update("unknown", unknown["id"], {"status": "resolved", "evidence_ids": evidence, "resolution": _need(args, "resolution")})
    if operation == "version-diff":
        left = _source(store, case_id, _need(args, "left_id"))
        right = _source(store, case_id, _need(args, "right_id"))
        a = store.read_material(left["data"]["material_id"])
        b = store.read_material(right["data"]["material_id"])
        changed = [i for i, pair in enumerate(zip(a, b)) if pair[0] != pair[1]]
        return {"left_sha256": digest(a), "right_sha256": digest(b), "status": "unchanged" if a == b else "changed", "size_delta": len(b) - len(a), "changed_byte_count_common": len(changed), "sample_offsets": changed[:100], "sample_capped": len(changed) > 100, "limitations": ["Byte difference is not behavior difference; no normalization is applied"]}
    if operation == "report":
        return _report(store, case_id)
    raise TraceError("invalid-operation", "Operation has no handler")
