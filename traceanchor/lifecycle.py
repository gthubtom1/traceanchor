"""Three-tier storage governance; never infers ownership from directory names."""
from __future__ import annotations

import contextlib
import os
import stat
import time

from .core import Store, TraceError, canonical, child_path, digest, new_id, read_regular


def usage(store: Store):
    with contextlib.closing(store.connect()) as db:
        rows = db.execute("SELECT tier,COUNT(*) count,COALESCE(SUM(size),0) bytes FROM materials WHERE deleted=0 GROUP BY tier").fetchall()
        physical = db.execute("SELECT COALESCE(SUM(size),0) FROM (SELECT path,MAX(size) size FROM materials WHERE deleted=0 GROUP BY path)").fetchone()[0]
        leases = [dict(r) for r in db.execute("SELECT * FROM leases")]
    levels = {tier: {"count": 0, "bytes": 0} for tier in ("L1", "L2", "L3")}
    levels.update({r["tier"]: {"count": r["count"], "bytes": r["bytes"]} for r in rows})
    limits = store.limits()
    return {"tiers": levels, "physical_registered_bytes": physical, "limits": limits, "soft_exceeded": physical >= limits["soft_bytes"], "leases": leases, "scope": "Registered owned material bytes; database, working directories and unregistered files are not falsely counted as managed objects"}


def _decision(store, db, row, now, min_age):
    if row["deleted"]:
        return False, "already-deleted"
    if row["tier"] == "L1":
        return False, "long-term-asset"
    if row["pinned"]:
        return False, "user-pinned"
    if row["active"]:
        return False, "active-material"
    from .core import parse_json
    if parse_json(row['metadata']).get('recovery_use'):
        return False, 'unreleased-recovery-dependency'
    if now - row["created"] < min_age:
        return False, "retention-period"
    if db.execute("SELECT 1 FROM refs WHERE target=? LIMIT 1", (row["id"],)).fetchone():
        return False, "referenced-evidence-or-recovery"
    if row["run_id"]:
        run = db.execute("SELECT data FROM records WHERE kind='run' AND id=?", (row["run_id"],)).fetchone()
        if run is None:
            return False, "producer-state-unknown"
        from .core import parse_json
        data = parse_json(run[0])
        if data.get("status") not in {"succeeded", "failed", "cancelled", "timed_out", "output_limit", "abandoned"} or data.get("cleanup", {}).get("state") != "complete":
            return False, "producer-or-cleanup-active"
    if db.execute("SELECT 1 FROM leases WHERE owner IN (?,?) OR resource IN (?,?) LIMIT 1", (row["id"], row["run_id"] or "", row["id"], row["path"])).fetchone():
        return False, "active-lease"
    if row["tier"] == "L2":
        from .core import parse_json
        case = db.execute("SELECT data FROM records WHERE kind='case' AND id=?", (row["case_id"],)).fetchone()
        if case is None:
            return False, "case-state-unknown"
        data = parse_json(case[0])
        if data.get("status") != "closed" or data.get("disposition") != "accepted" or not data.get("archive_id"):
            return False, "case-not-accepted-and-archived"
        try:
            store.read_material(data["archive_id"])
        except TraceError:
            return False, "archive-integrity-unconfirmed"
    try:
        path = child_path(store.root, row["path"])
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            return False, "file-ownership-ambiguous"
        if info.st_size != row["size"] or digest(read_regular(path, max(row["size"], 1))) != row["sha256"]:
            return False, "material-modified-or-corrupt"
    except (OSError, TraceError):
        return False, "path-or-integrity-unknown"
    return True, "eligible-" + row["tier"]


def preview(store: Store, *, min_age=0, max_items=1000):
    if not isinstance(min_age, (int, float)) or min_age < 0 or not 1 <= max_items <= 1000:
        raise TraceError("invalid-input", "Invalid cleanup age or item budget")
    now = time.time()
    result = []
    with contextlib.closing(store.connect()) as db:
        rows = db.execute("SELECT * FROM materials WHERE deleted=0 ORDER BY CASE tier WHEN 'L3' THEN 0 WHEN 'L2' THEN 1 ELSE 2 END,created,id LIMIT ?", (max_items,)).fetchall()
        for row in rows:
            eligible, reason = _decision(store, db, row, now, min_age)
            sharing = db.execute("SELECT COUNT(*) FROM materials WHERE path=? AND deleted=0 AND id<>?", (row["path"], row["id"])).fetchone()[0]
            result.append({"id": row["id"], "tier": row["tier"], "bytes": row["size"], "eligible": eligible, "reason": reason, "physical_bytes": 0 if sharing else row["size"]})
        total = db.execute("SELECT COUNT(*) FROM materials WHERE deleted=0").fetchone()[0]
    return {"items": result, "examined": len(result), "total": total, "truncated": total > len(result), "estimated_reclaim_bytes": sum(r["physical_bytes"] for r in result if r["eligible"]), "read_only": True, "unknown_unregistered_files": "preserved; not scanned or selected"}


def clean(store: Store, *, ids=None, min_age=0, max_items=100, max_seconds=5, cancel=None):
    if not 1 <= max_items <= 1000 or not 0 < max_seconds <= 60:
        raise TraceError("invalid-input", "Cleanup must have a finite item/time budget")
    candidates = preview(store, min_age=min_age, max_items=max_items)
    selected = set(ids) if ids is not None else {r["id"] for r in candidates["items"] if r["eligible"] and r["tier"] == "L3"}
    # Default automatic cleanup is L3 only; explicit IDs permit eligible archived L2.
    if not selected.issubset({r["id"] for r in candidates["items"]}):
        raise TraceError("invalid-input", "Cleanup IDs must be in the bounded current preview")
    gc = store.create("gc", {"status": "active", "requested": sorted(selected), "results": []})
    results, reclaimed = [], 0
    started = time.monotonic()
    for identity in sorted(selected):
        if time.monotonic() - started >= max_seconds or cancel is not None and cancel.is_set():
            break
        with store.transaction() as db:
            row = db.execute("SELECT * FROM materials WHERE id=?", (identity,)).fetchone()
            if row is None:
                results.append({"id": identity, "status": "kept", "reason": "unknown-owner"})
                continue
            eligible, reason = _decision(store, db, row, time.time(), min_age)
            if not eligible:
                results.append({"id": identity, "status": "kept", "reason": reason})
                continue
            shared = db.execute("SELECT 1 FROM materials WHERE path=? AND deleted=0 AND id<>? LIMIT 1", (row["path"], identity)).fetchone()
            # The transaction serializes new references/promotions with this decision.
            # A committed tombstone before unlink makes a crash conservatively leak bytes,
            # not lose an admitted live object. Physical unlink is then rechecked below.
            db.execute("UPDATE materials SET deleted=1 WHERE id=?", (identity,))
        status = "retired-shared" if shared else "deleted"
        if not shared:
            try:
                with store.transaction() as db:
                    if db.execute("SELECT 1 FROM materials WHERE path=? AND deleted=0 LIMIT 1", (row["path"],)).fetchone():
                        status = "retired-shared"
                    else:
                        path = child_path(store.root, row["path"])
                        if path.stat().st_nlink != 1 or digest(read_regular(path, max(1, row["size"]))) != row["sha256"]:
                            raise TraceError("integrity-error", "Cleanup object changed before unlink")
                        path.unlink()
                        reclaimed += row["size"]
            except (OSError, TraceError) as exc:
                status = "retired-retained-bytes"
                reason = str(exc)
        results.append({"id": identity, "status": status, "reason": reason})
        store.update("gc", gc["id"], {"results": results})
    pending = sorted(selected - {r["id"] for r in results})
    return store.update("gc", gc["id"], {"status": "interrupted" if pending else "completed", "results": results, "pending": pending, "reclaimed_bytes": reclaimed})


def promote(store, identity, *, owner=None):
    with store.transaction() as db:
        material = db.execute("SELECT * FROM materials WHERE id=? AND deleted=0", (identity,)).fetchone()
        if material is None:
            raise TraceError("integrity-error", "Cannot promote a missing or retired material")
        raw = read_regular(child_path(store.root, material["path"]), max(1, material["size"]))
        if digest(raw) != material["sha256"] or len(raw) != material["size"]:
            raise TraceError("integrity-error", "Cannot promote corrupt material")
        if owner and db.execute("SELECT 1 FROM records WHERE id=? UNION SELECT 1 FROM materials WHERE id=? AND deleted=0", (owner, owner)).fetchone() is None:
            raise TraceError("not-found", "Promotion reference owner was not found")
        changed = db.execute("UPDATE materials SET tier='L1',reason='promoted-evidence' WHERE id=? AND deleted=0", (identity,)).rowcount
        if changed != 1:
            raise TraceError("revision-conflict", "Material changed while promoting")
        if owner:
            db.execute("INSERT OR IGNORE INTO refs VALUES(?,?,?)", (owner, identity, "evidence"))
    return store.material(identity)


def release_recovery(store, identity, *, reason):
    """Explicitly archive the actual recovery bytes before retiring protection."""
    if not isinstance(reason, str) or not reason.strip():
        raise TraceError('invalid-input', 'Reviewed recovery release requires a reason')
    material = store.material(identity)
    if not material['metadata'].get('recovery_use') or material['deleted']:
        raise TraceError('recovery-not-active', 'Material has no active recovery obligation')
    case = store.get('case', material['case_id'])
    if case['data'].get('status') != 'closed' or case['data'].get('disposition') != 'accepted':
        raise TraceError('recovery-not-archived', 'Accept and archive the owning case before releasing recovery')
    store.read_material(case['data']['archive_id'])
    raw = store.read_material(identity)
    archived = store.put_bytes(material['case_id'], raw, 'L1', 'archived-recovery-payload', metadata={'source_material_id': identity, 'reason': reason})
    from .core import parse_json
    with store.transaction() as db:
        row = db.execute('SELECT * FROM materials WHERE id=? AND deleted=0', (identity,)).fetchone()
        if row is None or not parse_json(row['metadata']).get('recovery_use'):
            raise TraceError('revision-conflict', 'Recovery state changed; immutable archive was retained')
        if row['run_id']:
            run = store.record(db.execute("SELECT * FROM records WHERE kind='run' AND id=?", (row['run_id'],)).fetchone())
            if run['data'].get('cleanup', {}).get('state') != 'complete' or run['data'].get('status') not in {'succeeded','failed','cancelled','timed_out','output_limit','abandoned'}:
                raise TraceError('resource-busy', 'Producer cleanup must be complete')
        if db.execute('SELECT 1 FROM leases WHERE owner IN (?,?) OR resource IN (?,?)', (identity,row['run_id'] or '',identity,row['path'])).fetchone():
            raise TraceError('resource-busy', 'Recovery material is leased')
        store.read_material(archived['id'])
        data = parse_json(row['metadata'])
        data.update(recovery_use=False, recovery_archive_id=archived['id'], recovery_release_reason=reason)
        db.execute('INSERT OR IGNORE INTO refs VALUES(?,?,?)', (material['case_id'], archived['id'], 'archived-recovery-payload'))
        db.execute('UPDATE materials SET metadata=? WHERE id=?', (canonical(data),identity))
        db.execute("DELETE FROM refs WHERE target=? AND purpose='recovery-protection'", (identity,))
    store.event(material['case_id'], 'recovery-released', {'material_id': identity, 'archived_material_id': archived['id'], 'reason': reason})
    return {'material_id': identity, 'archived_material_id': archived['id'], 'status': 'recovery-archived-and-released'}


def pin(store, identity, pinned=True):
    with store.transaction() as db:
        material = db.execute("SELECT * FROM materials WHERE id=? AND deleted=0", (identity,)).fetchone()
        if material is None:
            raise TraceError("integrity-error", "Cannot pin a missing or retired material")
        raw = read_regular(child_path(store.root, material["path"]), max(1, material["size"]))
        if digest(raw) != material["sha256"]:
            raise TraceError("integrity-error", "Cannot pin corrupt material")
        if db.execute("UPDATE materials SET pinned=? WHERE id=? AND deleted=0", (int(bool(pinned)), identity)).rowcount != 1:
            raise TraceError("revision-conflict", "Material changed while pinning")
    return store.material(identity)
