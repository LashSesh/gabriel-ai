#!/usr/bin/env python3
"""Reproduce complete durable graph-observer tasks in fresh worker processes.

The parent collector never compiles. An explicit, hash-identified native bridge
must already exist. Each measured task includes adapter identity checks, a fresh
SQLite Store, binding, every append, the scalar query and close. Workers execute
serially; statistical intervals and financial performance are not inferred.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import sqlite3
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gabriel_runtime.canonical import canonical, digest
from gabriel_runtime.engine import Store
from gabriel_runtime.graph_observer import ADAPTER, CAPS, GraphObserverAdapter, bits, number

PROTOCOL = ROOT / 'results/graph_observer_owner_protocol.json'
VARIANTS = ('spectral_full', 'auto_full', 'auto_region')
PAIRS = (('spectral_full', 'auto_full'), ('spectral_full', 'auto_region'),
         ('auto_full', 'auto_region'))


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def atomic_json(path, value):
    """Replace only our own derived output atomically, then read it back."""
    path = Path(path)
    temporary = path.with_name(path.name + '.writing')
    encoded = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()
    with temporary.open('xb') as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    if path.read_bytes() != encoded or json.loads(path.read_text()) != value:
        raise AssertionError('output readback mismatch: ' + str(path))


def source_manifest():
    paths = [Path(__file__).resolve(), PROTOCOL,
             ROOT / 'native_pse/benchmark-results/conditioned_engine/protocol.json',
             ROOT / 'native_pse/benchmark-results/conditioned_engine/src/main.rs']
    paths += list((ROOT / 'gabriel_runtime').glob('*.py'))
    native = ROOT / 'native_pse'
    paths += [native / 'Cargo.toml', native / 'Cargo.lock', native / 'examples/engine_observer.rs']
    paths += list((native / 'src').rglob('*.rs'))
    paths += list((native / 'crates').glob('*/Cargo.toml'))
    paths += list((native / 'crates').glob('*/src/**/*.rs'))
    paths += list((native / 'crates').glob('*/data/*.bin'))
    return {str(path.relative_to(ROOT)): sha256(path) for path in sorted(set(paths))}


def load_protocol():
    value = json.loads(PROTOCOL.read_text())
    if value['variants'] != list(VARIANTS):
        raise AssertionError('unexpected variant protocol')
    native = json.loads((ROOT / value['native_protocol']).read_text())
    for name in ('query_times', 'query_offsets_denominator', 'deadband', 'mass_absolute_tolerance'):
        if value[name] != native[name]:
            raise AssertionError('native and owner protocols disagree: ' + name)
    return value


def fixture(case, count, protocol):
    n = case['n']
    if case['family'] == 'clique':
        batches = [list(range(n))]
    elif case['family'] == 'path':
        batches = [[i, i + 1] for i in range(n - 1)]
    elif case['family'] == 'near_clique':
        batches = [list(range(n - 1)), list(range(n - 2)) + [n - 1]]
    else:
        raise ValueError('unknown fixture family')
    source = [(float(((17*i+3) % 29)-14), float(((11*i+5) % 23)-11)) for i in range(n)]
    squared_norm = sum(re*re + im*im for re, im in source)
    norm = math.sqrt(squared_norm)
    source = [(re/norm, im/norm) for re, im in source]
    normalized_norm = sum(re*re + im*im for re, im in source)
    targets = list(range(0, n, 2))
    threshold = sum((source[i][0]*source[i][0] + source[i][1]*source[i][1])/normalized_norm
                    for i in targets)
    query = {
        'source': [{'entity': i, 're_bits': bits(re), 'im_bits': bits(im)}
                   for i, (re, im) in enumerate(source)],
        'targets': targets,
        'times_bits': [bits(protocol['query_times'][i % len(protocol['query_times'])]
                            + (i // len(protocol['query_times']))
                            / protocol['query_offsets_denominator'])
                       for i in range(count)],
        'threshold_bits': bits(threshold), 'deadband_bits': bits(protocol['deadband']),
    }
    value = {'case': case, 'query_count': count, 'batches': batches, 'query': query}
    value['fingerprint'] = digest(value)
    return value


def run_task(directory, item, variant, trial, executable, executable_sha, keep_db):
    """The timed code path is complete from trusted adapter creation to close."""
    stem = f"{item['case']['id']}_q{item['query_count']}_trial{trial}_{variant}"
    db_path = directory / (stem + '.sqlite')
    if db_path.exists():
        raise ValueError('refusing to overwrite an owner database')
    commands = []
    owner = None
    start = time.perf_counter_ns()
    try:
        adapter = GraphObserverAdapter(executable, executable_sha)
        owner = Store.create(db_path, {ADAPTER: adapter})
        setup_end = time.perf_counter_ns()

        def submit(operation, payload):
            command = {'id': 'task-' + str(len(commands)+1), 'contract': 'graph',
                       'op': operation, 'at': len(commands),
                       'expected_head': owner.head, 'payload': payload}
            receipt = owner.submit(command)
            commands.append(command)
            return receipt

        submit('bind', {'adapter': ADAPTER, 'config': {'backend': variant, **CAPS}})
        bind_end = time.perf_counter_ns()
        for batch in item['batches']:
            submit('append_batch', {'entities': batch})
        append_end = time.perf_counter_ns()
        receipt = submit('query', item['query'])
        query_end = time.perf_counter_ns()
        owner.close()
        owner = None
        end = time.perf_counter_ns()
    finally:
        if owner is not None:
            owner.close()
    elapsed = end - start
    response = receipt['result']['issue']['native_result']
    values = response['query_results'][0]['values']
    if len(values) != item['query_count']:
        raise AssertionError('missing task answers')
    if response['engine']['faulted'] or response['engine']['commits'] != 0:
        raise AssertionError('observation profile unexpectedly faulted or committed')
    if response['engine']['ticks'] != len(item['batches']):
        raise AssertionError('batch history was not fully consumed')
    if response['engine']['vertices'] != item['case']['n']:
        raise AssertionError('wrong graph size')
    if response['snapshot']['walk_backend'] != (
            'spectral' if variant == 'spectral_full' else item['case']['expected_auto']):
        raise AssertionError('wrong execution backend')
    for requested, value in zip(item['query']['times_bits'], values):
        if value['time_bits'] != requested or not math.isfinite(number(value['mass_bits'])):
            raise AssertionError('invalid complete task output')
    record = {
        'case_id': item['case']['id'], 'query_count': item['query_count'],
        'trial': trial, 'variant': variant, 'input_fingerprint': item['fingerprint'],
        'elapsed_ns': elapsed, 'elapsed_seconds': elapsed / 1e9,
        'phase_ns': {'adapter_and_create': setup_end-start, 'bind': bind_end-setup_end,
                     'append_all': append_end-bind_end, 'query': query_end-append_end,
                     'close': end-query_end},
        'commands': commands, 'commands_sha256': digest(commands),
        'query_receipt': receipt, 'query_receipt_sha256': digest(receipt),
        'database_filename': db_path.name, 'database_bytes': db_path.stat().st_size,
        'database_sha256': sha256(db_path), 'database_retained': keep_db,
        'owner_events': receipt['sequence'], 'owner_head': receipt['head'],
    }
    if not keep_db:
        db_path.unlink()
    return record


def check_triple(records, tolerance):
    by_variant = {row['variant']: row for row in records}
    if set(by_variant) != set(VARIANTS) or len(records) != 3:
        raise AssertionError('incomplete paired triple')
    responses = {key: row['query_receipt']['result']['issue']['native_result']
                 for key, row in by_variant.items()}
    reference = responses['spectral_full']
    expected = reference['query_results'][0]['values']
    maximum = 0.0
    for response in responses.values():
        if response['snapshot']['identity'] != reference['snapshot']['identity']:
            raise AssertionError('comparison mixed graph snapshots')
        if response['engine'] != reference['engine']:
            raise AssertionError('comparison mixed engine histories')
        for left, right in zip(expected, response['query_results'][0]['values']):
            difference = abs(number(left['mass_bits'])-number(right['mass_bits']))
            maximum = max(maximum, difference)
            if difference > tolerance or left['decision'] != right['decision']:
                raise AssertionError('backend output or decision disagreement')
    return maximum


def worker(args):
    protocol = load_protocol()
    directory = Path(args.output).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    before = source_manifest()
    if sha256(args.executable) != args.sha256:
        raise AssertionError('executable identity mismatch before worker')
    inputs = [fixture(case, count, protocol) for case in protocol['cases']
              for count in protocol['query_counts']]
    atomic_json(directory / 'inputs.json', inputs)
    records = []
    max_difference = 0.0
    for case_index, case in enumerate(protocol['cases']):
        for count_index, count in enumerate(protocol['query_counts']):
            item = inputs[case_index*len(protocol['query_counts']) + count_index]
            for trial in range(protocol['triples_per_process']):
                offset = (args.process_index + case_index + count_index + trial) % 3
                order = list(VARIANTS[offset:] + VARIANTS[:offset])
                if (args.process_index + trial) % 2:
                    order.reverse()
                triple = []
                for position, variant in enumerate(order):
                    keep = (args.process_index == 0 and case_index == 0
                            and count_index == 0 and trial == 0 and variant == 'spectral_full')
                    record = run_task(directory, item, variant, trial,
                                      args.executable, args.sha256, keep)
                    record.update(process_index=args.process_index,
                                  order_position=position, variant_order=order)
                    triple.append(record)
                    records.append(record)
                    # Retain partial successful evidence if a later task fails.
                    atomic_json(directory / f'task_{len(records)-1:03d}.json', record)
                max_difference = max(max_difference,
                                     check_triple(triple, protocol['mass_absolute_tolerance']))
    # The retained database is semantically replayed only after every measured
    # task in this worker, avoiding an untimed replay between paired variants.
    for index, record in enumerate(records):
        if record['database_retained']:
            db_path = directory / record['database_filename']
            with Store.open(db_path, {ADAPTER: GraphObserverAdapter(args.executable, args.sha256)},
                            expected_head=record['owner_head'],
                            expected_events=record['owner_events']) as check:
                record['untimed_replay_audit'] = check.audit(
                    expected_head=record['owner_head'], expected_events=record['owner_events'])
            atomic_json(directory / f'task_{index:03d}.json', record)
    after = source_manifest()
    if before != after or sha256(args.executable) != args.sha256:
        raise AssertionError('source or executable changed during worker')
    report = {'schema': 'gabriel.graph-observer-owner.worker.v1',
              'process_index': args.process_index, 'pid': os.getpid(),
              'task_count': len(records), 'records': records,
              'maximum_mass_difference': max_difference,
              'source_guard_before': before, 'source_guard_after': after,
              'executable_sha256': args.sha256,
              'protocol_sha256': sha256(PROTOCOL)}
    atomic_json(directory / 'worker.json', report)
    print(json.dumps({'process_index': args.process_index, 'pid': os.getpid(),
                      'task_count': len(records), 'maximum_mass_difference': max_difference},
                     sort_keys=True))


def summarize(workers, protocol):
    rows = []
    for case in protocol['cases']:
        for count in protocol['query_counts']:
            processes = []
            for worker_result in workers:
                selected = [record for record in worker_result['records']
                            if record['case_id'] == case['id'] and record['query_count'] == count]
                pairs = {f'{a}_over_{b}': [] for a, b in PAIRS}
                per_variant = {v: [] for v in VARIANTS}
                for trial in range(protocol['triples_per_process']):
                    triple = [record for record in selected if record['trial'] == trial]
                    check_triple(triple, protocol['mass_absolute_tolerance'])
                    by_variant = {record['variant']: record for record in triple}
                    for variant, record in by_variant.items():
                        per_variant[variant].append(record['elapsed_ns'])
                    for a, b in PAIRS:
                        pairs[f'{a}_over_{b}'].append(
                            by_variant[a]['elapsed_ns']/by_variant[b]['elapsed_ns'])
                processes.append({'process_index': worker_result['process_index'],
                                  'paired_ratios': pairs,
                                  'median_paired_ratios': {k: statistics.median(v) for k,v in pairs.items()},
                                  'median_ns': {k: statistics.median(v) for k,v in per_variant.items()}})
            aggregate = {}
            for a, b in PAIRS:
                key = f'{a}_over_{b}'
                medians = [p['median_paired_ratios'][key] for p in processes]
                aggregate[key] = {'median': statistics.median(medians),
                                  'minimum': min(medians), 'maximum': max(medians)}
            rows.append({'case': case, 'query_count': count, 'processes': processes,
                         'paired_ratio_summary': aggregate,
                         'median_process_ns': {v: statistics.median([p['median_ns'][v] for p in processes])
                                               for v in VARIANTS}})
    return {'schema': 'gabriel.graph-observer-owner.summary.v1', 'cases': rows,
            'fresh_processes': len(workers), 'total_tasks': sum(w['task_count'] for w in workers),
            'maximum_mass_difference': max(w['maximum_mass_difference'] for w in workers)}


def collect(args):
    protocol = load_protocol()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    executable = Path(args.executable).resolve(strict=True)
    if sha256(executable) != args.sha256:
        raise AssertionError('explicit executable hash does not match')
    before = source_manifest()
    atomic_json(output / 'source_guard_before.json', before)
    atomic_json(output / 'protocol.json', protocol)
    atomic_json(output / 'environment.json', {
        'python': sys.version, 'python_executable': sys.executable,
        'platform': platform.platform(), 'machine': platform.machine(),
        'sqlite_version': sqlite3.sqlite_version, 'collector_pid': os.getpid(),
        'executable': str(executable), 'executable_sha256': args.sha256,
        'executable_bytes': executable.stat().st_size,
        'build_metadata': json.loads(Path(args.build_metadata).read_text()) if args.build_metadata else None,
        'timing_clock': 'time.perf_counter_ns',
        'worker_environment_overrides': {'PYTHONHASHSEED': '0', 'OMP_NUM_THREADS': '1',
                                         'OPENBLAS_NUM_THREADS': '1'},
    })
    environment = os.environ.copy()
    environment.update(PYTHONHASHSEED='0', OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1')
    workers = []
    command_files = []
    try:
        for process_index in range(protocol['fresh_processes']):
            stem = f'process_{process_index}'
            argv = [sys.executable, str(Path(__file__).resolve()), 'worker',
                    '--output', str(output / stem), '--executable', str(executable),
                    '--sha256', args.sha256, '--process-index', str(process_index)]
            start = time.perf_counter_ns()
            with (output / (stem+'.stdout')).open('xb') as out, (output / (stem+'.stderr')).open('xb') as err:
                process = subprocess.run(argv, stdout=out, stderr=err, cwd=ROOT,
                                         env=environment, check=False, shell=False)
            record = {'process_index': process_index, 'argv': argv, 'cwd': str(ROOT),
                      'returncode': process.returncode,
                      'wall_ns': time.perf_counter_ns()-start,
                      'stdout': stem+'.stdout', 'stderr': stem+'.stderr',
                      'stdout_sha256': sha256(output/(stem+'.stdout')),
                      'stderr_sha256': sha256(output/(stem+'.stderr'))}
            filename = output / (stem+'.command.json')
            atomic_json(filename, record)
            command_files.append(filename)
            if process.returncode:
                raise RuntimeError('worker failed; retained ' + stem + '.stderr')
            workers.append(json.loads((output/stem/'worker.json').read_text()))
        if len({w['pid'] for w in workers}) != protocol['fresh_processes']:
            raise AssertionError('fresh worker process identities are not distinct')
        atomic_json(output/'summary.json', summarize(workers, protocol))
    finally:
        after = source_manifest()
        atomic_json(output/'source_guard_after.json', after)
        # Build the complete index from closed individual record files, not a
        # potentially stale in-memory aggregate. Do not alter primary records.
        command_files = sorted(output.glob('process_*.command.json'))
        commands = [{'file': path.name, 'sha256': sha256(path),
                     'record': json.loads(path.read_text())} for path in command_files]
        atomic_json(output/'commands.json', commands)
        index = json.loads((output/'commands.json').read_text())
        if [row['file'] for row in index] != [p.name for p in command_files]:
            raise AssertionError('command index did not retain every individual record')
        atomic_json(output/'integrity.json', {
            'sources_unchanged': before == after,
            'executable_unchanged': sha256(executable) == args.sha256,
            'individual_command_count': len(command_files), 'indexed_command_count': len(index),
            'successful_workers': len(workers), 'expected_workers': protocol['fresh_processes'],
        })
        if before != after or sha256(executable) != args.sha256:
            raise AssertionError('source or executable changed during collection')
    print(json.dumps({'status': 'passed', 'output': str(output),
                      'tasks': sum(w['task_count'] for w in workers)}, sort_keys=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('collect', 'worker'))
    parser.add_argument('--output', required=True)
    parser.add_argument('--executable', required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--build-metadata')
    parser.add_argument('--process-index', type=int, default=0)
    args = parser.parse_args()
    (collect if args.operation == 'collect' else worker)(args)


if __name__ == '__main__':
    main()
