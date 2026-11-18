"""Whole selected-workspace census and cooperative growth admission, not OS quota."""
import os
from pathlib import Path
import stat
import time
from .core import TraceError, canonical, child_path, digest, io_path, new_id, parse_json, read_regular

DEFAULT={'hard_bytes':1073741824,'soft_bytes':805306368,'work_bytes':134217728,'max_entries':100000}


def policy(store):
    with store.connect() as db:
        row=db.execute("SELECT value FROM meta WHERE key='workspace_limits'").fetchone()
    return parse_json(row[0]) if row else dict(DEFAULT)


def configure(store,limits):
    chosen={**DEFAULT,**limits}
    if set(chosen)!=set(DEFAULT) or any(type(v) is not int or v<=0 for v in chosen.values()) or chosen['soft_bytes']>chosen['hard_bytes'] or chosen['work_bytes']>chosen['hard_bytes']:
        raise TraceError('invalid-budget','Invalid whole-workspace budget')
    with store.transaction() as db:
        if db.execute('SELECT 1 FROM leases LIMIT 1').fetchone():
            raise TraceError('resource-busy','Active owners block workspace policy revision')
        db.execute("INSERT OR REPLACE INTO meta VALUES('workspace_limits',?)",(canonical(chosen),))
    return chosen


def census(store,*,max_entries=None):
    limit=max_entries or policy(store)['max_entries']
    if type(limit) is not int or not 1<=limit<=1000000:
        raise TraceError('invalid-input','Census entry budget is invalid')
    groups={n:{'bytes':0,'files':0} for n in ('registered_objects','unregistered_objects','database','work','checkpoints','exports','logs','cache','control','unknown')}
    with store.connect() as db:
        objects={r[0] for r in db.execute('SELECT DISTINCT path FROM materials WHERE deleted=0')}
        reservations=[parse_json(r[0]) for r in db.execute("SELECT data FROM records WHERE kind='reservation'")]
    pending=[store.root];seen=0;issues=[];complete=True
    while pending and complete:
        directory=pending.pop()
        try:
            with os.scandir(io_path(directory)) as entries:
                for entry in entries:
                    seen+=1
                    if seen>limit:
                        complete=False;issues.append({'path':'<remaining>','reason':'entry-budget'});break
                    relative=(directory/entry.name).relative_to(store.root).as_posix()
                    try:info=entry.stat(follow_symlinks=False)
                    except FileNotFoundError:
                        issues.append({'path':relative,'reason':'vanished-during-census'});continue
                    if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400:
                        complete=False;issues.append({'path':relative,'reason':'link-not-followed'});continue
                    if stat.S_ISDIR(info.st_mode):pending.append(directory/entry.name);continue
                    # Windows directory enumeration may cache size=0 while a writer
                    # still holds the file open. Query a fresh file handle instead.
                    try:descriptor=os.open(io_path(child_path(store.root,relative)),os.O_RDONLY|getattr(os,'O_BINARY',0)|getattr(os,'O_NOFOLLOW',0))
                    except FileNotFoundError:
                        issues.append({'path':relative,'reason':'vanished-during-census'});continue
                    try:info=os.fstat(descriptor)
                    finally:os.close(descriptor)
                    first=relative.split('/')[0]
                    if first=='objects':category='registered_objects' if relative in objects else 'unregistered_objects'
                    elif first.startswith('state.sqlite3'):category='database'
                    elif first in ('work','checkpoints','exports','logs'):category=first
                    elif first in ('cache','downloads','build','tests'):category='cache'
                    elif first=='traceanchor.workspace.json':category='control'
                    else:category='unknown'
                    groups[category]['bytes']+=info.st_size;groups[category]['files']+=1
        except FileNotFoundError:
            issues.append({'path':str(directory.relative_to(store.root)),'reason':'vanished-during-census'})
        except OSError as exc:
            complete=False;issues.append({'path':str(directory.relative_to(store.root)),'reason':type(exc).__name__})
    total=sum(x['bytes'] for x in groups.values());limits=policy(store)
    reserved=sum(x.get('bytes',0) for x in reservations if x.get('status')=='active')
    return {'categories':groups,'total_bytes':total,'reserved_bytes':reserved,'examined_entries':seen,'complete':complete,'issues':issues[:100],'limits':limits,'soft_exceeded':total+reserved>=limits['soft_bytes'],'hard_exceeded':total+reserved>limits['hard_bytes'],'work_exceeded':groups['work']['bytes']>limits['work_bytes'],'scope':'Only the explicitly selected marker workspace; no links followed or global disk scan','unscanned':'none' if complete else 'Conservative lower bound; new work admission blocked'}


def admit(store,expected_bytes=0):
    if type(expected_bytes) is not int or expected_bytes<0:
        raise TraceError('invalid-input','Expected bytes must be a nonnegative integer')
    usage=census(store)
    if not usage['complete']:
        raise TraceError('workspace-unmeasured','Partial census blocks new large work',usage)
    if usage['total_bytes']+usage['reserved_bytes']+expected_bytes>usage['limits']['hard_bytes']:
        raise TraceError('workspace-budget','Whole owned-workspace hard budget blocks new work',usage)
    if usage['work_exceeded']:
        raise TraceError('work-budget','Owned work growth exceeds the work budget',usage)
    return usage


def reserve(store,owner,expected_bytes,reason):
    """Serialize admission and reservations through the existing SQLite authority."""
    if not isinstance(reason,str) or not reason.strip():
        raise TraceError('invalid-input','Reservation needs a reason')
    identity=new_id('reservation')
    with store.transaction() as db:
        admit(store,expected_bytes)
        if db.execute('SELECT 1 FROM records WHERE id=?',(owner,)).fetchone() is None:
            raise TraceError('not-found','Reservation owner is not a durable record')
        data={'owner':owner,'bytes':expected_bytes,'reason':reason,'status':'active'}
        now=time.time();text=canonical(data)
        db.execute('INSERT INTO records VALUES(?,?,?,?,?,?)',('reservation',identity,None,1,text,now))
        db.execute('INSERT INTO history(kind,id,revision,data,at) VALUES(?,?,?,?,?)',('reservation',identity,1,text,now))
    return store.get('reservation',identity)


def release(store,identity,owner):
    row=store.get('reservation',identity)
    if row['data']['owner']!=owner:raise TraceError('owner-mismatch','Reservation owner mismatch')
    return store.update('reservation',identity,{'status':'released'})


def register_directory(store,relative,case_id,run_id,*,tier='L3',reason='tool-work'):
    if not relative.startswith('work/') or tier not in ('L2','L3'):
        raise TraceError('ownership-unknown','New owned tool directories must be under work/')
    path=child_path(store.root,relative)
    if path.exists():raise TraceError('ownership-unknown','Only a new empty operation directory can be claimed')
    row=store.create('workspace-item',{'path':relative,'run_id':run_id,'tier':tier,'reason':reason,'status':'preparing','pin':False,'recovery':True,'owner':run_id,'local_authority':True,'regeneration':'tool-and-frozen-input-replay'},case_id)
    path.mkdir(parents=True)
    store.add_ref(run_id,row['id'],'owned-workdir')
    return row


def finish_directory(store,identity,status,cleanup):
    row=store.get('workspace-item',identity)
    path=child_path(store.root,row['data']['path']);inventory=[];total=0
    pending=[path]
    while pending:
        directory=pending.pop()
        with os.scandir(io_path(directory)) as entries:
            for entry in entries:
                if len(inventory)>=1000:
                    return store.update('workspace-item',identity,{'status':status,'cleanup':cleanup,'inventory_complete':False,'recovery':True})
                file=child_path(store.root,str((directory/entry.name).relative_to(store.root)))
                if entry.is_dir(follow_symlinks=False):pending.append(file);continue
                info=io_path(file).stat();total+=info.st_size
                if info.st_size>policy(store)['work_bytes']:
                    return store.update('workspace-item',identity,{'status':status,'cleanup':cleanup,'inventory_complete':False,'recovery':True,'bytes_lower_bound':total,'reason':'oversized-file-retained-without-unbounded-hash'})
                inventory.append({'path':file.relative_to(path).as_posix(),'size':info.st_size,'sha256':digest(read_regular(file,max(1,info.st_size))),'nlink':info.st_nlink})
    return store.update('workspace-item',identity,{'status':status,'cleanup':cleanup,'inventory_complete':True,'inventory':inventory,'bytes':total,'recovery':True})


def archive_directory(store,identity,*,reason):
    """Archive real payloads before permitting explicit owned-directory cleanup."""
    row=store.get('workspace-item',identity);data=row['data']
    if not reason or data.get('cleanup',{}).get('state')!='complete' or data.get('status') not in ('completed','failed') or not data.get('inventory_complete'):
        raise TraceError('recovery-not-archived','Directory must have a complete terminal inventory and cleanup receipt')
    root=child_path(store.root,data['path'])
    archived=[]
    for entry in data['inventory']:
        path=child_path(root,entry['path']);info=io_path(path).stat()
        if info.st_nlink!=1:raise TraceError('ownership-unknown','Hardlinked work is retained')
        raw=read_regular(path,max(entry['size'],1))
        if digest(raw)!=entry['sha256']:raise TraceError('integrity-error','Work changed after inventory; retained')
        reserved=reserve(store,identity,len(raw),'archive actual work payload')
        try:blob=store.put_bytes(row['case_id'],raw,'L2','archived-work-payload',data['run_id'],{'relative_path':entry['path'],'recovery_use':True})
        finally:release(store,reserved['id'],identity)
        archived.append({'path':entry['path'],'material_id':blob['id'],'sha256':blob['sha256']})
        store.add_ref(identity,blob['id'],'work-recovery-payload')
    manifest=store.put_bytes(row['case_id'],canonical({'owner':identity,'payloads':archived,'reason':reason}).encode(),'L1','work-recovery-index')
    store.add_ref(identity,manifest['id'],'work-recovery-index')
    return store.update('workspace-item',identity,{'archived_materials':archived,'archive_id':manifest['id'],'recovery':False,'archive_reason':reason})


def clean_directory(store,identity,*,apply=False,cancel=None):
    row=store.get('workspace-item',identity);data=row['data']
    def blocked(reason):return {'id':identity,'eligible':False,'reason':reason,'deleted_bytes':0}
    if not data.get('local_authority'):return blocked('no-local-directory-ownership')
    if data.get('pin'):return blocked('user-pinned')
    if data.get('status') not in ('completed','failed') or data.get('cleanup',{}).get('state')!='complete':return blocked('producer-or-cleanup-active')
    if data.get('recovery') or not data.get('archive_id'):return blocked('unarchived-recovery-payload')
    with store.connect() as db:
        if db.execute('SELECT 1 FROM leases WHERE owner=? OR resource=?',(data['run_id'],data['path'])).fetchone():return blocked('active-lease')
    store.read_material(data['archive_id'])
    for item in data.get('archived_materials',[]):store.read_material(item['material_id'])
    root=child_path(store.root,data['path']);deleted=0;pending=[]
    if not apply:return {'id':identity,'eligible':True,'reason':'actual-payloads-archived','estimated_reclaim_bytes':data.get('bytes',0),'read_only':True}
    for item in data.get('inventory',[]):
        if cancel is not None and cancel.is_set():pending.append(item['path']);continue
        with store.transaction() as db:
            current=store.record(db.execute("SELECT * FROM records WHERE kind='workspace-item' AND id=?",(identity,)).fetchone())['data']
            if current.get('pin') or current.get('recovery') or db.execute('SELECT 1 FROM leases WHERE owner=? OR resource=?',(data['run_id'],data['path'])).fetchone():
                pending.append(item['path']);continue
            path=child_path(root,item['path'])
            if not io_path(path).exists():continue
            if io_path(path).stat().st_nlink!=1 or digest(read_regular(path,max(1,item['size'])))!=item['sha256']:
                pending.append(item['path']);continue
            io_path(path).unlink();deleted+=item['size']
    if io_path(root).exists():
        for directory,dirs,files in os.walk(io_path(root),topdown=False,followlinks=False):
            try:
                relative=Path(directory).relative_to(io_path(root))
                selected=root if not relative.parts else child_path(root,str(relative))
                io_path(selected).rmdir()
            except OSError:pass
    complete=not io_path(root).exists()
    store.update('workspace-item',identity,{'directory_retired':complete,'cleanup_pending':pending,'last_reclaimed_bytes':deleted})
    return {'id':identity,'status':'completed' if complete else 'interrupted-or-unknown-retained','deleted_bytes':deleted,'pending':pending,'unknown_files':'preserved; directory removal only if empty'}


def reconcile_directory(store,identity):
    """Refresh a terminal residual after explicit capacity/policy correction.
    This never changes cleanup unknown into complete or steals a live owner.
    """
    row=store.get('workspace-item',identity);data=row['data']
    run=store.get('run',data['run_id'])
    if run['data'].get('status') not in ('succeeded','failed','cancelled','timed_out','output_limit','abandoned') or run['data'].get('cleanup',{}).get('state')!='complete':
        raise TraceError('resource-busy','Independently complete producer cleanup before residual reconciliation')
    with store.connect() as db:
        if db.execute('SELECT 1 FROM leases WHERE owner=? OR resource=?',(data['run_id'],data['path'])).fetchone():
            raise TraceError('resource-busy','Active residual owner/lease is retained')
    return finish_directory(store,identity,'completed' if run['data']['status']=='succeeded' else 'failed',run['data']['cleanup'])
