#!/usr/bin/env python3
"""Capture a frozen three-consumer Engine task experiment in a new directory.

--pilot-only executes golden validation and one untimed-for-report sample per
case/consumer/query-count for a duration estimate. Those rows are never merged
with the seven-process paired measurements. Do not run other builds or timing
jobs concurrently. A Rust 1.95.0 installation and cached Cargo dependencies are
external requirements.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
import platform
import shutil
import statistics
import subprocess
import time
from pathlib import Path

HERE=Path(__file__).resolve().parent
NATIVE=HERE.parents[1]
VARIANTS=('spectral_full','auto_full','auto_region')
PHASES=('total_ns','ingest_ns','snapshot_ns','preparation_ns','query_ns')
PAIRS=(('spectral_full','auto_full'),('spectral_full','auto_region'),('auto_full','auto_region'))

def require(ok,message):
    if not ok:raise RuntimeError(message)

def sha(raw):return hashlib.sha256(raw).hexdigest()

def atomic(path,raw):
    temporary=path.with_name(path.name+'.pending')
    temporary.write_bytes(raw)
    os.replace(temporary,path)
    require(path.read_bytes()==raw,f'Atomic write mismatch: {path}')

def write_json(path,obj):
    atomic(path,(json.dumps(obj,indent=2,allow_nan=False)+'\n').encode())

def sources():
    paths={NATIVE/'Cargo.toml',NATIVE/'Cargo.lock'}
    for directory in (NATIVE/'src',NATIVE/'crates'):
        paths.update(p for p in directory.rglob('*') if p.is_file() and p.suffix in {'.rs','.toml','.lock','.bin'})
    paths.update(HERE/name for name in ('Cargo.toml','Cargo.lock','protocol.json','reproduce.py','README.md'))
    paths.update((HERE/'src').rglob('*.rs'))
    require(all(p.is_file() for p in paths),'Missing source file')
    return {str(p.relative_to(NATIVE)):sha(p.read_bytes()) for p in sorted(paths)}

def validate_run(run,protocol,process_index,pilot=False):
    require(run['schema']=='gabriel.conditioned-engine.measurements.v1','Measurement schema')
    require(run['protocol']==protocol and run['process_index']==process_index,'Embedded protocol/process differs')
    require(run['pilot'] is pilot,'Pilot/measurement flag differs')
    expected=[(case,q) for case in protocol['cases'] for q in protocol['query_counts']]
    require(len(run['cases'])==len(expected),'Case count differs')
    for index,(row,(case,q)) in enumerate(zip(run['cases'],expected)):
        require(row['case']==case and row['query_count']==q,'Case descriptor differs')
        count=1 if pilot else protocol['batches_per_process']
        require(len(row['measurements'])==count,'Batch count differs')
        ci=index//len(protocol['query_counts']);qi=index%len(protocol['query_counts'])
        for batch,sample in enumerate(row['measurements']):
            rotation=(process_index+ci+qi+batch)%3
            order=list(VARIANTS[rotation:]+VARIANTS[:rotation])
            if (process_index+batch)%2:order.reverse()
            require(sample['batch']==batch and sample['order']==order,'Execution order differs')
            for variant in VARIANTS:
                timing=sample[variant]
                require(all(type(timing[p]) is int and timing[p]>0 for p in PHASES),'Nonpositive timing')
                require(timing['total_ns']>=sum(timing[p] for p in PHASES[1:]),'Total smaller than measured subspans')
                require(len(timing['masses'])==len(timing['actions'])==q,'Missing scalar outputs')
                require(all(math.isfinite(x) for x in timing['masses']),'Nonfinite scalar output')
                expected_backend='spectral' if variant=='spectral_full' else case['expected_auto']
                expected_region='complete_graph' if variant=='auto_region' and expected_backend=='complete_graph' else 'state_readout'
                require(timing['backend']==expected_backend and timing['region_backend']==expected_region,'Dispatch differs')
                require(timing['vertices']==case['n'],'Vertex count differs')
                cutoff=timing['threshold'];deadband=protocol['deadband']
                actions=['above' if x>cutoff+deadband else 'below' if x<cutoff-deadband else 'abstain' for x in timing['masses']]
                require(actions==timing['actions'],'Stored decision differs from rule')
            ref=sample['spectral_full']
            for variant in VARIANTS[1:]:
                actual=sample[variant]
                require(actual['actions']==ref['actions'],'Consumer decisions differ')
                require(all(abs(a-b)<=protocol['mass_absolute_tolerance'] for a,b in zip(actual['masses'],ref['masses'])),'Consumer masses differ')

def summary(runs,protocol):
    rows=[]
    expected=[(case,q) for case in protocol['cases'] for q in protocol['query_counts']]
    for index,(case,q) in enumerate(expected):
        phases={}
        for phase in PHASES:
            pairs={}
            for numerator,denominator in PAIRS:
                per=[]
                for process,run in enumerate(runs):
                    batches=run['cases'][index]['measurements']
                    per.append({'process_index':process,'median_paired_ratio':statistics.median(r[numerator][phase]/r[denominator][phase] for r in batches),
                                'median_numerator_ns':statistics.median(r[numerator][phase] for r in batches),
                                'median_denominator_ns':statistics.median(r[denominator][phase] for r in batches)})
                ratios=[r['median_paired_ratio'] for r in per]
                pairs[f'{numerator}_over_{denominator}']={'processes':per,'median':statistics.median(ratios),'minimum':min(ratios),'maximum':max(ratios)}
            phases[phase]=pairs
        rows.append({'case':case,'query_count':q,'phases':phases})
    tasks=len(runs)*len(expected)*protocol['batches_per_process']
    queries=len(runs)*len(protocol['cases'])*sum(protocol['query_counts'])*protocol['batches_per_process']
    return {'schema':'gabriel.conditioned-engine.summary.v1','fresh_processes':len(runs),'complete_tasks_per_variant':tasks,
            'timed_scalar_queries_per_variant':queries,'cases':rows,'interpretation':protocol['summary']}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--pilot-only',action='store_true')
    args=parser.parse_args()
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=False)
    protocol=json.loads((HERE/'protocol.json').read_text())
    env=os.environ.copy()
    removed=[k for k in env if k.startswith('CARGO_PROFILE_') or k in {'RUSTFLAGS','CARGO_ENCODED_RUSTFLAGS','RUSTDOCFLAGS','RUSTC_WRAPPER','RUSTC_WORKSPACE_WRAPPER'}]
    for key in removed:env.pop(key)
    env['RUSTUP_TOOLCHAIN']=protocol['toolchain'];env['CARGO_BUILD_JOBS']=str(protocol['build_jobs'])
    commands=[]
    def run(command,name,timeout=1800):
        start=time.perf_counter();stdout=stderr=b'';code=None;failure=None
        try:
            p=subprocess.run([str(x) for x in command],cwd=HERE,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)
            stdout,stderr,code=p.stdout,p.stderr,p.returncode
        except subprocess.TimeoutExpired as e:
            stdout,stderr=e.stdout or b'',e.stderr or b'';failure=repr(e)
        except OSError as e:failure=repr(e)
        atomic(output/f'{name}.stdout',stdout);atomic(output/f'{name}.stderr',stderr)
        record={'name':name,'command':[str(x) for x in command],'cwd':str(HERE),'returncode':code,'failure':failure,
                'wrapper_wall_seconds':time.perf_counter()-start,'wrapper_wall_is_benchmark_metric':False,
                'stdout':name+'.stdout','stderr':name+'.stderr','stdout_bytes':len(stdout),'stderr_bytes':len(stderr),
                'stdout_sha256':sha(stdout),'stderr_sha256':sha(stderr)}
        write_json(output/f'{name}.command.json',record);commands.append(record)
        require(failure is None and code==0,f'{name} failed; all streams and the failed command are retained')
        return stdout
    frozen=None;executable=None;binary_hash=None;status={'complete':False,'pilot_only':args.pilot_only}
    try:
        require(run(['rustc','--version','--verbose'],'compiler').startswith(b'rustc 1.95.0 '),'Rust version differs')
        run(['cargo','--version','--verbose'],'cargo')
        if not (HERE/'Cargo.lock').is_file():run(['cargo','generate-lockfile','--offline'],'generate_lockfile')
        frozen=sources();write_json(output/'source_hashes_before.json',frozen)
        for name in ('Cargo.toml','Cargo.lock','protocol.json','reproduce.py','README.md'):shutil.copy2(HERE/name,output/('frozen_'+name))
        shutil.copy2(HERE/'src/main.rs',output/'frozen_main.rs')
        cpuinfo=Path('/proc/cpuinfo')
        model=next((line.partition(':')[2].strip() for line in cpuinfo.read_text().splitlines() if line.startswith('model name')),None) if cpuinfo.exists() else None
        write_json(output/'environment.json',{'platform':platform.platform(),'python':platform.python_version(),'logical_cpus':os.cpu_count(),'cpu_model':model,
            'affinity':sorted(os.sched_getaffinity(0)) if hasattr(os,'sched_getaffinity') else None,'profile':protocol['profile'],
            'removed_build_override_names':removed,'toolchain':env['RUSTUP_TOOLCHAIN'],'build_jobs':env['CARGO_BUILD_JOBS'],
            'RAYON_NUM_THREADS':env.get('RAYON_NUM_THREADS'),'process_startup_is_timed':False,'cpu_and_rss_counters_measured':False})
        target=output/'target'
        run(['cargo','build','--release','--locked','--offline','--target-dir',target],'build')
        executable=output/'executable'/('pse-conditioned-engine-benchmark'+('.exe' if os.name=='nt' else ''))
        executable.parent.mkdir();shutil.copy2(target/'release'/executable.name,executable)
        binary_hash=sha(executable.read_bytes());write_json(output/'binary.json',{'relative_path':str(executable.relative_to(output)),'bytes':executable.stat().st_size,'sha256':binary_hash})
        golden=json.loads(run([executable,'golden'],'golden'))
        require(golden['schema']=='gabriel.conditioned-engine.golden.v1' and golden['protocol']==protocol,'Golden protocol differs')
        require(len(golden['cases'])==len(protocol['cases']),'Golden case count differs')
        if args.pilot_only:
            parsed=json.loads(run([executable,'pilot'],'pilot',timeout=600));validate_run(parsed,protocol,0,pilot=True)
            write_json(output/'pilot_estimate.json',{'schema':'gabriel.conditioned-engine.pilot.v1','included_in_final_statistics':False,
                'single_pass_total_ns':sum(row[v]['total_ns'] for case in parsed['cases'] for row in case['measurements'] for v in VARIANTS),
                'approximate_measurement_seconds':sum(row[v]['total_ns'] for case in parsed['cases'] for row in case['measurements'] for v in VARIANTS)*protocol['fresh_processes']*(protocol['batches_per_process']+1)/1e9})
        else:
            runs=[]
            for index in range(protocol['fresh_processes']):
                parsed=json.loads(run([executable,'measure','--process-index',index],f'process_{index}',timeout=600))
                validate_run(parsed,protocol,index);runs.append(parsed)
                print(f'Validated process {index+1}/{protocol["fresh_processes"]}',flush=True)
            require(len({r['pid'] for r in runs})==len(runs),'Distinct fresh process IDs required')
            write_json(output/'summary.json',summary(runs,protocol))
        status['complete']=True
    finally:
        if frozen is not None:
            after=sources();write_json(output/'source_hashes_after.json',after)
            status['sources_unchanged']=after==frozen;status['complete'] &= after==frozen
        if executable is not None and binary_hash is not None:
            status['executable_unchanged']=sha(executable.read_bytes())==binary_hash
            status['complete'] &= status['executable_unchanged']
        # Rebuild the final index from the exact primary records, then reopen it.
        # This final write occurs after the last captured command, including failure.
        primary=[]
        for record in commands:
            path=output/(record['name']+'.command.json')
            saved=json.loads(path.read_text());require(saved==record,'Primary command changed')
            primary.append(saved)
        write_json(output/'commands.json',primary)
        reread=json.loads((output/'commands.json').read_text())
        actual_files={p.name for p in output.glob('*.command.json')}
        expected_files={r['name']+'.command.json' for r in commands}
        inventory_ok=(reread==commands and actual_files==expected_files and len(reread)==len(commands))
        stream_checks=[]
        for record in reread:
            for stream in ('stdout','stderr'):
                data=(output/record[stream]).read_bytes()
                stream_checks.append(len(data)==record[stream+'_bytes'] and sha(data)==record[stream+'_sha256'])
        status['command_index_complete_and_reopened']=inventory_ok
        status['all_captured_streams_verified']=all(stream_checks)
        status['captured_command_count']=len(reread)
        status['complete'] &= inventory_ok and all(stream_checks)
        write_json(output/'integrity.json',status)
    require(status['complete'],'Execution incomplete or provenance gate failed')
    print(output/'pilot_estimate.json' if args.pilot_only else output/'summary.json')

if __name__=='__main__':main()
