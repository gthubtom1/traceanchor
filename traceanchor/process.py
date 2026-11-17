"""Bounded process owner, independent of the durable store.

Windows: a trusted Python gate waits for a private stdin handshake. The owner
assigns the gate to a non-inheritable KILL_ON_JOB_CLOSE job and calls on_start
before releasing it. Target and descendants inherit job membership. Assignment
failure (including incompatible enclosing jobs) is a failure, never a fallback.
POSIX: the gate owns a new session/process group. Descendants that deliberately
setsid/setpgid escape that boundary; cleanup is therefore reported unknown.
This is resource ownership, not an execution sandbox. on_start must return
promptly; arbitrary caller callback code cannot be preempted safely.
"""
from __future__ import annotations

import json
import math
import os
import signal
import struct
import subprocess
import sys
import threading
import time

from .winjob import Job, cancel_thread_io, process_creation_time

# This code is our own gate, not target code. -I prevents cwd/PYTHONPATH imports.
# os.read consumes exactly the handshake, never buffering target stdin bytes.
_GATE = r'''
import json, os, struct, subprocess, sys
if os.name == 'nt':
    import msvcrt
    control = msvcrt.open_osfhandle(int(sys.argv[1]), os.O_WRONLY)
else:
    control = int(sys.argv[1])
os.set_inheritable(control, False)
def report(data):
    os.write(control, (json.dumps(data, ensure_ascii=True) + '\n').encode('ascii'))
def exact(n):
    data = bytearray()
    while len(data) < n:
        part = os.read(0, n - len(data))
        if not part:
            raise EOFError('gate closed before release')
        data.extend(part)
    return bytes(data)
try:
    size = struct.unpack('!I', exact(4))[0]
    if size > 1048576:
        raise ValueError('gate request too large')
    config = json.loads(exact(size))
    child = subprocess.Popen(config['argv'], stdin=0, stdout=1, stderr=2,
                             shell=False, close_fds=True)
    report({'target_pid': child.pid})
    code = child.wait()
    report({'exit_code': code})
except BaseException as exc:
    report({'error': {'code': 'spawn_error', 'message': str(exc)[:2000],
                      'type': type(exc).__name__}})
finally:
    os.close(control)
'''


def _cancelled(token):
    if token is None:
        return False
    if callable(token):
        return bool(token())
    return bool(token.is_set())


def run_process(argv, *, cwd, input_bytes=b'', timeout=30.0, idle_timeout=10.0,
                output_limit=1048576, cancelled=None, env=None, on_start=None):
    """Run argv without a shell, returning bytes and JSON-compatible metadata.

    Each output stream has its own hard retained-byte limit. Idle time measures
    lack of stdout/stderr bytes, not CPU utilization. Time includes preparation;
    cleanup/drain add at most a fixed ~2 seconds (OS calls excluded). stdin is a
    dedicated pipe and always closed after input. The returned pid identifies
    the owned gate; target_pid identifies the target if it started. A pre-release
    cancellation or failed callback never executes the target.
    """
    started = time.monotonic()
    result = dict(status='failed', exit_code=None, elapsed_seconds=0.0, pid=None,
                  target_pid=None, containment='none',
                  cleanup={'state': 'complete', 'details': ['no process started']},
                  output_truncated=False, error=None, stdout=b'', stderr=b'')
    proc = job = None
    assigned = released = False
    control_r = control_w = None
    threads = []
    streams = []
    buffers = {'stdout': bytearray(), 'stderr': bytearray()}
    protocol = bytearray()
    overflow = threading.Event()
    stop_io = threading.Event()
    io_errors = []
    last_output = [started]
    lock = threading.Lock()

    def error(code, exc):
        result['error'] = {'code': code, 'type': type(exc).__name__, 'message': str(exc)[:2000]}

    def reader(stream, name):
        try:
            if os.name != 'nt':
                os.set_blocking(stream.fileno(), False)
            while not stop_io.is_set():
                try:
                    chunk = os.read(stream.fileno(), 65536)
                except BlockingIOError:
                    stop_io.wait(0.01)
                    continue
                if not chunk:
                    return
                with lock:
                    if name == 'control':
                        if len(protocol) + len(chunk) > 16384:
                            io_errors.append('gate protocol exceeded limit')
                            return
                        protocol.extend(chunk)
                    else:
                        last_output[0] = time.monotonic()
                        available = output_limit - len(buffers[name])
                        buffers[name].extend(chunk[:available])
                        if len(chunk) > available:
                            overflow.set()
        except (OSError, ValueError) as exc:
            with lock:
                io_errors.append(f'{name}: {type(exc).__name__}: {exc}')

    def writer(payload):
        try:
            if os.name != 'nt':
                os.set_blocking(proc.stdin.fileno(), False)
            view = memoryview(payload)
            while view and not stop_io.is_set():
                try:
                    count = os.write(proc.stdin.fileno(), view[:65536])
                except BlockingIOError:
                    stop_io.wait(0.01)
                    continue
                if not count:
                    break
                view = view[count:]
        except (BrokenPipeError, OSError, ValueError):
            pass  # A target may legitimately not consume all supplied stdin.
        finally:
            try:
                proc.stdin.close()
            except (OSError, ValueError):
                pass

    def launch_thread(target, *args):
        thread = threading.Thread(target=target, args=args, daemon=True)
        threads.append(thread)
        thread.start()
        return thread

    try:
        if isinstance(argv, (str, bytes)) or not argv:
            raise ValueError('argv must be a nonempty sequence, not shell text')
        argv = [os.fsdecode(os.fspath(item)) for item in argv]
        if any('\x00' in item for item in argv):
            raise ValueError('argv contains a NUL')
        if not isinstance(input_bytes, bytes):
            raise TypeError('input_bytes must be bytes')
        if isinstance(output_limit, bool) or not isinstance(output_limit, int) or output_limit < 0:
            raise ValueError('output_limit must be a nonnegative integer')
        for name, value in (('timeout', timeout), ('idle_timeout', idle_timeout)):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f'{name} must be finite and positive')
        cwd = os.fspath(cwd)
        config = json.dumps({'argv': argv}, ensure_ascii=True).encode('ascii')
        if len(config) > 1048576:
            raise ValueError('argv exceeds gate request limit')
        if _cancelled(cancelled):
            result['status'] = 'cancelled'
            return result
        control_r, control_w = os.pipe()
        os.set_inheritable(control_w, True)
        options = dict(cwd=cwd, env=env, stdin=subprocess.PIPE,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       shell=False, close_fds=True, bufsize=0)
        if os.name == 'nt':
            import msvcrt
            job = Job()
            handle = msvcrt.get_osfhandle(control_w)
            startup = subprocess.STARTUPINFO()
            startup.lpAttributeList = {'handle_list': [handle]}
            options['startupinfo'] = startup
            options['creationflags'] = subprocess.CREATE_NO_WINDOW
            control_arg = str(handle)
        else:
            options['start_new_session'] = True
            options['pass_fds'] = (control_w,)
            control_arg = str(control_w)
        proc = subprocess.Popen([sys.executable, '-I', '-u', '-c', _GATE, control_arg], **options)
        result['pid'] = proc.pid
        streams = [proc.stdout, proc.stderr]
        os.close(control_w)
        control_w = None
        if os.name == 'nt':
            job.assign(proc._handle)
            assigned = True
            result['containment'] = 'windows-job'
            identity = {'pid': proc.pid, 'creation_time': process_creation_time(proc._handle),
                        'containment': result['containment']}
        else:
            assigned = True  # Popen performed setsid before exec of our gate.
            result['containment'] = 'posix-session'
            identity = {'pid': proc.pid, 'pgid': proc.pid, 'containment': result['containment']}
        control_stream = os.fdopen(control_r, 'rb', buffering=0)
        control_r = None
        streams = [proc.stdout, proc.stderr, control_stream]
        launch_thread(reader, proc.stdout, 'stdout')
        launch_thread(reader, proc.stderr, 'stderr')
        launch_thread(reader, control_stream, 'control')
        if on_start is not None:
            try:
                on_start(identity)
            except BaseException as exc:
                error('on_start_failed', exc)
                raise _Stop()
        if _cancelled(cancelled):
            result['status'] = 'cancelled'
            raise _Stop()
        if time.monotonic() - started >= timeout:
            result['status'] = 'timed_out'
            raise _Stop()
        last_output[0] = time.monotonic()
        launch_thread(writer, struct.pack('!I', len(config)) + config + input_bytes)
        released = True
        while True:
            now = time.monotonic()
            if overflow.is_set():
                result['status'] = 'output_limit'
                break
            if _cancelled(cancelled):
                result['status'] = 'cancelled'
                break
            if now - started >= timeout:
                result['status'] = 'timed_out'
                break
            if now - last_output[0] >= idle_timeout:
                result['status'] = 'timed_out'
                result['error'] = {'code': 'idle_timeout', 'message': 'no stdout/stderr progress within idle_timeout'}
                break
            if io_errors:
                result['error'] = {'code': 'io_error', 'message': io_errors[0]}
                break
            if proc.poll() is not None:
                break
            time.sleep(0.01)
    except _Stop:
        pass
    except Exception as exc:
        error('containment_error' if proc is not None and not assigned else 'process_error', exc)
    finally:
        cleanup_details = []
        cleanup_complete = proc is None
        if proc is not None:
            try:
                if os.name == 'nt' and assigned:
                    cleanup_complete = job.terminate_and_wait(timeout=1.0)
                    cleanup_details.append('job active process count confirmed zero' if cleanup_complete else 'job members not confirmed stopped before deadline')
                elif os.name != 'nt' and assigned:
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    cleanup_complete = False
                    cleanup_details.append('owned process group killed; detached descendants outside group are not observable')
                else:
                    proc.kill()  # Gate has not received a handshake: no target ran.
                    cleanup_details.append('unreleased gate terminated; target never started')
                    cleanup_complete = True
                try:
                    proc.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    cleanup_complete = False
                    cleanup_details.append('gate exit not confirmed')
            except Exception as exc:
                cleanup_complete = False
                cleanup_details.append(f'cleanup error: {type(exc).__name__}: {exc}')
        if job is not None:
            try:
                job.close()
            except Exception as exc:
                cleanup_complete = False
                cleanup_details.append(f'job close: {exc}')
        # One shared drain deadline, not one deadline per descendant or stream.
        drain_deadline = time.monotonic() + 0.5
        for thread in threads:
            thread.join(max(0.0, drain_deadline - time.monotonic()))
        alive = [thread for thread in threads if thread.is_alive()]
        if alive:
            cleanup_complete = False
            cleanup_details.append('pipe drain exceeded deadline; capture may be incomplete')
            stop_io.set()
            for thread in alive:
                cancel_thread_io(thread)
            for thread in alive:
                thread.join(0.05)
        # Do not close a stream still in use by a detached POSIX reader: a
        # concurrent close is not portable and could itself wait indefinitely.
        if not any(thread.is_alive() for thread in threads):
            for stream in streams + ([proc.stdin] if proc is not None else []):
                try:
                    stream.close()
                except (OSError, ValueError):
                    pass
        for fd in (control_r, control_w):
            if fd is not None:
                os.close(fd)
        if proc is not None and os.name == 'nt' and proc.poll() is not None:
            proc._handle.Close()
        with lock:
            result['stdout'], result['stderr'] = bytes(buffers['stdout']), bytes(buffers['stderr'])
            control_bytes = bytes(protocol)
        messages = []
        try:
            messages = [json.loads(line) for line in control_bytes.splitlines()]
        except (ValueError, UnicodeError):
            result['error'] = {'code': 'gate_protocol_error', 'message': 'incomplete or malformed gate result'}
        for message in messages:
            if 'target_pid' in message:
                result['target_pid'] = message['target_pid']
            if 'exit_code' in message:
                result['exit_code'] = message['exit_code']
            if 'error' in message and result['error'] is None:
                result['error'] = message['error']
        result['output_truncated'] = overflow.is_set()
        if overflow.is_set():
            result['status'] = 'output_limit'
        elif released and result['status'] == 'failed' and result['error'] is None:
            if result['exit_code'] is None:
                result['error'] = {'code': 'gate_exit', 'message': 'gate exited without target exit status'}
            elif result['exit_code'] == 0:
                result['status'] = 'succeeded'
        if released and io_errors and result['error'] is None:
            result['error'] = {'code': 'io_error', 'message': io_errors[0]}
            if result['status'] == 'succeeded':
                result['status'] = 'failed'
        result['cleanup'] = {'state': 'complete' if cleanup_complete else 'unknown',
                             'details': cleanup_details or ['no process started']}
        result['elapsed_seconds'] = round(time.monotonic() - started, 6)
    return result


class _Stop(Exception):
    """Local control-flow only; never exposed as an execution error."""
