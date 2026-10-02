"""Independent exact-output regression for the incremental execution profile.

Reference: unmodified StreamRiskAdapter; no market files or reserved data read.
Run from project root: python reproduction/check_incremental.py
All timing measurements are elapsed execution diagnostics, not speed claims.
"""
from collections import Counter
from pathlib import Path
import copy
import hashlib
import json
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
from gabriel_runtime.canonical import canonical, digest
from gabriel_runtime.engine import Store
from gabriel_runtime.stream import StreamRiskAdapter, extended_registry
from gabriel_runtime.incremental import IncrementalStreamRiskAdapter, incremental_registry

SEED = 2026092603
COUNTS = Counter()
DETAILS = {}
BASELINE_WORK = Counter()


def equal(a, b, label):
    assert canonical(a) == canonical(b), label
    COUNTS[label] += 1


def config(h, source='incremental-synthetic', budget='7/5'):
    return dict(source_id=source, horizon=h, risk_budget=budget,
                unit_exposure='3/2', max_units=1000)


def payload(i, rate, revision=0, receipt=None):
    at = 1000 + 3*i
    return dict(index=i, event_at=at, received_at=at if receipt is None else receipt,
                revision=revision, rate_hex=float(rate).hex())


def latest(state):
    rows = {}
    for row in state['receipts']:
        rows[row['index']] = row
    return rows


class Pair:
    def __init__(self, h, inc=None, source='incremental-synthetic', budget='7/5'):
        self.base = StreamRiskAdapter()
        self.inc = IncrementalStreamRiskAdapter() if inc is None else inc
        self.b = self.base.initialize(config(h, source, budget))
        self.i = self.inc.initialize(config(h, source, budget))
        equal(self.b, self.i, 'initialize_exact')

    def view(self):
        vb, vi = self.base.view(self.b), self.inc.view(self.i)
        BASELINE_WORK['gradient_evaluations'] += len(vb['learner']['active_feedback'])
        equal(vb, vi, 'view_exact')
        return vi

    def apply(self, p, op='record', at=None, warm_bound=None):
        at = p['received_at'] if at is None else at
        input_b, input_i = canonical(self.b), canonical(self.i)
        old_issues = [canonical(x) for x in self.b['issued']]
        old_fb = self.inc.view(self.i)['learner']['active_feedback']
        mb = self.inc.metrics()
        b, rb = self.base.apply(self.b, op, p, at)
        i, ri = self.inc.apply(self.i, op, p, at)
        equal(b, i, 'transition_state_exact')
        equal(rb, ri, 'transition_result_exact')
        BASELINE_WORK['gradient_evaluations'] += len(rb['view']['learner']['active_feedback'])
        assert canonical(self.b) == input_b and canonical(self.i) == input_i
        COUNTS['caller_states_unmodified'] += 1
        equal([canonical(x) for x in i['issued'][:len(old_issues)]], old_issues,
              'old_issued_bytes_immutable')
        self.b, self.i = b, i
        self.view()
        ma = self.inc.metrics()
        delta = {k: ma[k] - mb[k] for k in ma}
        if warm_bound is not None:
            assert delta['gradient_evaluations'] <= warm_bound, delta
            COUNTS['warm_gradient_work_bounded'] += 1
        new_fb = ri['view']['learner']['active_feedback']
        old_by_id = {x['forecast_id']: x for x in old_fb}
        changed = [x for x in new_fb if x['forecast_id'] in old_by_id
                   and x['loss_hex'] != old_by_id[x['forecast_id']]['loss_hex']]
        if p['revision'] and ri['accepted']:
            s, h = p['index'], self.i['config']['horizon']
            issues = {x['forecast_id']: x for x in self.i['issued']}
            assert len(changed) <= 2
            assert all(issues[x['forecast_id']]['origin_index'] == s
                       or x['target_index'] == s for x in changed)
            assert all(x['lane'] == s % h for x in changed)
            COUNTS['correction_endpoint_locality'] += 1
        return ri, delta

    def reject(self, p, label, op='record', at=None):
        at = p.get('received_at', 9000) if at is None else at
        states = canonical(self.b), canonical(self.i)
        classes = []
        for adapter, state in ((self.base, self.b), (self.inc, self.i)):
            try:
                adapter.apply(state, op, p, at)
            except (ValueError, TypeError) as exc:
                classes.append(type(exc).__name__)
            else:
                raise AssertionError('accepted invalid ' + label)
        assert classes[0] == classes[1], (label, classes)
        assert states == (canonical(self.b), canonical(self.i))
        COUNTS['rejection_' + label] += 1
        self.view()


def generated_inputs():
    rng = np.random.default_rng(SEED)
    increments = rng.normal(.0002, .007, 341) + .0015*np.sin(np.arange(341)/9)
    rates = 100*np.exp(np.r_[0., np.cumsum(increments)])
    return {'schema': 'gabriel.incremental.synthetic-inputs.v1',
            'synthetic': True, 'seed': SEED,
            'generator': 'numpy.PCG64; 341 Gaussian log returns plus deterministic sine',
            'rates_hex': [float(x).hex() for x in rates],
            'horizons': [1, 5],
            'correction_indices': [0, 1, 59, 60, 61, 160, 315, 330, 339],
            'correction_multipliers': ['257/256', '255/256', '513/512', '129/128', '127/128',
                                       '65/64', '33/32', '63/64', '31/32'],
            'same_value_revision_index': 339,
            'caps': 'source/revision reachable constant histories; issue cap isolated synthetic guard'}


def path_checks(inputs):
    rates = [float.fromhex(x) for x in inputs['rates_hex']]
    terminal, histories = {}, {}
    from fractions import Fraction
    for h in inputs['horizons']:
        pair = Pair(h)
        pair.inc.reset_metrics()
        snapshots = {}
        for j in range(340):
            pair.apply(payload(j, rates[j]), warm_bound=1)
            if j in (60, 310, 319, 339):
                snapshots[j] = copy.deepcopy(pair.b)
        append_metrics = pair.inc.metrics()
        mature = len(pair.b['maturity'])
        assert append_metrics['gradient_evaluations'] == mature, append_metrics
        COUNTS['one_gradient_per_new_maturity'] += 1
        for j, (s, mult) in enumerate(zip(inputs['correction_indices'],
                                        inputs['correction_multipliers'])):
            row = latest(pair.b)[s]
            value = float.fromhex(row['rate_hex'])*float(Fraction(mult))
            result, work = pair.apply(payload(s, value, row['revision']+1, 5000+j),
                                      warm_bound=2)
            DETAILS.setdefault('corrections', []).append(
                {'horizon': h, 'index': s, 'gradient_evaluations': work['gradient_evaluations'],
                 'metrics_delta': work,
                 'feedback_count': len(result['view']['learner']['active_feedback'])})
        row = latest(pair.b)[339]
        pair.apply(payload(339, float.fromhex(row['rate_hex']), row['revision']+1, 5010),
                   warm_bound=2)
        for j in (340, 341):
            pair.apply(payload(j, rates[j], receipt=5011+j-340), warm_bound=1)
        # Native duplicate does not create another contribution or issue.
        duplicate = copy.deepcopy(pair.b['receipts'][-1])
        result, work = pair.apply(duplicate, at=5020, warm_bound=0)
        assert result['accepted'] is False
        COUNTS['native_duplicate_no_extra_effect'] += 1
        current_view = pair.view()
        pair.inc.clear_cache()
        equal(pair.inc.view(pair.i), current_view, 'cold_warm_view_exact')
        # A single adapter is deliberately rewound through old canonical states.
        for index in (60, 319, 310, 339):
            state = snapshots[index]
            equal(pair.inc.view(state), pair.base.view(state), 'rewind_view_exact')
        equal(pair.inc.view(pair.i), current_view, 'return_to_current_view_exact')
        # Two alternate next records branch from the identical original prefix.
        for factor in (1.01, .99):
            state = snapshots[319]
            p = payload(320, rates[320]*factor, receipt=8000)
            b, rb = pair.base.apply(state, 'record', p, 8000)
            i, ri = pair.inc.apply(state, 'record', p, 8000)
            equal(b, i, 'fork_transition_state_exact')
            equal(rb, ri, 'fork_transition_result_exact')
        terminal[h] = pair
        histories[h] = snapshots
        DETAILS.setdefault('append_work', []).append(
            {'horizon': h, 'source_records': 340, 'mature_targets': mature,
             'incremental_metrics': append_metrics})
    return terminal, histories


def mixed_and_dependency_checks(pairs, snapshots):
    shared = IncrementalStreamRiskAdapter()
    h1, h5 = pairs[1].b, pairs[5].b
    variants = [copy.deepcopy(h1), copy.deepcopy(h5), copy.deepcopy(h1)]
    variants[2]['config'] = config(1, 'different-source', '11/7')
    for state in [variants[0], variants[1], variants[2], variants[0], variants[2], variants[1]]:
        equal(shared.view(state), StreamRiskAdapter().view(state), 'interleaved_view_exact')
        row = latest(state)[len(latest(state))-1]
        p = payload(row['index'], float.fromhex(row['rate_hex'])*1.001,
                    row['revision']+1, 10000)
        b, rb = StreamRiskAdapter().apply(state, 'record', p, 10000)
        i, ri = shared.apply(state, 'record', p, 10000)
        equal(b, i, 'interleaved_transition_state_exact')
        equal(rb, ri, 'interleaved_transition_result_exact')
    # These direct-state edits probe invalidation dependencies, not owner input
    # permissions: authenticated issued histories cannot be rewritten in Store.
    baseline = StreamRiskAdapter()
    original = pairs[5].b
    cases = []
    for field in ('fast_q_hex', 'expert_var_hex', 'expert_es_hex', 'issued_weights_hex'):
        changed = copy.deepcopy(original)
        issue = changed['issued'][3]
        if field == 'issued_weights_hex':
            w = [float.fromhex(x) for x in issue[field]]
            w[0] += .001; w[1] -= .001
            issue[field] = [x.hex() for x in w]
        elif type(issue[field]) is list:
            issue[field][0] = (float.fromhex(issue[field][0])*1.002).hex()
        else:
            issue[field] = (float.fromhex(issue[field])*1.002).hex()
        assert issue['digest'] == original['issued'][3]['digest']
        cases.append((field, changed))
    changed = copy.deepcopy(original)
    changed['maturity'][changed['issued'][3]['forecast_id']]['first_matured_at'] += 10000
    cases.append(('maturity_order', changed))
    changed = copy.deepcopy(original)
    changed['issued'][3]['issued_at'] += 10000
    cases.append(('issued_time', changed))
    changed = copy.deepcopy(original)
    changed['receipts'][-1]['rate_hex'] = (float.fromhex(changed['receipts'][-1]['rate_hex'])*1.01).hex()
    cases.append(('actual_endpoint_record', changed))
    for label, state in cases:
        shared.view(original)
        equal(shared.view(state), baseline.view(state), 'actual_dependency_' + label)
        shared.clear_cache()
        equal(shared.view(state), baseline.view(state), 'dependency_cold_' + label)
    DETAILS['direct_state_dependency_fixtures'] = [x[0] for x in cases]
    # Returned structures are caller owned, including cached nested values.
    shared.view(original)
    returned = shared.view(original)
    returned['learner']['lane_weights_hex'][0][0] = (987.).hex()
    returned['learner']['active_feedback'][0]['gradient_hex'][0] = (-123.).hex()
    equal(shared.view(original), baseline.view(original), 'returned_view_alias_isolation')
    p = payload(342, 101., receipt=15000)
    state, result = shared.apply(original, 'record', p, 15000)
    expected = baseline.view(state)
    result['view']['learner']['lane_weights_hex'][0][0] = (987.).hex()
    if result['issued'] is not None:
        result['issued']['expert_es_hex'][0] = (777.).hex()
    equal(shared.view(state), expected, 'returned_result_alias_isolation')


def unavailable_checks(inputs):
    rates = [float.fromhex(x) for x in inputs['rates_hex']]
    pair = Pair(1, source='flat-seed')
    for j in range(315):
        pair.apply(payload(j, 100. if j <= 60 else rates[j]))
    assert not pair.b['issued']
    assert pair.b['last_reason'] == 'zero_variance_history'
    COUNTS['flat_seed_then_motion_remains_unavailable'] += 1
    pair.apply(payload(0, 99., 1, 6000))
    result, work = pair.apply(payload(315, rates[315], receipt=6001))
    assert result['issued'] is not None
    COUNTS['historical_seed_correction_restores_availability'] += 1


def rejection_checks(pair):
    state = copy.deepcopy(pair.b)
    row = latest(state)[341]
    valid = payload(341, float.fromhex(row['rate_hex'])*1.001, row['revision']+1, 12000)
    bad = []
    for field in ('index', 'event_at', 'received_at', 'revision'):
        bad.append(('bool_' + field, dict(valid, **{field: True})))
    bad += [('missing_field', {k:v for k,v in valid.items() if k != 'rate_hex'}),
            ('extra_field', dict(valid, extra=0)),
            ('negative_rate', dict(valid, rate_hex=(-1.).hex())),
            ('zero_rate', dict(valid, rate_hex=0.0.hex())),
            ('nan', dict(valid, rate_hex='nan')),
            ('infinity', dict(valid, rate_hex='inf')),
            ('revision_gap', dict(valid, revision=valid['revision']+1)),
            ('changed_event_time', dict(valid, event_at=valid['event_at']+1)),
            ('noncontiguous', dict(valid, index=343, revision=0)),
            ('backdated_receipt', dict(valid, received_at=1100)),
            ('receipt_after_owner', dict(valid, received_at=12001))]
    for label, p in bad:
        pair.reject(p, label, at=12000)
    pair.reject(valid, 'unknown_operation', op='anything', at=12000)
    pair.reject(valid, 'bool_owner', at=True)
    # Real positive-finite ingress whose adjacent division over/underflows.
    for label, first, second in (
        ('division_overflow', float.fromhex('0x0.0000000000001p-1022'),
         float.fromhex('0x1.fffffffffffffp+1023')),
        ('division_underflow', float.fromhex('0x1.fffffffffffffp+1023'),
         float.fromhex('0x0.0000000000001p-1022'))):
        edge = Pair(1, source=label)
        edge.apply(payload(0, first))
        edge.reject(payload(1, second), label)
        edge.apply(payload(1, first))
        COUNTS['valid_command_after_arithmetic_failure'] += 1
    # Derived transition computes its private caches, then fails before return.
    pair.inc.view(pair.i)
    original = pair.inc._forecast
    calls = []
    def injected(*args, **kwargs):
        value = original(*args, **kwargs)
        calls.append(True)
        raise ValueError('injected post-forecast pre-commit failure')
    pair.inc._forecast = injected
    p = payload(342, float.fromhex(row['rate_hex'])*1.003, receipt=13000)
    before = canonical(pair.i)
    try:
        pair.inc.apply(pair.i, 'record', p, 13000)
    except ValueError as exc:
        assert 'injected' in str(exc)
    else:
        raise AssertionError('fault injection failed')
    finally:
        pair.inc._forecast = original
    assert calls and canonical(pair.i) == before
    pair.apply(p)
    COUNTS['recovery_after_uncommitted_cache_work'] += 1
    # A valid correction also succeeds after ordinary malformed ingress.
    row = latest(pair.b)[341]
    pair.apply(payload(341, float.fromhex(row['rate_hex']), row['revision']+1, 13001))


def historical_domain_checks(terminal):
    # Accepted source corrections can create a nonfinite five-step return
    # outside the current 250-scenario window while every adjacent return is
    # finite. Revisions themselves issue nothing; the following append must
    # retain the baseline's full historical scenario-domain rejection.
    for direction in (1, -1):
        pair = Pair(5, source='historical-domain')
        pair.b = copy.deepcopy(terminal[5].b)
        pair.i = copy.deepcopy(terminal[5].i)
        original_rows = latest(pair.b)
        exponents = [-250, -150, -50, 50, 150, 250]
        if direction < 0:
            exponents.reverse()
        for offset, exponent in enumerate(exponents):
            s = 80 + offset
            row = latest(pair.b)[s]
            pair.apply(payload(s, 10.**exponent, row['revision']+1, 17000+offset),
                       warm_bound=0)
        rows = latest(pair.b)
        x = np.array([float.fromhex(rows[j]['rate_hex']) for j in range(len(rows))])
        with np.errstate(over='ignore', under='ignore', divide='ignore', invalid='ignore'):
            adjacent = 100*np.log(x[1:]/x[:-1])
            five = 100*np.log(x[5:]/x[:-5])
        assert np.isfinite(adjacent).all()
        assert not np.isfinite(five[80]).all()
        assert np.isfinite(five[-250:]).all()
        p = payload(342, 101., receipt=18000)
        pair.reject(p, 'historical_h5_' + ('overflow' if direction > 0 else 'underflow'))
        # Revert accepted corrections in reverse order; a subsequent valid
        # forecast proves that rejected private cache work cannot poison retry.
        for offset in reversed(range(6)):
            index = 80+offset
            row = latest(pair.b)[index]
            rate = float.fromhex(original_rows[index]['rate_hex'])
            pair.apply(payload(index, rate, row['revision']+1, 18001+5-offset))
        pair.apply(payload(342, 101., receipt=18010))
        COUNTS['old_horizon_nonfinite_repair_recovery'] += 1


def cap_checks(terminal):
    # Reachable flat-price canonical histories avoid unnecessary long replay.
    pair = Pair(1, source='source-cap')
    state = pair.base.initialize(config(1, 'source-cap'))
    state['receipts'] = [payload(i, 100.) for i in range(1023)]
    state['last_status'], state['last_reason'] = 'unavailable', 'zero_variance_history'
    pair.b, pair.i = copy.deepcopy(state), copy.deepcopy(state)
    pair.apply(payload(1023, 100.))
    pair.reject(payload(1024, 100.), 'source_capacity')
    pair = Pair(1, source='revision-cap')
    state = pair.base.initialize(config(1, 'revision-cap'))
    state['receipts'] = [payload(0, 100., i, 1000+i) for i in range(2047)]
    state['last_status'], state['last_reason'] = 'revised', 'current_learner_replayed'
    pair.b, pair.i = copy.deepcopy(state), copy.deepcopy(state)
    pair.apply(payload(0, 100., 2047, 3047))
    pair.reject(payload(1, 100., receipt=3048), 'revision_capacity')
    COUNTS['reachable_constructed_capacity_boundaries'] += 2
    # Isolated guard fixture only; repeated synthetic pending issues are not
    # asserted to be a history constructible through accepted owner commands.
    state = copy.deepcopy(terminal[5].b)
    prototype = state['issued'][-1]
    state['issued'] = [dict(copy.deepcopy(prototype), forecast_id='guard-%d' % j,
                            target_index=1000000+j) for j in range(512)]
    state['maturity'] = {}
    pair = Pair(5)
    pair.b, pair.i = copy.deepcopy(state), copy.deepcopy(state)
    result, work = pair.apply(payload(342, 101., receipt=16000))
    assert result['issued'] is None and result['view']['reason'] == 'issuance_capacity'
    COUNTS['constructed_issue_capacity_guard'] += 1


def owner_checks(temp, inputs):
    rates = [float.fromhex(x) for x in inputs['rates_hex']]
    registry = incremental_registry()
    adapter = registry['stream-risk/v1']
    assert type(adapter) is IncrementalStreamRiskAdapter
    db = temp / 'incremental.sqlite'
    baseline, bstate = StreamRiskAdapter(), None
    commands = []
    with Store.create(db, registry) as store:
        def send(ident, at, p, op='record'):
            command = {'id':ident, 'contract':'stream', 'op':op, 'at':at,
                       'expected_head':store.head, 'payload':copy.deepcopy(p)}
            commands.append(command)
            return store.submit(command)
        send('bind', 0, {'adapter':'stream-risk/v1', 'config':config(5, 'owner-check')}, 'bind')
        bstate = baseline.initialize(config(5, 'owner-check'))
        for j in range(324):
            p = payload(j, rates[j])
            receipt = send('r%d' % j, p['received_at'], p)
            bstate, result = baseline.apply(bstate, 'record', p, p['received_at'])
            equal(receipt['result'], result, 'owner_transition_result_exact')
        p = payload(320, rates[320]*1.01, 1, 6000)
        receipt = send('correction', 6000, p)
        bstate, result = baseline.apply(bstate, 'record', p, 6000)
        equal(receipt['result'], result, 'owner_correction_exact')
        before = canonical(store.export()), canonical(store.budget), canonical(store.view('stream'))
        equal(store.submit(commands[-1]), receipt, 'owner_retry_receipt_exact')
        assert before == (canonical(store.export()), canonical(store.budget), canonical(store.view('stream')))
        COUNTS['owner_retry_uncharged'] += 1
        # Clear nonsemantic caches before the same owner read and full audit.
        adapter.clear_cache()
        expected_view = baseline.view(bstate)
        equal(store.view('stream'), expected_view, 'owner_cold_view_exact')
        anchor = {'head':store.head, 'events':store.budget['events']}
        store.audit(expected_head=anchor['head'], expected_events=anchor['events'])
        COUNTS['owner_semantic_audit'] += 1
    with Store.open(db, incremental_registry(), expected_head=anchor['head'],
                    expected_events=anchor['events']) as reopened:
        equal(reopened.view('stream'), expected_view, 'owner_reopen_exact')
    try:
        Store.open(db, extended_registry())
    except ValueError as exc:
        assert 'fingerprint' in str(exc)
        COUNTS['wrong_execution_profile_rejected'] += 1
    else:
        raise AssertionError('baseline opened incremental fingerprint')
    legacy_db = temp / 'baseline.sqlite'
    with Store.create(legacy_db, extended_registry()):
        pass
    try:
        Store.open(legacy_db, incremental_registry())
    except ValueError as exc:
        assert 'fingerprint' in str(exc)
        COUNTS['reverse_wrong_execution_profile_rejected'] += 1
    else:
        raise AssertionError('incremental opened baseline fingerprint')
    DETAILS['owner'] = {'commits':anchor['events'], 'head':anchor['head'],
                        'issued':len(bstate['issued']), 'mature':len(bstate['maturity'])}


def main():
    started = time.perf_counter()
    inputs = generated_inputs()
    pairs, snapshots = path_checks(inputs)
    mixed_and_dependency_checks(pairs, snapshots)
    rejection_checks(pairs[1])
    unavailable_checks(inputs)
    historical_domain_checks(pairs)
    cap_checks(pairs)
    with tempfile.TemporaryDirectory(prefix='gabriel-incremental-') as temporary:
        owner_checks(Path(temporary), inputs)
    results = ROOT / 'results'
    results.mkdir(exist_ok=True)
    input_path = results / 'incremental_inputs.json'
    input_path.write_text(json.dumps(inputs, indent=2)+'\n')
    source_files = ['gabriel_runtime/incremental.py', 'gabriel_runtime/stream.py',
                    'gabriel_runtime/engine.py', 'gabriel_runtime/canonical.py',
                    'reproduction/check_incremental.py', 'reproduction/ecb_risk.py',
                    'reproduction/aggregate_risk.py', 'reproduction/severity_risk.py']
    output = {'schema':'gabriel.incremental.checks.v1', 'status':'passed', 'synthetic':True,
              'seed':SEED, 'elapsed_seconds':time.perf_counter()-started,
              'comparison':'canonical JSON exact equality; no numerical tolerance',
              'counts':dict(COUNTS), 'details':DETAILS,
              'baseline_counted_gradient_work':dict(BASELINE_WORK),
              'inputs_sha256':hashlib.sha256(input_path.read_bytes()).hexdigest(),
              'source_sha256':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest()
                               for p in source_files},
              'environment':{'python':sys.version.split()[0], 'numpy':np.__version__},
              'limits':['synthetic integration and cache invalidation, not market superiority',
                        'direct state dependency mutations test cache trust boundaries, not owner permissions',
                        'fault injection tests computed-but-uncommitted cache recovery, not physical power loss',
                        'source and revision cap histories constructed directly; no new complete-capacity journal']}
    (results / 'incremental_checks.json').write_text(json.dumps(output, indent=2)+'\n')
    print(json.dumps({'status':'passed', 'elapsed_seconds':output['elapsed_seconds'],
                      'counts':dict(COUNTS), 'details':DETAILS}, indent=2))


if __name__ == '__main__':
    main()
