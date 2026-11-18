"""Cooperative, project-local exclusive file claims; no TTL takeover.
Bootstrap: the sole integrator creates this utility, then immediately claims its
own file and the integration files. This does not lock out noncooperating editors.
"""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from traceanchor.core import TraceError, canonical, no_links
AREA=ROOT/'.coordination'


def normalize(value):
    p=Path(value)
    if p.is_absolute() or not p.parts or any(x in ('.','..') or ':' in x for x in p.parts):
        raise TraceError('claim-path','Use exact product-relative files or directories')
    no_links(ROOT/p)
    return p.as_posix()


def fingerprint(relative):
    path=no_links(ROOT/relative)
    if not path.exists():return None
    if path.is_file():return {'kind':'file','sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    rows={}
    for file in sorted(path.rglob('*')):
        if set(file.relative_to(ROOT).parts)&{'.git','.coordination','.validation','__pycache__'}:continue
        no_links(file)
        if file.is_file():rows[file.relative_to(path).as_posix()]=hashlib.sha256(file.read_bytes()).hexdigest()
    return {'kind':'directory','sha256':hashlib.sha256(canonical(rows).encode()).hexdigest()}


@contextlib.contextmanager
def registry():
    no_links(AREA);AREA.mkdir(exist_ok=True)
    lock=AREA/'registry.lock'
    try:fd=os.open(lock,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    except FileExistsError:raise TraceError('claim-registry-busy','Existing registry lock is preserved; verify its owner, never steal by TTL')
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            f.write(canonical({'pid':os.getpid(),'created':time.time()}));f.flush();os.fsync(f.fileno())
        path=AREA/'claims.json'
        state=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'schema_version':1,'claims':{},'history':[]}
        if state.get('schema_version')!=1:raise TraceError('claim-schema','Unsupported registry; preserved')
        yield state
        temporary=AREA/('registry-'+uuid.uuid4().hex+'.staging')
        with temporary.open('x',encoding='utf-8') as f:
            f.write(canonical(state)+'\n');f.flush();os.fsync(f.fileno())
        os.replace(temporary,path)
    finally:lock.unlink()


def operate(action,owner=None,task=None,paths=None,claim_id=None,reason=None):
    with registry() as state:
        if action=='list':return state
        if not isinstance(owner,str) or not owner.strip():raise TraceError('claim-owner','Explicit owner required')
        if action=='acquire':
            selected=sorted(set(normalize(x) for x in paths or []))
            if not selected or not task:raise TraceError('claim-input','Nonempty paths and task required')
            for a in selected:
                for old in state['claims'].values():
                    if old['status']!='active':continue
                    for b in old['paths']:
                        left,right=a.casefold(),b.casefold()
                        if left==right or left.startswith(right+'/') or right.startswith(left+'/'):
                            raise TraceError('claim-conflict','File/parent ownership overlaps; no claims acquired',{'path':a,'owner':old['owner'],'claim_id':old['id']})
            identity='claim_'+uuid.uuid4().hex
            row={'id':identity,'owner':owner,'task':task,'paths':selected,'baseline':{p:fingerprint(p) for p in selected},'created':time.time(),'status':'active'}
            state['claims'][identity]=row;state['history'].append({'action':'acquire','id':identity,'owner':owner,'at':time.time()})
            return row
        row=state['claims'].get(claim_id)
        if not row or row['status']!='active' or row['owner']!=owner:raise TraceError('claim-owner','Active claim and exact owner required')
        differences={p:{'expected':sha,'actual':fingerprint(p)} for p,sha in row['baseline'].items() if fingerprint(p)!=sha}
        if action=='check':
            if differences:raise TraceError('claim-changed','Claimed bytes changed; inspect rather than overwrite',differences)
            return {'status':'owned-and-unchanged','claim_id':claim_id,'owner':owner}
        if action=='checkpoint':
            if not reason:raise TraceError('claim-reason','Describe the owner write or reviewed handoff')
            state['history'].append({'action':'checkpoint','id':claim_id,'owner':owner,'reason':reason,'before':row['baseline'],'after':{p:fingerprint(p) for p in row['paths']},'at':time.time()})
            row['baseline']={p:fingerprint(p) for p in row['paths']}
            return row
        if action=='release':
            if differences:raise TraceError('claim-changed','Checkpoint reviewed owner writes before release',differences)
            row['status']='released';row['released']=time.time();row['reason']=reason or 'owner completed'
            state['history'].append({'action':'release','id':claim_id,'owner':owner,'at':time.time()})
            return row
        raise TraceError('claim-action','Unsupported action')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['list','acquire','check','checkpoint','release'])
    p.add_argument('--owner');p.add_argument('--task');p.add_argument('--paths',nargs='+');p.add_argument('--claim');p.add_argument('--reason')
    args=p.parse_args()
    try:result=operate(args.action,args.owner,args.task,args.paths,args.claim,args.reason)
    except TraceError as exc:
        print(json.dumps({'error':exc.as_dict()},ensure_ascii=False));return 2
    print(json.dumps(result,ensure_ascii=False,indent=2));return 0

if __name__=='__main__':sys.exit(main())
