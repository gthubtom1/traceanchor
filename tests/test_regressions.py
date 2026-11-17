"""Permanent regressions for eight independently reproduced integration defects."""
import base64
import copy
import os
from pathlib import Path
import tempfile
import unittest

from traceanchor.core import Store, TraceError, canonical, child_path, digest, value_digest
from traceanchor import lifecycle
from traceanchor.service import dispatch
from traceanchor.maintenance import snapshot, restore

ROOT=Path(__file__).resolve().parents[1]/'.validation'/'temp';ROOT.mkdir(parents=True,exist_ok=True)


class Regressions(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT);self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.store=Store(self.base/'ws',create=True)
        self.case=self.call('case.create',objective='finite scalar protocol',mode='reconstruct',allowed_effects=['read','execute','write-candidate'])
    def call(self,op,**args):return dispatch(self.store.root,op,args)
    def pair(self):
        a=self.base/'original.py';a.write_text('print(7)\n')
        b=self.base/'candidate.py';b.write_text('print(3+4)\n')
        ref=self.call('source.add',case_id=self.case['id'],path=str(a))
        cand=self.call('source.add',case_id=self.case['id'],path=str(b),role='candidate')
        obs=self.call('analyze',case_id=self.case['id'],source_id=ref['id'])
        spec=self.call('spec.freeze',case_id=self.case['id'],reference_id=ref['id'],evidence_ids=[obs['id']],fixtures=[{'id':'scalar'}],plan={'obligations':[{'id':'value','dimension':'behavior','comparator':'exact','blocking':True}]},requirements=['same scalar'],scope='one fixed sample')
        return ref,cand,spec

    @unittest.skipUnless(os.name=='nt','Windows dynamic qualification')
    def test_r01_blocking_unknown_invalidates_existing_pass(self):
        ref,cand,spec=self.pair()
        verdict=self.call('verify',case_id=self.case['id'],spec_id=spec['id'],candidate_id=cand['id'])
        self.assertEqual(verdict['data']['status'],'pass')
        self.call('unknown.add',case_id=self.case['id'],question='unseen error branch',reason='missing evidence')
        self.assertNotEqual(self.call('report',case_id=self.case['id'])['acceptance'],'pass')
        with self.assertRaises(TraceError):self.call('case.close',case_id=self.case['id'])

    def test_r02_resource_named_material_protects_gc(self):
        m=self.store.put_bytes(self.case['id'],b'leased','L3','temp')
        self.store.acquire(m['id'],'independent-reader')
        self.assertEqual(next(r for r in lifecycle.preview(self.store)['items'] if r['id']==m['id'])['reason'],'active-lease')
        lifecycle.clean(self.store)
        self.assertEqual(self.store.read_material(m['id']),b'leased')

    def test_r03_import_path_name_cannot_escape(self):
        ref,_,_=self.pair();bundle=self.call('export',case_id=self.case['id'])
        victim=self.base/'victim.py';victim.write_text('keep')
        for record in bundle['payload']['records']:
            if record['kind']=='source':record['data']['name']=str(victim)
        bundle['sha256']=value_digest(bundle['payload'])
        other=Store(self.base/'other',create=True)
        with self.assertRaises(TraceError):dispatch(other.root,'import',bundle)
        self.assertEqual(victim.read_text(),'keep')
        self.assertEqual(other.list('case'),[])

    def test_r04_import_duplicate_is_atomic(self):
        bundle=self.call('export',case_id=self.case['id'])
        bundle['payload']['records'].append(copy.deepcopy(bundle['payload']['records'][0]));bundle['sha256']=value_digest(bundle['payload'])
        other=Store(self.base/'other',create=True)
        with self.assertRaises(TraceError):dispatch(other.root,'import',bundle)
        self.assertEqual(other.list('case'),[])

    @unittest.skipUnless(os.name=='nt','Windows dynamic qualification')
    def test_r05_resource_busy_does_not_create_or_charge_run(self):
        ref,_,_=self.pair();resource='case-execution:'+self.case['id']
        self.store.acquire(resource,'existing-owner')
        with self.assertRaises(TraceError):self.call('capture',case_id=self.case['id'],source_id=ref['id'])
        self.assertEqual(self.store.list('run',self.case['id']),[])
        self.store.release(resource,'existing-owner')
        self.assertEqual(self.call('capture',case_id=self.case['id'],source_id=ref['id'])['data']['capture']['status'],'completed')

    def test_r06_old_spec_cannot_bind_new_objective(self):
        _,cand,spec=self.pair()
        self.call('case.revise',case_id=self.case['id'],changes={'objective':'different behavior contract'})
        with self.assertRaises(TraceError) as e:self.call('verify',case_id=self.case['id'],spec_id=spec['id'],candidate_id=cand['id'])
        self.assertEqual(e.exception.code,'stale-specification')

    def test_r07_orphan_admission_still_charged(self):
        self.store.put_bytes(self.case['id'],b'12345678')
        raw=b'abcde';sha=digest(raw);path=child_path(self.store.root,f'objects/{sha[:2]}/{sha}');path.parent.mkdir(exist_ok=True);path.write_bytes(raw)
        with self.store.transaction() as db:db.execute("UPDATE meta SET value=? WHERE key='limits'",(canonical({'hard_bytes':10,'soft_bytes':9,'temp_bytes':10}),))
        with self.assertRaises(TraceError) as e:self.store.put_bytes(self.case['id'],raw)
        self.assertEqual(e.exception.code,'disk-budget')
        self.assertTrue(path.exists())
        self.assertEqual(lifecycle.usage(self.store)['physical_registered_bytes'],8)

    def test_r08_promotion_or_pin_after_delete_never_adds_dangling_ref(self):
        for operation in ('promote','pin'):
            m=self.store.put_bytes(self.case['id'],operation.encode(),'L3','temporary')
            lifecycle.clean(self.store,ids=[m['id']])
            with self.assertRaises(TraceError):
                lifecycle.promote(self.store,m['id'],owner=self.case['id']) if operation=='promote' else lifecycle.pin(self.store,m['id'])
            with self.store.connect() as db:self.assertIsNone(db.execute('SELECT 1 FROM refs WHERE target=?',(m['id'],)).fetchone())

    def test_snapshot_restore_real_sqlite_integrity(self):
        cp=snapshot(self.store)
        self.store.update('case',self.case['id'],{'objective':'changed'})
        done=restore(self.store,cp['id'])
        self.assertEqual(done['status'],'restored')
        self.assertEqual(self.store.get('case',self.case['id'])['data']['objective'],'finite scalar protocol')
        with self.store.connect() as db:self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')

    def test_maintenance_active_lease_refused(self):
        self.store.acquire('active-tool','owner')
        with self.assertRaises(TraceError):snapshot(self.store)


if __name__=='__main__':unittest.main()
