"""Real native professional service tests on an original, reproducible fixture."""
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from traceanchor.core import Store, TraceError
from traceanchor.process import run_process
from traceanchor.service import dispatch
from traceanchor import workspace
ROOT=Path(__file__).resolve().parents[1]
TEMP=ROOT/'.validation'/'tool-tests';TEMP.mkdir(parents=True,exist_ok=True)

class ProfessionalServiceTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory(dir=TEMP);self.addCleanup(t.cleanup)
        self.base=Path(t.name);self.store=Store(self.base/'ws',create=True)
    def test_read_only_case_does_not_get_tool_execution(self):
        path=self.base/'selected.bin';path.write_bytes(b'not executable')
        case=dispatch(self.store.root,'case.create',{'objective':'read only'})
        src=dispatch(self.store.root,'source.add',{'case_id':case['id'],'path':str(path)})
        with self.assertRaises(TraceError) as error:
            dispatch(self.store.root,'professional.run',{'case_id':case['id'],'source_id':src['id'],'method':'native.disassemble'})
        self.assertEqual(error.exception.code,'effect-not-granted')
        self.assertEqual(self.store.list('run'),[])

    @unittest.skipUnless(os.name=='nt' and all(shutil.which(x) for x in ('gcc','objdump','gdb')),'Optional qualified Windows GNU native tools')
    def test_actual_service_disassembly_and_gdb_observation(self):
        executable=self.base/'parcel.exe'
        built=run_process([shutil.which('gcc'),'-g','-O0','-fno-inline','-o',str(executable),str(ROOT/'examples/native/parcel.c')],cwd=str(self.base),timeout=30,idle_timeout=15)
        self.assertEqual(built['exit_code'],0,built['stderr'])
        case=dispatch(self.store.root,'case.create',{'objective':'runtime fee branch','target_kind':'native','allowed_effects':['read','execute']})
        src=dispatch(self.store.root,'source.add',{'case_id':case['id'],'path':str(executable)})
        args={'case_id':case['id'],'source_id':src['id'],'method':'native.disassemble','options':{'symbols':['dispatch_command','quote_parcel','reserve_parcels']}}
        static=dispatch(self.store.root,'professional.run',args)
        self.assertEqual(static['data']['professional']['status'],'complete')
        self.assertTrue(static['data']['raw_material_ids'])
        args.update(method='native.trace',options={'breakpoints':['quote_parcel'],'expressions':['service_zone'],'arguments':['scenario.txt'],'input_files':{'scenario.txt':'quote 501 1\n'},'test_environment':{'TRACEANCHOR_PARCEL_ZONE':'remote'}})
        dynamic=dispatch(self.store.root,'professional.run',args)
        self.assertEqual(dynamic['data']['professional']['status'],'complete')
        self.assertIn('"cents":920',dynamic['data']['professional']['runtime_trace'])
        self.assertEqual(workspace.census(self.store)['categories']['database']['files'],1)
        items=self.store.list('workspace-item')
        self.assertEqual(len(items),2)
        self.assertTrue(all(x['data']['inventory_complete'] for x in items))
        for run in self.store.list('run'):
            self.assertEqual(run['data']['cleanup']['state'],'complete')
        self.assertFalse(workspace.census(self.store)['reserved_bytes'])

if __name__=='__main__':unittest.main()
