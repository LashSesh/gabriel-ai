"""Independent strict-batch contract and sealed owner-evidence verification.

The verifier does not import the benchmark collector or its aggregation code.
Reference certificate evaluation intentionally uses the frozen scalar solver;
that is an equivalence oracle, not a second independent mathematics proof.
All live SQLite work is confined to a private temporary directory.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import copy
from fractions import Fraction
import hashlib
import inspect
import json
from pathlib import Path
import shutil
import sqlite3
import statistics
import struct
import sys
import tempfile
import textwrap
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'reproduction'))
from gabriel_runtime.engine import Store
from gabriel_runtime import graph_reachability as scalar
from gabriel_runtime import batched_reachability as batched
from gabriel_runtime import window_certificate as certificate
import verify_window_reachability as mathematical

EXPECTED_EXECUTABLE = 'f47f01b1f14c53184ccd5abdf22e01865d750a7b513f7acd6ec1e1a6a833aa93'
DEFAULT_EXECUTABLE = ROOT / 'native_pse/benchmark-results/window_reachability/executable/engine_snapshot_linux_x86_64.bin'


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode('ascii')


def digest(value):
    return hashlib.sha256(wire(value)).hexdigest()


def sha(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def bits(value):
    return struct.pack('>d', float(value)).hex()


def independent_source_contract():
    """Compare the entire owner transition, isolating only the batch call."""
    class Normalize(ast.NodeTransformer):
        def visit_Attribute(self, node):
            self.generic_visit(node)
            if isinstance(node.value, ast.Name) and node.value.id == 'reference':
                return ast.copy_location(ast.Name(node.attr, ast.Load()), node)
            return node

    normalized = []
    for implementation in (scalar.GraphReachabilityAdapter, batched.BatchedReachabilityAdapter):
        function = ast.parse(textwrap.dedent(inspect.getsource(implementation.apply))).body[0]
        function = Normalize().visit(function)
        blocks = [node for node in function.body if isinstance(node, ast.Try)]
        require(len(blocks) == 1 and len(blocks[0].body) == 2, 'unexpected certificate try block')
        blocks[0].body[0].value = ast.Constant('certificate-list-equivalence-checked-separately')
        normalized.append(ast.dump(function, include_attributes=False))
    require(normalized[0] == normalized[1], 'owner transition changed beyond certificate production')
    for method in ('__init__', '_check_identity'):
        expressions = []
        for implementation in (scalar.GraphReachabilityAdapter, batched.BatchedReachabilityAdapter):
            parsed = ast.parse(textwrap.dedent(inspect.getsource(getattr(implementation, method))))
            expressions.append(ast.dump(Normalize().visit(parsed), include_attributes=False))
        require(expressions[0] == expressions[1], method + ' changed beyond qualified identity helpers')
    old, new = scalar._sources(), batched._sources()
    require(all(new.get(path) == value for path, value in old.items()), 'old production closure changed')
    require(set(new) - set(old) == set(batched.EXTRA_SOURCES), 'unexpected production closure extension')
    require(batched.BatchedReachabilityAdapter._invoke is scalar.GraphReachabilityAdapter._invoke,
            'native invocation must be inherited unchanged')
    require(batched.BatchedReachabilityAdapter._validate is scalar.GraphReachabilityAdapter._validate,
            'owner validation must be inherited unchanged')
    return {'whole_transition_ast_equal_outside_certificate_call': True,
            'constructor_and_guard_ast_equal_after_qualifier_normalization': True,
            'original_source_files': len(old), 'strict_source_files': len(new),
            'extra_sources': list(batched.EXTRA_SOURCES),
            'original_closure_digest': digest(old), 'strict_closure_digest': digest(new)}


def guarded_full_owner_probe(executable, expected_sha):
    """Execute two successive changing-source observations per profile.

    The spy calls the real checks. It records no timing and bypasses no guard.
    Changed sources and targets expose accidental cross-command preparation.
    """
    result = {}
    with tempfile.TemporaryDirectory(prefix='gabriel-independent-owner-', dir='/tmp') as directory:
        for profile, cls, name in (
                ('legacy_scalar', scalar.GraphReachabilityAdapter, scalar.ADAPTER),
                ('strict_batch', batched.BatchedReachabilityAdapter, batched.ADAPTER)):
            trace = []

            class Traced(cls):
                def _check_identity(self):
                    trace.append(sys._getframe(1).f_code.co_name)
                    return super()._check_identity()

            path = Path(directory) / (profile + '.sqlite')
            adapter = Traced(executable, expected_sha)
            owner = Store.create(path, {name: adapter})
            commands, receipts = [], []
            try:
                def submit(op, payload):
                    command = {'id': 'independent-' + str(len(commands)), 'contract': 'windows',
                               'op': op, 'at': len(commands), 'expected_head': owner.head,
                               'payload': payload}
                    receipt = owner.submit(command)
                    commands.append(command)
                    receipts.append(receipt)
                    return receipt

                submit('bind', {'adapter': name, 'config': scalar.CAPS})
                for phase in range(2):
                    n = 7
                    source = [{'entity': i, 're_bits': bits(i - 3 if phase else i + 1),
                               'im_bits': bits(2 - i if phase else i % 3)} for i in range(n)]
                    payload = {'batches': [list(range(n))], 'source': source,
                               'targets': [1, 3] if phase else [0, 2, 4, 6],
                               'threshold_bits': bits(0.4 if phase else 0.6),
                               'windows': [{'start_bits': bits(0), 'end_bits': bits(0)},
                                           {'start_bits': bits(-10), 'end_bits': bits(10)}]}
                    submit('observe', payload)
                head, events = owner.head, owner.budget['events']
                before_duplicate = list(trace)
                require(owner.submit(commands[-1]) == receipts[-1], 'duplicate receipt changed')
                require(trace == before_duplicate, 'duplicate unexpectedly reexecuted identity guard')
            finally:
                owner.close()
            original_hash = sha(path)
            execution_trace = list(trace)
            trace.clear()
            adapter = Traced(executable, expected_sha)
            with Store.open(path, {name: adapter}, expected_head=head, expected_events=events) as owner:
                require(owner.head == head and owner.budget['events'] == events, 'replay anchors changed')
            require(sha(path) == original_hash, 'replay modified closed database')
            result[profile] = {'execute_guard_trace': execution_trace, 'replay_guard_trace': trace[:],
                               'issue_hashes': [digest(r['result']['issue']) for r in receipts[1:]],
                               'issues': [r['result']['issue'] for r in receipts[1:]],
                               'own_head': head, 'own_event_count': events,
                               'closed_database_sha256': original_hash}
        old, new = result['legacy_scalar'], result['strict_batch']
        require(wire(old['issues']) == wire(new['issues']), 'full cross-profile issue bytes differ')
        require(old['execute_guard_trace'] == new['execute_guard_trace'], 'execution guard sites differ')
        require(old['replay_guard_trace'] == new['replay_guard_trace'], 'replay guard sites differ')
        require(old['execute_guard_trace'] == ['__init__', 'fingerprint', 'fingerprint']
                + ['fingerprint', '_invoke', '_invoke', 'apply', 'apply'] * 2,
                'unexpected execution guard schedule')
        require(old['replay_guard_trace'] == ['__init__', 'fingerprint']
                + ['_invoke', '_invoke', 'apply', 'apply'] * 2,
                'unexpected replay guard schedule')
        require(old['issues'][0]['certificates'][0]['model']['input_sha256'] !=
                old['issues'][1]['certificates'][0]['model']['input_sha256'],
                'probe failed to change prepared input identity')
        for profile in result:
            del result[profile]['issues']
    return {'passed': True, 'profiles': result, 'complete_owners_executed': 2,
            'separate_full_replays_executed': 2, 'cross_profile_issue_comparisons': 2,
            'certificate_comparisons': 4,
            'scope': 'Actual Engine + Store; two sequential observations with changed source and targets; no timing.'}


def verify_input_rules(inputs):
    """Regenerate the declared synthetic design without importing its generator."""
    payload = {k: v for k, v in inputs.items() if k != 'cohort_digest'}
    require(digest(payload) == inputs['cohort_digest'], 'input cohort digest mismatch')
    expected_keys = {(cohort, n, seed, count)
                     for cohort, nodes, counts in (
                         ('primary', (7, 13, 32, 64), (1, 4, 16, 32)),
                         ('controls', (7, 13), (1, 32)))
                     for n in nodes for seed in (20260927, 20261003) for count in counts}
    observed_keys, certificates = set(), {}
    numerical_checks = 0
    require(len(inputs['tasks']) == 40, 'wrong cohort size')
    for item in inputs['tasks']:
        cohort, n, seed, count = (item[k] for k in ('cohort', 'nodes', 'seed', 'windows'))
        key = cohort, n, seed, count
        require(key in expected_keys and key not in observed_keys, 'unexpected or duplicate fixture')
        observed_keys.add(key)
        require(item['task_id'] == f'{cohort}-n{n}-s{seed}-q{count}', 'task label mismatch')
        snapshot_bundle = inputs['snapshots'][item['snapshot_key']]
        native = snapshot_bundle['response']
        snapshot = scalar.laplacian_for_certificate(native)
        require(snapshot == snapshot_bundle['certificate_snapshot'], 'converted snapshot changed')
        source = []
        for i in range(n):
            raw = hashlib.sha256(f'gabriel-window-source/v1:{seed}:{n}:{i}'.encode('ascii')).digest()
            source.append({'entity': i, 're_bits': bits(3 + int.from_bytes(raw[:8], 'big') % 17 - 8),
                           'im_bits': bits(1 + int.from_bytes(raw[8:16], 'big') % 19 - 9)})
        targets = list(range(0, n, 2))
        batches = [list(range(n))] if cohort == 'primary' else [[i, i+1] for i in range(n-1)]
        require(snapshot_bundle['request'] == {'schema': scalar.SCHEMA, 'batches': batches},
                'native fixture request differs from design')
        if cohort == 'primary':
            model = certificate.prepare_model(snapshot, source, targets)
            require(model.omega > 0, 'primary has no positive clique frequency')
            threshold = min(Fraction(1), max(Fraction(0), model.a + (abs(model.b) + abs(model.c))/4))
            phase = ((Fraction(0), Fraction(1, 8)), (Fraction(1, 7), Fraction(17, 7)),
                     (Fraction(2), Fraction(4)), (Fraction(0), Fraction(8)))
            windows = [{'start_bits': bits((phase[j % 4][0] + 9*(j//4))/model.omega),
                        'end_bits': bits((phase[j % 4][1] + 9*(j//4))/model.omega)} for j in range(count)]
        else:
            threshold = Fraction(1, 2)
            windows = [{'start_bits': bits(j), 'end_bits': bits(j+1)} for j in range(count)]
        request = {'batches': batches, 'source': source, 'targets': targets,
                   'windows': windows, 'threshold_bits': bits(threshold)}
        require(item['payload'] == request and item['input_sha256'] == digest(request),
                'fixture differs from independently regenerated design')
        require(item['expected_snapshot'] == native['snapshot']['identity'], 'snapshot identity mismatch')
        expected = [certificate.certify_window(snapshot, source, targets, window['start_bits'],
                    window['end_bits'], request['threshold_bits']) for window in windows]
        if cohort == 'controls':
            require(all(c['status'] == 'out_of_scope' for c in expected), 'generic fixture is supported')
            # Decode independently through binary64.as_integer_ratio and exhibit
            # failure of the uniform-clique condition rather than relying on the
            # producer's scope label alone.
            lap = [[mathematical.wire(value) for value in row] for row in snapshot['laplacian_bits']]
            d, w = lap[0][0], -lap[0][1]
            require(d < 0 or w < 0 or any(lap[i][j] != (d if i == j else -w)
                    for i in range(n) for j in range(n)), 'control lacks a nonclique witness')
        else:
            for window, result in zip(windows, expected):
                mathematical.verify_analytic(snapshot, {'source': source, 'targets': targets,
                    **window, 'threshold_bits': request['threshold_bits']}, result)
                numerical_checks += 1
        certificates[item['task_id']] = expected
    require(observed_keys == expected_keys, 'fixture Cartesian product incomplete')
    return certificates, numerical_checks


def check_database_bytes(raw, record, profile_name):
    """Independently verify SQL journals, hash chain and final state from bytes."""
    db = sqlite3.connect(':memory:')
    try:
        db.deserialize(raw)
        require(db.execute('PRAGMA integrity_check').fetchone() == ('ok',), 'SQLite integrity check failed')
        rows = db.execute('SELECT header_text,head,event_count,byte_count,last_at FROM meta').fetchall()
        require(len(rows) == 1, 'invalid meta row count')
        header_text, head, events, byte_count, last_at = rows[0]
        header = json.loads(header_text)
        require(wire(header).decode('ascii') == header_text, 'noncanonical header')
        require(set(header['registry']) == {profile_name}, 'wrong journal profile')
        chain = digest(header)
        current_state = None
        command_bytes = 0
        commands = []
        sql_rows = db.execute('SELECT sequence,command_id,contract_id,command_text,record_text,receipt_text '
                              'FROM journal ORDER BY sequence').fetchall()
        require(len(sql_rows) == events == record['owner_events'] == 2, 'wrong event count')
        for seq, command_id, contract_id, command_text, record_text, receipt_text in sql_rows:
            command, event, receipt = map(json.loads, (command_text, record_text, receipt_text))
            require(all(wire(v).decode('ascii') == t for v, t in
                        ((command, command_text), (event, record_text), (receipt, receipt_text))),
                    'noncanonical stored JSON')
            require(seq == len(commands)+1 and command_id == command['id']
                    and contract_id == command['contract'], 'journal identity mismatch')
            require(command['expected_head'] == event['prior_head'] == chain, 'journal chain broken')
            require(event['command'] == command and event['sequence'] == seq, 'event command mismatch')
            if seq == 1:
                require(command['op'] == 'bind' and command['payload']['adapter'] == profile_name,
                        'incorrect bind command')
                current_state = {'config': copy.deepcopy(command['payload']['config']), 'batches': [],
                                 'issues': [], 'window_count': 0, 'last_snapshot': None}
                require(event['pre_state_hash'] is None, 'bind prestate must be absent')
            else:
                require(command['op'] == 'observe' and event['pre_state_hash'] == digest(current_state),
                        'observe prestate differs')
                issue = event['result']['issue']
                current_state['batches'].extend(command['payload']['batches'])
                current_state['issues'].append(issue)
                current_state['window_count'] += len(command['payload']['windows'])
                current_state['last_snapshot'] = issue['native_snapshot']['snapshot']
            require(event['post_state_hash'] == digest(current_state), 'stored poststate differs')
            chain = digest({k: v for k, v in event.items() if k != 'hash'})
            require(chain == event['hash'] == receipt['head'], 'event hash differs')
            require(receipt == {'sequence': seq, 'command_id': command_id, 'contract': contract_id,
                                'result': event['result'], 'head': chain}, 'receipt derivation differs')
            command_bytes += len(command_text.encode('ascii'))
            commands.append(command)
        require(commands == record['commands'] and receipt == record['receipt'], 'record differs from SQLite')
        require(head == chain == record['owner_head'] and command_bytes == byte_count and last_at == 1,
                'metadata anchors differ')
        contracts = db.execute('SELECT contract_id,adapter,config_text,state_text FROM contracts').fetchall()
        require(len(contracts) == 1 and contracts[0][:2] == (commands[-1]['contract'], profile_name),
                'contract binding differs')
        require(json.loads(contracts[0][2]) == current_state['config'] and
                json.loads(contracts[0][3]) == current_state, 'final reducer state differs')
    finally:
        db.close()


def stats(values):
    return {'median': statistics.median(values), 'minimum': min(values), 'maximum': max(values)}


def verify_archive(path, executable, expected_sha, replay):
    """Check every archived record and recompute every published ratio."""
    with zipfile.ZipFile(path) as archive, tempfile.TemporaryDirectory(
            prefix='gabriel-independent-archive-', dir='/tmp') as temporary:
        require(archive.testzip() is None, 'archive CRC failure')
        names = archive.namelist()
        require(len(names) == len(set(names)), 'duplicate archive entry')
        manifest = json.loads(archive.read('manifest.json'))
        require(set(names) == set(manifest) | {'manifest.json'}, 'archive manifest mismatch')
        for name, metadata in manifest.items():
            raw = archive.read(name)
            require(len(raw) == metadata['bytes'] and hashlib.sha256(raw).hexdigest() == metadata['sha256'],
                    'archive member digest mismatch: ' + name)
        inputs = json.loads(archive.read('inputs.json'))
        protocol = json.loads(archive.read('frozen_protocol.json'))
        frozen = json.loads(archive.read('freeze.json'))
        summary = json.loads(archive.read('summary.json'))
        require(digest({k: v for k, v in frozen.items() if k != 'freeze_digest'}) == frozen['freeze_digest'],
                'freeze digest mismatch')
        require(hashlib.sha256(archive.read('inputs.json')).hexdigest() == frozen['input_file_sha256'],
                'frozen input file mismatch')
        require(hashlib.sha256(archive.read('frozen_protocol.json')).hexdigest() ==
                inputs['protocol_sha256'] == frozen['protocol_sha256'], 'protocol digest mismatch')
        require([v['name'] for v in protocol['variants']] == ['legacy_scalar', 'strict_batch'],
                'unexpected profile cohort')
        require(frozen['executable_sha256'] == inputs['executable_sha256'] == expected_sha,
                'executable binding mismatch')
        for relative, expected in frozen['source_sha256'].items():
            require(sha(ROOT / relative) == expected, 'production/collector source drift: ' + relative)
        require(scalar._arithmetic_identity() == frozen['arithmetic_identity'], 'arithmetic identity drift')
        expected_certificates, numerical_checks = verify_input_rules(inputs)
        task_by_id = {task['task_id']: task for task in inputs['tasks']}
        records, replays, workers, replay_count, certificate_count = [], [], [], 0, 0
        for index in range(3):
            worker = json.loads(archive.read(f'worker_{index}/worker.json'))
            workers.append(worker)
            require(worker['worker'] == index and worker['freeze_digest'] == frozen['freeze_digest']
                    and worker['source_sha256'] == frozen['source_sha256']
                    and worker['arithmetic_identity'] == frozen['arithmetic_identity']
                    and worker['cohort_digest'] == inputs['cohort_digest'], 'worker freeze binding changed')
            require(len(worker['records']) == len(worker['revalidation_replays']) == 80,
                    'incomplete worker output')
            offset = index % 40
            order = inputs['tasks'][offset:] + inputs['tasks'][:offset]
            if index % 2:
                order.reverse()
            expected_order = []
            original_index = {task['task_id']: i for i, task in enumerate(inputs['tasks'])}
            for task in order:
                variants = ['legacy_scalar', 'strict_batch']
                if (index + original_index[task['task_id']]) % 2:
                    variants.reverse()
                expected_order.extend({'task_id': task['task_id'], 'variant': variant} for variant in variants)
            require(worker['order'] == expected_order, 'prespecified order changed')
            for position, record in enumerate(worker['records']):
                require({k: record[k] for k in ('task_id', 'variant')} == expected_order[position]
                        and record['worker'] == index and record['order_position'] == position,
                        'record order binding changed')
                require(record == json.loads(archive.read(f'worker_{index}/task_{position:03d}.json')),
                        'duplicate record representations differ')
                task = task_by_id[record['task_id']]
                require(all(record[k] == task[k] for k in ('cohort', 'nodes', 'seed', 'windows', 'input_sha256')),
                        'record fixture metadata differs')
                require(type(record['elapsed_ns']) is int and record['elapsed_ns'] > 0
                        and all(type(v) is int and v >= 0 for v in record['phase_ns'].values())
                        and sum(record['phase_ns'].values()) == record['elapsed_ns'], 'invalid timing decomposition')
                for key, value in (('commands_sha256', record['commands']),
                                   ('receipt_sha256', record['receipt'])):
                    require(record[key] == digest(value), key + ' mismatch')
                issue = record['receipt']['result']['issue']
                require(digest(issue) == record['issue_sha256'] and
                        digest(issue['certificates']) == record['certificate_sha256'], 'issue digest mismatch')
                require(digest({k: v for k, v in issue.items() if k != 'digest'}) == issue['digest'],
                        'issue internal digest mismatch')
                require(issue['request'] == task['payload'] and issue['owner_receipt_at'] == 1
                        and issue['batch_count'] == len(task['payload']['batches']), 'issue request mismatch')
                require(issue['native_snapshot'] == inputs['snapshots'][task['snapshot_key']]['response'],
                        'actual Engine output differs from fixture')
                require(wire(issue['certificates']) == wire(expected_certificates[task['task_id']]),
                        'complete scalar certificate bytes differ')
                require(record['commands'][1]['payload'] == task['payload'], 'submitted input differs')
                raw = archive.read(f"worker_{index}/{record['database_filename']}")
                require(len(raw) == record['database_bytes'] and hashlib.sha256(raw).hexdigest() ==
                        record['database_sha256'], 'database identity mismatch')
                profile_name = scalar.ADAPTER if record['variant'] == 'legacy_scalar' else batched.ADAPTER
                check_database_bytes(raw, record, profile_name)
                if replay:
                    local = Path(temporary) / f'{index}-{position}.sqlite'
                    local.write_bytes(raw)
                    cls = scalar.GraphReachabilityAdapter if record['variant'] == 'legacy_scalar' else batched.BatchedReachabilityAdapter
                    adapter = cls(executable, expected_sha)
                    with Store.open(local, {profile_name: adapter}, expected_head=record['owner_head'],
                                    expected_events=record['owner_events']) as owner:
                        require(owner.head == record['owner_head'] and owner.budget['events'] == 2,
                                'independent replay anchors differ')
                    require(sha(local) == record['database_sha256'], 'independent replay changed database')
                    local.unlink()
                    replay_count += 1
                certificate_count += task['windows']
                records.append(record)
            for position, audit in enumerate(worker['revalidation_replays']):
                require(audit == json.loads(archive.read(f'worker_{index}/replay_{position:03d}.json')),
                        'duplicate replay representations differ')
                require(all(audit[k] is True for k in ('semantic_replay', 'external_anchors_checked',
                                                      'closed_database_unchanged')) and audit['elapsed_ns'] > 0,
                        'unsuccessful collector replay')
                require(audit['worker'] == index and {k: audit[k] for k in ('task_id', 'variant')} ==
                        expected_order[position], 'replay fixture binding differs')
                replays.append(audit)
            print(json.dumps({'independent_worker_checked': index, 'databases': 80,
                              'native_replays_executed': replay_count}), flush=True)
        require(len({worker['pid'] for worker in workers}) == 3, 'workers are not distinct processes')
        require(summary['fresh_worker_pids'] == [worker['pid'] for worker in workers]
                and summary['freeze_digest'] == frozen['freeze_digest']
                and summary['cohort_digest'] == inputs['cohort_digest'], 'summary provenance differs')
        require(len(summary['command_records']) == 3, 'missing worker process record')
        for index, command_record in enumerate(summary['command_records']):
            require(command_record == json.loads(archive.read(f'worker_{index}.command.json'))
                    and command_record['worker'] == index and command_record['returncode'] == 0,
                    'worker process record differs')
            for key in ('stdout', 'stderr'):
                require(hashlib.sha256(archive.read(command_record[key])).hexdigest() ==
                        command_record[key + '_sha256'], 'process stream digest differs')
        pairs = {}
        for record in records:
            key = record['worker'], record['task_id']
            require(record['variant'] not in pairs.setdefault(key, {}), 'duplicate paired observation')
            pairs[key][record['variant']] = record
        require(len(pairs) == 120 and all(set(pair) == {'legacy_scalar', 'strict_batch'}
                                       for pair in pairs.values()), 'missing paired observation')
        require(all(wire(pair['legacy_scalar']['receipt']['result']['issue']) ==
                    wire(pair['strict_batch']['receipt']['result']['issue']) for pair in pairs.values()),
                'cross-profile complete issue bytes differ')
        for task in inputs['tasks']:
            for variant in ('legacy_scalar', 'strict_batch'):
                selected = [r for r in records if r['task_id'] == task['task_id'] and r['variant'] == variant]
                require(len(selected) == 3 and len({wire(r['receipt']) for r in selected}) == 1,
                        'within-profile receipt nondeterminism')
        def ratios(predicate, variant='strict_batch'):
            values = [pair['legacy_scalar']['elapsed_ns'] / pair[variant]['elapsed_ns']
                      for pair in pairs.values() if predicate(pair['legacy_scalar'])]
            return {'pairs': len(values), **stats(values)}
        primary = ratios(lambda r: r['cohort'] == 'primary')
        groups = {key: {str(value): ratios(lambda r, key=key, value=value:
                    r['cohort'] == 'primary' and r[key] == value)
                    for value in sorted({t[key] for t in inputs['tasks'] if t['cohort'] == 'primary'})}
                  for key in ('nodes', 'seed', 'windows')}
        worker_ratios = {str(i): ratios(lambda r, i=i: r['cohort'] == 'primary' and r['worker'] == i)
                         for i in range(3)}
        demanding = ratios(lambda r: r['cohort'] == 'primary' and r['nodes'] in (32, 64)
                           and r['windows'] in (16, 32))
        profiles = {variant: ratios(lambda r: r['cohort'] == 'primary', variant)
                    for variant in ('legacy_scalar', 'strict_batch')}
        speed = primary['median'] > 1.10 and all(g['median'] > 1 for g in groups['nodes'].values())
        require(summary['primary_strict_batch_legacy_ratio'] == primary and summary['groups'] == groups
                and summary['worker_strict_batch_legacy_ratio'] == worker_ratios
                and summary['profile_legacy_ratio'] == profiles
                and summary['demanding_subgroup_ratio'] == demanding
                and summary['prespecified_speed_gate'] == speed
                and summary['demanding_subgroup_speed_gate'] == (demanding['median'] > 1.10),
                'published aggregation or speed gate differs')
        require(len(summary['tasks']) == 40 and {row['task_id'] for row in summary['tasks']} == set(task_by_id),
                'published task table is incomplete')
        for row in summary['tasks']:
            require(all(row[k] == task_by_id[row['task_id']][k] for k in ('cohort', 'nodes', 'seed', 'windows')),
                    'summary fixture metadata differs')
            for variant in ('legacy_scalar', 'strict_batch'):
                selected = [r['elapsed_ns'] for r in records if r['task_id'] == row['task_id'] and r['variant'] == variant]
                audits = [r['elapsed_ns'] for r in replays if r['task_id'] == row['task_id'] and r['variant'] == variant]
                pair_values = [pair['legacy_scalar']['elapsed_ns'] / pair[variant]['elapsed_ns']
                               for (_, task_id), pair in pairs.items() if task_id == row['task_id']]
                require(row['variants'][variant] == {'complete_ns': stats(selected),
                        'revalidation_replay_ns': stats(audits), 'paired_legacy_ratio': stats(pair_values)},
                        'per-task published statistics differ')
        require(summary['complete_tasks'] == len(records) == 240 and summary['windows'] == certificate_count
                and summary['revalidation_replays'] == len(replays) == 240, 'published total differs')
    return {'passed': True, 'archive_sha256': sha(path), 'sealed_files': len(manifest),
            'source_files_checked': len(frozen['source_sha256']), 'tasks': 40,
            'raw_complete_records': len(records), 'database_sql_and_hash_checks': len(records),
            'full_scalar_certificate_byte_comparisons': certificate_count,
            'independent_mathematical_fixture_certificate_checks': numerical_checks,
            'independent_mathematical_assertions': dict(sorted(mathematical.COUNTS.items())),
            'mathematical_verifier_sha256': sha(ROOT / 'reproduction/verify_window_reachability.py'),
            'independent_native_semantic_replays': replay_count,
            'primary_strict_batch_legacy_ratio': primary, 'groups': groups,
            'worker_ratios': worker_ratios, 'demanding_subgroup_ratio': demanding,
            'prespecified_speed_gate': speed, 'demanding_subgroup_speed_gate': demanding['median'] > 1.10,
            'scope': 'Independent input-rule regeneration, complex-evolution numerical verification '
                     'of each supported fixture certificate using the unchanged earlier verifier, '
                     'full scalar certificate-byte comparison, '
                     'SQL state/hash-chain reconstruction, all published aggregate recomputation; '
                     'actual native replay count reported separately.'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--executable', type=Path, default=DEFAULT_EXECUTABLE)
    parser.add_argument('--sha256', default=EXPECTED_EXECUTABLE)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--replay-all', action='store_true',
                        help='Independently execute all archived native semantic replays; no timing.')
    args = parser.parse_args()
    require(sha(args.executable) == args.sha256 == EXPECTED_EXECUTABLE, 'unexpected native executable')
    source = independent_source_contract()
    probe = guarded_full_owner_probe(args.executable, args.sha256)
    result = {'schema': 'gabriel.strict-batch-independent-verification/v1', 'passed': True,
              'source_contract': source, 'full_owner_probe': probe,
              'verifier_sha256': sha(__file__),
              'scope': 'Independent structural and full-owner equivalence verification; no performance measurement.'}
    if args.archive:
        result['archive_verification'] = verify_archive(args.archive, args.executable, args.sha256, args.replay_all)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, sort_keys=True, indent=2) + '\n')
    print(json.dumps({'passed': True, 'output': str(args.output)}))


if __name__ == '__main__':
    main()
