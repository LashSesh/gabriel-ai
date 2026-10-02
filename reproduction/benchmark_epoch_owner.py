#!/usr/bin/env python3
"""Prespecified complete-Store comparison; native generation and timings explicit.

Live journals remain under /tmp.  No benchmark starts without --run.  Every
complete task constructs a new adapter and Store and every replay constructs
another new adapter.  Process startup and cache eviction are not measured.
"""
from __future__ import annotations

import argparse
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import struct
import subprocess
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gabriel_runtime.canonical import canonical, digest
from gabriel_runtime.graph_reachability import (
    CAPS, SCHEMA as SNAPSHOT_SCHEMA, _sources, _arithmetic_identity,
    laplacian_for_certificate)
from gabriel_runtime.window_certificate import prepare_model, OutOfScope

PROTOCOL = ROOT / 'results/epoch_owner_protocol.json'
SCHEMA = 'gabriel.epoch-owner.benchmark.v1'
VARIANTS = ('legacy_scalar', 'strict_batch')


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n', encoding='ascii')
    temporary.replace(path)


def bits(value):
    return struct.pack('>d', float(value)).hex()


def source_for(n, seed):
    result = []
    for entity in range(n):
        raw = hashlib.sha256(f'gabriel-window-source/v1:{seed}:{n}:{entity}'.encode('ascii')).digest()
        re = 3 + int.from_bytes(raw[:8], 'big') % 17 - 8
        im = 1 + int.from_bytes(raw[8:16], 'big') % 19 - 9
        result.append({'entity': entity, 're_bits': bits(re), 'im_bits': bits(im)})
    return result


def make_profile(variant, executable, expected_sha):
    # Production factory, never a benchmark-local replacement of adapter methods.
    from gabriel_runtime.batched_reachability import make_profile as factory
    return factory(variant, executable, expected_sha)


def source_hashes():
    result = _sources()
    for relative in ('gabriel_runtime/batched_reachability.py', 'gabriel_runtime/window_batch.py',
                     'reproduction/benchmark_epoch_owner.py', 'results/epoch_owner_protocol.json'):
        result[relative] = sha(ROOT / relative)
    return dict(sorted(result.items()))


def read_protocol():
    value = json.loads(PROTOCOL.read_text())
    if value['schema'] != 'gabriel.epoch-owner.protocol.v1':
        raise ValueError('unexpected protocol schema')
    if tuple(x['name'] for x in value['variants']) != VARIANTS:
        raise ValueError('unexpected profile names')
    return value


def invoke_snapshot(executable, expected_sha, batches):
    if sha(executable) != expected_sha:
        raise ValueError('snapshot executable mismatch')
    request = {'schema': SNAPSHOT_SCHEMA, 'batches': batches}
    result = subprocess.run([str(executable)], input=canonical(request).encode('ascii'),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
                            check=True, shell=False)
    if sha(executable) != expected_sha:
        raise ValueError('snapshot executable changed')
    response = json.loads(result.stdout)
    snapshot = laplacian_for_certificate(response)
    return {'request': request, 'response': response, 'certificate_snapshot': snapshot,
            'stdout': result.stdout.decode('ascii'), 'stderr': result.stderr.decode('ascii')}


def generate(args):
    p = read_protocol()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    executable = Path(args.executable).resolve(strict=True)
    snapshots = {}
    for cohort in ('primary', 'controls'):
        for n in p[cohort]['nodes']:
            batches = ([list(range(n))] if cohort == 'primary'
                       else [[i, i+1] for i in range(n-1)])
            snapshots[f'{cohort}-n{n}'] = invoke_snapshot(executable, args.sha256, batches)
    items = []
    for cohort in ('primary', 'controls'):
        for n in p[cohort]['nodes']:
            key = f'{cohort}-n{n}'
            snapshot = snapshots[key]['certificate_snapshot']
            for seed in p[cohort]['source_seeds']:
                source, targets = source_for(n, seed), list(range(0, n, 2))
                if cohort == 'primary':
                    model = prepare_model(snapshot, source, targets)
                    if model.omega <= 0:
                        raise ValueError('primary cohort requires positive clique frequency')
                    threshold = min(Fraction(1), max(Fraction(0), model.a + (abs(model.b)+abs(model.c))/4))
                    threshold_bits = bits(threshold)
                    windows = []
                    for j in range(32):
                        a, b = map(Fraction, p['primary']['phase_windows'][j % 4])
                        shift = 9*(j//4)
                        windows.append({'start_bits': bits((a+shift)/model.omega),
                                        'end_bits': bits((b+shift)/model.omega)})
                else:
                    try:
                        prepare_model(snapshot, source, targets)
                    except OutOfScope:
                        pass
                    else:
                        raise ValueError('control snapshot was unexpectedly in scope')
                    threshold_bits = p['controls']['threshold_bits']
                    windows = [{'start_bits': bits(j), 'end_bits': bits(j+1)} for j in range(32)]
                if len({canonical(w) for w in windows}) != 32:
                    raise ValueError('distinct-window fixture construction failed')
                for count in p[cohort]['windows_per_task']:
                    payload = {'batches': snapshots[key]['request']['batches'], 'source': source,
                               'targets': targets, 'windows': windows[:count],
                               'threshold_bits': threshold_bits}
                    items.append({'task_id': f'{cohort}-n{n}-s{seed}-q{count}', 'cohort': cohort,
                                  'nodes': n, 'seed': seed, 'windows': count,
                                  'snapshot_key': key, 'payload': payload,
                                  'input_sha256': digest(payload),
                                  'expected_snapshot': snapshots[key]['response']['snapshot']['identity']})
    if (sum(x['cohort']=='primary' for x in items) != 32 or len(items) != 40):
        raise AssertionError('frozen cohort count mismatch')
    payload = {'schema': SCHEMA, 'protocol_sha256': sha(PROTOCOL),
               'executable_sha256': args.sha256, 'snapshots': snapshots, 'tasks': items}
    payload['cohort_digest'] = digest(payload)
    write(output/'inputs.json', payload)
    (output/'frozen_protocol.json').write_bytes(PROTOCOL.read_bytes())
    print(json.dumps({'generated_tasks': len(items), 'cohort_digest': payload['cohort_digest'],
                      'timings_executed': False}, sort_keys=True))


def inputs(path):
    data = json.loads(Path(path).read_text())
    expected = data.pop('cohort_digest')
    if digest(data) != expected or data['protocol_sha256'] != sha(PROTOCOL):
        raise ValueError('input or protocol identity mismatch')
    data['cohort_digest'] = expected
    return data


def freeze(args):
    data = inputs(args.inputs)
    if sha(args.executable) != args.sha256 or data['executable_sha256'] != args.sha256:
        raise ValueError('executable identity mismatch')
    result = {'schema': SCHEMA, 'protocol_sha256': sha(PROTOCOL),
              'input_file_sha256': sha(args.inputs), 'cohort_digest': data['cohort_digest'],
              'source_sha256': source_hashes(), 'arithmetic_identity': _arithmetic_identity(),
              'executable_sha256': args.sha256, 'timings_executed': False}
    result['freeze_digest'] = digest(result)
    if Path(args.output).exists():
        raise ValueError('refusing to replace a freeze record')
    write(args.output, result)
    print(json.dumps({'freeze': args.output, 'freeze_digest': result['freeze_digest'],
                      'timings_executed': False}, sort_keys=True))


def verify_freeze(args):
    data = inputs(args.inputs)
    frozen = json.loads(Path(args.freeze).read_text())
    expected = frozen.pop('freeze_digest')
    if digest(frozen) != expected:
        raise ValueError('freeze record digest mismatch')
    frozen['freeze_digest'] = expected
    if (frozen['protocol_sha256'] != sha(PROTOCOL)
            or frozen['input_file_sha256'] != sha(args.inputs)
            or frozen['cohort_digest'] != data['cohort_digest']
            or frozen['source_sha256'] != source_hashes()
            or frozen['arithmetic_identity'] != _arithmetic_identity()
            or frozen['executable_sha256'] != args.sha256
            or sha(args.executable) != args.sha256):
        raise ValueError('execution no longer matches its frozen specification')
    return data, frozen


def run_task(directory, item, variant, executable, expected_sha, position):
    path = directory / (item['task_id']+'-'+variant+'.sqlite')
    if path.exists():
        raise ValueError('refusing to overwrite an owner database')
    owner = None
    commands = []
    start = time.perf_counter_ns()
    StoreClass, name, adapter = make_profile(variant, executable, expected_sha)
    owner = StoreClass.create(path, {name: adapter})
    setup_end = time.perf_counter_ns()
    try:
        def submit(op, payload):
            command = {'id': 'task-'+str(len(commands)+1), 'contract': 'reachability',
                       'op': op, 'at': len(commands), 'expected_head': owner.head, 'payload': payload}
            receipt = owner.submit(command)
            commands.append(command)
            return receipt
        submit('bind', {'adapter': name, 'config': CAPS})
        bind_end = time.perf_counter_ns()
        receipt = submit('observe', item['payload'])
        observe_end = time.perf_counter_ns()
        owner.close(); owner = None
        end = time.perf_counter_ns()
    finally:
        if owner is not None:
            owner.close()
    issue = receipt['result']['issue']
    if (len(issue['certificates']) != item['windows']
            or issue['native_snapshot']['snapshot']['identity'] != item['expected_snapshot']
            or issue['native_snapshot']['engine']['faulted']
            or issue['native_snapshot']['engine']['commits'] != 0):
        raise AssertionError('complete owner task output mismatch')
    if item['cohort'] == 'controls' and any(c['status'] != 'out_of_scope' for c in issue['certificates']):
        raise AssertionError('generic control did not preserve out_of_scope')
    elapsed = end-start
    result = {'task_id': item['task_id'], 'cohort': item['cohort'], 'nodes': item['nodes'],
              'seed': item['seed'], 'windows': item['windows'], 'variant': variant,
              'order_position': position, 'input_sha256': item['input_sha256'],
              'elapsed_ns': elapsed,
              'phase_ns': {'adapter_and_create': setup_end-start, 'bind': bind_end-setup_end,
                           'observe': observe_end-bind_end, 'close': end-observe_end},
              'commands': commands, 'commands_sha256': digest(commands),
              'receipt': receipt, 'receipt_sha256': digest(receipt),
              'issue_sha256': digest(issue), 'certificate_sha256': digest(issue['certificates']),
              'owner_head': receipt['head'], 'owner_events': receipt['sequence'],
              'database_filename': path.name, 'database_bytes': path.stat().st_size,
              'database_sha256': sha(path)}
    if sum(result['phase_ns'].values()) != elapsed:
        raise AssertionError('timing phases do not cover complete scope')
    return result


def replay_task(directory, record, executable, expected_sha):
    path = directory / record['database_filename']
    start = time.perf_counter_ns()
    StoreClass, name, adapter = make_profile(record['variant'], executable, expected_sha)
    with StoreClass.open(path, {name: adapter}, expected_head=record['owner_head'],
                         expected_events=record['owner_events']) as owner:
        if owner.head != record['owner_head'] or owner.budget['events'] != record['owner_events']:
            raise AssertionError('replay anchors changed')
    end = time.perf_counter_ns()
    if sha(path) != record['database_sha256']:
        raise AssertionError('closed database changed after semantic replay')
    return {'task_id': record['task_id'], 'variant': record['variant'], 'elapsed_ns': end-start,
            'semantic_replay': True, 'external_anchors_checked': True,
            'closed_database_unchanged': True}


def warmup_item(executable, expected_sha):
    payload = {'batches': [[0,1,2]], 'source': [{'entity': i, 're_bits': bits(1),
               'im_bits': bits(0)} for i in range(3)], 'targets': [0],
               'windows': [{'start_bits': bits(0), 'end_bits': bits(1)}],
               'threshold_bits': bits(Fraction(1,2))}
    snapshot = invoke_snapshot(executable, expected_sha, payload['batches'])
    return {'task_id': 'warmup-constant-n3', 'cohort': 'warmup', 'nodes': 3, 'seed': None,
            'windows': 1, 'payload': payload, 'input_sha256': digest(payload),
            'expected_snapshot': snapshot['response']['snapshot']['identity']}


def worker(args):
    if not args.run:
        raise ValueError('timing requires --run')
    data, frozen = verify_freeze(args)
    directory = Path(args.output).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    warmup = warmup_item(args.executable, args.sha256)
    warm_records = [run_task(directory, warmup, v, args.executable, args.sha256, -1) for v in VARIANTS]
    for record in warm_records:
        record['replay'] = replay_task(directory, record, args.executable, args.sha256)
    if len({r['issue_sha256'] for r in warm_records}) != 1:
        raise AssertionError('warmup profile issue mismatch')
    write(directory/'warmup.json', warm_records)
    items = data['tasks']
    offset = args.worker % len(items)
    ordered = items[offset:] + items[:offset]
    if args.worker % 2:
        ordered.reverse()
    indices = {item['task_id']: i for i, item in enumerate(items)}
    records, audits, order = [], [], []
    for item in ordered:
        index = indices[item['task_id']]
        offset = (args.worker + index) % len(VARIANTS)
        variants = VARIANTS[offset:] + VARIANTS[:offset]
        same_task = []
        for variant in variants:
            record = run_task(directory, item, variant, args.executable, args.sha256, len(records))
            record['worker'] = args.worker
            records.append(record); same_task.append(record)
            order.append({'task_id': item['task_id'], 'variant': variant})
            write(directory/f'task_{len(records)-1:03d}.json', record)
        if len({r['issue_sha256'] for r in same_task}) != 1:
            raise AssertionError('complete issue bytes differ across variants')
        for record in same_task:
            audit = replay_task(directory, record, args.executable, args.sha256)
            audit['worker'] = args.worker
            audits.append(audit)
            write(directory/f'replay_{len(audits)-1:03d}.json', audit)
    verify_freeze(args)
    result = {'schema': SCHEMA, 'worker': args.worker, 'pid': os.getpid(),
              'environment': {'python': sys.version, 'executable': sys.executable,
                              'platform': platform.platform()},
              'freeze_digest': frozen['freeze_digest'], 'source_sha256': frozen['source_sha256'],
              'arithmetic_identity': frozen['arithmetic_identity'],
              'executable_sha256': args.sha256, 'cohort_digest': data['cohort_digest'],
              'order': order, 'records': records, 'revalidation_replays': audits,
              'warmup': warm_records}
    write(directory/'worker.json', result)
    print(json.dumps({'worker': args.worker, 'pid': os.getpid(), 'tasks': len(records),
                      'revalidation_replays': len(audits)}, sort_keys=True))


def statistics_for(values):
    return {'median': statistics.median(values), 'minimum': min(values), 'maximum': max(values)}


def aggregate(data, workers, frozen, command_records):
    records = [r for w in workers for r in w['records']]
    audits = [r for w in workers for r in w['revalidation_replays']]
    if len(records) != 240 or len(audits) != 240 or len({w['pid'] for w in workers}) != 3:
        raise AssertionError('incorrect full task count, replay count or fresh process count')
    pairs = {}
    for record in records:
        key = record['worker'], record['task_id']
        if record['variant'] in pairs.setdefault(key, {}):
            raise AssertionError('duplicate profile measurement')
        pairs[key][record['variant']] = record
    if len(pairs) != 120 or any(set(group) != set(VARIANTS) for group in pairs.values()):
        raise AssertionError('missing matched task')
    if any(len({r['issue_sha256'] for r in group.values()}) != 1 for group in pairs.values()):
        raise AssertionError('profile semantic mismatch')
    for item in data['tasks']:
        matches = [r for r in records if r['task_id'] == item['task_id']]
        if len({r['issue_sha256'] for r in matches}) != 1:
            raise AssertionError('worker semantic nondeterminism')
        for variant in VARIANTS:
            if len({r['receipt_sha256'] for r in matches if r['variant'] == variant}) != 1:
                raise AssertionError('profile receipt nondeterminism')
    table = []
    for item in data['tasks']:
        row = {k: item[k] for k in ('task_id','cohort','nodes','seed','windows')}
        row['variants'] = {}
        for variant in VARIANTS:
            selected = [r for r in records if r['task_id']==item['task_id'] and r['variant']==variant]
            replays = [r for r in audits if r['task_id']==item['task_id'] and r['variant']==variant]
            ratios = [group['legacy_scalar']['elapsed_ns']/group[variant]['elapsed_ns']
                      for (_, task_id), group in pairs.items() if task_id == item['task_id']]
            row['variants'][variant] = {'complete_ns': statistics_for([r['elapsed_ns'] for r in selected]),
                                       'revalidation_replay_ns': statistics_for([r['elapsed_ns'] for r in replays]),
                                       'paired_legacy_ratio': statistics_for(ratios)}
        table.append(row)
    def ratio_group(select, variant='strict_batch'):
        values = [group['legacy_scalar']['elapsed_ns']/group[variant]['elapsed_ns']
                  for group in pairs.values() if select(group['legacy_scalar'])]
        return dict(pairs=len(values), **statistics_for(values))
    primary = ratio_group(lambda r:r['cohort']=='primary')
    groups = {key: {str(value): ratio_group(lambda r,key=key,value=value:
                r['cohort']=='primary' and r[key]==value)
                for value in sorted({x[key] for x in data['tasks'] if x['cohort']=='primary'})}
              for key in ('nodes','seed','windows')}
    by_worker = {str(i): ratio_group(lambda r,i=i:r['cohort']=='primary' and r['worker']==i) for i in range(3)}
    ablations = {v: ratio_group(lambda r:r['cohort']=='primary',v) for v in VARIANTS}
    speed = (primary['median']>1.10 and all(g['median']>1 for g in groups['nodes'].values())
             )
    demanding = ratio_group(lambda r:r['cohort']=='primary' and r['nodes'] in (32,64) and r['windows'] in (16,32))
    return {'schema': SCHEMA, 'freeze_digest': frozen['freeze_digest'],
            'cohort_digest': data['cohort_digest'], 'complete_tasks': len(records),
            'windows': sum(r['windows'] for r in records), 'revalidation_replays': len(audits),
            'fresh_worker_pids': [w['pid'] for w in workers],
            'issue_equivalence': True, 'within_profile_receipt_determinism': True,
            'primary_strict_batch_legacy_ratio': primary, 'groups': groups,
            'worker_strict_batch_legacy_ratio': by_worker, 'profile_legacy_ratio': ablations,
            'prespecified_speed_gate': speed,
            'demanding_subgroup_ratio': demanding, 'demanding_subgroup_speed_gate': demanding['median']>1.10,
            'correctness_gate': 'requires separately recorded negative controls and independent verification',
            'scope': read_protocol()['contract'], 'tasks': table, 'command_records': command_records}


def collect(args):
    if not args.run:
        raise ValueError('timing collection requires --run')
    data, frozen = verify_freeze(args)
    directory = Path(args.output).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    workers, command_records = [], []
    (directory/'frozen_protocol.json').write_bytes(PROTOCOL.read_bytes())
    (directory/'freeze.json').write_bytes(Path(args.freeze).read_bytes())
    (directory/'inputs.json').write_bytes(Path(args.inputs).read_bytes())
    for index in range(3):
        command = [sys.executable, '-B', str(Path(__file__).resolve()), 'worker', '--run',
                   '--inputs', str(Path(args.inputs).resolve()), '--freeze', str(Path(args.freeze).resolve()),
                   '--executable', str(Path(args.executable).resolve()), '--sha256', args.sha256,
                   '--output', str(directory/f'worker_{index}'), '--worker', str(index)]
        stdout, stderr = directory/f'worker_{index}.stdout', directory/f'worker_{index}.stderr'
        with stdout.open('wb') as out, stderr.open('wb') as err:
            result = subprocess.run(command, stdout=out, stderr=err, check=False, shell=False)
        captured = {'worker': index, 'command': command, 'returncode': result.returncode,
                    'stdout': stdout.name, 'stderr': stderr.name,
                    'stdout_sha256': sha(stdout), 'stderr_sha256': sha(stderr)}
        command_records.append(captured)
        write(directory/f'worker_{index}.command.json', captured)
        if result.returncode:
            raise RuntimeError(f'worker {index} failed; partial evidence retained at {directory}')
        workers.append(json.loads((directory/f'worker_{index}/worker.json').read_text()))
        verify_freeze(args)
    report = aggregate(data, workers, frozen, command_records)
    write(directory/'summary.json', report)
    manifest = {str(path.relative_to(directory)): {'sha256': sha(path), 'bytes': path.stat().st_size}
                for path in sorted(directory.rglob('*')) if path.is_file()}
    write(directory/'manifest.json', manifest)
    archive = directory/'closed_databases_and_records.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
        for relative in list(manifest)+['manifest.json']:
            bundle.write(directory/relative, relative)
    print(json.dumps({'complete_tasks': len([r for w in workers for r in w['records']]),
                      'prespecified_speed_gate': report['prespecified_speed_gate'],
                      'summary': str(directory/'summary.json'), 'archive_sha256': sha(archive)}, sort_keys=True))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('generate','freeze','worker','collect'))
    parser.add_argument('--inputs')
    parser.add_argument('--freeze')
    parser.add_argument('--executable', required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--worker', type=int)
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args()
    if args.action in ('worker','collect') and not Path(args.output).resolve().is_relative_to(Path('/tmp')):
        raise ValueError('live SQLite journals must remain outside automatic workspace mirroring, under /tmp')
    {'generate': generate, 'freeze': freeze, 'worker': worker, 'collect': collect}[args.action](args)


if __name__ == '__main__':
    main()
