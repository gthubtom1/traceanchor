"""Read-only, on-demand domain guidance; not another execution controller."""
from pathlib import Path
import shutil
from .core import TraceError, digest, read_regular

CATALOG={
 'native':{'methods':['native.disassemble','native.trace'],'tools':['objdump','gdb'],'question':'Locate concrete machine-code logic, then observe runtime parameters/state when static evidence is insufficient'},
 'apk':{'methods':['apk.analyze'],'tools':['java'],'additional_configuration':['jadx_jar'],'question':'Locate DEX-derived class/method control logic and cross-check critical calls; Android execution remains separate'},
 'web':{'methods':['web.observe'],'tools':['node'],'question':'Observe finite JS interactions, client/service state, real HTTP IDs and inspector function positions; do not infer browser DOM qualification'}
}


def guide(domain):
    if domain not in CATALOG:raise TraceError('unsupported-capability','No qualified domain guide for this target',{'domains':sorted(CATALOG)})
    local=Path(__file__).resolve().parents[1]/'docs'/'knowledge'/(domain+'.md')
    packaged=Path(__file__).with_name('resources')/'docs'/'knowledge'/(domain+'.md')
    path=local if local.is_file() else packaged
    raw=read_regular(path,262144)
    return {'domain':domain,**CATALOG[domain],'guide':raw.decode('utf-8'),'sha256':digest(raw),'authority':'Method guidance only. Case effects, budgets, source identity and actual tool outcomes remain core authority.'}


def capabilities():
    return {'professional':{name:{**data,'availability':{tool:bool(shutil.which(tool)) for tool in data['tools']},'qualification':'Not probed by doctor; version and real operation are recorded by professional.run','auto_install':False} for name,data in CATALOG.items()},'browser_extension':{'manifest_static':'existing bounded JSON analysis','runtime':'not-qualified','route':'Use an explicitly qualified browser/CDP adapter on a separate profile and extension ID; Node or manifest success alone does not qualify an extension'},'model_loop':'Current host reasons, selects a guide and uses the single application service; no internal model loop'}
