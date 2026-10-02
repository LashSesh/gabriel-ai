"""Independent exhaustive small-instance checks for decision_regions.py.

Run from the project root with python reproduction/check_decision_regions.py.
These are synthetic finite-table tests, not empirical portfolio experiments.
"""
import argparse
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
from functools import lru_cache
import hashlib
from itertools import product
import json
import math
from pathlib import Path
import platform
import time

from decision_regions import (Observation, RegionCatalogue, RegionPlanner, RegionSession,
                              exact_rational, run_policy, verify_certificate)


def oracle_sets(c):
    answer = []
    for i in range(len(c.rows)):
        feasible = [a for a in range(len(c.action_names))
                    if c.feasible[i][a] and (c.risk_limit is None or c.risks[i][a] <= c.risk_limit)]
        best = min((c.risks[i][a] for a in feasible), default=None)
        answer.append(frozenset(a for a in feasible if c.risks[i][a] - best <= c.epsilon))
    return tuple(answer)


def oracle(c):
    sets = oracle_sets(c)
    def status(rows):
        if not rows:
            return 'conflict', ()
        common = [a for a in range(len(c.action_names)) if all(a in sets[i] for i in rows)]
        if common:
            return 'known', tuple(c.action_names[a] for a in common)
        if all(not sets[i] for i in rows):
            return 'blocked', ()
        return 'unresolved', ()

    @lru_cache(None)
    def cost(rows):
        kind, _ = status(rows)
        if kind == 'conflict':
            return math.inf
        if kind in ('known', 'blocked'):
            return 0
        candidates = []
        for q in range(len(c.costs)):
            distinct = sorted({c.rows[i][q] for i in rows})
            if len(distinct) <= 1:
                continue
            branches = [tuple(i for i in rows if c.rows[i][q] == value) for value in distinct]
            candidates.append(c.costs[q] + max(cost(branch) for branch in branches))
        return min(candidates, default=math.inf)
    return status, cost


def assert_rejected(operation, exception=ValueError):
    try:
        operation()
    except exception:
        return
    raise AssertionError('invalid input was accepted')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path,
                        default=Path(__file__).resolve().parents[1] / 'results/decision_region_checks.json')
    args = parser.parse_args()
    started = time.perf_counter()
    counts = dict(two_row_models=0, two_row_states=0, four_row_models=0,
                  four_row_states=0, certificates=0, tamper_rejections=0,
                  invalid_input_rejections=0, policy_paths=0)
    statuses = {key: 0 for key in ('known', 'blocked', 'unresolved', 'conflict')}

    # Exhaustive: 3^4 risk tables, 2^4 observation tables, 2^4 feasibility
    # masks, two tolerances and two scalar limits. No random sampling.
    for scores in product((-1, 0, 1), repeat=4):
        risk = (scores[:2], scores[2:])
        for obs in product(('0', '1'), repeat=4):
            rows = (obs[:2], obs[2:])
            for flag in product((False, True), repeat=4):
                for epsilon, limit in product((0, 1), (None, 0)):
                    c = RegionCatalogue('exhaustive-two-row', ('x', 'y'), (1, 2), rows,
                                        ('a', 'b'), risk, epsilon=epsilon, risk_limit=limit,
                                        feasible=(flag[:2], flag[2:]))
                    p, (reference_status, reference_cost) = RegionPlanner(c), oracle(c)
                    for state in (1, 2, 3):
                        indices = tuple(i for i in range(2) if state & (1 << i))
                        expected_status, expected_actions = reference_status(indices)
                        actual = p.assess(state)
                        assert actual['status'] == expected_status
                        assert actual['acceptable_actions'] == expected_actions
                        assert actual['action'] == (expected_actions[0] if expected_actions else None)
                        assert p.value(state) == reference_cost(indices)
                        statuses[actual['status']] += 1
                        counts['two_row_states'] += 1
                    counts['two_row_models'] += 1

    # Exhaustive overlapping regions: all 8^4 assignments of subsets of
    # three actions to four records, with three genuinely competing queries.
    rows = (('0', '0', '0'), ('0', '1', '1'), ('1', '0', '1'), ('1', '1', '0'))
    for masks in product(range(8), repeat=4):
        flags = tuple(tuple(bool(mask & (1 << a)) for a in range(3)) for mask in masks)
        c = RegionCatalogue('exhaustive-four-row', ('x', 'y', 'xor'), (2, 3, 1), rows,
                            ('a', 'b', 'c'), ((0, 0, 0),) * 4, feasible=flags,
                            weights=(1, 2, 3, 4))
        p, (reference_status, reference_cost) = RegionPlanner(c), oracle(c)
        for state in range(16):
            indices = tuple(i for i in range(4) if state & (1 << i))
            expected_status, expected_actions = reference_status(indices)
            report = p.assess(state)
            assert (report['status'], report['acceptable_actions']) == (expected_status, expected_actions)
            assert p.value(state) == reference_cost(indices)
            chosen = p.choice(state)
            if chosen is not None:
                assert c.costs[chosen] + max(p.value(child) for child in p.branches(state, chosen)) == p.value(state)
            statuses[report['status']] += 1
            counts['four_row_states'] += 1
        if counts['four_row_models'] % 128 == 0:
            for policy in p.POLICIES:
                for row_index in range(4):
                    result = run_policy(p, row_index, policy, include_certificate=True)
                    cert = json.loads(json.dumps(result['certificate']))
                    assert verify_certificate(c, cert)
                    if result['status'] == 'known':
                        assert c.action_names.index(result['action']) in oracle_sets(c)[row_index]
                    counts['certificates'] += 1
                    counts['policy_paths'] += 1
        counts['four_row_models'] += 1

    base = RegionCatalogue('named-cases', ('field',), (1,), (('0',), ('1',)),
                           ('a', 'b'), ((0, 1), (1, 0)))
    # For every row there exists an acceptable action, but none is common.
    assert all(base.acceptable_masks)
    assert RegionPlanner(base).assess(3)['status'] == 'unresolved'
    # Current scores may be negative and genuinely fractional.
    exact = replace(base, risks=(('-3/2', '-1'), ('-1', '-3/2')), epsilon='1/2')
    assert exact.acceptable_masks == (3, 3)
    p = RegionPlanner(exact)
    assert p.value(p.all) == 0 and p.assess(p.all)['action'] == 'a'
    # Distinct strict winners need not prevent a common acceptable action.
    overlap = replace(base, epsilon=1, rows=(('same',), ('same',)))
    p = RegionPlanner(overlap)
    assert p.value(p.all) == 0 and math.isinf(p.strict_value(p.all))
    indistinguishable = replace(base, rows=(('same',), ('same',)))
    assert math.isinf(RegionPlanner(indistinguishable).value(3))
    # Empty action set for some rows is unresolved; for every row it is blocked.
    mixed = replace(base, feasible=((False, False), (True, False)))
    assert RegionPlanner(mixed).assess(3)['status'] == 'unresolved'
    blocked = replace(base, risk_limit=-1)
    assert RegionPlanner(blocked).assess(3)['status'] == 'blocked'
    assert RegionPlanner(blocked).value(3) == 0
    # Feasibility participates in the minimum, independently of risk level.
    excluded_best = replace(base, risks=((-10, 2), (-10, 2)), feasible=((False, True),) * 2)
    assert excluded_best.acceptable_masks == (2, 2)
    no_queries = replace(overlap, query_names=(), costs=(), rows=((), ()))
    assert RegionPlanner(no_queries).value(3) == 0
    assert RegionPlanner(no_queries).assess(3)['acceptable_actions'] == ('a', 'b')

    p, session = RegionPlanner(base), RegionSession(RegionPlanner(base))
    evidence = Observation(base.identity, 0, '0', 'feed:field', (7, 8), 10)
    assert session.ingest(evidence, 12)
    assert not session.ingest(evidence, 14)  # idempotent evidence, later cutoff
    cert = session.certificate()
    assert verify_certificate(base, cert)
    counts['certificates'] += 1
    for value in (True, 0.1, float('nan'), '1.0', '-0', '2/4', '01', '+1', '1/0'):
        assert_rejected(lambda v=value: exact_rational(v))
        counts['invalid_input_rejections'] += 1
    assert exact_rational(Fraction(2, 3)) == Fraction(2, 3)
    bad_models = [dict(epsilon=-1), dict(costs=(0,)), dict(costs=(True,)),
                  dict(costs=(0.5,)), dict(weights=(1, 0)), dict(feasible=((1, True),) * 2),
                  dict(max_rows=1), dict(action_names=('a', 'a')), dict(risks=((1, 2),)),
                  dict(risk_limit=False), dict(query_names=('field', 'field'))]
    for changes in bad_models:
        assert_rejected(lambda kw=changes: replace(base, **kw))
        counts['invalid_input_rejections'] += 1
    for changes, cutoff in [(dict(kind='intervention'), 12), (dict(status='predicted'), 12),
                            (dict(event_interval=(13, 14), received_at=14), 12),
                            (dict(event_interval=(7, 11)), 12), (dict(contract_digest='wrong'), 12),
                            (dict(query=True), 12), (dict(source_id=7), 12),
                            (dict(event_interval=(1,)), 12)]:
        assert_rejected(lambda kw=changes, now=cutoff: RegionSession(p).ingest(replace(evidence, **kw), now))
        counts['invalid_input_rejections'] += 1
    assert_rejected(lambda: session.ingest(evidence, 11))
    assert_rejected(lambda: session.ingest(replace(evidence, outcome='1'), 15))
    counts['invalid_input_rejections'] += 2
    for state in (-1, True, 4, 0.5):
        assert_rejected(lambda s=state: p.assess(s))
        counts['invalid_input_rejections'] += 1
    assert_rejected(lambda: RegionPlanner(base, max_states=1).value(3), RuntimeError)
    counts['invalid_input_rejections'] += 1

    # Every independent certificate claim is recomputed, including transcript
    # states. Model tampering binds even information not needed on this path.
    mutations = [lambda x: x.update(status='blocked'), lambda x: x.update(action='b'),
                 lambda x: x.update(compatible_mask='0x3'), lambda x: x.update(compatible_count=True),
                 lambda x: x.update(target='strict-best-label'), lambda x: x.update(epsilon='1'),
                 lambda x: x.update(model_identity='0' * 64), lambda x: x.update(cutoff=9),
                 lambda x: x.update(acceptable_actions=['b']), lambda x: x.update(possible_actions=[]),
                 lambda x: x.update(acceptable_masks=[dict(row=0, mask='0x3')]),
                 lambda x: x['ledger'][0].update(before='0x1'),
                 lambda x: x['ledger'][0].update(after='0x3'),
                 lambda x: x['ledger'][0]['observation'].update(kind='scenario'),
                 lambda x: x['ledger'][0]['observation'].update(received_at=13),
                 lambda x: x['ledger'][0]['observation'].update(event_interval=[7, 13]),
                 lambda x: x['ledger'][0]['observation'].update(query=True),
                 lambda x: x['ledger'].append(deepcopy(x['ledger'][0])),
                 lambda x: x.update(extra_unchecked_claim='unsafe')]
    for mutate in mutations:
        tampered = deepcopy(cert)
        mutate(tampered)
        assert not verify_certificate(base, tampered)
        counts['tamper_rejections'] += 1
    for changes in [dict(risks=((0, 1), (0, 0))), dict(epsilon=1), dict(risk_limit=3),
                    dict(feasible=((True, True), (False, True))), dict(costs=(2,)),
                    dict(action_names=('b', 'a')), dict(weights=(2, 1)),
                    dict(rows=(('0',), ('different',))), dict(contract_id='other')]:
        assert not verify_certificate(replace(base, **changes), cert)
        counts['tamper_rejections'] += 1
    conflict = RegionSession(p)
    conflict.ingest(replace(evidence, outcome='outside-model'), 12)
    assert conflict.result()['status'] == 'conflict'
    assert verify_certificate(base, conflict.certificate())
    counts['certificates'] += 1
    for catalogue in (base, exact, overlap, blocked, mixed, no_queries):
        empty_session = RegionSession(RegionPlanner(catalogue))
        assert verify_certificate(catalogue, empty_session.certificate())
        counts['certificates'] += 1

    root = Path(__file__).resolve().parent
    output = dict(schema='gabriel.decision-regions.checks.v1', passed=True,
                  scope='exhaustive synthetic finite-table verification; no empirical finance claim',
                  counts=counts, assessed_statuses=statuses,
                  exact_arithmetic='fractions.Fraction for scores; integer positive query costs',
                  named_cases=['exists common action versus pointwise existence',
                               'empty intersection versus empty union', 'negative rational scores',
                               'no-query tie with canonical action',
                               'strict labels unresolved while acceptable action known',
                               'observationally equivalent incompatible records',
                               'independent feasibility and scalar risk constraint',
                               'timestamped passive ingestion and idempotence',
                               'future-scenario evidence rejected', 'explicit state guard',
                               'model identity and transcript tampering'],
                  python=platform.python_version(), elapsed_seconds=round(time.perf_counter() - started, 3),
                  source_sha256={name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                                 for name in ('decision_regions.py', 'check_decision_regions.py')})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(passed=True, **counts, output=str(args.output))))


if __name__ == '__main__':
    main()
