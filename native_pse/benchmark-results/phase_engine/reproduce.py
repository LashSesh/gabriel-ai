#!/usr/bin/env python3
"""Build, verify and measure frozen same-tree sparse native engine variants.

Use a NEW --output directory. Execute correctness tests first; run no other
build or CPU-heavy process concurrently with the timing phase. Rust 1.95.0 and
Python 3.10+ are required. Timings are never accepted without exact goldens.
"""
from __future__ import annotations
import argparse,base64,hashlib,json,os,platform,shutil,statistics,subprocess,time
from pathlib import Path
HERE=Path(__file__).resolve().parent
NATIVE=HERE.parents[1]

def require(condition,message):
    if not condition: raise RuntimeError(message)

def sha(raw): return hashlib.sha256(raw).hexdigest()

def atomic(path,raw):
    pending=path.with_name(path.name+'.pending')
    pending.write_bytes(raw)
    os.replace(pending,path)
    require(path.read_bytes()==raw,f'Atomic write reread differs: {path}')

def write_json(path,value): atomic(path,(json.dumps(value,indent=2)+'\n').encode())

def source_hashes():
    files={NATIVE/'Cargo.toml',NATIVE/'Cargo.lock'}
    for directory in [NATIVE/'crates',NATIVE/'src']:
        files.update(p for p in directory.rglob('*') if p.is_file() and p.suffix in {'.rs','.toml','.lock','.bin'})
    files.update(HERE/name for name in ['Cargo.toml','Cargo.lock','protocol.json','inputs.json','freeze_inputs.py','reproduce.py','README.md'])
    files.update((HERE/'src').rglob('*.rs'))
    return {str(p.relative_to(NATIVE)):sha(p.read_bytes()) for p in sorted(files)}

def compare(name,records,output):
    result={'bytes_identical':len(set(records.values()))==1,'bytes':{k:len(v) for k,v in records.items()},
            'sha256':{k:sha(v) for k,v in records.items()}}
    write_json(output/(name+'_comparison.json'),result)
    require(result['bytes_identical'],name+' differs; timings halted')
    return result

def golden_diagnostics(raw,inputs):
    golden=json.loads(raw);rows=golden['cases'];source=inputs['cases']
    require(len(rows)==len(source),'Wrong golden case count')
    diagnostics=[]
    for case,fixture in zip(rows,source):
        n=fixture['entities'];workload=fixture['workload']
        require(case['entities']==n and case['workload']==workload,'Golden case order differs')
        expected=[('bootstrap',s) for s in fixture['bootstrap']]+[('measured',s) for s in fixture['measured']]
        require(len(case['traces'])==len(expected),'Golden trace count differs')
        keys=[];measured=[]
        for tick,(trace,(stage,step)) in enumerate(zip(case['traces'],expected),1):
            crystal=trace['crystal'];topology=trace['topology'];size=step['vertices']
            require(trace['stage']==stage and trace['commits']==tick,'Actual commit/stage differs')
            require(topology['vertices']==size and topology['edges']==step['edges'],'Actual graph shape differs')
            require(len(crystal['region'])==size and topology['region']==crystal['region'],'Full region/order differs')
            bits=topology['labelled_upper_bits_lsb_first']
            require(len(bits)==size*(size-1)//2 and set(bits)<=set('01') and bits.count('1')==step['edges'],'Actual induced graph bits invalid')
            if size<=7:
                word=sum(int(v)<<i for i,v in enumerate(bits));sig=crystal.get('metatron_signature')
                require(word==topology['labelled_word'] and sig is not None and sig['n']==size and sig['m']==step['edges'],'Signature shape/key differs')
                key=(size,word);keys.append(key)
                if stage=='measured':measured.append(key)
            else:
                require(crystal.get('metatron_signature') is None and topology['labelled_word'] is None,'Ineligible signature present')
        if n<=7:
            expected_distinct=1 if workload=='repeated_path' else len(fixture['measured'])
            require(len(set(measured))==expected_distinct,'Requested key regime not observed')
        diagnostics.append({'entities':n,'workload':workload,'bootstrap_ticks':len(fixture['bootstrap']),
          'measured_ticks':len(fixture['measured']),'all_eligible_labelled_keys':keys,'measured_eligible_labelled_keys':measured,
          'distinct_all_eligible_keys':len(set(keys)),'distinct_measured_eligible_keys':len(set(measured)),
          'measured_edge_counts':[t['topology']['edges'] for t in case['traces'] if t['stage']=='measured']})
    return diagnostics

def summarize(protocol,runs):
    summary=[]
    for comparison in protocol['comparisons']:
        reference,candidate=comparison['variants']
        for n in protocol['engine']['entities']:
            for workload in protocol['engine']['workloads']:
                pairs=[]
                for pair in range(protocol['engine']['external_pairs']):
                    rates={};latencies={}
                    for variant in comparison['variants']:
                        matching=[r for r in runs if r['comparison']==comparison['name'] and r['pair']==pair and r['variant']==variant]
                        require(len(matching)==1,'Missing/duplicate engine process')
                        measurements=[m for m in matching[0]['raw']['measurements'] if m['entities']==n and m['workload']==workload]
                        require(len(measurements)==protocol['engine']['inner_repetitions'],'Wrong repetition count')
                        expected_ticks=12 if workload=='repeated_path' else min(16,n*(n-1)//2)
                        require(all(m['measured_commits']==expected_ticks==m['ticks'] and m['elapsed_ns']>0 for m in measurements),'Bad measured commits/timing')
                        rates[variant]=statistics.median(m['ticks_per_s'] for m in measurements)
                        latencies[variant]=statistics.median(m['ns_per_tick'] for m in measurements)
                    pairs.append({'pair':pair,'median_ticks_per_s':rates,'median_ns_per_tick':latencies,'ratio':rates[candidate]/rates[reference]})
                ratios=[p['ratio'] for p in pairs]
                summary.append({'comparison':comparison['name'],'entities':n,'workload':workload,'pairs':pairs,
                  'median_paired_ratio':statistics.median(ratios),'min_paired_ratio':min(ratios),'max_paired_ratio':max(ratios)})
    return summary

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=False)
    protocol=json.loads((HERE/'protocol.json').read_text());inputs=json.loads((HERE/'inputs.json').read_text())
    for name in ['Cargo.toml','Cargo.lock','protocol.json','inputs.json','freeze_inputs.py','reproduce.py','README.md']:
        shutil.copy2(HERE/name,output/('frozen_'+name))
    for source in (HERE/'src').glob('*.rs'):shutil.copy2(source,output/('frozen_'+source.name))
    frozen=source_hashes();write_json(output/'source_hashes_before.json',frozen)
    env=os.environ.copy()
    removed=[k for k in list(env) if k.startswith('CARGO_PROFILE_') or k in {'RUSTFLAGS','CARGO_ENCODED_RUSTFLAGS','RUSTDOCFLAGS','RUSTC_WRAPPER','RUSTC_WORKSPACE_WRAPPER'}]
    for key in removed:env.pop(key)
    env['RUSTUP_TOOLCHAIN']=protocol['toolchain'];env['CARGO_BUILD_JOBS']=str(protocol['build_jobs'])
    commands=[];captured=[]
    def run(command,name,timeout=1800):
        begin=time.perf_counter();failure=None;returncode=None;stdout=b'';stderr=b''
        try:
            result=subprocess.run(command,cwd=HERE,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)
            stdout=result.stdout;stderr=result.stderr;returncode=result.returncode
        except subprocess.TimeoutExpired as error:
            failure=repr(error);stdout=error.stdout or b'';stderr=error.stderr or b''
        except OSError as error:failure=repr(error)
        prefix=output/name
        atomic(prefix.with_suffix('.stdout'),stdout);atomic(prefix.with_suffix('.stderr'),stderr)
        record={'command':command,'cwd':str(HERE),'returncode':returncode,'failure':failure,
          'wrapper_wall_seconds':time.perf_counter()-begin,'wrapper_wall_is_benchmark_metric':False,
          'stdout':prefix.with_suffix('.stdout').name,'stderr':prefix.with_suffix('.stderr').name,
          'stdout_bytes':len(stdout),'stderr_bytes':len(stderr),'stdout_sha256':sha(stdout),'stderr_sha256':sha(stderr)}
        write_json(prefix.with_suffix('.command.json'),record);commands.append(record)
        # Independent original-byte copy; later comparisons use in-memory bytes,
        # but final acceptance also rereads every emitted file and checks hashes.
        captured.append({'name':name,'stdout_base64':base64.b64encode(stdout).decode(),'stderr_base64':base64.b64encode(stderr).decode(),
          'stdout_sha256':sha(stdout),'stderr_sha256':sha(stderr)})
        write_json(output/'commands.json',commands)
        require(failure is None and returncode==0,f'Command failed: {name}; inspect captured stderr')
        if not name.startswith('build_'):require(bool(stdout),f'Unexpected empty stdout: {name}')
        return stdout
    try:
        compiler=run(['rustc','--version','--verbose'],'compiler');require(compiler.startswith(b'rustc 1.95.0 '),'Rust version mismatch')
        run(['cargo','--version','--verbose'],'cargo')
        cpuinfo=Path('/proc/cpuinfo');cpu=None
        if cpuinfo.exists():cpu=next((s.partition(':')[2].strip() for s in cpuinfo.read_text().splitlines() if s.startswith('model name')),None)
        write_json(output/'environment.json',{'platform':platform.platform(),'python':platform.python_version(),'logical_cpus':os.cpu_count(),
          'cpu_model':cpu,'affinity':sorted(os.sched_getaffinity(0)) if hasattr(os,'sched_getaffinity') else None,
          'profile':protocol['profile'],'removed_build_override_names':removed,'RAYON_NUM_THREADS':env.get('RAYON_NUM_THREADS'),
          'effective_rustup_toolchain':env['RUSTUP_TOOLCHAIN'],'effective_cargo_build_jobs':env['CARGO_BUILD_JOBS'],
          'process_startup_is_timed':False,'cpu_and_rss_counters_measured':False})
        target=output/'target/build';preserved=output/'target/binaries';preserved.mkdir(parents=True);binaries={}
        for variant in protocol['variants']:
            command=['cargo','build','--locked','--release','--jobs',str(protocol['build_jobs']),'--manifest-path',str(HERE/'Cargo.toml'),
                     '--target-dir',str(target),'--features',','.join(protocol['features'][variant])]
            run(command,'build_'+variant)
            suffix='.exe' if os.name=='nt' else '';built=target/'release'/('pse-phase-engine-benchmark'+suffix)
            binaries[variant]=preserved/(variant+suffix);shutil.copy2(built,binaries[variant])
            require(sha(built.read_bytes())==sha(binaries[variant].read_bytes()),'Executable copy mismatch')
            print('Built and preserved '+variant,flush=True)
        binary_hashes={v:{'path':str(p),'sha256':sha(p.read_bytes()),'bytes':p.stat().st_size} for v,p in binaries.items()}
        write_json(output/'binaries.json',binary_hashes)
        configs={v:run([str(b),'configuration'],'configuration_'+v) for v,b in binaries.items()}
        compare('configuration',configs,output);atomic(output/'configuration.json',configs['indexed'])
        goldens={v:run([str(b),'golden'],'golden_'+v) for v,b in binaries.items()}
        golden_equality=compare('golden',goldens,output)
        diagnostics=golden_diagnostics(goldens['indexed'],inputs);write_json(output/'topology_diagnostics.json',diagnostics)
        before_timing=source_hashes();write_json(output/'source_hashes_before_timing.json',before_timing)
        require(frozen==before_timing,'Sources changed during setup; timing halted')
        print('Exact four-way goldens and actual public-input graph traces verified; starting timings',flush=True)
        runs=[]
        for comparison in protocol['comparisons']:
            for pair,order in enumerate(comparison['orders']):
                for variant in order:
                    raw=json.loads(run([str(binaries[variant]),'engine'],f"engine_{comparison['name']}_{pair}_{variant}"))
                    require(raw['variant']==variant,'Executable reports wrong variant')
                    runs.append({'comparison':comparison['name'],'pair':pair,'variant':variant,'raw':raw})
                print(f"Completed {comparison['name']} pair {pair+1}/5",flush=True)
        after=source_hashes();write_json(output/'source_hashes_after.json',after)
        require(frozen==after,'Source/input/protocol changed during measurement; results invalid')
        require(all(sha(p.read_bytes())==binary_hashes[v]['sha256'] for v,p in binaries.items()),'Executable changed during measurement')
        for capture in captured:
            for stream in ['stdout','stderr']:
                original=base64.b64decode(capture[stream+'_base64']);actual=(output/(capture['name']+'.'+stream)).read_bytes()
                require(actual==original and sha(actual)==capture[stream+'_sha256'],'Persisted capture mismatch')
        summary=summarize(protocol,runs)
        write_json(output/'results.json',{'schema':1,'source_unchanged':True,'binary_unchanged':True,'all_capture_files_verified':True,
          'engine_golden':golden_equality,'topology_diagnostics':diagnostics,'engine_runs':runs,'summary':summary})
        write_json(output/'summary.json',summary)
        print('Complete: '+str(output/'summary.json'),flush=True)
    finally:
        write_json(output/'captured_records.json',captured)

if __name__=='__main__':main()
