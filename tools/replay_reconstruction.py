"""Replay the actual independently authored revisions after the blind assessment.
Inputs are public now, so this is reproducibility, NOT a new blind-model score.
"""
import json
import os
from pathlib import Path
import shutil
import sys
import uuid
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from traceanchor.core import Store,digest
from traceanchor.service import dispatch
from traceanchor.process import run_process

FIXTURES=[
 {'id':'normal','stdin':'state\nreserve 3\nquote 250 0\ncancel 1\nstate\n'},
 {'id':'errors','stdin':'reserve 99\ncancel 1\nquote 0 0\nwhat\nstate\n'},
 {'id':'remote','stdin':'quote 501 1\nstate\n','test_environment':{'TRACEANCHOR_PARCEL_ZONE':'remote'}},
 {'id':'rounding-edges','stdin':'quote 499 0\nquote 500 0\nquote 501 0\nquote 19999 1\nquote 20000 1\nquote 20001 0\nstate\n'},
 {'id':'reservation-errors','stdin':'reserve 12\nreserve 1\ncancel 13\ncancel 12\nreserve 0\nreserve -2\ncancel 0\nstate\n'},
 {'id':'parsing-boundary','stdin':'\nreserve +2\ncancel +1\nquote 1\nreserve 3 trailing\nSTATE\nstate\n'},
 {'id':'formerly-sealed-final','stdin':'quote 1501 1\nreserve 11\nreserve 2\ncancel 4\nreserve 5\nquote -1 1\nquote 1 2\nstate\n','test_environment':{'TRACEANCHOR_PARCEL_ZONE':'remote'}}
]

def main():
    gcc=shutil.which('gcc')
    if not gcc:raise RuntimeError('Optional trusted GCC required; no automatic installation')
    base=ROOT/'.validation'/('reconstruction-replay-'+uuid.uuid4().hex[:12]);base.mkdir(parents=True)
    ownership={'owner':'reconstruction-replay','tier':'L2','status':'active','reason':'Public replay of already completed host assessment; raw run evidence retained'}
    def save(name,value):(base/name).write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
    save('ownership.json',ownership)
    original=(ROOT/'examples/native/parcel.c').read_text(encoding='utf-8')
    revised=original.replace('grams > 20000','grams > 15000').replace('250 + blocks * 75','275 + blocks * 75').replace('fee += 180','fee += 220')
    refs={}
    for version,text in [(1,original),(2,revised)]:
        source=base/('reference-v'+str(version)+'.c');source.write_text(text,encoding='utf-8')
        output=base/('reference-v'+str(version)+('.exe' if os.name=='nt' else ''))
        command=[gcc,'-g','-O0','-fno-inline','-o',str(output),str(source)]
        result=run_process(command,cwd=str(base),timeout=30,idle_timeout=15)
        (base/('build-'+str(version)+'.stdout')).write_bytes(result['stdout']);(base/('build-'+str(version)+'.stderr')).write_bytes(result['stderr'])
        if result['exit_code']!=0 or result['cleanup']['state']!='complete':raise RuntimeError('Reference build failed; raw evidence retained')
        refs[version]=output
    summaries=[]
    for refver,candver,expected in [(1,1,'pass'),(2,1,'fail'),(2,2,'pass')]:
        label='reference'+str(refver)+'-candidate'+str(candver)
        store=Store(base/label,create=True)
        def call(op,**kwargs):return dispatch(store.root,op,kwargs)
        c=call('case.create',objective='Replay finite parcel shipping/state reconstruction',mode='reconstruct',target_kind='native',allowed_effects=['read','execute','write-candidate']);cid=c['id']
        ref=call('source.add',case_id=cid,path=str(refs[refver]))
        cand=call('source.add',case_id=cid,path=str(ROOT/'examples/reconstruction'/('candidate_v'+str(candver)+'.py')),role='candidate')
        obs=call('analyze',case_id=cid,source_id=ref['id'])
        fixtures=[{**f,'stdout_json_lines':True,'state_from_last_json_line':True,'test_environment':{'TRACEANCHOR_PARCEL_ZONE':'local',**f.get('test_environment',{})}} for f in FIXTURES]
        obligations=[{'id':'outputs','dimension':'behavior','selector':'decoded_stdout','comparator':'json','blocking':True},{'id':'exit','dimension':'behavior','selector':'exit_code','comparator':'exact','blocking':True},{'id':'stderr','dimension':'behavior','selector':'stderr','comparator':'exact','blocking':True},{'id':'state','dimension':'state','comparator':'exact','blocking':True},{'id':'effects','dimension':'side-effects','comparator':'exact','blocking':True},{'id':'structure','dimension':'structure','comparator':'json-shape','blocking':True},{'id':'visual','dimension':'visual','comparator':'ppm','blocking':False,'not_applicable_reason':'Frozen text-only protocol with no visual surface'}]
        spec=call('spec.freeze',case_id=cid,reference_id=ref['id'],evidence_ids=[obs['id']],fixtures=fixtures,plan={'obligations':obligations},requirements=['shipping prices','reservation state','error branches','integer boundaries'],scope='Seven public replay sequences; not an unexposed assessment now')
        verdict=call('verify',case_id=cid,spec_id=spec['id'],candidate_id=cand['id'])
        assert verdict['data']['status']==expected,(label,verdict['data']['status'])
        if expected=='pass':call('case.close',case_id=cid)
        summaries.append({'pair':label,'status':expected,'case_id':cid,'verdict_id':verdict['id'],'candidate_sha256':cand['data']['sha256'],'reference_sha256':ref['data']['sha256'],'fixtures':7,'runs':14})
    ownership.update(status='completed',cleanup='complete');save('ownership.json',ownership)
    report={'status':'passed-public-replay','pairs':summaries,'total_actual_process_runs':42,'scope':'Actual frozen independent revisions replayed after assessment. All inputs public now; not a new blind-host score. No deliberate bad candidate: V1 fails only against owner-changed V2 reference.'}
    save('qualification.json',report)
    print(json.dumps({'status':report['status'],'actual_process_runs':42,'evidence':str((base/'qualification.json').relative_to(ROOT))}))

if __name__=='__main__':main()
