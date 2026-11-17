# TraceAnchor 0.1.0 — frozen implementation and acceptance contract

Status: implementation authorized by the user's explicit Goal, research handoff revision 2, 2026-11-18. This document freezes scope before implementation; it is not a passing test record. The complete Goal completion gate remains handoff section 12. No publication before local gates and public-file review. Public name may change only for collision, without changing requirements.

## Product and architecture

A host-driven evidence workbench for reverse analysis and independent reconstruction. Python >=3.11, standard-library runtime only. SQLite transactions own records/events/leases/material metadata; content-addressed private blobs store evidence; CLI/MCP are thin adapters to one dispatch function. No internal model loop or billed API requests. No upstream code, binaries, assets, APIs or runtime are required. Source snapshots remain research-only. The host reasons, writes independent candidates, reads differences and revises candidates; core owns effects, observations, identity, freshness and verdicts.

Implementation package `traceanchor/` is directly importable and installable; product-only Git. Avoid developer paths in shipped data. Tests generate fixtures inside explicit temporary directories; no real targets or global settings.

## Frozen first-release capability matrix

All six task modes are explicit: analysis, protocol, reconstruct, diagnose-modify, version-diff, dev-subtask. No silent fallback to a different goal. Six target kinds: desktop/native, apk, extension, javascript/web, protocol, development-component (plus generic file).

1. Actual static support: bounded regular-file hashing and inventory; Python AST facts (not execution), JS textual import/endpoint hints with inferred labels, extension manifest JSON, APK ZIP entry inventory/hash and plain-text manifest when available (binary AXML explicitly unsupported), PE/ELF/Mach-O header identification (not decompilation), JSON/HTTP contract material. Paths/line ranges, examined/omitted/unknown and source identities are retained. ZIP is inspected, never extracted automatically.
2. Actual dynamic support: explicit trusted single-file command/Python reference/candidate execution through one process owner, bounded stdin/stdout/stderr/time/cancellation; real local HTTP sampling for caller-listed loopback endpoints with redirects refused and limited output. Arbitrary target execution requires case effect allowlist; not a sandbox. No credential strings persisted in request metadata. Missing test session/data/service/tool stays blocked or unknown.
3. Independent implementation: collect reference observations, freeze a finite specification/fixtures/obligations, host produces separate candidate file, execute both independently with same inputs in separate owned workdirs; compare, return differences, revise candidate while retaining previous identity, reverify. No copying modified reference and calling it independent.
4. Five dimensions: behavior (exit/stdout/stderr exact or JSON), state (declared JSON state files after controlled sequences), side-effects (owned workdir file before/after hashes), structure (declared JSON schema-shape), visual (explicit PPM pixel comparison for deterministic image fixtures; general browser/desktop visual equivalence unsupported). Unsupported/missing requested dimension is blocked/inconclusive, not not-applicable unless frozen contract gives reason. No mean score hides a blocking failure.
5. Derived modification: explicit byte-range precondition and immutable derived file with parent identity, never change reference in place. Intended for controlled fixtures and diagnostic branches; not a general access-control bypass feature. Original/derived/candidate roles checked.
6. Dev subtask: linked parent case, finite question/version/material/budget/output, evidence-return contract and recursive parent invalidation on relevant source revisions.
7. Plan: observation gaps, prerequisites, route question/method/evidence/falsification/stop conditions; static/dynamic/combined selection based on capability/effects, budget and reachability, with recorded exclusions. No escalation from target keywords.

Deferred requirements remain in `docs/requirements-map.json`: interactive desktop automation, real Android device/repack/instrumentation, browser extensions runtime, browser screenshots, decompilation/debugger integration and broad protocol inference. Explicit unsupported/experimental, not claimed implemented. Future adapters must pass real-tool qualification, no registry-only READY.

## Core record contract

`Store(root)`; root is an explicit owned workspace with marker, SQLite database, objects/, work/. Generic immutable-history records: kind, id, case_id, revision, data, created. `create(kind,data,case_id=None,id=None)`, `get(kind,id)`, `list(kind,case_id=None)`, `update(kind,id,changes,expected_revision=None)`, `event(case_id,action,data)`. Public records returned flattened with id/kind/case_id/revision/data. No caller-created run/observation/verdict through generic API. Source refresh creates new source identity; old observed bytes remain immutable.

Cases contain mode, target_kind, objective/non_goals, allowed_effects (read by default; execute/network/derive/write-candidate require explicit case grant), budgets {max_runs, max_seconds, max_bytes, output_limit}, parent_id, status, acceptance_revision, current bindings. Observability records retain reachability (startup/ui/function/verified separately), prerequisites (session/data/server/runtime/device/tool), evidence references, affected obligations, next experiment/cost/stops. Secrets only caller refs, never literal credentials in contracts.

`TraceError(code,message,details={})`; deterministic structured errors. Case status active/suspended/closed; runs preparing/running/collecting/succeeded/failed/cancelled/timed_out/output_limit/abandoned, cleanup complete/unknown/pending; acceptance pass/fail/blocked/inconclusive/stale independently. All progress/control mutations durable; revision mismatch conflicts rather than overwrite.

## Module ownership/API seams for concurrent implementation

- Main owns core.py (store, sources, materials, references), service.py (dispatch, routing/observability/subtask/spec/run/verify/unknown), lifecycle.py (L1/L2/L3, budgets/GC), cli.py, demo.py, __init__/__main__, build backend, integration tests and final qualification/release.
- Process implementer exclusively owns process.py, winjob.py, tests/test_process.py. `run_process(argv, *, cwd, input_bytes=b'', timeout=30.0, idle_timeout=10.0, output_limit=1048576, cancelled=None, env=None, on_start=None) -> dict`. stdout/stderr are bounded raw bytes; all other fields JSON-compatible: status, exit_code, elapsed_seconds, pid, containment, cleanup {state, details}, output_truncated and error. No shell; stdin not inherited; on_start(identity_dict) after ownership acquired before target executes. Windows strong Job Object ownership before resume (or a gated supervisor handshake with equivalent guarantee); POSIX own session/process group and honest detached-descendant limits. Deadline includes bounded cleanup/drain. Do not claim unsupported ownership worked. No Store dependency.
- Analysis implementer exclusively owns analysis.py, comparison.py, tests/test_analysis.py, tests/test_comparison.py. `analyze_path(path, *, max_bytes=1048576, max_entries=5000) -> dict`; `compare_observations(left:dict,right:dict,plan:dict) -> dict`. Capture dictionary fields status/exit_code/stdout(str)/stderr(str)/state(dict of selected path→decoded JSON or error)/effects(dict path→sha256)/structure(JSON shape)/visual(optional PPM bytes). Plan is `obligations:[{id,dimension, comparator:exact|json|json-shape|ppm, selector?, blocking:true, not_applicable_reason?}]`; missing dimension fails closed. Output `{status,obligations:[{id,dimension,status,differences,coverage}],differences,limitations}`. Unknown/error/truncated/failed cleanup observation never yields overall pass. Each dimension independent. Comparison package doesn't execute processes or own Store.
- Host implementer exclusively owns mcp.py, hosts.py, tests/test_mcp.py, tests/test_hosts.py, docs/hosts.md, skills/traceanchor/SKILL.md, docs/provenance/* and UPSTREAM-REVIEW-PROMPT.md. `mcp.serve(root)` calls `service.dispatch(root,operation,args,cancel=threading.Event)`; cancellation threaded and EOF cancels active calls. JSON-RPC stdio lifecycle, strict input shape/size, tool error isError, no stray stdout, supported protocol versions explicit. Hosts `install_host(project, host, python_executable, workspace, apply=False)` and `uninstall_host(project,host,apply=False)` with project-local Claude `.mcp.json` and Codex `.codex/config.toml`, receipt-backed ownership/conflict/backup/readback. Never write real global config in development. Consult official protocol/config docs. Source lineage map stable IDs with URLs/fixed commits/source anchors/local modules/tests/adoption/differences, original work labelled, future review self-contained/static-only.

## Service and CLI surface

`service.dispatch(root, operation, args, cancel=None) -> dict` raises TraceError for input/policy/integrity errors. CLI `python -m traceanchor --workspace PATH call OP --input FILE` (FILE '-' means JSON stdin), `init`, `doctor`, `mcp`, `demo`; shell-independent UTF-8 JSON output and nonzero errors. MCP exposes grouped stable tools requiring operation string and arguments object; uses same service and cannot authorize effects beyond case.

Operations implemented (qualification remains separate): case.create/get/list/revise/close; source.add/get/refresh/derive; analyze; observability.set; observe.http; plan; subtask.create/result; spec.freeze/get; capture; compare/verify; run.get/list/cancel/reconcile; unknown.add/resolve; storage.usage/register/preview/clean/promote/pin; report; export/import; doctor; version-diff. Explicit offline CLI maintenance snapshot/restore is not an MCP operation; stop all hosts first. Host installation via hosts functions and CLI convenience. Version-diff uses source inventories/comparator not program mutation. API registry/schema published from actual dispatch and exercised.

## Storage lifecycle and budgets (blocking)

Material registration at creation stores case/run/source role, digest+size+tier/reason, references, leases, recovery use/regeneration cost, pinned, created/deleted. Only product-owned regular files under marker root; reject symlink/junction/hardlink ambiguity for deletion. L1 always skipped by automatic cleanup. L2 requires case accepted/closed, L1 archive verified, no dependency/recovery/shared refs; L3 requires producer terminal and lease released, no references. Unknown/unregistered files preserved. Promotion writes/verifies durable L1 and references before former temporary deletion. Dry-run returns byte estimates and reasons for both keep/delete. Execution rechecks within transaction and bounds items/time; interruption leaves auditable resumable tombstones. Budgets project/task/temp soft/hard, reserve before large writes, L3-first eligible cleanup then fail preserving restore state; never sacrifice L1. No full-disk scan or deleting old 60GB material.

## Frozen acceptance and completion gate

IDs A01–A20 below cannot be removed or weakened to obtain release. Tests and evidence must map to each, distinguish mock vs real integration, pass/fail/skip/not-run. Platform/host qualifications scoped honestly.

A01 research integrity retained; revision2 including4.1–4.5 verified; original snapshots unchanged.
A02 six-mode/multi-target dispatch, invalid/unsupported explicit, no target/effect silent switch.
A03 observability prerequisites + actual runtime-state and missing-server fixtures; startup/UI/function/verified not conflated.
A04 static→dynamic gap routing with bounded actual experiment; static fallback doesn't become runtime fact.
A05 original/derived/candidate identity and content integrity; full hashes, independent runs, no same-side identity pass.
A06 real analysis→spec→independent candidate→fail differences→host fix→pass integration, error/edge/state inputs beyond help/version; persisted trace and finite coverage.
A07 five separate comparisons; missing dimensions not pass; wrong-but-builds and right-picture/wrong-behavior negative controls.
A08 source/candidate/spec/fixture/tool/environment/comparator changes invalidate relevant verdict/reuse; history immutable.
A09 real timeout/cancel/output-limit/nonzero+stdout, owned parent/child/grandchild cleanup, partial artifacts retained; root crash recovery no blind replay.
A10 budgets/time/runs/output/disk and no-progress stop; hard cap does not discard L1 or silently retry.
A11 L1/L2/L3 ownership/ref/lease/pin/shared protections, preview reasons and bytes, promotion and eligible L3/L2 actual deletion, interrupted/concurrent/resume safety.
A12 transaction/revision/concurrency, malformed/newer schema refuses writes, export/import integrity and migration snapshot rollback.
A13 linked dev-subtask returns evidence and fixtures; relevant source change invalidates parent verification.
A14 real MCP initialize/list/call/error/cancel/EOF and bounded transport integration; official config source-backed templates, host end-to-end not-run explicit if absent.
A15 isolated install from actual release artifact, doctor + meaningful commands; install upgrade/uninstall/rollback projects preserved; not called clean machine.
A16 user docs quickstart/full example/support matrix/storage/diagnostics/security-limitations/version-maintenance usable without private paths.
A17 source provenance baselines/mechanism bidirectional map/ADRs/notices/future AI review prompt/templates and tests.
A18 simple deterministic baseline comparisons for freshness/recovery/disk/resources; no paid model calls without new budget; no superiority claim.
A19 public-file+Git-history inspection, no credentials/real targets/private paths/upstream copies/caches; license and release artifacts/checksums complete.
A20 actual authorized GitHub repo/push/CI/Release/download verification individually recorded. Remote blockers do not mark full Goal complete.

Support tier before results: Windows10 x64/Python3.12 candidate for tested core/runner; Linux/macOS experimental until actual CI qualification. CLI and MCP protocol real tests; Claude/Codex host configuration static checked plus synthetic project install, true host workflow only if actually exercised. Broad native/debugger/Android/browser runtime deferred, never mock-qualified.

Resource policy: test fixture work stays under product/.validation or test temp roots; local commands bounded, >2min background. Initial app defaults <=30s/run,10s idle,1MiB per stream,100 runs/task,300s cumulative task,256MiB owned project hard material cap (configurable before task starts),L3 short lifetime policy; no system-wide edits. Tool settings/environment not copied wholesale to evidence. No fixed deadline for complete product; if a hard permission/environment/budget block remains after other work is done, report partial with exact evidence and resume, per handoff12.
