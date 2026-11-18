"""P05 actual parent feature, finite native research and version reuse.
Parent expectations are reviewed development requirements, not blind P04 answers.
"""
import argparse
import json
from pathlib import Path
import sys
import uuid
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from traceanchor.core import Store, canonical, digest
from traceanchor.service import dispatch


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--reference-v1',required=True)
    parser.add_argument('--reference-v2',required=True)
    args=parser.parse_args()
    base=ROOT/'.validation'/('development-'+uuid.uuid4().hex[:12]);base.mkdir(parents=True)
    store=Store(base/'workspace',create=True)
    def save(name,data):(base/name).write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
    def call(op,**kw):return dispatch(store.root,op,kw)
    backend=base/'selected-parcel.exe';backend.write_bytes(Path(args.reference_v1).read_bytes())
    parent=call('case.create',objective='Build a batch-order shipping-cost utility using an existing native quote interface; do not rebuild the backend',mode='analysis',target_kind='development-component',allowed_effects=['read','execute','write-candidate'])
    cid=parent['id']
    child=call('subtask.create',case_id=cid,question='Find the quote command, error semantics and state query needed by this batch feature',target_kind='native',allowed_effects=['read','execute'])
    child_id=child['id']
    original=call('source.add',case_id=child_id,path=str(backend))
    def research(source,version,reused=None):
        symbols=['quote_parcel'] if version==2 else ['dispatch_command','quote_parcel']
        static=call('professional.run',case_id=child_id,source_id=source['id'],method='native.disassemble',options={'symbols':symbols})
        observed=call('capture',case_id=child_id,source_id=source['id'],fixture={'id':'quote-interface-v'+str(version),'stdin':'quote 250 0\nquote 501 0\nquote 0 0\nstate\n','stdout_json_lines':True,'state_from_last_json_line':True,'test_environment':{'TRACEANCHOR_PARCEL_ZONE':'local'}})
        result=call('subtask.result',case_id=child_id,contract={'question':'Finite quote protocol for batch orders','interface':'quote <integer grams> <priority 0/1>; one NDJSON response per command; final state query','unit':'integer cents','version':version,'source_sha256':source['data']['sha256'],'reused_from':reused,'reuse_scope':'command grammar, integer cents and error envelope unchanged; pricing/weight boundary re-observed'},evidence_ids=[static['id'],observed['id']],fixture_source_ids=[source['id']],unknowns=['GUI, arbitrary byte streams and integer overflow not studied'],limitations=['Only this finite dependency research, not a full reconstruction'])
        save('child-v'+str(version)+'.json',result)
        return result,observed
    first,observed=research(original,1)
    client=base/'quote_batch.py';client.write_bytes((ROOT/'examples/development/quote_batch.py').read_bytes())
    client_sha=digest(client.read_bytes())
    candidate=call('source.add',case_id=cid,path=str(client),role='candidate',description='Actual parent feature consuming the child interface, not a backend clone')
    oracle=base/'reviewed_parent_contract.py'
    payload={'items':[{'grams':250},{'grams':501},{'grams':0}]}
    def parent_check(version):
        prices=[325,400] if version==1 else [350,425]
        expected={'quotes':[{'ok':True,'cents':x,'zone':0} for x in prices]+[{'ok':False,'error':'weight-or-priority'}],'total_cents':sum(prices),'backend_state':{'ok':True,'available':12,'reserved':0}}
        oracle.write_text('import json\nprint(json.dumps('+repr(expected)+'))\n',encoding='utf-8')
        reference=call('source.add',case_id=cid,path=str(oracle),description='Reviewed parent acceptance witness, not a recovered backend or hidden oracle')
        evidence=call('analyze',case_id=cid,source_id=reference['id'])
        spec=call('spec.freeze',case_id=cid,reference_id=reference['id'],evidence_ids=[evidence['id']],requirements=['Batch quote projection','Integer-cent total','Error passthrough','Backend final state'],scope='Parent development tests against explicitly reviewed expected outputs; not independent legacy reconstruction',fixtures=[{'id':'basket','stdin':canonical(payload),'arguments':[str(backend)],'test_environment':{'TRACEANCHOR_PARCEL_ZONE':'local'}}],plan={'obligations':[{'id':'output','dimension':'behavior','comparator':'json','blocking':True},{'id':'stderr','dimension':'behavior','selector':'stderr','comparator':'exact','blocking':True},{'id':'exit','dimension':'behavior','selector':'exit_code','comparator':'exact','blocking':True},{'id':'files','dimension':'side-effects','comparator':'exact','blocking':True},{'id':'shape','dimension':'structure','comparator':'json-shape','blocking':True}]})
        verdict=call('verify',case_id=cid,spec_id=spec['id'],candidate_id=candidate['id'])
        save('parent-verdict-v'+str(version)+'.json',verdict)
        assert verdict['data']['status']=='pass'
        call('case.close',case_id=cid)
        return verdict
    v1=parent_check(1)
    backend.write_bytes(Path(args.reference_v2).read_bytes())
    stale=call('report',case_id=cid)
    assert stale['acceptance']=='stale'
    assert not store.get('verdict',v1['id'])['data']['current']
    save('parent-stale-after-child-version-change.json',stale)
    call('case.revise',case_id=cid,changes={'status':'active','objective':'Maintain the batch-order utility for reference V2; reuse compatible interface and unchanged client'})
    fresh=call('source.refresh',case_id=child_id,source_id=original['id'])
    second,observed2=research(fresh,2,first['id'])
    assert second['data']['contract']['reused_from']==first['id']
    assert digest(client.read_bytes())==client_sha
    v2=parent_check(2)
    result={'status':'pass-finite-development-and-version-reuse','parent_id':cid,'child_id':child_id,'old_result':first['id'],'new_result':second['id'],'parent_v1':v1['id'],'parent_v2':v2['id'],'old_parent_verification_became_stale':True,'parent_client_sha256':client_sha,'parent_code_reused_byte_identical':True,'incremental_scope':'V2 revisits pricing function and price observations; command grammar, error envelope and parent implementation reused with explicit version evidence','not_claimed':'This reviewed parent acceptance witness is not a blind independent reconstruction or proof of every backend input'}
    save('qualification.json',result)
    print(json.dumps({**result,'evidence':str(base.relative_to(ROOT))+'/qualification.json'}))

if __name__=='__main__':main()
