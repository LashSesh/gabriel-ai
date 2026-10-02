#!/usr/bin/env python3
"""Functional native/Store integration checks; no performance claims."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gabriel_runtime.canonical import canonical
from gabriel_runtime.engine import Store
from gabriel_runtime.graph_observer import bits, _source_hashes
from gabriel_runtime.graph_reachability import (
    ADAPTER, CAPS, SCHEMA, GraphReachabilityAdapter, laplacian_for_certificate)


def command(owner, operation, payload, key):
    return {'id': key, 'contract': 'reachability', 'op': operation,
            'at': owner.budget['events'], 'expected_head': owner.head, 'payload': payload}


def request(n=3, batches=None, targets=None, threshold=0.0, windows=None):
    return {'batches': [list(range(n))] if batches is None else batches,
            'source': [{'entity': i, 're_bits': bits(1 if i == 0 else 0),
                        'im_bits': bits(0)} for i in range(n)],
            'targets': list(range(n)) if targets is None else targets,
            'windows': ([{'start_bits': bits(0), 'end_bits': bits(1)}]
                        if windows is None else windows),
            'threshold_bits': bits(threshold)}


def expect_rollback(owner, operation, payload, key):
    before = canonical(owner.export()), owner.head, owner.budget
    try:
        owner.submit(command(owner, operation, payload, key))
    except ValueError:
        pass
    else:
        raise AssertionError('invalid command accepted: ' + key)
    assert before == (canonical(owner.export()), owner.head, owner.budget), key


def check(directory, executable, expected_sha):
    before_v1 = _source_hashes()
    adapter = GraphReachabilityAdapter(executable, expected_sha)
    calls = []
    native_invoke = adapter._invoke
    def counted(batches):
        calls.append(copy.deepcopy(batches))
        return native_invoke(batches)
    adapter._invoke = counted
    db_path = directory / 'reachability.sqlite'
    with Store.create(db_path, {ADAPTER: adapter}) as owner:
        owner.submit(command(owner, 'bind', {'adapter': ADAPTER, 'config': CAPS}, 'bind'))
        first = request(targets=[])
        cmd = command(owner, 'observe', first, 'empty-region')
        receipt = owner.submit(cmd)
        issue = receipt['result']['issue']
        assert len(calls) == 1
        assert [c['status'] for c in issue['certificates']] == ['excluded']
        matrix = laplacian_for_certificate(issue['native_snapshot'])
        assert set(matrix['entities']) == {0, 1, 2}
        damaged = copy.deepcopy(issue['native_snapshot'])
        damaged['snapshot']['degree_bits'][0] = bits(123)
        try:
            laplacian_for_certificate(damaged)
        except ValueError:
            pass
        else:
            raise AssertionError('changed snapshot bytes accepted')
        swapped = copy.deepcopy(issue['native_snapshot'])
        vertices = swapped['snapshot']['vertices']
        vertices[0]['entity'], vertices[1]['entity'] = vertices[1]['entity'], vertices[0]['entity']
        assert swapped['snapshot']['identity'] == issue['native_snapshot']['snapshot']['identity']
        try:
            laplacian_for_certificate(swapped)
        except ValueError:
            pass
        else:
            raise AssertionError('swapped entity labels accepted under unchanged graph digest')
        saved_records = owner.export()['records']
        budget = owner.budget
        assert owner.submit(cmd) == receipt and owner.budget == budget and len(calls) == 1
        full = request(batches=[], windows=[
            {'start_bits': bits(-1), 'end_bits': bits(0)},
            {'start_bits': bits(0), 'end_bits': bits(2)}])
        reached = owner.submit(command(owner, 'observe', full, 'full-region'))
        assert [c['status'] for c in reached['result']['issue']['certificates']] == ['reachable', 'reachable']
        equal = owner.submit(command(owner, 'observe', request(batches=[], threshold=1), 'equality'))
        assert [c['status'] for c in equal['result']['issue']['certificates']] == ['excluded']
        assert owner.export()['records'][:len(saved_records)] == saved_records
        invalid = []
        def bad(name, change):
            value = request(batches=[]); change(value); invalid.append((name, value))
        bad('extra', lambda p: p.update(extra=1))
        bad('duplicate-source', lambda p: p['source'][1].update(entity=0))
        bad('unknown-source', lambda p: p['source'][1].update(entity=63))
        bad('nonfinite', lambda p: p['source'][0].update(re_bits='7ff0000000000000'))
        bad('zero-source', lambda p: [x.update(re_bits=bits(0), im_bits=bits(0)) for x in p['source']])
        bad('duplicate-target', lambda p: p.update(targets=[0, 0]))
        bad('unknown-target', lambda p: p.update(targets=[63]))
        bad('duplicate-batch', lambda p: p.update(batches=[[0, 0]]))
        bad('empty-batch', lambda p: p.update(batches=[[]]))
        bad('batch-cap', lambda p: p.update(batches=[[0]]*128))
        bad('threshold-range', lambda p: p.update(threshold_bits=bits(2)))
        bad('no-windows', lambda p: p.update(windows=[]))
        bad('reversed-window', lambda p: p['windows'][0].update(start_bits=bits(2)))
        bad('nonfinite-end', lambda p: p['windows'][0].update(end_bits='7ff8000000000000'))
        bad('window-total-cap', lambda p: p.update(windows=p['windows']*32))
        bad('invalid-second-member', lambda p: p['windows'].append({'start_bits': bits(2), 'end_bits': bits(1)}))
        call_count = len(calls)
        for name, payload in invalid:
            expect_rollback(owner, 'observe', payload, name)
        expect_rollback(owner, 'invalid-operation', {}, 'invalid-operation')
        assert len(calls) == call_count, 'invalid members performed native work'
        stale = command(owner, 'observe', request(batches=[]), 'stale')
        stale['expected_head'] = '0'*64
        snapshot = canonical(owner.export())
        try:
            owner.submit(stale)
        except ValueError:
            pass
        else:
            raise AssertionError('stale head accepted')
        assert canonical(owner.export()) == snapshot and len(calls) == call_count
        # Execution failures must roll back an otherwise valid atomic request.
        def failed_process(kind):
            def run(argv, **kwargs):
                if kind == 'timeout':
                    raise subprocess.TimeoutExpired(argv, kwargs['timeout'])
                if kind == 'nonzero':
                    kwargs['stderr'].write(b'controlled test rejection')
                    return subprocess.CompletedProcess(argv, 2)
                kwargs['stdout'].write(b'{}' if kind == 'malformed' else b' '*(4*1024*1024+1))
                return subprocess.CompletedProcess(argv, 0)
            return run
        for kind in ('timeout', 'nonzero', 'malformed', 'oversize-output'):
            with patch('gabriel_runtime.graph_reachability.subprocess.run', side_effect=failed_process(kind)):
                expect_rollback(owner, 'observe', request(batches=[]), 'failure-' + kind)
        with patch('gabriel_runtime.graph_reachability.window_certificate.certify_window',
                   side_effect=ValueError('controlled certificate failure')):
            expect_rollback(owner, 'observe', request(batches=[]), 'failure-certificate')
        anchor = {'head': owner.head, 'events': owner.budget['events']}
        journal = owner.export()
    relocated = directory / 'snapshot-relocated'
    shutil.copy2(executable, relocated)
    moved = GraphReachabilityAdapter(relocated, expected_sha)
    assert adapter.fingerprint() == moved.fingerprint()
    with Store.open(db_path, {ADAPTER: moved}, expected_head=anchor['head'],
                    expected_events=anchor['events']) as reopened:
        assert reopened.export() == journal
        replay = reopened.audit(expected_head=anchor['head'], expected_events=anchor['events'])
    with relocated.open('ab') as stream:
        stream.write(b'\x00')
    try:
        moved.fingerprint()
    except ValueError:
        pass
    else:
        raise AssertionError('changed executable accepted')
    relocated.unlink()
    key = next(iter(adapter.sources))
    original = adapter.sources[key]
    adapter.sources[key] = '0'*64
    try:
        adapter.fingerprint()
    except ValueError:
        pass
    else:
        raise AssertionError('source identity mismatch accepted')
    adapter.sources[key] = original
    with Store.create(directory / 'generic.sqlite', {ADAPTER: adapter}) as generic:
        generic.submit(command(generic, 'bind', {'adapter': ADAPTER, 'config': CAPS}, 'bind'))
        generic_receipt = generic.submit(command(generic, 'observe',
            request(batches=[[0, 1], [1, 2]], targets=[1], threshold=0.5), 'path'))
        assert generic_receipt['result']['issue']['certificates'][0]['status'] == 'out_of_scope'
    with Store.create(directory / 'soft-caps.sqlite', {ADAPTER: adapter}) as small:
        config = {'max_nodes': 2, 'max_batches': 1, 'max_windows': 1}
        small.submit(command(small, 'bind', {'adapter': ADAPTER, 'config': config}, 'bind'))
        expect_rollback(small, 'observe', request(), 'nodes')
        small.submit(command(small, 'observe', request(n=2), 'valid'))
        expect_rollback(small, 'observe', request(n=2, batches=[]), 'windows')
    job = {'schema': SCHEMA, 'batches': [[0, 1, 2]]}
    raw = canonical(job)
    malformed = {
        'unknown-field': canonical(dict(job, extra=0)).encode('ascii'),
        'duplicate-entity': canonical(dict(job, batches=[[0, 0]])).encode('ascii'),
        'empty-batch': canonical(dict(job, batches=[[]])).encode('ascii'),
        'batch-cap': canonical(dict(job, batches=[[0]]*129)).encode('ascii'),
        'out-of-range': canonical(dict(job, batches=[[64]])).encode('ascii'),
        'duplicate-key': raw.replace('{', '{"schema":"bad",', 1).encode('ascii'),
        'noncanonical': (' ' + raw).encode('ascii'),
        'oversize': b' '*(4*1024*1024+1),
    }
    for name, wire in malformed.items():
        result = subprocess.run([str(executable)], input=wire, capture_output=True, timeout=30)
        assert result.returncode != 0, name
    assert _source_hashes() == before_v1, 'v1 fingerprint source closure changed'
    return {'status': 'passed', 'schema': 'gabriel.graph-reachability.checks.v1',
            'invalid_atomic_commands': len(invalid)+1, 'invalid_members_no_native_work': True,
            'identical_retry': True, 'stale_head_rejected': True, 'issued_prefix_immutable': True,
            'cold_replay': replay, 'same_binary_relocation': True,
            'source_and_executable_identity_rejected': True,
            'snapshot_digest_reconstructed': True, 'swapped_entity_labels_rejected': True,
            'generic_out_of_scope': True,
            'soft_cap_rollbacks': 2, 'direct_native_rejections': list(malformed),
            'execution_failure_rollbacks': ['timeout', 'nonzero', 'malformed', 'oversize-output', 'certificate'],
            'v1_source_closure_unchanged_during_checks': True,
            'database_sha256': hashlib.sha256(db_path.read_bytes()).hexdigest(),
            'anchor': anchor, 'timings': 'not measured'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--executable', required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    directory = Path(args.output).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    report = check(directory, Path(args.executable).resolve(strict=True), args.sha256)
    (directory / 'checks.json').write_text(json.dumps(report, indent=2, sort_keys=True)+'\n', encoding='ascii')
    print(json.dumps(report, sort_keys=True))


if __name__ == '__main__':
    main()
