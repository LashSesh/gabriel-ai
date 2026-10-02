#!/usr/bin/env python3
"""Fresh strict-batch owner guards for the frozen comparison protocol.

This executes the native Engine through the unchanged Store. No timing is
measured. All live databases stay under /tmp; only closed evidence is archived.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gabriel_runtime.batched_reachability import make_profile, _sources
from gabriel_runtime.canonical import canonical
from gabriel_runtime.graph_observer import bits
from gabriel_runtime.graph_reachability import CAPS


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + '\n', encoding='ascii')


def command(owner, operation, payload, key):
    return {'id': key, 'contract': 'reachability', 'op': operation,
            'at': owner.budget['events'], 'expected_head': owner.head, 'payload': payload}


def anchor(owner):
    return {'head': owner.head, 'events': owner.budget['events'], 'budget': owner.budget}


def check(directory, executable, expected_sha):
    sources_before = _sources()
    cls, name, adapter = make_profile('strict_batch', executable, expected_sha)
    final_path = directory / 'accepted-final.sqlite'
    prefix_path = directory / 'sealed-valid-prefix.sqlite'
    with cls.create(final_path, {name: adapter}) as owner:
        owner.submit(command(owner, 'bind', {'adapter': name, 'config': CAPS}, 'bind'))
        prefix_anchor = anchor(owner)
    shutil.copy2(final_path, prefix_path)
    prefix_sha = sha(prefix_path)
    payload = {'batches': [[0, 1, 2]],
               'source': [{'entity': i, 're_bits': bits(i + 1), 'im_bits': bits(i - 1)}
                          for i in range(3)],
               'targets': [0], 'threshold_bits': bits(0.25),
               'windows': [{'start_bits': bits(0), 'end_bits': bits(1)},
                           {'start_bits': bits(1), 'end_bits': bits(2)}]}
    controls = []
    with cls.open(final_path, {name: adapter}, expected_head=prefix_anchor['head'],
                  expected_events=prefix_anchor['events']) as owner:
        observed = command(owner, 'observe', payload, 'observe')
        receipt = owner.submit(observed)
        assert len(receipt['result']['issue']['certificates']) == 2
        final_anchor = anchor(owner)
        accepted_journal = canonical(owner.export())
        accepted_bytes = sha(final_path)
        bad_id = copy.deepcopy(observed)
        bad_id['payload']['threshold_bits'] = bits(0.5)
        stale = command(owner, 'observe', {**payload, 'batches': []}, 'stale-head')
        stale['expected_head'] = prefix_anchor['head']
        for key, attempted, expected_error in (
                ('conflicting_command_id', bad_id, 'conflicting command id reuse'),
                ('stale_expected_head', stale, 'stale expected journal head')):
            try:
                owner.submit(attempted)
            except ValueError as exc:
                error = str(exc)
                assert expected_error in error, error
            else:
                raise AssertionError(key + ' accepted')
            assert anchor(owner) == final_anchor
            assert canonical(owner.export()) == accepted_journal
            assert sha(final_path) == accepted_bytes
            controls.append({'control': key, 'rejected': True, 'error': error,
                             'database_bytes_unchanged': True,
                             'anchors_budget_and_journal_unchanged': True})
    assert sha(final_path) == accepted_bytes
    write(directory / 'accepted-command.json', observed)
    write(directory / 'accepted-receipt.json', receipt)
    write(directory / 'external-final-anchor.json', final_anchor)
    write(directory / 'external-prefix-anchor.json', prefix_anchor)

    def reject_open(path, label, head, events, expected_error):
        before = sha(path)
        _, _, fresh = make_profile('strict_batch', executable, expected_sha)
        try:
            with cls.open(path, {name: fresh}, expected_head=head, expected_events=events):
                pass
        except ValueError as exc:
            error = str(exc)
            assert expected_error in error, error
        else:
            raise AssertionError(label + ' accepted')
        assert sha(path) == before
        controls.append({'control': label, 'rejected': True, 'error': error,
                         'database_bytes_unchanged': True,
                         'expected_head': head, 'expected_events': events})

    reject_open(final_path, 'wrong_external_head', '0' * 64, final_anchor['events'],
                'external expected head mismatch')
    reject_open(final_path, 'wrong_external_event_count', final_anchor['head'],
                final_anchor['events'] + 1, 'external expected event count mismatch')
    # A valid prefix is intentionally self-consistent. First demonstrate that
    # unanchored semantic replay accepts it, then detect the rollback with the
    # independently retained final anchors.
    with cls.open(prefix_path, {name: adapter}) as owner:
        assert anchor(owner) == prefix_anchor
        prefix_replay = owner.audit()
    assert sha(prefix_path) == prefix_sha
    rollback_path = directory / 'replaced-with-valid-prefix.sqlite'
    shutil.copy2(final_path, rollback_path)
    assert sha(rollback_path) == accepted_bytes
    shutil.copy2(prefix_path, rollback_path)
    assert sha(rollback_path) == prefix_sha
    reject_open(rollback_path, 'valid_prefix_rollback_final_head', final_anchor['head'], None,
                'external expected head mismatch')
    reject_open(rollback_path, 'valid_prefix_rollback_final_events', None, final_anchor['events'],
                'external expected event count mismatch')
    reject_open(rollback_path, 'valid_prefix_rollback_both_final_anchors',
                final_anchor['head'], final_anchor['events'], 'external expected head mismatch')
    # All failure cases leave the actual final journal usable and byte-identical.
    _, _, fresh = make_profile('strict_batch', executable, expected_sha)
    with cls.open(final_path, {name: fresh}, expected_head=final_anchor['head'],
                  expected_events=final_anchor['events']) as owner:
        assert anchor(owner) == final_anchor
        assert canonical(owner.export()) == accepted_journal
        final_replay = owner.audit(expected_head=final_anchor['head'],
                                   expected_events=final_anchor['events'])
    assert sha(final_path) == accepted_bytes
    assert sha(prefix_path) == prefix_sha and sha(rollback_path) == prefix_sha
    assert _sources() == sources_before
    assert sha(executable) == expected_sha
    return {'schema': 'gabriel.strict-batch-protocol-guards/v1', 'status': 'passed',
            'profile': name, 'executed_checker_sha256': sha(__file__),
            'executable_sha256': expected_sha, 'source_sha256': sources_before,
            'controls': controls, 'negative_controls': len(controls),
            'required_protocol_controls': ['conflicting_command_id', 'stale_expected_head',
                'wrong_external_head', 'wrong_external_event_count', 'valid_prefix_rollback'],
            'all_required_protocol_controls_passed': True,
            'valid_prefix_unanchored_semantic_replay': prefix_replay,
            'final_anchored_semantic_replay': final_replay,
            'unchanged_final_database_sha256': accepted_bytes,
            'unchanged_valid_prefix_database_sha256': prefix_sha,
            'external_final_anchor': final_anchor, 'external_prefix_anchor': prefix_anchor,
            'rollback_scope': 'synthetic replacement of a closed copied database with its previously sealed valid prefix',
            'post_failure_final_state_unchanged': True, 'sources_and_executable_unchanged': True,
            'timings': 'not measured'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--executable', required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    directory = Path(args.output).resolve()
    if not directory.is_relative_to('/tmp'):
        raise ValueError('live databases must remain under /tmp')
    directory.mkdir(parents=True, exist_ok=False)
    report = check(directory, Path(args.executable).resolve(strict=True), args.sha256)
    write(directory / 'checks.json', report)
    manifest = {p.name: {'sha256': sha(p), 'bytes': p.stat().st_size}
                for p in sorted(directory.iterdir()) if p.is_file()}
    write(directory / 'manifest.json', manifest)
    archive = ROOT / 'audit/strict_batch_protocol_guards_closed.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as out:
        for path in sorted(directory.iterdir()):
            if path.is_file():
                out.write(path, path.name)
    report['sealed_evidence'] = {'file': str(archive.relative_to(ROOT)),
                               'sha256': sha(archive), 'bytes': archive.stat().st_size}
    summary = ROOT / 'results/epoch_batch/protocol_guards.json'
    summary.parent.mkdir(parents=True, exist_ok=True)
    write(summary, report)
    print(json.dumps({'status': 'passed', 'negative_controls': report['negative_controls'],
                      'summary': str(summary), 'archive_sha256': sha(archive)}, sort_keys=True))


if __name__ == '__main__':
    main()
