"""Whole workspace byte census and real bounded growth/archival lifecycle."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from traceanchor.core import Store, TraceError, io_path, read_regular
from traceanchor import workspace
from traceanchor.process import run_process
ROOT=Path(__file__).resolve().parents[1]/'.validation'/'workspace-tests';ROOT.mkdir(parents=True,exist_ok=True)

class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory(dir=ROOT);self.addCleanup(t.cleanup)
        self.store=Store(Path(t.name)/'workspace',create=True)
        self.case=self.store.create('case',{'objective':'workspace tests','status':'active'})
    def run_record(self):
        return self.store.create('run',{'status':'succeeded','cleanup':{'state':'complete'}},self.case['id'])
    def test_actual_database_work_checkpoint_cache_and_unknown_census(self):
        for relative,data in [('work/a',b'a'*11),('checkpoints/a',b'b'*13),('cache/a',b'c'*17),('private-unknown',b'd'*19)]:
            path=self.store.root/relative;path.parent.mkdir(exist_ok=True);path.write_bytes(data)
        result=workspace.census(self.store)
        self.assertTrue(result['complete'])
        for category,size in [('work',11),('checkpoints',13),('cache',17),('unknown',19)]:
            self.assertEqual(result['categories'][category]['bytes'],size)
        self.assertGreater(result['categories']['database']['bytes'],0)
        self.assertEqual(result['total_bytes'],sum(x['bytes'] for x in result['categories'].values()))
        self.assertFalse(workspace.census(self.store,max_entries=1)['complete'])
    def test_reservation_owner_and_whole_workspace_hard_stop(self):
        initial=workspace.census(self.store)['total_bytes']
        workspace.configure(self.store,{'hard_bytes':initial+262144,'soft_bytes':initial+131072,'work_bytes':262144})
        (self.store.root/'unregistered-large').write_bytes(b'x'*300000)
        with self.assertRaises(TraceError) as error:workspace.reserve(self.store,self.case['id'],1,'new output')
        self.assertEqual(error.exception.code,'workspace-budget')
        self.assertTrue((self.store.root/'unregistered-large').exists())
    def test_owned_archive_copies_real_payload_and_cleans_only_verified_files(self):
        run=self.run_record();item=workspace.register_directory(self.store,'work/owned',self.case['id'],run['id'])
        directory=self.store.root/'work/owned';(directory/'answer.txt').write_bytes(b'needed recovery bytes')
        workspace.finish_directory(self.store,item['id'],'failed',{'state':'complete'})
        self.assertFalse(workspace.clean_directory(self.store,item['id'])['eligible'])
        archived=workspace.archive_directory(self.store,item['id'],reason='Review complete; copy actual bytes before directory retirement')
        material=archived['data']['archived_materials'][0]['material_id']
        self.assertEqual(self.store.read_material(material),b'needed recovery bytes')
        (directory/'unknown-new').write_bytes(b'preserve')
        done=workspace.clean_directory(self.store,item['id'],apply=True)
        self.assertEqual(done['deleted_bytes'],len(b'needed recovery bytes'))
        self.assertEqual((directory/'unknown-new').read_bytes(),b'preserve')
        self.assertEqual(self.store.read_material(material),b'needed recovery bytes')
    def test_pin_and_lease_rechecked_before_work_cleanup(self):
        run=self.run_record();item=workspace.register_directory(self.store,'work/pinned',self.case['id'],run['id'])
        path=self.store.root/'work/pinned/a';path.write_bytes(b'keep')
        workspace.finish_directory(self.store,item['id'],'completed',{'state':'complete'})
        workspace.archive_directory(self.store,item['id'],reason='archive payload')
        self.store.update('workspace-item',item['id'],{'pin':True})
        self.assertEqual(workspace.clean_directory(self.store,item['id'],apply=True)['reason'],'user-pinned')
        self.assertEqual(path.read_bytes(),b'keep')
    @unittest.skipUnless(os.name=='nt','Windows long-path filesystem qualification')
    def test_long_java_style_path_is_counted_archived_and_cleaned(self):
        run=self.run_record();item=workspace.register_directory(self.store,'work/long-output',self.case['id'],run['id'])
        root=self.store.root/'work/long-output'
        selected=root/('namespace-'+'a'*80)/('package-'+'b'*80)/'ShipmentSession.java'
        self.assertGreater(len(str(selected)),260)
        io_path(selected.parent).mkdir(parents=True)
        payload=b'actual long-path evidence';io_path(selected).write_bytes(payload)
        self.assertEqual(read_regular(selected),payload)
        measured=workspace.census(self.store)
        self.assertTrue(measured['complete'],measured['issues'])
        self.assertEqual(measured['categories']['work']['bytes'],len(payload))
        finished=workspace.finish_directory(self.store,item['id'],'completed',{'state':'complete'})
        self.assertTrue(finished['data']['inventory_complete'])
        archived=workspace.archive_directory(self.store,item['id'],reason='Preserve actual deep Java output')
        mid=archived['data']['archived_materials'][0]['material_id']
        self.assertEqual(self.store.read_material(mid),payload)
        cleaned=workspace.clean_directory(self.store,item['id'],apply=True)
        self.assertEqual(cleaned['status'],'completed')
        self.assertEqual(cleaned['deleted_bytes'],len(payload))
        self.assertFalse(io_path(root).exists())
        self.assertEqual(self.store.read_material(mid),payload)

    @unittest.skipUnless(os.name=='nt','Windows owned-process qualification')
    def test_real_external_writer_growth_is_cancelled_and_residual_recorded(self):
        run=self.run_record();item=workspace.register_directory(self.store,'work/growth',self.case['id'],run['id'])
        directory=self.store.root/'work/growth'
        workspace.configure(self.store,{'hard_bytes':16777216,'soft_bytes':12582912,'work_bytes':8192})
        reasons=[]
        def cancel():
            try:workspace.admit(self.store)
            except TraceError as exc:reasons.append(exc.code);return True
            return False
        code='import time\nf=open("growth.bin","wb")\nfor i in range(1000):\n f.write(b"x"*4096);f.flush();time.sleep(0.01)\n'
        result=run_process([sys.executable,'-I','-B','-c',code],cwd=str(directory),timeout=10,idle_timeout=5,cancelled=cancel)
        self.assertEqual(result['status'],'cancelled')
        self.assertEqual(result['cleanup']['state'],'complete')
        self.assertIn('work-budget',reasons)
        self.store.update('run',run['id'],{'status':'cancelled','cleanup':result['cleanup']})
        finished=workspace.finish_directory(self.store,item['id'],'failed',result['cleanup'])
        self.assertTrue(finished['data']['recovery'])
        self.assertGreater(workspace.census(self.store)['categories']['work']['bytes'],8192)
        self.assertTrue((directory/'growth.bin').exists())

if __name__=='__main__':unittest.main()
