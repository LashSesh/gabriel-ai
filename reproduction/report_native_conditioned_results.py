#!/usr/bin/env python3
"""Independently verify recorded conditioned-state queries and regenerate tables.

Does not import/run the timing wrapper, compile Rust, or create new timings.
SciPy matrix exponentials independently check all first-process stored states.
"""
from pathlib import Path
import argparse
import hashlib
import json
import math
import statistics
import struct
import zipfile
import numpy as np
import scipy
from scipy.linalg import expm

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / 'native_pse'
BENCH = NATIVE / 'benchmark-results/conditioned_walk'

def require(test, message):
    if not test:
        raise RuntimeError(message)

def digest(raw):
    return hashlib.sha256(raw).hexdigest()

def read(path):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'Duplicate JSON key: ' + key)
            result[key] = value
        return result
    return json.loads(path.read_text(), object_pairs_hook=pairs,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))

def close(a, b, tol=2e-13):
    require(math.isfinite(a) and math.isfinite(b) and
            abs(a-b) <= tol * max(1., abs(a), abs(b)), f'Numeric mismatch {a} != {b}')

def reconstruct(case):
    n, w = case['n'], case['weight']
    adjacency = []
    degrees = [0.]*n
    for i in range(n):
        for j in range(n):
            if i == j or case['family'] == 'path' and abs(i-j) != 1:
                continue
            value = 2*w if case['family'] == 'near_clique' and {i,j} == {0,1} else w
            adjacency.append((i,j,value))
            degrees[i] += value
    values = [[float((17*i+3)%29-14), float((11*i+5)%23-11)] for i in range(n)]
    norm = math.sqrt(sum(a*a+b*b for a,b in values))
    values = [[a/norm,b/norm] for a,b in values]
    fnv = 0xcbf29ce484222325
    def absorb(word):
        nonlocal fnv
        for b in struct.pack('<Q', word):
            fnv = ((fnv ^ b)*0x100000001b3) & ((1<<64)-1)
    def bits(x): return struct.unpack('<Q', struct.pack('<d',x))[0]
    absorb(n)
    for d in degrees: absorb(bits(d))
    for i,j,w in adjacency:
        absorb(i); absorb(j); absorb(bits(w))
    for a,b in values: absorb(bits(a)); absorb(bits(b))
    L = np.diag(degrees)
    for i,j,w in adjacency: L[i,j] -= w
    return L, np.array([complex(a,b) for a,b in values]), f'fnv1a64:{fnv:016x}', len(adjacency)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executed', type=Path, default=BENCH/'executed')
    parser.add_argument('--output-dir', type=Path, default=ROOT/'results')
    args = parser.parse_args()
    executed = args.executed
    protocol = read(BENCH/'protocol.json')
    require(protocol['fresh_processes']==7 and protocol['batches_per_process']==5, 'Unexpected sampling')
    require(len(protocol['cases'])==11 and len(protocol['times'])==16, 'Unexpected workload')
    before, after = (read(executed/name) for name in ['source_hashes_before.json','source_hashes_after.json'])
    require(before == after, 'Measured sources changed')
    current_matches = all((NATIVE/rel).is_file() and
                          digest((NATIVE/rel).read_bytes()) == expected
                          for rel, expected in before.items())
    historical_snapshot_verified = False
    if not current_matches:
        # Engine integration is an additive later source revision. Attribute
        # these older measurements only to the exact retained source snapshot.
        snapshot = ROOT/'audit/native_conditioned_measured_sources.zip'
        require(snapshot.is_file(), 'Current sources differ and measured snapshot is absent')
        with zipfile.ZipFile(snapshot) as archive:
            require(len(archive.namelist()) == len(before) and
                    set(archive.namelist()) == set(before), 'Measured snapshot inventory differs')
            for rel, expected in before.items():
                require(digest(archive.read(rel)) == expected, 'Measured snapshot differs: '+rel)
        historical_snapshot_verified = True
    for name in ['Cargo.toml','Cargo.lock','protocol.json','reproduce.py','README.md']:
        require((executed/('frozen_'+name)).read_bytes()==(BENCH/name).read_bytes(), 'Frozen '+name)
    require((executed/'frozen_main.rs').read_bytes()==(BENCH/'src/main.rs').read_bytes(), 'Frozen harness')
    aggregate = read(executed/'commands.json')
    names = ['compiler','cargo']
    if (executed/'generate_lockfile.command.json').exists():
        names.append('generate_lockfile')
    names += ['build']+[f'process_{i}' for i in range(7)]
    require({p.name for p in executed.glob('*.command.json')}=={n+'.command.json' for n in names}, 'Unexpected individual command inventory')
    commands = [read(executed/(name+'.command.json')) for name in names]
    require(len(aggregate) in [len(commands)-1,len(commands)] and aggregate==commands[:len(aggregate)],
            'Aggregate differs beyond the observed missing-final-index condition')
    command_index = {'original_aggregate_records':len(aggregate),'original_individual_records':len(commands),
                     'aggregate_complete':aggregate==commands,'aggregate_is_exact_prefix':True,
                     'aggregate_sha256':digest((executed/'commands.json').read_bytes()),
                     'cause_of_missing_final_aggregate_entry':'Undetermined' if aggregate!=commands else None,
                     'original_aggregate_modified':False}
    for command in commands:
        require(command['returncode']==0 and command['failure'] is None, 'Unsuccessful captured command')
        name = Path(command['stdout']).name.removesuffix('.stdout')
        require(read(executed/(name+'.command.json'))==command, 'Command record/index disagreement')
        for stream in ['stdout','stderr']:
            raw = (executed/command[stream]).read_bytes()
            require(len(raw)==command[stream+'_bytes'] and digest(raw)==command[stream+'_sha256'], 'Capture hash differs')
    expected_names = {'compiler','cargo','build'}|{f'process_{i}' for i in range(7)}
    actual_names = {Path(c['stdout']).name.removesuffix('.stdout') for c in commands}
    require(actual_names in [expected_names, expected_names|{'generate_lockfile'}], 'Unexpected command inventory')
    integrity = read(executed/'integrity.json')
    require(integrity['captured_command_count']==len(commands), 'Wrapper and original command counts differ')
    require(all(integrity[k] is True for k in ['complete','sources_unchanged','executable_unchanged','all_captured_streams_verified']), 'Incomplete run')
    binary = read(executed/'binary.json'); bp = executed/binary['relative_path']
    binary_present = bp.is_file()
    if binary_present:
        require(bp.stat().st_size==binary['bytes'] and digest(bp.read_bytes())==binary['sha256'], 'Binary differs')
    runs = [read(executed/f'process_{i}.stdout') for i in range(7)]
    require(len({run['pid'] for run in runs})==7, 'Not seven fresh processes')
    oracle_max = 0.; max_component = 0.; max_norm = 0.; component_count = 0; queries_count = 0
    oracle_states = 0
    for index, run in enumerate(runs):
        require(run['schema']=='gabriel.conditioned-walk.measurements.v1' and run['process_index']==index, 'Run identity')
        require(run['protocol']==protocol and len(run['cases'])==11, 'Embedded protocol/cases')
        for ci, (row, case) in enumerate(zip(run['cases'],protocol['cases'])):
            require(row['case']==case and row['auto_backend']==case['expected_auto'] and row['spectral_backend']=='spectral', 'Dispatch/case mismatch')
            L, initial, fingerprint, edges = reconstruct(case)
            require(row['input_fingerprint']==fingerprint and row['directed_adjacency_entries']==edges, 'Reconstructed input differs')
            norm0 = sum(float(z.real)*float(z.real)+float(z.imag)*float(z.imag) for z in initial)
            close(row['initial_norm_squared'],norm0)
            validation = row['validation']; local_max = 0.; local_fraction = 0.; local_norm = 0.
            frames = validation['states']
            require(len(frames)==16, 'Missing time queries')
            for t, frame in zip(protocol['times'],frames):
                require(frame['time']==t, 'Time grid differs')
                s, a = np.asarray(frame['spectral']),np.asarray(frame['auto'])
                require(s.shape==a.shape==(case['n'],2) and np.isfinite(s).all() and np.isfinite(a).all(), 'Malformed state')
                diff = np.abs(s-a)
                allowance = protocol['component_absolute_tolerance']+protocol['component_relative_tolerance']*np.maximum(abs(s),abs(a))
                require((diff<=allowance).all(), 'Component bound violated')
                local_max=max(local_max,float(diff.max())); local_fraction=max(local_fraction,float((diff/allowance).max()))
                close(frame['max_component_difference'],float(diff.max()))
                component_count += s.size
                for tag, data in [('spectral',s),('auto',a)]:
                    norm = sum(float(x)*float(x)+float(y)*float(y) for x,y in data)
                    close(frame[tag+'_norm_squared'],norm)
                    err=abs(norm-norm0); local_norm=max(local_norm,err)
                    require(err<=protocol['norm_absolute_tolerance'], 'Norm bound violated')
                if index==0:
                    ref = expm(-1j*t*L)@initial
                    for data in [s,a]:
                        output=data[:,0]+1j*data[:,1]
                        err=float(np.max(np.abs(output-ref)))
                        oracle_max=max(oracle_max,err)
                        require(err<=2e-9, 'Independent SciPy oracle exceeds 2e-9 absolute component modulus')
                    oracle_states += 1
            require(validation['checked_real_components']==case['n']*32, 'Component count')
            close(validation['max_component_difference'],local_max)
            close(validation['max_component_tolerance_fraction'],local_fraction)
            close(validation['max_norm_error'],local_norm)
            max_component=max(max_component,local_max);max_norm=max(max_norm,local_norm)
            expected_checksums={}
            for tag in ['spectral','auto']:
                result=0.
                for q in range(case['queries_per_batch']):
                    re,im=frames[q%16][tag][q%case['n']]
                    result += re+0.5*im
                expected_checksums[tag]=result
            for phase in ['plan_setup','state_preparation','query_measurements']:
                require(len(row[phase])==5, 'Missing phase pairs')
                for bi,sample in enumerate(row[phase]):
                    require(sample['batch']==bi and sample['spectral_first']==((index+ci+bi)%2==0), 'Order mismatch')
                    for key in ['spectral_ns','auto_ns']:
                        require(type(sample[key]) is int and sample[key]>0, 'Invalid timing')
                    if phase=='query_measurements':
                        require(sample['queries']==case['queries_per_batch'], 'Query count')
                        queries_count += sample['queries']
                        for tag in ['spectral','auto']:
                            close(sample[tag+'_checksum'],expected_checksums[tag],2e-12)
    archived = read(executed/'summary.json')
    rows=[]
    for ci,case in enumerate(protocol['cases']):
        phases={}
        for phase in ['plan_setup','state_preparation','query_measurements']:
            processes=[]
            for i,run in enumerate(runs):
                samples=run['cases'][ci][phase]
                processes.append({'process_index':i,
                    'median_paired_spectral_over_auto':statistics.median(s['spectral_ns']/s['auto_ns'] for s in samples),
                    'median_spectral_ns':statistics.median(s['spectral_ns'] for s in samples),
                    'median_auto_ns':statistics.median(s['auto_ns'] for s in samples)})
            ratios=[p['median_paired_spectral_over_auto'] for p in processes]
            divisor=case['queries_per_batch'] if phase=='query_measurements' else 1
            phases[phase]={'processes':processes,'median_process_paired_ratio':statistics.median(ratios),
                          'minimum_process_paired_ratio':min(ratios),'maximum_process_paired_ratio':max(ratios),
                          'median_process_spectral_ns_per_operation':statistics.median(p['median_spectral_ns']/divisor for p in processes),
                          'median_process_auto_ns_per_operation':statistics.median(p['median_auto_ns']/divisor for p in processes)}
        row={'case':case,'input_fingerprint':runs[0]['cases'][ci]['input_fingerprint'],'phases':phases,
             'max_component_difference':max(run['cases'][ci]['validation']['max_component_difference'] for run in runs),
             'max_norm_error':max(run['cases'][ci]['validation']['max_norm_error'] for run in runs)}
        require(row==archived['cases'][ci], 'Independently recomputed summary differs')
        rows.append(row)
    require(archived['total_timed_queries_per_backend']==queries_count and archived['total_real_component_pairs_checked']==component_count,'Summary counts differ')
    evidence={'schema':1,'commands_verified':len(commands),'capture_streams_verified':2*len(commands),
              'command_index_provenance':command_index,
              'current_and_measured_source_hashes_match':current_matches,
              'historical_measured_sources_verified_in_snapshot':historical_snapshot_verified,
              'source_files':len(before),'binary_present_and_reverified':binary_present,
              'processes':7,'cases_per_process':11,'paired_batches_per_phase':385,'component_pairs_checked':component_count,
              'timed_queries_per_backend':queries_count,'timed_queries_total':2*queries_count,
              'max_auto_vs_spectral_real_component_difference':max_component,'max_norm_squared_error':max_norm,
              'scipy_reference_states':oracle_states,'scipy_max_complex_component_error':oracle_max,
              'scipy_acceptance_tolerance':2e-9,'scipy_version':scipy.__version__,'numpy_version':np.__version__,
              'every_timed_checksum_recomputed_from_saved_full_states':True,'no_new_timings_generated':True}
    lines=[r'\begin{table}[H]\centering\small',
           r'\caption{Conditioned full-state queries. Median Spectral/Auto elapsed-time ratios and observed ranges of seven process medians, each based on five alternating pairs. Setup and source preparation are timed separately. One in sixteen queries is at zero time. These are synthetic API measurements, not whole-engine gains.}',
           r'\label{tab:conditionedwalk}',
           r'\resizebox{\textwidth}{!}{\begin{tabular}{lrrrr}\toprule',
           r'Graph & $n$ & Setup ratio & Prepare ratio & Query ratio [range]\\\midrule']
    for row in rows:
        case=row['case'];ph=row['phases'];q=ph['query_measurements']
        name={'clique':'Clique','near_clique':'Near-clique','path':'Path'}[case['family']]
        if case['weight']==1.7:name+=' (guard)'
        elif case['weight']==1.:name+=' ($w=1$)'
        lines.append(r'%s & %d & %.2f & %.2f & $%.2f\,[%.2f,\,%.2f]$ \\'%(name,case['n'],ph['plan_setup']['median_process_paired_ratio'],ph['state_preparation']['median_process_paired_ratio'],q['median_process_paired_ratio'],q['minimum_process_paired_ratio'],q['maximum_process_paired_ratio']))
    lines.extend([r'\bottomrule\end{tabular}}',r'\end{table}'])
    args.output_dir.mkdir(parents=True,exist_ok=True)
    derived=[{'source_file':name+'.command.json','source_sha256':digest((executed/(name+'.command.json')).read_bytes()),'record':command}
             for name,command in zip(names,commands)]
    (args.output_dir/'native_conditioned_commands_derived.json').write_text(json.dumps({'status':'Derived index from retained original individual records; no inferred measurements', 'provenance':command_index,'records':derived},indent=2)+'\n')
    (args.output_dir/'native_conditioned_checks.json').write_text(json.dumps(evidence,indent=2)+'\n')
    (args.output_dir/'native_conditioned_summary.json').write_text(json.dumps({'evidence':evidence,'cases':rows},indent=2)+'\n')
    (args.output_dir/'native_conditioned_tables.tex').write_text('\n'.join(lines)+'\n')
    print(json.dumps(evidence,indent=2))

if __name__=='__main__':
    main()
