"""Frozen synthetic Engine-window verification cohort and matched timings.

No measurements run without --run.  Snapshot generation is a separate explicit
operation, and the protocol digest is checked before either generation or runs.
"""
from __future__ import annotations

import argparse
from fractions import Fraction as F
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import platform
import statistics
import struct
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
PROTOCOL = ROOT/'results/window_reachability_protocol.json'
PROTOCOL_SHA = 'aa4d41d74c11e7d80654d3df1cbdc1eabbfa249e047e2adae8d384c547a763c2'
METHODS = ('analytic','adaptive','uniform')
PI = F('3.14159265358979323846264338327950288419716939937510')


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def bits(value):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError('finite binary64 required')
    return struct.pack('>d',value).hex()


def protocol():
    if file_hash(PROTOCOL) != PROTOCOL_SHA:
        raise ValueError('frozen window protocol SHA256 mismatch')
    return json.loads(PROTOCOL.read_text())


def source_for(n, seed=None, control=None):
    source = []
    for entity in range(n):
        if control == 'uniform':
            re, im = 1, 0
        elif control == 'zero_sum':
            re, im = (1 if entity == 0 else -1 if entity == 1 else 0), 0
        elif control == 'localized':
            re, im = int(entity == 0), 0
        else:
            raw = hashlib.sha256(f'gabriel-window-source/v1:{seed}:{n}:{entity}'.encode('ascii')).digest()
            re = 3 + int.from_bytes(raw[:8],'big') % 17 - 8
            im = 1 + int.from_bytes(raw[8:16],'big') % 19 - 9
        source.append(dict(entity=entity,re_bits=bits(re),im_bits=bits(im)))
    return source


def inputs_from_snapshots(snapshots):
    from gabriel_runtime.window_certificate import prepare_model
    p = protocol()
    cases = []
    for n,seed,region,q,window in itertools.product(
            p['primary']['nodes'],p['primary']['source_seeds'],range(2),
            p['primary']['threshold_offsets'],range(4)):
        snapshot = snapshots[str(n)]['certificate_snapshot']
        source = source_for(n,seed)
        targets = [i for i in range(n) if (i%2 == 0 if region == 0 else i < n//3)]
        model = prepare_model(snapshot,source,targets)
        if model.omega <= 0:
            raise ValueError('frozen primary expected positive clique frequency')
        threshold = min(F(1),max(F(0),model.a+F(q)*(abs(model.b)+abs(model.c))))
        a,b = map(F,p['primary']['phase_windows'][window])
        cases.append(dict(case_id=f'primary-n{n}-s{seed}-r{region}-q{q}-w{window}',
                          cohort='primary',snapshot_key=str(n),source=source,targets=targets,
                          start_bits=bits(a/model.omega),end_bits=bits(b/model.omega),
                          threshold_bits=bits(threshold)))
    for n,control,offset in itertools.product(p['controls']['nodes'],('uniform','zero_sum'),
                                              p['controls']['threshold_offsets_from_exact_stationary_mass']):
        source = source_for(n,control=control)
        targets = [i for i in range(n) if i%2 == 0]
        model = prepare_model(snapshots[str(n)]['certificate_snapshot'],source,targets)
        stationary = model.a + model.b if model.omega == 0 else model.a
        threshold = min(F(1),max(F(0),stationary+F(offset)))
        # Exact rational equality is retained explicitly in controls.  The
        # general query function accepts canonical numerator/denominator input.
        threshold_wire = (dict(numerator=str(threshold.numerator),denominator=str(threshold.denominator))
                          if offset == '0' else bits(threshold))
        cases.append(dict(case_id=f'control-n{n}-{control}-q{offset}',cohort='control',
                          snapshot_key=str(n),source=source,targets=targets,
                          start_bits=bits(0),end_bits=bits(F(8)/model.omega),threshold_bits=threshold_wire))
    n = p['stress']['nodes']
    source,targets = source_for(n,control='localized'),[1]
    model = prepare_model(snapshots[str(n)]['certificate_snapshot'],source,targets)
    peak = F(4,n*n)
    stress = [
        ('alias',bits(0),bits(510*PI/model.omega),bits(F(3,n*n))),
        ('narrow',bits(0),bits(2*PI/model.omega),bits(peak*(1-F(1,1<<24)))),
        ('exact_global_equality',bits(0),bits(2*PI/model.omega),
         dict(numerator=str(peak.numerator),denominator=str(peak.denominator))),
        ('huge_phase',bits(1e250),bits(math.nextafter(1e250,math.inf)),bits(F(2,n*n))),
    ]
    for label,a,b,threshold in stress:
        cases.append(dict(case_id='stress-'+label,cohort='stress',snapshot_key=str(n),
                          source=source,targets=targets,start_bits=a,end_bits=b,threshold_bits=threshold))
    if sum(c['cohort']=='primary' for c in cases) != p['primary']['expected_cases']:
        raise AssertionError('frozen primary case count mismatch')
    return cases


def generate(args):
    protocol()
    out = Path(args.output)
    out.mkdir(parents=True,exist_ok=False)
    executable = Path(args.executable).resolve(strict=True)
    if file_hash(executable) != args.sha256:
        raise ValueError('explicit native executable SHA256 mismatch')
    sys.path.insert(0,str(ROOT))
    from gabriel_runtime.graph_reachability import laplacian_for_certificate
    snapshots = {}
    for n in protocol()['primary']['nodes']:
        request = dict(schema='gabriel-engine-snapshot/v1',batches=[list(range(n))])
        result = subprocess.run([str(executable)],input=canonical(request).encode('ascii'),
                                stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True,timeout=30)
        response = json.loads(result.stdout)
        if file_hash(executable) != args.sha256:
            raise ValueError('native executable identity changed during generation')
        snapshots[str(n)] = dict(request=request,response=response,
                                stdout=result.stdout.decode('ascii'),stderr=result.stderr.decode('ascii'),
                                certificate_snapshot=laplacian_for_certificate(response))
    payload = dict(schema='gabriel.window-cohort.v1',protocol_sha256=PROTOCOL_SHA,
                   executable_sha256=args.sha256,snapshots=snapshots)
    payload['cases'] = inputs_from_snapshots(snapshots)
    payload['cohort_digest'] = digest(payload)
    (out/'inputs.json').write_text(json.dumps(payload,indent=2)+'\n')
    (out/'frozen_protocol.json').write_bytes(PROTOCOL.read_bytes())
    print(canonical(dict(inputs=str(out/'inputs.json'),cases=len(payload['cases']),cohort_digest=payload['cohort_digest'])))


def load_inputs(path):
    protocol()
    data = json.loads(Path(path).read_text())
    expected = data.pop('cohort_digest')
    if digest(data) != expected or data['protocol_sha256'] != PROTOCOL_SHA:
        raise ValueError('frozen input/protocol identity mismatch')
    data['cohort_digest'] = expected
    return data


def call_method(method,snapshot,case):
    from gabriel_runtime.window_certificate import certify_window
    from window_baselines import certify_by_subdivision
    arguments = (snapshot,case['source'],case['targets'],case['start_bits'],case['end_bits'],case['threshold_bits'])
    if method == 'analytic':
        return certify_window(*arguments,precisions=(128,256,512))
    return certify_by_subdivision(*arguments,method=method,precisions=(128,256,512),max_evaluations=256)


def source_hashes():
    paths = [Path(__file__),ROOT/'reproduction/window_baselines.py',ROOT/'gabriel_runtime/window_certificate.py',PROTOCOL]
    return {str(path.relative_to(ROOT)):file_hash(path) for path in paths}


def evaluate(args):
    if not args.run:
        raise ValueError('evaluation requires explicit --run')
    data = load_inputs(args.inputs)
    before = source_hashes()
    outputs = []
    for case in data['cases']:
        snapshot = data['snapshots'][case['snapshot_key']]['certificate_snapshot']
        for method in METHODS:
            result = call_method(method,snapshot,case)
            outputs.append(dict(case_id=case['case_id'],cohort=case['cohort'],method=method,result=result))
    if source_hashes() != before:
        raise ValueError('measured sources changed during evaluation')
    payload = dict(schema='gabriel.window-evaluation.v1',protocol_sha256=PROTOCOL_SHA,
                   cohort_digest=data['cohort_digest'],source_sha256=before,outputs=outputs)
    Path(args.output).write_text(json.dumps(payload,indent=2)+'\n')
    print(canonical(dict(output=args.output,records=len(outputs))))


def worker(args):
    if not args.run:
        raise ValueError('timing worker requires --run')
    data = load_inputs(args.inputs)
    before = source_hashes()
    primary = [c for c in data['cases'] if c['cohort']=='primary']
    # Import and run a fixed control before timing.  Its output is retained;
    # primary cases are never used for warmup or protocol changes.
    warm = next(c for c in data['cases'] if c['cohort']=='control')
    warmup = {m:call_method(m,data['snapshots'][warm['snapshot_key']]['certificate_snapshot'],warm) for m in METHODS}
    rows = []
    for repeat,order in enumerate(protocol()['timing']['method_orders']):
        for case in primary:
            snapshot = data['snapshots'][case['snapshot_key']]['certificate_snapshot']
            for method in order:
                start = time.perf_counter_ns()
                result = call_method(method,snapshot,case)
                elapsed = time.perf_counter_ns()-start
                rows.append(dict(worker=args.worker,repeat=repeat,case_id=case['case_id'],method=method,
                                 elapsed_ns=elapsed,status=result['status'],result_digest=digest(result),
                                 point_evaluations=result.get('point_evaluations',result.get('resources',{}).get('point_evaluations')),
                                 phase_evaluations=result.get('resources',{}).get('phase_evaluations')))
    if source_hashes() != before:
        raise ValueError('measured sources changed during timing')
    payload = dict(schema='gabriel.window-timing-worker.v1',protocol_sha256=PROTOCOL_SHA,
                   cohort_digest=data['cohort_digest'],source_sha256=before,worker=args.worker,
                   process=dict(pid=os.getpid(),python=sys.version,executable=sys.executable,
                                platform=platform.platform(),processor=platform.processor()),
                   warmup=warmup,rows=rows)
    Path(args.output).write_text(json.dumps(payload,indent=2)+'\n')


def collect(args):
    if not args.run:
        raise ValueError('timing collection requires explicit --run')
    load_inputs(args.inputs)
    out = Path(args.output)
    out.mkdir(parents=True,exist_ok=False)
    before = source_hashes()
    for index in range(protocol()['timing']['fresh_processes']):
        command = [sys.executable,str(Path(__file__)),'worker','--inputs',str(Path(args.inputs).resolve()),
                   '--output',str((out/f'worker_{index}.json').resolve()),'--worker',str(index),'--run']
        (out/f'worker_{index}.command.json').write_text(json.dumps(command,indent=2)+'\n')
        with (out/f'worker_{index}.stdout').open('wb') as stdout,(out/f'worker_{index}.stderr').open('wb') as stderr:
            subprocess.run(command,stdout=stdout,stderr=stderr,check=True)
        if source_hashes() != before:
            raise ValueError('sources changed across timing workers')
    (out/'source_hashes.json').write_text(json.dumps(before,indent=2)+'\n')
    print(canonical(dict(output=str(out),workers=protocol()['timing']['fresh_processes'])))


def report(args):
    protocol()
    evaluation = json.loads(Path(args.evaluation).read_text())
    if evaluation['protocol_sha256'] != PROTOCOL_SHA:
        raise ValueError('evaluation protocol mismatch')
    summary = {}
    expected_results = {}
    for cohort in ('primary','control','stress'):
        summary[cohort] = {}
        for method in METHODS:
            records = [r for r in evaluation['outputs'] if r['cohort']==cohort and r['method']==method]
            statuses = {s:sum(r['result']['status']==s for r in records)
                        for s in ('reachable','excluded','unknown','out_of_scope')}
            summary[cohort][method] = dict(cases=len(records),statuses=statuses,
                                           resolved=statuses['reachable']+statuses['excluded'])
            for record in records:
                expected_results[(record['case_id'],method)] = digest(record['result'])
    total = protocol()['primary']['expected_cases']
    primary = summary['primary']
    if any(v['cases'] != total for v in primary.values()):
        raise ValueError('primary result count mismatch')
    resolution_gate = (F(primary['analytic']['resolved'],total) >= F(19,20)
                       and all(primary['analytic']['resolved'] >= primary[m]['resolved'] for m in METHODS))
    secondary = F(primary['analytic']['resolved']-primary['uniform']['resolved'],total) >= F(1,10)
    workers = []
    if args.timings:
        for path in sorted(Path(args.timings).glob('worker_*.json')):
            if '.command.' in path.name:
                continue
            worker_data = json.loads(path.read_text())
            if (worker_data['protocol_sha256'] != PROTOCOL_SHA or
                    worker_data['cohort_digest'] != evaluation['cohort_digest'] or
                    worker_data['source_sha256'] != evaluation['source_sha256']):
                raise ValueError('timing/evaluation identity mismatch')
            pairs = {}
            for row in worker_data['rows']:
                if row['result_digest'] != expected_results[(row['case_id'],row['method'])]:
                    raise ValueError('timed result differs from captured evaluation')
                pair = pairs.setdefault((row['repeat'],row['case_id']),{})
                if row['method'] in pair:
                    raise ValueError('duplicate timed method')
                pair[row['method']] = row
            if len(pairs) != total*3 or any(set(p) != set(METHODS) for p in pairs.values()):
                raise ValueError('timing comparison is incomplete')
            eligible = [p for p in pairs.values() if p['analytic']['status'] == p['adaptive']['status']
                        and p['analytic']['status'] in ('reachable','excluded')]
            ratios = [p['adaptive']['elapsed_ns']/p['analytic']['elapsed_ns'] for p in eligible]
            workers.append(dict(worker=worker_data['worker'],matched_decisive_pairs=len(ratios),
                                excluded_pairs=len(pairs)-len(ratios),
                                median_paired_adaptive_over_analytic=statistics.median(ratios) if ratios else None))
    timing_gate = None
    if len(workers) == protocol()['timing']['fresh_processes']:
        medians = [w['median_paired_adaptive_over_analytic'] for w in workers]
        timing_gate = bool(all(x is not None for x in medians) and statistics.median(medians)>1
                           and sum(x>1 for x in medians)>=4)
    result = dict(schema='gabriel.window-summary.v1',protocol_sha256=PROTOCOL_SHA,
                  cohort_digest=evaluation['cohort_digest'],cohorts=summary,timing_workers=workers,
                  gates=dict(resolution=resolution_gate,matched_task_timing=timing_gate,
                             independent_zero_false_certificates='requires independent verifier',
                             secondary_uniform_ten_percentage_points=secondary),
                  overall='unassessed until independent certificate verification is incorporated',
                  scope='synthetic graph-model verification; no external predictive or overall-system superiority claim')
    Path(args.output).write_text(json.dumps(result,indent=2)+'\n')
    print(canonical(dict(output=args.output,resolution_gate=resolution_gate,timing_gate=timing_gate)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='operation',required=True)
    gen = sub.add_parser('generate'); gen.add_argument('--executable',required=True);gen.add_argument('--sha256',required=True);gen.add_argument('--output',required=True)
    for name in ('evaluate','collect','worker'):
        command = sub.add_parser(name)
        command.add_argument('--inputs',required=True);command.add_argument('--output',required=True)
        command.add_argument('--run',action='store_true')
        if name == 'worker': command.add_argument('--worker',type=int,required=True)
    command = sub.add_parser('report')
    command.add_argument('--evaluation',required=True);command.add_argument('--timings')
    command.add_argument('--output',required=True)
    args = parser.parse_args()
    {'generate':generate,'evaluate':evaluate,'collect':collect,'worker':worker,'report':report}[args.operation](args)


if __name__ == '__main__':
    main()
