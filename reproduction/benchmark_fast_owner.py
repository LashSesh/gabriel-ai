"""Matched durable-owner benchmark; synthetic workloads, no forecasts selected.

Prepare frozen protocol/data first:
  python reproduction/benchmark_fast_owner.py --prepare
Run alone, with OMP_NUM_THREADS=OPENBLAS_NUM_THREADS=MKL_NUM_THREADS=1:
  python reproduction/benchmark_fast_owner.py --run
The journal uses DELETE/EXTRA throughout. Complete semantic open is never skipped.
"""
from __future__ import annotations
import argparse
import cProfile
import hashlib
import json
import os
from pathlib import Path
import platform
import sqlite3
import statistics
import sys
import tempfile
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gabriel_runtime.canonical import canonical, digest
from gabriel_runtime.engine import Store
from gabriel_runtime.fast_owner import FastStore

PROTOCOL = {
    'format': 'gabriel-fast-owner-benchmark/v1', 'status': 'frozen_before_timing',
    'seed': 2026092603,
    'implementations': ['reference_owner', 'fast_owner'],
    'owner_classes': ['gabriel_runtime.engine.Store', 'gabriel_runtime.fast_owner.FastStore'],
    'durability': 'Both owners SQLite DELETE journal, synchronous EXTRA; one transaction and commit per accepted command; same registry fingerprint, header, commands, receipts and stored canonical state.',
    'thread_environment': {'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1'},
    'paired_order': 'reference then fast for even pair index, reverse for odd; same command exact bytes supplied to both',
    'warmup': '32 fixed-width accumulator commands per owner outside timing before any measured runs',
    'register_widths': [32, 256, 2048], 'register_prefix_commands': 100,
    'register_trials': 7, 'register_commands_per_trial': 100,
    'register_rule': 'Initialize width integer registers to zero; event i adds 1+(i mod 19) to register (37*i mod width), returns count,total; bounded exact JSON state.',
    'stream_horizons': [1, 5], 'stream_neighborhood_starts': [360, 500, 800],
    'stream_trials': 7,
    'stream_trial_order': ['append', 'early_correction_then_append', 'recent_correction_then_append'],
    'stream_neighborhood': 'Seven successive live trials, each accepting three new observations and two corrections. Start lengths n,n+3,...,n+18; final length n+21. Both implementations have identical evolving state; these are neighborhoods, not independent repetitions of one state.',
    'stream_config': {'source_id': 'fast-owner-synthetic', 'risk_budget': '10', 'unit_exposure': '100', 'max_units': 100},
    'stream_profile': 'Both owners use fresh IncrementalStreamRiskAdapter with same fingerprint and numerical caches; this measures owner change only, not incremental-vs-baseline forecasting.',
    'stream_source': 'NumPy default_rng(seed), r_i=.006*(1+.3*sin(i/31))*Z_i, price_i=100*exp(cumsum(r)_i), 823 observations encoded binary64 hex.',
    'stream_corrections': 'Early index320, alternating factors33/32 and31/32 by successive revision parity; recent index current_source_length-3, factor65/64. Revision increments per index. Correction and immediately following append timed separately and summed.',
    'clocks': 'event_at=index; each accepted record received_at=owner_at=next owner command ordinal, including corrections; bind at0.',
    'cold_open_repetitions': {'360': 5, '500': 1, '800': 1},
    'cold_open_scope': 'Fresh owner and fresh adapter over each existing live-owner database, complete semantic replay in Store.open; OS page cache not flushed; close outside timer. Report warm filesystem/cold adapter distinction.',
    'warm_audit_repetitions': 1,
    'views': 'One full view per owner per stream trial, timed separately, after all five commands; state and forecast history materialized in both.',
    'trajectory_measurement': 'Sum submit wall times for all source/correction commands; prefix checkpoints360,500,800 include earlier benchmark-neighborhood corrections. Equality checks, view/audit/open, profiler and source generation excluded.',
    'profiling': 'After last neighborhood, one matched additional append per horizon under cProfile. These profiled wall times are excluded from efficiency summaries; record Python call counts and top cumulative functions.',
    'exactness': 'Direct canonical receipt-string comparison after every paired command; direct SQL canonical-state-string/meta comparison at checkpoint and branch boundaries; journal rows compared byte for byte; actual export API compared for register endpoints and stream n360.',
    'timing_exclusions': 'Imports, database creation/bind, input generation, command construction, exactness checks, report writing, cProfile diagnostics; no transaction batching and no bypass of audit on open.',
    'limits': 'Synthetic bounded workloads; seven sequential paired trials are descriptive, correlated observations, not independent samples or confidence intervals. No universal throughput, predictive gain or external product comparison.',
}


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False)+'\n')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def input_data():
    import numpy as np
    rng = np.random.default_rng(PROTOCOL['seed'])
    i = np.arange(823, dtype=float)
    prices = 100*np.exp(np.cumsum(.006*(1+.3*np.sin(i/31))*rng.standard_normal(823)))
    assert np.isfinite(prices).all() and (prices>0).all()
    return {'protocol_sha256': digest(PROTOCOL), 'price_hex': [float(v).hex() for v in prices]}


def summary(values):
    return {'median': statistics.median(values), 'minimum': min(values),
            'maximum': max(values), 'samples': values}


def pair_summary(samples, key='seconds'):
    left=[s['reference_owner'][key] for s in samples]
    right=[s['fast_owner'][key] for s in samples]
    return {'reference_owner': summary(left), 'fast_owner': summary(right),
            'paired_speedup': summary([a/b for a,b in zip(left,right)])}


class RegisterAdapter:
    """Benchmark-only domain-independent exact accumulator, no task accuracy."""
    def fingerprint(self):
        return {'adapter': 'benchmark-register/v1', 'arithmetic': 'exact-bounded-integers',
                'mutation': 'trusted-local-apply-input'}

    def initialize(self, config):
        if set(config)!= {'width'} or type(config['width']) is not int or config['width']<=0:
            raise ValueError('positive integer width required')
        return {'registers': [0]*config['width'], 'count': 0, 'total': 0}

    def apply(self, state, operation, payload, at):
        if operation!='add' or set(payload)!={'index','amount'}:
            raise ValueError('register operation')
        index, amount=payload['index'],payload['amount']
        if type(index) is not int or type(amount) is not int or not 0<=index<len(state['registers']):
            raise ValueError('register input')
        state['registers'][index] += amount
        state['total'] += amount; state['count'] += 1
        return state, self.view(state)

    def view(self, state):
        return {'count': state['count'], 'total': state['total']}


def stream_registry():
    from gabriel_runtime.incremental import IncrementalStreamRiskAdapter
    return {'stream-risk/v1': IncrementalStreamRiskAdapter()}


def register_registry():
    return {'benchmark-register/v1': RegisterAdapter()}


class Pair:
    def __init__(self, directory, key, registry_factory, adapter, config):
        self.factory=registry_factory; self.paths={}; self.stores={}; self.ordinal=0
        self.receipt_checks=0; self.state_checks=0; self.journal_rows_checked=0; self.export_checks=0
        self.submit_seconds={k:0. for k in PROTOCOL['implementations']}
        for name,cls in zip(PROTOCOL['implementations'], [Store,FastStore]):
            self.paths[name]=Path(directory)/(key+'-'+name+'.sqlite')
            self.stores[name]=cls.create(self.paths[name],registry_factory())
        self._submit('bind',{'adapter':adapter,'config':config},at=0,measure=False)

    def _submit(self,op,payload,at=None,measure=True):
        if at is None: at=self.ordinal
        assert self.stores['reference_owner'].head==self.stores['fast_owner'].head
        cmd={'id':f'cmd-{self.ordinal:06d}','contract':'main','op':op,'at':at,
             'expected_head':self.stores['reference_owner'].head,'payload':payload}
        receipts={}; timings={}
        order=PROTOCOL['implementations'] if self.ordinal%2==0 else list(reversed(PROTOCOL['implementations']))
        for name in order:
            start=time.perf_counter()
            receipts[name]=self.stores[name].submit(cmd)
            timings[name]={'seconds':time.perf_counter()-start}
            if measure: self.submit_seconds[name]+=timings[name]['seconds']
        assert canonical(receipts['reference_owner'])==canonical(receipts['fast_owner']),('receipt',self.ordinal)
        self.receipt_checks+=1; self.ordinal+=1
        return timings

    def state_check(self, journal=False, export=False):
        left,right=[self.stores[k] for k in PROTOCOL['implementations']]
        assert left._db.execute('SELECT * FROM meta').fetchall()==right._db.execute('SELECT * FROM meta').fetchall()
        assert left._db.execute('SELECT * FROM contracts ORDER BY contract_id').fetchall()==right._db.execute('SELECT * FROM contracts ORDER BY contract_id').fetchall()
        self.state_checks+=1
        if journal:
            a=left._db.execute('SELECT * FROM journal ORDER BY sequence')
            b=right._db.execute('SELECT * FROM journal ORDER BY sequence')
            while True:
                ra,rb=a.fetchone(),b.fetchone()
                assert ra==rb
                if ra is None:break
                self.journal_rows_checked+=1
        if export:
            assert canonical(left.export())==canonical(right.export())
            self.export_checks+=1

    def view(self):
        times={}; values={}
        order=PROTOCOL['implementations'] if self.ordinal%2==0 else list(reversed(PROTOCOL['implementations']))
        for name in order:
            start=time.perf_counter(); values[name]=self.stores[name].view('main')
            times[name]={'seconds':time.perf_counter()-start}
        assert canonical(values['reference_owner'])==canonical(values['fast_owner'])
        times['canonical_view_bytes']=len(canonical(values['reference_owner']).encode('ascii'))
        return times

    def cold_open(self,repeats):
        samples=[]
        for repeat in range(repeats):
            sample={}; results={}
            order=PROTOCOL['implementations'] if repeat%2==0 else list(reversed(PROTOCOL['implementations']))
            for name in order:
                cls=Store if name=='reference_owner' else FastStore
                registry=self.factory()
                start=time.perf_counter(); opened=cls.open(self.paths[name],registry)
                sample[name]={'seconds':time.perf_counter()-start}
                results[name]={'head':opened.head,'budget':opened.budget}
                opened.close()
            assert canonical(results['reference_owner'])==canonical(results['fast_owner'])
            samples.append(sample)
        return samples

    def audit(self):
        result={}; outcomes={}
        for name in PROTOCOL['implementations']:
            start=time.perf_counter(); outcomes[name]=self.stores[name].audit()
            result[name]={'seconds':time.perf_counter()-start}
        assert canonical(outcomes['reference_owner'])==canonical(outcomes['fast_owner'])
        result['outcome']=outcomes['reference_owner']
        return result

    def details(self):
        return {'receipt_byte_comparisons':self.receipt_checks,'state_byte_comparisons':self.state_checks,
                'journal_rows_byte_compared':self.journal_rows_checked,'export_api_byte_comparisons':self.export_checks,
                'accepted_commands':self.ordinal,'submit_seconds':dict(self.submit_seconds),
                'database_bytes':{k:p.stat().st_size for k,p in self.paths.items()}}

    def close(self):
        for owner in self.stores.values(): owner.close()


def register_benchmark(directory,width):
    pair=Pair(directory,f'register-{width}',register_registry,'benchmark-register/v1',{'width':width})
    def event(i,measure=True):
        return pair._submit('add',{'index':37*i%width,'amount':1+i%19},measure=measure)
    for i in range(PROTOCOL['register_prefix_commands']): event(i,False)
    samples=[]
    for trial in range(PROTOCOL['register_trials']):
        sums={k:{'seconds':0.} for k in PROTOCOL['implementations']}
        for j in range(PROTOCOL['register_commands_per_trial']):
            i=PROTOCOL['register_prefix_commands']+trial*PROTOCOL['register_commands_per_trial']+j
            timing=event(i)
            for k in sums: sums[k]['seconds']+=timing[k]['seconds']
        pair.state_check()
        samples.append(sums)
    pair.state_check(journal=True,export=True)
    result={'width':width,'commands_per_trial':PROTOCOL['register_commands_per_trial'],
            'samples':samples,'summary':pair_summary(samples),'verification':pair.details()}
    pair.close(); return result


def profiling_append(pair,payload):
    assert pair.stores['reference_owner'].head==pair.stores['fast_owner'].head
    cmd={'id':f'cmd-{pair.ordinal:06d}','contract':'main','op':'record','at':pair.ordinal,
         'expected_head':pair.stores['reference_owner'].head,'payload':payload}
    output={}; receipts={}
    for name in PROTOCOL['implementations']:
        profiler=cProfile.Profile(); profiler.enable()
        receipts[name]=pair.stores[name].submit(cmd)
        profiler.disable(); stats=profiler.getstats()
        functions=[]
        for row in stats:
            code=row.code
            if isinstance(code,str): filename=''; lineno=0; function=code
            else: filename=code.co_filename; lineno=code.co_firstlineno; function=code.co_name
            if filename.startswith(str(ROOT)):filename=str(Path(filename).relative_to(ROOT))
            functions.append({'file':filename,'line':lineno,'function':function,
                              'calls':row.callcount,'recursive_calls':row.reccallcount,
                              'total_seconds':row.totaltime,'inline_seconds':row.inlinetime})
        selected=[r for r in functions if (r['function'] in ['canonical','loads','_check','_clone','checked_clone','dumps','_stored','_text_digest','digest'])]
        output[name]={'selected_functions':selected,
                      'top_cumulative_functions':sorted(functions,key=lambda r:r['total_seconds'],reverse=True)[:20]}
    assert canonical(receipts['reference_owner'])==canonical(receipts['fast_owner'])
    pair.ordinal+=1; pair.receipt_checks+=1; pair.state_check()
    return output


def stream_benchmark(directory,h,prices):
    pair=Pair(directory,f'stream-{h}',stream_registry,'stream-risk/v1',PROTOCOL['stream_config']|{'horizon':h})
    n=0; revisions={}; checkpoints=[]
    def append():
        nonlocal n
        row={'index':n,'event_at':n,'received_at':pair.ordinal,'revision':0,'rate_hex':prices[n].hex()}
        timing=pair._submit('record',row); revisions[n]=0; n+=1; return timing
    def correction(index,early):
        revisions[index]+=1; rev=revisions[index]
        factor=(33/32 if rev%2 else 31/32) if early else 65/64
        row={'index':index,'event_at':index,'received_at':pair.ordinal,'revision':rev,
             'rate_hex':float(prices[index]*factor).hex()}
        return pair._submit('record',row)
    for target in PROTOCOL['stream_neighborhood_starts']:
        while n<target:append()
        pair.state_check(journal=True,export=target==360)
        checkpoint={'source_length':n,'prefix_submit_seconds':dict(pair.submit_seconds),
                    'prefix_verification':pair.details()}
        checkpoint['cold_open_samples']=pair.cold_open(PROTOCOL['cold_open_repetitions'][str(target)])
        checkpoint['cold_open_summary']=pair_summary(checkpoint['cold_open_samples'])
        checkpoint['warm_audit']=pair.audit()
        print(json.dumps({'stage':'stream-checkpoint-open-audit','horizon':h,'source_length':n,
                          'cold_open_summary':checkpoint['cold_open_summary']}),flush=True)
        samples={k:[] for k in PROTOCOL['stream_trial_order']}; views=[]
        for trial in range(PROTOCOL['stream_trials']):
            for kind in PROTOCOL['stream_trial_order']:
                before=n
                if kind=='append': value=append()
                else:
                    index=320 if kind.startswith('early') else n-3
                    corr=correction(index,kind.startswith('early')); add=append()
                    value={k:{'seconds':corr[k]['seconds']+add[k]['seconds'],
                              'correction_seconds':corr[k]['seconds'],'append_seconds':add[k]['seconds']}
                           for k in PROTOCOL['implementations']}
                    value['correction_index']=index
                value['source_length_before']=before; value['source_length_after']=n; value['trial']=trial
                pair.state_check(); samples[kind].append(value)
            views.append(pair.view())
        checkpoint['transition_samples']=samples
        checkpoint['transition_summaries']={k:pair_summary(v) for k,v in samples.items()}
        checkpoint['view_samples']=views; checkpoint['view_summary']=pair_summary(views)
        checkpoint['verification_after']=pair.details(); checkpoints.append(checkpoint)
        print(json.dumps({'stage':'stream-neighborhood','horizon':h,'start':target,
                          'speedups':{k:v['paired_speedup']['median'] for k,v in checkpoint['transition_summaries'].items()}}),flush=True)
    profile_payload={'index':n,'event_at':n,'received_at':pair.ordinal,'revision':0,'rate_hex':prices[n].hex()}
    profile=profiling_append(pair,profile_payload)
    pair.state_check(journal=True)
    result={'horizon':h,'checkpoints':checkpoints,'profiled_append_source_length_before':n,
            'profile':profile,'verification':pair.details()}
    pair.close(); return result


def run():
    for key,value in PROTOCOL['thread_environment'].items():
        if os.environ.get(key)!=value:raise ValueError(f'set {key}={value} before importing NumPy')
    pp=ROOT/'results/fast_owner_benchmark_protocol.json'; ip=ROOT/'results/fast_owner_benchmark_inputs.json'
    assert json.loads(pp.read_text())==PROTOCOL
    data=json.loads(ip.read_text()); assert data==input_data()
    sources=['gabriel_runtime/engine.py','gabriel_runtime/fast_owner.py','gabriel_runtime/canonical.py',
             'gabriel_runtime/stream.py','gabriel_runtime/incremental.py','reproduction/benchmark_fast_owner.py']
    hashes={p:sha(ROOT/p) for p in sources}
    import numpy as np
    cpu_model='unknown'
    for line in Path('/proc/cpuinfo').read_text().splitlines():
        if line.startswith('model name'):cpu_model=line.split(':',1)[1].strip();break
    result={'protocol':PROTOCOL,'protocol_file_sha256':sha(pp),'inputs_file_sha256':sha(ip),
            'source_sha256':hashes,'started_at_utc':datetime.now(timezone.utc).isoformat(),
            'environment':{'python':sys.version,'numpy':np.__version__,'sqlite':sqlite3.sqlite_version,
                           'platform':platform.platform(),'processor':cpu_model,'logical_cpus':os.cpu_count(),
                           'threads':{k:os.environ[k] for k in PROTOCOL['thread_environment']}},
            'register':[],'stream':[]}
    with tempfile.TemporaryDirectory(prefix='gabriel-fast-owner-') as directory:
        warm=Pair(directory,'warmup',register_registry,'benchmark-register/v1',{'width':32})
        for i in range(32):warm._submit('add',{'index':i,'amount':1},measure=False)
        warm.close()
        for width in PROTOCOL['register_widths']:
            result['register'].append(register_benchmark(directory,width))
            print(json.dumps({'stage':'register','width':width,'summary':result['register'][-1]['summary']}),flush=True)
            write(ROOT/'results/fast_owner_benchmark_partial.json',result)
        prices=list(map(float.fromhex,data['price_hex']))
        for h in PROTOCOL['stream_horizons']:
            result['stream'].append(stream_benchmark(directory,h,prices))
            write(ROOT/'results/fast_owner_benchmark_partial.json',result)
    assert {p:sha(ROOT/p) for p in sources}==hashes,'source changed during timing; discard timings'
    result['finished_at_utc']=datetime.now(timezone.utc).isoformat(); result['status']='passed'
    write(ROOT/'results/fast_owner_benchmark.json',result)
    (ROOT/'results/fast_owner_benchmark_partial.json').unlink(missing_ok=True)
    print(json.dumps({'status':'passed','output':'results/fast_owner_benchmark.json'}),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--prepare',action='store_true');parser.add_argument('--run',action='store_true')
    args=parser.parse_args()
    if args.prepare:
        write(ROOT/'results/fast_owner_benchmark_protocol.json',PROTOCOL)
        write(ROOT/'results/fast_owner_benchmark_inputs.json',input_data())
        print('Prepared frozen protocol and exact binary64 input tokens; no timings executed.')
    if args.run:run()
    if not(args.prepare or args.run):parser.error('select --prepare or --run')
