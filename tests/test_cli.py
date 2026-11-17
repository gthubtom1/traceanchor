"""Real CLI process tests; no installed/global config or network needed."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from traceanchor.core import Store

PRODUCT = Path(__file__).resolve().parents[1]
ROOT = PRODUCT/'.validation'/'temp'
ROOT.mkdir(parents=True,exist_ok=True)

class CliTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(dir=ROOT);self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.ws=self.root/'workspace'
    def command(self,*args,expected=0,input=None):
        bootstrap='import sys;sys.path.insert(0,'+repr(str(PRODUCT))+');from traceanchor.cli import main;sys.exit(main())'
        result=subprocess.run([sys.executable,'-I','-B','-c',bootstrap,'--workspace',str(self.ws),*args],input=input,capture_output=True,timeout=30,cwd=self.root)
        self.assertEqual(result.returncode,expected,result.stderr.decode('utf-8','replace'))
        return json.loads(result.stdout if result.returncode==0 else result.stderr)
    def test_custom_init_limits_and_no_silent_change(self):
        self.command('init','--hard-bytes','4096','--soft-bytes','3072','--temp-bytes','1024')
        self.assertEqual(Store(self.ws).limits(),{'hard_bytes':4096,'soft_bytes':3072,'temp_bytes':1024})
        result=self.command('init','--hard-bytes','8192',expected=2)
        self.assertEqual(result['error']['code'],'limits-frozen')
        self.assertEqual(Store(self.ws).limits()['hard_bytes'],4096)
    def test_invalid_init_leaves_no_workspace(self):
        self.command('init','--hard-bytes','-1',expected=2)
        self.assertFalse(self.ws.exists())
    def test_real_offline_snapshot_restore_preserves_objects(self):
        self.command('init')
        case=self.command('call','case.create',input=b'{"objective":"before"}')
        cp=self.command('maintenance','snapshot')
        self.command('call','case.revise',input=json.dumps({'case_id':case['id'],'changes':{'objective':'after'}}).encode())
        restored=self.command('maintenance','restore','--checkpoint',cp['id'])
        self.assertEqual(restored['status'],'restored')
        self.assertEqual(Store(self.ws).get('case',case['id'])['data']['objective'],'before')
        self.assertTrue((self.ws/'checkpoints'/(restored['rollback_to']+'.json')).is_file())
    def test_restore_requires_checkpoint_and_bad_json_structured(self):
        self.command('init')
        self.assertEqual(self.command('maintenance','restore',expected=2)['error']['code'],'invalid-input')
        self.assertEqual(self.command('call','case.create',input=b'{"objective":"a","objective":"b"}',expected=2)['error']['code'],'invalid-json')

if __name__=='__main__':unittest.main()
