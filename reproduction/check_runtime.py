"""Independent integration and process-failure checks for Gabriel's runtime.

Run from the delivered project: python reproduction/check_runtime.py
Only temporary SQLite databases are modified. Synthetic fixtures and the executed
check report are written to results/runtime_inputs.json and runtime_checks.json.
No network, source data, financial decisions or external actuators are used.
"""
from pathlib import Path
from collections import Counter
from dataclasses import asdict
from itertools import permutations, product
import argparse
import copy
import hashlib
import json
import math
import os
import random
import sqlite3
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'reproduction'))
from gabriel_runtime.canonical import canonical, loads, digest
from gabriel_runtime.engine import Store
from gabriel_runtime.adapters import default_registry
from finite_observation import Catalogue, Planner, Session, Observation
from maturity_ledger import MaturityLedger, IssuedForecast, TargetRequirement
from sequential_contract import EventRevision
from replay_adaptive_maturity import score_outcome, reduce_controller

SEED = 2026092603
COUNTS = Counter()


def plain(x):
    return json.loads(json.dumps(x, sort_keys=True, separators=(',', ':')))


def equal(a, b, label):
    # Byte comparison deliberately avoids Python's True == 1 alias.
    if canonical(a) != canonical(b):
        raise AssertionError((label, a, b))
    COUNTS[label] += 1


def reject(fn, label):
    try:
        fn()
    except ValueError:
        COUNTS[label] += 1
        return
    raise AssertionError('Expected ValueError: ' + label)


class ProbeAdapter:
    """Pure deterministic adversarial probe, not a Gabriel domain algorithm."""
    def fingerprint(self):
        return {'name': 'verification-probe', 'version': 1}

    def initialize(self, config):
        if config != {'start': 0}:
            raise ValueError('probe config')
        config['start'] = 900  # Verify argument ownership at successful binding.
        return {'count': 0, 'echo': None}

    def view(self, state):
        result = copy.deepcopy(state)
        state['count'] = -1000  # The store must not expose stored mutable state.
        return result

    def apply(self, state, operation, payload, receipt_at):
        if operation == 'fail':
            state['count'] += 1000
            payload['mutated'] = True
            raise ValueError('intentional reducer failure')
        if operation == 'badresult':
            state['count'] += 1000
            return state, {'inexact': 0.5}
        if operation != 'advance':
            raise ValueError('unknown probe operation')
        state['count'] += 1
        state['echo'] = copy.deepcopy(payload)
        payload['mutated'] = True
        return state, {'count': state['count'], 'echo': state['echo']}


def registry():
    return {'probe/v1': ProbeAdapter()}


def command(store, ident, contract, op, at, payload):
    return {'id': ident, 'contract': contract, 'op': op, 'at': at,
            'expected_head': store.head, 'payload': copy.deepcopy(payload)}


def send(store, ident, contract, op, at, payload):
    cmd = command(store, ident, contract, op, at, payload)
    before = canonical(cmd)
    receipt = store.submit(cmd)
    assert canonical(cmd) == before, 'submit mutated caller-owned command'
    COUNTS['caller_command_ownership'] += 1
    return receipt


def bind_probe(store, ident='bind'):
    return send(store, ident, 'probe', 'bind', 0,
                {'adapter': 'probe/v1', 'config': {'start': 0}})


def unchanged_rejection(store, cmd, label):
    before = canonical(store.export()), canonical(store.budget)
    reject(lambda: store.submit(cmd), label)
    equal([canonical(store.export()), canonical(store.budget)], list(before),
          'rejections_preserve_log_and_budget')


def canonical_checks():
    rng = random.Random(SEED)
    vals = [None, False, True, 0, -1, 2**53-1, -(2**53-1), '', 'x', '\\n',
            {'z': [1, True, None], 'a': {'b': 'c'}}]
    for _ in range(100):
        vals.append({'n': rng.randrange(-100000, 100001),
                     'flags': [bool(rng.getrandbits(1)) for _ in range(6)],
                     'text': ''.join(chr(rng.randrange(32, 127)) for _ in range(8))})
    for x in vals:
        expected = json.dumps(x, sort_keys=True, separators=(',', ':'), ensure_ascii=True)
        assert canonical(x) == expected
        assert digest(x) == hashlib.sha256(expected.encode('ascii')).hexdigest()
        equal(loads(expected), x, 'canonical_roundtrip_and_independent_digest')
    for x in [0.0, math.inf, math.nan, 2**53, -(2**53), (1,), {1: 'x'},
              'nonascii:\u00e4', {'x': b'a'}, {1, 2}]:
        reject(lambda x=x: canonical(x), 'canonical_invalid_python_value')
    for text in ['{"a":1,"a":1}', '{"a":{"x":1,"x":2}}', '1.0',
                 'NaN', 'Infinity', '9007199254740992', '{"x":1} trailing']:
        reject(lambda text=text: loads(text), 'canonical_invalid_json_text')
    x = None
    for _ in range(66):
        x = [x]
    reject(lambda: canonical(x), 'canonical_excessive_nesting')
    assert {'value': True} == {'value': 1}
    assert canonical({'value': True}) != canonical({'value': 1})
    COUNTS['constructed_python_equality_collision'] += 1


def core_checks(temp):
    db = temp / 'core.sqlite'
    with Store.create(db, registry()) as store:
        bind_probe(store)
        equal(store.view('probe'), {'count': 0, 'echo': None}, 'view_argument_ownership')
        cmd = command(store, 'one', 'probe', 'advance', 1, {'value': True})
        receipt = store.submit(cmd)
        equal(cmd['payload'], {'value': True}, 'successful_reducer_argument_ownership')
        before = plain(store.budget)
        send(store, 'two', 'probe', 'advance', 2, {'value': 2})
        charged = plain(store.budget)
        equal(store.submit(copy.deepcopy(cmd)), receipt, 'identical_old_head_retry_receipt')
        equal(store.budget, charged, 'duplicate_never_charged')
        collision = copy.deepcopy(cmd)
        collision['payload']['value'] = 1
        assert collision == cmd  # Deliberately demonstrates an unsafe equality control.
        unchanged_rejection(store, collision, 'bool_int_same_id_collision_rejected')
        stale = command(store, 'stale', 'probe', 'advance', 3, {})
        stale['expected_head'] = receipt['head']
        unchanged_rejection(store, stale, 'stale_head_rejected')
        cases = [('backdated', {'at': 1}), ('bool_time', {'at': True}),
                 ('negative_time', {'at': -1}), ('float_time', {'at': 2.0}),
                 ('unknown_contract', {'contract': 'absent'}),
                 ('unknown_op', {'op': 'unknown'}), ('bad_id', {'id': ''}),
                 ('bad_head', {'expected_head': 'x'}), ('extra', {'extra': 1})]
        for label, change in cases:
            bad = command(store, 'bad-' + label, 'probe', 'advance', 3, {})
            bad.update(change)
            unchanged_rejection(store, bad, 'invalid_command_' + label)
        for op in ['fail', 'badresult']:
            bad = command(store, op, 'probe', op, 3, {'input': 1})
            unchanged_rejection(store, bad, 'failed_reducer_' + op)
            equal(bad['payload'], {'input': 1}, 'failed_reducer_argument_ownership')
        altered = command(store, 'rebind', 'probe', 'bind', 3,
                          {'adapter': 'probe/v1', 'config': {'start': 1}})
        unchanged_rejection(store, altered, 'immutable_contract_rebind_rejected')
        unknown = command(store, 'unknown-adapter', 'other', 'bind', 3,
                          {'adapter': 'absent', 'config': {}})
        unchanged_rejection(store, unknown, 'unknown_adapter_rejected')
        missing = command(store, 'missing', 'probe', 'advance', 3, {})
        del missing['at']
        unchanged_rejection(store, missing, 'missing_command_field_rejected')
        assert charged['events'] == before['events'] + 1
        store.audit()
    with Store.open(db, registry()) as first, Store.open(db, registry()) as second:
        stale = command(second, 'stale-handle', 'probe', 'advance', 3, {})
        send(first, 'writer-a', 'probe', 'advance', 3, {'handle': 'a'})
        unchanged_rejection(second, stale, 'independent_handle_stale_frontier')
        send(second, 'writer-b', 'probe', 'advance', 4, {'handle': 'b'})
        equal(first.view('probe'), second.view('probe'), 'handles_read_current_committed_state')
        assert first.view('probe')['count'] == 4
    class Changed(ProbeAdapter):
        def fingerprint(self):
            return {'name': 'verification-probe', 'version': 2}
    reject(lambda: Store.open(db, {'probe/v1': Changed()}), 'changed_registry_rejected')
    reject(lambda: Store.open(db, {}), 'removed_registry_rejected')


def budget_checks(temp):
    # Hashes have fixed length, so header-dependent genesis contents do not
    # change the command's canonical byte size.
    with Store.create(temp / 'budget-size.sqlite', registry()) as probe:
        base = command(probe, 'bind', 'probe', 'bind', 0,
                       {'adapter': 'probe/v1', 'config': {'start': 0}})
        size = len(canonical(base).encode('ascii'))
    for name, limits in [
        ('events', {'max_events': 1}),
        ('bytes', {'max_bytes': size}),
        ('command', {'max_command_bytes': size}),
    ]:
        with Store.create(temp / ('budget-' + name + '.sqlite'), registry(), limits=limits) as store:
            cmd = command(store, 'bind', 'probe', 'bind', 0, base['payload'])
            assert len(canonical(cmd).encode('ascii')) == size
            receipt = store.submit(cmd)
            equal(store.budget, {'events': 1, 'bytes': size}, 'budget_exact_' + name)
            equal(store.submit(cmd), receipt, 'retry_at_exhausted_' + name)
            extra = command(store, 'over', 'probe', 'advance', 1, {'padding': 'x' * size})
            unchanged_rejection(store, extra, 'budget_over_' + name)
    for name in ['max_bytes', 'max_command_bytes']:
        with Store.create(temp / ('budget-small-' + name + '.sqlite'), registry(),
                          limits={name: size - 1}) as store:
            cmd = command(store, 'bind', 'probe', 'bind', 0, base['payload'])
            unchanged_rejection(store, cmd, 'budget_one_byte_below_' + name)


def finite_config(name, queries):
    return {'contract_id': name, 'query_names': ['q%d' % i for i in range(queries)],
            'costs': list(range(1, queries + 1)),
            'rows': [list(x) for x in product(['0', '1'], repeat=queries)],
            'labels': [sum(map(int, x)) % 2 for x in product(['0', '1'], repeat=queries)],
            'weights': []}


def catalogue(config):
    return Catalogue(config['contract_id'], tuple(config['query_names']),
                     tuple(config['costs']), tuple(map(tuple, config['rows'])),
                     tuple(config['labels']), tuple(config['weights']))


def finite_payload(q, value, source, at, event=0):
    return {'query': q, 'outcome': value, 'source_id': source,
            'event_interval': [event, event], 'received_at': at,
            'status': 'observed', 'kind': 'passive', 'cutoff': at}


def direct_finite(session, payload):
    fields = {k: v for k, v in payload.items() if k != 'cutoff'}
    fields['event_interval'] = tuple(fields['event_interval'])
    accepted = session.ingest(Observation(contract_digest=session.planner.c.identity, **fields),
                              payload['cutoff'])
    return accepted


def compare_finite(store, contract, session):
    view = store.view(contract)
    equal(view['result'], session.result(), 'finite_direct_legacy_result')
    equal(view['compatible_mask'], hex(session.state), 'finite_direct_legacy_mask')
    equal(view['next_query'], session.planner.choice(session.state, 'minimax'),
          'finite_direct_legacy_next_query')
    val = session.planner.value(session.state)
    equal([view['worst_case_cost'], view['cost_status']],
          [None, 'infinite'] if math.isinf(val) else [val, 'finite'],
          'finite_direct_legacy_cost')
    equal(view['evidence_count'], len(session.ledger), 'finite_direct_legacy_evidence_count')
    equal(view['catalogue_digest'], session.planner.c.identity, 'finite_catalogue_binding')
    assert view['semantic_profile'] == 'finite-catalogue/v1'
    # Additional transparent set filtering, without Planner.observe.
    members = [i for i, row in enumerate(session.planner.c.rows)
               if all(row[e['observation']['query']] == e['observation']['outcome']
                      for e in session.ledger)]
    assert view['result']['compatible_count'] == len(members)
    COUNTS['finite_independent_set_filter'] += 1


def finite_checks(temp, fixtures):
    configs = [finite_config('parity-two', 2), finite_config('parity-three', 3)]
    fixtures['finite_catalogues'] = configs
    index = 0
    for config in configs:
        n = len(config['query_names'])
        for order in permutations(range(n)):
            for row in config['rows']:
                index += 1
                direct = Session(Planner(catalogue(config)))
                with Store.create(temp / ('finite-%d.sqlite' % index), default_registry()) as store:
                    send(store, 'bind', 'finite', 'bind', 0,
                         {'adapter': 'finite-observation/v1', 'config': config})
                    compare_finite(store, 'finite', direct)
                    for step, q in enumerate(order, 1):
                        p = finite_payload(q, row[q], 'source-%d' % q, step)
                        direct_finite(direct, p)
                        send(store, 'obs-%d' % step, 'finite', 'observe', step, p)
                        compare_finite(store, 'finite', direct)
                    store.audit()
                COUNTS['finite_complete_query_order_outcome_paths'] += 1
    config = {'contract_id': 'indistinguishable', 'query_names': ['same'], 'costs': [1],
              'rows': [['x'], ['x']], 'labels': [0, 1], 'weights': [1, 2]}
    fixtures['finite_indistinguishable'] = config
    direct = Session(Planner(catalogue(config)))
    with Store.create(temp / 'finite-adversarial.sqlite', default_registry()) as store:
        send(store, 'bind', 'finite', 'bind', 0,
             {'adapter': 'finite-observation/v1', 'config': config})
        compare_finite(store, 'finite', direct)
        assert store.view('finite')['result']['status'] == 'unresolved'
        p = finite_payload(0, 'x', 'source', 3, event=0)
        send(store, 'late', 'finite', 'observe', 3, p)
        direct_finite(direct, p)
        compare_finite(store, 'finite', direct)
        COUNTS['late_completed_event_accepted'] += 1
        repeated = dict(p, received_at=4, cutoff=4)
        send(store, 'same-evidence-new-command', 'finite', 'observe', 4, repeated)
        direct_finite(direct, repeated)
        compare_finite(store, 'finite', direct)
        assert store.view('finite')['evidence_count'] == 1
        COUNTS['domain_duplicate_has_no_extra_evidence'] += 1
        for name, change in [('source-conflict', {'outcome': 'y'}),
                             ('future-receipt', {'received_at': 8}),
                             ('future-cutoff', {'cutoff': 8}),
                             ('active', {'kind': 'intervention'}),
                             ('bool-query', {'query': False}),
                             ('bad-event', {'event_interval': [5, 4]})]:
            bad = dict(p, cutoff=5, received_at=5)
            bad.update(change)
            unchanged_rejection(store, command(store, name, 'finite', 'observe', 5, bad),
                                'finite_invalid_' + name)
        contradictory = finite_payload(0, 'absent', 'independent-source', 5)
        send(store, 'contradiction', 'finite', 'observe', 5, contradictory)
        direct_finite(direct, contradictory)
        compare_finite(store, 'finite', direct)
        assert store.view('finite')['result']['status'] == 'conflict'
        COUNTS['empty_compatible_set_is_conflict'] += 1
        store.audit()


def issue(ident, origin, end, lane):
    return {'forecast_id': ident, 'origin': origin, 'target_end': end, 'issued_at': origin,
            'requirements': [{'source_id': 'synthetic', 'record_id': str(t),
                              'event_start': t, 'event_end': t} for t in (origin, end)],
            'prediction': {'var_hex': (1.0).hex(), 'es_hex': (2.0).hex()},
            'lane_id': lane, 'provenance': {'synthetic': True}}


def outcome(event, receipt, value, revision=0):
    return {'source_id': 'synthetic', 'record_id': str(event), 'revision': revision,
            'event_interval': [event, event], 'received_at': receipt,
            'vintage_id': 'synthetic-v%d' % revision, 'payload': {'rate_hex': float(value).hex()}}


def maturity_fixture():
    config = {'scoring_rule_id': 'binary64-upper-loss-hit-primary-v1',
              'availability_mode': 'declared_observed_receipts',
              'initial_states': {'a': {'theta_units': 0, 'updates': 0},
                                 'b': {'theta_units': 10, 'updates': 0}}}
    steps = [('issue', 0, issue('A', 0, 4, 'a')),
             ('outcome', 0, outcome(0, 0, 100)),
             ('issue', 1, issue('B', 1, 3, 'b')),
             ('outcome', 1, outcome(1, 1, 100)),
             ('outcome', 5, outcome(4, 5, 103)),
             ('outcome', 6, outcome(3, 6, 99)),
             ('outcome', 7, outcome(4, 7, 99, 1)),
             ('outcome', 7, outcome(3, 7, 104, 1)),
             ('issue', 7, issue('C', 7, 9, 'a')),
             ('outcome', 7, outcome(7, 7, 100)),
             ('outcome', 12, outcome(9, 12, 102)),
             ('outcome', 13, outcome(0, 13, 98, 1))]
    return config, steps


def direct_maturity(ledger, operation, payload):
    if operation == 'issue':
        data = copy.deepcopy(payload)
        data['requirements'] = [TargetRequirement(**x) for x in data['requirements']]
        return ledger.issue(IssuedForecast.create(**data))
    data = copy.deepcopy(payload)
    return ledger.append(EventRevision.create(**data))


def compare_maturity(view, snapshot, config):
    equal(view['feedback'], plain(asdict(snapshot)), 'maturity_direct_legacy_snapshot')
    equal(view['feedback_digest'], snapshot.identity, 'maturity_direct_legacy_digest')
    expected = {lane: snapshot.replay(initial, reduce_controller, lane)
                for lane, initial in config['initial_states'].items()}
    equal(view['controller_states'], expected, 'maturity_direct_legacy_controller')
    # Integer control replay independently re-implements the documented rule.
    manual = copy.deepcopy(config['initial_states'])
    for active in snapshot.active:
        x = manual[active.lane_id]
        hit = json.loads(active.score_json)['hit']
        x['theta_units'] = min(800, max(-800, x['theta_units'] + (39 if hit else -1)))
        x['updates'] += 1
    equal(view['controller_states'], manual, 'maturity_independent_integer_reducer')
    assert view['arithmetic'] == 'binary64'
    assert view['semantic_profile'] == 'maturity-risk/v1'
    equal(view['issuance_basis'], 'declared_owner_receipt' if config['availability_mode'] ==
          'declared_observed_receipts' else 'historical_declaration', 'maturity_issuance_basis')


def maturity_checks(temp, fixtures):
    config, steps = maturity_fixture()
    fixtures['maturity'] = {'config': config, 'operations': plain(steps)}
    ledger = MaturityLedger(score_outcome, config['scoring_rule_id'], config['availability_mode'])
    with Store.create(temp / 'maturity.sqlite', default_registry()) as store:
        send(store, 'bind', 'risk', 'bind', 0, {'adapter': 'maturity-risk/v1', 'config': config})
        historical = {}
        issued = {}
        for index, (operation, at, payload) in enumerate(steps):
            accepted = direct_maturity(ledger, operation, payload)
            rec = send(store, 'step-%d' % index, 'risk', operation, at, payload)
            equal(rec['result']['accepted'], accepted, 'maturity_legacy_acceptance')
            snap = ledger.snapshot(ledger.clock, ledger.clock)
            compare_maturity(store.view('risk'), snap, config)
            if index == 5:
                historical['six_operations'] = plain(asdict(snap))
                assert [s.forecast_id for s in snap.active] == ['A', 'B']
                assert [s.target_end for s in snap.active] == [4, 3]
                COUNTS['receipt_maturity_order_differs_from_target_order'] += 1
            if operation == 'issue':
                issued[payload['forecast_id']] = next(x.identity for x in ledger.forecasts
                                                     if x.forecast_id == payload['forecast_id'])
            assert all(issued[x.forecast_id] == x.identity for x in ledger.forecasts)
            COUNTS['revisions_preserve_issued_forecast_identity'] += 1
        # Exact as-of grid: both physical receipt and accepted-operation prefix
        # matter, particularly for the two corrections received at time 7.
        for prefix, event, receipt in product([0, 1, 5, 6, 7, 8, 12],
                                              [0, 3, 4, 9, 13], [0, 5, 6, 7, 13]):
            snap = ledger.snapshot(event, receipt, prefix)
            payload = {'event_cutoff': event, 'receipt_cutoff': receipt,
                       'operation_cutoff': prefix}
            rec = send(store, 'query-%d-%d-%d' % (prefix, event, receipt), 'risk', 'query', 13, payload)
            compare_maturity(rec['result'], snap, config)
            COUNTS['maturity_asof_prefix_queries'] += 1
        snap = ledger.snapshot(6, 6, 6)
        equal(plain(asdict(snap)), historical['six_operations'],
              'future_receipts_leave_historical_snapshot_unchanged')
        duplicate = steps[-1]
        rec = send(store, 'duplicate-outcome-new-command', 'risk', duplicate[0], 13, duplicate[2])
        assert rec['result']['accepted'] is False
        assert store.view('risk')['module_operation_count'] == len(steps)
        COUNTS['maturity_domain_duplicate_preserves_prefix_length'] += 1
        changed = copy.deepcopy(steps[0][2]); changed['prediction']['var_hex'] = (1.5).hex()
        unchanged_rejection(store, command(store, 'changed-issue', 'risk', 'issue', 13, changed),
                            'immutable_forecast_rewrite_rejected')
        for label, operation, payload in [
            ('future_receipt', 'outcome', outcome(14, 14, 100)),
            ('revision_gap', 'outcome', outcome(4, 13, 100, 3)),
            ('nonfinite_rate', 'outcome', dict(outcome(4, 13, 100, 2), payload={'rate_hex': 'inf'})),
            ('future_query', 'query', {'event_cutoff': 13, 'receipt_cutoff': 14, 'operation_cutoff': None}),
            ('invalid_prefix', 'query', {'event_cutoff': 13, 'receipt_cutoff': 13, 'operation_cutoff': 13}),
            ('bool_prefix', 'query', {'event_cutoff': 13, 'receipt_cutoff': 13, 'operation_cutoff': True}),
        ]:
            unchanged_rejection(store, command(store, label, 'risk', operation, 13, payload),
                                'maturity_invalid_' + label)
        audit = store.audit()
        COUNTS['maturity_full_semantic_audit'] += 1


def maturity_boundary_checks(temp, fixtures):
    config, _ = maturity_fixture()
    extremes = [(float.fromhex('0x0.0000000000001p-1022'),
                 float.fromhex('0x1.fffffffffffffp+1023')),
                (float.fromhex('0x1.fffffffffffffp+1023'),
                 float.fromhex('0x0.0000000000001p-1022'))]
    fixtures['positive_finite_endpoint_arithmetic_boundaries'] = [
        [a.hex(), b.hex()] for a, b in extremes]
    for i, (a, b) in enumerate(extremes):
        with Store.create(temp / ('arithmetic-boundary-%d.sqlite' % i), default_registry()) as store:
            send(store, 'bind', 'risk', 'bind', 0, {'adapter': 'maturity-risk/v1', 'config': config})
            send(store, 'issue', 'risk', 'issue', 0, issue('edge', 0, 1, 'a'))
            send(store, 'first', 'risk', 'outcome', 0, outcome(0, 0, a))
            bad = command(store, 'second', 'risk', 'outcome', 1, outcome(1, 1, b))
            unchanged_rejection(store, bad, 'finite_endpoint_ratio_' + ('overflow' if i == 0 else 'underflow'))
            assert store.view('risk')['module_operation_count'] == 2
            assert store.view('risk')['feedback']['pending'] == ['edge']
            COUNTS['arithmetic_failure_preserves_pending_forecast'] += 1
    for mode in ['declared_observed_receipts', 'historical_replay_without_vintages']:
        cfg = dict(config, availability_mode=mode)
        with Store.create(temp / ('issuance-' + mode + '.sqlite'), default_registry()) as store:
            send(store, 'bind', 'risk', 'bind', 0, {'adapter': 'maturity-risk/v1', 'config': cfg})
            cmd = command(store, 'imported', 'risk', 'issue', 10, issue('old-issue', 0, 4, 'a'))
            if mode == 'declared_observed_receipts':
                unchanged_rejection(store, cmd, 'late_declared_live_issue_rejected')
            else:
                store.submit(cmd)
                equal(store.view('risk')['issuance_basis'], 'historical_declaration',
                      'historical_import_explicitly_labelled')
                assert store.view('risk')['feedback']['pending'] == ['old-issue']
                COUNTS['historical_import_is_not_completed_feedback'] += 1


def isolation_checks(temp):
    finite = finite_config('isolation', 2)
    maturity, steps = maturity_fixture()
    finite_steps = [('observe', at, finite_payload(q, value, 'f%d' % q, at))
                    for at, q, value in [(2, 0, '1'), (8, 1, '0')]]
    configs = {'finite': ('finite-observation/v1', finite), 'risk': ('maturity-risk/v1', maturity)}
    streams = {'finite': finite_steps, 'risk': steps}
    independent = {}
    for key in configs:
        adapter, config = configs[key]
        with Store.create(temp / ('separate-' + key + '.sqlite'), default_registry()) as store:
            send(store, 'bind', key, 'bind', 0, {'adapter': adapter, 'config': config})
            for i, (op, at, payload) in enumerate(streams[key]):
                send(store, 'op%d' % i, key, op, at, payload)
            independent[key] = store.view(key)
    with Store.create(temp / 'interleaved.sqlite', default_registry()) as store:
        for key, (adapter, config) in configs.items():
            send(store, 'bind-' + key, key, 'bind', 0, {'adapter': adapter, 'config': config})
        merged = sorted((at, key, i, op, payload) for key, stream in streams.items()
                        for i, (op, at, payload) in enumerate(stream))
        for at, key, i, op, payload in merged:
            other = 'risk' if key == 'finite' else 'finite'
            before = store.view(other)
            send(store, key + str(i), key, op, at, payload)
            equal(store.view(other), before, 'interleaving_other_contract_unchanged')
        for key in configs:
            equal(store.view(key), independent[key], 'interleaving_matches_separate_execution')
        store.audit()


def corruption_checks(temp):
    original = temp / 'corruption-original.sqlite'
    with Store.create(original, registry()) as store:
        bind_probe(store)
        send(store, 'one', 'probe', 'advance', 1, {'value': 1})
        send(store, 'two', 'probe', 'advance', 2, {'value': 2})
        full = store.export()
        anchor = {'head': store.head, 'events': store.budget['events']}
    forged = temp / 'corruption-forged.sqlite'
    forged.write_bytes(original.read_bytes())
    with sqlite3.connect(forged) as db:
        row = db.execute('SELECT sequence,record_text,receipt_text FROM journal ORDER BY sequence DESC LIMIT 1').fetchone()
        record, receipt = json.loads(row[1]), json.loads(row[2])
        record['result']['count'] = 999
        bare = {key: value for key, value in record.items() if key != 'hash'}
        # Deliberately recompute the public hash and receipt; structural hash
        # checking alone would accept this altered domain result.
        record['hash'] = hashlib.sha256(json.dumps(bare, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        receipt['result'] = record['result']; receipt['head'] = record['hash']
        db.execute('UPDATE journal SET record_text=?,receipt_text=? WHERE sequence=?',
                   (canonical(record), canonical(receipt), row[0]))
        db.execute('UPDATE meta SET head=? WHERE singleton=1', (record['hash'],))
    reject(lambda: Store.open(forged, registry()), 'rehashed_semantic_corruption_rejected')
    changedstate = temp / 'corruption-state.sqlite'
    changedstate.write_bytes(original.read_bytes())
    with sqlite3.connect(changedstate) as db:
        db.execute('UPDATE contracts SET state_text=? WHERE contract_id=?',
                   (canonical({'count': 999, 'echo': None}), 'probe'))
    reject(lambda: Store.open(changedstate, registry()), 'materialized_state_corruption_rejected')
    prefix = temp / 'valid-prefix.sqlite'
    with Store.create(prefix, registry()) as store:
        for record in full['records'][:-1]:
            store.submit(record['command'])
        store.audit()  # A complete consistent earlier history is self-consistent.
        COUNTS['unanchored_valid_prefix_is_accepted'] += 1
        reject(lambda: store.audit(expected_head=anchor['head'], expected_events=anchor['events']),
               'retained_anchor_rejects_truncated_prefix')
    reject(lambda: Store.open(prefix, registry(), expected_head=anchor['head'],
                              expected_events=anchor['events']),
           'open_with_retained_anchor_rejects_truncated_prefix')


def crash_child(args):
    with Store.open(Path(args.database), registry()) as store:
        def crash(stage):
            if stage == args.stage:
                os._exit(77 if stage == 'before_commit' else 78)
        store._test_hook = crash
        store.submit(json.loads(Path(args.command_file).read_text()))
    raise AssertionError('crash hook was not reached')


def crash_checks(temp):
    records = []
    for stage in ['before_commit', 'after_commit']:
        db = temp / ('crash-' + stage + '.sqlite')
        with Store.create(db, registry()) as store:
            bind_probe(store)
            cmd = command(store, 'crashing-command', 'probe', 'advance', 1, {'test': stage})
            before = store.export()
            beforebudget = plain(store.budget)
        commandfile = temp / ('command-' + stage + '.json')
        commandfile.write_text(canonical(cmd))
        result = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--crash-child',
                                 '--database', str(db), '--stage', stage,
                                 '--command-file', str(commandfile)],
                                capture_output=True, text=True, timeout=60)
        expected_code = 77 if stage == 'before_commit' else 78
        assert result.returncode == expected_code, (result.returncode, result.stdout, result.stderr)
        with Store.open(db, registry()) as store:
            persisted_receipt = None
            if stage == 'before_commit':
                equal(store.export(), before, 'process_exit_before_commit_rolls_back')
                equal(store.budget, beforebudget, 'process_exit_before_commit_not_charged')
                assert store.view('probe')['count'] == 0
            else:
                assert store.view('probe')['count'] == 1
                assert store.budget['events'] == beforebudget['events'] + 1
                COUNTS['process_exit_after_commit_preserves_effect'] += 1
                with sqlite3.connect(db) as raw:
                    saved = raw.execute('SELECT receipt_text FROM journal WHERE command_id=?',
                                        ('crashing-command',)).fetchone()
                    persisted_receipt = json.loads(saved[0])
            receipt = store.submit(cmd)
            if persisted_receipt is not None:
                equal(receipt, persisted_receipt, 'postcommit_retry_returns_original_stored_receipt')
            assert store.view('probe')['count'] == 1
            assert store.budget['events'] == beforebudget['events'] + 1
            before_retry = store.export(), plain(store.budget)
            equal(store.submit(copy.deepcopy(cmd)), receipt, 'crash_retry_identical_receipt')
            equal([store.export(), store.budget], list(before_retry), 'crash_retry_no_second_effect_or_charge')
            store.audit()
            records.append({'stage': stage, 'os_exit_code': result.returncode,
                            'committed_effect_count_after_retry': 1,
                            'journal_events_after_retry': store.budget['events']})
    return records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--crash-child', action='store_true')
    parser.add_argument('--database'); parser.add_argument('--stage'); parser.add_argument('--command-file')
    args = parser.parse_args()
    if args.crash_child:
        crash_child(args)
        return
    started = time.monotonic()
    fixtures = {'schema': 'gabriel.runtime.synthetic-inputs.v1', 'seed': SEED,
                'purpose': 'Operational integration fixtures; not empirical XR or market observations.'}
    with tempfile.TemporaryDirectory(prefix='gabriel-runtime-checks-') as directory:
        temp = Path(directory)
        for name, fn in [('canonical', lambda: canonical_checks()),
                         ('core', lambda: core_checks(temp)),
                         ('budgets', lambda: budget_checks(temp)),
                         ('finite', lambda: finite_checks(temp, fixtures)),
                         ('maturity', lambda: maturity_checks(temp, fixtures)),
                         ('maturity_boundaries', lambda: maturity_boundary_checks(temp, fixtures)),
                         ('isolation', lambda: isolation_checks(temp)),
                         ('corruption', lambda: corruption_checks(temp))]:
            fn()
            print(name + ': passed', flush=True)
        crashes = crash_checks(temp)
    inputs = ROOT / 'results/runtime_inputs.json'
    inputs.write_text(json.dumps(fixtures, indent=2) + '\n')
    files = list((ROOT / 'gabriel_runtime').glob('*.py')) + [Path(__file__).resolve()]
    report = {'schema': 'gabriel.runtime.executed-checks.v1', 'status': 'passed', 'seed': SEED,
              'elapsed_seconds': round(time.monotonic() - started, 3),
              'python': sys.version, 'sqlite': sqlite3.sqlite_version,
              'input_sha256': hashlib.sha256(inputs.read_bytes()).hexdigest(),
              'source_sha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in sorted(files)},
              'counts': dict(sorted(COUNTS.items())), 'process_crashes': crashes,
              'comparison_tolerance': 'Exact canonical JSON and integer equality; binary64 score strings reproduced by the same legacy scoring function.',
              'independence': 'Separate test implementation: direct legacy calls outside runtime, independent set filtering and integer controller rule, independently computed journal forgery hashes. This is integration equivalence, not independent validation of the legacy binary64 scoring mathematics.',
              'not_tested': ['Physical power loss or damaged storage hardware',
                             'Malicious adapter code or arbitrary untrusted plugins',
                             'External sensor authenticity or actuation',
                             'Production throughput or predictive superiority'],
              'prefix_limitation': 'A valid historical prefix passes unanchored internal replay. A separately retained expected head/event-count anchor is necessary to detect this deletion.'}
    (ROOT / 'results/runtime_checks.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'status': report['status'], 'elapsed_seconds': report['elapsed_seconds'],
                      'counts': report['counts']}, indent=2))


if __name__ == '__main__':
    main()
