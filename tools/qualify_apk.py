"""Build a self-authored APK and retain real JADX/DEX evidence; never run the APK."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from traceanchor.apk_adapter import analyze
from traceanchor.process import run_process


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('java', 'javac', 'jadx-jar', 'd8-jar', 'aapt2', 'android-jar', 'dexdump'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    tools = {key: Path(value).resolve(strict=True) for key, value in vars(args).items()}
    work = ROOT / '.validation' / ('apk-' + uuid.uuid4().hex)
    work.mkdir(parents=True)
    commands = []
    report = {'schema': 1, 'status': 'failed', 'scope': 'P02 self-authored APK static analysis only',
              'started_at': time.time(), 'commands': commands,
              'tools': {key: {'path': str(value), 'sha256': sha(value)} for key, value in tools.items()},
              'limitations': ['APK is unsigned and was not installed or run.',
                              'Reference Java builds this disclosed fixture; this is not P04 blind reconstruction.',
                              'No qualification of arbitrary APKs, native boundaries or device behavior.']}

    report['implementation_inputs'] = [
        {'path': p.relative_to(ROOT).as_posix(), 'sha256': sha(p)}
        for p in [ROOT / 'traceanchor' / 'apk_adapter.py', Path(__file__).resolve()]]
    local_environment = work / 'environment'
    local_environment.mkdir()
    for name in ('home', 'tmp', 'config', 'cache', 'appdata', 'localappdata'):
        (local_environment / name).mkdir()
    overrides = {key: str(local_environment / name) for key, name in
                 [('TEMP', 'tmp'), ('TMP', 'tmp'), ('USERPROFILE', 'home'),
                  ('APPDATA', 'appdata'), ('LOCALAPPDATA', 'localappdata'),
                  ('JADX_CONFIG_DIR', 'config'), ('JADX_CACHE_DIR', 'cache'), ('JADX_TMP_DIR', 'tmp')]}

    def execute(argv, input_bytes=b'', env=None):
        selected = {**overrides, **(env or {})}
        run = run_process(argv, cwd=work, input_bytes=input_bytes, timeout=60,
                          idle_timeout=45, output_limit=1024 * 1024,
                          env={**os.environ, **selected})
        index = len(commands)
        meta = {k: v for k, v in run.items() if k not in ('stdout', 'stderr')}
        meta['argv'] = argv
        meta['environment_overrides'] = selected
        for channel in ('stdout', 'stderr'):
            path = work / ('command-%02d.%s' % (index, channel))
            path.write_bytes(run[channel])
            meta[channel] = {'path': path.name, 'sha256': sha(path), 'size': path.stat().st_size}
        commands.append(meta)
        return run

    def required(argv):
        argv = [str(x) for x in argv]
        if Path(argv[0]) == tools['java']:
            argv[1:1] = ['-Duser.home=' + str(local_environment / 'home'),
                         '-Djava.io.tmpdir=' + str(local_environment / 'tmp')]
        elif Path(argv[0]) == tools['javac']:
            argv[1:1] = ['-J-Duser.home=' + str(local_environment / 'home'),
                         '-J-Djava.io.tmpdir=' + str(local_environment / 'tmp')]
        run = execute(argv)
        if (run['status'] != 'succeeded' or run['exit_code'] != 0
                or run['cleanup']['state'] != 'complete' or run['output_truncated']):
            raise RuntimeError('Tool failed, capture truncated or cleanup incomplete: command %d' % (len(commands) - 1))
        return run

    try:
        required([tools['java'], '-version'])
        required([tools['javac'], '-version'])
        required([tools['java'], '-cp', tools['d8_jar'], 'com.android.tools.r8.D8', '--version'])
        required([tools['aapt2'], 'version'])
        fixture = ROOT / 'examples' / 'apk'
        sources = sorted((fixture / 'src').rglob('*.java'))
        report['fixture_inputs'] = [{'path': p.relative_to(ROOT).as_posix(), 'sha256': sha(p)}
                                    for p in [*sources, fixture / 'AndroidManifest.xml']]
        classes, dex = work / 'classes', work / 'dex'
        classes.mkdir()
        dex.mkdir()
        required([tools['javac'], '--release', '8', '-g', '-classpath', tools['android_jar'],
                  '-d', classes, *sources])
        required([tools['java'], '-Xmx512m', '-cp', tools['d8_jar'], 'com.android.tools.r8.D8',
                  '--release', '--min-api', '21', '--lib', tools['android_jar'],
                  '--output', dex, *sorted(classes.rglob('*.class'))])
        resources = work / 'resources.ap_'
        required([tools['aapt2'], 'link', '--manifest', fixture / 'AndroidManifest.xml',
                  '-I', tools['android_jar'], '-o', resources])
        apk = work / 'shipping.apk'
        with zipfile.ZipFile(resources) as base, zipfile.ZipFile(apk, 'x', zipfile.ZIP_DEFLATED) as out:
            for entry in base.infolist():
                out.writestr(entry.filename, base.read(entry))
            out.write(dex / 'classes.dex', 'classes.dex')
        report['target'] = {'path': apk.name, 'sha256': sha(apk), 'size': apk.stat().st_size}
        disassembly = required([tools['dexdump'], '-d', dex / 'classes.dex'])
        dex_command_index = len(commands) - 1
        result = analyze(apk, work, execute, java=str(tools['java']), jadx_jar=str(tools['jadx_jar']))
        report['analysis'] = result
        if result['status'] != 'complete':
            raise RuntimeError('JADX analysis incomplete: ' + repr(result['unknowns']))
        chain = []
        for owner, callee in [('ShippingActivity.java', 'session.requestQuote'),
                              ('ShippingActivity.java', 'session.confirm'),
                              ('ShipmentSession.java', 'requireState'),
                              ('ShipmentSession.java', 'ShippingRules.quote')]:
            found = [f for f in result['facts'] if f['kind'] == 'java-call-hint'
                     and f['path'].endswith('/' + owner) and f['callee'].removeprefix('this.') == callee]
            if not found:
                raise RuntimeError('Expected disclosed fixture edge absent: ' + callee)
            chain.append(found[0])
        report['critical_chain'] = chain
        dex_edges = []
        caller = None
        for number, line in enumerate(disassembly['stdout'].decode('utf-8').splitlines(), 1):
            if '|[' in line and 'study.shipping.' in line:
                caller = line.split('] ', 1)[1]
            if 'invoke-' in line and 'Lstudy/shipping/' in line:
                dex_edges.append({'caller': caller, 'line': number,
                                  'path': commands[dex_command_index]['stdout']['path'],
                                  'instruction': line.strip()})
        for caller_part, callee_part in [('ShippingActivity.onCreate', 'ShipmentSession;.requestQuote:'),
                                         ('ShippingActivity.onCreate', 'ShipmentSession;.confirm:'),
                                         ('ShipmentSession.requestQuote', 'ShipmentSession;.requireState:'),
                                         ('ShipmentSession.requestQuote', 'ShippingRules;.quote:')]:
            if not any(caller_part in (edge['caller'] or '') and callee_part in edge['instruction']
                       for edge in dex_edges):
                raise RuntimeError('Independent DEX edge absent: ' + caller_part + ' -> ' + callee_part)
        report['independent_dex_edges'] = dex_edges
        conditions = []
        for filename, markers in [('ShippingRules.java', ['weight-out-of-range', 'unknown-zone', 'express-unavailable']),
                                  ('ShipmentSession.java', ['DRAFT', 'QUOTED', 'CONFIRMED', 'price-mismatch', 'invalid-order-id'])]:
            artifact = next(a for a in result['artifacts'] if a['path'].endswith('/' + filename))
            lines = (work / artifact['path']).read_text(encoding='utf-8').splitlines()
            for marker in markers:
                hits = [{'path': artifact['path'], 'line': n, 'text': text.strip()}
                        for n, text in enumerate(lines, 1) if marker in text]
                if not hits:
                    raise RuntimeError('Input/state condition absent: ' + marker)
                conditions.append({'marker': marker, 'locations': hits})
        report['input_and_state_conditions'] = conditions
        report['status'] = 'observed-finite-static-chain'
    except Exception as exc:
        report['error'] = {'type': type(exc).__name__, 'message': str(exc)}
    report['finished_at'] = time.time()
    output = work / 'qualification.json'
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': report['status'], 'report': str(output), 'error': report.get('error')}))
    return 0 if report['status'] == 'observed-finite-static-chain' else 1


if __name__ == '__main__':
    sys.exit(main())
