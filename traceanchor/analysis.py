"""Bounded, read-only static observations. No target code is imported or executed.

Content digests here identify examined slices or complete ZIP members, not the
source identity; identity and immutable storage belong to the caller.
"""
from __future__ import annotations

import ast
from bisect import bisect_right
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import struct
import tokenize
import zipfile


def json_shape(value, *, _depth=0):
    """Describe external JSON types, retaining object keys and array alternatives."""
    if _depth > 64:
        raise ValueError("JSON nesting exceeds 64 levels")
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, (int, float)):
        return {"type": "number"}
    if isinstance(value, str):
        return {"type": "string"}
    if isinstance(value, list):
        variants = {json.dumps(json_shape(v, _depth=_depth + 1), sort_keys=True)
                    for v in value}
        return {"type": "array", "items": [json.loads(v) for v in sorted(variants)]}
    if isinstance(value, dict):
        return {"type": "object", "properties": {
            k: json_shape(v, _depth=_depth + 1) for k, v in sorted(value.items())}}
    raise ValueError("Value is not JSON data")


def _strict_json(text):
    def invalid(value):
        raise ValueError("Non-finite JSON number: " + value)
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON object key: " + key)
            result[key] = value
        return result
    return json.loads(text, parse_constant=invalid, object_pairs_hook=pairs)


def _unsafe_name(name):
    normalized = name.replace("\\", "/")
    parts = PurePosixPath(normalized).parts
    return (not name or "\x00" in name or normalized.startswith("/")
            or ".." in parts or any(":" in part for part in parts)
            or any(part.endswith((".", " ")) for part in parts)
            or any(re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", part)
                   for part in parts))


def _link(st):
    return stat.S_ISLNK(st.st_mode) or bool(getattr(st, "st_file_attributes", 0) & 0x400)


class _Analysis:
    def __init__(self, max_bytes, max_entries):
        self.max_bytes = max_bytes
        self.max_entries = max_entries
        self.expanded_reserved = 0
        self.facts_limited = False
        self.result = {
            "status": "complete", "target_kind": "generic-file", "facts": [],
            "limitations": ["Static observations only; no target execution or runtime behavior proven.",
                            "Slice digests are not complete source identities."],
            "unknowns": [],
            "coverage": {"max_bytes": max_bytes, "max_entries": max_entries,
                         "bytes_read": 0, "expanded_bytes_read": 0,
                         "entries_examined": 0, "entries_omitted": 0,
                         "files_examined": 0, "max_facts": max(64, max_entries * 8),
                         "facts_omitted": 0, "truncated": False},
        }

    @property
    def coverage(self):
        return self.result["coverage"]

    def gap(self, path, reason, *, unknown=False):
        self.result["unknowns"].append({"path": path, "reason": reason})
        if self.result["status"] == "complete":
            self.result["status"] = "unknown" if unknown else "partial"
        elif self.result["status"] == "unknown" and not unknown:
            self.result["status"] = "partial"

    def fact(self, kind, path, **data):
        if len(self.result["facts"]) >= self.coverage["max_facts"]:
            self.coverage["facts_omitted"] += 1
            if not self.facts_limited:
                self.facts_limited = True
                self.coverage["truncated"] = True
                self.gap(path, "Fact count budget exhausted; further facts omitted")
            return
        self.result["facts"].append({"kind": kind, "path": path, **data})

    def file(self, path, relative):
        try:
            before = path.lstat()
            if _link(before) or not stat.S_ISREG(before.st_mode):
                self.gap(relative, "Symlink, reparse point or non-regular file not read")
                return
            remaining = self.max_bytes - self.coverage["bytes_read"]
            if remaining <= 0:
                self.coverage["entries_omitted"] += 1
                self.coverage["truncated"] = True
                self.gap(relative, "Read byte budget exhausted")
                return
            # O_NOFOLLOW when supported, then verify the opened identity and type.
            flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(path, flags)
            with os.fdopen(fd, "rb") as stream:
                current = os.fstat(stream.fileno())
                if (not stat.S_ISREG(current.st_mode)
                        or (before.st_dev, before.st_ino) != (current.st_dev, current.st_ino)):
                    self.gap(relative, "File identity changed before read")
                    return
                data = stream.read(min(current.st_size, remaining))
                after = os.fstat(stream.fileno())
            self.coverage["bytes_read"] += len(data)
            self.coverage["files_examined"] += 1
            complete = (len(data) == current.st_size and
                        (after.st_size, after.st_mtime_ns) == (current.st_size, current.st_mtime_ns))
            self.fact("file-slice", relative, size=current.st_size,
                      examined_bytes=len(data), complete=complete,
                      slice_sha256=hashlib.sha256(data).hexdigest())
            if not complete:
                self.coverage["truncated"] = True
                self.gap(relative, "File truncated by budget or changed during read")
            self.inspect(data, path, relative, complete)
        except (OSError, ValueError) as exc:
            self.gap(relative, "Read failed: " + str(exc), unknown=True)

    def inspect(self, data, path, relative, complete):
        suffix = path.suffix.lower()
        if suffix in {".apk", ".zip"} or data.startswith(b"PK\x03\x04"):
            self.result["target_kind"] = "apk" if suffix == ".apk" else "generic-file"
            if complete:
                self.archive(data, relative, suffix == ".apk")
            else:
                self.gap(relative, "ZIP central directory unavailable in a bounded prefix")
            return
        if self.native(data, relative, suffix):
            self.result["target_kind"] = "desktop/native"
            return
        if suffix in {".exe", ".dll", ".so", ".dylib"}:
            self.result["target_kind"] = "desktop/native"
            self.gap(relative, "Unrecognized or damaged native header", unknown=True)
            return
        try:
            if suffix == ".py":
                encoding, _ = tokenize.detect_encoding(io.BytesIO(data).readline)
                text = data.decode(encoding)
            else:
                text = data.decode("utf-8-sig")
        except (UnicodeError, SyntaxError, LookupError) as exc:
            self.gap(relative, "Text encoding unknown: " + str(exc), unknown=True)
            return
        if suffix == ".py":
            self.result["target_kind"] = "development-component"
            self.python(text, relative, complete)
        elif suffix in {".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx"}:
            self.result["target_kind"] = "javascript/web"
            self.javascript(text, relative)
        elif suffix == ".json" or path.name == "manifest.json":
            self.json(text, relative, complete, path.name == "manifest.json")
        elif suffix in {".http", ".rest"}:
            self.result["target_kind"] = "protocol"
            for m in re.finditer(r"(?m)^(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+(\S+)", text):
                self.fact("http-request-hint", relative, method=m[1], endpoint=m[2],
                          line=text.count("\n", 0, m.start()) + 1, evidence="textual/inferred")
        else:
            self.gap(relative, "No specialized parser for this file type", unknown=True)

    def python(self, text, path, complete):
        if not complete:
            self.gap(path, "Python prefix is not parsed as a complete module")
            return
        try:
            tree = ast.parse(text, filename=path)
        except (SyntaxError, ValueError, RecursionError) as exc:
            self.gap(path, "Python AST parse failed: " + str(exc), unknown=True)
            return

        def name(node):
            if isinstance(node, ast.Name):
                return node.id
            if isinstance(node, ast.Attribute):
                parent = name(node.value)
                return (parent + "." if parent else "") + node.attr
            return "<dynamic>"

        owner = self

        class Facts(ast.NodeVisitor):
            scope = []

            def record(self, kind, node, **fields):
                owner.fact(kind, path, line=node.lineno,
                           end_line=getattr(node, "end_lineno", node.lineno),
                           column=node.col_offset, scope=".".join(self.scope), **fields)

            def visit_FunctionDef(self, node):
                self.record("python-function", node, name=node.name,
                            qualified_name=".".join(self.scope + [node.name]),
                            parameters=[a.arg for a in node.args.posonlyargs + node.args.args],
                            keyword_only=[a.arg for a in node.args.kwonlyargs],
                            vararg=node.args.vararg.arg if node.args.vararg else None,
                            kwarg=node.args.kwarg.arg if node.args.kwarg else None,
                            asynchronous=isinstance(node, ast.AsyncFunctionDef))
                self.scope = self.scope + [node.name]
                self.generic_visit(node)
                self.scope = self.scope[:-1]

            visit_AsyncFunctionDef = visit_FunctionDef

            def visit_ClassDef(self, node):
                self.record("python-class", node, name=node.name)
                self.scope = self.scope + [node.name]
                self.generic_visit(node)
                self.scope = self.scope[:-1]

            def visit_Call(self, node):
                self.record("python-call", node, callee=name(node.func),
                            evidence="syntactic; not proven execution or resolved call target")
                self.generic_visit(node)

            def visit_Import(self, node):
                self.record("python-import", node, module=None, level=0,
                            names=[{"name": a.name, "alias": a.asname} for a in node.names])

            def visit_ImportFrom(self, node):
                self.record("python-import", node, module=node.module, level=node.level,
                            names=[{"name": a.name, "alias": a.asname} for a in node.names])

        try:
            Facts().visit(tree)
        except RecursionError:
            self.gap(path, "Python visitor nesting limit reached")
        self.result["limitations"].append("Python AST calls are syntactic; dynamic dispatch/imports are unresolved.")

    def javascript(self, text, path):
        # Deliberately not a JS parser: comments/strings may produce false positives.
        newlines = [index for index, char in enumerate(text) if char == "\n"]
        patterns = [r"(?:import|export)\s+(?:[^;'\"\n]*?\bfrom\s*)?['\"]([^'\"\n]+)['\"]",
                    r"(?:require|import)\s*\(\s*['\"]([^'\"\n]+)['\"]\s*\)"]
        # Bound lookahead per keyword so repeated 'import' on one malicious
        # minified line cannot trigger quadratic scans of the whole source.
        for keyword in re.finditer(r"\b(?:import|export|require)\b", text):
            window = text[keyword.start():keyword.start() + 4096]
            for pattern in patterns:
                match = re.match(pattern, window)
                if match:
                    self.fact("javascript-import-hint", path, module=match[1],
                              line=bisect_right(newlines, keyword.start()) + 1,
                              evidence="textual/inferred")
                    break
        for m in re.finditer(r"['\"]((?:https?://|/)[^'\"\s<>]*)['\"]", text):
            self.fact("endpoint-hint", path, endpoint=m[1],
                      line=bisect_right(newlines, m.start()) + 1, evidence="textual/inferred")
        self.result["limitations"].append("JS hints use text patterns (4096-character import lookahead), including comments; no AST, resolution or runtime request proof.")

    def json(self, text, path, complete, manifest):
        if not complete:
            self.gap(path, "Truncated JSON has no complete structure")
            return
        try:
            value = _strict_json(text)
            shape = json_shape(value)
        except (ValueError, TypeError, RecursionError) as exc:
            self.gap(path, "JSON parse/shape failed: " + str(exc), unknown=True)
            return
        self.fact("json-structure", path, shape=shape)
        if manifest and isinstance(value, dict) and "manifest_version" in value:
            self.result["target_kind"] = "extension"
            fields = ("manifest_version", "name", "version", "permissions", "host_permissions",
                      "background", "content_scripts", "action", "browser_action",
                      "web_accessible_resources", "content_security_policy")
            self.fact("extension-manifest", path,
                      fields={k: value[k] for k in fields if k in value})
            self.result["limitations"].append("Extension manifest is declarative; browser/runtime behavior not observed.")
        else:
            self.result["target_kind"] = "protocol"

    def archive(self, data, path, apk):
        # Check EOCD before ZipFile allocates a central-directory object per member.
        pos = data.rfind(b"PK\x05\x06", max(0, len(data) - 65557))
        if pos < 0 or pos + 22 > len(data):
            self.gap(path, "ZIP end-of-central-directory missing", unknown=True)
            return
        disk, cd_disk, disk_count, count, cd_size, cd_offset, comment = struct.unpack_from("<4H2IH", data, pos + 4)
        if (disk or cd_disk or disk_count != count or count == 65535
                or cd_size == 0xFFFFFFFF or cd_offset == 0xFFFFFFFF):
            self.gap(path, "Multi-disk/ZIP64 archive unsupported", unknown=True)
            return
        if pos + 22 + comment != len(data) or cd_offset + cd_size > pos:
            self.gap(path, "ZIP central-directory bounds invalid", unknown=True)
            return
        self.fact("zip-summary", path, entries_declared=count, compressed_container_bytes=len(data))
        remaining_entries = self.max_entries - self.coverage["entries_examined"]
        if count > remaining_entries:
            self.coverage["entries_omitted"] += count
            self.coverage["truncated"] = True
            self.gap(path, "ZIP entry budget exceeded before central-directory allocation")
            return
        # Count actual records, not just the attacker-controlled EOCD count.
        # Otherwise ZipFile can allocate many more records than the announced cap.
        cursor = cd_offset
        actual_count = 0
        while cursor < cd_offset + cd_size:
            if cursor + 46 > cd_offset + cd_size or data[cursor:cursor + 4] != b"PK\x01\x02":
                self.gap(path, "ZIP central-directory record invalid", unknown=True)
                return
            name_size, extra_size, comment_size, member_disk = struct.unpack_from("<4H", data, cursor + 28)
            compressed, expanded = struct.unpack_from("<II", data, cursor + 20)
            next_cursor = cursor + 46 + name_size + extra_size + comment_size
            if next_cursor > cd_offset + cd_size or member_disk:
                self.gap(path, "ZIP member metadata bounds/disk invalid", unknown=True)
                return
            if compressed == 0xFFFFFFFF or expanded == 0xFFFFFFFF:
                self.gap(path, "ZIP64 member metadata unsupported", unknown=True)
                return
            actual_count += 1
            if actual_count > remaining_entries:
                self.coverage["truncated"] = True
                self.coverage["entries_omitted"] += actual_count
                self.gap(path, "Actual ZIP central-directory count exceeds entry budget")
                return
            cursor = next_cursor
        if actual_count != count:
            self.gap(path, "ZIP declared and actual central-directory counts differ", unknown=True)
            return
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                entries = archive.infolist()
                if len(entries) != count:
                    self.gap(path, "ZIP entry count mismatch", unknown=True)
                    return
                seen = set()
                manifest_seen = False
                for entry in entries:
                    self.coverage["entries_examined"] += 1
                    issues = []
                    if _unsafe_name(entry.orig_filename):
                        issues.append("unsafe-path")
                    if entry.filename in seen:
                        issues.append("duplicate-name")
                    seen.add(entry.filename)
                    if stat.S_ISLNK(entry.external_attr >> 16):
                        issues.append("symlink-entry")
                    if entry.flag_bits & 1:
                        issues.append("encrypted")
                    if entry.file_size > 65536 and entry.file_size > max(1, entry.compress_size) * 1000:
                        issues.append("compression-ratio-limit")
                    remaining = self.max_bytes - self.expanded_reserved
                    if entry.file_size > remaining:
                        issues.append("expanded-byte-budget")
                        self.coverage["truncated"] = True
                    record = {"name": entry.filename, "size": entry.file_size,
                              "compressed_size": entry.compress_size, "issues": issues,
                              "hash_status": "not-read", "sha256": None}
                    payload = None
                    if not issues and not entry.is_dir():
                        # Reserve even failed CRC reads; corrupt members must not
                        # refund expansion budget for an attacker-controlled retry.
                        self.expanded_reserved += entry.file_size
                        self.coverage["expanded_bytes_reserved"] = self.expanded_reserved
                        try:
                            with archive.open(entry) as stream:
                                # A complete CRC-checked member is required for a member hash.
                                payload = stream.read(remaining + 1)
                            self.coverage["expanded_bytes_read"] += len(payload)
                            if len(payload) != entry.file_size or len(payload) > remaining:
                                record["issues"].append("member-size-or-budget-mismatch")
                            else:
                                record["sha256"] = hashlib.sha256(payload).hexdigest()
                                record["hash_status"] = "complete"
                        except (OSError, ValueError, RuntimeError, NotImplementedError, zipfile.BadZipFile) as exc:
                            record["issues"].append("member-read-failed: " + str(exc))
                    elif entry.is_dir() and not issues:
                        record["hash_status"] = "directory"
                    if record["issues"]:
                        self.gap(path + "!" + entry.filename, ", ".join(record["issues"]))
                    self.fact("zip-entry", path, **record)
                    if apk and entry.filename == "AndroidManifest.xml":
                        manifest_seen = True
                        if payload is not None and record["hash_status"] == "complete":
                            if payload.lstrip().startswith(b"<"):
                                try:
                                    xml = payload.decode("utf-8-sig")
                                    package = re.search(r"\bpackage\s*=\s*['\"]([^'\"]+)['\"]", xml)
                                    self.fact("apk-text-manifest", path, entry=entry.filename,
                                              package=package[1] if package else None,
                                              evidence="textual; XML not executed")
                                except UnicodeError:
                                    self.gap(path, "Manifest text encoding unsupported")
                            else:
                                self.gap(path, "Binary Android AXML manifest unsupported")
                if apk and not manifest_seen:
                    self.gap(path, "AndroidManifest.xml missing")
            self.result["limitations"].append("ZIP members never extracted; DEX/resources/native code not decompiled.")
        except (OSError, ValueError, RuntimeError, NotImplementedError, zipfile.BadZipFile) as exc:
            self.gap(path, "ZIP parse failed: " + str(exc), unknown=True)

    def native(self, data, path, suffix):
        def short(kind):
            self.fact("native-header", path, format=kind, complete=False)
            self.gap(path, kind + " header truncated or invalid")
            return True

        if data.startswith(b"MZ"):
            if len(data) < 64:
                return short("PE")
            offset = struct.unpack_from("<I", data, 0x3C)[0]
            if offset < 64 or offset + 24 > len(data) or data[offset:offset + 4] != b"PE\0\0":
                return short("PE")
            machine, sections, timestamp, _, _, optional_size, flags = struct.unpack_from("<HHIIIHH", data, offset + 4)
            if offset + 24 + optional_size > len(data):
                return short("PE")
            self.fact("native-header", path, format="PE", complete=True, machine=machine,
                      sections=sections, timestamp=timestamp, characteristics=flags,
                      pe_offset=offset, optional_header_size=optional_size)
        elif data.startswith(b"\x7fELF"):
            if len(data) < 16 or data[4] not in (1, 2) or data[5] not in (1, 2) or data[6] != 1:
                return short("ELF")
            bits = 32 if data[4] == 1 else 64
            end = "<" if data[5] == 1 else ">"
            expected = 52 if bits == 32 else 64
            if len(data) < expected:
                return short("ELF")
            kind, machine, version = struct.unpack_from(end + "HHI", data, 16)
            entry = struct.unpack_from(end + ("I" if bits == 32 else "Q"), data, 24)[0]
            header_size = struct.unpack_from(end + "H", data, 40 if bits == 32 else 52)[0]
            if version != 1 or header_size != expected:
                return short("ELF")
            self.fact("native-header", path, format="ELF", complete=True, bits=bits,
                      endian="little" if end == "<" else "big", machine=machine,
                      file_type=kind, entry_address=entry)
        elif data[:4] in {b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe"}:
            little = data[:4] in {b"\xce\xfa\xed\xfe", b"\xcf\xfa\xed\xfe"}
            bits = 64 if data[:4] in {b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe"} else 32
            if len(data) < (32 if bits == 64 else 28):
                return short("Mach-O")
            cpu, subtype, file_type, commands, command_bytes, flags = struct.unpack_from(("<" if little else ">") + "6I", data, 4)
            self.fact("native-header", path, format="Mach-O", complete=True, bits=bits,
                      endian="little" if little else "big", cpu_type=cpu, cpu_subtype=subtype,
                      file_type=file_type, load_commands=commands, load_command_bytes=command_bytes, flags=flags)
        elif data[:4] in {b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca", b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca"}:
            if len(data) < 8:
                return short("Mach-O universal")
            endian = ">" if data[0] == 0xCA else "<"
            count = struct.unpack_from(endian + "I", data, 4)[0]
            stride = 32 if data[:4] in {b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca"} else 20
            if count > self.max_entries or 8 + count * stride > len(data):
                return short("Mach-O universal")
            self.fact("native-header", path, format="Mach-O universal", complete=True, architectures=count)
        else:
            return False
        self.result["limitations"].append("Native support identifies bounded headers only; no decompilation or execution.")
        return True


def analyze_path(path, *, max_bytes=1048576, max_entries=5000):
    """Inspect one regular file or a bounded tree, never following filesystem links.

    ``max_bytes`` separately caps source bytes and expanded ZIP-member bytes;
    ``max_entries`` caps visited directory/ZIP entries. Larger ZIP metadata is
    rejected before ZipFile allocates it. All partial/unsupported reads are explicit.
    """
    if (isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0
            or isinstance(max_entries, bool) or not isinstance(max_entries, int) or max_entries <= 0):
        return {"status": "unknown", "target_kind": "generic-file", "facts": [],
                "limitations": [], "unknowns": [{"reason": "Budgets must be positive integers"}],
                "coverage": {"truncated": False, "entries_examined": 0, "bytes_read": 0}}
    analysis = _Analysis(max_bytes, max_entries)
    try:
        root = Path(path)
        # Reject symlink/reparse ancestors too, not just the final component.
        absolute = Path(os.path.abspath(root))
        for part in reversed((absolute, *absolute.parents)):
            if _link(part.lstat()):
                analysis.gap(".", "Symlink or reparse path boundary rejected", unknown=True)
                return analysis.result
        info = root.lstat()
        if _link(info):
            analysis.gap(".", "Symlink or reparse target rejected", unknown=True)
        elif stat.S_ISREG(info.st_mode):
            analysis.file(root, root.name)
        elif stat.S_ISDIR(info.st_mode):
            analysis.result["target_kind"] = "development-component"
            # Iterative depth-first walk: no unbounded listdir/sort allocation.
            stack = [(os.scandir(root), root)]
            try:
                while stack:
                    iterator, directory = stack[-1]
                    try:
                        entry = next(iterator)
                    except StopIteration:
                        iterator.close()
                        stack.pop()
                        continue
                    if analysis.coverage["entries_examined"] >= max_entries:
                        analysis.coverage["entries_omitted"] += 1
                        analysis.coverage["truncated"] = True
                        analysis.gap(".", "Directory entry budget exhausted; omitted count is a lower bound")
                        break
                    analysis.coverage["entries_examined"] += 1
                    child = directory / entry.name
                    relative = child.relative_to(root).as_posix()
                    try:
                        child_stat = entry.stat(follow_symlinks=False)
                        if _link(child_stat):
                            analysis.gap(relative, "Symlink/reparse entry skipped")
                        elif stat.S_ISDIR(child_stat.st_mode):
                            stack.append((os.scandir(child), child))
                        else:
                            analysis.file(child, relative)
                    except OSError as exc:
                        analysis.gap(relative, "Entry read failed: " + str(exc))
            finally:
                for iterator, _ in stack:
                    iterator.close()
            # A tree's classification must not depend on filesystem enumeration
            # order or the last child file parsed. A root manifest is explicit.
            analysis.result["target_kind"] = (
                "extension" if any(f["kind"] == "extension-manifest" and f["path"] == "manifest.json"
                                   for f in analysis.result["facts"])
                else "development-component")
        else:
            analysis.gap(".", "Target is not a regular file or directory", unknown=True)
    except (OSError, TypeError, ValueError) as exc:
        analysis.gap(".", "Target unavailable: " + str(exc), unknown=True)
    analysis.result["limitations"] = list(dict.fromkeys(analysis.result["limitations"]))
    return analysis.result
