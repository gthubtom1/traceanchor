"""Optional JADX static adapter. Only the injected executor may start tools.

JADX produces semantic reading material; extracted call hints are navigation,
not a resolved call graph or evidence that Android executed a method.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import stat
import uuid
from .core import io_path

MAX_ARTIFACT_BYTES = 4 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024
MAX_LOG_BYTES = 1024 * 1024


def _regular(path):
    """Reject links/reparse ancestors before consuming caller/tool files."""
    path = Path(os.path.abspath(path))
    for item in reversed((path, *path.parents)):
        info = io_path(item).lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('Link/reparse boundary rejected: ' + str(item))
    return path


def _hash(path, limit=256 * 1024 * 1024):
    path = _regular(path)
    before = io_path(path).stat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
        raise ValueError('Input is not a bounded regular file')
    hasher = hashlib.sha256()
    total = 0
    with io_path(path).open('rb') as stream:
        while True:
            block = stream.read(min(1024 * 1024, limit - total + 1))
            if not block:
                break
            total += len(block)
            if total > limit:
                raise ValueError('Input grew beyond byte budget')
            hasher.update(block)
    after = io_path(path).stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise ValueError('Input changed while hashing')
    return hasher.hexdigest()


def analyze(target: Path, directory: Path, execute, *, java: str,
            jadx_jar: str, max_files=200) -> dict:
    """Run version + bounded decompilation and preserve exact generated sources.

    ``directory`` must already be owned/registered by the caller. Each invocation
    creates an isolated child, so failed reruns never consume an old Java tree.
    ``execute(argv, input_bytes=b'', env=None)`` owns timeout, cancellation,
    containment and growth monitoring. ``env`` is an explicit override map, never
    a persisted copy of the caller's environment. The adapter creates no process,
    Store or model.
    """
    result = {
        'status': 'blocked', 'facts': [], 'artifacts': [], 'unknowns': [],
        'qualification_level': 'static-decompiler-output; runtime-unobserved',
        'limitations': [
            'Static JADX output only; Android runtime, installation and business execution not observed.',
            'Java call hints are syntactic navigation in decompiled output, not resolved dispatch or reachability.',
            'Reflection, dynamic DEX, JNI/native, Kotlin coroutine/lambda reconstruction and decompiler errors may leave gaps.',
            'Artifact budgets are checked after tool return; the executor must enforce timeout and monitor directory growth.',
        ],
        'tool': {'kind': 'jadx', 'version': None}, 'runs': [],
        'coverage': {'files_examined': 0, 'bytes_read': 0, 'truncated': False},
    }
    try:
        if isinstance(max_files, bool) or not isinstance(max_files, int) or not 1 <= max_files <= 1000:
            raise ValueError('max_files must be in 1..1000')
        target, directory = _regular(target), _regular(directory)
        if not directory.is_dir():
            raise ValueError('Managed output directory must exist')
        jar = _regular(Path(jadx_jar))
        target_hash = _hash(target)
        result['target'] = {'sha256': target_hash, 'size': target.stat().st_size,
                            'name': target.name}
        result['tool']['jar_sha256'] = _hash(jar, 512 * 1024 * 1024)
        attempt = directory / ('jadx-' + uuid.uuid4().hex)
        attempt.mkdir()
        output = attempt / 'sources'
        result['attempt'] = attempt.relative_to(directory).as_posix()
        homes = {name: attempt / name for name in ('home', 'config', 'cache', 'tmp')}
        for path in homes.values():
            path.mkdir()
        environment = {'JADX_CONFIG_DIR': str(homes['config']),
                       'JADX_CACHE_DIR': str(homes['cache']),
                       'JADX_TMP_DIR': str(homes['tmp']),
                       'TEMP': str(homes['tmp']), 'TMP': str(homes['tmp'])}
        # Avoid JVM performance-data files held with restrictive Windows sharing;
        # all task evidence remains explicit, without weakening workspace census.
        java_command = [str(java), '-Xmx512m', '-XX:-UsePerfData',
                        '-Duser.home=' + str(homes['home']),
                        '-Djava.io.tmpdir=' + str(homes['tmp']),
                        '-cp', str(jar), 'jadx.cli.JadxCLI', '--config', 'none']

        def add_fact(row):
            if len(result['facts']) < 10000:
                result['facts'].append(row)
            else:
                result['coverage']['truncated'] = True

        def artifact(path, kind):
            data = io_path(path).read_bytes()
            row = {'path': path.relative_to(directory).as_posix(), 'kind': kind,
                   'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
            result['artifacts'].append(row)
            return row

        def run(label, argv):
            raw = execute(argv, input_bytes=b'', env=environment)
            meta = {key: value for key, value in raw.items() if key not in ('stdout', 'stderr')}
            meta['environment_overrides'] = environment
            meta['argv'] = argv
            meta['label'] = label
            for channel in ('stdout', 'stderr'):
                value = raw.get(channel, b'')
                if not isinstance(value, bytes):
                    raise ValueError('Executor must return raw stdout/stderr bytes')
                if len(value) > MAX_LOG_BYTES:
                    value = value[:MAX_LOG_BYTES]
                    result['unknowns'].append(label + ' ' + channel + ' exceeds retained log limit')
                    result['coverage']['truncated'] = True
                path = attempt / (label + '.' + channel)
                with io_path(path).open('xb') as stream:
                    stream.write(value)
                meta[channel + '_artifact'] = artifact(path, 'tool-' + channel)['path']
            result['runs'].append(meta)
            return raw

        def successful(run_result):
            return (run_result.get('status') == 'succeeded'
                    and run_result.get('exit_code') == 0
                    and run_result.get('cleanup', {}).get('state') == 'complete'
                    and not run_result.get('output_truncated'))

        version = run('version', [*java_command, '--version'])

        if not successful(version):
            result['unknowns'].append('JADX version execution or cleanup failed; no decompilation started')
            return result
        version_text = (version['stdout'] + b'\n' + version['stderr']).decode('utf-8', 'replace').strip()
        match = re.search(r'\b\d+\.\d+\.\d+(?:[-+][\w.-]+)?\b', version_text)
        if not match:
            result['unknowns'].append('JADX version output not recognized')
            return result
        result['tool']['version'] = match[0]
        decompile = run('decompile', [*java_command, '--no-res', '--threads-count', '1',
                                    '-d', str(output), str(target)])
        result['status'] = 'complete' if successful(decompile) else 'partial'
        if not successful(decompile):
            result['unknowns'].append('JADX failed/truncated or cleanup incomplete; existing files are partial evidence only')
        if decompile.get('cleanup', {}).get('state') != 'complete':
            result['status'] = 'blocked'
            result['unknowns'].append('Cleanup unconfirmed; output tree is not consumed while a tool may still write')
            return result
        if not output.is_dir():
            result['status'] = 'failed'
            result['unknowns'].append('JADX produced no source directory')
            return result
        method = re.compile(r'^\s*(?:(?:public|protected|private|static|final|synchronized|native|abstract|bridge|synthetic)\s+)+(?:[\w.$<>?\[\],]+\s+)?([\w$<>]+)\s*\([^;]*\)\s*(?:throws\s+[^{}]+)?\s*\{')
        calls = re.compile(r'\b((?:[A-Za-z_$][\w$]*\.)*[A-Za-z_$][\w$]*)\s*\(')
        ignored = {'if', 'while', 'for', 'switch', 'catch', 'synchronized', 'super', 'this'}
        stack = [output]
        entries = 0
        while stack:
            folder = _regular(stack.pop())
            with os.scandir(io_path(folder)) as children:
                for entry in children:
                    entries += 1
                    if entries > max_files * 8 + 100:
                        result['coverage']['truncated'] = True
                        stack.clear()
                        break
                    path = _regular(folder / entry.name)
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(path)
                        continue
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    size = io_path(path).stat().st_size
                    if (result['coverage']['files_examined'] >= max_files
                            or size > MAX_ARTIFACT_BYTES
                            or result['coverage']['bytes_read'] + size > MAX_TOTAL_BYTES):
                        result['coverage']['truncated'] = True
                        continue
                    result['coverage']['files_examined'] += 1
                    result['coverage']['bytes_read'] += size
                    row = artifact(path, 'decompiled-java' if path.suffix == '.java' else 'tool-output')
                    if path.suffix != '.java':
                        continue
                    text = io_path(path).read_text(encoding='utf-8', errors='strict')
                    add_fact({'kind': 'decompiled-source', 'path': row['path'], 'sha256': row['sha256'],
                                            'producer': 'jadx', 'evidence': 'static-decompiler-output'})
                    current_method = None
                    for number, line in enumerate(text.splitlines(), 1):
                        declaration = method.match(line)
                        if declaration:
                            current_method = declaration[1]
                            add_fact({'kind': 'java-method', 'path': row['path'], 'line': number,
                                                    'name': current_method, 'signature': line.strip()[:1000],
                                                    'evidence': 'decompiled-declaration'})
                        elif not line.lstrip().startswith(('*', '//', '/*')):
                            for call in calls.finditer(line):
                                if call[1] not in ignored:
                                    add_fact({'kind': 'java-call-hint', 'path': row['path'],
                                                            'line': number, 'callee': call[1],
                                                            'method_context': current_method,
                                                            'evidence': 'syntactic/inferred; dispatch unresolved'})
                                    if len(result['facts']) >= 10000:
                                        result['coverage']['truncated'] = True
                                        break
                        if len(result['facts']) >= 10000:
                            result['coverage']['truncated'] = True
                            break
        if result['coverage']['truncated']:
            result['status'] = 'partial'
            result['unknowns'].append('Output file/entry/byte/fact budget exhausted; coverage is incomplete')
        if not any(f['kind'] == 'decompiled-source' for f in result['facts']):
            result['status'] = 'failed'
            result['unknowns'].append('No fresh readable Java source collected')
        for row in result['artifacts']:
            if row['kind'] == 'decompiled-java':
                text = io_path(directory / row['path']).read_text(encoding='utf-8')
                if re.search(r'(?i)method not decompiled|JADX (?:WARN|ERROR)', text):
                    result['status'] = 'partial'
                    result['unknowns'].append('Decompiler diagnostic in ' + row['path'])
        if _hash(target) != target_hash:
            result['status'] = 'invalid'
            result['unknowns'].append('Target changed during analysis; evidence identity invalid')
        return result
    except (OSError, ValueError, TypeError, UnicodeError) as exc:
        result['status'] = 'failed'
        result['unknowns'].append(type(exc).__name__ + ': ' + str(exc))
        return result
