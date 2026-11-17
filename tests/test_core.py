import base64
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

from traceanchor.core import Store, TraceError, child_path, digest, parse_json, read_regular
from traceanchor import lifecycle
from traceanchor.service import dispatch

ROOT = Path(__file__).resolve().parents[1] / '.validation' / 'temp'
ROOT.mkdir(parents=True, exist_ok=True)


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.store = Store(self.base / 'ws', create=True)
        self.case = self.store.create('case', {'status': 'active', 'allowed_effects': ['read'], 'budgets': {'max_bytes': 1024 * 1024}})

    def test_real_read_identity(self):
        path = self.base / 'file.txt'
        path.write_bytes(b'abc')
        self.assertEqual(read_regular(path), b'abc')
        with self.assertRaises(TraceError):
            read_regular(path, 2)

    def test_json_duplicate_and_nonfinite_rejected(self):
        for raw in ('{"x":1,"x":2}', '{"x":NaN}', '[] junk'):
            with self.assertRaises(TraceError): parse_json(raw)

    def test_revision_and_history(self):
        item = self.store.create('unknown', {'status': 'open'}, self.case['id'])
        self.store.update('unknown', item['id'], {'status': 'resolved'}, 1)
        with self.assertRaises(TraceError) as caught: self.store.update('unknown', item['id'], {'status': 'open'}, 1)
        self.assertEqual(caught.exception.code, 'revision-conflict')
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM history WHERE id=?', (item['id'],)).fetchone()[0], 2)

    def test_concurrent_revision_only_one_wins(self):
        results = []
        barrier = threading.Barrier(2)
        def edit():
            barrier.wait()
            try: self.store.update('case', self.case['id'], {'writer': 1}, 1); results.append('ok')
            except TraceError as exc: results.append(exc.code)
        workers = [threading.Thread(target=edit) for _ in range(2)]
        for w in workers: w.start()
        for w in workers: w.join(10)
        self.assertCountEqual(results, ['ok', 'revision-conflict'])

    def test_newer_schema_not_reset(self):
        with self.store.connect() as db: db.execute('PRAGMA user_version=99')
        with self.assertRaises(TraceError): Store(self.store.root)
        with self.store.connect() as db: self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 99)

    def test_nonowned_directory_rejected(self):
        path = self.base / 'other'
        path.mkdir(); (path / 'mine').write_text('keep')
        with self.assertRaises(TraceError): Store(path, create=True)
        self.assertEqual((path / 'mine').read_text(), 'keep')

    def test_traversal_and_link_rejected(self):
        for path in ('../outside', '/absolute', 'C:/absolute'):
            with self.assertRaises(TraceError): child_path(self.store.root, path)
        try: (self.store.root / 'linked').symlink_to(self.base, target_is_directory=True)
        except OSError: return  # Windows privilege optional; hardlink tested separately.
        with self.assertRaises(TraceError): child_path(self.store.root, 'linked/child')

    def test_material_integrity_and_dedup(self):
        a = self.store.put_bytes(self.case['id'], b'hello')
        b = self.store.put_bytes(self.case['id'], b'hello', 'L3', 'temporary')
        self.assertEqual(a['path'], b['path'])
        self.assertEqual(lifecycle.usage(self.store)['physical_registered_bytes'], 5)
        (self.store.root / a['path']).write_bytes(b'xxxxx')
        with self.assertRaises(TraceError): self.store.read_material(a['id'])

    def test_full_file_hash_changes_after_50mib(self):
        # Full-file identity is covered with a manageable >50MiB original fixture.
        path = self.base / 'large.bin'
        path.write_bytes(b'x' * (50 * 1024 * 1024) + b'A')
        before = digest(read_regular(path))
        with path.open('r+b') as f: f.seek(-1, 2); f.write(b'B')
        self.assertNotEqual(before, digest(read_regular(path)))

    def test_gc_protections_and_real_l3_delete(self):
        protected = {}
        for tier in ('L1', 'L2', 'L3'):
            protected[tier] = self.store.put_bytes(self.case['id'], tier.encode(), tier, 'test')
        pinned = self.store.put_bytes(self.case['id'], b'pinned', 'L3', 'test')
        lifecycle.pin(self.store, pinned['id'])
        referenced = self.store.put_bytes(self.case['id'], b'referenced', 'L3', 'test')
        self.store.add_ref(self.case['id'], referenced['id'])
        active = self.store.put_bytes(self.case['id'], b'active', 'L3', 'test')
        with self.store.transaction() as db: db.execute('UPDATE materials SET active=1 WHERE id=?', (active['id'],))
        plan = lifecycle.preview(self.store)
        reasons = {r['id']: r['reason'] for r in plan['items']}
        self.assertEqual(reasons[protected['L1']['id']], 'long-term-asset')
        self.assertEqual(reasons[protected['L2']['id']], 'case-not-accepted-and-archived')
        self.assertEqual(reasons[pinned['id']], 'user-pinned')
        self.assertEqual(reasons[referenced['id']], 'referenced-evidence-or-recovery')
        done = lifecycle.clean(self.store)
        self.assertEqual(done['data']['reclaimed_bytes'], 2)
        self.assertFalse((self.store.root / protected['L3']['path']).exists())
        for m in (protected['L1'], protected['L2'], pinned, referenced, active): self.assertEqual(self.store.read_material(m['id']), self.store.read_material(m['id']))

    def test_gc_shared_blob_retained_and_promotion(self):
        a = self.store.put_bytes(self.case['id'], b'shared', 'L3', 'tmp')
        b = self.store.put_bytes(self.case['id'], b'shared', 'L1', 'evidence')
        lifecycle.clean(self.store, ids=[a['id']])
        self.assertEqual(self.store.read_material(b['id']), b'shared')
        c = self.store.put_bytes(self.case['id'], b'promote', 'L3', 'tmp')
        lifecycle.promote(self.store, c['id'], owner=self.case['id'])
        self.assertEqual(self.store.material(c['id'])['tier'], 'L1')
        self.assertFalse(next(r for r in lifecycle.preview(self.store)['items'] if r['id'] == c['id'])['eligible'])

    def test_gc_hardlink_and_unknown_preserved(self):
        m = self.store.put_bytes(self.case['id'], b'linked', 'L3', 'tmp')
        os.link(self.store.root / m['path'], self.base / 'hardlink')
        unknown = self.store.root / 'objects' / 'unknown'
        unknown.write_bytes(b'not-registered')
        lifecycle.clean(self.store)
        self.assertEqual(self.store.read_material(m['id']), b'linked')
        self.assertEqual(unknown.read_bytes(), b'not-registered')

    def test_gc_l2_only_after_verified_archive(self):
        m = self.store.put_bytes(self.case['id'], b'intermediate', 'L2', 'work')
        archive = self.store.put_bytes(self.case['id'], b'archive', 'L1', 'archive')
        self.store.update('case', self.case['id'], {'status': 'closed', 'disposition': 'accepted', 'archive_id': archive['id']})
        done = lifecycle.clean(self.store, ids=[m['id']])
        self.assertEqual(done['data']['reclaimed_bytes'], len(b'intermediate'))
        self.assertEqual(self.store.read_material(archive['id']), b'archive')

    def test_gc_cancel_resume_and_reference_added_after_preview(self):
        a = self.store.put_bytes(self.case['id'], b'cancel', 'L3', 'test')
        event = threading.Event(); event.set()
        result = lifecycle.clean(self.store, ids=[a['id']], cancel=event)
        self.assertEqual(result['data']['status'], 'interrupted')
        self.store.add_ref(self.case['id'], a['id'])
        result = lifecycle.clean(self.store, ids=result['data']['pending'])
        self.assertEqual(result['data']['results'][0]['reason'], 'referenced-evidence-or-recovery')

    def test_disk_budget_keeps_l1(self):
        a = self.store.put_bytes(self.case['id'], b'keep')
        with self.store.transaction() as db: db.execute("UPDATE meta SET value=? WHERE key='limits'", ('{"hard_bytes":5,"soft_bytes":4,"temp_bytes":2}',))
        with self.assertRaises(TraceError) as e: self.store.put_bytes(self.case['id'], b'too-much')
        self.assertEqual(e.exception.code, 'disk-budget')
        self.assertEqual(self.store.read_material(a['id']), b'keep')

    def test_export_import_integrity_and_portability(self):
        path = self.base / 'source.txt'; path.write_bytes(b'evidence')
        # use public-case contract for service calls
        case = dispatch(self.store.root, 'case.create', {'objective': 'inspect'})
        dispatch(self.store.root, 'source.add', {'case_id': case['id'], 'path': str(path)})
        bundle = dispatch(self.store.root, 'export', {'case_id': case['id']})
        self.assertNotIn(str(self.base), json.dumps(bundle))
        other = Store(self.base / 'other-ws', create=True)
        done = dispatch(other.root, 'import', bundle)
        self.assertEqual(done['imported_records'], 2)
        source = other.list('source', case['id'])[0]
        self.assertEqual(other.read_material(source['data']['material_id']), b'evidence')
        bundle['sha256'] = '0' * 64
        with self.assertRaises(TraceError): dispatch(other.root, 'import', bundle)


if __name__ == '__main__': unittest.main()
