import http.server
import json
from pathlib import Path
import tempfile
import threading
import unittest

from traceanchor.core import Store, TraceError
from traceanchor.http_observer import observe
from traceanchor.service import dispatch

ROOT=Path(__file__).resolve().parents[1]/'.validation'/'temp'
ROOT.mkdir(parents=True,exist_ok=True)


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def do_GET(self):
        if self.path=='/redirect':
            self.send_response(302);self.send_header('Location','http://example.invalid/');self.end_headers();return
        if self.path=='/account':
            # Reaching an interface is not proving the protected business function.
            body=b'{"interface":"visible","function":"blocked","reason":"test-session-required"}'
            self.send_response(401)
        else:
            body=b'{"value":7,"state":"ready"}' if self.path=='/data' else b'x'*2048
            self.send_response(200)
        self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.send_header('Set-Cookie','test-only-must-not-retain');self.end_headers();self.wfile.write(body)


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
        cls.worker=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.worker.start()
        cls.url='http://127.0.0.1:'+str(cls.server.server_port)
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.worker.join(5)

    def test_real_local_response(self):
        result=observe(self.url+'/data')
        self.assertEqual(result['http_status'],200)
        self.assertEqual(json.loads(result['body'])['value'],7)
        self.assertNotIn('set-cookie',result['headers'])
        self.assertEqual(result['digest_scope'],'complete-response-body')

    def test_access_state_not_business_pass(self):
        result=observe(self.url+'/account')
        self.assertEqual(result['http_status'],401)
        self.assertEqual(json.loads(result['body'])['function'],'blocked')
        self.assertNotIn('pass',result.values())

    def test_redirect_and_external_and_secrets_refused(self):
        for url in (self.url+'/redirect','http://192.0.2.1/x','http://user:pass@127.0.0.1/x',self.url+'/x?token=secret'):
            with self.assertRaises(TraceError): observe(url)

    def test_output_limit_partial_not_complete(self):
        result=observe(self.url+'/large',max_bytes=32)
        self.assertEqual(len(result['body']),32)
        self.assertTrue(result['truncated'])
        self.assertEqual(result['status'],'partial')

    def test_missing_service_is_unavailable_not_fixed(self):
        with self.assertRaises(TraceError) as error: observe('http://127.0.0.1:0/data',timeout=0.2)
        self.assertEqual(error.exception.code,'observation-unavailable')

    def test_service_requires_network_effect_and_keeps_evidence(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            store=Store(Path(temp)/'ws',create=True)
            path=Path(temp)/'contract.json';path.write_text('{"path":"/data"}')
            case=dispatch(store.root,'case.create',{'objective':'Observe local service','target_kind':'protocol'})
            source=dispatch(store.root,'source.add',{'case_id':case['id'],'path':str(path)})
            args={'case_id':case['id'],'source_id':source['id'],'url':self.url+'/data'}
            with self.assertRaises(TraceError): dispatch(store.root,'observe.http',args)
            dispatch(store.root,'case.revise',{'case_id':case['id'],'changes':{'allowed_effects':['read','network']}})
            observation=dispatch(store.root,'observe.http',args)
            self.assertEqual(observation['data']['http']['status'],'observed')
            self.assertEqual(json.loads(store.read_material(observation['data']['body_material']))['value'],7)

    def test_http_charges_shared_run_budget(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            store=Store(Path(temp)/'ws',create=True)
            path=Path(temp)/'contract.json';path.write_text('{}')
            case=dispatch(store.root,'case.create',{'objective':'one HTTP request','allowed_effects':['read','network'],'budgets':{'max_runs':1}})
            source=dispatch(store.root,'source.add',{'case_id':case['id'],'path':str(path)})
            args={'case_id':case['id'],'source_id':source['id'],'url':self.url+'/data'}
            dispatch(store.root,'observe.http',args)
            with self.assertRaises(TraceError) as error:dispatch(store.root,'observe.http',args)
            self.assertEqual(error.exception.code,'task-budget')
            runs=store.list('run',case['id'])
            self.assertEqual(len(runs),1)
            self.assertEqual(runs[0]['data']['cleanup']['state'],'complete')
            self.assertGreater(runs[0]['data']['reserved_seconds'],0)


if __name__=='__main__': unittest.main()
