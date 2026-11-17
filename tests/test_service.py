import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from traceanchor.core import Store, TraceError
from traceanchor.service import dispatch
from traceanchor.demo import run_demo

ROOT = Path(__file__).resolve().parents[1] / '.validation' / 'temp'
ROOT.mkdir(parents=True, exist_ok=True)


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.store = Store(self.base / 'workspace', create=True)
        self.case = self.call('case.create', objective='test finite task', mode='reconstruct', target_kind='protocol', allowed_effects=['read', 'execute', 'write-candidate', 'derive'])

    def call(self, op, **args): return dispatch(self.store.root, op, args)

    def source(self, text='print(1)\n', role='reference', name='source.py', case_id=None):
        path = self.base / name
        path.write_text(text, encoding='utf-8')
        return self.call('source.add', case_id=case_id or self.case['id'], path=str(path), role=role)

    def test_modes_targets_and_no_implicit_effect(self):
        for mode in ('analysis','protocol','reconstruct','diagnose-modify','version-diff','dev-subtask'):
            case = self.call('case.create', objective='finite', mode=mode, target_kind='apk')
            self.assertEqual(case['data']['mode'], mode)
            source = self.source(case_id=case['id'])
            with self.assertRaises(TraceError) as exc: self.call('capture', case_id=case['id'], source_id=source['id'])
            self.assertEqual(exc.exception.code, 'effect-not-granted')
        with self.assertRaises(TraceError): self.call('case.create', objective='test', mode='bypass-automatically')

    def test_static_analysis_real_python_facts(self):
        source = self.source('import json\ndef transform(value):\n    return json.dumps(value)\n')
        result = self.call('analyze', case_id=self.case['id'], source_id=source['id'])
        self.assertIn('transform', json.dumps(result['data']['analysis']))
        self.assertNotIn('observed-runtime', json.dumps(result['data']['analysis']))

    def test_observability_static_dynamic_and_server_gap(self):
        cid = self.case['id']
        features = [{'id':'calculation','reachable':'ui','question':'Does signed addition persist?', 'prerequisites':[], 'obligations':['persist']}]
        self.call('observability.set', case_id=cid, features=features)
        self.assertEqual(self.call('plan', case_id=cid)['data']['route'], 'combined')
        features[0]['prerequisites']=[{'kind':'server','status':'missing','source':'caller-test-service'}]
        self.call('observability.set', case_id=cid, features=features)
        plan = self.call('plan', case_id=cid)['data']
        self.assertEqual(plan['status'],'blocked')
        self.assertEqual(plan['route'],'static-with-observation-gap')
        features[0]['reachable']='verified'
        with self.assertRaises(TraceError): self.call('observability.set', case_id=cid, features=features)

    def test_derived_reference_isolation(self):
        source = self.source('print(1)\n')
        derived = self.call('source.derive', case_id=self.case['id'], source_id=source['id'], offset=6, expected_hex='31', replacement_hex='32')
        self.assertEqual(derived['data']['role'], 'derived')
        self.assertNotEqual(source['data']['sha256'], derived['data']['sha256'])
        self.assertEqual((self.base/'source.py').read_text(), 'print(1)\n')
        with self.assertRaises(TraceError): self.call('capture', case_id=self.case['id'], source_id=derived['id'])

    def test_child_result_and_parent_stale(self):
        parent = self.case['id']
        child = self.call('subtask.create', case_id=parent, question='Find component JSON interface', target_kind='development-component')
        source = self.source('def interface(x): return x\n', case_id=child['id'])
        obs = self.call('analyze', case_id=child['id'], source_id=source['id'])
        result = self.call('subtask.result', case_id=child['id'], evidence_ids=[obs['id']], contract={'input':'JSON','output':'JSON'}, unknowns=[])
        self.assertEqual(result['case_id'], parent)
        verdict = self.store.create('verdict', {'current':True,'status':'pass'}, parent)
        (self.base/'source.py').write_text('def interface(x): return [x]\n')
        with self.assertRaises(TraceError): self.store.check_source(source['id'])
        self.assertFalse(self.store.get('verdict',verdict['id'])['data']['current'])

    @unittest.skipUnless(os.name=='nt', 'Windows Job-qualified dynamic acceptance; POSIX retained as experimental')
    def test_real_capture_expected_error_exit(self):
        source = self.source('import sys\nprint("bad input")\nsys.exit(2)\n')
        obs = self.call('capture', case_id=self.case['id'], source_id=source['id'], fixture={'id':'error','expect_exit':2})
        self.assertEqual(obs['data']['capture']['status'],'completed')
        self.assertEqual(obs['data']['capture']['process_status'],'failed')
        self.assertEqual(obs['data']['capture']['exit_code'],2)

    @unittest.skipUnless(os.name=='nt', 'Windows Job-qualified dynamic acceptance')
    def test_timeout_and_cancel_durable_run(self):
        source=self.source('import time\nprint("started",flush=True)\ntime.sleep(20)\n')
        obs=self.call('capture',case_id=self.case['id'],source_id=source['id'],fixture={'id':'bounded','timeout':0.2,'idle_timeout':0.2})
        self.assertEqual(obs['data']['capture']['process_status'],'timed_out')
        self.assertEqual(obs['data']['capture']['cleanup']['state'],'complete')
        self.assertEqual(self.call('report',case_id=self.case['id'])['acceptance'],'not-verified')

    @unittest.skipUnless(os.name=='nt', 'Windows Job-qualified dynamic acceptance')
    def test_finite_full_loop_with_negative_control(self):
        summary=run_demo(self.base/'real-demo')
        self.assertEqual(summary['status'],'passed-finite-scope')
        self.assertEqual(summary['actual_process_runs'],12)
        self.assertEqual(summary['model_calls'],0)

    def test_spec_and_identity_rejections(self):
        source=self.source()
        obs=self.call('analyze',case_id=self.case['id'],source_id=source['id'])
        with self.assertRaises(TraceError): self.call('spec.freeze',case_id=self.case['id'],reference_id=source['id'],fixtures=[],plan={'obligations':[]},evidence_ids=[obs['id']],requirements=[],scope='nothing')
        with self.assertRaises(TraceError): self.call('compare',case_id=self.case['id'],left_id=obs['id'],right_id=obs['id'],plan={'obligations':[]})

    def test_interrupted_run_retains_unknown_no_replay(self):
        run=self.store.create('run',{'status':'running','identity':{'pid':999999},'cleanup':{'state':'pending'}},self.case['id'])
        reconciled=self.call('run.reconcile',run_id=run['id'])
        self.assertEqual(reconciled['data']['status'],'abandoned')
        self.assertEqual(reconciled['data']['cleanup']['state'],'unknown')
        self.assertEqual(reconciled['data']['recovery'],'reconcile-external-effects-before-retry')

    def test_unknown_needs_evidence(self):
        item=self.call('unknown.add',case_id=self.case['id'],question='missing runtime',reason='not observed')
        with self.assertRaises(TraceError): self.call('unknown.resolve',case_id=self.case['id'],unknown_id=item['id'],evidence_ids=[],resolution='assumed')


if __name__=='__main__': unittest.main()
