"""Optional native-tool adapters. All tool processes use the supplied owner.

This module imports no third-party tool and never installs or launches on import.
An installed path is availability, not qualification. Disassembly is static
machine-code evidence; debugger observations apply only to the selected run.
"""
from pathlib import Path
import os
import json
import uuid
import re
import shutil
from .core import TraceError, digest, read_regular, child_path

_SYMBOL=re.compile(r'[A-Za-z_][A-Za-z0-9_]{0,127}\Z')


def resolve_tool(name, configured=None):
    value=configured or shutil.which(name)
    if not value:
        raise TraceError('missing-tool','Configure the optional professional executable',{'tool':name})
    path=Path(value).absolute()
    if path.suffix.lower() in {'.bat','.cmd','.ps1','.sh'}:
        raise TraceError('tool-wrapper-not-admitted','Select a trusted executable, not an unreviewed shell wrapper',{'tool':name})
    raw=read_regular(path,128*1024*1024)
    return {'name':name,'path':str(path),'sha256':digest(raw),'qualification':'selected-executable-only'}


def _invoke(execute,argv):
    result=execute([str(x) for x in argv])
    if not isinstance(result,dict) or not isinstance(result.get('stdout'),bytes) or not isinstance(result.get('stderr'),bytes):
        raise TraceError('adapter-contract','Executor must retain raw byte streams')
    return result


def _text(result):
    return result['stdout'].decode('utf-8','replace')


def _receipt(tool,version):
    return {**tool,'version_output':_text(version).strip()[:4096],
            'version_exit_code':version.get('exit_code'),'version_status':version.get('status')}


def _complete(result):
    return result.get('status')=='succeeded' and result.get('exit_code')==0 and not result.get('output_truncated') and result.get('cleanup',{}).get('state')=='complete'


def disassemble(target,directory,execute,*,objdump=None,symbols=None):
    tool=resolve_tool('objdump',objdump)
    version=_invoke(execute,[tool['path'],'--version'])
    symbols=symbols or []
    if not isinstance(symbols,list) or len(symbols)>32 or any(not isinstance(s,str) or not _SYMBOL.fullmatch(s) for s in symbols):
        raise TraceError('invalid-input','Disassembly symbols must be a bounded C identifier list')
    args=[tool['path'],'-d','-M','intel','--no-show-raw-insn',str(target)]
    result=_invoke(execute,args)
    raw=result['stdout'];text=_text(result)
    output=child_path(directory,'disassembly.txt');output.write_bytes(raw)
    functions=[];calls=[];current=None
    for number,line in enumerate(text.splitlines(),1):
        match=re.match(r'^\s*([0-9a-fA-F]+) <([^>]+)>:',line)
        if match:
            current={'name':match[2],'address':'0x'+match[1],'line':number}
            if len(functions)<10000:functions.append(current)
        call=re.search(r'^\s*([0-9a-fA-F]+):\s+call\s+.*?<([^>]+)>',line)
        if call and current and len(calls)<20000:
            calls.append({'caller':current['name'],'callee':call[2],'instruction_address':'0x'+call[1],'line':number})
    selected=[f for f in functions if not symbols or f['name'] in symbols]
    selected_calls=[c for c in calls if not symbols or c['caller'] in symbols]
    return {'status':'complete' if _complete(result) and _complete(version) else 'partial',
            'domain':'native','method':'GNU objdump actual machine-code disassembly',
            'tool':_receipt(tool,version),'target_sha256':digest(read_regular(target)),
            'functions':selected,'calls':selected_calls,'artifacts':[{'path':'disassembly.txt','sha256':digest(raw),'size':len(raw),'role':'raw-disassembly'}],
            'execution':{k:v for k,v in result.items() if k not in ('stdout','stderr')},
            'limitations':['Call edges are direct symbol-resolved machine instructions, not exhaustive indirect-call resolution','Symbols/debug info depend on the selected build; machine code is not original source','No runtime branch is claimed executed by disassembly'],
            'unknowns':[] if selected else ['Requested functions were not resolved in the admitted disassembly']}


def trace(target,directory,execute,*,gdb=None,breakpoints=None,expressions=None,arguments=None,test_environment=None):
    tool=resolve_tool('gdb',gdb)
    version=_invoke(execute,[tool['path'],'--version'])
    points=breakpoints or [];expressions=expressions or [];arguments=arguments or []
    if not 1<=len(points)<=8 or any(not isinstance(x,str) or not _SYMBOL.fullmatch(x) for x in points):
        raise TraceError('invalid-input','Debugger needs 1-8 explicit symbol breakpoints')
    if len(expressions)>16 or any(not isinstance(x,str) or not _SYMBOL.fullmatch(x) for x in expressions):
        raise TraceError('invalid-input','Inspect simple named variables only; no debugger expression evaluation or function calls')
    if len(arguments)>16 or any(not isinstance(x,str) or not re.fullmatch(r'[A-Za-z0-9_./-]{1,256}',x) for x in arguments):
        raise TraceError('invalid-input','Debugger arguments must be simple fixture names/values')
    test_environment=test_environment or {}
    if len(test_environment)>8 or any(not re.fullmatch(r'TRACEANCHOR_[A-Z0-9_]+',k) or not isinstance(v,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',v) for k,v in test_environment.items()):
        raise TraceError('invalid-input','Only bounded non-secret TRACEANCHOR test environment values are admitted')
    commands=['set pagination off','set confirm off','set print elements 64']
    if os.name!='nt':commands.append('set startup-with-shell off')
    for key,value in sorted(test_environment.items()):commands.append('set environment '+key+'='+value)
    if arguments:commands.append('set args '+' '.join(arguments))
    event_path=child_path(directory,'gdb-events-'+uuid.uuid4().hex+'.json')
    nonce=uuid.uuid4().hex
    commands.extend(['python', 'import gdb,json',
        'TA_EVENTS=[]', 'TA_EXIT=[]',
        'TA_PATH='+repr(str(event_path)), 'TA_NONCE='+repr(nonce),
        'TA_VARS='+repr(expressions),
        'def ta_save():',
        '    with open(TA_PATH,"w",encoding="utf-8") as f: json.dump({"nonce":TA_NONCE,"events":TA_EVENTS,"exits":TA_EXIT},f)',
        'class TABreak(gdb.Breakpoint):',
        '    def __init__(self,name):',
        '        super().__init__(name,internal=False);self.ta_name=name;self.silent=True',
        '    def stop(self):',
        '        frame=gdb.selected_frame();values={}',
        '        for name in TA_VARS:',
        '            try: values[name]=str(gdb.parse_and_eval(name))',
        '            except gdb.error as exc: values[name]="unknown:"+str(exc)',
        '        args=gdb.execute("info args",to_string=True);stack=gdb.execute("bt 8",to_string=True)',
        '        TA_EVENTS.append({"kind":"gdb-breakpoint-callback","symbol":self.ta_name,"function":frame.name(),"pc":hex(frame.pc()),"inferior_pid":gdb.selected_inferior().pid,"arguments":args,"stack":stack,"values":values})',
        '        ta_save();gdb.write(args+stack)',
        '        return False',
        'def ta_exit(event):',
        '    TA_EXIT.append({"exit_code":getattr(event,"exit_code",None)});ta_save()',
        'gdb.events.exited.connect(ta_exit)'])
    commands.extend('TABreak('+repr(point)+')' for point in points)
    commands.extend(['ta_save()','end'])
    commands.append('run')
    script=child_path(directory,'debugger.gdb');script.write_text('\n'.join(commands)+'\n',encoding='utf-8')
    result=_invoke(execute,[tool['path'],'-nx','-nh','-q','-batch','-x',str(script),str(target)])
    raw=result['stdout'];child_path(directory,'debugger-trace.txt').write_bytes(raw)
    text=_text(result)
    events={}
    if event_path.is_file():
        try:events=json.loads(read_regular(event_path,1048576))
        except (TraceError,ValueError):events={}
    valid=events.get('nonce')==nonce
    hit=[e for e in events.get('events',[]) if valid and e.get('kind')=='gdb-breakpoint-callback' and e.get('symbol') in points and e.get('function')==e.get('symbol') and e.get('inferior_pid',0)>0]
    complete=_complete(result) and _complete(version) and bool(hit) and any(e.get('exit_code')==0 for e in events.get('exits',[]))
    return {'status':'complete' if complete else 'partial','domain':'native','method':'GNU GDB actual breakpoint, arguments and call-stack trace',
            'tool':_receipt(tool,version),'target_sha256':digest(read_regular(target)),
            'breakpoint_hits':hit,'runtime_trace':text,'breakpoint_authority':'GDB Python Breakpoint.stop callback and debugger-selected frame; never target stdout marker','test_environment':test_environment,
            'artifacts':[{'path':'debugger.gdb','sha256':digest(script.read_bytes()),'role':'replay-commands'}, {'path':'debugger-trace.txt','sha256':digest(raw),'role':'raw-runtime-trace'}]+([{'path':event_path.name,'sha256':digest(event_path.read_bytes()),'role':'debugger-event-receipt'}] if event_path.is_file() else []),
            'execution':{k:v for k,v in result.items() if k not in ('stdout','stderr')},
            'limitations':['Breakpoints change timing and are a derived observation condition','Only hit symbols and inspected variables are observed; no claim about other inputs or all process memory','Tool exit zero alone does not qualify the trace; actual hits and normal inferior exit are required'],
            'unknowns':[] if complete else ['No complete qualified breakpoint trace for the requested scenario']}
