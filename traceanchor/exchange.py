"""Atomic admission of portable, untrusted evidence exports. Never imports code."""
import base64
import re
import time

from .core import RECORD_KINDS, TraceError, canonical, child_path, digest, new_id, parse_json, read_regular, value_digest


def import_bundle(store, payload, sha256):
    from .service import _source_name
    if sha256 != value_digest(payload) or payload.get('schema_version') != 1:
        raise TraceError('integrity-error', 'Export digest/schema mismatch')
    records=payload.get('records'); materials=payload.get('materials'); refs=payload.get('refs'); objects=payload.get('objects')
    if not isinstance(records,list) or not records or len(records)>1000 or not isinstance(materials,list) or len(materials)>1000 or not isinstance(refs,list) or len(refs)>5000 or not isinstance(objects,dict):
        raise TraceError('invalid-export','Invalid bounded export inventory')
    if sum(len(canonical(r)) for r in records)>8*1024*1024:
        raise TraceError('over-limit','Export record bytes exceed admission budget')
    ids=set(); case_ids=set(); prepared=[]
    for record in records:
        if not isinstance(record,dict) or record.get('kind') not in RECORD_KINDS-{'gc'} or not isinstance(record.get('id'),str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',record['id']) or record['id'] in ids or not isinstance(record.get('data'),dict):
            raise TraceError('invalid-export','Duplicate or invalid record identity')
        ids.add(record['id'])
        data=parse_json(canonical(record['data']))
        if record['kind']=='case':
            if record.get('case_id') is not None:
                raise TraceError('invalid-export','Case cannot belong to another case')
            case_ids.add(record['id'])
            data['allowed_effects']=['read'];data['status']='active';data.pop('archive_id',None);data['disposition']='imported'
        if record['kind']=='source':
            _source_name(data.get('name'))
            data['path']=None;data['portable_snapshot']=True;data['trust']='imported-untrusted'
        if record['kind']=='verdict':
            data['current']=False;data['stale_reason']='imported-proof-not-local-execution'
        if record['kind']=='observation':data['trust']='imported-untrusted'
        prepared.append((record,data))
    if len(case_ids)!=1:
        raise TraceError('invalid-export','One portable case is required per import')
    for record,_ in prepared:
        if record['kind']!='case' and record.get('case_id') not in case_ids:
            raise TraceError('invalid-export','Record case ownership is outside the export')
    decoded={}; remap={}; total=0
    for material in materials:
        if not isinstance(material,dict) or not isinstance(material.get('id'),str) or material['id'] in remap or material.get('case_id') not in case_ids or material.get('tier') not in {'L1','L2','L3'}:
            raise TraceError('invalid-export','Invalid material ownership or tier')
        try: raw=base64.b64decode(objects[material['id']],validate=True)
        except (ValueError,KeyError,TypeError) as exc: raise TraceError('integrity-error','Invalid export object encoding') from exc
        if digest(raw)!=material.get('sha256') or len(raw)!=material.get('size'):
            raise TraceError('integrity-error','Export object bytes do not match manifest')
        total+=len(raw)
        if total>store.limits()['hard_bytes']:
            raise TraceError('disk-budget','Export exceeds managed object budget')
        decoded[material['id']]=raw;remap[material['id']]=new_id('material')
    if any(data.get('material_id') not in remap for r,data in prepared if r['kind']=='source'):
        raise TraceError('invalid-export','Source snapshot material is missing')
    all_targets=ids|set(remap)
    for ref in refs:
        if not isinstance(ref,dict) or ref.get('owner') not in all_targets or ref.get('target') not in all_targets or not isinstance(ref.get('purpose'),str):
            raise TraceError('invalid-export','Reference graph is outside the admitted export')
    def replace(value):
        if isinstance(value,str):return remap.get(value,value)
        if isinstance(value,list):return [replace(v) for v in value]
        if isinstance(value,dict):return {k:replace(v) for k,v in value.items()}
        return value
    with store.transaction() as db:
        if any(db.execute('SELECT 1 FROM records WHERE id=?',(identity,)).fetchone() for identity in ids):
            raise TraceError('conflict','Import contains existing record IDs; use a fresh workspace')
        limits=parse_json(db.execute("SELECT value FROM meta WHERE key='limits'").fetchone()[0])
        used=db.execute('SELECT COALESCE(SUM(size),0) FROM (SELECT path,MAX(size) size FROM materials WHERE deleted=0 GROUP BY path)').fetchone()[0]
        unique={digest(raw):raw for raw in decoded.values()}
        additional=sum(len(raw) for sha,raw in unique.items() if db.execute('SELECT 1 FROM materials WHERE path=? AND deleted=0 LIMIT 1',(f'objects/{sha[:2]}/{sha}',)).fetchone() is None)
        if used+additional>limits['hard_bytes']:raise TraceError('disk-budget','Import would exceed managed hard budget')
        for old,raw in decoded.items():
            sha=digest(raw);rel=f'objects/{sha[:2]}/{sha}';path=child_path(store.root,rel);path.parent.mkdir(exist_ok=True)
            if path.exists():
                if digest(read_regular(path,limits['hard_bytes']))!=sha:raise TraceError('integrity-error','Existing object is corrupt')
            else:
                with path.open('xb') as f:f.write(raw)
            material=next(m for m in materials if m['id']==old)
            db.execute('INSERT INTO materials(id,case_id,run_id,path,sha256,size,tier,reason,pinned,created,metadata) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(remap[old],material['case_id'],None,rel,sha,len(raw),material['tier'],'imported-evidence',int(bool(material.get('pinned') or material.get('active') or material.get('run_id'))),time.time(),canonical({'external_id':old,'imported_retention': material.get('metadata', '{}')})))
        for record,data in prepared:
            text=canonical(replace(data));now=time.time()
            db.execute('INSERT INTO records VALUES(?,?,?,?,?,?)',(record['kind'],record['id'],record.get('case_id'),1,text,now))
            db.execute('INSERT INTO history(kind,id,revision,data,at) VALUES(?,?,?,?,?)',(record['kind'],record['id'],1,text,now))
        for ref in refs:
            db.execute('INSERT OR IGNORE INTO refs VALUES(?,?,?)',(remap.get(ref['owner'],ref['owner']),remap.get(ref['target'],ref['target']),ref['purpose']))
    return {'imported_records':len(records),'imported_materials':len(materials),'trust':'imported-untrusted','verdicts_current':False,'effects_reset':['read']}
