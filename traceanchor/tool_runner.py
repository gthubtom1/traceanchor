"""One process/material authority for optional professional adapters."""
import time
import os
import base64
from pathlib import Path
from .core import TraceError, canonical, child_path, digest, new_id, read_regular, value_digest
from .process import run_process
from . import workspace


def run(store,case_id,source_id,operation,options=None,tools=None,cancel=None):
    from .service import _source, _case, _effect, _all, _source_name, _environment
    case=_case(store,case_id);_effect(case,'execute')
    source=_source(store,case_id,source_id)
    if source['data'].get('portable_snapshot'):
        raise TraceError('imported-execution-not-admitted','Explicitly reattach a local target before tool execution')
    if operation not in ('native.disassemble','native.trace','apk.analyze','web.observe'):
        raise TraceError('unsupported-capability','Select an implemented professional operation')
    if operation=='web.observe':_effect(case,'network')
    options=options or {};tools=tools or {}
    if not isinstance(options,dict) or not isinstance(tools,dict):raise TraceError('invalid-input','Tool options and paths must be objects')
    workspace.admit(store,source['data']['size']+262144)
    identity=new_id('run');resource='case-execution:'+case_id
    store.acquire(resource,identity)
    owner=None;item=None;raw_ids=[];children=[]
    try:
        owner=store.create('run',{'kind':'professional-owner','status':'preparing','source_id':source_id,'source_sha256':source['data']['sha256'],'cleanup':{'state':'pending'},'options_digest':value_digest(options),'environment':_environment()},case_id,id=identity)
        item=workspace.register_directory(store,'work/'+identity,case_id,identity,tier='L2',reason=operation)
        directory=child_path(store.root,item['data']['path'])
        reservation=workspace.reserve(store,identity,source['data']['size'],'immutable target copy')
        target=child_path(directory,_source_name(source['data']['name']))
        try:target.write_bytes(store.read_material(source['data']['material_id']))
        finally:workspace.release(store,reservation['id'],identity)
        state={'last_check':0.0,'budget_error':None}
        def cancelled():
            if cancel is not None and cancel.is_set():return True
            if store.get('run',identity)['data'].get('cancel_requested'):return True
            now=time.perf_counter()
            if now-state['last_check']>=0.05:
                state['last_check']=now
                try:workspace.admit(store)
                except TraceError as exc:state['budget_error']=exc.as_dict();return True
            return False
        def execute(argv,input_bytes=b'',env=None):
            workspace.admit(store)
            if env is not None and (not isinstance(env,dict) or any(not isinstance(k,str) or not isinstance(v,str) for k,v in env.items())):
                raise TraceError('adapter-contract','Tool environment overrides must be string pairs')
            environment={**os.environ, **(env or {})}
            previous=[r for r in _all(store,'run',case_id) if r['id']!=identity and r['data'].get('kind')!='professional-owner']
            timeout=options.get('timeout',30)
            if type(timeout) not in (int,float) or not 0<timeout<=60:raise TraceError('invalid-input','Tool timeout must be positive and at most 60 seconds')
            charged=sum(r['data'].get('reserved_seconds',r['data'].get('elapsed_seconds',0)) for r in previous)
            if len(previous)>=case['data']['budgets']['max_runs'] or charged+timeout>case['data']['budgets']['max_seconds']:
                raise TraceError('task-budget','Tool command not launched; cumulative task budget exhausted')
            child=store.create('run',{'kind':'professional-command','parent_run_id':identity,'source_id':source_id,'status':'preparing','cleanup':{'state':'pending'},'reserved_seconds':timeout,'argv_digest':value_digest(argv)},case_id)
            children.append(child['id'])
            def started(receipt):store.update('run',child['id'],{'status':'running','identity':receipt})
            result=run_process(argv,cwd=str(directory),input_bytes=input_bytes,timeout=timeout,idle_timeout=min(timeout,15),output_limit=case['data']['budgets']['output_limit'],cancelled=cancelled,on_start=started,env=environment)
            extra={}
            if state['budget_error']:extra={'resource_limit':state['budget_error'],'polling_limit':'Growth is polled every 50ms; overshoot is possible and retained, not an OS quota'}
            outcome={k:v for k,v in result.items() if k not in ('stdout','stderr')}
            store.update('run',child['id'],{**outcome,**extra,'reserved_seconds':result.get('elapsed_seconds',timeout)})
            # Preserve a bounded exact prefix in the durable run even if an
            # exceeded directory budget prevents new CAS evidence admission.
            emergency={name:{'prefix_base64':base64.b64encode(result[name][:4096]).decode(),'full_size':len(result[name]),'full_sha256':digest(result[name]),'complete':len(result[name])<=4096} for name in ('stdout','stderr')}
            store.update('run',child['id'],{'recovery_stream_prefixes':emergency,'recovery_scope':'At most4096bytes/stream retained in control journal; not a fabricated full observation'})
            if state['budget_error']:raise TraceError('work-budget','Tool cancelled after workspace growth limit',state['budget_error'])
            streams={}
            for name in ('stdout','stderr'):
                blob=store.put_bytes(case_id,result[name],'L1','raw-tool-'+name,child['id'])
                raw_ids.append(blob['id']);streams[name+'_material']=blob['id'];store.add_ref(child['id'],blob['id'],'raw-tool-stream')
            store.update('run',child['id'],{'publication':'complete',**streams})
            if state['budget_error']:raise TraceError('work-budget','Tool cancelled after workspace growth limit',state['budget_error'])
            return result
        clean_options={k:v for k,v in options.items() if k!='timeout'}
        if operation=='native.disassemble':
            from .professional import disassemble
            result=disassemble(target,directory,execute,objdump=tools.get('objdump'),**clean_options)
        elif operation=='native.trace':
            from .professional import trace
            inputs=clean_options.pop('input_files',{})
            if not isinstance(inputs,dict) or len(inputs)>10:raise TraceError('invalid-input','At most ten bounded fixture input files')
            for relative,text in inputs.items():
                if not isinstance(text,str) or len(text.encode())>1048576:raise TraceError('invalid-input','Fixture input is not bounded text')
                path=child_path(directory,relative)
                if path.exists():raise TraceError('conflict','Fixture cannot replace a target/tool artifact')
                reservation=workspace.reserve(store,identity,len(text.encode()),'debugger fixture input')
                try:path.write_text(text,encoding='utf-8')
                finally:workspace.release(store,reservation['id'],identity)
            result=trace(target,directory,execute,gdb=tools.get('gdb'),**clean_options)
        elif operation=='apk.analyze':
            from .apk_adapter import analyze
            result=analyze(target,directory,execute,java=tools.get('java'),jadx_jar=tools.get('jadx_jar'),**clean_options)
        else:
            from .web_adapter import observe
            result=observe(target,directory,execute,node=tools.get('node'),**clean_options)
        _source(store,case_id,source_id)
        artifacts=[]
        for artifact in result.get('artifacts',[]):
            path=child_path(directory,artifact['path']);raw=read_regular(path,case['data']['budgets']['max_bytes'])
            reservation=workspace.reserve(store,identity,len(raw),'archive selected professional evidence')
            try:blob=store.put_bytes(case_id,raw,'L1','professional-evidence',identity,{'relative_path':artifact['path'],'tool_operation':operation})
            finally:workspace.release(store,reservation['id'],identity)
            artifacts.append(blob['id'])
        observation=store.create('observation',{'source_id':source_id,'source_sha256':source['data']['sha256'],'run_id':identity,'professional':result,'artifact_ids':artifacts,'raw_material_ids':raw_ids,'trust':'local-managed-tool-execution','producer':'traceanchor-professional-owner','environment':owner['data']['environment']},case_id)
        for target_id in (source_id,*artifacts,*raw_ids):store.add_ref(observation['id'],target_id,'professional-evidence')
        store.update('run',identity,{'status':'succeeded' if result.get('status') in ('complete','completed','succeeded') else 'failed','cleanup':{'state':'complete'},'publication':'complete','observation_id':observation['id'],'child_run_ids':children})
        workspace.finish_directory(store,item['id'],'completed',{'state':'complete'})
        return observation
    except BaseException as exc:
        if owner:
            complete=all(store.get('run',c)['data'].get('cleanup',{}).get('state')=='complete' for c in children)
            cleanup={'state':'complete' if complete else 'unknown'}
            store.update('run',identity,{'status':'failed','cleanup':cleanup,'error':exc.as_dict() if isinstance(exc,TraceError) else {'code':'tool-error','message':str(exc)},'child_run_ids':children})
            if item:
                try:workspace.finish_directory(store,item['id'],'failed',cleanup)
                except (OSError,TraceError):pass
        raise
    finally:
        if not owner or store.get('run',identity)['data'].get('cleanup',{}).get('state')=='complete':store.release(resource,identity)
