"""Actual native-tool qualification on an original non-blind parcel fixture.
No external target, third-party download, model call or global configuration.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from traceanchor.core import digest
from traceanchor.process import run_process
from traceanchor.professional import resolve_tool, disassemble, trace


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--gcc');p.add_argument('--objdump');p.add_argument('--gdb')
    args=p.parse_args()
    directory=ROOT/'.validation'/('native-'+uuid.uuid4().hex[:12]);directory.mkdir(parents=True)
    manifest={'owner':'native-professional-qualification','tier':'L2','reason':'P01 replayable build and actual tool evidence','status':'active','cleanup':'pending','regeneration':'tools/qualify_professional.py','runs':[]}
    manifest_path=directory/'ownership.json'
    def persist():manifest_path.write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    persist()
    def execute(argv,input_bytes=b''):
        n=len(manifest['runs'])+1
        outcome=run_process(argv,cwd=str(directory),input_bytes=input_bytes,timeout=30,idle_timeout=15,output_limit=8*1024*1024)
        for stream in ('stdout','stderr'):(directory/(str(n)+'-'+stream+'.bin')).write_bytes(outcome[stream])
        manifest['runs'].append({'argv':argv,'stdout':str(n)+'-stdout.bin','stderr':str(n)+'-stderr.bin',**{k:v for k,v in outcome.items() if k not in ('stdout','stderr')}})
        persist();return outcome
    try:
        source=ROOT/'examples/native/parcel.c';snapshot=directory/'parcel.c';snapshot.write_bytes(source.read_bytes())
        executable=directory/('parcel.exe' if os.name=='nt' else 'parcel')
        compiler=resolve_tool('gcc',args.gcc)
        compiler_version=execute([compiler['path'],'--version'])
        built=execute([compiler['path'],'-g','-O0','-fno-inline','-o',str(executable),str(snapshot)])
        if built['status']!='succeeded' or built['exit_code']!=0:raise AssertionError('Native fixture build failed; inspect retained raw diagnostics')
        static=disassemble(executable,directory,execute,objdump=args.objdump,symbols=['dispatch_command','quote_parcel','reserve_parcels','main'])
        edges={(x['caller'],x['callee']) for x in static['calls']}
        assert ('dispatch_command','quote_parcel') in edges and ('dispatch_command','reserve_parcels') in edges
        scenario=b'reserve 3\nquote 501 1\ncancel 1\nreserve 99\nstate\n'
        (directory/'scenario.txt').write_bytes(scenario)
        dynamic=trace(executable,directory,execute,gdb=args.gdb,breakpoints=['quote_parcel','reserve_parcels'],expressions=['service_zone','available','reserved'],arguments=['scenario.txt'],test_environment={'TRACEANCHOR_PARCEL_ZONE':'remote'})
        assert static['status']=='complete',static['execution']
        assert dynamic['status']=='complete',dynamic['runtime_trace']
        text=dynamic['runtime_trace']
        assert 'grams=501' in text.replace(' ','') and 'zone=2' in text.replace(' ','')
        assert '"cents":920' in text and '"error":"stock"' in text
        output={'status':'pass','contract_id':'FOUR-SOURCE-PRODUCT-R3','product_gate':'P01-tool-slice','sample':'original non-blind parcel-pricing/reservation fixture; NOT P04 independent-reconstruction proof','source_sha256':digest(snapshot.read_bytes()),'target_sha256':digest(executable.read_bytes()),'compiler':{**compiler,'version':compiler_version['stdout'].decode('utf-8','replace')[:4096]},'static':static,'runtime':dynamic,'question':'Which fee path and stock state are actually used when runtime environment selects the remote zone?','static_hypothesis':'quote_parcel accepts a runtime zone; static code alone does not establish the live branch for a deployment','observed_answer':'GDB stopped in quote_parcel with grams=501, priority=1, zone=2; dispatched quote returned 920 cents; reserve 99 followed the stock error branch','scenario_sha256':digest(scenario),'scope':'GNU machine-code disassembly and actual GDB breakpoint/arguments/stack observations, not only process exit/stdout','limitations':['Self-created source is visible to qualifier; this sample is capability qualification, not a blind reverse-engineering result','General GUI, stripped/packed binaries and other tools/platforms are not implied']}
        (directory/'qualification.json').write_text(json.dumps(output,indent=2)+'\n',encoding='utf-8')
        manifest.update(status='completed',cleanup='complete',target_sha256=output['target_sha256']);persist()
        print(json.dumps({'status':'pass','directory':directory.relative_to(ROOT).as_posix(),'calls':len(static['calls']),'breakpoint_hits':len(dynamic['breakpoint_hits'])}))
        return 0
    except BaseException as exc:
        manifest.update(status='failed',error={'type':type(exc).__name__,'message':str(exc)},cleanup='complete' if all(x.get('cleanup',{}).get('state')=='complete' for x in manifest['runs']) else 'unknown');persist()
        raise

if __name__=='__main__':sys.exit(main())
