"""Explicit local database checkpoints and verified rollback; user objects preserved."""
import contextlib
import os
import sqlite3
from pathlib import Path

from .core import Store, TraceError, canonical, child_path, digest, new_id, parse_json, read_regular


def snapshot(store):
    with contextlib.closing(store.connect()) as db:
        if db.execute('SELECT 1 FROM leases LIMIT 1').fetchone():
            raise TraceError('resource-busy','Release or reconcile all active leases before maintenance')
    identity=new_id('checkpoint')
    directory=child_path(store.root,'checkpoints');directory.mkdir(exist_ok=True)
    temporary=directory/(identity+'.staging')
    try:
        with contextlib.closing(store.connect()) as source:
            with contextlib.closing(sqlite3.connect(temporary)) as target:
                source.backup(target)
                if target.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
                    raise TraceError('integrity-error','Checkpoint SQLite integrity check failed')
        raw=read_regular(temporary,store.limits()['hard_bytes'])
        data=store.put_bytes(None,raw,'L1','database-checkpoint',metadata={'schema_version':1})
        manifest={'schema_version':1,'id':identity,'object_path':data['path'],'sha256':data['sha256'],'size':data['size'],'material_id':data['id'],'purpose':'explicit-database-rollback','limitations':['Only database state rolls back; foreign side effects and source files do not']}
        # Manifest stays outside the DB being rolled back and points at immutable L1.
        path=directory/(identity+'.json')
        with path.open('x',encoding='utf-8') as f:f.write(canonical(manifest)+'\n')
        return manifest
    finally:
        if temporary.exists():temporary.unlink()


def restore(store, checkpoint_id):
    if not isinstance(checkpoint_id,str) or not checkpoint_id.startswith('checkpoint_') or not checkpoint_id[11:].isalnum():
        raise TraceError('invalid-input','Invalid checkpoint ID')
    manifest=parse_json(read_regular(child_path(store.root,'checkpoints/'+checkpoint_id+'.json'),16384))
    raw=read_regular(child_path(store.root,manifest['object_path']),store.limits()['hard_bytes'])
    if digest(raw)!=manifest['sha256'] or len(raw)!=manifest['size']:
        raise TraceError('integrity-error','Checkpoint content does not match its manifest')
    # Offline-only: this check does not lock out other host processes. The caller
    # must stop every host before maintenance; existing leases refuse restore.
    with contextlib.closing(store.connect()) as db:
        if db.execute('SELECT 1 FROM leases LIMIT 1').fetchone():
            raise TraceError('resource-busy','Active leases block restore')
    before=snapshot(store)
    temporary=child_path(store.root,'checkpoints/'+new_id('restore')+'.sqlite3')
    try:
        with temporary.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
        with contextlib.closing(sqlite3.connect(temporary)) as db:
            if db.execute('PRAGMA user_version').fetchone()[0]!=1 or db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
                raise TraceError('unsupported-schema','Checkpoint schema/integrity is not compatible')
            if db.execute('SELECT 1 FROM leases LIMIT 1').fetchone():
                raise TraceError('resource-busy','Checkpoint contains unresolved leases; no silent replay')
        # No live connections are retained by Store. Windows fails closed on a
        # concurrent holder; caller must stop all hosts before maintenance.
        os.replace(temporary,store.path)
        Store(store.root)
        return {'status':'restored','checkpoint_id':checkpoint_id,'rollback_to':before['id'],'preserved_objects':True,'limitations':['All hosts must be stopped before maintenance; no cross-process hot restore guarantee','Foreign side effects were not rolled back']}
    finally:
        if temporary.exists():temporary.unlink()
