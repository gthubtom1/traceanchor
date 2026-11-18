"""Transactional case records and owned, content-addressed materials.

No model, provider, target execution or global configuration belongs here.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import sqlite3
import stat
import time
import uuid
from pathlib import Path

SCHEMA_VERSION = 1
RECORD_KINDS = frozenset({"case", "source", "observation", "spec", "run", "verdict", "unknown", "route", "subtask-result", "gc", "checkpoint", "workspace-item", "reservation"})
DEFAULT_LIMITS = {"hard_bytes": 256 * 1024 * 1024, "soft_bytes": 192 * 1024 * 1024, "temp_bytes": 64 * 1024 * 1024}


class TraceError(Exception):
    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details or {}

    def as_dict(self):
        return {"code": self.code, "message": self.message, "details": self.details}


def canonical(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (ValueError, TypeError, RecursionError) as exc:
        raise TraceError("invalid-json", "Expected finite, bounded JSON data") from exc


def digest(data):
    return hashlib.sha256(data).hexdigest()


def value_digest(value):
    return digest(canonical(value).encode("utf-8"))


def parse_json(text):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise TraceError("invalid-json", f"Duplicate JSON key: {key}")
            result[key] = value
        return result
    try:
        return json.loads(text, object_pairs_hook=unique, parse_constant=lambda v: (_ for _ in ()).throw(ValueError(v)))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise TraceError("invalid-json", "Input is not valid finite JSON") from exc


def new_id(kind):
    return kind.replace("-", "_") + "_" + uuid.uuid4().hex


def io_path(path):
    """Native Windows long-path spelling for IO only, never logical identities.

    Keep normal relative paths in records and tool commands. This neither grants
    ownership nor bypasses no_links/child_path checks.
    """
    path = Path(os.path.abspath(path))
    text = str(path)
    prefix = chr(92) * 2 + '?' + chr(92)
    if os.name != 'nt' or text.startswith(prefix):
        return path
    if text.startswith(chr(92) * 2):
        return Path(prefix + 'UNC' + chr(92) + text[2:])
    return Path(prefix + text)


def no_links(path):
    """Reject symlinks and Windows reparse/junction ancestors before resolving."""
    path = Path(os.path.abspath(path))
    for part in [*reversed(path.parents), path]:
        try:
            info = io_path(part).lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise TraceError("unsafe-path", "Linked/reparse paths are not admitted", {"name": part.name})
    return path


def child_path(root, relative):
    rel = Path(relative)
    if rel.is_absolute() or not rel.parts or any(p in ("..", ".") or ":" in p or "\x00" in p for p in rel.parts):
        raise TraceError("unsafe-path", "Expected a contained relative path")
    result = no_links(Path(root) / rel)
    if not result.is_relative_to(Path(root).absolute()):
        raise TraceError("unsafe-path", "Path is outside the owned workspace")
    return result


def read_regular(path, limit=64 * 1024 * 1024):
    path = no_links(path)
    native = io_path(path)
    try:
        info = native.stat()
        if not stat.S_ISREG(info.st_mode):
            raise TraceError("invalid-input", "Only regular files are accepted")
        if info.st_size > limit:
            raise TraceError("over-limit", "File exceeds the admitted read budget", {"size": info.st_size, "limit": limit})
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        with os.fdopen(os.open(native, flags), "rb") as stream:
            initial = os.fstat(stream.fileno())
            data = stream.read(limit + 1)
            after = os.fstat(stream.fileno())
        current = native.stat()
        # Python 3.12 Windows fstat exposes change time while stat may expose
        # creation time as st_ctime; do not compare incompatible clock meanings.
        identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns) + (() if os.name == "nt" else (s.st_ctime_ns,))
        if len(data) > limit or len(data) != initial.st_size or identity(initial) != identity(after) or identity(initial) != identity(current):
            raise TraceError("source-changed", "File changed during its bounded read")
        return data
    except OSError as exc:
        raise TraceError("file-error", "Could not read the selected regular file", {"error": str(exc), "name": path.name}) from exc


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


class Store:
    def __init__(self, root, create=False, limits=None):
        self.root = no_links(root)
        if limits is not None:
            if not isinstance(limits, dict) or set(limits) != set(DEFAULT_LIMITS) or any(type(v) is not int or v <= 0 for v in limits.values()) or limits["soft_bytes"] > limits["hard_bytes"] or limits["temp_bytes"] > limits["hard_bytes"]:
                raise TraceError("invalid-budget", "Workspace limits require positive integer hard/soft/temp bytes with soft and temp no greater than hard")
        if create:
            self.root.mkdir(parents=True, exist_ok=True)
            marker = self.root / "traceanchor.workspace.json"
            if not marker.exists():
                if any(self.root.iterdir()):
                    raise TraceError("ownership-unknown", "Existing nonempty directory is not a TraceAnchor workspace")
                with marker.open("x", encoding="utf-8") as stream:
                    stream.write(canonical({"schema_version": 1, "owner": "traceanchor", "workspace_id": new_id("workspace")}))
        marker = self.root / "traceanchor.workspace.json"
        if not marker.is_file():
            raise TraceError("workspace-missing", "Initialize an explicit workspace first")
        marker_data = parse_json(read_regular(marker, 4096))
        if marker_data.get("schema_version") != 1 or marker_data.get("owner") != "traceanchor":
            raise TraceError("unsupported-schema", "Workspace marker is not supported")
        for name in ("objects", "work"):
            child_path(self.root, name).mkdir(exist_ok=True)
        self.path = child_path(self.root, "state.sqlite3")
        existed = self.path.exists()
        if existed and not stat.S_ISREG(self.path.stat().st_mode):
            raise TraceError("unsafe-path", "Database is not a regular file")
        try:
            with self.connect() as db:
                version = db.execute("PRAGMA user_version").fetchone()[0]
                if existed and version != SCHEMA_VERSION:
                    raise TraceError("unsupported-schema", "Database version is not writable by this release", {"version": version})
                if not existed:
                    db.executescript("""
                    CREATE TABLE records(kind TEXT NOT NULL,id TEXT PRIMARY KEY,case_id TEXT,revision INTEGER NOT NULL,data TEXT NOT NULL,created REAL NOT NULL);
                    CREATE INDEX records_by_case ON records(case_id,kind);
                    CREATE TABLE history(seq INTEGER PRIMARY KEY AUTOINCREMENT,kind TEXT,id TEXT,revision INTEGER,data TEXT,at REAL);
                    CREATE TABLE events(seq INTEGER PRIMARY KEY AUTOINCREMENT,case_id TEXT,action TEXT,data TEXT,at REAL);
                    CREATE TABLE materials(id TEXT PRIMARY KEY,case_id TEXT,run_id TEXT,path TEXT NOT NULL,sha256 TEXT NOT NULL,size INTEGER NOT NULL,tier TEXT NOT NULL,reason TEXT NOT NULL,pinned INTEGER NOT NULL DEFAULT 0,active INTEGER NOT NULL DEFAULT 0,deleted INTEGER NOT NULL DEFAULT 0,created REAL NOT NULL,metadata TEXT NOT NULL);
                    CREATE INDEX materials_path ON materials(path,deleted);
                    CREATE TABLE refs(owner TEXT NOT NULL,target TEXT NOT NULL,purpose TEXT NOT NULL,PRIMARY KEY(owner,target,purpose));
                    CREATE INDEX refs_target ON refs(target);
                    CREATE TABLE leases(resource TEXT PRIMARY KEY,owner TEXT NOT NULL,created REAL NOT NULL);
                    CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                    PRAGMA user_version=1;
                    """)
                    db.execute("INSERT INTO meta VALUES('limits',?)", (canonical(limits or DEFAULT_LIMITS),))
                db.execute("SELECT kind FROM records LIMIT 1")
        except sqlite3.DatabaseError as exc:
            raise TraceError("database-error", "Database is corrupt, unavailable or incompatible; it was not reset", {"error": str(exc)}) from exc

    def connect(self):
        db = sqlite3.connect(self.path, timeout=5, isolation_level=None, factory=ClosingConnection)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=5000")
        return db

    @contextlib.contextmanager
    def transaction(self):
        db = self.connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.execute("COMMIT")
        except sqlite3.OperationalError as exc:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise TraceError("storage-error", "Transactional storage failed; operation not acknowledged", {"error": str(exc)}) from exc
        except BaseException:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        finally:
            db.close()

    @staticmethod
    def record(row):
        if row is None:
            raise TraceError("not-found", "Record was not found")
        return {"id": row["id"], "kind": row["kind"], "case_id": row["case_id"], "revision": row["revision"], "data": parse_json(row["data"]), "created": row["created"]}

    def create(self, kind, data, case_id=None, id=None):
        if kind not in RECORD_KINDS or not isinstance(data, dict):
            raise TraceError("invalid-input", "Unsupported record kind or payload")
        identity = id or new_id(kind)
        text = canonical(data)
        if len(text.encode("utf-8")) > 4 * 1024 * 1024:
            raise TraceError("over-limit", "Record exceeds 4MiB; put large bytes in material storage")
        from .workspace import admit
        if kind not in {'gc','reservation','workspace-item'}:
            admit(self,len(text.encode('utf-8'))+8192)
        with self.transaction() as db:
            if case_id is not None and db.execute("SELECT id FROM records WHERE kind='case' AND id=?", (case_id,)).fetchone() is None:
                raise TraceError("not-found", "Case was not found")
            now = time.time()
            try:
                db.execute("INSERT INTO records VALUES(?,?,?,?,?,?)", (kind, identity, case_id, 1, text, now))
            except sqlite3.IntegrityError as exc:
                raise TraceError("conflict", "Record ID already exists") from exc
            db.execute("INSERT INTO history(kind,id,revision,data,at) VALUES(?,?,?,?,?)", (kind, identity, 1, text, now))
        return self.get(kind, identity)

    def get(self, kind, identity):
        with contextlib.closing(self.connect()) as db:
            return self.record(db.execute("SELECT * FROM records WHERE kind=? AND id=?", (kind, identity)).fetchone())

    def list(self, kind, case_id=None, limit=1000):
        if kind not in RECORD_KINDS:
            raise TraceError("invalid-input", "Unknown record kind")
        limit = max(1, min(int(limit), 1000))
        with contextlib.closing(self.connect()) as db:
            rows = db.execute("SELECT * FROM records WHERE kind=? AND (? IS NULL OR case_id=?) ORDER BY created,id LIMIT ?", (kind, case_id, case_id, limit)).fetchall()
            return [self.record(row) for row in rows]

    def update(self, kind, identity, changes, expected_revision=None):
        if not isinstance(changes, dict):
            raise TraceError("invalid-input", "Changes must be an object")
        with self.transaction() as db:
            old = self.record(db.execute("SELECT * FROM records WHERE kind=? AND id=?", (kind, identity)).fetchone())
            if expected_revision is not None and old["revision"] != expected_revision:
                raise TraceError("revision-conflict", "Record changed since it was read", {"actual_revision": old["revision"]})
            data = {**old["data"], **changes}
            text = canonical(data)
            if len(text.encode("utf-8")) > 4 * 1024 * 1024:
                raise TraceError("over-limit", "Record exceeds storage limit")
            revision = old["revision"] + 1
            db.execute("UPDATE records SET data=?,revision=? WHERE id=?", (text, revision, identity))
            db.execute("INSERT INTO history(kind,id,revision,data,at) VALUES(?,?,?,?,?)", (kind, identity, revision, text, time.time()))
        return self.get(kind, identity)

    def event(self, case_id, action, data):
        with self.transaction() as db:
            text = canonical(data)
            if len(text.encode("utf-8")) > 65536:
                raise TraceError("over-limit", "Event exceeds 64KiB; store large evidence as a material")
            db.execute("INSERT INTO events(case_id,action,data,at) VALUES(?,?,?,?)", (case_id, action, text, time.time()))
            # Bounded diagnostic journal; record history and L1 evidence are separate.
            db.execute("DELETE FROM events WHERE seq <= (SELECT COALESCE(MAX(seq),0)-10000 FROM events)")

    def add_ref(self, owner, target, purpose="evidence"):
        with self.transaction() as db:
            exists = db.execute("SELECT id FROM materials WHERE id=? AND deleted=0 UNION SELECT id FROM records WHERE id=?", (target, target)).fetchone()
            if exists is None:
                raise TraceError("integrity-error", "Reference target does not exist")
            db.execute("INSERT OR IGNORE INTO refs VALUES(?,?,?)", (owner, target, purpose))

    def remove_ref(self, owner, target, purpose=None):
        with self.transaction() as db:
            db.execute("DELETE FROM refs WHERE owner=? AND target=? AND (? IS NULL OR purpose=?)", (owner, target, purpose, purpose))

    def acquire(self, resource, owner):
        with self.transaction() as db:
            try:
                db.execute("INSERT INTO leases VALUES(?,?,?)", (resource, owner, time.time()))
            except sqlite3.IntegrityError as exc:
                row = db.execute("SELECT owner FROM leases WHERE resource=?", (resource,)).fetchone()
                raise TraceError("resource-busy", "Resource has an existing lease; reconcile instead of stealing it", {"owner": row[0]}) from exc

    def release(self, resource, owner):
        with self.transaction() as db:
            db.execute("DELETE FROM leases WHERE resource=? AND owner=?", (resource, owner))

    def limits(self):
        with contextlib.closing(self.connect()) as db:
            return parse_json(db.execute("SELECT value FROM meta WHERE key='limits'").fetchone()[0])

    def put_bytes(self, case_id, data, tier="L1", reason="evidence", run_id=None, metadata=None):
        if tier not in {"L1", "L2", "L3"} or not isinstance(data, bytes):
            raise TraceError("invalid-input", "Invalid material bytes or lifecycle tier")
        sha = digest(data)
        relative = f"objects/{sha[:2]}/{sha}"
        path = child_path(self.root, relative)
        material_id = new_id("material")
        with contextlib.closing(self.connect()) as check:
            limits_now = parse_json(check.execute("SELECT value FROM meta WHERE key='limits'").fetchone()[0])
            used_now = check.execute("SELECT COALESCE(SUM(size),0) FROM (SELECT path,MAX(size) size FROM materials WHERE deleted=0 GROUP BY path)").fetchone()[0]
            live_path = check.execute("SELECT 1 FROM materials WHERE path=? AND deleted=0 LIMIT 1", (relative,)).fetchone()
        if used_now + (0 if live_path else len(data)) > limits_now["hard_bytes"]:
            from .lifecycle import clean
            clean(self, max_items=1000)  # Only eligible L3, never L1 or unarchived L2.
        with self.transaction() as db:
            limits = parse_json(db.execute("SELECT value FROM meta WHERE key='limits'").fetchone()[0])
            used = db.execute("SELECT COALESCE(SUM(size),0) FROM (SELECT path,MAX(size) size FROM materials WHERE deleted=0 GROUP BY path)").fetchone()[0]
            exists = path.exists()
            registered = db.execute("SELECT 1 FROM materials WHERE path=? AND deleted=0 LIMIT 1", (relative,)).fetchone()
            extra = 0 if registered else len(data)
            from .workspace import admit
            # The same transaction serializes all product object admissions, not
            # only CAS quota. Include actual database/work/checkpoints/unknown.
            admit(self,extra)
            if used + extra > limits["hard_bytes"]:
                raise TraceError("disk-budget", "Managed material hard budget exceeded; preserve evidence and clean eligible L3 first", {"used": used, "requested": extra, "hard_bytes": limits["hard_bytes"]})
            if tier == "L3":
                temp = db.execute("SELECT COALESCE(SUM(size),0) FROM materials WHERE tier='L3' AND deleted=0").fetchone()[0]
                if temp + len(data) > limits["temp_bytes"]:
                    raise TraceError("temp-budget", "Temporary material budget exceeded")
            path.parent.mkdir(exist_ok=True)
            if exists:
                if digest(read_regular(path, limits["hard_bytes"])) != sha:
                    raise TraceError("integrity-error", "Existing content-addressed object is corrupt")
            else:
                # Unregistered partial files after crashes are conservatively preserved by GC.
                try:
                    with path.open("xb") as stream:
                        stream.write(data)
                        stream.flush()
                        os.fsync(stream.fileno())
                except OSError as exc:
                    raise TraceError("write-error", "Material write failed; any partial object is not admitted", {"error": str(exc)}) from exc
            db.execute("INSERT INTO materials(id,case_id,run_id,path,sha256,size,tier,reason,created,metadata) VALUES(?,?,?,?,?,?,?,?,?,?)", (material_id, case_id, run_id, relative, sha, len(data), tier, reason, time.time(), canonical(metadata or {})))
            if (metadata or {}).get('recovery_use'):
                owner = run_id or case_id
                if not owner or db.execute('SELECT 1 FROM records WHERE id=?', (owner,)).fetchone() is None:
                    raise TraceError('recovery-owner-required', 'Recovery payload requires a durable case or run owner')
                db.execute('INSERT INTO refs VALUES(?,?,?)', (owner, material_id, 'recovery-protection'))
        return self.material(material_id)

    def material(self, identity):
        with contextlib.closing(self.connect()) as db:
            row = db.execute("SELECT * FROM materials WHERE id=?", (identity,)).fetchone()
        if row is None:
            raise TraceError("not-found", "Material was not found")
        result = dict(row)
        result["metadata"] = parse_json(result["metadata"])
        return result

    def read_material(self, identity):
        row = self.material(identity)
        if row["deleted"]:
            raise TraceError("integrity-error", "Referenced material was deleted")
        data = read_regular(child_path(self.root, row["path"]), max(self.limits()["hard_bytes"], row["size"]))
        if len(data) != row["size"] or digest(data) != row["sha256"]:
            raise TraceError("integrity-error", "Material integrity check failed", {"material_id": identity})
        return data

    def invalidate(self, case_id, reason, visited=None):
        visited = visited or set()
        if case_id in visited:
            return
        visited.add(case_id)
        for verdict in self.list("verdict", case_id):
            if verdict["data"].get("current", True):
                self.update("verdict", verdict["id"], {"current": False, "stale_reason": reason})
        case = self.get("case", case_id)
        if case["data"].get("status") == "closed" and case["data"].get("disposition") == "accepted":
            self.update("case", case_id, {"disposition": "stale", "stale_reason": reason})
        self.event(case_id, "invalidated", {"reason": reason})
        if case["data"].get("parent_id"):
            self.invalidate(case["data"]["parent_id"], "subtask-dependency: " + reason, visited)

    def check_source(self, source_id):
        source = self.get("source", source_id)
        data = source["data"]
        blob = self.read_material(data["material_id"])
        if digest(blob) != data["sha256"]:
            raise TraceError("integrity-error", "Source snapshot does not match its identity")
        if data.get("path"):
            try:
                fresh = digest(read_regular(data["path"], self.limits()["hard_bytes"])) == data["sha256"]
            except TraceError:
                fresh = False
            if not fresh:
                self.invalidate(source["case_id"], "source-changed:" + source_id)
                raise TraceError("stale-source", "Selected source changed or became unreadable; register a new revision", {"source_id": source_id})
        return source
