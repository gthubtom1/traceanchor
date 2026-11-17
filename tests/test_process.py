"""Only locally authored synthetic fixtures; no downloaded code or targets."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from traceanchor.process import run_process

PRODUCT = Path(__file__).resolve().parents[1]

# Each synthetic process reports its kernel creation identity and holds a byte
# lock. Tests verify actual kernel exit and lock release, not a guessed sleep.
_TREE = r'''
import json, os, pathlib, subprocess, sys, time
root = pathlib.Path(sys.argv[1])
role = sys.argv[2]
lock = open(root / (role + '.lock'), 'w+b', buffering=0)
lock.write(b'x')
if os.name == 'nt':
    import ctypes, msvcrt
    from ctypes import wintypes as w
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.GetCurrentProcess.argtypes = []
    k.GetCurrentProcess.restype = w.HANDLE
    k.GetProcessTimes.argtypes = [w.HANDLE] + [ctypes.POINTER(w.FILETIME)] * 4
    k.GetProcessTimes.restype = w.BOOL
    ts = [w.FILETIME() for _ in range(4)]
    if not k.GetProcessTimes(k.GetCurrentProcess(), *(ctypes.byref(t) for t in ts)):
        raise ctypes.WinError(ctypes.get_last_error())
    creation = (ts[0].dwHighDateTime << 32) | ts[0].dwLowDateTime
    lock.seek(0)
    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
else:
    import fcntl
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    creation = None
(root / (role + '.json')).write_text(json.dumps({'pid': os.getpid(), 'creation_time': creation}))
if role != 'grandchild':
    next_role = 'child' if role == 'parent' else 'grandchild'
    subprocess.Popen([sys.executable, '-I', sys.argv[0], str(root), next_role, sys.argv[3]],
                     stdin=subprocess.DEVNULL, close_fds=True)
    deadline = time.monotonic() + 5
    while not (root / 'grandchild.json').exists():
        if time.monotonic() > deadline:
            raise RuntimeError('grandchild startup did not finish')
        time.sleep(.01)
if role == 'parent':
    (root / 'ready').write_text('ready')
    print('tree ready', flush=True)
    if sys.argv[3] == 'exit':
        sys.exit(0)
    if sys.argv[3] == 'flood':
        os.write(1, b'x' * 8192)
while True:
    time.sleep(1)
'''


class ProcessTests(unittest.TestCase):
    def setUp(self):
        temp_root = PRODUCT / '.validation' / 'temp'
        temp_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='process-test-', dir=temp_root)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def run_code(self, code, **kwargs):
        return run_process([sys.executable, '-I', '-u', '-c', code], cwd=self.root, **kwargs)

    def assert_clean(self, result):
        self.assertEqual(result['containment'], 'windows-job' if os.name == 'nt' else 'posix-session', result)
        self.assertEqual(result['cleanup']['state'], 'complete' if os.name == 'nt' else 'unknown', result)
        json.dumps({k: v for k, v in result.items() if k not in ('stdout', 'stderr')})

    def wait_for(self, predicate, timeout=6):
        deadline = time.monotonic() + timeout
        while not predicate():
            if time.monotonic() >= deadline:
                self.fail('fixture synchronization deadline exceeded')
            time.sleep(.01)

    def write_tree(self):
        path = self.root / 'tree.py'
        path.write_text(_TREE, encoding='utf-8')
        return path

    def tree_argv(self, mode='wait'):
        return [sys.executable, '-I', '-u', str(self.write_tree()), str(self.root), 'parent', mode]

    def assert_tree_stopped(self):
        for role in ('parent', 'child', 'grandchild'):
            identity = json.loads((self.root / (role + '.json')).read_text())
            if os.name == 'nt':
                self.assert_windows_stopped(identity)
            # The fixture held this exclusive lock throughout its lifetime.
            with open(self.root / (role + '.lock'), 'r+b', buffering=0) as stream:
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    fcntl.flock(stream, fcntl.LOCK_UN)

    def assert_windows_stopped(self, identity):
        import ctypes
        from ctypes import wintypes as w
        k = ctypes.WinDLL('kernel32', use_last_error=True)
        k.OpenProcess.argtypes, k.OpenProcess.restype = [w.DWORD, w.BOOL, w.DWORD], w.HANDLE
        k.GetProcessTimes.argtypes = [w.HANDLE] + [ctypes.POINTER(w.FILETIME)] * 4
        k.GetProcessTimes.restype = w.BOOL
        k.WaitForSingleObject.argtypes, k.WaitForSingleObject.restype = [w.HANDLE, w.DWORD], w.DWORD
        k.CloseHandle.argtypes, k.CloseHandle.restype = [w.HANDLE], w.BOOL
        handle = k.OpenProcess(0x100000 | 0x1000, False, identity['pid'])
        if not handle:
            self.assertEqual(ctypes.get_last_error(), 87)  # no such PID
            return
        try:
            ts = [w.FILETIME() for _ in range(4)]
            self.assertTrue(k.GetProcessTimes(handle, *(ctypes.byref(t) for t in ts)))
            creation = (ts[0].dwHighDateTime << 32) | ts[0].dwLowDateTime
            if creation != identity['creation_time']:
                return  # PID reused; this is not the owned process.
            self.assertEqual(k.WaitForSingleObject(handle, 1000), 0, identity)
        finally:
            k.CloseHandle(handle)

    def test_nonzero_and_raw_stdout_stderr(self):
        result = self.run_code("import os,sys; os.write(1,b'hello\\x00\\xff'); os.write(2,b'err'); sys.exit(7)")
        self.assertEqual(result['status'], 'failed', result)
        self.assertEqual(result['exit_code'], 7)
        self.assertEqual(result['stdout'], b'hello\x00\xff')
        self.assertEqual(result['stderr'], b'err')
        self.assertIsNone(result['error'])
        self.assert_clean(result)

    def test_missing_program(self):
        result = run_process([str(self.root / 'missing-executable')], cwd=self.root)
        self.assertEqual(result['status'], 'failed', result)
        self.assertEqual(result['error']['code'], 'spawn_error', result)
        self.assertIsNone(result['exit_code'])
        self.assert_clean(result)

    def test_binary_stdin_and_eof(self):
        data = bytes(range(256)) * 4096
        result = self.run_code('import sys; d=sys.stdin.buffer.read(); sys.stdout.buffer.write(d)',
                               input_bytes=data, output_limit=len(data))
        self.assertEqual(result['status'], 'succeeded', result)
        self.assertEqual(result['stdout'], data)
        self.assertFalse(result['output_truncated'])
        self.assert_clean(result)

    def test_no_inherited_stdin(self):
        result = self.run_code('import sys; print(len(sys.stdin.buffer.read()))')
        self.assertEqual(result['stdout'].strip(), b'0', result)
        self.assert_clean(result)

    def test_timeout(self):
        result = self.run_code('import time; time.sleep(30)', timeout=.25, idle_timeout=10)
        self.assertEqual(result['status'], 'timed_out', result)
        self.assertLess(result['elapsed_seconds'], 3)
        self.assert_clean(result)

    def test_idle_timeout(self):
        result = self.run_code('import time; print("started",flush=True); time.sleep(30)', timeout=5, idle_timeout=.2)
        self.assertEqual(result['status'], 'timed_out', result)
        self.assertEqual(result['error']['code'], 'idle_timeout')
        self.assertIn(b'started', result['stdout'])
        self.assertLess(result['elapsed_seconds'], 3)
        self.assert_clean(result)

    def test_output_caps_each_stream(self):
        result = self.run_code("import os,time; os.write(1,b'a'*4096); os.write(2,b'b'*4096); time.sleep(30)",
                               output_limit=128)
        self.assertEqual(result['status'], 'output_limit', result)
        self.assertTrue(result['output_truncated'])
        self.assertEqual(result['stdout'], b'a' * 128)
        self.assertEqual(result['stderr'], b'b' * 128)
        self.assertLess(result['elapsed_seconds'], 3)
        self.assert_clean(result)

    def test_zero_output_cap(self):
        result = self.run_code('print("x")', output_limit=0)
        self.assertEqual(result['status'], 'output_limit', result)
        self.assertEqual(result['stdout'], b'')
        self.assertTrue(result['output_truncated'])
        self.assert_clean(result)

    def test_cancel_with_tree_and_inherited_pipes(self):
        event = threading.Event()
        def cancel_when_ready():
            deadline = time.monotonic() + 6
            while time.monotonic() < deadline:
                if (self.root / 'ready').exists():
                    event.set()
                    return
                time.sleep(.01)
        thread = threading.Thread(target=cancel_when_ready)
        thread.start()
        result = run_process(self.tree_argv(), cwd=self.root, cancelled=event, timeout=8)
        thread.join()
        self.assertEqual(result['status'], 'cancelled', result)
        self.assertLess(result['elapsed_seconds'], 4)
        self.assert_clean(result)
        self.assert_tree_stopped()

    def test_timeout_cleans_tree_with_inherited_pipes(self):
        result = run_process(self.tree_argv(), cwd=self.root, timeout=1.0, idle_timeout=3)
        self.assertEqual(result['status'], 'timed_out', result)
        self.assertTrue((self.root / 'ready').exists(), result)
        self.assertLess(result['elapsed_seconds'], 4)
        self.assert_clean(result)
        self.assert_tree_stopped()

    def test_output_limit_cleans_tree_with_inherited_pipes(self):
        result = run_process(self.tree_argv('flood'), cwd=self.root, output_limit=128, timeout=8)
        self.assertEqual(result['status'], 'output_limit', result)
        self.assertEqual(len(result['stdout']), 128)
        self.assert_clean(result)
        self.assert_tree_stopped()

    def test_blocked_stdin_writer_is_bounded(self):
        result = self.run_code('import time; time.sleep(30)', input_bytes=b'x' * (4 * 1048576),
                               timeout=.25, idle_timeout=5)
        self.assertEqual(result['status'], 'timed_out', result)
        self.assertLess(result['elapsed_seconds'], 3)
        self.assert_clean(result)

    def test_assignment_failure_does_not_release_target(self):
        if os.name != 'nt':
            self.skipTest('Windows Job assignment error-path injection')
        from unittest.mock import patch
        marker = self.root / 'executed'
        with patch('traceanchor.process.Job.assign', side_effect=OSError(5, 'synthetic AssignProcessToJobObject failure')):
            result = self.run_code(f'from pathlib import Path; Path({str(marker)!r}).touch()')
        self.assertEqual(result['status'], 'failed', result)
        self.assertEqual(result['error']['code'], 'containment_error')
        self.assertIn('AssignProcessToJobObject', result['error']['message'])
        self.assertEqual(result['containment'], 'none')
        self.assertIsNone(result['target_pid'])
        self.assertEqual(result['cleanup']['state'], 'complete')
        self.assertFalse(marker.exists())

    def test_normal_root_exit_cleans_descendants_holding_pipes(self):
        result = run_process(self.tree_argv('exit'), cwd=self.root, timeout=8)
        self.assertEqual(result['status'], 'succeeded', result)
        self.assertEqual(result['exit_code'], 0)
        self.assertIn(b'tree ready', result['stdout'])
        self.assertLess(result['elapsed_seconds'], 4)
        self.assert_clean(result)
        self.assert_tree_stopped()

    def test_on_start_precedes_target_and_failure_never_executes(self):
        marker = self.root / 'executed'
        seen = []
        def callback(identity):
            self.assertFalse(marker.exists())
            self.assertGreater(identity['pid'], 0)
            self.assertIn('containment', identity)
            seen.append(identity)
            raise RuntimeError('synthetic persistence failure')
        result = self.run_code(f'from pathlib import Path; Path({str(marker)!r}).write_text("ran")', on_start=callback)
        self.assertEqual(len(seen), 1)
        self.assertEqual(result['status'], 'failed', result)
        self.assertEqual(result['error']['code'], 'on_start_failed')
        self.assertIsNone(result['target_pid'])
        self.assertFalse(marker.exists())
        self.assert_clean(result)

    def test_successful_on_start_identity_before_release(self):
        marker = self.root / 'executed'
        seen = []
        def callback(identity):
            self.assertFalse(marker.exists())
            self.assertGreater(identity['pid'], 0)
            if os.name == 'nt':
                self.assertIsInstance(identity['creation_time'], int)
                self.assertGreater(identity['creation_time'], 0)
            seen.append(identity.copy())
        result = self.run_code(f'from pathlib import Path; Path({str(marker)!r}).touch()', on_start=callback)
        self.assertEqual(result['status'], 'succeeded', result)
        self.assertTrue(marker.exists())
        self.assertEqual(len(seen), 1)
        self.assertEqual(result['pid'], seen[0]['pid'])
        self.assertIsInstance(result['target_pid'], int)
        self.assertNotEqual(result['target_pid'], result['pid'])
        self.assert_clean(result)

    def test_callback_can_cancel_before_release(self):
        event = threading.Event()
        marker = self.root / 'executed'
        result = self.run_code(f'from pathlib import Path; Path({str(marker)!r}).touch()',
                               cancelled=event, on_start=lambda _: event.set())
        self.assertEqual(result['status'], 'cancelled', result)
        self.assertFalse(marker.exists())
        self.assert_clean(result)

    def test_precancelled_and_bad_input_do_not_launch(self):
        event = threading.Event()
        event.set()
        result = self.run_code('raise RuntimeError()', cancelled=event)
        self.assertEqual(result['status'], 'cancelled')
        self.assertIsNone(result['pid'])
        result = run_process('echo shell text', cwd=self.root)
        self.assertEqual(result['status'], 'failed')
        self.assertIsNone(result['pid'])

    def test_cwd_env_and_literal_argv(self):
        code = 'import json,os,sys; print(json.dumps([os.getcwd(),os.getenv("TA_TEST"),sys.argv[1]]))'
        result = run_process([sys.executable, '-I', '-c', code, 'a & echo unsafe'],
                             cwd=self.root, env={**os.environ, 'TA_TEST': 'isolated'})
        self.assertEqual(result['status'], 'succeeded', result)
        values = json.loads(result['stdout'])
        self.assertEqual(Path(values[0]), self.root)
        self.assertEqual(values[1:], ['isolated', 'a & echo unsafe'])
        self.assert_clean(result)

    def test_job_owner_crash_kills_entire_tree(self):
        if os.name != 'nt':
            self.skipTest('Windows Job parent-death guarantee; POSIX has no such guarantee')
        argv = self.tree_argv()
        owner_code = r'''
import json, os, pathlib, sys, threading, time
sys.path.insert(0, sys.argv[1])
from traceanchor.process import run_process
root = pathlib.Path(sys.argv[2])
def on_start(identity):
    (root / 'gate.json').write_text(json.dumps(identity))
def worker():
    result = run_process(json.loads(sys.argv[3]), cwd=root, timeout=15, on_start=on_start)
    (root / 'unexpected-return').write_text(str(result))
threading.Thread(target=worker, daemon=True).start()
deadline = time.monotonic() + 10
while not (root / 'crash-now').exists():
    if time.monotonic() > deadline:
        sys.exit(9)
    time.sleep(.01)
os._exit(71)
'''
        owner = subprocess.Popen([sys.executable, '-I', '-c', owner_code, str(PRODUCT), str(self.root), json.dumps(argv)],
                                 cwd=PRODUCT, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            self.wait_for(lambda: (self.root / 'ready').exists())
            identities = [json.loads((self.root / (role + '.json')).read_text())
                          for role in ('gate', 'parent', 'child', 'grandchild')]
            (self.root / 'crash-now').touch()
            stdout, stderr = owner.communicate(timeout=5)
            self.assertEqual(owner.returncode, 71, (stdout, stderr))
            self.assertFalse((self.root / 'unexpected-return').exists())
            for identity in identities:
                self.assert_windows_stopped(identity)
            self.assert_tree_stopped()
        finally:
            if owner.poll() is None:
                owner.kill()
                owner.wait(timeout=3)
            for stream in (owner.stdout, owner.stderr):
                stream.close()

    def test_windows_structure_sizes(self):
        if os.name == 'nt':
            import ctypes
            from traceanchor.winjob import ACCOUNTING, BASIC_LIMIT, EXTENDED_LIMIT, IO_COUNTERS
            self.assertEqual(ctypes.sizeof(IO_COUNTERS), 48)
            self.assertEqual(ctypes.sizeof(ACCOUNTING), 48)
            self.assertEqual(ctypes.sizeof(BASIC_LIMIT), 64 if ctypes.sizeof(ctypes.c_void_p) == 8 else 48)
            self.assertEqual(ctypes.sizeof(EXTENDED_LIMIT), 144 if ctypes.sizeof(ctypes.c_void_p) == 8 else 112)


if __name__ == '__main__':
    unittest.main()
