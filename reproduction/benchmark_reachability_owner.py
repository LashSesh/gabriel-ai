#!/usr/bin/env python3
"""Absolute complete-Store costs for eight frozen four-window requests.

No competing Store profile is timed, so this collector reports no owner speedup.
Live databases and all captures must be under /tmp. Execution is opt-in.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gabriel_runtime.canonical import canonical, digest
from gabriel_runtime.engine import Store
from gabriel_runtime.graph_reachability import (
    ADAPTER, CAPS, GraphReachabilityAdapter, _sources, _arithmetic_identity,
    window_certificate)

SCHEMA = 'gabriel.reachability-owner-benchmark/v1'
COHORT_DIGEST = '0edec494f8ea6c9f4ff4009712fabc10bca0d9b0a767a93a7939d5d2e4c23256'


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True)+'\n', encoding='ascii')
    temporary.replace(path)


def fixtures(path):
    data = json.loads(path.read_text())
    if data['schema'] != 'gabriel.window-cohort.v1' or data['cohort_digest'] != COHORT_DIGEST:
        raise ValueError('unexpected frozen cohort identity')
    cases = {c['case_id']: c for c in data['cases']}
    result = []
    for n in (7, 13, 32, 64):
        for region in (0, 1):
            prefix = f'primary-n{n}-s20260927-r{region}-q1/4'
            group = [cases[f'{prefix}-w{i}'] for i in range(4)]
            first = group[0]
            if any(c['cohort'] != 'primary' or c['snapshot_key'] != str(n)
                   or any(c[k] != first[k] for k in ('source', 'targets', 'threshold_bits'))
                   for c in group):
                raise ValueError('window group does not share one exact source, region and threshold')
            request = {'batches': data['snapshots'][str(n)]['request']['batches'],
                       'source': first['source'], 'targets': first['targets'],
                       'threshold_bits': first['threshold_bits'],
                       'windows': [{'start_bits': c['start_bits'], 'end_bits': c['end_bits']} for c in group]}
            result.append({'task_id': f'n{n}-r{region}', 'nodes': n, 'region': region,
                           'case_ids': [c['case_id'] for c in group], 'payload': request,
                           'input_sha256': digest(request),
                           'expected_snapshot': data['snapshots'][str(n)]['response']['snapshot']['identity']})
    return data, result


def run_task(directory, item, executable, expected_sha, position):
    path = directory / (item['task_id'] + '.sqlite')
    if path.exists():
        raise ValueError('refusing to overwrite an owner database')
    commands = []
    kernel_ns = []
    original = window_certificate.certify_window
    def measured_certificate(*args, **kwargs):
        start = time.perf_counter_ns()
        result = original(*args, **kwargs)
        kernel_ns.append(time.perf_counter_ns()-start)
        return result
    owner = None
    window_certificate.certify_window = measured_certificate
    try:
        start = time.perf_counter_ns()
        adapter = GraphReachabilityAdapter(executable, expected_sha)
        owner = Store.create(path, {ADAPTER: adapter})
        setup_end = time.perf_counter_ns()
        def submit(op, payload):
            command = {'id': 'task-' + str(len(commands)+1), 'contract': 'reachability',
                       'op': op, 'at': len(commands), 'expected_head': owner.head, 'payload': payload}
            receipt = owner.submit(command)
            commands.append(command)
            return receipt
        submit('bind', {'adapter': ADAPTER, 'config': CAPS})
        bind_end = time.perf_counter_ns()
        receipt = submit('observe', item['payload'])
        observe_end = time.perf_counter_ns()
        owner.close(); owner = None
        end = time.perf_counter_ns()
    finally:
        window_certificate.certify_window = original
        if owner is not None:
            owner.close()
    issue = receipt['result']['issue']
    if (len(issue['certificates']) != 4 or len(kernel_ns) != 4
            or issue['native_snapshot']['snapshot']['identity'] != item['expected_snapshot']
            or issue['native_snapshot']['engine']['faulted']
            or issue['native_snapshot']['engine']['commits'] != 0
            or any(c['status'] not in ('reachable', 'excluded', 'unknown', 'out_of_scope')
                   for c in issue['certificates'])):
        raise AssertionError('complete owner task output mismatch')
    elapsed = end-start
    record = {'task_id': item['task_id'], 'nodes': item['nodes'], 'region': item['region'],
              'order_position': position, 'case_ids': item['case_ids'],
              'input_sha256': item['input_sha256'], 'elapsed_ns': elapsed,
              'phase_ns': {'adapter_and_create': setup_end-start, 'bind': bind_end-setup_end,
                           'observe': observe_end-bind_end, 'close': end-observe_end},
              'certificate_calls_ns': kernel_ns, 'certificate_calls_total_ns': sum(kernel_ns),
              'certificate_calls_fraction': sum(kernel_ns)/elapsed,
              'commands': commands, 'commands_sha256': digest(commands),
              'receipt': receipt, 'receipt_sha256': digest(receipt),
              'owner_head': receipt['head'], 'owner_events': receipt['sequence'],
              'database_filename': path.name, 'database_bytes': path.stat().st_size,
              'database_sha256': sha(path)}
    if sum(record['phase_ns'].values()) != elapsed or sum(kernel_ns) > record['phase_ns']['observe']:
        raise AssertionError('timing scopes overlap incorrectly')
    return record


def worker(args, data, items):
    directory = Path(args.output).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    sources = _sources(); arithmetic = _arithmetic_identity()
    if sha(args.executable) != args.sha256:
        raise ValueError('executable identity mismatch')
    offset = args.worker % len(items)
    ordered = items[offset:] + items[:offset]
    if args.worker % 2:
        ordered.reverse()
    records = []
    for position, item in enumerate(ordered):
        record = run_task(directory, item, args.executable, args.sha256, position)
        record['worker'] = args.worker
        records.append(record)
        write(directory / f'task_{position:02d}.json', record)
    # Keep semantic replay separate from the timed create-to-close tasks.
    # Each audit reconstructs a new adapter and native process; Python startup
    # and module import are excluded, and this is not a cold filesystem cache.
    audits = []
    for record in records:
        path = directory / record['database_filename']
        start = time.perf_counter_ns()
        adapter = GraphReachabilityAdapter(args.executable, args.sha256)
        with Store.open(path, {ADAPTER: adapter}, expected_head=record['owner_head'],
                        expected_events=record['owner_events']) as owner:
            if owner.head != record['owner_head'] or owner.budget['events'] != record['owner_events']:
                raise AssertionError('cold replay anchors changed')
        end = time.perf_counter_ns()
        if sha(path) != record['database_sha256']:
            raise AssertionError('closed database changed after full replay')
        audit = {'task_id': record['task_id'], 'elapsed_ns': end-start,
                 'semantic_replay': True, 'external_anchors_checked': True,
                 'closed_database_unchanged': True}
        audits.append(audit)
        write(directory / f'audit_{len(audits)-1:02d}.json', audit)
    if sources != _sources() or arithmetic != _arithmetic_identity() or sha(args.executable) != args.sha256:
        raise AssertionError('production source, arithmetic, or executable identity changed')
    result = {'schema': SCHEMA, 'worker': args.worker, 'pid': os.getpid(),
              'task_order': [x['task_id'] for x in ordered], 'records': records,
              'cold_replays': audits, 'source_sha256': sources,
              'arithmetic_identity': arithmetic, 'executable_sha256': args.sha256,
              'input_file_sha256': sha(args.inputs), 'cohort_digest': data['cohort_digest']}
    write(directory / 'worker.json', result)
    print(json.dumps({'worker': args.worker, 'pid': os.getpid(), 'tasks': len(records),
                      'cold_replays': len(audits)}, sort_keys=True))


def collect(args, data, items):
    directory = Path(args.output).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    import flint
    arithmetic = _arithmetic_identity()
    arithmetic_root = Path(flint.__file__).resolve().parent.parent
    protocol = {'schema': SCHEMA, 'workers': 3, 'tasks_per_worker': 8, 'windows_per_task': 4,
                'selection': 'n=7,13,32,64; seed=20260927; regions=0,1; primary q=1/4; windows=0,1,2,3',
                'cohort_digest': data['cohort_digest'], 'input_file_sha256': sha(args.inputs),
                'collector_sha256': sha(__file__),
                'complete_task_scope': 'before fresh GraphReachabilityAdapter construction through Store.close; includes source/arithmetic/executable hashes, create, bind, command construction, one observe, native full replay, all certificates, canonical JSON, receipt construction and SQLite EXTRA commits',
                'excluded_from_complete_task': 'Python process startup/import, fixture selection, result validation, closed database hashes, evidence writes, separate cold replay',
                'certificate_scope': 'each actual certify_window call including prepare_model and Arb; measured inside observe; no instrumentation overhead subtraction',
                'cold_replay_scope': 'before new adapter construction through Store.open full semantic replay and close; excludes Python startup/import and final closed-database hashing; no cold-cache claim',
                'comparison': 'absolute costs only; no baseline Store ratio or overall speedup claim',
                'code_derived_work_per_complete_task': {
                    'native_launches': 1, 'engine_steps': 1, 'sqlite_commits': 3,
                    'source_hash_sweeps': 9, 'arithmetic_hash_sweeps': 9,
                    'executable_hash_sweeps': 8, 'certificate_calls': 4,
                    'source_bytes_per_sweep': sum((ROOT/p).stat().st_size for p in _sources()),
                    'arithmetic_bytes_per_sweep': sum((arithmetic_root/p).stat().st_size for p in arithmetic['files']),
                    'executable_bytes_per_sweep': Path(args.executable).stat().st_size,
                    'interpretation': 'logical bytes hashed, not physical storage reads'},
                'order': 'rotate eight tasks by worker index; reverse odd worker',
                'environment': {'python': sys.version, 'platform': sys.platform}}
    write(directory / 'protocol.json', protocol)
    write(directory / 'tasks.json', items)
    workers, command_records = [], []
    for index in range(3):
        command = [sys.executable, '-B', str(Path(__file__).resolve()),
                   '--inputs', str(Path(args.inputs).resolve()), '--executable', str(Path(args.executable).resolve()),
                   '--sha256', args.sha256, '--output', str(directory / f'worker_{index}'),
                   '--worker', str(index)]
        stdout = directory / f'worker_{index}.stdout'; stderr = directory / f'worker_{index}.stderr'
        with stdout.open('wb') as out, stderr.open('wb') as err:
            result = subprocess.run(command, stdout=out, stderr=err, check=False, shell=False)
        captured = {'worker': index, 'command': command, 'returncode': result.returncode,
                    'stdout': stdout.name, 'stderr': stderr.name,
                    'stdout_sha256': sha(stdout), 'stderr_sha256': sha(stderr)}
        command_records.append(captured); write(directory / f'worker_{index}.command.json', captured)
        if result.returncode:
            raise RuntimeError(f'worker {index} failed; completed evidence retained at {directory}')
        workers.append(json.loads((directory / f'worker_{index}/worker.json').read_text()))
    if len({w['pid'] for w in workers}) != 3:
        raise AssertionError('workers were not fresh processes')
    records = [r for w in workers for r in w['records']]
    if len(records) != 24:
        raise AssertionError('incomplete task count')
    if sha(__file__) != protocol['collector_sha256'] or sha(args.inputs) != protocol['input_file_sha256']:
        raise AssertionError('collector or frozen inputs changed during collection')
    summaries = []
    for item in items:
        selected = [r for r in records if r['task_id'] == item['task_id']]
        replay = [r for w in workers for r in w['cold_replays'] if r['task_id'] == item['task_id']]
        if len({r['receipt_sha256'] for r in selected}) != 1:
            raise AssertionError('identical frozen task produced different receipts')
        summaries.append({'task_id': item['task_id'], 'nodes': item['nodes'], 'region': item['region'],
                          'complete_ns': {'median': statistics.median(r['elapsed_ns'] for r in selected),
                                          'minimum': min(r['elapsed_ns'] for r in selected),
                                          'maximum': max(r['elapsed_ns'] for r in selected)},
                          'median_certificate_calls_ns': statistics.median(r['certificate_calls_total_ns'] for r in selected),
                          'median_certificate_calls_fraction': statistics.median(r['certificate_calls_fraction'] for r in selected),
                          'median_cold_replay_ns': statistics.median(r['elapsed_ns'] for r in replay),
                          'certificate_statuses': [c['status'] for c in selected[0]['receipt']['result']['issue']['certificates']]})
    report = {'schema': SCHEMA, 'status': 'passed', 'timed_tasks': 24,
              'timed_windows': 96, 'cold_replays': 24, 'fresh_worker_pids': [w['pid'] for w in workers],
              'scope': protocol, 'summary': summaries, 'command_records': command_records}
    write(directory / 'summary.json', report)
    manifest = {}
    for path in sorted(directory.rglob('*')):
        if path.is_file():
            manifest[str(path.relative_to(directory))] = {'sha256': sha(path), 'bytes': path.stat().st_size}
    write(directory / 'manifest.json', manifest)
    archive = directory / 'closed_databases_and_records.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
        for relative in list(manifest) + ['manifest.json']:
            bundle.write(directory / relative, relative)
    print(json.dumps({'status': 'passed', 'timed_tasks': 24, 'cold_replays': 24,
                      'summary': str(directory/'summary.json'), 'archive_sha256': sha(archive)}, sort_keys=True))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--inputs', default=str(ROOT/'results/window_reachability_study/inputs.json'))
    parser.add_argument('--executable', required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--worker', type=int)
    args = parser.parse_args()
    if not Path(args.output).resolve().is_relative_to(Path('/tmp')):
        raise ValueError('live benchmark databases must remain under /tmp')
    data, items = fixtures(Path(args.inputs))
    if data['executable_sha256'] != args.sha256 or sha(args.executable) != args.sha256:
        raise ValueError('snapshot executable differs from frozen cohort')
    if args.worker is None:
        collect(args, data, items)
    else:
        worker(args, data, items)


if __name__ == '__main__':
    main()
