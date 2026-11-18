"""Adapter fault controls use stubs; real qualification is tools/qualify_apk.py."""
import json
from pathlib import Path
import tempfile
import unittest

from traceanchor.apk_adapter import analyze

TEST_ROOT = Path(__file__).resolve().parents[1] / '.validation'


class ApkAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        TEST_ROOT.mkdir(exist_ok=True)

    def fixture(self, root):
        target, jar = root / 'sample.apk', root / 'jadx.jar'
        target.write_bytes(b'self-authored placeholder, not an APK execution')
        jar.write_bytes(b'stub tool identity')
        return target, jar

    def executor(self, *, bad_version=False, exit_code=0, cleanup='complete', emit=True,
                 diagnostic=False, count=1):
        calls = []
        def execute(argv, input_bytes=b'', env=None):
            self.assertTrue(env and 'JADX_CONFIG_DIR' in env)
            self.assertIn('jadx.cli.JadxCLI', argv)
            self.assertNotIn('-jar', argv)
            self.assertIn('--config', argv)
            self.assertEqual(argv[argv.index('--config') + 1], 'none')
            self.assertEqual(len({Path(value).parent for value in env.values()}), 1)
            self.assertTrue(all(Path(value).is_dir() for value in env.values()))
            calls.append(argv)
            version = '--version' in argv
            if not version and emit:
                out = Path(argv[argv.index('-d') + 1])
                out.mkdir(parents=True)
                for index in range(count):
                    (out / ('Sample%d.java' % index)).write_text(
                        'public class Sample {\n public int quote(int n) {\n'
                        '  return Rules.price(n);\n }\n}\n' +
                        ('// JADX ERROR: Method not decompiled\n' if diagnostic else ''),
                        encoding='utf-8')
            return {'status': 'failed' if (version and bad_version) or (not version and exit_code) else 'succeeded',
                    'exit_code': 2 if version and bad_version else (0 if version else exit_code),
                    'stdout': b'1.5.6\n' if version else b'partial diagnostic\n',
                    'stderr': b'', 'cleanup': {'state': cleanup}, 'output_truncated': False}
        return execute, calls

    def test_semantic_source_preserved_and_hints_labelled(self):
        with tempfile.TemporaryDirectory(prefix='apk-unit-', dir=TEST_ROOT) as name:
            root = Path(name)
            target, jar = self.fixture(root)
            execute, calls = self.executor()
            result = analyze(target, root, execute, java='explicit-java', jadx_jar=str(jar))
            self.assertEqual(result['status'], 'complete')
            self.assertEqual(result['tool']['version'], '1.5.6')
            self.assertEqual(len(calls), 2)
            self.assertTrue(any(f['kind'] == 'java-method' and f['name'] == 'quote' for f in result['facts']))
            hint = next(f for f in result['facts'] if f['kind'] == 'java-call-hint')
            self.assertEqual(hint['callee'], 'Rules.price')
            self.assertEqual(hint['line'], 3)
            self.assertIn('inferred', hint['evidence'])
            for artifact in result['artifacts']:
                self.assertFalse(Path(artifact['path']).is_absolute())
                self.assertTrue((root / artifact['path']).is_file())
            self.assertEqual(target.read_bytes(), b'self-authored placeholder, not an APK execution')
            json.dumps(result)

    def test_bad_version_stops_before_decompile(self):
        with tempfile.TemporaryDirectory(prefix='apk-unit-', dir=TEST_ROOT) as name:
            root = Path(name)
            target, jar = self.fixture(root)
            execute, calls = self.executor(bad_version=True)
            result = analyze(target, root, execute, java='java', jadx_jar=str(jar))
            self.assertEqual(result['status'], 'blocked')
            self.assertEqual(len(calls), 1)

    def test_failed_tool_stdout_never_becomes_success(self):
        with tempfile.TemporaryDirectory(prefix='apk-unit-', dir=TEST_ROOT) as name:
            root = Path(name)
            target, jar = self.fixture(root)
            execute, _ = self.executor(exit_code=7)
            result = analyze(target, root, execute, java='java', jadx_jar=str(jar))
            self.assertEqual(result['status'], 'partial')
            self.assertEqual(result['runs'][-1]['exit_code'], 7)

    def test_missing_fresh_sources_rejects_old_tree(self):
        with tempfile.TemporaryDirectory(prefix='apk-unit-', dir=TEST_ROOT) as name:
            root = Path(name)
            target, jar = self.fixture(root)
            execute, _ = self.executor()
            first = analyze(target, root, execute, java='java', jadx_jar=str(jar))
            missing, _ = self.executor(emit=False)
            second = analyze(target, root, missing, java='java', jadx_jar=str(jar))
            self.assertEqual(second['status'], 'failed')
            self.assertNotEqual(first['attempt'], second['attempt'])
            self.assertFalse(second['facts'])

    def test_partial_diagnostics_and_file_budget(self):
        for options in ({'diagnostic': True}, {'count': 2}):
            with self.subTest(options=options), tempfile.TemporaryDirectory(prefix='apk-unit-', dir=TEST_ROOT) as name:
                root = Path(name)
                target, jar = self.fixture(root)
                execute, _ = self.executor(**options)
                result = analyze(target, root, execute, java='java', jadx_jar=str(jar), max_files=1)
                self.assertEqual(result['status'], 'partial')
                self.assertTrue(result['unknowns'])

    def test_unknown_cleanup_stops(self):
        with tempfile.TemporaryDirectory(prefix='apk-unit-', dir=TEST_ROOT) as name:
            root = Path(name)
            target, jar = self.fixture(root)
            execute, calls = self.executor(cleanup='unknown')
            result = analyze(target, root, execute, java='java', jadx_jar=str(jar))
            self.assertEqual(result['status'], 'blocked')
            self.assertEqual(len(calls), 1)

    def test_decompile_unknown_cleanup_does_not_consume_output(self):
        with tempfile.TemporaryDirectory(prefix='apk-unit-', dir=TEST_ROOT) as name:
            root = Path(name)
            target, jar = self.fixture(root)
            base, _ = self.executor()
            def execute(argv, input_bytes=b'', env=None):
                raw = base(argv, input_bytes=input_bytes, env=env)
                if '--version' not in argv:
                    raw['cleanup'] = {'state': 'unknown'}
                return raw
            result = analyze(target, root, execute, java='java', jadx_jar=str(jar))
            self.assertEqual(result['status'], 'blocked')
            self.assertFalse(result['facts'])

    def test_target_mutation_invalidates_static_identity(self):
        with tempfile.TemporaryDirectory(prefix='apk-unit-', dir=TEST_ROOT) as name:
            root = Path(name)
            target, jar = self.fixture(root)
            base, _ = self.executor()
            def execute(argv, input_bytes=b'', env=None):
                raw = base(argv, input_bytes=input_bytes, env=env)
                if '--version' not in argv:
                    target.write_bytes(b'changed input')
                return raw
            result = analyze(target, root, execute, java='java', jadx_jar=str(jar))
            self.assertEqual(result['status'], 'invalid')
            self.assertTrue(any('changed during' in x for x in result['unknowns']))

    def test_one_long_line_obeys_fact_cap(self):
        with tempfile.TemporaryDirectory(prefix='apk-unit-', dir=TEST_ROOT) as name:
            root = Path(name)
            target, jar = self.fixture(root)
            base, _ = self.executor()
            def execute(argv, input_bytes=b'', env=None):
                raw = base(argv, input_bytes=input_bytes, env=env)
                if '--version' not in argv:
                    out = Path(argv[argv.index('-d') + 1])
                    (out / 'Sample0.java').write_text('class X { void x() {\n' + 'x();' * 15000 + '\n}}')
                return raw
            result = analyze(target, root, execute, java='java', jadx_jar=str(jar))
            self.assertEqual(result['status'], 'partial')
            self.assertEqual(len(result['facts']), 10000)

    def test_invalid_budget_and_missing_tool(self):
        with tempfile.TemporaryDirectory(prefix='apk-unit-', dir=TEST_ROOT) as name:
            root = Path(name)
            target, jar = self.fixture(root)
            execute, calls = self.executor()
            result = analyze(target, root, execute, java='java', jadx_jar=str(jar), max_files=0)
            self.assertEqual(result['status'], 'failed')
            self.assertFalse(calls)
            jar.unlink()
            result = analyze(target, root, execute, java='java', jadx_jar=str(jar))
            self.assertEqual(result['status'], 'failed')
            self.assertFalse(calls)


if __name__ == '__main__':
    unittest.main()
