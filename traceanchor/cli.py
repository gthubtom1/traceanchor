"""Thin UTF-8 CLI over the shared service, with no implicit global configuration."""
import argparse
import json
import sys
from pathlib import Path
from .core import Store, TraceError, parse_json, read_regular
from .service import VERSION, dispatch


def main(argv=None):
    parser = argparse.ArgumentParser(prog="traceanchor", description="Evidence-driven analysis and independent reconstruction")
    parser.add_argument("--workspace", default=".traceanchor", help="Explicit owned data directory (not your source checkout)")
    parser.add_argument("--version", action="version", version=VERSION)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("--hard-bytes", type=int, help="Managed CAS hard budget at workspace creation")
    init.add_argument("--soft-bytes", type=int, help="Managed CAS soft threshold at workspace creation")
    init.add_argument("--temp-bytes", type=int, help="L3 material budget at workspace creation")
    sub.add_parser("doctor")
    sub.add_parser("mcp")
    maintenance = sub.add_parser("maintenance", help="Offline database maintenance; stop all hosts first")
    maintenance.add_argument("action", choices=["snapshot", "restore"])
    maintenance.add_argument("--checkpoint", help="Required for restore")
    call = sub.add_parser("call")
    call.add_argument("operation")
    call.add_argument("--input", default="-", help="JSON file, or '-' for stdin")
    demo = sub.add_parser("demo")
    demo.add_argument("--directory", required=True, help="New directory for synthetic reference, independent candidates and evidence")
    host = sub.add_parser("host")
    host.add_argument("action", choices=["install", "uninstall"])
    host.add_argument("--host", choices=["claude", "codex"], required=True)
    host.add_argument("--project", required=True)
    host.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "mcp":
            from .mcp import serve
            serve(args.workspace)
            return 0
        if args.command == "init":
            from .core import DEFAULT_LIMITS
            selected = {k: v for k, v in {"hard_bytes": args.hard_bytes, "soft_bytes": args.soft_bytes, "temp_bytes": args.temp_bytes}.items() if v is not None}
            if selected and (Path(args.workspace) / "traceanchor.workspace.json").exists():
                raise TraceError("limits-frozen", "Workspace limits are set only on creation; existing workspace was preserved")
            store = Store(args.workspace, create=True, limits={**DEFAULT_LIMITS, **selected})
            result = {"status": "initialized", "schema_version": 1, "workspace_id": parse_json(read_regular(store.root / "traceanchor.workspace.json", 4096))["workspace_id"]}
        elif args.command == "maintenance":
            from .maintenance import snapshot, restore
            store = Store(args.workspace)
            if args.action == "restore" and not args.checkpoint:
                raise TraceError("invalid-input", "Restore requires --checkpoint ID; stop all hosts first")
            result = snapshot(store) if args.action == "snapshot" else restore(store, args.checkpoint)
        elif args.command == "doctor":
            result = dispatch(args.workspace, "doctor", {})
        elif args.command == "demo":
            from .demo import run_demo
            result = run_demo(args.directory)
        elif args.command == "host":
            from .hosts import install_host, uninstall_host
            if args.action == "install":
                result = install_host(args.project, args.host, sys.executable, str(Path(args.workspace).absolute()), apply=args.apply)
            else:
                result = uninstall_host(args.project, args.host, apply=args.apply)
        else:
            data = sys.stdin.buffer.read(4 * 1024 * 1024 + 1) if args.input == "-" else read_regular(args.input, 4 * 1024 * 1024)
            if len(data) > 4 * 1024 * 1024:
                raise TraceError("over-limit", "CLI input exceeds 4MiB")
            result = dispatch(args.workspace, args.operation, parse_json(data))
        text = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)
        sys.stdout.buffer.write((text + "\n").encode("utf-8"))
        return 0
    except TraceError as exc:
        sys.stderr.buffer.write((json.dumps({"error": exc.as_dict()}, ensure_ascii=False) + "\n").encode("utf-8"))
        return 2
    except KeyboardInterrupt:
        sys.stderr.write('{"error":{"code":"cancelled","message":"Interrupted"}}\n')
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
