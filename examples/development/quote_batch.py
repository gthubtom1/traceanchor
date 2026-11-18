"""A normal development feature consuming a researched legacy quote interface.
This is a batch-order utility, not an independent reconstruction of the backend.
The explicit selected backend path is supplied by the developer at runtime.
"""
import json
import subprocess
import sys


def main():
    items=json.load(sys.stdin)['items']
    if not isinstance(items,list) or len(items)>20:
        raise ValueError('at most twenty order items')
    for item in items:
        if not isinstance(item,dict) or type(item.get('grams')) is not int or type(item.get('priority',0)) is not int:
            raise ValueError('explicit integer grams and priority are required')
    commands=''.join('quote %d %d\n'%(item['grams'],item.get('priority',0)) for item in items)+'state\n'
    process=subprocess.run([sys.argv[1]],input=commands.encode(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=5,shell=False)
    if process.returncode!=0 or process.stderr:
        raise RuntimeError('selected backend failed; do not turn missing observation into a quote')
    responses=[json.loads(line) for line in process.stdout.splitlines() if line.strip()]
    if len(responses)!=len(items)+1:
        raise RuntimeError('backend response contract changed')
    quotes=responses[:-1]
    result={'quotes':quotes,'total_cents':sum(x['cents'] for x in quotes if x.get('ok') is True),'backend_state':responses[-1]}
    print(json.dumps(result,separators=(',',':'),sort_keys=True))

if __name__=='__main__':main()
