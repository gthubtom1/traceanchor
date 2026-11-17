"""Offline same-machine isolated installation and maintenance qualification.
Run only on the reviewed product checkout. No global installation or downloads.
"""
import argparse
import hashlib
import json
import os
import re
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
    args=parser.parse_args()
    work=ROOT/'.validation'/('install-'+uuid.uuid4().hex)
    work.mkdir(parents=True)
    env=work/'environment'
    venv.EnvBuilder(with_pip=True,clear=False).create(env)
    python=env/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    console=env/('Scripts/traceanchor.exe' if os.name=='nt' else 'bin/traceanchor')
    steps=[]
    def run(label,command,input=None,code=0):
        started=time.monotonic()
        completed=subprocess.run([str(c) for c in command],input=input,capture_output=True,cwd=work,timeout=120)
        if completed.returncode!=code:
            # Full diagnostics stay local; the public report contains no private path.
            (work/(label+'.stderr')).write_bytes(completed.stderr)
            (work/(label+'.stdout')).write_bytes(completed.stdout)
            raise RuntimeError(label+' failed with exit '+str(completed.returncode)+'; inspect local .validation run')
        steps.append({'step':label,'status':'pass','elapsed_seconds':round(time.monotonic()-started,6)})
        return completed.stdout
    def call(label,operation,data):
        return json.loads(run(label,[python,'-I','-B','-m','traceanchor','--workspace',workspace,'call',operation],json.dumps(data).encode()))
    wheel=ROOT/'dist/traceanchor-0.1.1-py3-none-any.whl'
    sdist=ROOT/'dist/traceanchor-0.1.1.tar.gz'
    if not wheel.is_file() or not sdist.is_file():raise RuntimeError('Build wheel and sdist first')
    code_manifest={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'traceanchor').glob('*.py'))}
    workspace=work/'workspace'
    run('install-wheel',[python,'-I','-m','pip','install','--no-index','--no-deps','--no-cache-dir',wheel])
    run('module-version',[python,'-I','-B','-m','traceanchor','--version'])
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
        # Use the JSON actually printed in README rather than a parallel example.
        examples=[json.loads(text) for text in re.findall(r'```json\s*\n(.*?)\n```',(ROOT/'README.md').read_text(encoding='utf-8'),re.S)]
        manual_case=next(x for x in examples if x.get('mode')=='reconstruct')
        manual_spec=next(x for x in examples if 'fixtures' in x and 'requirements' in x)
        original_workspace=workspace
        workspace=work/'readme-workspace'
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
    run('same-version-reinstall',[python,'-I','-m','pip','install','--no-index','--no-deps','--no-cache-dir','--force-reinstall',wheel])
    call('workspace-survives-reinstall','case.get',{'case_id':case['id']})
    run('uninstall',[python,'-I','-m','pip','uninstall','-y','traceanchor'])
    assert (workspace/'state.sqlite3').is_file()
    absent=subprocess.run([str(python),'-I','-B','-c','import traceanchor'],capture_output=True,cwd=work,timeout=30)
    assert absent.returncode!=0
    steps.append({'step':'package-absent-assets-preserved','status':'pass'})
    run('install-sdist',[python,'-I','-m','pip','install','--no-index','--no-deps','--no-cache-dir',sdist])
    call('workspace-survives-sdist-install','case.get',{'case_id':case['id']})
    # Export/import is explicit untrusted evidence migration, not local proof.
    bundle=call('export','export',{'case_id':case['id']})
    destination=work/'migrated'
    run('destination-init',[python,'-I','-B','-m','traceanchor','--workspace',destination,'init'])
    imported=json.loads(run('migration-import',[python,'-I','-B','-m','traceanchor','--workspace',destination,'call','import'],json.dumps(bundle).encode()))
    assert imported['effects_reset']==['read'] and not imported['verdicts_current']
    run('rollback-reinstall-local-wheel',[python,'-I','-m','pip','install','--no-index','--no-deps','--no-cache-dir','--force-reinstall',wheel])
    call('final-data-preserved','case.get',{'case_id':case['id']})
    report={'schema_version':1,'version':'0.1.1','status':'pass','scope':'Same machine, newly created isolated venv; not a clean-machine or cross-version upgrade qualification','platform':sys.platform,'python':list(sys.version_info[:3]),'network_downloads':False,'global_config_modified':False,'steps':steps,'installed_demo':demo_status,'implementation_sha256':code_manifest,'not_run':['Different-version package/schema upgrade (no earlier release exists)','Real Claude/Codex host workflows','Other operating systems'],'limitations':['Database restore is offline and does not roll back source files or foreign effects','Same-version reinstall and local artifact recovery are not proof of arbitrary future upgrades']}
    output=Path(args.output)
    if not output.is_absolute():output=ROOT/output
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    (work/'artifact-hashes.json').write_text(json.dumps({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (wheel,sdist)},indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':'pass','steps':len(steps),'installed_demo':demo_status,'report':output.relative_to(ROOT).as_posix()}))
    return 0

if __name__=='__main__':sys.exit(main())
