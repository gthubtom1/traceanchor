"""Permanent regressions for the new-context R3 reviewer six real counterexamples."""
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import time
from traceanchor.core import Store, TraceError
from traceanchor import workspace
from traceanchor.service import dispatch
from traceanchor.process import run_process
ROOT=Path(__file__).resolve().parents[1]
TEMP=ROOT/'.validation'/'review-fix-tests';TEMP.mkdir(parents=True,exist_ok=True)

class ReviewFixTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory(dir=TEMP)
        def bounded_cleanup():
            # A closed Windows image can remain briefly locked by filesystem
            # observers. Retry only this owned fixture, then propagate failure;
            # no ignore_errors and no live process/cleanup assertion is relaxed.
            for _ in range(10):
                try:t.cleanup();return
                except (PermissionError,NotADirectoryError):time.sleep(0.1)
            t.cleanup()
        self.addCleanup(bounded_cleanup)
        self.base=Path(t.name);self.store=Store(self.base/'ws',create=True)
        self.case=self.call('case.create',objective='review regressions',mode='reconstruct',allowed_effects=['read','execute','write-candidate'])
        self.cid=self.case['id']
    def call(self,op,**kw):return dispatch(self.store.root,op,kw)
    def source(self,name,code,case_id=None,role='reference'):
        p=self.base/name;p.write_bytes(code.encode())
        return self.call('source.add',case_id=case_id or self.cid,path=str(p),role=role)
    def passing(self):
        r=self.source('ref.py','print(7)\n');c=self.source('candidate.py','print(3+4)\n',role='candidate')
        o=self.call('analyze',case_id=self.cid,source_id=r['id'])
        s=self.call('spec.freeze',case_id=self.cid,reference_id=r['id'],evidence_ids=[o['id']],requirements=['same scalar'],scope='one sample',fixtures=[{'id':'one'}],plan={'obligations':[{'id':'out','dimension':'behavior','comparator':'exact','blocking':True}]})
        v=self.call('verify',case_id=self.cid,spec_id=s['id'],candidate_id=c['id'])
        self.assertEqual(v['data']['status'],'pass');return v
    def test_whole_workspace_limit_rejects_source_admission(self):
        used=workspace.census(self.store)['total_bytes']
        workspace.configure(self.store,{'hard_bytes':used+200000,'soft_bytes':used+100000,'work_bytes':200000})
        selected=self.base/'big.bin';selected.write_bytes(b'x'*210000)
        with self.assertRaises(TraceError) as error:self.call('source.add',case_id=self.cid,path=str(selected))
        self.assertEqual(error.exception.code,'workspace-budget')
        self.assertFalse(list((self.store.root/'objects').glob('*/*')))
    def test_oversized_terminal_residual_reconciles_after_explicit_policy_change(self):
        run=self.store.create('run',{'status':'cancelled','cleanup':{'state':'complete'}},self.cid)
        item=workspace.register_directory(self.store,'work/oversize',self.cid,run['id'])
        (self.store.root/'work/oversize/file').write_bytes(b'x'*9000)
        workspace.configure(self.store,{'work_bytes':8192})
        self.assertFalse(workspace.finish_directory(self.store,item['id'],'failed',{'state':'complete'})['data']['inventory_complete'])
        with self.assertRaises(TraceError):workspace.archive_directory(self.store,item['id'],reason='need bounded reinventory')
        workspace.configure(self.store,{'work_bytes':16384})
        renewed=self.call('workspace.work.reconcile',work_id=item['id'])
        self.assertTrue(renewed['data']['inventory_complete'])
        self.call('workspace.work.archive',work_id=item['id'],reason='actual payload preserved')
        self.call('workspace.work.clean',work_id=item['id'],apply=True)
        self.assertFalse((self.store.root/'work/oversize').exists())
    def test_child_revision_cannot_expand_read_only_parent(self):
        p=self.call('case.create',objective='read-only')
        c=self.call('subtask.create',case_id=p['id'],question='finite read')
        with self.assertRaises(TraceError) as error:self.call('case.revise',case_id=c['id'],changes={'allowed_effects':['read','execute']})
        self.assertEqual(error.exception.code,'effect-not-granted')
    @unittest.skipUnless(os.name=='nt','Windows execution qualification')
    def test_child_corrupt_raw_evidence_invalidates_parent_acceptance(self):
        child=self.call('subtask.create',case_id=self.cid,question='runtime scalar contract',allowed_effects=['read','execute'])
        src=self.source('child.py','print(17)\n',case_id=child['id'])
        obs=self.call('capture',case_id=child['id'],source_id=src['id'])
        self.call('subtask.result',case_id=child['id'],contract={'scalar':17},evidence_ids=[obs['id']])
        self.passing()
        material=self.store.material(obs['data']['stdout_material'])
        (self.store.root/material['path']).write_bytes(b'corrupt')
        self.assertNotEqual(self.call('report',case_id=self.cid)['acceptance'],'pass')
        with self.assertRaises(TraceError):self.call('case.close',case_id=self.cid)
    @unittest.skipUnless(os.name=='nt','Windows execution qualification')
    def test_compare_rechecks_raw_material_integrity(self):
        v=self.passing();pair=v['data']['pairs'][0]
        obs=self.store.get('observation',pair['left'])
        m=self.store.material(obs['data']['stdout_material']);(self.store.root/m['path']).unlink()
        with self.assertRaises(TraceError) as error:self.call('compare',case_id=self.cid,left_id=pair['left'],right_id=pair['right'],plan={'obligations':[{'id':'out','dimension':'behavior','comparator':'exact'}]})
        self.assertEqual(error.exception.code,'integrity-error')
    @unittest.skipUnless(os.name=='nt' and shutil.which('gcc') and shutil.which('gdb'),'Optional GNU debugger tools')
    def test_target_stdout_never_creates_debugger_breakpoint_receipt(self):
        code=self.base/'not-called.c';exe=self.base/'not-called.exe'
        code.write_text('#include <stdio.h>\nint never_called(int x){return x+1;}\nint main(void){puts("TRACEANCHOR_BREAK never_called");return 0;}\n')
        # GCC may be silent for the entire compile. Preserve the existing30s
        # total bound rather than treating10s stdout silence as compile failure.
        b=run_process([shutil.which('gcc'),'-g','-O0','-o',str(exe),str(code)],cwd=str(self.base),timeout=30,idle_timeout=30)
        self.assertEqual(b['exit_code'],0,b)
        s=self.call('source.add',case_id=self.cid,path=str(exe))
        o=self.call('professional.run',case_id=self.cid,source_id=s['id'],method='native.trace',options={'breakpoints':['never_called']})
        p=o['data']['professional'];self.assertNotEqual(p['status'],'complete')
        self.assertEqual(p['breakpoint_hits'],[])
        self.assertTrue(p['unknowns'])

if __name__=='__main__':unittest.main()
