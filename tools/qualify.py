"""Stdlib engineering qualification; run from the product checkout.

    python -I tools/qualify.py
    python -I tools/qualify.py --tests-only --output .validation/unit-result.json
    python -I tools/qualify.py --static-only --output .validation/static-result.json

Default output is docs/qualification.json. Artifacts stay in a new owned
.validation/qualification-* directory. A filtered --pattern is a partial run,
never full-suite qualification. No build/install, external target or model call.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import re
import statistics
import subprocess
import sys
import tempfile
import time
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
# Explicit checkout import, including when launched with Python isolated mode.
sys.path.insert(0, str(ROOT))


def safe_text(value):
    """Reports contain relative identities, not workstation paths/usernames."""
    text = str(value)
    for path, replacement in ((ROOT, '<product>'), (Path.home(), '<home>'),
                              (Path(sys.executable).parent, '<python>')):
        for form in (str(path), path.as_posix(), str(path).replace('\\', '\\\\')):
            text = text.replace(form, replacement)
    text = re.sub(r'(?i)\b[A-Z]:[\\/][^\s\"\'<>]*', '<absolute-path>', text)
    text = re.sub(r'(?<![A-Za-z0-9_<>:])/(?:[^\s\"\'<>]+)', '<absolute-path>', text)
    return text[:12000]


def public_data(value):
    if isinstance(value, str):
        return safe_text(value)
    if isinstance(value, list):
        return [public_data(item) for item in value]
    if isinstance(value, dict):
        return {key: public_data(item) for key, item in value.items()}
    return value


def identity():
    """Hash executable source/tests/config, excluding changing output artifacts."""
    paths = [ROOT / '_build.py', ROOT / 'pyproject.toml', ROOT / 'tools' / 'install_journey.py', Path(__file__),
             ROOT / '.github' / 'workflows' / 'qualification.yml']
    for directory in ('traceanchor', 'tests', 'tools'):
        paths.extend((ROOT / directory).rglob('*.py'))
    manifest = {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(set(paths)) if path.is_file()}
    encoded = json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()
    return {'sha256': hashlib.sha256(encoded).hexdigest(), 'files': manifest,
            'scope': 'Python product/tests, build configuration, qualifier and CI; not dependencies or documentation'}


@contextlib.contextmanager
def owned_temp(directory):
    """Redirect default temp users and their child interpreters into this run."""
    directory.mkdir()
    previous = tempfile.tempdir
    keys = ('TEMP', 'TMP', 'TMPDIR')
    old = {key: os.environ.get(key) for key in keys}
    tempfile.tempdir = str(directory)
    for key in keys:
        os.environ[key] = str(directory)
    try:
        yield
    finally:
        tempfile.tempdir = previous
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class RecordedResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.outcomes = []

    def note(self, test, status, detail=None):
        item = {'id': test.id(), 'status': status}
        if detail is not None:
            item['detail'] = safe_text(detail)
        self.outcomes.append(item)

    def addSuccess(self, test):
        super().addSuccess(test)
        self.note(test, 'pass')

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.note(test, 'fail', self._exc_info_to_string(err, test))

    def addError(self, test, err):
        super().addError(test, err)
        self.note(test, 'error', self._exc_info_to_string(err, test))

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.note(test, 'skip', reason)

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self.note(test, 'expected-failure', self._exc_info_to_string(err, test))

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self.note(test, 'unexpected-success')

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is not None:
            self.note(subtest, 'fail' if issubclass(err[0], test.failureException) else 'error',
                      self._exc_info_to_string(err, test))


class StaticSkip(unittest.TestCase):
    def __init__(self, original):
        super().__init__('runTest')
        self.original_id = original.id()

    def id(self):
        return self.original_id

    def runTest(self):
        self.skipTest('Dynamic process acceptance intentionally excluded from static-only qualification')


def static_suite(suite):
    dynamic_names = {
        'test_real_capture_expected_error_exit', 'test_timeout_and_cancel_durable_run',
        'test_finite_full_loop_with_negative_control',
        'test_r01_blocking_unknown_invalidates_existing_pass',
        'test_r05_resource_busy_does_not_create_or_charge_run',
        'test_distinct_invalid_utf8_never_passes', 'test_superseded_spec_cannot_be_reaccepted',
        'test_parent_report_checks_child_source_without_child_read',
        'test_real_notification_cancel_managed_capture', 'test_real_eof_cancels_managed_capture',
    }
    result = unittest.TestSuite()
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            result.addTest(static_suite(test))
        elif '.test_process.' in test.id() or test.id().rsplit('.', 1)[-1] in dynamic_names:
            result.addTest(StaticSkip(test))
        else:
            result.addTest(test)
    return result


def run_tests(pattern, static_only=False):
    output = io.StringIO()
    started = time.perf_counter()
    loader = unittest.TestLoader()
    suite = loader.discover(str(ROOT / 'tests'), pattern=pattern, top_level_dir=str(ROOT))
    if static_only:
        suite = static_suite(suite)
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
        result = unittest.TextTestRunner(stream=output, verbosity=0,
                                         resultclass=RecordedResult).run(suite)
    passed = sum(item['status'] == 'pass' for item in result.outcomes)
    return {'status': 'passed' if result.wasSuccessful() and result.testsRun else 'failed',
            'complete_suite': pattern == 'test*.py', 'pattern': pattern,
            'tests_run': result.testsRun, 'passed': passed,
            'failed': len(result.failures), 'errors': len(result.errors),
            'skipped': len(result.skipped), 'expected_failures': len(result.expectedFailures),
            'unexpected_successes': len(result.unexpectedSuccesses),
            'elapsed_seconds': round(time.perf_counter() - started, 6),
            'outcomes': result.outcomes,
            'skip_policy': 'Every skip is retained; skipped capability is not qualified. Protocol stub tests are not host end-to-end proof.'}


def demo(directory):
    from traceanchor.demo import run_demo
    started = time.perf_counter()
    summary = run_demo(directory)
    if (summary.get('status') != 'passed-finite-scope'
            or summary.get('disposition') != 'accepted' or summary.get('model_calls') != 0):
        raise AssertionError('demo did not meet finite acceptance and zero-model-call gates')
    return {'status': 'passed', 'elapsed_seconds': round(time.perf_counter() - started, 6),
            'artifact_directory': directory.relative_to(ROOT).as_posix(), 'summary': summary,
            'scope': 'Actual finite synthetic reference/spec/wrong candidate/fix/acceptance, not broad target support'}


def process_baseline(directory, samples):
    from traceanchor.process import run_process
    directory.mkdir()
    code = ('import sys; data=sys.stdin.buffer.read(); '
            'sys.stdout.buffer.write(data[::-1]); '
            'sys.stderr.buffer.write(b"fixture-stderr")')
    argv = [sys.executable, '-I', '-B', '-c', code]
    payload = bytes(range(256)) * 16
    measurements = {'raw_subprocess': [], 'managed_runner': []}
    cleanup = []
    for _ in range(samples):
        started = time.perf_counter()
        raw = subprocess.run(argv, cwd=directory, input=payload, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, timeout=5, shell=False, close_fds=True)
        measurements['raw_subprocess'].append(time.perf_counter() - started)
        if raw.returncode != 0 or raw.stdout != payload[::-1] or raw.stderr != b'fixture-stderr':
            raise AssertionError('raw baseline output/exit mismatch')
        started = time.perf_counter()
        managed = run_process(argv, cwd=directory, input_bytes=payload, timeout=5,
                              idle_timeout=3, output_limit=8192)
        measurements['managed_runner'].append(time.perf_counter() - started)
        cleanup.append(managed['cleanup']['state'])
        if (managed['status'] != 'succeeded' or managed['exit_code'] != 0
                or managed['stdout'] != raw.stdout or managed['stderr'] != raw.stderr
                or managed['output_truncated'] or managed['cleanup']['state'] != 'complete'
                or managed['containment'] != 'windows-job'):
            raise AssertionError('managed baseline output/exit/ownership mismatch')
    timing = {name: {'samples_seconds': [round(x, 6) for x in values],
                     'median_seconds': round(statistics.median(values), 6)}
              for name, values in measurements.items()}
    raw_median = statistics.median(measurements['raw_subprocess'])
    managed_median = statistics.median(measurements['managed_runner'])
    return {'status': 'passed', 'samples_per_method': samples, 'timing': timing,
            'median_overhead_seconds': round(managed_median - raw_median, 6),
            'median_managed_over_raw_ratio': round(managed_median / raw_median, 3),
            'output_equal': True, 'stdout_bytes': len(payload), 'stderr_bytes': 14,
            'output_sha256': hashlib.sha256(payload[::-1]).hexdigest(), 'cleanup_states': cleanup,
            'method': 'Same fixed Python echo/reversal, input and interpreter; sequential raw then managed, cold-start included, no statistical superiority claim',
            'limitations': ['Raw subprocess is only a simple successful-root baseline; it does not offer Job ownership or equivalent crash recovery',
                            'These are local engineering resource/startup measurements, not model effectiveness or product superiority']}


def storage_baseline(directory):
    from traceanchor.core import Store
    from traceanchor import lifecycle
    directory.mkdir()
    raw = directory / 'naive-files'
    raw.mkdir()
    keep, temporary = b'L1-evidence:' * 4096, b'L3-temporary:' * 4096
    started = time.perf_counter()
    for name, data in (('evidence', keep), ('duplicate', keep), ('temporary', temporary)):
        (raw / name).write_bytes(data)
    naive_write = time.perf_counter() - started
    naive_before = sum(path.stat().st_size for path in raw.iterdir())
    store = Store(directory / 'cas', create=True)
    case = store.create('case', {'status': 'active', 'objective': 'Synthetic storage measurement'})
    started = time.perf_counter()
    evidence = store.put_bytes(case['id'], keep, 'L1', 'qualification-evidence')
    duplicate = store.put_bytes(case['id'], keep, 'L3', 'qualification-duplicate')
    scratch = store.put_bytes(case['id'], temporary, 'L3', 'qualification-temporary')
    cas_write = time.perf_counter() - started
    def object_bytes():
        return sum(path.stat().st_size for path in (store.root / 'objects').rglob('*') if path.is_file())
    cas_before = object_bytes()
    registered_before = lifecycle.usage(store)['physical_registered_bytes']
    if (evidence['path'] != duplicate['path'] or cas_before != len(keep) + len(temporary)
            or registered_before != cas_before):
        raise AssertionError('CAS deduplication or physical accounting mismatch')
    preview = lifecycle.preview(store)
    started = time.perf_counter()
    cleaned = lifecycle.clean(store, ids=[duplicate['id'], scratch['id']])
    cas_clean = time.perf_counter() - started
    cas_after = object_bytes()
    if (store.read_material(evidence['id']) != keep or cas_after != len(keep)
            or cleaned['data']['reclaimed_bytes'] != len(temporary)
            or not store.material(duplicate['id'])['deleted'] or not store.material(scratch['id'])['deleted']):
        raise AssertionError('cleanup removed evidence or misreported reclaimed object bytes')
    started = time.perf_counter()
    (raw / 'duplicate').unlink()
    (raw / 'temporary').unlink()
    naive_clean = time.perf_counter() - started
    naive_after = sum(path.stat().st_size for path in raw.iterdir())
    if (raw / 'evidence').read_bytes() != keep or naive_after != cas_after:
        raise AssertionError('naive measurement control mismatch')
    return {'status': 'passed', 'naive_files': {'before_bytes': naive_before, 'after_bytes': naive_after,
                'write_seconds': round(naive_write, 6), 'cleanup_seconds': round(naive_clean, 6)},
            'cas_objects': {'before_bytes': cas_before, 'after_bytes': cas_after,
                'registered_before_bytes': registered_before,
                'registered_after_bytes': lifecycle.usage(store)['physical_registered_bytes'],
                'registration_seconds': round(cas_write, 6), 'cleanup_seconds': round(cas_clean, 6),
                'estimated_reclaim_bytes': preview['estimated_reclaim_bytes'],
                'actual_reclaimed_bytes': cleaned['data']['reclaimed_bytes']},
            'dedup_saved_bytes': naive_before - cas_before, 'l1_preserved': True,
            'scope': 'Actual object payload bytes, not SQLite/database overhead, whole-project disk usage, or model effectiveness',
            'baseline_limit': 'Naive control deletes explicitly named synthetic files; it does not reproduce authority, leases, references or recovery guarantees'}


def recovery_baseline(directory):
    from traceanchor.core import Store, TraceError, canonical
    from traceanchor.service import dispatch
    directory.mkdir()
    naive = directory / 'naive-state.json'
    naive.write_text('{"objective":"before"}', encoding='utf-8')
    # Explicit deterministic interruption point, not a claim of crash-frequency.
    naive.write_text('{"objective":', encoding='utf-8')
    try:
        json.loads(naive.read_text(encoding='utf-8'))
        naive_readable = True
    except ValueError:
        naive_readable = False
    store = Store(directory / 'workspace', create=True)
    case = dispatch(store.root, 'case.create', {'objective':'before'})
    try:
        with store.transaction() as db:
            db.execute('UPDATE records SET data=? WHERE id=?', (canonical({'objective':'interrupted'}), case['id']))
            raise RuntimeError('deterministic interruption before commit')
    except RuntimeError:
        pass
    restored = store.get('case', case['id'])['data']['objective'] == 'before'
    selected = directory / 'selected.py'
    selected.write_bytes(b'print(1)\n')
    source = dispatch(store.root, 'source.add', {'case_id':case['id'], 'path':str(selected)})
    before = selected.stat()
    legacy = (before.st_size, before.st_mtime_ns)
    selected.write_bytes(b'print(2)\n')
    os.utime(selected, ns=(before.st_atime_ns, before.st_mtime_ns))
    after = selected.stat()
    legacy_hit = legacy == (after.st_size, after.st_mtime_ns)
    rejected = False
    try:
        store.check_source(source['id'])
    except TraceError as exc:
        rejected = exc.code == 'stale-source'
    if naive_readable or not restored or not legacy_hit or not rejected:
        raise AssertionError('deterministic recovery/freshness negative control failed')
    return {'status':'passed', 'naive_partial_json_readable':naive_readable,
            'transaction_retained_preimage':restored, 'size_mtime_cache_false_hit':legacy_hit,
            'full_source_identity_rejected_changed_bytes':rejected,
            'method':'One injected precommit exception and one same-size/same-mtime source mutation; real files and SQLite',
            'limitations':['Not a power-loss durability or arbitrary filesystem failure proof',
                           'Naive controls intentionally lack transactions and full-content identity; no broad superiority claim',
                           'Peak CPU/RSS and model quality are not measured']}


def measure(function, *args):
    try:
        return function(*args)
    except Exception as exc:
        return {'status': 'failed', 'error': {'type': type(exc).__name__, 'message': safe_text(exc)}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--output', default='docs/qualification.json', help='Contained product-relative JSON output')
    parser.add_argument('--tests-only', action='store_true', help='Unit/integration suite only; no demo or benchmarks')
    parser.add_argument('--static-only', action='store_true', help='No separate dynamic demo/benchmark; no dynamic qualification')
    parser.add_argument('--pattern', default='test*.py', help='unittest discovery pattern; a filter makes qualification partial')
    parser.add_argument('--samples', type=int, default=3, help='Raw/managed samples per method, 1-20')
    args = parser.parse_args(argv)
    if not 1 <= args.samples <= 20:
        parser.error('--samples must be between 1 and 20')
    from traceanchor.core import child_path
    destination = child_path(ROOT, args.output)
    validation = child_path(ROOT, '.validation')
    validation.mkdir(exist_ok=True)
    directory = validation / ('qualification-' + uuid.uuid4().hex[:12])
    directory.mkdir()
    before = identity()
    report = {'schema_version': 1, 'generated_at': dt.datetime.now(dt.timezone.utc).isoformat(),
              'environment': {'python': platform.python_version(), 'implementation': platform.python_implementation(),
                              'platform': sys.platform, 'architecture': platform.machine(), 'os_release': platform.release()},
              'artifact_directory': directory.relative_to(ROOT).as_posix(), 'model_calls': 0,
              'build_install_release': 'not-run; owned by separate release qualification',
              'source_identity': before,
              'scope': 'Local engineering qualification. No paid models, downloaded targets, real host end-to-end claim, or model-effectiveness/superiority measurement.'}
    with owned_temp(directory / 'temp'):
        report['tests'] = measure(run_tests, args.pattern, args.static_only or os.name != 'nt')
        if args.tests_only:
            for name in ('demo', 'process_baseline', 'storage_baseline', 'recovery_baseline'):
                report[name] = {'status': 'not-run', 'reason': '--tests-only'}
        else:
            report['storage_baseline'] = measure(storage_baseline, directory / 'storage')
            report['recovery_baseline'] = measure(recovery_baseline, directory / 'recovery')
            if args.static_only or os.name != 'nt':
                reason = 'Explicit static-only run; POSIX dynamic ownership is experimental' if args.static_only else 'Non-Windows dynamic qualification is not granted'
                report['demo'] = {'status': 'skip', 'reason': reason}
                report['process_baseline'] = {'status': 'skip', 'reason': reason}
            else:
                report['demo'] = measure(demo, directory / 'demo')
                report['process_baseline'] = measure(process_baseline, directory / 'process', args.samples)
    after = identity()
    report['source_unchanged_during_run'] = before == after
    failed = any(report[key].get('status') == 'failed' for key in ('tests', 'demo', 'process_baseline', 'storage_baseline', 'recovery_baseline'))
    tests_ok = report['tests'].get('status') == 'passed'
    full_suite = report['tests'].get('complete_suite', False)
    critical_suffixes = ('test_job_owner_crash_kills_entire_tree', 'test_timeout_cleans_tree_with_inherited_pipes',
                         'test_cancel_with_tree_and_inherited_pipes', 'test_output_limit_cleans_tree_with_inherited_pipes',
                         'test_normal_root_exit_cleans_descendants_holding_pipes',
                         'test_on_start_precedes_target_and_failure_never_executes')
    outcomes = report['tests'].get('outcomes', [])
    critical_ok = all(any(item['id'].endswith('.' + name) and item['status'] == 'pass' for item in outcomes)
                      for name in critical_suffixes)
    dynamic = (os.name == 'nt' and not args.static_only and not args.tests_only and tests_ok and full_suite
               and critical_ok and report['source_unchanged_during_run'] and not failed
               and report['demo']['status'] == 'passed' and report['process_baseline']['status'] == 'passed')
    report['qualification'] = {'status': 'failed' if failed else 'stale' if before != after else 'passed' if full_suite else 'partial',
                             'complete_suite': full_suite, 'windows_dynamic_qualified': dynamic,
                             'critical_process_tests_passed': critical_ok,
                             'posix_dynamic_qualified': False,
                             'scope': 'Windows dynamic qualification requires unchanged source, the complete suite, critical real process tests, separate demo and baseline; skipped tests never qualify their capability'}
    destination.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(public_data(report), ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
    fd, temporary = tempfile.mkstemp(prefix='.qualification-', dir=destination.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print(json.dumps({'status': report['qualification']['status'],
                      'tests_run': report['tests'].get('tests_run', 0),
                      'skipped': report['tests'].get('skipped', 0),
                      'windows_dynamic_qualified': dynamic,
                      'output': destination.relative_to(ROOT).as_posix()}, sort_keys=True))
    return 1 if failed or before != after else 0


if __name__ == '__main__':
    raise SystemExit(main())
