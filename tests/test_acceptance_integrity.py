"""Second independent review: negative controls using real files and execution."""
import os
from pathlib import Path
import tempfile
import unittest
from traceanchor.core import Store, TraceError
from traceanchor.service import dispatch
from traceanchor import lifecycle

ROOT = Path(__file__).resolve().parents[1] / '.validation' / 'temp'
ROOT.mkdir(parents=True, exist_ok=True)

class IntegrityTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(t.cleanup)
        self.base = Path(t.name)
        self.store = Store(self.base/'ws', create=True)
        self.case = self.call('case.create', objective='finite sample', mode='reconstruct', allowed_effects=['read','execute','derive','write-candidate'])
        self.cid = self.case['id']
    def call(self, op, **kw):
        return dispatch(self.store.root, op, kw)
    def source(self, name, text, role='reference', cid=None):
        path = self.base/name
        path.write_bytes(text.encode('utf-8'))
        return self.call('source.add', case_id=cid or self.cid, path=str(path), role=role)
    def spec(self, ref, stderr=False):
        obs = self.call('analyze', case_id=self.cid, source_id=ref['id'])
        obligations = [{'id':'stdout','dimension':'behavior','selector':'stdout','comparator':'exact','blocking':True}]
        if stderr:
            obligations.append({'id':'stderr','dimension':'behavior','selector':'stderr','comparator':'exact','blocking':True})
        return self.call('spec.freeze', case_id=self.cid, reference_id=ref['id'], evidence_ids=[obs['id']], fixtures=[{'id':'sample'}], plan={'obligations':obligations}, requirements=['finite sample'], scope='one sample')

    @unittest.skipUnless(os.name == 'nt', 'Windows dynamic qualification')
    def test_distinct_invalid_utf8_never_passes(self):
        ref = self.source('ref.py','import sys;sys.stdout.buffer.write(bytes([255]))\n')
        cand = self.source('cand.py','import sys;sys.stdout.buffer.write(bytes([254]))\n','candidate')
        spec = self.spec(ref)
        verdict = self.call('verify', case_id=self.cid, spec_id=spec['id'], candidate_id=cand['id'])
        self.assertEqual(verdict['data']['status'], 'blocked')
        pair = verdict['data']['pairs'][0]
        captures = [self.store.get('observation', pair[k])['data'] for k in ('left','right')]
        self.assertNotEqual(*[self.store.read_material(c['stdout_material']) for c in captures])

    @unittest.skipUnless(os.name == 'nt', 'Windows dynamic qualification')
    def test_superseded_spec_cannot_be_reaccepted(self):
        ref = self.source('ref.py','print(7)\n')
        cand = self.source('cand.py','import sys;print(7);print("unexpected",file=sys.stderr)\n','candidate')
        old = self.spec(ref)
        new = self.spec(ref, stderr=True)
        self.assertEqual(self.call('verify',case_id=self.cid,spec_id=new['id'],candidate_id=cand['id'])['data']['status'],'fail')
        with self.assertRaises(TraceError) as error:
            self.call('verify',case_id=self.cid,spec_id=old['id'],candidate_id=cand['id'])
        self.assertEqual(error.exception.code,'stale-specification')
        with self.assertRaises(TraceError):self.call('case.close',case_id=self.cid)

    def test_known_derived_digest_cannot_be_laundered_as_candidate(self):
        ref = self.source('ref.py','print(7) # A\n')
        raw = self.store.read_material(ref['data']['material_id'])
        der = self.call('source.derive',case_id=self.cid,source_id=ref['id'],offset=raw.index(b'A'),expected_hex='41',replacement_hex='42')
        cand = self.source('copy.py', self.store.read_material(der['data']['material_id']).decode(), 'candidate')
        spec = self.spec(ref)
        with self.assertRaises(TraceError) as error:self.call('verify',case_id=self.cid,spec_id=spec['id'],candidate_id=cand['id'])
        self.assertEqual(error.exception.code,'not-independent')

    @unittest.skipUnless(os.name == 'nt', 'Windows dynamic qualification')
    def test_parent_report_checks_child_source_without_child_read(self):
        ref = self.source('ref.py','print(7)\n')
        cand = self.source('cand.py','print(3+4)\n','candidate')
        child = self.call('subtask.create',case_id=self.cid,question='read component')
        src = self.source('child.py','print(1)\n',cid=child['id'])
        obs = self.call('analyze',case_id=child['id'],source_id=src['id'])
        self.call('subtask.result',case_id=child['id'],contract={'output':'scalar'},evidence_ids=[obs['id']])
        spec = self.spec(ref)
        self.assertEqual(self.call('verify',case_id=self.cid,spec_id=spec['id'],candidate_id=cand['id'])['data']['status'],'pass')
        (self.base/'child.py').write_text('print(2)\n')
        self.assertEqual(self.call('report',case_id=self.cid)['acceptance'],'stale')
        with self.assertRaises(TraceError):self.call('case.close',case_id=self.cid)

    def test_direct_child_creation_cannot_expand_parent_effects(self):
        parent = self.call('case.create',objective='read-only parent')
        with self.assertRaises(TraceError) as error:
            self.call('case.create',objective='child',parent_id=parent['id'],allowed_effects=['read','network'])
        self.assertEqual(error.exception.code,'effect-not-granted')

    def test_child_refresh_and_reviewed_result_can_replace_stale_dependency(self):
        from traceanchor.service import _check_dependencies
        child = self.call('subtask.create',case_id=self.cid,question='read a component')
        src = self.source('component.py','print(1)\n',cid=child['id'])
        obs = self.call('analyze',case_id=child['id'],source_id=src['id'])
        first = self.call('subtask.result',case_id=child['id'],contract={'value':1},evidence_ids=[obs['id']])
        (self.base/'component.py').write_bytes(b'print(2)\n')
        self.assertFalse(_check_dependencies(self.store,self.cid))
        refreshed = self.call('source.refresh',case_id=child['id'],source_id=src['id'])
        obs = self.call('analyze',case_id=child['id'],source_id=refreshed['id'])
        second = self.call('subtask.result',case_id=child['id'],contract={'value':2},evidence_ids=[obs['id']])
        self.assertFalse(self.store.get('subtask-result',first['id'])['data']['current'])
        self.assertEqual(second['data']['applicable_source_ids'],[refreshed['id']])
        self.assertTrue(_check_dependencies(self.store,self.cid))

    def test_pinned_material_retains_protection_on_import(self):
        m = self.store.put_bytes(self.cid,b'keep','L3','temporary')
        lifecycle.pin(self.store,m['id'])
        bundle = self.call('export',case_id=self.cid)
        other = Store(self.base/'other',create=True)
        dispatch(other.root,'import',bundle)
        with other.connect() as db:
            imported = dict(db.execute("SELECT * FROM materials WHERE reason='imported-evidence'").fetchone())
        self.assertEqual(imported['pinned'],1)
        lifecycle.clean(other)
        self.assertEqual(other.read_material(imported['id']),b'keep')

    def test_derive_never_leaks_work_copies_outside_object_budget(self):
        tight = Store(self.base/'tight',create=True,limits={'hard_bytes':200,'soft_bytes':150,'temp_bytes':80})
        case = dispatch(tight.root,'case.create',{'objective':'byte patch','allowed_effects':['read','derive']})
        path = self.base/'small.bin';path.write_bytes(b'a'*80)
        ref = dispatch(tight.root,'source.add',{'case_id':case['id'],'path':str(path)})
        for _ in range(5):
            dispatch(tight.root,'source.derive',{'case_id':case['id'],'source_id':ref['id'],'offset':0,'expected_hex':'61','replacement_hex':'62'})
        self.assertEqual(lifecycle.usage(tight)['physical_registered_bytes'],160)
        self.assertEqual(sum(p.stat().st_size for p in (tight.root/'work').rglob('*') if p.is_file()),0)

if __name__ == '__main__':unittest.main()
