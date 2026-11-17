"""Small auditable PEP517 backend, no network/build dependencies or target execution."""
import base64
import csv
import gzip
import hashlib
import io
import os
from pathlib import Path
import tarfile
import zipfile

NAME = 'traceanchor'
VERSION = '0.1.1'
ROOT = Path(__file__).resolve().parent
INFO = f'{NAME}-{VERSION}.dist-info'


def _metadata():
    return f'Metadata-Version: 2.3\nName: {NAME}\nVersion: {VERSION}\nSummary: Host-driven evidence and independent reconstruction\nRequires-Python: >=3.11\nLicense: MIT\nDescription-Content-Type: text/markdown\n\n' + (ROOT/'README.md').read_text(encoding='utf-8')


def _files():
    roots = ['traceanchor', 'tests', 'docs', 'skills', 'examples', 'tools', '.github']
    files = [ROOT/n for n in ['pyproject.toml','_build.py','README.md','LICENSE','CHANGELOG.md','UPSTREAM-REVIEW-PROMPT.md']]
    for name in roots:
        if (ROOT/name).exists():
            files.extend(p for p in (ROOT/name).rglob('*') if p.is_file() and not p.is_symlink() and '__pycache__' not in p.parts and p.suffix != '.pyc')
    # Post-build verification describes artifacts from outside them, avoiding
    # self-referential artifact hash recursion.
    external = {'docs/public-audit.json', 'docs/release-verification.json', 'docs/completion-gates.json'}
    return sorted(p for p in set(files) if p.relative_to(ROOT).as_posix() not in external)


def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    out = Path(wheel_directory); out.mkdir(parents=True,exist_ok=True)
    name = f'{NAME}-{VERSION}-py3-none-any.whl'
    entries = {p.relative_to(ROOT).as_posix():p.read_bytes() for p in (ROOT/'traceanchor').glob('*.py')}
    entries.update({f'{INFO}/METADATA':_metadata().encode(),f'{INFO}/WHEEL':b'Wheel-Version: 1.0\nGenerator: traceanchor-stdlib\nRoot-Is-Purelib: true\nTag: py3-none-any\n',f'{INFO}/entry_points.txt':b'[console_scripts]\ntraceanchor = traceanchor.cli:main\n',f'{INFO}/licenses/LICENSE':(ROOT/'LICENSE').read_bytes()})
    # Package installation carries the host skill and provenance, not research snapshots.
    for p in _files():
        rel=p.relative_to(ROOT).as_posix()
        if rel.startswith(('docs/','skills/')) or rel=='UPSTREAM-REVIEW-PROMPT.md':
            entries['traceanchor/resources/'+rel]=p.read_bytes()
    record=io.StringIO(newline=''); writer=csv.writer(record,lineterminator='\n')
    for path,data in sorted(entries.items()):
        hashed=base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode()
        writer.writerow([path,'sha256='+hashed,str(len(data))])
    writer.writerow([f'{INFO}/RECORD','',''])
    entries[f'{INFO}/RECORD']=record.getvalue().encode()
    with zipfile.ZipFile(out/name,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for path,data in sorted(entries.items()):
            info=zipfile.ZipInfo(path,date_time=(2026,1,1,0,0,0)); info.compress_type=zipfile.ZIP_DEFLATED; info.external_attr=0o644<<16
            z.writestr(info,data)
    return name


def build_sdist(sdist_directory, config_settings=None):
    out=Path(sdist_directory);out.mkdir(parents=True,exist_ok=True)
    name=f'{NAME}-{VERSION}.tar.gz'
    with (out/name).open('wb') as f:
        with gzip.GzipFile(filename='',mode='wb',fileobj=f,mtime=0) as gz:
            with tarfile.open(fileobj=gz,mode='w') as tar:
                for path in _files():
                    data=path.read_bytes(); info=tarfile.TarInfo(f'{NAME}-{VERSION}/'+path.relative_to(ROOT).as_posix());info.size=len(data);info.mtime=0;info.mode=0o644
                    tar.addfile(info,io.BytesIO(data))
    return name


def get_requires_for_build_wheel(config_settings=None): return []
def get_requires_for_build_sdist(config_settings=None): return []


if __name__=='__main__':
    import sys
    output=sys.argv[1] if len(sys.argv)>1 else 'dist'
    print(build_wheel(output));print(build_sdist(output))
