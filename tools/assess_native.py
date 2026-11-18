"""R3 host collaboration assessment: packet and judge separate from candidate.
The integrator knows the original fixture; the fresh candidate is given only the
packet. This is cooperative material isolation, not an OS secrecy mechanism.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from traceanchor.core import Store, digest, canonical, TraceError
from traceanchor.service import dispatch
from traceanchor.process import run_process
BASE=ROOT/'assessments/native-parcel'
PRIVATE=BASE/'private'
PACKET=BASE/'packet'
REFERENCE=ROOT/'.validation/native-c85a89382ca2/parcel.exe'

def save(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def prepare():
    PACKET.mkdir(parents=True,exist_ok=False);PRIVATE.mkdir()
    source=REFERENCE.parent
    (PACKET/'disassembly.txt').write_bytes((source/'disassembly.txt').read_bytes())
    text=(source/'debugger-trace.txt').read_text(encoding='utf-8')
    text=text.replace(str(ROOT.parent),'[INTEGRATOR_ROOT]').replace(ROOT.parent.as_posix(),'[INTEGRATOR_ROOT]')
    (PACKET/'runtime-trace.txt').write_text(text,encoding='utf-8')
    training=[{'id':'normal','stdin':'state\nreserve 3\nquote 250 0\ncancel 1\nstate\n'}, {'id':'errors','stdin':'reserve 99\ncancel 1\nquote 0 0\nwhat\nstate\n'}, {'id':'remote','stdin':'quote 501 1\nstate\n','test_environment':{'TRACEANCHOR_PARCEL_ZONE':'remote'}}]
    observations=[]
    for f in training:
        env={**os.environ,'TRACEANCHOR_PARCEL_ZONE':'local',**f.get('test_environment',{})}
        result=run_process([str(REFERENCE)],cwd=str(PRIVATE),input_bytes=f['stdin'].encode(),timeout=10,idle_timeout=5,env=env)
        assert result['exit_code']==0 and result['cleanup']['state']=='complete'
        observations.append({**f,'stdout':result['stdout'].decode(),'stderr':result['stderr'].decode(),'exit_code':result['exit_code']})
    save(PACKET/'observations.json',observations)
    hidden=[{'id':'rounding-edges','stdin':'quote 499 0\nquote 500 0\nquote 501 0\nquote 19999 1\nquote 20000 1\nquote 20001 0\nstate\n'}, {'id':'reservation-errors','stdin':'reserve 12\nreserve 1\ncancel 13\ncancel 12\nreserve 0\nreserve -2\ncancel 0\nstate\n'}, {'id':'parsing-boundary','stdin':'\nreserve +2\ncancel +1\nquote 1\nreserve 3 trailing\nSTATE\nstate\n'}]
    sealed=[{'id':'sealed-final-edge','stdin':'quote 1501 1\nreserve 11\nreserve 2\ncancel 4\nreserve 5\nquote -1 1\nquote 1 2\nstate\n','test_environment':{'TRACEANCHOR_PARCEL_ZONE':'remote'}}]
    data={'contract_id':'FOUR-SOURCE-PRODUCT-R3','reference_sha256':digest(REFERENCE.read_bytes()),'development':training,'assessment':hidden,'sealed_final':sealed,'scope':'Finite parcel fee/state/error protocol, including ordinary scanf token behavior; not C integer overflow or arbitrary malformed byte streams','exposure':'Integrator authored reference and judge. Fresh candidate sees packet only, no reference C/source/binary or private fixtures. Cooperative isolation, not OS-enforced secrecy.'}
    save(PRIVATE/'frozen-fixtures.json',data)
    (PRIVATE/'freeze.sha256').write_text(digest((PRIVATE/'frozen-fixtures.json').read_bytes())+'\n')
    (PACKET/'TASK.md').write_text('''# Independent parcel protocol reconstruction

Implement candidate.py using only this packet: real objdump machine-code output,
real GDB trace and selected direct observations. Read no reference source,
binary, judge/private directory, or other project data. You are a fresh host
worker and have not seen the reference implementation.

stdin is a stream of text commands: quote grams priority; reserve quantity;
cancel quantity; state. Emit JSON lines for responses and preserve state through
the process; exit normally after EOF. Runtime test condition
TRACEANCHOR_PARCEL_ZONE is externally selectable; remote behavior is observed in
the trace. Determine rounding, argument parsing, state and errors from evidence.
Judge compares decoded JSON-line outputs, exit/stderr, final state query,
structure and owned-directory effects; visual is not applicable to this protocol.

Write an independent Python implementation and a short evidence/uncertainty note.
Do not intentionally insert a defect, read hidden fixtures or obtain reference
source. You may request bounded observations in your report. Approved feedback
can be used for later corrections. Hidden/sealed sequences were frozen before
you started. Same-filesystem access is governed by cooperative role boundaries,
not OS secrecy; keep an explicit list of materials you actually read.
''',encoding='utf-8')
    print('Public packet and private/sealed fixtures frozen before candidate creation')


def judge(stage):
    frozen=(PRIVATE/'frozen-fixtures.json').read_bytes()
    assert digest(frozen)==(PRIVATE/'freeze.sha256').read_text().strip()
    data=json.loads(frozen);assert digest(REFERENCE.read_bytes())==data['reference_sha256']
    candidate=BASE/'candidate/candidate.py'
    if not candidate.is_file():raise RuntimeError('Independent host candidate is not ready')
    checkpoint=digest(candidate.read_bytes())
    directory=PRIVATE/('judgment-'+checkpoint[:12]+'-'+stage)
    directory.mkdir(exist_ok=False)
    store=Store(directory/'workspace',create=True)
    def call(op,**args):return dispatch(store.root,op,args)
    c=call('case.create',objective='Independent parcel shipping quotes and reservation state/errors',mode='reconstruct',target_kind='native',allowed_effects=['read','execute','write-candidate'])
    cid=c['id'];ref=call('source.add',case_id=cid,path=str(REFERENCE));cand=call('source.add',case_id=cid,path=str(candidate),role='candidate')
    observation=call('analyze',case_id=cid,source_id=ref['id'])
    items=data['development']+(data['assessment'] if stage=='development' else data['assessment']+data['sealed_final'])
    fixtures=[{**f,'stdout_json_lines':True,'state_from_last_json_line':True,'test_environment':{'TRACEANCHOR_PARCEL_ZONE':'local',**f.get('test_environment',{})}} for f in items]
    obligations=[{'id':'responses','dimension':'behavior','comparator':'json','selector':'decoded_stdout','blocking':True}, {'id':'exit','dimension':'behavior','comparator':'exact','selector':'exit_code','blocking':True}, {'id':'stderr','dimension':'behavior','comparator':'exact','selector':'stderr','blocking':True}, {'id':'state','dimension':'state','comparator':'exact','blocking':True}, {'id':'files','dimension':'side-effects','comparator':'exact','blocking':True}, {'id':'shape','dimension':'structure','comparator':'json-shape','blocking':True}, {'id':'visual','dimension':'visual','comparator':'ppm','blocking':False,'not_applicable_reason':'Frozen text-only shipping/reservation protocol has no visual interface'}]
    spec=call('spec.freeze',case_id=cid,reference_id=ref['id'],evidence_ids=[observation['id']],fixtures=fixtures,requirements=['shipping fees','stateful reservations','error branches','boundary input parsing'],scope=data['scope'],plan={'obligations':obligations})
    verdict=call('verify',case_id=cid,spec_id=spec['id'],candidate_id=cand['id'])
    save(directory/'verdict.json',verdict)
    feedback=[]
    for pair in verdict['data']['pairs']:
        if pair['result']['status']!='pass':
            left=store.get('observation',pair['left'])['data']['capture'];right=store.get('observation',pair['right'])['data']['capture']
            feedback.append({'fixture_id':pair['fixture_id'],'result':pair['result'],'input':next(x['stdin'] for x in fixtures if x['id']==pair['fixture_id']),'reference_stdout':left['stdout'],'candidate_stdout':right['stdout']})
    save(directory/'feedback.json',feedback)
    summary={'stage':stage,'candidate_sha256':checkpoint,'fixture_manifest_sha256':digest(frozen),'status':verdict['data']['status'],'fixtures':len(fixtures),'sealed_final_exposed_to_candidate':False,'case_id':cid,'spec_id':spec['id'],'verdict_id':verdict['id'],'feedback_fixtures':[x['fixture_id'] for x in feedback]}
    save(directory/'summary.json',summary)
    print(json.dumps({**summary,'directory':str(directory.relative_to(ROOT))}))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','development','final'])
    parser.add_argument('--reference',help='Explicit immutable native reference for another version')
    parser.add_argument('--private',help='Separate judge-only assessment directory')
    parser.add_argument('--packet',help='Separate allowed evidence packet directory')
    args=parser.parse_args()
    if args.reference:REFERENCE=Path(args.reference).absolute()
    if args.private:PRIVATE=Path(args.private).absolute()
    if args.packet:PACKET=Path(args.packet).absolute()
    prepare() if args.action=='prepare' else judge(args.action)
