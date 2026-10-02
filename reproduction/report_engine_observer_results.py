#!/usr/bin/env python3
"""Independently audit captured Engine-to-observer tasks and recreate tables.

This reader imports neither the benchmark harness nor its runner. Input graphs,
vertex identities, initial conditions and matrix-exponential references are
reconstructed here. It never creates fresh timing measurements.
"""
from pathlib import Path
import argparse
import hashlib
import json
import math
import re
import statistics
import struct
import numpy as np
import scipy
from scipy.linalg import expm

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / 'native_pse'
BENCH = NATIVE / 'benchmark-results/conditioned_engine'


def require(value, message):
    if not value:
        raise RuntimeError(message)


def read(path):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'Duplicate JSON key: ' + key)
            result[key] = value
        return result
    return json.loads(path.read_text(), object_pairs_hook=pairs,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def close(a, b, tolerance=2e-13):
    require(math.isfinite(a) and math.isfinite(b) and
            abs(a-b) <= tolerance * max(1., abs(a), abs(b)),
            f'Numeric mismatch {a} != {b}')


def vertex_id(source):
    value = 0xcbf29ce484222325
    for byte in source.encode('utf-8'):
        value = ((value ^ byte) * 0x100000001b3) & ((1 << 64)-1)
    return value


def state_array(values, n):
    result = np.asarray(values, dtype=float)
    require(result.shape == (n, 2) and np.isfinite(result).all(), 'Invalid complex state')
    return result[:, 0] + 1j * result[:, 1]


def norm_squared(values):
    return sum(float(x.real)*float(x.real)+float(x.imag)*float(x.imag) for x in values)


def reconstruct(case):
    """Engine batch clique projection, not a direct synthetic L substitute."""
    n = case['n']
    if case['family'] == 'clique':
        batches = [list(range(n))]
    elif case['family'] == 'path':
        batches = [[i, i+1] for i in range(n-1)]
    elif case['family'] == 'near_clique':
        batches = [list(range(n-1)), list(range(n-2))+[n-1]]
    else:
        raise RuntimeError('Unknown graph family')
    ids = [vertex_id('sensor-'+str(i)) for i in range(n)]
    require(len(set(ids)) == n, 'FNV identity collision')
    directed = set()
    encountered = []
    for batch in batches:
        for i in batch:
            if ids[i] not in encountered:
                encountered.append(ids[i])
        ordered = sorted(ids[i] for i in batch)
        # Every benchmark batch has at most 64 distinct vertices. Existing
        # engine creates one directed edge per ordered pair; repeated insertions
        # leave the starting unit weight unchanged when lambda_decay is zero.
        require(len(ordered) <= 64, 'Benchmark batch leaves clique producer regime')
        for i, u in enumerate(ordered):
            for v in ordered[i+1:]:
                directed.add((u, v))
    indices = {vid: i for i, vid in enumerate(encountered)}
    undirected = sorted((min(indices[u], indices[v]), max(indices[u], indices[v]))
                        for u, v in directed)
    degrees = [0.]*n
    adjacency = []
    for i, j in undirected:
        degrees[i] += .5
        degrees[j] += .5
        adjacency.extend([[i,j,.5], [j,i,.5]])
    matrix = np.diag(degrees)
    for i,j,w in adjacency:
        matrix[i,j] -= w
    values = [complex(float((17*i+3)%29-14), float((11*i+5)%23-11)) for i in range(n)]
    norm = math.sqrt(norm_squared(values))
    values = [z / norm for z in values]
    source_by_id = dict(zip(ids, values))
    source = np.asarray([source_by_id[vid] for vid in encountered])
    target_ids = [ids[i] for i in range(n) if i % 2 == 0]
    target_indices = sorted(indices[vid] for vid in target_ids)
    payload = bytearray(b'gabriel/conditioned-snapshot/v1;exp(-itL);L=D-A\0')
    payload.extend(struct.pack('<QQ', len(batches), n))
    for vid, degree in zip(encountered, degrees):
        payload.extend(struct.pack('<Qd', vid, degree))
    payload.extend(struct.pack('<Q', len(adjacency)))
    for i,j,w in sorted(adjacency):
        payload.extend(struct.pack('<QQd', i,j,w))
    return {'batches':batches, 'vertices':encountered, 'laplacian':{'n':n,'degree':degrees,'adjacency':adjacency},
            'matrix':matrix,'source':source,'targets':target_ids,'target_indices':target_indices,
            'identity':digest(payload), 'tick':len(batches),'directed_edges':len(directed)}


def expected_action(mass, threshold, deadband):
    # A deadband is policy, not a rounding enclosure or predictive confidence.
    if mass > threshold + deadband:
        return 'above'
    if mass < threshold - deadband:
        return 'below'
    return 'abstain'


def validate_captures(executed, protocol):
    before = read(executed/'source_hashes_before.json')
    after = read(executed/'source_hashes_after.json')
    require(before == after, 'Measured source hashes changed during execution')
    for rel, expected in before.items():
        require((NATIVE/rel).is_file() and digest((NATIVE/rel).read_bytes()) == expected,
                'Current/measured source mismatch: '+rel)
    for name in ['Cargo.toml','Cargo.lock','protocol.json','reproduce.py','README.md']:
        require((executed/('frozen_'+name)).read_bytes() == (BENCH/name).read_bytes(),
                'Frozen benchmark file mismatch: '+name)
    require((executed/'frozen_main.rs').read_bytes() == (BENCH/'src/main.rs').read_bytes(),
            'Frozen benchmark source mismatch')
    paths = sorted(executed.glob('*.command.json'))
    commands = [read(p) for p in paths]
    aggregate = read(executed/'commands.json')
    require(len(aggregate) == len(commands), 'Command aggregate is incomplete')
    by_stream = {row['stdout']: row for row in commands}
    require(len(by_stream) == len(commands) and
            all(by_stream.get(row['stdout']) == row for row in aggregate),
            'Individual command records disagree with aggregate')
    names = {Path(row['stdout']).name.removesuffix('.stdout') for row in commands}
    expected = {'compiler','cargo','build','golden'} | {f'process_{i}' for i in range(protocol['fresh_processes'])}
    require(names in [expected, expected|{'generate_lockfile'}], 'Unexpected command inventory')
    for row in commands:
        require(row['returncode'] == 0 and row['failure'] is None, 'Captured command failed')
        for stream in ['stdout','stderr']:
            path = executed/row[stream]
            require(path.resolve().is_relative_to(executed.resolve()), 'Capture escaped output directory')
            raw = path.read_bytes()
            require(len(raw) == row[stream+'_bytes'] and digest(raw) == row[stream+'_sha256'],
                    'Capture bytes/hash mismatch: '+row[stream])
    binary = read(executed/'binary.json')
    bp = executed/binary['relative_path']
    binary_present = bp.is_file()
    if binary_present:
        require(bp.stat().st_size == binary['bytes'] and digest(bp.read_bytes()) == binary['sha256'],
                'Measured binary mismatch')
    integrity = read(executed/'integrity.json')
    require(integrity['captured_command_count'] == len(commands), 'Captured command count mismatch')
    require(all(integrity[key] is True for key in
                ['complete','sources_unchanged','executable_unchanged','all_captured_streams_verified']),
            'Incomplete capture integrity record')
    return {'source_files':len(before), 'captured_commands':len(commands),
            'capture_streams':2*len(commands), 'aggregate_command_index_complete':True,
            'current_and_measured_sources_match':True,
            'binary_present_and_reverified':binary_present}


def stable_unit(source):
    scale = max(max(abs(float(z.real)),abs(float(z.imag))) for z in source)
    require(math.isfinite(scale) and scale > 0., 'Invalid normalized source')
    scaled = [complex(float(z.real)/scale,float(z.imag)/scale) for z in source]
    norm = math.sqrt(norm_squared(scaled))
    return np.array([z/norm for z in scaled])


def check_batches(captured, indices, reverse=False):
    require(len(captured)==len(indices), 'Input batch count mismatch')
    encountered=[]
    for tick,(raws,batch) in enumerate(zip(captured,indices)):
        wanted=list(reversed(batch)) if reverse else batch
        require(len(raws)==len(wanted), 'Input batch size mismatch')
        for raw,entity in zip(raws,wanted):
            require(isinstance(raw,str) and raw.isascii(), 'Non-ASCII input fixture')
            value=json.loads(raw)
            require(value=={'entity':entity,'tick':tick,'phase':0.}, 'Canonical input fixture mismatch')
            vid=vertex_id('sensor-'+str(entity))
            if vid not in encountered:
                encountered.append(vid)
    return encountered


def validate_golden(golden, protocol):
    require(golden['schema']=='gabriel.conditioned-engine.golden.v1' and golden['protocol']==protocol,
            'Golden identity/protocol mismatch')
    require(golden['configuration']['persistence']['lambda_decay']==0., 'Graph decay is active')
    require(golden['configuration']['consensus']['min_crystal_tick']==(1<<64)-1,
            'Fixture does not suppress extraction')
    require(len(golden['cases'])==len(protocol['cases']), 'Golden case count')
    evidence={'oracle_full_states':0,'oracle_diagnostic_states':0,'oracle_max_complex_component_error':0.,
              'oracle_max_region_mass_error':0.,'auto_spectral_max_real_component_difference':0.,
              'max_norm_ratio_error':0.,'max_scalar_variant_difference':0.,'permutation_max_component_difference':0.,
              'source_conditioned_state_pairs':0,'diagnostic_controls':{},'oracle_tolerance':2e-9}
    for case,row in zip(protocol['cases'],golden['cases']):
        require(row['case']==case, 'Golden case mismatch')
        data=reconstruct(case);n=case['n']
        diagnostic_times=[0.]+protocol['query_times']
        times=[0.]+[protocol['query_times'][j%16]+(j//16)/protocol['query_offsets_denominator']
                    for j in range(protocol['golden_query_count'])]
        require(len(set(times[1:]))==protocol['golden_query_count'],'Primary query times repeat')
        require(check_batches(row['batches'],data['batches'])==data['vertices'], 'Ingestion node order mismatch')
        require(row['vertex_ids']==data['vertices'] and row['snapshot_tick']==data['tick'], 'Snapshot metadata mismatch')
        require(bytes(row['snapshot_identity']).hex()==data['identity'], 'Snapshot SHA-256 mismatch')
        require(row['laplacian']==data['laplacian'], 'Reconstructed actual engine Laplacian mismatch')
        require(row['target_ids']==data['targets'], 'Target identity mismatch')
        require(row['auto_backend']==case['expected_auto'], 'Wrong automatic backend')
        require(row['region_backend']==('complete_graph' if case['family']=='clique' else 'state_readout'), 'Wrong region backend')
        source=state_array(row['source'],n)
        require(np.max(np.abs(source-data['source'])) < 2e-15, 'Caller source reconstruction mismatch')
        unit=stable_unit(source)
        if 'unit_source' in row:
            require(np.max(np.abs(state_array(row['unit_source'],n)-unit)) < 2e-15, 'Normalized source mismatch')
        initial_norm=norm_squared(unit)
        threshold=sum(float(abs(source[i])**2)/norm_squared(source) for i in data['target_indices'])
        close(row['threshold'],threshold)
        require(len(row['states'])==len(times), 'Golden frame count')
        actions_count={name:0 for name in ['above','below','abstain']}
        for time,frame in zip(times,row['states']):
            require(frame['time']==time, 'Golden time grid mismatch')
            ref=expm(-1j*time*data['matrix'])@unit
            ref_intensity=np.abs(ref)**2/initial_norm
            ref_mass=float(sum(ref_intensity[i] for i in data['target_indices']))
            a=state_array(frame['auto_amplitudes'],n);s=state_array(frame['spectral_amplitudes'],n)
            realdiff=np.abs(np.column_stack(((s-a).real,(s-a).imag)))
            allowance=protocol['component_absolute_tolerance']+protocol['component_relative_tolerance']*np.maximum(
                np.abs(np.column_stack((a.real,a.imag))),np.abs(np.column_stack((s.real,s.imag))))
            require((realdiff<=allowance).all(), 'Auto/Spectral component tolerance exceeded')
            evidence['auto_spectral_max_real_component_difference']=max(evidence['auto_spectral_max_real_component_difference'],float(realdiff.max()))
            evidence['source_conditioned_state_pairs']+=2*n
            for name,values in [('auto',a),('spectral',s)]:
                error=float(np.max(np.abs(values-ref)))
                require(error<=evidence['oracle_tolerance'], 'Independent SciPy state tolerance exceeded')
                evidence['oracle_max_complex_component_error']=max(evidence['oracle_max_complex_component_error'],error)
                expected=[float(z.real)*float(z.real)/initial_norm+float(z.imag)*float(z.imag)/initial_norm for z in values]
                actual=frame[name+'_normalized_intensities']
                require(len(actual)==n, 'Intensity dimension')
                for x,y in zip(actual,expected): close(x,y)
                close(frame[name+'_norm_ratio'],sum(actual))
                normerror=abs(frame[name+'_norm_ratio']-1.)
                require(normerror<=protocol['norm_absolute_tolerance'], 'Norm drift tolerance exceeded')
                evidence['max_norm_ratio_error']=max(evidence['max_norm_ratio_error'],normerror)
                if time==0.: require(np.max(np.abs(values-unit))<2e-15, 'Zero-time normalized identity')
                mass=sum(actual[i] for i in data['target_indices'])
                close(frame[name+'_full'],mass)
            masses=[frame[name] for name in protocol['variants']]
            spread=max(masses)-min(masses)
            require(spread<=protocol['mass_absolute_tolerance'], 'Scalar variant disagreement')
            evidence['max_scalar_variant_difference']=max(evidence['max_scalar_variant_difference'],spread)
            for name in protocol['variants']:
                error=abs(frame[name]-ref_mass)
                require(error<=evidence['oracle_tolerance'],'Independent SciPy scalar tolerance exceeded')
                evidence['oracle_max_region_mass_error']=max(evidence['oracle_max_region_mass_error'],error)
                require(frame['actions'][name]==expected_action(frame[name],row['threshold'],protocol['deadband']), 'Policy decision mismatch')
            require(len(set(frame['actions'].values()))==1, 'Variant decision disagreement')
            require(frame['actions']['auto_region']==expected_action(ref_mass,row['threshold'],protocol['deadband']), 'SciPy decision disagreement')
            actions_count[frame['actions']['auto_region']]+=1
            evidence['oracle_full_states']+=1
        controls={}
        for source_name in ['uniform','one_hot','real_zero_mean']:
            diag=row['diagnostics'][source_name]
            raw={'uniform':[complex(1.,0.)]*n,
                 'one_hot':[complex(float(i==0),0.) for i in range(n)],
                 'real_zero_mean':[complex(1. if i==0 else -1. if i==1 else 0.,0.) for i in range(n)]}[source_name]
            raw=np.asarray(raw)/math.sqrt(norm_squared(raw))
            captured=state_array(diag['source'],n)
            require(np.max(np.abs(captured-raw))<2e-15,'Diagnostic source mismatch')
            unit_d=stable_unit(captured);norm_d=norm_squared(unit_d)
            require(len(diag['states'])==len(diagnostic_times),'Diagnostic frame count')
            max_deviation=0.;mass_frames=[]
            for time,frame in zip(diagnostic_times,diag['states']):
                require(frame['time']==time,'Diagnostic time grid')
                values=state_array(frame['amplitudes'],n)
                ref=expm(-1j*time*data['matrix'])@unit_d
                err=float(np.max(np.abs(values-ref)))
                require(err<=evidence['oracle_tolerance'],'Diagnostic SciPy state disagreement')
                evidence['oracle_max_complex_component_error']=max(evidence['oracle_max_complex_component_error'],err)
                intensities=np.asarray(frame['normalized_intensities'])
                require(intensities.shape==(n,) and np.isfinite(intensities).all(),'Diagnostic intensities malformed')
                require(np.max(np.abs(intensities-np.abs(values)**2/norm_d))<2e-13,'Diagnostic intensity mismatch')
                close(frame['norm_ratio'],float(sum(intensities)))
                require(abs(frame['norm_ratio']-1.)<=protocol['norm_absolute_tolerance'],'Diagnostic norm drift')
                max_deviation=max(max_deviation,float(np.max(np.abs(intensities-np.abs(unit_d)**2/norm_d))))
                if case['family']=='clique' and source_name=='one_hot':
                    require(float(np.max(intensities[1:])-np.min(intensities[1:]))<=protocol['mass_absolute_tolerance'], 'Clique breaks source-excluded vertex symmetry')
                mass_frames.append(float(sum(intensities[i] for i in data['target_indices'])))
                evidence['oracle_diagnostic_states']+=1
            if source_name=='uniform' or (case['family']=='clique' and source_name=='real_zero_mean'):
                require(max_deviation<=protocol['mass_absolute_tolerance'],'Stationary control moved')
            controls[source_name]={'max_intensity_change_from_zero':max_deviation,'region_mass_range':max(mass_frames)-min(mass_frames)}
        perm=row['diagnostics']['permutation']
        require(perm['vertex_ids']==check_batches(perm['batches'],data['batches'],reverse=True),'Permutation node order')
        permutation=[data['vertices'].index(vid) for vid in perm['vertex_ids']]
        psource=state_array(perm['source'],n)
        require(np.max(np.abs(psource-source[permutation]))<2e-15,'Permuted source identity mismatch')
        require(len(perm['states'])==len(diagnostic_times),'Permutation frame count')
        for time,pframe,frame in zip(diagnostic_times,perm['states'],row['states']):
            require(pframe['time']==time,'Permutation time grid')
            values=state_array(pframe['amplitudes'],n)
            original=state_array(frame['auto_amplitudes'],n)[permutation]
            error=float(np.max(np.abs(values-original)))
            require(error<=2e-9,'Permutation equivariance disagreement')
            evidence['permutation_max_component_difference']=max(evidence['permutation_max_component_difference'],error)
            require(np.max(np.abs(np.array(pframe['normalized_intensities'])-np.array(frame['auto_normalized_intensities'])[permutation]))<=2e-9,'Permutation intensity disagreement')
            close(pframe['norm_ratio'],sum(pframe['normalized_intensities']))
        evidence['diagnostic_controls'][case['id']]={'source_controls':controls,'primary_actions':actions_count,
            'primary_region_mass_range':max(f['auto_region'] for f in row['states'])-min(f['auto_region'] for f in row['states'])}
    return evidence


def validate_runs(runs, golden, protocol):
    require(len(runs)==protocol['fresh_processes'] and len({r['pid'] for r in runs})==len(runs),
            'Fresh-process count/identity mismatch')
    variants=protocol['variants'];phases=['total_ns','ingest_ns','snapshot_ns','preparation_ns','query_ns']
    pairs=[('spectral_full','auto_full'),('spectral_full','auto_region'),('auto_full','auto_region')]
    total_queries=0;total_tasks=0;max_timed_vs_golden=0.
    for pi,run in enumerate(runs):
        require(run['schema']=='gabriel.conditioned-engine.measurements.v1' and run['process_index']==pi
                and run['protocol']==protocol and run['pilot'] is False,'Measured run identity mismatch')
        require(len(run['cases'])==len(protocol['cases'])*len(protocol['query_counts']),'Measured case count')
        for ci,case in enumerate(protocol['cases']):
            reference=golden['cases'][ci];data=reconstruct(case)
            for qi,count in enumerate(protocol['query_counts']):
                row=run['cases'][ci*len(protocol['query_counts'])+qi]
                require(row['case']==case and row['query_count']==count,'Measured task mismatch')
                require(len(row['measurements'])==protocol['batches_per_process'],'Measured batch count')
                for bi,batch in enumerate(row['measurements']):
                    rotation=(pi+ci+qi+bi)%3
                    order=variants[rotation:]+variants[:rotation]
                    if (pi+bi)%2: order.reverse()
                    require(batch['batch']==bi and batch['order']==order,'Variant timing order mismatch')
                    for variant in variants:
                        sample=batch[variant];total_tasks+=1
                        for phase in phases:
                            require(type(sample[phase]) is int and sample[phase]>0,'Nonpositive/noninteger timing')
                        require(sum(sample[p] for p in phases[1:])<=sample['total_ns'],'Nested times exceed total')
                        require(sample['tick']==data['tick'] and sample['vertices']==case['n']
                                and sample['edges']==data['directed_edges'],'Timed engine counters mismatch')
                        wanted_backend='spectral' if variant=='spectral_full' else case['expected_auto']
                        wanted_region='complete_graph' if variant=='auto_region' and case['family']=='clique' else 'state_readout'
                        require(sample['backend']==wanted_backend and sample['region_backend']==wanted_region,'Timed dispatch mismatch')
                        close(sample['threshold'],reference['threshold'])
                        require(len(sample['masses'])==len(sample['actions'])==count,'Timed output count mismatch')
                        for q,(mass,action) in enumerate(zip(sample['masses'],sample['actions'])):
                            frame=reference['states'][1+q]
                            error=abs(mass-frame[variant]);max_timed_vs_golden=max(max_timed_vs_golden,error)
                            require(math.isfinite(mass) and error<=protocol['mass_absolute_tolerance'],'Timed mass disagrees with golden')
                            require(action==expected_action(mass,sample['threshold'],protocol['deadband'])
                                    and action==frame['actions'][variant],'Timed policy decision mismatch')
                        total_queries+=count
    rows=[]
    for ci,case in enumerate(protocol['cases']):
        for qi,count in enumerate(protocol['query_counts']):
            entry={'case':case,'query_count':count,'phases':{}}
            idx=ci*len(protocol['query_counts'])+qi
            for phase in phases:
                comparisons={}
                for numerator,denominator in pairs:
                    processes=[]
                    for pi,run in enumerate(runs):
                        samples=run['cases'][idx]['measurements']
                        processes.append({'process_index':pi,
                            'median_paired_ratio':statistics.median(s[numerator][phase]/s[denominator][phase] for s in samples),
                            'median_numerator_ns':statistics.median(s[numerator][phase] for s in samples),
                            'median_denominator_ns':statistics.median(s[denominator][phase] for s in samples)})
                    ratios=[p['median_paired_ratio'] for p in processes]
                    comparisons[numerator+'_over_'+denominator]={'processes':processes,
                        'median_process_paired_ratio':statistics.median(ratios),
                        'minimum_process_paired_ratio':min(ratios),'maximum_process_paired_ratio':max(ratios),
                        'median_process_numerator_ns':statistics.median(p['median_numerator_ns'] for p in processes),
                        'median_process_denominator_ns':statistics.median(p['median_denominator_ns'] for p in processes)}
                entry['phases'][phase]=comparisons
            rows.append(entry)
    return rows,{'fresh_processes':len(runs),'paired_three_variant_batches':len(protocol['cases'])*len(protocol['query_counts'])*protocol['batches_per_process']*len(runs),
        'complete_timed_engine_tasks':total_tasks,'total_timed_scalar_queries':total_queries,
        'maximum_timed_vs_golden_mass_difference':max_timed_vs_golden,'all_timed_scalar_outputs_checked':True}


def write_tables(rows, output):
    lines=[r'\begin{table}[H]\centering\small',
        r'\caption{Public-Engine observation tasks. Median elapsed-time ratios of seven process medians (five paired batches each). Each task creates an Engine, ingests the graph, constructs one snapshot and prepares a source/region before $q$ scalar queries. The two total columns compare the full spectral baseline with automatic full-state and direct-region consumers. Query-only ratios exclude ingestion and preparation. Ranges are observed process ranges, not confidence intervals.}',
        r'\label{tab:engineobserver}',
        r'\resizebox{\textwidth}{!}{\begin{tabular}{lrrrrr}\toprule',
        r'Graph & $q$ & Total/full & Total/region [range] & Query/region & Total region ($\mu$s)\\\midrule']
    for row in rows:
        if row['query_count'] not in [1,256]: continue
        total=row['phases']['total_ns'];query=row['phases']['query_ns']
        direct=total['spectral_full_over_auto_region'];full=total['spectral_full_over_auto_full']
        label={'clique':'Clique','path':'Path','near_clique':'Near-clique'}[row['case']['family']]+' '+str(row['case']['n'])
        lines.append(r'%s & %d & %.2f & $%.2f\,[%.2f,\,%.2f]$ & %.2f & %.1f\\'%(
            label,row['query_count'],full['median_process_paired_ratio'],direct['median_process_paired_ratio'],
            direct['minimum_process_paired_ratio'],direct['maximum_process_paired_ratio'],
            query['spectral_full_over_auto_region']['median_process_paired_ratio'],direct['median_process_denominator_ns']/1000))
    lines += [r'\bottomrule\end{tabular}}',r'\end{table}']
    (output/'engine_observer_tables.tex').write_text('\n'.join(lines)+'\n')


def validate_native_tests():
    directory=NATIVE/'benchmark-results/engine_observer_validation'
    evidence={}
    for name,code in [('workspace_observer',0),('historical_fixture',101)]:
        record=read(directory/(name+'.command.json'))
        require(record['returncode']==code,'Unexpected native validation exit status')
        for stream in ['stdout','stderr']:
            raw=(directory/record[stream]).read_bytes()
            require(len(raw)==record[stream+'_bytes'] and digest(raw)==record[stream+'_sha256'],
                    'Native validation stream hash mismatch')
        stdout=(directory/record['stdout']).read_text()
        matches=re.findall(r'test result: (?:ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out',stdout)
        require(matches,'Missing native test summaries')
        counts=[sum(int(row[i]) for row in matches) for i in range(5)]
        evidence[name]=dict(zip(['passed','failed','ignored','measured','filtered'],counts))
        evidence[name]['returncode']=code
        evidence[name]['stdout_sha256']=record['stdout_sha256']
    require(evidence['workspace_observer']['passed']==492
            and evidence['workspace_observer']['failed']==0
            and evidence['workspace_observer']['ignored']==1
            and evidence['workspace_observer']['filtered']==1,'Native workspace counts differ')
    require(evidence['historical_fixture']['failed']==1,'Historical fixture failure was not exercised')
    return evidence


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executed',type=Path,default=BENCH/'executed')
    parser.add_argument('--output-dir',type=Path,default=ROOT/'results')
    args=parser.parse_args()
    protocol=read(BENCH/'protocol.json')
    require(protocol['fresh_processes']==7 and protocol['batches_per_process']==5
            and protocol['query_counts']==[1,16,256] and len(protocol['cases'])==8
            and protocol['query_offsets_denominator']==4096 and protocol['golden_query_count']==256,
            'Unexpected declared experiment design')
    evidence=validate_captures(args.executed,protocol)
    evidence['native_validation']=validate_native_tests()
    golden=read(args.executed/'golden.stdout')
    evidence.update(validate_golden(golden,protocol))
    runs=[read(args.executed/f'process_{i}.stdout') for i in range(protocol['fresh_processes'])]
    rows,timing_evidence=validate_runs(runs,golden,protocol)
    archived=read(args.executed/'summary.json')
    expected=[]
    for row in rows:
        phases={}
        for phase,comparisons in row['phases'].items():
            phases[phase]={name:{'processes':values['processes'],
                'median':values['median_process_paired_ratio'],
                'minimum':values['minimum_process_paired_ratio'],
                'maximum':values['maximum_process_paired_ratio']}
                for name,values in comparisons.items()}
        expected.append({'case':row['case'],'query_count':row['query_count'],'phases':phases})
    require(archived['schema']=='gabriel.conditioned-engine.summary.v1'
            and archived['cases']==expected,'Independently aggregated summary disagrees')
    require(archived['fresh_processes']==protocol['fresh_processes']
            and archived['complete_tasks_per_variant']*3==timing_evidence['complete_timed_engine_tasks']
            and archived['timed_scalar_queries_per_variant']*3==timing_evidence['total_timed_scalar_queries'],
            'Archived task/query counts disagree')
    evidence['every_archived_timing_summary_recomputed_exactly']=True
    evidence.update(timing_evidence)
    evidence.update({'schema':'gabriel.engine-observer.independent-checks.v1',
        'numpy_version':np.__version__,'scipy_version':scipy.__version__,
        'input_graphs_and_vertex_identities_independently_reconstructed':True,
        'no_new_timings_generated':True})
    args.output_dir.mkdir(parents=True,exist_ok=True)
    (args.output_dir/'engine_observer_checks.json').write_text(json.dumps(evidence,indent=2)+'\n')
    (args.output_dir/'engine_observer_summary.json').write_text(json.dumps({'evidence':evidence,'cases':rows},indent=2)+'\n')
    write_tables(rows,args.output_dir)
    print(json.dumps(evidence,indent=2))


if __name__=='__main__':
    main()
