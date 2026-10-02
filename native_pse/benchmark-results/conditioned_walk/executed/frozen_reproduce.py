#!/usr/bin/env python3
"""Build and run the paired, same-output conditioned-walk benchmark.

Use a NEW --output directory, run correctness tests first, and run no other
build or CPU-heavy task concurrently. Rust 1.95.0 and Python 3.10+ are required.
This runner records successful execution; its presence alone is not evidence
that an experiment has been performed.
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

HERE = Path(__file__).resolve().parent
NATIVE = HERE.parents[1]


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def atomic(path, raw):
    pending = path.with_name(path.name + '.pending')
    pending.write_bytes(raw)
    os.replace(pending, path)
    require(path.read_bytes() == raw, f'Atomic write differs: {path}')


def write_json(path, value):
    atomic(path, (json.dumps(value, indent=2, allow_nan=False) + '\n').encode())


def source_hashes():
    files = {NATIVE / 'Cargo.toml', NATIVE / 'Cargo.lock'}
    for directory in [NATIVE / 'crates', NATIVE / 'src']:
        files.update(p for p in directory.rglob('*')
                     if p.is_file() and p.suffix in {'.rs', '.toml', '.lock', '.bin'})
    files.update(HERE / name for name in ['Cargo.toml', 'Cargo.lock', 'protocol.json',
                                        'reproduce.py', 'README.md'])
    files.update((HERE / 'src').rglob('*.rs'))
    require(all(p.is_file() for p in files), 'Source manifest contains a missing file')
    return {str(p.relative_to(NATIVE)): sha(p.read_bytes()) for p in sorted(files)}


def validate_run(raw, protocol, process_index):
    require(raw['schema'] == 'gabriel.conditioned-walk.measurements.v1', 'Wrong schema')
    require(raw['protocol'] == protocol, 'Embedded protocol differs from frozen protocol')
    require(raw['process_index'] == process_index, 'Wrong process index')
    require(len(raw['cases']) == len(protocol['cases']), 'Wrong case count')
    for case_index, (row, case) in enumerate(zip(raw['cases'], protocol['cases'])):
        require(row['case'] == case, 'Case descriptor mismatch')
        require(row['auto_backend'] == case['expected_auto'], 'Wrong Auto dispatch')
        require(row['spectral_backend'] == 'spectral', 'Forced Spectral changed dispatch')
        validation = row['validation']
        require(validation['checked_real_components'] == 2 * case['n'] * len(protocol['times']),
                'Not every returned component was checked')
        require(validation['max_component_tolerance_fraction'] <= 1, 'Component tolerance exceeded')
        require(validation['max_norm_error'] <= protocol['norm_absolute_tolerance'], 'Norm tolerance exceeded')
        require(len(validation['states']) == len(protocol['times']), 'Missing validation states')
        for state, t in zip(validation['states'], protocol['times']):
            require(state['time'] == t, 'Validation time differs')
            require(len(state['spectral']) == len(state['auto']) == case['n'], 'Wrong state dimension')
            for s, a in zip(state['spectral'], state['auto']):
                require(len(s) == len(a) == 2, 'Malformed complex value')
                for vs, va in zip(s, a):
                    require(math.isfinite(vs) and math.isfinite(va), 'Nonfinite state')
                    allowance = (protocol['component_absolute_tolerance']
                                 + protocol['component_relative_tolerance'] * max(abs(vs), abs(va)))
                    require(abs(vs - va) <= allowance, 'Saved state violates tolerance')
            for name in ['spectral', 'auto']:
                norm = sum(re * re + im * im for re, im in state[name])
                require(abs(norm - row['initial_norm_squared']) <= protocol['norm_absolute_tolerance'],
                        'Saved state violates norm bound')
        for category in ['plan_setup', 'state_preparation', 'query_measurements']:
            require(len(row[category]) == protocol['batches_per_process'], 'Wrong batch count')
            for batch, sample in enumerate(row[category]):
                require(sample['batch'] == batch, 'Wrong batch index')
                expected_order = (process_index + case_index + batch) % 2 == 0
                require(sample['spectral_first'] == expected_order, 'Pair order differs')
                require(sample['spectral_ns'] > 0 and sample['auto_ns'] > 0, 'Nonpositive timing')
                if category == 'query_measurements':
                    require(sample['queries'] == case['queries_per_batch'], 'Wrong query count')
                    s, a = sample['spectral_checksum'], sample['auto_checksum']
                    require(math.isfinite(s) and math.isfinite(a), 'Nonfinite checksum')
                    allowance = (protocol['checksum_absolute_tolerance']
                                 + protocol['checksum_relative_tolerance'] * max(abs(s), abs(a)))
                    require(abs(s - a) <= allowance, 'Timed checksum violates tolerance')


def summarize(runs, protocol):
    summaries = []
    for case_index, case in enumerate(protocol['cases']):
        process_rows = [run['cases'][case_index] for run in runs]
        require(len({row['input_fingerprint'] for row in process_rows}) == 1,
                'Inputs changed between processes')
        phases = {}
        for category in ['plan_setup', 'state_preparation', 'query_measurements']:
            per_process = []
            for index, row in enumerate(process_rows):
                samples = row[category]
                per_process.append({
                    'process_index': index,
                    'median_paired_spectral_over_auto': statistics.median(
                        sample['spectral_ns'] / sample['auto_ns'] for sample in samples),
                    'median_spectral_ns': statistics.median(s['spectral_ns'] for s in samples),
                    'median_auto_ns': statistics.median(s['auto_ns'] for s in samples),
                })
            ratios = [r['median_paired_spectral_over_auto'] for r in per_process]
            divisor = case['queries_per_batch'] if category == 'query_measurements' else 1
            phases[category] = {
                'processes': per_process,
                'median_process_paired_ratio': statistics.median(ratios),
                'minimum_process_paired_ratio': min(ratios),
                'maximum_process_paired_ratio': max(ratios),
                'median_process_spectral_ns_per_operation': statistics.median(
                    r['median_spectral_ns'] / divisor for r in per_process),
                'median_process_auto_ns_per_operation': statistics.median(
                    r['median_auto_ns'] / divisor for r in per_process),
            }
        summaries.append({
            'case': case, 'input_fingerprint': process_rows[0]['input_fingerprint'],
            'phases': phases,
            'max_component_difference': max(row['validation']['max_component_difference'] for row in process_rows),
            'max_norm_error': max(row['validation']['max_norm_error'] for row in process_rows),
        })
    return {
        'schema': 'gabriel.conditioned-walk.summary.v1',
        'fresh_processes': len(runs), 'cases': summaries,
        'total_real_component_pairs_checked': sum(
            row['validation']['checked_real_components'] for run in runs for row in run['cases']),
        'total_timed_queries_per_backend': sum(
            sample['queries'] for run in runs for row in run['cases'] for sample in row['query_measurements']),
        'interpretation': protocol['summary'],
        'scope': 'Same-output conditioned full-vector API. No comparison to historical all-pairs CTQW, no whole-engine speed claim.',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    protocol = json.loads((HERE / 'protocol.json').read_text())
    env = os.environ.copy()
    removed = [key for key in list(env) if key.startswith('CARGO_PROFILE_') or key in {
        'RUSTFLAGS', 'CARGO_ENCODED_RUSTFLAGS', 'RUSTDOCFLAGS', 'RUSTC_WRAPPER', 'RUSTC_WORKSPACE_WRAPPER'}]
    for key in removed:
        env.pop(key)
    env['RUSTUP_TOOLCHAIN'] = protocol['toolchain']
    env['CARGO_BUILD_JOBS'] = str(protocol['build_jobs'])
    commands = []

    def run(command, name, timeout=1800):
        started = time.perf_counter()
        failure = None
        returncode = None
        stdout = stderr = b''
        try:
            result = subprocess.run(command, cwd=HERE, env=env, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, timeout=timeout)
            stdout, stderr, returncode = result.stdout, result.stderr, result.returncode
        except subprocess.TimeoutExpired as error:
            failure = repr(error)
            stdout, stderr = error.stdout or b'', error.stderr or b''
        except OSError as error:
            failure = repr(error)
        atomic(output / f'{name}.stdout', stdout)
        atomic(output / f'{name}.stderr', stderr)
        record = {
            'command': [str(a) for a in command], 'cwd': str(HERE), 'returncode': returncode,
            'failure': failure, 'wrapper_wall_seconds': time.perf_counter() - started,
            'wrapper_wall_is_benchmark_metric': False,
            'stdout': f'{name}.stdout', 'stderr': f'{name}.stderr',
            'stdout_bytes': len(stdout), 'stderr_bytes': len(stderr),
            'stdout_sha256': sha(stdout), 'stderr_sha256': sha(stderr),
        }
        write_json(output / f'{name}.command.json', record)
        commands.append(record)
        write_json(output / 'commands.json', commands)
        require(failure is None and returncode == 0, f'{name} failed; inspect captured stderr')
        return stdout

    frozen = None
    executable = None
    executable_hash = None
    status = {'complete': False}
    try:
        compiler = run(['rustc', '--version', '--verbose'], 'compiler')
        require(compiler.startswith(b'rustc 1.95.0 '), 'Compiler version does not match protocol')
        run(['cargo', '--version', '--verbose'], 'cargo')
        if not (HERE / 'Cargo.lock').is_file():
            run(['cargo', 'generate-lockfile', '--offline'], 'generate_lockfile')
        frozen = source_hashes()
        write_json(output / 'source_hashes_before.json', frozen)
        for name in ['Cargo.toml', 'Cargo.lock', 'protocol.json', 'reproduce.py', 'README.md']:
            shutil.copy2(HERE / name, output / ('frozen_' + name))
        shutil.copy2(HERE / 'src/main.rs', output / 'frozen_main.rs')
        cpuinfo = Path('/proc/cpuinfo')
        cpu_model = None
        if cpuinfo.exists():
            cpu_model = next((line.partition(':')[2].strip() for line in cpuinfo.read_text().splitlines()
                              if line.startswith('model name')), None)
        write_json(output / 'environment.json', {
            'platform': platform.platform(), 'python': platform.python_version(),
            'logical_cpus': os.cpu_count(), 'cpu_model': cpu_model,
            'affinity': sorted(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else None,
            'profile': protocol['profile'], 'removed_build_override_names': removed,
            'rustup_toolchain': env['RUSTUP_TOOLCHAIN'], 'cargo_build_jobs': env['CARGO_BUILD_JOBS'],
            'RAYON_NUM_THREADS': env.get('RAYON_NUM_THREADS'),
            'process_startup_is_timed': False, 'cpu_and_rss_counters_measured': False,
        })
        target = output / 'target'
        run(['cargo', 'build', '--release', '--locked', '--offline',
             '--target-dir', str(target)], 'build')
        suffix = '.exe' if os.name == 'nt' else ''
        executable_dir = output / 'executable'
        executable_dir.mkdir()
        executable = executable_dir / ('pse-conditioned-walk-benchmark' + suffix)
        shutil.copy2(target / 'release' / executable.name, executable)
        executable_hash = sha(executable.read_bytes())
        write_json(output / 'binary.json', {
            'relative_path': str(executable.relative_to(output)),
            'bytes': executable.stat().st_size, 'sha256': executable_hash,
        })
        runs = []
        for process_index in range(protocol['fresh_processes']):
            raw = run([str(executable), '--process-index', str(process_index)],
                      f'process_{process_index}', timeout=300)
            parsed = json.loads(raw)
            validate_run(parsed, protocol, process_index)
            runs.append(parsed)
            print(f'Validated fresh process {process_index + 1}/{protocol["fresh_processes"]}', flush=True)
        require(len({run['pid'] for run in runs}) == len(runs), 'Expected fresh, distinct process IDs')
        write_json(output / 'summary.json', summarize(runs, protocol))
        status['complete'] = True
    finally:
        if frozen is not None:
            after = source_hashes()
            write_json(output / 'source_hashes_after.json', after)
            status['sources_unchanged'] = after == frozen
            if after != frozen:
                status['complete'] = False
        if executable is not None and executable_hash is not None:
            status['executable_unchanged'] = sha(executable.read_bytes()) == executable_hash
            if not status['executable_unchanged']:
                status['complete'] = False
        stream_checks = []
        for record in commands:
            for stream in ['stdout', 'stderr']:
                raw = (output / record[stream]).read_bytes()
                stream_checks.append(len(raw) == record[stream + '_bytes']
                                     and sha(raw) == record[stream + '_sha256'])
        status['all_captured_streams_verified'] = all(stream_checks)
        status['captured_command_count'] = len(commands)
        status['complete'] = status['complete'] and status['all_captured_streams_verified']
        write_json(output / 'integrity.json', status)
    require(status['complete'], 'Execution incomplete or source/binary/output integrity failed')
    print(str(output / 'summary.json'))


if __name__ == '__main__':
    main()
