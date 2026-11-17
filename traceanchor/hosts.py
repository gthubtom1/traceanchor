"""Project-local host configuration, preview-first and receipt-owned.

Receipts embed the bounded original bytes. No global configuration, executable
installation, credentials, or host process is touched by this module.
"""
from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import tomllib

MAX_CONFIG_BYTES = 1024 * 1024
TARGETS = {"claude": ".mcp.json", "codex": ".codex/config.toml"}


def _fail(code, message, **details):
    from .core import TraceError
    raise TraceError(code, message, details)


def _digest(data):
    return hashlib.sha256(data).hexdigest() if data is not None else None


def _safe(path, project):
    """Reject link/reparse and hardlink ambiguity, including parent components."""
    try:
        relative = path.relative_to(project)
    except ValueError:
        _fail("host.path", "Path is outside the selected project")
    current = project
    for part in ("", *relative.parts):
        if part:
            current /= part
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            _fail("host.path", "Linked or reparse paths are not managed")
        if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
            _fail("host.path", "Hardlinked configuration is not managed")
        if current != path and not stat.S_ISDIR(info.st_mode):
            _fail("host.path", "Configuration parent is not a directory")


def _read(path, project):
    _safe(path, project)
    try:
        if not stat.S_ISREG(path.lstat().st_mode):
            _fail("host.config", "Configuration is not a regular file")
        with path.open("rb") as stream:
            data = stream.read(MAX_CONFIG_BYTES * 3 + 1 if path.suffix == ".json" and path.parent.name == ".traceanchor-hosts" else MAX_CONFIG_BYTES + 1)
    except FileNotFoundError:
        return None
    except OSError:
        _fail("host.config", "Configuration is not a readable regular file")
    limit = MAX_CONFIG_BYTES * 3 if path.parent.name == ".traceanchor-hosts" else MAX_CONFIG_BYTES
    if len(data) > limit:
        _fail("host.size", "Configuration exceeds the management size limit")
    return data


def _json(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    return json.loads(data.decode("utf-8-sig"), object_pairs_hook=unique,
                      parse_constant=lambda v: (_ for _ in ()).throw(ValueError("non-finite number")))


def _parse(data, host):
    try:
        value = ({} if data is None else _json(data)) if host == "claude" else ({} if data is None else tomllib.loads(data.decode("utf-8")))
        key = "mcpServers" if host == "claude" else "mcp_servers"
        if not isinstance(value, dict) or not isinstance(value.get(key, {}), dict):
            raise ValueError("invalid server map")
        return value
    except (ValueError, UnicodeError, RecursionError):
        _fail("host.config", "Malformed host configuration; original bytes preserved")


def _entry(python_executable, workspace):
    try:
        python = os.fspath(python_executable)
        root = os.fspath(workspace)
    except TypeError:
        _fail("host.arguments", "Executable and workspace must be explicit path strings")
    if not isinstance(python, str) or not python or "\x00" in python or not Path(python).is_absolute():
        _fail("host.arguments", "python_executable must be an absolute executable path")
    if not isinstance(root, str) or not root or "\x00" in root or not Path(root).is_absolute():
        _fail("host.arguments", "workspace must be an explicit absolute path")
    return {"command": python, "args": ["-m", "traceanchor", "--workspace", root, "mcp"]}


def _render(before, host, entry):
    value = _parse(before, host)
    key = "mcpServers" if host == "claude" else "mcp_servers"
    if "traceanchor" in value.get(key, {}):
        _fail("host.conflict", "An external same-name server exists; ownership receipt required")
    if host == "claude":
        value.setdefault(key, {})["traceanchor"] = {"type": "stdio", **entry}
        after = (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    else:
        # Appending preserves all existing comments, values and unrelated tables.
        # Validating the complete result rejects inline/frozen table collisions.
        original = before or b""
        block = "\n[mcp_servers.traceanchor]\ncommand = " + json.dumps(entry["command"], ensure_ascii=False) + "\nargs = " + json.dumps(entry["args"], ensure_ascii=False) + "\n"
        after = original + (b"\n" if original and not original.endswith(b"\n") else b"") + block.encode("utf-8")
    if len(after) > MAX_CONFIG_BYTES:
        _fail("host.size", "Generated configuration exceeds size limit")
    parsed = _parse(after, host)
    actual = parsed[key]["traceanchor"]
    if actual.get("command") != entry["command"] or actual.get("args") != entry["args"]:
        _fail("host.config", "Generated configuration failed semantic readback")
    return after


def _locations(project, host):
    if not isinstance(host, str) or host not in TARGETS:
        _fail("host.unsupported", "Supported hosts are claude and codex")
    try:
        project = Path(os.path.abspath(os.fspath(project)))
    except (TypeError, ValueError):
        _fail("host.project", "Project must be a directory path")
    if not project.is_dir():
        _fail("host.project", "Project must be an existing directory")
    # Deliberately avoid resolve(): it would erase link/reparse evidence.
    for ancestor in reversed((project, *project.parents)):
        _safe(ancestor, ancestor)
    _safe(project, project)
    config = project / TARGETS[host]
    receipt = project / ".traceanchor-hosts" / (host + ".json")
    _safe(config, project)
    _safe(receipt, project)
    return project, config, receipt


def _receipt(data, host, config):
    if data is None:
        return None
    try:
        value = _json(data)
        if set(value) != {"schema", "host", "config", "before", "before_sha256", "after_sha256", "entry", "phase"} or value["schema"] != 1 or value["host"] != host or value["config"] != TARGETS[host] or value["phase"] != "installed":
            raise ValueError("invalid receipt")
        original = None if value["before"] is None else base64.b64decode(value["before"], validate=True)
        if original is not None and len(original) > MAX_CONFIG_BYTES:
            raise ValueError("oversized backup")
        if _digest(original) != value["before_sha256"] or _digest(config) != value["after_sha256"]:
            _fail("host.conflict", "Configuration or backup changed since receipt; preserving user bytes")
        if not isinstance(value["entry"], dict):
            raise ValueError("invalid entry")
        # Ownership requires both full bytes and an actual server entry match.
        parsed = _parse(config, host)
        actual = parsed.get("mcpServers" if host == "claude" else "mcp_servers", {}).get("traceanchor")
        expected = {"type": "stdio", **value["entry"]} if host == "claude" else value["entry"]
        if actual != expected:
            _fail("host.conflict", "Receipt does not match the owned server entry")
        value["original"] = original
        return value
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        _fail("host.receipt", "Malformed or incomplete ownership receipt; preserving configuration")


def _atomic(path, data, project):
    _safe(path, project)
    path.parent.mkdir(parents=True, exist_ok=True)
    _safe(path, project)
    fd, temporary = tempfile.mkstemp(prefix=".traceanchor-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        _safe(path, project)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _replace_checked(path, expected, replacement, project):
    if _read(path, project) != expected:
        _fail("host.conflict", "Concurrent configuration change detected")
    if replacement is None:
        if expected is not None:
            path.unlink()
    else:
        _atomic(path, replacement, project)
    if _read(path, project) != replacement:
        _fail("host.readback", "Configuration byte readback failed")


@contextlib.contextmanager
def _lock(project):
    directory = project / ".traceanchor-hosts"
    _safe(directory, project)
    directory.mkdir(exist_ok=True)
    path = directory / ".lock"
    _safe(path, project)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        _fail("host.busy", "A host transaction or interrupted lock exists; inspect it before retrying")
    try:
        os.close(descriptor)
        yield
    finally:
        path.unlink()


def _install(project, host, python_executable, workspace, apply):
    project, config_path, receipt_path = _locations(project, host)
    entry = _entry(python_executable, workspace)
    current = _read(config_path, project)
    raw_receipt = _read(receipt_path, project)
    prior = _receipt(raw_receipt, host, current)
    original = prior["original"] if prior else current
    after = _render(original, host, entry)
    status = "unchanged" if prior and after == current else ("reinstall" if prior else "install")
    preview = {"host": host, "action": status, "applied": False, "config": TARGETS[host],
               "entry": {"type": "stdio", **entry} if host == "claude" else entry,
               "before_sha256": _digest(current), "after_sha256": _digest(after)}
    if not apply or status == "unchanged":
        return preview
    receipt = {"schema": 1, "host": host, "config": TARGETS[host], "before": None if original is None else base64.b64encode(original).decode("ascii"),
               "before_sha256": _digest(original), "after_sha256": _digest(after), "entry": entry, "phase": "prepared"}
    prepared = (json.dumps(receipt, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    # Durable backup precedes config mutation. A crash leaving prepared phase
    # requires inspection; we never guess whether a partial install is owned.
    _replace_checked(receipt_path, raw_receipt, prepared, project)
    try:
        _replace_checked(config_path, current, after, project)
        receipt["phase"] = "installed"
        installed = (json.dumps(receipt, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        _replace_checked(receipt_path, prepared, installed, project)
        _receipt(_read(receipt_path, project), host, _read(config_path, project))
    except Exception:
        # Roll back only bytes still equal to our own write. Concurrent user
        # edits are never overwritten, even as part of an error recovery.
        observed = _read(config_path, project)
        if observed == after:
            _replace_checked(config_path, after, current, project)
        if _read(config_path, project) == current:
            observed_receipt = _read(receipt_path, project)
            if observed_receipt in (prepared, locals().get("installed")):
                _replace_checked(receipt_path, observed_receipt, raw_receipt, project)
        raise
    return {**preview, "applied": True}


def install_host(project, host, python_executable, workspace, apply=False):
    """Preview by default; explicitly apply only project-local owned changes."""
    if type(apply) is not bool:
        _fail("host.arguments", "apply must be a boolean")
    if not apply:
        return _install(project, host, python_executable, workspace, False)
    project, _, _ = _locations(project, host)
    with _lock(project):
        return _install(project, host, python_executable, workspace, True)


def _uninstall(project, host, apply):
    project, config_path, receipt_path = _locations(project, host)
    current = _read(config_path, project)
    raw_receipt = _read(receipt_path, project)
    prior = _receipt(raw_receipt, host, current)
    if prior is None:
        parsed = _parse(current, host)
        if "traceanchor" in parsed.get("mcpServers" if host == "claude" else "mcp_servers", {}):
            _fail("host.receipt", "Ownership receipt missing; preserving same-name server")
        return {"host": host, "action": "absent", "applied": False, "config": TARGETS[host]}
    original = prior["original"]
    preview = {"host": host, "action": "uninstall", "applied": False, "config": TARGETS[host],
               "before_sha256": _digest(current), "after_sha256": _digest(original)}
    if not apply:
        return preview
    try:
        _replace_checked(config_path, current, original, project)
        _replace_checked(receipt_path, raw_receipt, None, project)
    except Exception:
        if _read(config_path, project) == original:
            _replace_checked(config_path, original, current, project)
        raise
    return {**preview, "applied": True}


def uninstall_host(project, host, apply=False):
    """Restore exact backed-up bytes only if installed bytes remain unchanged."""
    if type(apply) is not bool:
        _fail("host.arguments", "apply must be a boolean")
    if not apply:
        return _uninstall(project, host, False)
    project, _, _ = _locations(project, host)
    with _lock(project):
        return _uninstall(project, host, True)
