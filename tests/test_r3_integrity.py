"""R3 negative controls: real raw evidence and recovery payload protection."""
import os
from pathlib import Path
import tempfile
import unittest
from traceanchor.core import Store, TraceError
from traceanchor import lifecycle
from traceanchor.service import dispatch
ROOT=Path(__file__).resolve().parents[1]/'.validation'/'r3-integrity'
ROOT.mkdir(parents=True,exist_ok=True)

class R3IntegrityTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory(dir=ROOT);self.addCleanup(t.cleanup)
        self.base=Path(t.name);self.store=Store(self.base/'workspace',create=True)
        self.case=self.call('case.create',objective='raw output integrity',mode='reconstruct',allowed_effects=['read','execute','write-candidate'])
    def call(self,operation,**kw):return dispatch(self.store.root,operation,kw)
    def passed(self):
        cid=self.case['id'];files=[]
        for name,code,role in [('ref.py','import sys;print(7);print("trace",file=sys.stderr)\n','reference'),('cand.py','import sys;print(3+4);print("trace",file=sys.stderr)\n','candidate')]:
            path=self.base/name;path.write_bytes(code.encode())
            files.append(self.call('source.add',case_id=cid,path=str(path),role=role))
        ref,cand=files;obs=self.call('analyze',case_id=cid,source_id=ref['id'])
        plan={'obligations':[{'id':s,'dimension':'behavior','selector':s,'comparator':'exact','blocking':True} for s in ('stdout','stderr')]}
        spec=self.call('spec.freeze',case_id=cid,reference_id=ref['id'],evidence_ids=[obs['id']],fixtures=[{'id':'one'}],requirements=['same outputs'],scope='one sample',plan=plan)
        verdict=self.call('verify',case_id=cid,spec_id=spec['id'],candidate_id=cand['id'])
        self.assertEqual(verdict['data']['status'],'pass')
        pair=verdict['data']['pairs'][0]
        return self.store.get('observation',pair['left'])['data']

    @unittest.skipUnless(os.name=='nt','Windows managed-execution qualification')
    def test_raw_stdout_corruption_blocks_report_and_close(self):
        observation=self.passed()
        material=self.store.material(observation['stdout_material'])
        (self.store.root/material['path']).write_bytes(b'corrupt output')
        report=self.call('report',case_id=self.case['id'])
        self.assertNotEqual(report['acceptance'],'pass')
        self.assertTrue(report['integrity_failures'])
        with self.assertRaises(TraceError):self.call('case.close',case_id=self.case['id'])

    @unittest.skipUnless(os.name=='nt','Windows managed-execution qualification')
    def test_missing_raw_stderr_blocks_report_and_close(self):
        observation=self.passed()
        material=self.store.material(observation['stderr_material'])
        (self.store.root/material['path']).unlink()
        self.assertNotEqual(self.call('report',case_id=self.case['id'])['acceptance'],'pass')
        with self.assertRaises(TraceError):self.call('case.close',case_id=self.case['id'])

    def test_recovery_metadata_without_reference_is_still_protected(self):
        cid=self.case['id']
        m=self.store.put_bytes(cid,b'recovery state','L2','interrupted output',metadata={'recovery_use':True})
        archive=self.store.put_bytes(cid,b'archive index','L1','archive')
        self.store.update('case',cid,{'status':'closed','disposition':'accepted','archive_id':archive['id']})
        # Legacy/missing graph edge must not silently make recovery metadata deletable.
        with self.store.transaction() as db:db.execute('DELETE FROM refs WHERE target=?',(m['id'],))
        result=lifecycle.clean(self.store,ids=[m['id']])
        self.assertEqual(result['data']['reclaimed_bytes'],0)
        self.assertEqual(self.store.read_material(m['id']),b'recovery state')

    def test_recovery_release_archives_bytes_before_reclaim(self):
        cid=self.case['id']
        m=self.store.put_bytes(cid,b'needed snapshot','L2','recovery',metadata={'recovery_use':True})
        archive=self.store.put_bytes(cid,b'case archive','L1','archive')
        self.store.update('case',cid,{'status':'closed','disposition':'accepted','archive_id':archive['id']})
        result=lifecycle.release_recovery(self.store,m['id'],reason='Review completed; immutable recovery payload archived')
        archived=result['archived_material_id']
        self.assertEqual(self.store.read_material(archived),b'needed snapshot')
        self.assertEqual(self.store.material(archived)['tier'],'L1')
        lifecycle.clean(self.store,ids=[m['id']])
        self.assertTrue(self.store.material(m['id'])['deleted'])
        self.assertEqual(self.store.read_material(archived),b'needed snapshot')

if __name__=='__main__':unittest.main()
