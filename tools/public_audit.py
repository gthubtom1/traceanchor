"""Inspect the explicit public inventory, optional Git history and build archives.
This is a conservative pattern/content audit, not proof no secret can exist.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import zipfile

ROOT=Path(__file__).resolve().parents[1]
EXCLUDE={'.git','.validation','dist','.venv','__pycache__'}
BAD_PARTS={'.traceanchor-hosts','.mcp.json','.codex','.env','state.sqlite3','sources'}
PATTERNS={
 'private-path':re.compile(r'[A-Za-z]:[\\/](?:Users|Project)[\\/]|/(?:Users|home)/[A-Za-z0-9_.-]+/',re.I),
 'private-key':re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
 'github-secret':re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b'),
 'provider-secret':re.compile(r'\bsk-(?:ant-)?[A-Za-z0-9_-]{30,}\b'),
}

def check(name,raw,issues):
    parts=Path(name).parts
    if set(parts)&BAD_PARTS or name.endswith(('.sqlite3','.pyc','.exe','.dll','.pdb')):
        issues.append({'file':name,'kind':'excluded-material'})
    try:text=raw.decode('utf-8')
    except UnicodeError:
        issues.append({'file':name,'kind':'unexpected-binary'});return
    for key,pattern in PATTERNS.items():
        if pattern.search(text):issues.append({'file':name,'kind':key})

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',default='docs/public-audit.json')
    parser.add_argument('--artifacts',action='store_true')
    parser.add_argument('--history',action='store_true')
    args=parser.parse_args()
    issues=[];inventory={};archives={}
    destination=ROOT/args.output
    for path in sorted(ROOT.rglob('*')):
        relative=path.relative_to(ROOT)
        if set(relative.parts)&EXCLUDE or any(p.endswith('.egg-info') for p in relative.parts) or path==destination:continue
        if path.is_symlink():issues.append({'file':relative.as_posix(),'kind':'link'});continue
        if not path.is_file():continue
        raw=path.read_bytes();name=relative.as_posix()
        inventory[name]=hashlib.sha256(raw).hexdigest();check(name,raw,issues)
    history={'status':'not-run'}
    if args.history:
        if not (ROOT/'.git').is_dir():raise RuntimeError('Initialize product-only Git before history audit')
        commits=subprocess.check_output(['git','-C',str(ROOT),'rev-list','--all'],text=True).splitlines()
        checked=set()
        for commit in commits:
            listing=subprocess.check_output(['git','-C',str(ROOT),'ls-tree','-r',commit],text=True)
            for line in listing.splitlines():
                metadata,name=line.split('\t',1);sha=metadata.split()[2]
                if sha in checked:continue
                checked.add(sha)
                raw=subprocess.check_output(['git','-C',str(ROOT),'cat-file','blob',sha])
                check(name,raw,issues)
        history={'status':'checked','commits':len(commits),'distinct_blobs':len(checked)}
    if args.artifacts:
        for path in sorted((ROOT/'dist').glob('*')):
            if path.suffix=='.whl':
                with zipfile.ZipFile(path) as archive:
                    names=archive.namelist()
                    for name in names:check(name,archive.read(name),issues)
            elif path.name.endswith('.tar.gz'):
                with tarfile.open(path,'r:gz') as archive:
                    members=[m for m in archive.getmembers() if m.isfile()];names=[m.name for m in members]
                    for member in members:check(member.name,archive.extractfile(member).read(),issues)
            else:continue
            if any(set(Path(n).parts)&EXCLUDE for n in names):issues.append({'file':path.name,'kind':'archive-private-directory'})
            archives[path.name]={'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'size':path.stat().st_size,'files':len(names)}
    report={'schema_version':1,'status':'pass' if not issues else 'fail','inventory':inventory,'artifacts':archives,'git_history':history,'issues':issues,'scope':'Explicit product tree excluding .git/.validation/dist/env/cache; common private path/key/token patterns and artifact inventory. Human review of origin, data and license is still required.','license_review':'Original MIT implementation; upstream mechanism-only study with no copied upstream code/assets/runtime, see docs/provenance/notices.md'}
    destination.parent.mkdir(parents=True,exist_ok=True);destination.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':report['status'],'files':len(inventory),'artifacts':len(archives),'issues':issues}))
    return bool(issues)

if __name__=='__main__':sys.exit(main())
