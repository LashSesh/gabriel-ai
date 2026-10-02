"""Frozen synthetic efficiency protocol for equivalent stream implementations.

Prepare first: python reproduction/benchmark_incremental.py --prepare
Run with exclusive access to one execution environment:
  OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
    python reproduction/benchmark_incremental.py --run
No market observations are read. Cache snapshots are prepared outside timing.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import sys
import tempfile
import time
import types
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
from gabriel_runtime.canonical import canonical, digest
from gabriel_runtime.stream import StreamRiskAdapter, MAX_ISSUES
from gabriel_runtime.engine import Store

PROTOCOL = {
    'format': 'gabriel-incremental-benchmark/v1',
    'status': 'frozen_before_timing', 'protocol_revision': 2, 'seed': 2026092602,
    'source_kind': 'synthetic_positive_prices',
    'source_formula': 'r_i = 0.006 * (1 + 0.3*sin(i/31)) * Z_i; p_i = 100*exp(cumsum(r)_i), Z from NumPy default_rng(seed).standard_normal(801); first 800 form full trajectory',
    'horizons': [1, 5], 'source_lengths': [360, 500, 800], 'trajectory_length': 800,
    'complete_trajectory_repeats': 1,
    'terminal_transition_repeats': 3,
    'terminal_transitions': ['append', 'early_correction', 'recent_correction', 'early_correction_then_append', 'recent_correction_then_append'],
    'correction_indexes': {'early_correction': '320', 'recent_correction': 'source_length-3'},
    'amendment_before_any_timing': 'add paired correction-then-append to include deferred variance repair work; choose early index320 so both endpoint-dependent issued feedback contributions mature for all lengths',
    'correction_factors': {'early_correction': '33/32', 'recent_correction': '65/64'},
    'owner_source_length': 360, 'owner_repeats': 3,
    'owner_conditions': 'append, then fresh cold-profile Store.open including complete semantic audit',
    'config': {'source_id': 'efficiency-synthetic', 'risk_budget': '10', 'unit_exposure': '100', 'max_units': 100},
    'clocks': 'event=index; received=owner=index for initial source; corrections at source_length+1',
    'repeat_order': 'baseline then incremental at even trial index; reverse at odd trial index',
    'correctness': 'byte-exact canonical state/result digests at every initial source transition and each measured branch',
    'kernel_time': 'wall time inside _learner plus _forecast, including their own construction/digests; excludes outer apply validation, state cloning and result canonicalization',
    'adapter_time': 'complete apply including validation, cloning and full canonical result materialization',
    'owner_time': 'Store.submit terminal append including serialization, hashing and durable SQLite commit; fresh audit measured separately',
    'preparation_exclusions': 'imports, fixed numerical warmup, prefix state construction for terminal trials, adapter/cache snapshots, source/state digest comparison, filesystem copy',
    'warmup': 'one baseline 320-observation trajectory before recorded work; optimized terminal caches derive from completed sequential prefix, cold audits use fresh adapter',
    'work_counters': {
        'variance_steps': 'initial variance-mean calculation counts one; each later EWMA row counts one (both two-scale components together)',
        'forecast_scenario_rows': 'one quantile/ES evaluation row per expert; each row contains 250 scenarios',
        'gradient_evaluations': 'one eight-expert transformed gradient at immutable issued weights',
        'projections': 'one eight-dimensional simplex projection',
        'severity_steps': 'one feedback step updating both severity filters'},
    'thread_environment': {'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1'},
    'scope': 'bounded synthetic reference profile, 1024 source and 512 issue caps; not predictive performance or production throughput',
    'materialization_limit': 'full history retained in canonical state/result, so outer operations retain linear serialization work and semantic audit replays the journal'
}


def write(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False)+'\n')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inputs():
    rng = np.random.default_rng(PROTOCOL['seed'])
    i = np.arange(801, dtype=float)
    returns = .006*(1+.3*np.sin(i/31))*rng.standard_normal(801)
    rates = 100*np.exp(np.cumsum(returns))
    assert np.isfinite(rates).all() and np.all(rates > 0)
    return {'protocol_digest': digest(PROTOCOL), 'rate_hex': [float(x).hex() for x in rates]}


def cfg(h):
    return PROTOCOL['config'] | {'horizon': h}


def payload(index, rate, revision=0, receipt=None):
    return {'index': index, 'event_at': index, 'received_at': index if receipt is None else receipt,
            'revision': revision, 'rate_hex': float(rate).hex()}


class TimingMixin:
    def __init__(self):
        super().__init__()
        self._kernel_seconds = 0.

    def _learner(self, *args, **kwargs):
        start = time.perf_counter()
        try:
            return super()._learner(*args, **kwargs)
        finally:
            self._kernel_seconds += time.perf_counter()-start

    def _forecast(self, *args, **kwargs):
        start = time.perf_counter()
        try:
            return super()._forecast(*args, **kwargs)
        finally:
            self._kernel_seconds += time.perf_counter()-start

    def reset_measurement(self):
        self._kernel_seconds = 0.
        self.reset_metrics()


class CountedReference(StreamRiskAdapter):
    """Counter formulas for the unchanged full replay, not an optimization."""
    def __init__(self):
        super().__init__()
        self.reset_metrics()

    def reset_metrics(self):
        self._metrics = dict.fromkeys(['variance_steps', 'forecast_scenario_rows',
                                      'gradient_evaluations', 'projections', 'severity_steps'], 0)

    def metrics(self):
        return self._metrics.copy()

    def _learner(self, state, latest):
        count = sum(issue['forecast_id'] in state['maturity'] for issue in state['issued'])
        for name in ['gradient_evaluations', 'projections', 'severity_steps']:
            self._metrics[name] += count
        return super()._learner(state, latest)

    def _forecast(self, state, latest, learner, owner_at):
        first = 60+state['config']['horizon']+250-1
        if len(latest)-1 >= first and len(state['issued']) < MAX_ISSUES:
            self._metrics['variance_steps'] += 2*(len(latest)-60)
            self._metrics['forecast_scenario_rows'] += 6*(len(latest)-first)
        return super()._forecast(state, latest, learner, owner_at)


class TimedReference(TimingMixin, CountedReference):
    pass


def snapshot(adapter):
    # Share imported modules but clone caches, arrays, counters and owner cycles.
    memo = {id(value): value for value in vars(adapter).values()
            if isinstance(value, types.ModuleType)}
    clone = object.__new__(type(adapter))
    memo[id(adapter)] = clone
    if not isinstance(adapter.ecb, types.ModuleType):
        # The private forwarding proxy is constructed explicitly because its
        # __getattr__ expects initialized fields during generic deepcopy.
        proxy = object.__new__(type(adapter.ecb))
        proxy.owner, proxy.reference = clone, adapter._ecb_reference
        memo[id(adapter.ecb)] = proxy
    clone.__dict__.update(copy.deepcopy(vars(adapter), memo))
    return clone


def measure(adapter, state, row):
    adapter.reset_measurement()
    start = time.perf_counter()
    output = adapter.apply(state, 'record', row, row['received_at'])
    elapsed = time.perf_counter()-start
    return output, {'adapter_seconds': elapsed, 'kernel_seconds': adapter._kernel_seconds,
                    'work': adapter.metrics()}


def summary(values):
    return {'median': statistics.median(values), 'min': min(values), 'max': max(values),
            'samples': values}


def summarize_pair(samples, key):
    left = [sample['baseline'][key] for sample in samples]
    right = [sample['incremental'][key] for sample in samples]
    return {'baseline': summary(left), 'incremental': summary(right),
            'paired_speedup': summary([a/b for a,b in zip(left,right)])}


def run():
    from gabriel_runtime.incremental import IncrementalStreamRiskAdapter
    class TimedIncremental(TimingMixin, IncrementalStreamRiskAdapter):
        pass
    for key, value in PROTOCOL['thread_environment'].items():
        if os.environ.get(key) != value:
            raise ValueError(f'set {key}={value} before importing NumPy')
    protocol_path = ROOT/'results/incremental_benchmark_protocol.json'
    input_path = ROOT/'results/incremental_benchmark_inputs.json'
    assert json.loads(protocol_path.read_text()) == PROTOCOL
    data = json.loads(input_path.read_text())
    assert data == inputs()
    rates = list(map(float.fromhex, data['rate_hex']))
    classes = {'baseline': TimedReference, 'incremental': TimedIncremental}
    started = datetime.now(timezone.utc).isoformat()
    warm = TimedReference(); warm_state = warm.initialize(cfg(1))
    for i in range(320):
        row = payload(i, rates[i]); warm_state, _ = warm.apply(warm_state, 'record', row, i)
    del warm, warm_state
    trajectories = []; checkpoints = {}; terminal = []
    for h in PROTOCOL['horizons']:
        expected = None
        for label, cls in classes.items():
            adapter = cls(); state = adapter.initialize(cfg(h)); cumulative = 0.; kernel = 0.
            hashes = []; work = {}; checkpoint_rows = []
            for i, rate in enumerate(rates[:PROTOCOL['trajectory_length']]):
                # Snapshot before n-th append; this work is outside all timers.
                n = i+1
                if n in PROTOCOL['source_lengths']:
                    checkpoints[h,label,n,'append'] = (snapshot(adapter), copy.deepcopy(state))
                (state, result), timing = measure(adapter, state, payload(i, rate))
                cumulative += timing['adapter_seconds']; kernel += timing['kernel_seconds']
                for key, value in timing['work'].items(): work[key] = work.get(key, 0)+value
                hashes.append(digest({'state': state, 'result': result}))
                if expected is not None:
                    assert hashes[-1] == expected[i], ('sequential equivalence',h,i)
                if n in PROTOCOL['source_lengths']:
                    checkpoints[h,label,n,'correction'] = (snapshot(adapter), copy.deepcopy(state))
                    checkpoint_rows.append({'source_length': n, 'adapter_seconds': cumulative,
                                            'kernel_seconds': kernel, 'work': work.copy(),
                                            'issued_count': len(state['issued']), 'state_digest': digest(state)})
            if expected is None: expected = hashes
            trajectories.append({'horizon': h, 'implementation': label, 'checkpoints': checkpoint_rows,
                                 'transition_output_digests': hashes,
                                 'all_transitions': len(hashes), 'final_state_digest': digest(state)})
            print(json.dumps({'stage': 'trajectory', 'horizon': h, 'implementation': label,
                              'seconds': cumulative}), flush=True)
        for n in PROTOCOL['source_lengths']:
            for kind in PROTOCOL['terminal_transitions']:
                if kind == 'append':
                    row = payload(n-1, rates[n-1]); checkpoint_kind = 'append'
                else:
                    index = 320 if kind.startswith('early_correction') else n-3
                    factor = 33/32 if kind.startswith('early_correction') else 65/64
                    row = payload(index, rates[index]*factor, 1, n+1); checkpoint_kind = 'correction'
                rows = [row]
                if kind.endswith('_then_append'):
                    rows.append(payload(n, rates[n], receipt=n+2))
                samples = []; output_digest = None
                for trial in range(PROTOCOL['terminal_transition_repeats']):
                    order = ['baseline','incremental'] if trial % 2 == 0 else ['incremental','baseline']
                    sample = {}
                    for label in order:
                        prepared, state = checkpoints[h,label,n,checkpoint_kind]
                        adapter = snapshot(prepared)
                        step_state = state; step_outputs = []; step_timings = []
                        for step_row in rows:
                            output, timing = measure(adapter, step_state, step_row)
                            step_state = output[0]
                            step_outputs.append(digest({'state': output[0], 'result': output[1]}))
                            step_timings.append(timing)
                        timing = {'adapter_seconds': sum(t['adapter_seconds'] for t in step_timings),
                                  'kernel_seconds': sum(t['kernel_seconds'] for t in step_timings),
                                  'work': {key: sum(t['work'].get(key,0) for t in step_timings)
                                           for key in step_timings[0]['work']},
                                  'steps': step_timings}
                        current_digest = digest(step_outputs)
                        if output_digest is None: output_digest = current_digest
                        assert output_digest == current_digest, ('terminal equivalence',h,n,kind,trial,label)
                        sample[label] = timing
                    samples.append(sample)
                terminal.append({'horizon': h, 'source_length': n, 'transition': kind,
                                 'payloads': rows, 'output_digest': output_digest,
                                 'adapter_time': summarize_pair(samples,'adapter_seconds'),
                                 'kernel_time': summarize_pair(samples,'kernel_seconds'),
                                 'work': {label: samples[0][label]['work'] for label in classes},
                                 'repeats': samples})
        # Release trajectory checkpoint states once their transition tests finish.
        checkpoints = {key:value for key,value in checkpoints.items() if key[0] != h}
    owners = []
    with tempfile.TemporaryDirectory(prefix='gabriel-incremental-benchmark-') as temp:
        temp = Path(temp); n = PROTOCOL['owner_source_length']
        for h in PROTOCOL['horizons']:
            paths = {}; expected_view = None
            for label, cls in classes.items():
                path = temp/f'{label}-{h}.sqlite'; adapter = cls()
                with Store.create(path, {'stream-risk/v1': adapter}) as store:
                    def submit(row=None):
                        op = 'bind' if row is None else 'record'
                        at = 0 if row is None else row['received_at']
                        p = {'adapter':'stream-risk/v1','config':cfg(h)} if row is None else row
                        return store.submit({'id':'bind' if row is None else 'i'+str(row['index']),
                                             'contract':'stream','op':op,'at':at,
                                             'expected_head':store.head,'payload':p})
                    submit()
                    for i in range(n-1): submit(payload(i,rates[i]))
                paths[label] = path
            trials=[]
            for trial in range(PROTOCOL['owner_repeats']):
                sample={}; order=['baseline','incremental'] if trial%2==0 else ['incremental','baseline']
                for label in order:
                    path=temp/f'trial-{label}-{h}-{trial}.sqlite'; path.write_bytes(paths[label].read_bytes())
                    adapter=classes[label]()
                    # Opening performs a complete untimed replay and warms this adapter.
                    with Store.open(path, {'stream-risk/v1':adapter}) as store:
                        row=payload(n-1,rates[n-1])
                        command={'id':'i'+str(n-1),'contract':'stream','op':'record','at':n-1,
                                 'expected_head':store.head,'payload':row}
                        adapter.reset_measurement(); start=time.perf_counter()
                        receipt=store.submit(command); owner_seconds=time.perf_counter()-start
                        result_digest=digest(receipt['result'])
                        anchor={'head':store.head,'events':store.budget['events']}
                        view_digest=digest(store.view('stream'))
                        if expected_view is None: expected_view=view_digest
                        assert view_digest==expected_view, ('owner semantic view',h,label)
                    cold=classes[label](); cold.reset_measurement(); start=time.perf_counter()
                    with Store.open(path, {'stream-risk/v1':cold}, expected_head=anchor['head'],
                                    expected_events=anchor['events']) as store:
                        audit_seconds=time.perf_counter()-start
                        audited_view=digest(store.view('stream'))
                        assert audited_view==view_digest
                    sample[label]={'owner_seconds':owner_seconds,'audit_seconds':audit_seconds,
                                   'result_digest':result_digest, 'view_digest':view_digest,
                                   'database_bytes':path.stat().st_size,'events':anchor['events']}
                assert sample['baseline']['result_digest']==sample['incremental']['result_digest']
                trials.append(sample)
            owners.append({'horizon':h,'source_length':n,'terminal_transaction_time':summarize_pair(trials,'owner_seconds'),
                           'fresh_semantic_open_time':summarize_pair(trials,'audit_seconds'),'trials':trials})
            print(json.dumps({'stage':'owner','horizon':h,'status':'passed'}),flush=True)
    files=['gabriel_runtime/stream.py','gabriel_runtime/incremental.py','gabriel_runtime/engine.py',
           'gabriel_runtime/canonical.py','reproduction/ecb_risk.py','reproduction/aggregate_risk.py',
           'reproduction/severity_risk.py','reproduction/benchmark_incremental.py']
    import scipy
    cpuinfo=Path('/proc/cpuinfo').read_text() if Path('/proc/cpuinfo').exists() else ''
    models=[line.split(':',1)[1].strip() for line in cpuinfo.splitlines() if line.startswith('model name')]
    output={'status':'passed','started_utc':started,'finished_utc':datetime.now(timezone.utc).isoformat(),
            'protocol_sha256':sha(protocol_path),'input_sha256':sha(input_path),
            'source_sha256':{name:sha(ROOT/name) for name in files},
            'environment':{'python':platform.python_version(),'numpy':np.__version__,'scipy':scipy.__version__,
                           'platform':platform.platform(),'cpu_model':models[0] if models else platform.processor(),
                           'logical_cpus':os.cpu_count(),'thread_environment':{key:os.environ[key] for key in PROTOCOL['thread_environment']}},
            'trajectories':trajectories,'terminal_transitions':terminal,'owner_transactions':owners,
            'verified_sequential_pairs':1600,'verified_terminal_pairs':90,'verified_owner_pairs':6,
            'limitations':['three local timing repeats are not a portable throughput guarantee or a timing confidence interval',
                           'single complete-trajectory execution per implementation and horizon is descriptive',
                           'kernel bracket includes kernel-owned materialization and output digest work',
                           'canonical state and complete feedback output retain linear history materialization',
                           'synthetic source chosen before timing; no forecast accuracy or market-performance claim']}
    write(ROOT/'results/incremental_benchmark.json',output)
    print(json.dumps({'status':'passed','output':'results/incremental_benchmark.json'}),flush=True)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(); group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--prepare',action='store_true'); group.add_argument('--run',action='store_true')
    args=parser.parse_args()
    if args.prepare:
        for name,value in [('incremental_benchmark_protocol.json',PROTOCOL),('incremental_benchmark_inputs.json',inputs())]:
            path=ROOT/'results'/name
            if path.exists() and json.loads(path.read_text()) != value:
                raise ValueError('refuse to overwrite a differing frozen protocol or input')
            write(path,value)
        print(json.dumps({'status':'prepared','protocol_digest':digest(PROTOCOL)}))
    else: run()
