"""Synthetic raw-stream integration and correction checks; no market data reads.

Run: python reproduction/check_stream.py
The reference forecasters are the unchanged numerical research modules. A second
active-set projection and direct formulas independently check corrected feedback.
"""
from pathlib import Path
from collections import Counter
from fractions import Fraction
import copy
import hashlib
import json
import math
import sqlite3
import tempfile
import time
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'reproduction'))
import numpy as np
from gabriel_runtime.canonical import canonical
from gabriel_runtime.engine import Store
from gabriel_runtime.stream import extended_registry
from ecb_risk import forecast_candidates
from severity_risk import replay_severity
from aggregate_risk import replay_adagrad

SEED = 2026092701
ATOL, RTOL = 2e-10, 2e-11
COUNTS, ERRORS = Counter(), {}


def hx(values):
    if isinstance(values, list):
        return np.array([hx(x) for x in values], dtype=float)
    return float.fromhex(values)


def equal(a, b, label):
    assert canonical(a) == canonical(b), (label, a, b)
    COUNTS[label] += 1


def close(a, b, label):
    a, b = np.asarray(a, float), np.asarray(b, float)
    assert a.shape == b.shape, (label, a.shape, b.shape)
    error = float(np.max(np.abs(a-b))) if a.size else 0.
    ERRORS[label] = max(ERRORS.get(label, 0.), error)
    assert np.allclose(a, b, rtol=RTOL, atol=ATOL), (label, error, a, b)
    COUNTS[label] += 1


def config(h):
    return {'source_id': 'synthetic-raw', 'horizon': h, 'risk_budget': '7/5',
            'unit_exposure': '3/2', 'max_units': 1000}


def payload(i, rate, revision=0, receipt=None):
    clock = 1000 + 3*i
    return {'index': i, 'event_at': clock, 'received_at': clock if receipt is None else receipt,
            'revision': revision, 'rate_hex': float(rate).hex()}


def cmd(store, ident, at, p, op='record', contract='stream'):
    return {'id': ident, 'contract': contract, 'op': op, 'at': at,
            'expected_head': store.head, 'payload': copy.deepcopy(p)}


def submit(store, ident, p, at=None):
    at = p['received_at'] if at is None else at
    c = cmd(store, ident, at, p)
    before = canonical(c)
    receipt = store.submit(c)
    assert canonical(c) == before
    return receipt


def bind(store, h):
    return store.submit(cmd(store, 'bind', 0,
                       {'adapter': 'stream-risk/v1', 'config': config(h)}, 'bind'))


def rejected(store, c, label):
    before = canonical(store.export()), canonical(store.budget), canonical(store.view('stream'))
    try:
        store.submit(c)
    except ValueError:
        pass
    else:
        raise AssertionError('missing ValueError: ' + label)
    after = canonical(store.export()), canonical(store.budget), canonical(store.view('stream'))
    assert before == after, label + ' changed logical state'
    COUNTS[label] += 1


def reference(rates, h):
    # Only algorithm parameters; this function does not load any protocol/data file.
    protocol = {'variance_initial_observations': 60,
                'variance_halflives_observed_intervals': [20, 120],
                'window': 250, 'fast_weights': ['0', '1/4', '1/2', '3/4', '1'],
                'horizons_observed_intervals': [h], 'alpha': '39/40'}
    _, native = forecast_candidates(np.asarray(rates)[:, None], protocol)
    origins, qs, es = native[0, h]
    losses = np.full(len(origins), np.nan)
    mature = origins+h < len(rates)
    losses[mature] = 100*np.log(rates[origins[mature]+h]/rates[origins[mature]])
    severity = [replay_severity(qs[:, 5], losses, h, half_life) for half_life in [125, 500]]
    bankq = np.column_stack([qs, qs[:, 5], qs[:, 5]])
    banke = np.column_stack([es, severity[0]['es'], severity[1]['es']])
    learner = replay_adagrad(bankq, banke, losses, h, .1, origins)
    return {'origins': origins, 'q': bankq, 'e': banke, 'loss': losses,
            'severity': severity, 'learner': learner}


def exact_proposal(issue, cfg):
    proposal = issue['proposal']
    exact_es = Fraction(float.fromhex(issue['es_hex']))
    budget, exposure = Fraction(cfg['risk_budget']), Fraction(cfg['unit_exposure'])
    per_unit = exposure*exact_es/100
    # Exhaustive independent finite feasible-set construction, avoiding floor.
    feasible = [n for n in range(cfg['max_units']+1) if n*per_unit <= budget]
    maximum = max(feasible)
    assert proposal['units'] == maximum
    assert proposal['kind'] == 'read_only_log_loss_proxy'
    assert proposal['budget_satisfied'] is True and proposal['maximum_feasible'] is True
    equal(proposal['es_exact'], str(exact_es), 'proposal_exact_binary64_rational')
    equal(proposal['proxy_loss'], str(maximum*per_unit), 'proposal_exact_proxy_loss')
    equal(proposal['next_unit_proxy_loss'], str((maximum+1)*per_unit), 'proposal_exact_next_unit')
    assert maximum == cfg['max_units'] or (maximum+1)*per_unit > budget
    COUNTS['proposal_exhaustive_maximality'] += 1


def independent_projection(v):
    # Active-set water filling, deliberately independent of the sorted
    # cumulative-threshold implementation used by the numerical producer.
    v = np.asarray(v, np.longdouble)
    active = np.ones(len(v), dtype=bool)
    while True:
        threshold = (v[active].sum()-1)/int(active.sum())
        changed = active & (v <= threshold)
        if not np.any(changed):
            return np.where(active, v-threshold, 0.).astype(float)
        active[changed] = False
        assert np.any(active)


def score_gradient(issue, y, weights=None):
    q, e = hx(issue['expert_var_hex']), hx(issue['expert_es_hex'])
    w = hx(issue['issued_weights_hex']) if weights is None else np.asarray(weights)
    a, b = q/e, 1/e
    aw, bw = float(a@w), float(b@w)
    hinge = y*bw-aw
    score = -math.log(bw)+aw+max(hinge, 0.)*40-1
    grad = -b/bw+a+(y*b-a)*(40 if hinge > 0 else 0)
    centered = grad-grad.mean()
    return score, grad, centered


def independent_fold(issues, feedback, latest, h):
    by_id = {x['forecast_id']: x for x in issues}
    weights = np.full((h, 8), 1/8)
    acc = np.zeros(h)
    severity = np.full(2, 1.5)
    orders = []
    lane_rows = [[] for _ in range(h)]
    for row in feedback:
        issue = by_id[row['forecast_id']]
        origin, target = issue['origin_index'], issue['target_index']
        lane = origin % h
        y = float(100*np.log(np.float64(latest[target])/np.float64(latest[origin])))
        value, gradient, centered = score_gradient(issue, y)
        u, v = hx(issue['issued_weights_hex']), weights[lane].copy()
        norm = float(centered@centered)
        before = float(acc[lane]); after = before+norm
        step = .1/math.sqrt(after) if after > 0 else 0.
        updated = independent_projection(v-step*centered)
        close(hx(row['loss_hex']), y, 'corrected_loss')
        close(hx(row['gradient_hex']), gradient, 'corrected_issued_gradient')
        close(hx(row['centered_gradient_hex']), centered, 'corrected_centered_gradient')
        close(hx(row['pre_weights_hex']), v, 'corrected_replay_pre_weights')
        close(hx(row['post_weights_hex']), updated, 'corrected_independent_projection')
        close(hx(row['accumulator_before_hex']), before, 'corrected_accumulator_before')
        close(hx(row['accumulator_after_hex']), after, 'corrected_accumulator_after')
        close(hx(row['gradient_norm_squared_hex']), norm, 'corrected_gradient_norm')
        close(hx(row['step_hex']), step, 'corrected_step')
        close(hx(row['staleness_l2_hex']), np.linalg.norm(u-v), 'corrected_staleness_l2')
        weights[lane], acc[lane] = updated, after
        response = 1+max(y-float.fromhex(issue['fast_q_hex']), 0)/(float.fromhex(issue['fast_q_hex'])/40)
        for j, half in enumerate([125, 500]):
            decay = 2**(-1/half)
            severity[j] = decay*severity[j]+(1-decay)*response
        orders.append((row['first_matured_at'], target))
        lane_rows[lane].append((issue, y, value, float(centered@(u-v)), norm))
    assert orders == sorted(orders)
    bounds = []
    for lane, rows in enumerate(lane_rows):
        norm_sum = math.fsum(row[4] for row in rows)
        residual = math.fsum(row[3] for row in rows)
        base = 10.1*math.sqrt(norm_sum)
        for i, comparator in enumerate([np.full(8, 1/8)] + list(np.eye(8))):
            regret = math.fsum(value-score_gradient(issue, y, comparator)[0]
                               for issue, y, value, _, _ in rows)
            assert regret <= base+residual+ATOL*(1+abs(regret)), (lane, regret, base, residual)
            COUNTS['fixed_issued_gradient_staleness_bound'] += 1
        bounds.append({'lane': lane, 'updates': len(rows), 'gradient_energy': norm_sum,
                       'base_bound': base, 'signed_staleness_term': residual,
                       'bound_with_staleness': base+residual})
    return weights, acc, severity, bounds


def on_time_run(temp, h, rates):
    owner_delay = 0 if h == 1 else 1000
    native = reference(rates, h)
    expected = {int(origin): j for j, origin in enumerate(native['origins'])}
    issues, snapshots = [], {}
    db = temp / ('stream-h%d.sqlite' % h)
    with Store.create(db, extended_registry()) as store:
        bind(store, h)
        for i, rate in enumerate(rates):
            p = payload(i, rate)
            receipt = submit(store, 'raw%d' % i, p, at=p['received_at']+owner_delay)
            issued = receipt['result']['issued']
            if i not in expected:
                assert issued is None
                COUNTS['warmup_no_issue'] += 1
                continue
            assert issued is not None, (h, i, receipt)
            j = expected[i]
            issues.append(issued)
            equal([issued['origin_index'], issued['target_index']], [i, i+h], 'source_count_horizon')
            equal(issued['origin_event_at'], p['event_at'], 'event_timestamp_preserved')
            equal(issued['issued_at'], p['received_at']+owner_delay, 'owner_issue_time_preserved')
            equal(issued['prediction_basis'], 'next_unreceived_observation', 'explicit_prediction_basis')
            close(hx(issued['expert_var_hex']), native['q'][j], 'native_8expert_var')
            close(hx(issued['expert_es_hex']), native['e'][j], 'native_8expert_es')
            close(hx(issued['issued_weights_hex']), native['learner']['issued_weights'][j], 'native_issued_weights')
            close(hx(issued['var_hex']), native['learner']['var'][j], 'native_aggregate_var')
            close(hx(issued['es_hex']), native['learner']['es'][j], 'native_aggregate_es')
            close(hx(issued['severity_raw_ratio_hex']), [x['issued_raw_ratio'][j] for x in native['severity']],
                  'native_severity_state')
            exact_proposal(issued, config(h))
            if j in [0, 5, 15]:
                snapshots[i] = copy.deepcopy(store.view('stream'))
                truncated = reference(rates[:i+1], h)
                close(hx(issued['expert_var_hex']), truncated['q'][-1], 'native_prefix_truncation_var')
                close(hx(issued['expert_es_hex']), truncated['e'][-1], 'native_prefix_truncation_es')
        final = store.view('stream')
        close(hx(final['learner']['lane_weights_hex']), native['learner']['final_weights'], 'native_final_lane_weights')
        close(hx(final['learner']['lane_accumulators_hex']), native['learner']['final_accumulators'],
              'native_final_accumulators')
        assert final['pending_count'] == h
        feedback = final['learner']['active_feedback']
        for row in feedback:
            assert row['first_matured_at'] == payload(row['target_index'], 1)['received_at']+owner_delay
            assert row['target_event_at'] == payload(row['target_index'], 1)['event_at']
            assert row['target_after_issue'] is (owner_delay == 0)
            COUNTS['first_maturity_owner_clock'] += 1
            COUNTS['future_event_target' if owner_delay == 0 else 'already_occurred_unreceived_target'] += 1
        independent_fold(issues, feedback, rates, h)
        # Old issued objects are retained as byte-identical records in the log.
        log_issues = [r['result']['issued'] for r in store.export()['records']
                      if r['command']['op'] == 'record' and r['result']['issued'] is not None]
        equal(log_issues, issues, 'issued_objects_unchanged_through_later_records')
        old = canonical(issues)
        revision_at = payload(len(rates), 1)['received_at']+10
        owner_revision_at = revision_at+owner_delay
        latest = np.asarray(rates).copy()
        chosen = issues[0]['target_index']
        latest[chosen] *= 1.12
        corrected = payload(chosen, latest[chosen], revision=1, receipt=revision_at)
        rec = submit(store, 'correction', corrected, at=owner_revision_at)
        assert rec['result']['issued'] is None
        revised = store.view('stream')
        equal(revised['issued_count'], len(issues), 'correction_does_not_regenerate_issues')
        equal(canonical(issues), old, 'saved_issue_objects_are_immutable')
        with sqlite3.connect(db) as raw:
            materialized = json.loads(raw.execute('SELECT state_text FROM contracts WHERE contract_id=?',
                                                 ('stream',)).fetchone()[0])
        equal(materialized['issued'], issues, 'stored_issues_unchanged_after_correction')
        revised_feedback = revised['learner']['active_feedback']
        equal([[r['forecast_id'], r['first_matured_at']] for r in revised_feedback],
              [[r['forecast_id'], r['first_matured_at']] for r in feedback], 'correction_retains_first_maturity_order')
        w, a, s, bounds = independent_fold(issues, revised_feedback, latest, h)
        close(hx(revised['learner']['lane_weights_hex']), w, 'corrected_final_weights')
        close(hx(revised['learner']['lane_accumulators_hex']), a, 'corrected_final_accumulators')
        close(hx(revised['learner']['severity_raw_ratio_hex']), s, 'corrected_final_severity')
        assert any(float.fromhex(r['staleness_l2_hex']) > 1e-8 for r in revised_feedback)
        COUNTS['correction_creates_nonzero_staleness'] += 1
        command = cmd(store, 'same-correction', owner_revision_at, corrected)
        repeated = store.submit(command)
        assert repeated['result']['accepted'] is False and repeated['result']['issued'] is None
        equal(store.view('stream'), revised, 'native_record_duplicate_is_noop')
        budget = store.budget
        equal(store.submit(command), repeated, 'outer_record_retry_same_receipt')
        equal(store.budget, budget, 'outer_record_retry_no_charge')
        invalid_cases = [
            ('bool_index', dict(corrected, index=True)),
            ('revision_gap', dict(corrected, revision=3)),
            ('event_rewrite', dict(corrected, revision=2, event_at=corrected['event_at']+1)),
            ('old_revision_conflict', dict(corrected, rate_hex=(123.).hex())),
            ('index_gap', payload(len(rates)+1, rates[-1], receipt=revision_at)),
            ('new_index_revision', payload(len(rates), rates[-1], revision=1, receipt=revision_at)),
            ('infinity', dict(corrected, revision=2, rate_hex='inf')),
            ('zero_rate', dict(corrected, revision=2, rate_hex=(0.).hex())),
            ('future_receipt', dict(corrected, revision=2, received_at=owner_revision_at+1)),
        ]
        for label, bad in invalid_cases:
            rejected(store, cmd(store, 'invalid-' + label, owner_revision_at, bad), 'atomic_reject_' + label)
        store.audit()
        COUNTS['whole_stream_semantic_audit'] += 1
    with Store.open(db, extended_registry()) as store:
        equal(store.view('stream'), revised, 'reopen_reconstructs_corrected_pipeline')
    return {'horizon': h, 'owner_receipt_delay': owner_delay, 'rates': len(rates), 'issued': len(issues),
            'matured': len(feedback), 'pending': h, 'correction_index': chosen,
            'correction_rate_hex': float(latest[chosen]).hex(),
            'regret_bounds_by_lane': bounds, 'final_corrected_view': revised}, issues, snapshots


def stale_counterexample():
    # An explicitly constructed mathematical sequence, not a fitted stream:
    # every issued weight remains on the worse first expert while the update
    # state moves toward the better second expert. This is allowed by the
    # fixed-issued-gradient theorem and disproves omitting its residual.
    issue = {'expert_var_hex': [(0.5).hex(), (0.25).hex()],
             'expert_es_hex': [(1.).hex(), (0.5).hex()],
             'issued_weights_hex': [(1.).hex(), (0.).hex()]}
    issued = np.array([1., 0.]); state = np.full(2, .5)
    regret = residual = energy = 0.
    for _ in range(200):
        value, _, g = score_gradient(issue, 0.)
        comparator = score_gradient(issue, 0., [0., 1.])[0]
        regret += value-comparator
        residual += float(g@(issued-state))
        energy += float(g@g)
        state = independent_projection(state-.1/math.sqrt(energy)*g)
    ordinary = 10.1*math.sqrt(energy)
    assert regret > ordinary+1
    assert regret <= ordinary+residual+ATOL
    COUNTS['omitted_staleness_counterexample'] += 1
    close(regret, 200*math.log(2), 'stale_example_analytic_regret')
    close(ordinary, 101., 'stale_example_analytic_ordinary_bound')
    return {'synthetic_mathematical_example': True, 'rounds': 200, 'experts': 2,
            'c': .1, 'realized_regret': regret, 'ordinary_bound_without_residual': ordinary,
            'signed_staleness_term': residual, 'bound_with_staleness': ordinary+residual}


def edge_checks(temp):
    # Arithmetic rejection is exercised before warmup, so unavailable forecasts
    # cannot silently permit nonfinite intermediate source returns.
    extreme = [float.fromhex('0x0.0000000000001p-1022'),
               float.fromhex('0x1.fffffffffffffp+1023')]
    for index, (a, b) in enumerate([extreme, extreme[::-1]]):
        with Store.create(temp/('return-overflow-%d.sqlite' % index), extended_registry()) as store:
            bind(store, 1)
            submit(store, 'first', payload(0, a))
            rejected(store, cmd(store, 'second', 1003, payload(1, b)),
                     'atomic_nonfinite_adjacent_return')
    with Store.create(temp/'constant-stream.sqlite', extended_registry()) as store:
        bind(store, 1)
        for index in range(312):
            result = submit(store, 'constant%d' % index, payload(index, 100.))
            assert result['result']['issued'] is None
        view = store.view('stream')
        equal(view['reason'], 'zero_variance_history', 'degenerate_history_explicit_unavailability')
        equal([view['source_count'], view['issued_count']], [312, 0], 'degenerate_history_retained')
        store.audit()
    # Four isolated arithmetic boundary cases use the actual proposal function;
    # the expected maximum is found by independent exhaustive enumeration.
    adapter = extended_registry()['stream-risk/v1']
    es = 1.3
    per_unit = Fraction(es)*Fraction(1, 3)/100
    records = []
    for name, budget, cap in [('zero_budget', Fraction(0), 20),
                              ('zero_capacity', 10*per_unit, 0),
                              ('exact_boundary', 7*per_unit, 20),
                              ('below_boundary', 7*per_unit-Fraction(1, 10**20), 20)]:
        cfg = dict(config(1), risk_budget=str(budget), unit_exposure='1/3', max_units=cap)
        proposal = adapter._proposal(cfg, es)
        exact_proposal({'es_hex': es.hex(), 'proposal': proposal}, cfg)
        records.append({'case': name, 'config': cfg, 'proposal': proposal})
    return records


def main():
    start = time.monotonic()
    rng = np.random.Generator(np.random.PCG64(SEED))
    returns = .004*rng.standard_normal(379)+.0015*np.sin(np.arange(379)/17)
    rates = 100*np.exp(np.r_[0., np.cumsum(returns)])
    inputs = {'schema': 'gabriel.raw-stream.synthetic-inputs.v1', 'seed': SEED,
              'generator': 'numpy.PCG64; 379 Gaussian log returns plus deterministic sine',
              'synthetic': True, 'rates_hex': [float(x).hex() for x in rates],
              'event_at': [1000+3*i for i in range(len(rates))],
              'owner_delay_by_horizon': {'1': 0, '5': 1000},
              'configs': [config(h) for h in [1, 5]]}
    results = []
    with tempfile.TemporaryDirectory(prefix='gabriel-stream-checks-') as directory:
        for h in [1, 5]:
            result, _, _ = on_time_run(Path(directory), h, rates)
            results.append(result)
            print('horizon %d passed' % h, flush=True)
        proposal_edges = edge_checks(Path(directory))
    example = stale_counterexample()
    input_path = ROOT / 'results/stream_inputs.json'
    input_path.write_text(json.dumps(inputs, indent=2)+'\n')
    paths = [ROOT/'gabriel_runtime/stream.py', Path(__file__).resolve(),
             ROOT/'reproduction/ecb_risk.py', ROOT/'reproduction/severity_risk.py',
             ROOT/'reproduction/aggregate_risk.py']
    output = {'schema': 'gabriel.raw-stream.executed-checks.v1', 'status': 'passed',
              'synthetic': True, 'seed': SEED, 'absolute_tolerance': ATOL, 'relative_tolerance': RTOL,
              'counts': dict(COUNTS), 'max_absolute_differences': ERRORS,
              'cases': results, 'staleness_counterexample': example,
              'proposal_boundary_cases': proposal_edges,
              'input_sha256': hashlib.sha256(input_path.read_bytes()).hexdigest(),
              'source_sha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
              'elapsed_seconds': time.monotonic()-start,
              'scope': 'Synthetic integration equivalence, independent correction fold, and exact finite modeled-proposal check; no forecast accuracy, empirical calibration or investment-performance result.',
              'limitations': ['Binary64 numerical checks, not directed-rounding certificates',
                              'Unchanged native forecasters are reference implementations, not independent evidence of their statistical validity',
                              'No reserved currencies read or evaluated',
                              'Process-crash durability belongs to separately executed check_runtime.py; not repeated here']}
    (ROOT/'results/stream_checks.json').write_text(json.dumps(output, indent=2)+'\n')
    print(json.dumps({'status': 'passed', 'counts': dict(COUNTS),
                      'maximum_difference': max(ERRORS.values()),
                      'elapsed_seconds': output['elapsed_seconds']}, indent=2))


if __name__ == '__main__':
    main()
