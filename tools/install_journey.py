"""Offline same-machine isolated installation and maintenance qualification.
Run only on the reviewed product checkout. No global installation or downloads.
"""
import argparse
import atexit
import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
import subprocess
import sys
import time
import uuid
import venv

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',default='docs/install-qualification.json')
    parser.add_argument('--previous-wheel',help='Explicit reviewed earlier local wheel for upgrade and paired-data rollback')
    parser.add_argument('--tools',help='Optional explicit professional tool map for installed-package checks')
    parser.add_argument('--apk',help='Explicit reviewed self-built APK for installed JADX qualification')
    args=parser.parse_args()
    # pip itself still uses ordinary Windows paths for nested wheel caches.
    # Keep this explicitly owned temp root short; product output IO separately
    # supports long paths and has a real >260-character archive regression.
    work=ROOT/'.validation'/('i-'+uuid.uuid4().hex[:8])
    work.mkdir(parents=True)
    temporary=work/'t';temporary.mkdir()
    for key in ('TEMP','TMP','TMPDIR'):os.environ[key]=str(temporary)
    tempfile.tempdir=str(temporary)
    ownership={'owner':'artifact-install-journey','tier':'L2','status':'active','reason':'Isolated package, tool and maintenance qualification; no global install','recovery_use':True}
    def save_ownership():
        (work/'ownership.json').write_text(json.dumps(ownership,indent=2)+'\n',encoding='utf-8')
    save_ownership()
    def terminal_ownership():
        if ownership['status']=='active':ownership['status']='failed-or-interrupted'
        ownership['retention']='Retain owned venv, raw commands, workspaces and artifacts for diagnosis; no automatic recursive deletion'
        save_ownership()
    atexit.register(terminal_ownership)
    env=work/'environment'
    venv.EnvBuilder(with_pip=True,clear=False).create(env)
    python=env/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    console=env/('Scripts/traceanchor.exe' if os.name=='nt' else 'bin/traceanchor')
    steps=[]
    def run(label,command,input=None,code=0):
        started=time.monotonic();argv=[str(c) for c in command]
        (work/(label+'.command.json')).write_text(json.dumps(argv,indent=2)+'\n',encoding='utf-8')
        if input is not None:(work/(label+'.stdin')).write_bytes(input)
        try:completed=subprocess.run(argv,input=input,capture_output=True,cwd=work,timeout=120)
        except subprocess.TimeoutExpired as exc:
            for name,raw in (('stdout',exc.stdout),('stderr',exc.stderr)):
                (work/(label+'.'+name)).write_bytes(raw or b'')
            ownership['failure']={'step':label,'status':'timed_out'}
            raise
        streams={}
        for name in ('stdout','stderr'):
            raw=getattr(completed,name);(work/(label+'.'+name)).write_bytes(raw)
            streams[name]={'size':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
        receipt={'step':label,'status':'pass' if completed.returncode==code else 'fail','exit_code':completed.returncode,'expected_exit_code':code,'elapsed_seconds':round(time.monotonic()-started,6),'streams':streams}
        (work/(label+'.receipt.json')).write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
        steps.append(receipt)
        if completed.returncode!=code:
            ownership['failure']=receipt
            raise RuntimeError(label+' failed with exit '+str(completed.returncode)+'; inspect local .validation run')
        return completed.stdout
    def call(label,operation,data):
        return json.loads(run(label,[python,'-I','-B','-m','traceanchor','--workspace',workspace,'call',operation],json.dumps(data).encode()))
    wheel=ROOT/'dist/traceanchor-0.2.0-py3-none-any.whl'
    sdist=ROOT/'dist/traceanchor-0.2.0.tar.gz'
    if not wheel.is_file() or not sdist.is_file():raise RuntimeError('Build wheel and sdist first')
    code_manifest={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'traceanchor').rglob('*')) if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc'}
    workspace=work/'workspace'
    previous_case=None;previous_identity=None;rollback_workspace=work/'pre-upgrade-workspace'
    if args.previous_wheel:
        previous=Path(args.previous_wheel).absolute()
        previous_identity={'filename':previous.name,'sha256':hashlib.sha256(previous.read_bytes()).hexdigest()}
        run('install-previous-local-version',[python,'-I','-m','pip','install','--no-index','--no-deps','--no-cache-dir',previous])
        run('previous-version-init',[python,'-I','-B','-m','traceanchor','--workspace',workspace,'init'])
        previous_case=call('previous-version-create-case','case.create',{'objective':'preserve earlier product case through upgrade'})
        shutil.copytree(workspace,rollback_workspace)
        steps.append({'step':'preserve-pre-upgrade-owned-workspace','status':'pass','scope':'Offline local copy after previous CLI exited; paired with previous package for rollback'})
    run('install-wheel',[python,'-I','-m','pip','install','--no-index','--no-deps','--no-cache-dir',wheel])
    if previous_case:
        assert call('cross-version-upgrade-preserves-case','case.get',{'case_id':previous_case['id']})['data']['objective']=='preserve earlier product case through upgrade'
    assert run('module-version',[python,'-I','-B','-m','traceanchor','--version']).strip()==b'0.2.0'
    run('console-entrypoint',[console,'--version'])
    doctor=json.loads(run('doctor',[python,'-I','-B','-m','traceanchor','doctor']))
    assert doctor['runtime_dependencies']==[]
    run('init',[python,'-I','-B','-m','traceanchor','--workspace',workspace,'init'])
    case=call('create-case','case.create',{'objective':'installation survives maintenance'})
    checkpoint=json.loads(run('checkpoint',[python,'-I','-B','-m','traceanchor','--workspace',workspace,'maintenance','snapshot']))
    call('revise-case','case.revise',{'case_id':case['id'],'changes':{'objective':'temporary change'}})
    restored=json.loads(run('restore',[python,'-I','-B','-m','traceanchor','--workspace',workspace,'maintenance','restore','--checkpoint',checkpoint['id']]))
    assert restored['status']=='restored'
    assert call('verify-rollback','case.get',{'case_id':case['id']})['data']['objective']=='installation survives maintenance'
    demo_status='not-run-platform'
    if os.name=='nt':
        demo=json.loads(run('real-installed-demo',[python,'-I','-B','-m','traceanchor','demo','--directory',work/'demo']))
        assert demo['status']=='passed-finite-scope'
        demo_status='passed-finite-scope'
        # Exercise the public advanced manual; this counter is not a P04 score.
        examples=[json.loads(text) for text in re.findall(r'```json\s*\n(.*?)\n```',(ROOT/'docs/manual-json-api.md').read_text(encoding='utf-8'),re.S)]
        manual_case=next(x for x in examples if x.get('mode')=='reconstruct')
        manual_spec=next(x for x in examples if 'fixtures' in x and 'requirements' in x)
        original_workspace=workspace;workspace=work/'readme-workspace'
        run('readme-init',[python,'-I','-B','-m','traceanchor','--workspace',workspace,'init'])
        c=call('readme-case','case.create',manual_case)
        ref=call('readme-reference','source.add',{'case_id':c['id'],'path':str(work/'demo/reference.py'),'role':'reference'})
        obs=call('readme-analyze','analyze',{'case_id':c['id'],'source_id':ref['id']})
        encoded=json.dumps(manual_spec).replace('[CASE_ID]',c['id']).replace('[REFERENCE_ID]',ref['id']).replace('[ANALYSIS_ID]',obs['id'])
        spec=call('readme-freeze','spec.freeze',json.loads(encoded))
        cand=call('readme-candidate','source.add',{'case_id':c['id'],'path':str(work/'demo/candidate.py'),'role':'candidate'})
        verdict=call('readme-verify','verify',{'case_id':c['id'],'spec_id':spec['id'],'candidate_id':cand['id']})
        assert verdict['data']['status']=='pass'
        assert call('readme-close','case.close',{'case_id':c['id']})['data']['disposition']=='accepted'
        workspace=original_workspace
    for host,relative,original in [('claude','.mcp.json',b'{"mcpServers":{},"testOnly":true}\n'),('codex','.codex/config.toml',b'# synthetic existing project setting\n')]:
        project=work/('host-'+host);project.mkdir()
        config=project/relative;config.parent.mkdir(parents=True,exist_ok=True);config.write_bytes(original)
        prefix=[python,'-I','-B','-m','traceanchor','--workspace',workspace,'host']
        preview=json.loads(run(host+'-preview',prefix+['install','--host',host,'--project',project]))
        assert not preview['applied'] and config.read_bytes()==original
        assert not (project/'.traceanchor-hosts').exists()
        applied=json.loads(run(host+'-apply',prefix+['install','--host',host,'--project',project,'--apply']))
        assert applied['applied']
        unchanged=json.loads(run(host+'-reinstall',prefix+['install','--host',host,'--project',project,'--apply']))
        assert unchanged['action']=='unchanged'
        run(host+'-uninstall',prefix+['uninstall','--host',host,'--project',project,'--apply'])
        assert config.read_bytes()==original
    tool_map=json.loads(Path(args.tools).read_text()) if args.tools else {n:shutil.which(n) for n in ('node','objdump','gdb','gcc')}
    professional=[]
    run('installed-domain-knowledge',[python,'-I','-B','-c','from traceanchor.knowledge import guide;assert all(guide(d)["guide"] for d in ("native","apk","web"))'])
    tools_file=work/'professional-tools.json';tools_file.write_text(json.dumps(tool_map),encoding='utf-8')
    if tool_map.get('node') and os.name=='nt':
        scenario=work/'web-options.json';scenario.write_text(json.dumps({'scenario':json.loads((ROOT/'examples/web/scenario.json').read_text())}),encoding='utf-8')
        observed=json.loads(run('installed-node-inspector-chain',[python,'-I','-B','-m','traceanchor','--workspace',work/'web-workspace','inspect',ROOT/'examples/web/reservation.mjs','--method','web.observe','--question','Trace reservation state and HTTP causality','--allow-execute','--allow-network','--tools',tools_file,'--options',scenario]))
        assert observed['observation']['data']['professional']['status']=='succeeded'
        professional.append('Node-inspector-state-network')
    gcc=tool_map.get('gcc') or shutil.which('gcc')
    if tool_map.get('objdump') and gcc and os.name=='nt':
        target=work/'parcel.exe'
        run('installed-native-fixture-build',[gcc,'-g','-O0','-fno-inline','-o',target,ROOT/'examples/native/parcel.c'])
        observed=json.loads(run('installed-native-disassembly',[python,'-I','-B','-m','traceanchor','--workspace',work/'native-workspace','inspect',target,'--method','native.disassemble','--question','Locate shipping pricing calls','--allow-execute','--tools',tools_file]))
        assert any(x['name']=='quote_parcel' for x in observed['observation']['data']['professional']['functions'])
        professional.append('GNU-machine-code-disassembly')
        if tool_map.get('gdb'):
            options=work/'native-options.json'
            options.write_text(json.dumps({'breakpoints':['quote_parcel'],'expressions':['service_zone'],'arguments':['scenario.txt'],'input_files':{'scenario.txt':'quote 501 1\n'},'test_environment':{'TRACEANCHOR_PARCEL_ZONE':'remote'}}),encoding='utf-8')
            dynamic=json.loads(run('installed-native-gdb-trace',[python,'-I','-B','-m','traceanchor','--workspace',work/'native-runtime-workspace','inspect',target,'--method','native.trace','--question','Determine actual remote price branch','--allow-execute','--tools',tools_file,'--options',options]))
            facts=dynamic['observation']['data']['professional']
            assert facts['status']=='complete' and facts['breakpoint_hits'] and '"cents":920' in facts['runtime_trace']
            professional.append('GNU-GDB-callback-runtime')
    if args.apk and tool_map.get('java') and tool_map.get('jadx_jar') and os.name=='nt':
        selected=Path(args.apk).absolute()
        apk=json.loads(run('installed-jadx-static-chain',[python,'-I','-B','-m','traceanchor','--workspace',work/'apk-workspace','inspect',selected,'--method','apk.analyze','--question','Locate stateful quote request and input errors','--allow-execute','--tools',tools_file]))
        facts=apk['observation']['data']['professional']
        assert facts['status']=='complete' and facts['facts']
        professional.append('JADX-DEX-static-semantics')
    run('same-version-reinstall',[python,'-I','-m','pip','install','--no-index','--no-deps','--no-cache-dir','--force-reinstall',wheel])
    call('workspace-survives-reinstall','case.get',{'case_id':case['id']})
    run('uninstall',[python,'-I','-m','pip','uninstall','-y','traceanchor'])
    assert (workspace/'state.sqlite3').is_file()
    run('package-absent-assets-preserved',[python,'-I','-B','-c','import traceanchor'],code=1)
    run('install-sdist',[python,'-I','-m','pip','install','--no-index','--no-deps','--no-cache-dir',sdist])
    call('workspace-survives-sdist-install','case.get',{'case_id':case['id']})
    # Export/import is untrusted evidence migration, not local proof.
    bundle=call('export','export',{'case_id':case['id']})
    destination=work/'migrated'
    run('destination-init',[python,'-I','-B','-m','traceanchor','--workspace',destination,'init'])
    imported=json.loads(run('migration-import',[python,'-I','-B','-m','traceanchor','--workspace',destination,'call','import'],json.dumps(bundle).encode()))
    assert imported['effects_reset']==['read'] and not imported['verdicts_current']
    if previous_case:
        run('rollback-previous-local-package',[python,'-I','-m','pip','install','--no-index','--no-deps','--no-cache-dir','--force-reinstall',previous])
        original_workspace=workspace;workspace=rollback_workspace
        assert call('rollback-paired-old-data','case.get',{'case_id':previous_case['id']})['data']['objective']=='preserve earlier product case through upgrade'
        workspace=original_workspace
        assert (workspace/'state.sqlite3').is_file()
        steps.append({'step':'newer-assets-retained-during-rollback','status':'pass','scope':'Older package opens only pre-upgrade data; R3 workspaces remain on disk and are not interpreted by old version'})
    run('rollback-reinstall-local-wheel',[python,'-I','-m','pip','install','--no-index','--no-deps','--no-cache-dir','--force-reinstall',wheel])
    call('final-data-preserved','case.get',{'case_id':case['id']})
    artifacts={p.name:{'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'size':p.stat().st_size} for p in (wheel,sdist)}
    report={'schema_version':2,'version':'0.2.0','status':'pass','scope':'Same machine, newly created isolated venv; explicitly selected local-version upgrade and paired pre-upgrade-data rollback when previous artifact supplied; not clean-machine qualification','platform':sys.platform,'python':list(sys.version_info[:3]),'network_downloads':False,'global_config_modified':False,'steps':steps,'installed_demo':demo_status,'installed_professional_chains':professional,'implementation_sha256':code_manifest,'artifacts':artifacts,'previous_artifact':previous_identity,'cross_version':'upgrade-and-paired-data-rollback-tested' if previous_case else 'not-run-no-previous-artifact-selected','not_run':['Real named-host launcher/config workflow (this script checks synthetic project configuration)','Other operating systems','Arbitrary old-version use of newer professional/workspace records'],'limitations':['Database restore is offline and does not roll back source files or foreign effects','Rollback uses matching old package and pre-upgrade workspace; newer assets remain preserved, not interpreted by old version','Optional tools qualify only chains actually listed; availability is not execution proof','Raw commands/input/outputs retained locally; public stream hashes identify bytes without publishing private paths']}
    output=Path(args.output)
    if not output.is_absolute():output=ROOT/output
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    (work/'artifact-hashes.json').write_text(json.dumps(artifacts,indent=2)+'\n',encoding='utf-8')
    ownership.update(status='complete',recovery_use=False,steps=len(steps),report_sha256=hashlib.sha256(output.read_bytes()).hexdigest());save_ownership()
    print(json.dumps({'status':'pass','steps':len(steps),'installed_demo':demo_status,'professional_chains':professional,'report':output.relative_to(ROOT).as_posix(),'local_evidence':work.relative_to(ROOT).as_posix()}))
    return 0

if __name__=='__main__':sys.exit(main())
