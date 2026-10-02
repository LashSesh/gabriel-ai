"""Paired fresh-owner full-replay experiment, with resumable case outputs.

--prepare freezes the protocol and binary64 synthetic inputs.
--run registers|h1|h5 executes one case alone. --summarize requires all cases.
Use OPENBLAS_NUM_THREADS=OMP_NUM_THREADS=MKL_NUM_THREADS=1.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import platform
import statistics
import sys
import tempfile
import time
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'reproduction')]
from gabriel_runtime.canonical import canonical, digest
from gabriel_runtime.fast_owner import FastStore
from gabriel_runtime.replay_owner import ReplayStore
from benchmark_fast_owner import register_registry, stream_registry

PROTOCOL={
    'schema':'gabriel-replay-open-benchmark/v2-reconstructed',
    'status':'frozen_before_timing','seed':2026092617,
    'owners':['fast','replay'], 'register_widths':[32,256,2048],
    'register_updates':1000,'register_pairs':5,'horizons':[1,5],
    'source_lengths':[360,500,800],'stream_pairs':3,
    'stream_config':{'source_id':'replay-owner-synthetic','risk_budget':'10','unit_exposure':'100','max_units':100},
    'source':'NumPy default_rng(seed); 801 prices, 100*exp(cumsum(.006*(1+.3*sin(i/31))*Z_i)); binary64 hex archived.',
    'corrections':'At each length checkpoint: revise index320 by33/32 and length-3 by65/64. Each revision increments. Later checkpoints retain earlier revisions.',
    'clocks':'Bind at0; owner receipt time equals next command ordinal. Source event_at=index; corrected records keep event_at.',
    'paired_order':'fast then replay for even pair, reverse for odd; same unchanged database; fresh adapter and owner each open.',
    'timed':'Store.open including connect/header checks and complete semantic replay. Filesystem warm; no page-cache flush. Close, equality checks, full view, input/database construction excluded.',
    'durability':'Unchanged SQLite v1, DELETE/EXTRA; every live unique command uses one durable transaction. No checkpoints.',
    'equality':'Exact canonical head/budget/view after every open; database SHA256 before/after each group; source hashes before/after each case.',
    'threads':{'OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1'},
    'limits':'Synthetic, one host; alternating paired repetitions are descriptive, no confidence intervals, no affinity/frequency lock, no forecast change.',
    'recovery':'This is a fresh executed experiment. Lost raw outputs from the interrupted earlier run are not reconstructed from summary statistics.'}


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n')


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def source_hashes():
    files=list((ROOT/'gabriel_runtime').glob('*.py'))+[Path(__file__),ROOT/'reproduction/benchmark_fast_owner.py']
    return {str(p.relative_to(ROOT)):sha(p) for p in sorted(files)}


def prepare():
    import numpy as np
    rng=np.random.default_rng(PROTOCOL['seed']);i=np.arange(801,dtype=float)
    prices=100*np.exp(np.cumsum(.006*(1+.3*np.sin(i/31))*rng.standard_normal(801)))
    data={'protocol_sha256':digest(PROTOCOL),'price_hex':[float(p).hex() for p in prices]}
    write(ROOT/'results/replay_benchmark_protocol.json',PROTOCOL)
    write(ROOT/'results/replay_benchmark_inputs.json',data)


def measure(path,factory,pairs,view_expected,anchor):
    before=sha(path);samples=[]
    for i in range(pairs):
        row={}
        for name in (['fast','replay'] if i%2==0 else ['replay','fast']):
            cls=FastStore if name=='fast' else ReplayStore
            registry=factory()
            start=time.perf_counter();opened=cls.open(path,registry)
            row[name]=time.perf_counter()-start
            assert canonical({'head':opened.head,'budget':opened.budget})==anchor
            assert canonical(opened.view('main'))==view_expected
            opened.close()
        row['ratio']=row['fast']/row['replay'];samples.append(row)
        print(json.dumps({'database':path.name,'pair':i,'seconds':row}),flush=True)
    assert sha(path)==before
    return {'samples':samples,'database_sha256':before,'database_bytes':path.stat().st_size,
        'events':json.loads(anchor)['budget']['events'],
        'median_seconds':{n:statistics.median(s[n] for s in samples) for n in ['fast','replay']},
        'median_paired_ratio':statistics.median(s['ratio'] for s in samples),
        'paired_ratio_range':[min(s['ratio'] for s in samples),max(s['ratio'] for s in samples)]}


def make_submit(store):
    ordinal=0
    def send(op,payload):
        nonlocal ordinal
        cmd={'id':'cmd-%06d'%ordinal,'contract':'main','op':op,'at':ordinal,
            'expected_head':store.head,'payload':payload}
        result=store.submit(cmd);ordinal+=1
        return result
    return send


def registers(temp):
    rows=[]
    for width in PROTOCOL['register_widths']:
        p=temp/('register-'+str(width)+'.sqlite')
        with FastStore.create(p,register_registry()) as s:
            send=make_submit(s);send('bind',{'adapter':'benchmark-register/v1','config':{'width':width}})
            for i in range(PROTOCOL['register_updates']):send('add',{'index':37*i%width,'amount':1+i%19})
            view=canonical(s.view('main'));anchor=canonical({'head':s.head,'budget':s.budget})
        rows.append({'width':width,**measure(p,register_registry,PROTOCOL['register_pairs'],view,anchor)})
    return rows


def stream(temp,h,prices):
    p=temp/('stream-h'+str(h)+'.sqlite'); rows=[];n=0;revision={}
    with FastStore.create(p,stream_registry()) as s:
        send=make_submit(s);send('bind',{'adapter':'stream-risk/v1','config':PROTOCOL['stream_config']|{'horizon':h}})
        def record(index,rev,value):
            send('record',{'index':index,'event_at':index,'received_at':s.budget['events'],
                'revision':rev,'rate_hex':value.hex()})
        for target in PROTOCOL['source_lengths']:
            while n<target: record(n,0,prices[n]);n+=1
            for index,factor in [(320,33/32),(n-3,65/64)]:
                revision[index]=revision.get(index,0)+1
                record(index,revision[index],prices[index]*factor)
            view=canonical(s.view('main'));anchor=canonical({'head':s.head,'budget':s.budget})
            rows.append({'horizon':h,'source_length':n,**measure(p,stream_registry,PROTOCOL['stream_pairs'],view,anchor)})
            write(ROOT/('results/replay_benchmark_h'+str(h)+'_partial.json'),rows)
    return rows


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--prepare',action='store_true')
    parser.add_argument('--run',choices=['registers','h1','h5']);parser.add_argument('--summarize',action='store_true')
    args=parser.parse_args()
    if args.prepare:prepare();return
    protocol=json.loads((ROOT/'results/replay_benchmark_protocol.json').read_text())
    data=json.loads((ROOT/'results/replay_benchmark_inputs.json').read_text())
    assert protocol==PROTOCOL and data['protocol_sha256']==digest(PROTOCOL)
    if args.summarize:
        cases={name:json.loads((ROOT/('results/replay_benchmark_'+name+'.json')).read_text()) for name in ['registers','h1','h5']}
        assert all(c['status']=='passed' and c['protocol_sha256']==digest(PROTOCOL) for c in cases.values())
        write(ROOT/'results/replay_benchmark.json',{'schema':'gabriel-replay-open-summary/v2','protocol':PROTOCOL,
            'cases':cases,'timed_opens':sum(len(row['samples'])*2 for c in cases.values() for row in c['rows'])})
        return
    if not args.run:parser.error('choose --prepare, --run or --summarize')
    assert all(os.environ.get(k)==v for k,v in PROTOCOL['threads'].items())
    before=source_hashes();started=datetime.now(timezone.utc).isoformat();t=time.perf_counter()
    with tempfile.TemporaryDirectory(prefix='gabriel-replay-benchmark-') as d:
        rows=registers(Path(d)) if args.run=='registers' else stream(Path(d),int(args.run[1:]),list(map(float.fromhex,data['price_hex'])))
    assert before==source_hashes()
    write(ROOT/('results/replay_benchmark_'+args.run+'.json'),{
        'status':'passed','case':args.run,'protocol_sha256':digest(PROTOCOL),'input_sha256':sha(ROOT/'results/replay_benchmark_inputs.json'),
        'started_utc':started,'finished_utc':datetime.now(timezone.utc).isoformat(),'elapsed_seconds':time.perf_counter()-t,
        'source_sha256':before,'python':sys.version,'platform':platform.platform(),'thread_environment':PROTOCOL['threads'],'rows':rows})


if __name__=='__main__':main()
