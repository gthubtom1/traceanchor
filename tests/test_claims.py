"""Actual atomic-claim collisions, changed-byte detection and reviewed handoff."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from traceanchor.core import TraceError
ROOT=Path(__file__).resolve().parents[1]
TEMP=ROOT/'.validation'/'claim-tests';TEMP.mkdir(parents=True,exist_ok=True)

class ClaimTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory(dir=TEMP);self.addCleanup(t.cleanup)
        self.root=Path(t.name)
        spec=importlib.util.spec_from_file_location('tested_claims',ROOT/'tools/claims.py')
        self.mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.mod)
        self.mod.ROOT=self.root;self.mod.AREA=self.root/'.coordination'
    def test_case_and_parent_overlap_are_atomic(self):
        a=self.mod.operate('acquire','first','write',['Source/File.py'])
        with self.assertRaises(TraceError) as error:
            self.mod.operate('acquire','second','collision',['new.py','source'])
        self.assertEqual(error.exception.code,'claim-conflict')
        state=self.mod.operate('list')
        self.assertEqual(set(state['claims']),{a['id']})
        with self.assertRaises(TraceError):self.mod.operate('acquire','second','collision',['SOURCE/FILE.PY'])
    def test_changed_bytes_stop_until_reviewed_checkpoint_then_handoff(self):
        f=self.root/'file.py';f.write_bytes(b'before')
        a=self.mod.operate('acquire','first','fix',['file.py'])
        f.write_bytes(b'partial or external change')
        with self.assertRaises(TraceError):self.mod.operate('check','first',claim_id=a['id'])
        with self.assertRaises(TraceError):self.mod.operate('release','first',claim_id=a['id'])
        with self.assertRaises(TraceError):self.mod.operate('checkpoint','second',claim_id=a['id'],reason='not the owner')
        self.mod.operate('checkpoint','first',claim_id=a['id'],reason='Inspected owner-produced partial bytes before explicit handoff')
        self.mod.operate('release','first',claim_id=a['id'])
        b=self.mod.operate('acquire','second','continue',['file.py'])
        self.assertEqual(self.mod.operate('check','second',claim_id=b['id'])['status'],'owned-and-unchanged')
        history=self.mod.operate('list')['history']
        self.assertTrue(any(x['action']=='checkpoint' for x in history))
    def test_registry_lock_never_stolen_by_age(self):
        self.mod.AREA.mkdir();lock=self.mod.AREA/'registry.lock'
        lock.write_text('{"pid":0,"created":0}')
        with self.assertRaises(TraceError) as error:self.mod.operate('acquire','owner','task',['a'])
        self.assertEqual(error.exception.code,'claim-registry-busy')
        self.assertTrue(lock.exists())
    def test_path_escape_rejected(self):
        for path in ('../external','C:/external'):
            with self.assertRaises(TraceError):self.mod.operate('acquire','owner','task',[path])

if __name__=='__main__':unittest.main()
