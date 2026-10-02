#!/usr/bin/env python3
"""Functional equivalence and unchanged guard-boundary checks; no timings."""
from __future__ import annotations

import argparse
import copy
import hashlib
import inspect
import json
from pathlib import Path
import shutil
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gabriel_runtime.canonical import canonical
from gabriel_runtime.engine import Store
from gabriel_runtime.graph_observer import bits, _source_hashes
from gabriel_runtime import graph_reachability as scalar
from gabriel_runtime import batched_reachability as batched
from gabriel_runtime import window_batch


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def request(n=7, count=4, batches=None):
    return {'batches': [list(range(n))] if batches is None else batches,
            'source': [{'entity': i, 're_bits': bits((i + 1) / n),
                        'im_bits': bits((i % 3 - 1) / n)} for i in range(n)],
            'targets': [0, n - 1], 'threshold_bits': bits(0.2),
            'windows': [{'start_bits': bits(i / 8), 'end_bits': bits((i + 1) / 8)}
                        for i in range(count)]}


def command(owner, operation, payload, key):
    return {'id': key, 'contract': 'reachability', 'op': operation,
            'at': owner.budget['events'], 'expected_head': owner.head, 'payload': payload}


def reject(owner, operation, payload, key):
    before = canonical(owner.export()), owner.head, owner.budget
    try:
        owner.submit(command(owner, operation, payload, key))
    except ValueError:
        pass
    else:
        raise AssertionError('invalid atomic request accepted: ' + key)
    assert before == (canonical(owner.export()), owner.head, owner.budget), key


class _Trace:
    def __init__(self, *args):
        self.check_sites = []
        self.native_histories = []
        super().__init__(*args)

    def _check_identity(self):
        self.check_sites.append(inspect.currentframe().f_back.f_code.co_name)
        return super()._check_identity()

    def _invoke(self, batches):
        self.native_histories.append(copy.deepcopy(batches))
        return super()._invoke(batches)


class _TraceScalar(_Trace, scalar.GraphReachabilityAdapter):
    pass


class _TraceBatch(_Trace, batched.BatchedReachabilityAdapter):
    pass


def compare(directory, executable, expected_sha):
    records = {}
    for name, cls, adapter_name, module in (
            ('legacy_scalar', _TraceScalar, scalar.ADAPTER, scalar.window_certificate),
            ('strict_batch', _TraceBatch, batched.ADAPTER, window_batch)):
        path = directory / (name + '.sqlite')
        calls = []
        original = module.prepare_model
        def prepare(*args, **kwargs):
            calls.append(1)
            return original(*args, **kwargs)
        with patch.object(module, 'prepare_model', side_effect=prepare):
            adapter = cls(executable, expected_sha)
            with Store.create(path, {adapter_name: adapter}) as owner:
                owner.submit(command(owner, 'bind', {'adapter': adapter_name,
                    'config': scalar.CAPS}, 'bind'))
                issued = command(owner, 'observe', request(), 'first')
                receipt = owner.submit(issued)
                sites = list(adapter.check_sites)
                expected = ['__init__', 'fingerprint', 'fingerprint', 'fingerprint',
                            '_invoke', '_invoke', 'apply', 'apply']
                assert sites == expected, (name, sites)
                preparation_count = len(calls)
                assert preparation_count == (4 if name == 'legacy_scalar' else 1)
                before = len(calls), len(adapter.native_histories), list(adapter.check_sites)
                assert owner.submit(issued) == receipt
                assert before == (len(calls), len(adapter.native_histories), adapter.check_sites)
                prefix = copy.deepcopy(owner.export()['records'])
                later = owner.submit(command(owner, 'observe', request(batches=[list(range(7))]), 'second'))
                assert adapter.native_histories == [[list(range(7))], [list(range(7)), list(range(7))]]
                assert owner.export()['records'][:len(prefix)] == prefix
                anchor = {'head': owner.head, 'events': owner.budget['events']}
                export = owner.export()
                assert owner.view('reachability')['semantic_profile'] == adapter_name
        fresh = cls(executable, expected_sha)
        with Store.open(path, {adapter_name: fresh}, expected_head=anchor['head'],
                        expected_events=anchor['events']) as owner:
            assert owner.export() == export
            audit = owner.audit(expected_head=anchor['head'], expected_events=anchor['events'])
        records[name] = {'first_issue': receipt['result']['issue'],
                         'second_issue': later['result']['issue'],
                         'check_sites': sites, 'preparations_per_four_windows': preparation_count,
                         'source_files': len(adapter.sources), 'replay': audit,
                         'database_sha256': sha(path)}
    for key in ('first_issue', 'second_issue'):
        assert canonical(records['legacy_scalar'][key]) == canonical(records['strict_batch'][key])
    assert records['legacy_scalar']['check_sites'] == records['strict_batch']['check_sites']
    assert records['strict_batch']['source_files'] == records['legacy_scalar']['source_files'] + 2
    return records


def failures(directory, executable, expected_sha):
    copied = directory / 'snapshot-copy.bin'
    shutil.copy2(executable, copied)
    adapter = batched.BatchedReachabilityAdapter(copied, expected_sha)
    original_prepare = window_batch.certify_prepared
    native = adapter._invoke
    invokes = []
    def invoked(batches):
        invokes.append(1)
        return native(batches)
    adapter._invoke = invoked
    rejections = []
    with Store.create(directory / 'rejections.sqlite', {batched.ADAPTER: adapter}) as owner:
        owner.submit(command(owner, 'bind', {'adapter': batched.ADAPTER, 'config': scalar.CAPS}, 'bind'))
        bad = request()
        bad['windows'][1]['end_bits'] = bits(-1)
        reject(owner, 'observe', bad, 'invalid-later-member')
        assert not invokes
        rejections.append('invalid-later-member-before-native')
        for kind in ('certificate-failure', 'executable-change', 'new-source-identity-change',
                     'arithmetic-identity-change'):
            count = []
            saved_sources = dict(adapter.sources)
            saved_arithmetic = copy.deepcopy(adapter.arithmetic)
            def certify(*args, **kwargs):
                count.append(1)
                if len(count) == 2:
                    if kind == 'certificate-failure':
                        raise ValueError('controlled later-certificate rejection')
                    if kind == 'executable-change':
                        with copied.open('ab') as out:
                            out.write(b'\x00')
                    elif kind == 'new-source-identity-change':
                        adapter.sources[batched.EXTRA_SOURCES[0]] = '0' * 64
                    elif kind == 'arithmetic-identity-change':
                        adapter.arithmetic['python_flint'] = 'controlled-mismatch'
                return original_prepare(*args, **kwargs)
            try:
                with patch.object(window_batch, 'certify_prepared', side_effect=certify):
                    reject(owner, 'observe', request(), kind)
                assert len(count) >= 2
                rejections.append(kind)
            finally:
                adapter.sources = saved_sources
                adapter.arithmetic = saved_arithmetic
                shutil.copy2(executable, copied)
        # The post-native check remains before numerical preparation.
        real_run = scalar.subprocess.run
        def changed_after_native(*args, **kwargs):
            result = real_run(*args, **kwargs)
            with copied.open('ab') as out:
                out.write(b'\x00')
            return result
        with patch.object(scalar.subprocess, 'run', side_effect=changed_after_native):
            with patch.object(window_batch, 'prepare_window_model', side_effect=AssertionError('should not prepare')):
                reject(owner, 'observe', request(), 'post-native-executable-change')
        shutil.copy2(executable, copied)
        rejections.append('post-native-executable-change-before-preparation')
        # Recovery uses unchanged expected identities; failed batches consumed no capacity.
        good = owner.submit(command(owner, 'observe', request(count=32), 'capacity-32'))
        assert len(good['result']['issue']['certificates']) == 32
        reject(owner, 'observe', request(count=1, batches=[]), 'total-window-cap')
        rejections.append('total-window-cap')
        assert owner.budget['events'] == 2
    for source in batched.EXTRA_SOURCES:
        prior = adapter.sources[source]
        adapter.sources[source] = '0' * 64
        try:
            adapter.fingerprint()
        except ValueError:
            pass
        else:
            raise AssertionError('new source identity accepted: ' + source)
        finally:
            adapter.sources[source] = prior
    copied.unlink()
    return rejections


def out_of_scope(directory, executable, expected_sha):
    issues = []
    for profile in batched.PROFILE_NAMES:
        cls, name, adapter = batched.make_profile(profile, executable, expected_sha)
        assert cls is Store
        with cls.create(directory / ('generic-' + profile + '.sqlite'), {name: adapter}) as owner:
            owner.submit(command(owner, 'bind', {'adapter': name, 'config': scalar.CAPS}, 'bind'))
            payload = request(n=3, batches=[[0, 1], [1, 2]])
            receipt = owner.submit(command(owner, 'observe', payload, 'path'))
            issue = receipt['result']['issue']
            assert [c['status'] for c in issue['certificates']] == ['out_of_scope'] * 4
            issues.append(issue)
    assert canonical(issues[0]) == canonical(issues[1])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--executable', required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    directory = Path(args.output).resolve()
    if not directory.is_relative_to('/tmp'):
        raise ValueError('live check databases must remain outside the mirrored workspace, under /tmp')
    directory.mkdir(parents=True, exist_ok=False)
    executable = Path(args.executable).resolve(strict=True)
    before = scalar._sources()
    before_v1 = _source_hashes()
    comparisons = compare(directory, executable, args.sha256)
    rejections = failures(directory, executable, args.sha256)
    out_of_scope(directory, executable, args.sha256)
    assert before == scalar._sources() and before_v1 == _source_hashes()
    assert sha(executable) == args.sha256
    report = {'schema': 'gabriel.strict-batch-checks/v1', 'status': 'passed',
              'semantic_issue_bytes_identical': True,
              'full_replay_for_each_command': True, 'identical_retry_no_work': True,
              'issued_prefix_immutable': True, 'generic_out_of_scope_identical': True,
              'unchanged_original_source_closures': True, 'unchanged_store_class': True,
              'post_failure_recovery_at_32_window_cap': True,
              'new_source_identity_checks': list(batched.EXTRA_SOURCES),
              'mutation_scope': 'copied executable bytes, bound expected source/arithmetic identities; no shared dependency file modified',
              'atomic_rejections': rejections, 'profiles': comparisons,
              'timings': 'not measured'}
    (directory / 'checks.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'status': 'passed', 'output': str(directory / 'checks.json'),
                      'atomic_rejections': len(rejections),
                      'check_sites': comparisons['strict_batch']['check_sites']}, sort_keys=True))


if __name__ == '__main__':
    main()
