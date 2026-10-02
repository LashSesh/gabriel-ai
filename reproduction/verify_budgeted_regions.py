"""Independent tuple-posterior replay of budget-constrained acquisition.

This verifier does not import either decision-region planner. It reconstructs
acceptable actions from the saved rational score table and solves the finite
query problems directly over tuples of compatible row indices. The inherited
portfolio risk calculation is not rerun: its exact previously verified output
is bound by hashes. All claims remain conditional on the supplied catalogue.
"""
from collections import Counter
from copy import deepcopy
from fractions import Fraction as F
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import platform
import time

ROOT = Path(__file__).resolve().parents[1]


def exact(value):
    if type(value) is int:
        return F(value)
    if type(value) is F:
        return value
    if type(value) is str:
        result = F(value)
        if str(result) == value:
            return result
    raise ValueError('canonical exact rational required')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def file_digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def mask(rows):
    return hex(sum(1 << row for row in rows))


class TupleOracle:
    """Independent set-valued decision and remaining-budget dynamic programs."""

    def __init__(self, catalogue, prior=None):
        self.c = catalogue
        self.rows = tuple(tuple(row) for row in catalogue['rows'])
        self.costs = tuple(catalogue['costs'])
        self.actions = tuple(catalogue['action_names'])
        self.all = tuple(range(len(self.rows)))
        self.weights = tuple(catalogue.get('weights') or (1,) * len(self.rows))
        raw = self.weights if prior is None else prior
        weights = tuple(exact(value) for value in raw)
        if len(weights) != len(self.rows) or any(value <= 0 for value in weights):
            raise ValueError('positive prior weight for every catalogue row required')
        total = sum(weights, F(0))
        self.prior = tuple(value / total for value in weights)
        epsilon = exact(catalogue['epsilon'])
        limit = None if catalogue['risk_limit'] is None else exact(catalogue['risk_limit'])
        scores = tuple(tuple(exact(v) for v in row) for row in catalogue['risks'])
        flags = catalogue.get('feasible') or [[True] * len(self.actions) for _ in self.rows]
        self.allowed = []
        for row_scores, row_flags in zip(scores, flags):
            feasible = {a for a in range(len(self.actions))
                        if row_flags[a] and (limit is None or row_scores[a] <= limit)}
            best = min((row_scores[a] for a in feasible), default=None)
            self.allowed.append(frozenset(a for a in feasible if row_scores[a] <= best + epsilon))
        self.identity = digest(dict(schema='gabriel.decision-regions.model.v1',
                                    contract_id=catalogue['contract_id'],
                                    query_names=catalogue['query_names'], costs=self.costs,
                                    rows=self.rows, action_names=self.actions,
                                    risks=[[str(v) for v in row] for row in scores],
                                    epsilon=str(epsilon),
                                    risk_limit=None if limit is None else str(limit),
                                    weights=self.weights, feasible=flags))
        self.mass = lru_cache(None)(lambda rows: sum((self.prior[i] for i in rows), F(0)))
        self.terminal = lru_cache(None)(lambda rows:
            bool(rows) and self.assessment(rows)['status'] in ('known', 'blocked'))
        self.informative = lru_cache(None)(self._informative)
        self.worst = lru_cache(None)(self._worst)
        self.local = lru_cache(None)(self._local)
        self.value = lru_cache(None)(self._value)

    def assessment(self, rows):
        common = set.intersection(*(set(self.allowed[i]) for i in rows)) if rows else set()
        possible = set.union(*(set(self.allowed[i]) for i in rows)) if rows else set()
        status = 'conflict' if not rows else 'known' if common else 'blocked' if not possible else 'unresolved'
        selected = [self.actions[a] for a in range(len(self.actions)) if a in common]
        return dict(status=status, action=selected[0] if selected else None,
                    acceptable_actions=selected,
                    possible_actions=[self.actions[a] for a in range(len(self.actions)) if a in possible],
                    compatible_count=len(rows), compatible_weight=sum(self.weights[i] for i in rows))

    def _informative(self, rows):
        choices = []
        for q in range(len(self.costs)):
            outcomes = sorted({self.rows[i][q] for i in rows})
            if len(outcomes) > 1:
                choices.append((q, tuple(tuple(i for i in rows if self.rows[i][q] == outcome)
                                         for outcome in outcomes)))
        return tuple(choices)

    def _worst(self, rows):
        if not rows:
            return math.inf
        if self.terminal(rows):
            return 0
        return min((self.costs[q] + max(self.worst(child) for child in children)
                    for q, children in self.informative(rows)), default=math.inf)

    def _local(self, rows):
        if not rows:
            return math.inf, math.inf, None
        if self.terminal(rows):
            return 0, F(0), None
        choices = []
        for q, children in self.informative(rows):
            values = tuple(self.local(child) for child in children)
            if any(math.isinf(value[0]) for value in values):
                continue
            worst = self.costs[q] + max(value[0] for value in values)
            mean = self.costs[q] + sum((self.mass(child) * value[1]
                                       for child, value in zip(children, values)), F(0)) / self.mass(rows)
            choices.append((worst, mean, q))
        return min(choices) if choices else (math.inf, math.inf, None)

    def _value(self, rows, budget):
        if not rows or budget < 0:
            return math.inf
        if self.terminal(rows):
            return F(0)
        candidates = self.budget_choices(rows, budget)
        return min((value for value, q in candidates), default=math.inf)

    def budget_choices(self, rows, budget):
        candidates = []
        for q, children in self.informative(rows):
            remaining = budget - self.costs[q]
            if remaining < 0:
                continue
            values = tuple(self.value(child, remaining) for child in children)
            if any(math.isinf(value) for value in values):
                continue
            mean = self.costs[q] + sum((self.mass(child) * value
                                       for child, value in zip(children, values)), F(0)) / self.mass(rows)
            candidates.append((mean, q))
        return candidates

    def choice(self, rows, budget, policy):
        if not rows or self.terminal(rows):
            return None
        candidates = self.informative(rows)
        if policy == 'reverse':
            return candidates[-1][0] if candidates else None
        if policy in ('old_minimax', 'minimax'):
            return min(candidates, key=lambda item:
                       (self.costs[item[0]] + max(self.worst(child) for child in item[1]), item[0]))[0]
        if policy == 'local_lex':
            return self.local(rows)[2]
        if policy == 'global_lex':
            candidates = self.budget_choices(rows, budget)
            return min(candidates)[1] if candidates else None
        raise ValueError('unknown oracle policy')

    def count_states(self):
        return dict(worst=self.worst.cache_info().currsize,
                    local_lex=self.local.cache_info().currsize,
                    residual_budget=self.value.cache_info().currsize)


def replay_certificate(oracle, certificate, case, policy, budget, snapshot=100):
    """Check every model, evidence, query-choice and stopping field independently."""
    c = oracle.c
    expected_header = dict(schema='gabriel.decision-regions.certificate.v1',
                           model_identity=oracle.identity, target='common-epsilon-feasible-action',
                           action_order=list(oracle.actions), epsilon=str(exact(c['epsilon'])),
                           risk_limit=None if c['risk_limit'] is None else str(exact(c['risk_limit'])))
    for key, value in expected_header.items():
        assert certificate[key] == value, ('certificate header', key)
    rows, cost, queries = oracle.all, 0, []
    assert type(case) is int and case in rows
    for entry in certificate['ledger']:
        assert set(entry) == {'observation', 'cutoff', 'before', 'after'}
        evidence = entry['observation']
        assert set(evidence) == {'contract_digest', 'query', 'outcome', 'source_id',
                                 'event_interval', 'received_at', 'status', 'kind'}
        q = evidence['query']
        assert type(q) is int and 0 <= q < len(oracle.costs) and q not in queries
        assert not oracle.terminal(rows), 'acquisition continued after common-action terminal'
        assert q == oracle.choice(rows, budget - cost, policy), 'policy query mismatch'
        assert evidence['contract_digest'] == oracle.identity
        assert evidence['source_id'] == 'current-record:' + str(q)
        assert evidence['kind'] == 'passive' and evidence['status'] == 'observed'
        assert evidence['event_interval'] == [snapshot, snapshot]
        assert all(type(t) is int for t in evidence['event_interval'])
        assert evidence['outcome'] == oracle.rows[case][q]
        assert entry['before'] == mask(rows)
        cost += oracle.costs[q]
        assert type(evidence['received_at']) is int and type(entry['cutoff']) is int
        assert evidence['received_at'] == snapshot + cost == entry['cutoff']
        rows = tuple(i for i in rows if oracle.rows[i][q] == evidence['outcome'])
        assert entry['after'] == mask(rows)
        queries.append(q)
    assert case in rows and oracle.terminal(rows), 'incorrect or unfinished decision'
    expected = dict(expected_header, ledger=certificate['ledger'],
                    cutoff=snapshot + cost if queries else None,
                    compatible_mask=mask(rows),
                    acceptable_masks=[dict(row=i, mask=hex(sum(1 << a for a in oracle.allowed[i])))
                                      for i in rows], **oracle.assessment(rows))
    assert json.dumps(certificate, sort_keys=True) == json.dumps(expected, sort_keys=True), 'final certificate fields'
    return dict(cost=cost, queries=queries, rows=rows,
                status=expected['status'], action=expected['action'])


def counterexample_check():
    """Enumerate every nonredundant tree for the six-row witness."""
    columns = (15, 3, 5, 1, 16)
    c = dict(contract_id='residual-budget-six-row-witness',
             query_names=['q0', 'q1', 'q2', 'q3', 'q4'], costs=[1, 1, 1, 1, 3],
             rows=[[str((column >> i) & 1) for column in columns] for i in range(6)],
             action_names=list('ABCDEF'), risks=[[0 if i == j else 1 for j in range(6)] for i in range(6)],
             feasible=[[True] * 6 for _ in range(6)], weights=[3, 1, 1, 1, 1, 1],
             epsilon='0', risk_limit=None)
    oracle = TupleOracle(c)

    @lru_cache(None)
    def all_tree_costs(rows):
        if oracle.terminal(rows):
            return {(0, 0): 1}
        results = Counter()
        for q, children in oracle.informative(rows):
            assert len(children) == 2
            left, right = children
            mass = sum(c['weights'][i] for i in rows)
            for (lw, le), ln in all_tree_costs(left).items():
                for (rw, re), rn in all_tree_costs(right).items():
                    results[(c['costs'][q] + max(lw, rw), c['costs'][q] * mass + le + re)] += ln * rn
        return results

    trees = all_tree_costs(oracle.all)
    roots = [oracle.costs[q] + max(oracle.worst(child) for child in children)
             for q, children in oracle.informative(oracle.all)]
    assert roots == [4, 5, 5, 5, 6]
    assert sum(trees.values()) == 64
    assert min(e for (w, e) in trees if w <= 4) == 25
    assert oracle.worst(oracle.all) == 4
    assert oracle.local(oracle.all)[:2] == (4, F(13, 4))
    assert oracle.value(oracle.all, 4) == F(25, 8)
    assert math.isinf(oracle.value(oracle.all, 3))
    return dict(catalogue=c, distinct_nonredundant_trees=sum(trees.values()),
                distinct_cost_pairs=len(trees), root_minimum_worst_costs=roots,
                minimum_worst_cost=4, local_lex_expected='13/4',
                global_lex_expected='25/8', expected_improvement='1/8')


def planning_identity(oracle):
    return digest(dict(schema='gabriel.budgeted-regions.planning.v1',
                       model_identity=oracle.identity,
                       prior=[str(v) for v in oracle.prior],
                       objective='minimum-expected-cost-under-pathwise-budget',
                       terminal='known-or-blocked'))


def replay_path(oracle, path, case, policy, budget, snapshot):
    assert type(path['case']) is int and path['case'] == case
    assert type(path['budget']) is int and path['budget'] == budget
    assert path['planning_identity'] == planning_identity(oracle)
    result = replay_certificate(oracle, path['certificate'], case, policy, budget, snapshot)
    assert type(path['cost']) is int and path['cost'] == result['cost']
    assert path['queries'] == result['queries']
    assert type(path['budget_compliant']) is bool
    assert path['budget_compliant'] == (result['cost'] <= budget)
    return result


def verify_study(study, budgets, snapshot, expected_catalogue=None):
    if expected_catalogue is not None:
        assert study['catalogue'] == expected_catalogue, 'inherited catalogue was changed'
    oracle = TupleOracle(study['catalogue'], study['prior'])
    assert study['prior'] == [str(value) for value in oracle.prior], 'prior is not normalized canonical rational'
    assert study['model_identity'] == oracle.identity
    assert study['planning_identity'] == planning_identity(oracle)
    worst = oracle.worst(oracle.all)
    local = oracle.local(oracle.all)
    assert worst == study['root_worst_cost'] == local[0]
    assert str(local[1]) == study['local_lex_expected_cost']
    assert [case['budget'] for case in study['budgets']] == budgets
    path_count, observation_count, all_summaries = 0, 0, []
    for scenario in study['budgets']:
        budget = scenario['budget']
        assert type(budget) is int and budget >= worst
        optimum = oracle.value(oracle.all, budget)
        assert scenario['optimal_expected_cost'] == str(optimum)
        assert set(scenario['policies']) == {'old_minimax', 'reverse', 'local_lex', 'global_lex'}
        summaries = {}
        for policy, saved in scenario['policies'].items():
            assert len(saved['paths']) == len(oracle.rows)
            costs, lengths, statuses, actions = [], [], Counter(), Counter()
            for case, path in enumerate(saved['paths']):
                result = replay_path(oracle, path, case, policy, budget, snapshot)
                costs.append(result['cost'])
                lengths.append(len(result['queries']))
                statuses[result['status']] += 1
                actions[result['action'] or 'none'] += 1
                path_count += 1
                observation_count += len(result['queries'])
            expected_mean = sum((p * cost for p, cost in zip(oracle.prior, costs)), F(0))
            expected_length = sum((p * length for p, length in zip(oracle.prior, lengths)), F(0))
            expected = dict(mean_cost=str(expected_mean), worst_cost=max(costs),
                            mean_queries=str(expected_length), budget_feasible=max(costs) <= budget,
                            budget_violations=sum(cost > budget for cost in costs),
                            status_counts=dict(statuses), action_counts=dict(actions), wrong_decisions=0)
            for key, value in expected.items():
                # JSON comparison rejects Boolean substitutions for integer counts.
                assert json.dumps(saved[key], sort_keys=True) == json.dumps(value, sort_keys=True), (policy, key)
            if policy == 'global_lex':
                assert expected_mean == optimum and max(costs) <= budget
            if policy == 'local_lex':
                assert expected_mean == local[1] and max(costs) == worst
            if policy == 'old_minimax':
                assert max(costs) == worst
            if expected['budget_feasible']:
                assert expected_mean >= optimum
            summaries[policy] = expected
        all_summaries.append(dict(budget=budget, optimal_expected_cost=str(optimum), policies=summaries))
    return dict(scope=study['scope'], model_identity=oracle.identity,
                planning_identity=planning_identity(oracle), records=len(oracle.rows),
                root_worst_cost=worst, local_lex_expected_cost=str(local[1]),
                budgets=all_summaries, paths=path_count, observations=observation_count,
                independent_states=oracle.count_states()), oracle


def tamper_checks(study, oracle, snapshot):
    """Reject altered policy, budget, identity, evidence and result fields."""
    scenario = study['budgets'][0]
    budget = scenario['budget']
    original = next(path for path in scenario['policies']['global_lex']['paths']
                    if path['certificate']['ledger'])
    case = original['case']
    mutations = [
        ('planning_identity', lambda p: p.__setitem__('planning_identity', 'wrong')),
        ('declared_budget', lambda p: p.__setitem__('budget', budget + 1)),
        ('budget_compliance', lambda p: p.__setitem__('budget_compliant', not p['budget_compliant'])),
        ('path_cost', lambda p: p.__setitem__('cost', p['cost'] + 1)),
        ('path_queries', lambda p: p.__setitem__('queries', [])),
        ('certificate_model', lambda p: p['certificate'].__setitem__('model_identity', 'wrong')),
        ('observation_contract', lambda p: p['certificate']['ledger'][0]['observation'].__setitem__('contract_digest', 'wrong')),
        ('forecast_evidence', lambda p: p['certificate']['ledger'][0]['observation'].__setitem__('kind', 'future-scenario')),
        ('predicted_evidence', lambda p: p['certificate']['ledger'][0]['observation'].__setitem__('status', 'predicted')),
        ('unavailable_evidence', lambda p: p['certificate']['ledger'][0]['observation'].__setitem__('received_at', 10**9)),
        ('snapshot_time', lambda p: p['certificate']['ledger'][0]['observation'].__setitem__('event_interval', [101, 101])),
        ('wrong_outcome', lambda p: p['certificate']['ledger'][0]['observation'].__setitem__('outcome', 'outside-catalogue')),
        ('wrong_source', lambda p: p['certificate']['ledger'][0]['observation'].__setitem__('source_id', 'wrong')),
        ('wrong_posterior', lambda p: p['certificate'].__setitem__('compatible_mask', '0x0')),
        ('wrong_action', lambda p: p['certificate'].__setitem__('action', 'absent-action')),
        ('wrong_count_type', lambda p: p['certificate'].__setitem__('compatible_count', True)),
    ]
    rejected = []
    for name, change in mutations:
        bad = deepcopy(original)
        change(bad)
        try:
            replay_path(oracle, bad, case, 'global_lex', budget, snapshot)
        except (AssertionError, ValueError, KeyError, IndexError, TypeError):
            rejected.append(name)
        else:
            raise AssertionError('tamper was accepted: ' + name)
    return rejected


def main():
    started = time.perf_counter()
    original_path = ROOT / 'results/portfolio_results.json'
    protocol_path = ROOT / 'results/portfolio_protocol.json'
    results_path = ROOT / 'results/budgeted_portfolio_results.json'
    prior_report_path = ROOT / 'results/portfolio_verification.json'
    original = json.loads(original_path.read_text())
    protocol = json.loads(protocol_path.read_text())
    saved = json.loads(results_path.read_text())
    prior_report = json.loads(prior_report_path.read_text())
    assert prior_report['passed'] is True
    assert saved['schema'] == 'gabriel.budgeted-regions.benchmark.v1'
    assert saved['original_results_sha256'] == file_digest(original_path) == prior_report['results_sha256']
    assert saved['protocol_sha256'] == file_digest(protocol_path) == prior_report['protocol_sha256']
    assert saved['protocol_sha256'] == original['protocol_sha256']
    snapshot = protocol['record_snapshot_completed_at']
    assert snapshot == 100 and protocol['forecast_queries'] is False
    assert len(saved['studies']) == len(original['studies']) == 5
    reports, oracles = [], []
    for study, source in zip(saved['studies'], original['studies']):
        assert study['scope'] == source['scope']
        worst = source['optimal_worst_cost']
        report, oracle = verify_study(study, [worst, worst + 1, worst + 2], snapshot, source['catalogue'])
        reports.append(report)
        oracles.append(oracle)
    witness = counterexample_check()
    counter = saved['counterexample']
    assert counter['catalogue']['rows'] == witness['catalogue']['rows']
    assert counter['catalogue']['costs'] == witness['catalogue']['costs']
    assert counter['prior'] == ['3/8', '1/8', '1/8', '1/8', '1/8', '1/8']
    witness_report, witness_oracle = verify_study(counter, [4], snapshot)
    assert all(witness_oracle.allowed[i] == frozenset({i}) for i in range(6))
    assert witness_report['root_worst_cost'] == 4
    assert witness_report['local_lex_expected_cost'] == '13/4'
    assert witness_report['budgets'][0]['optimal_expected_cost'] == '25/8'
    tampering = tamper_checks(counter, witness_oracle, snapshot)
    all_reports = reports + [witness_report]
    result = dict(schema='gabriel.budgeted-regions.verification.v1', passed=True,
                  scope='Independent tuple-row dynamic programs and exact transcript replay for a finite frozen model.',
                  results_sha256=file_digest(results_path), original_results_sha256=file_digest(original_path),
                  protocol_sha256=file_digest(protocol_path),
                  inherited_risk_verification_sha256=file_digest(prior_report_path),
                  studies=reports, counterexample=witness_report,
                  counterexample_tree_enumeration=witness,
                  replayed_paths=sum(r['paths'] for r in all_reports),
                  replayed_observations=sum(r['observations'] for r in all_reports),
                  independent_states={kind: sum(r['independent_states'][kind] for r in all_reports)
                                      for kind in ('worst', 'local_lex', 'residual_budget')},
                  tamper_rejections=len(tampering), tamper_cases=tampering,
                  inherited_risk_optimization_calls=0,
                  fields_not_recomputed=['Original and benchmark wall-clock execution durations.'],
                  limits=['Exact guarantees are conditional on the finite immutable catalogue and strictly positive prior.',
                          'Weighted means use the declared synthetic prior, not estimated operating frequencies.',
                          'Earlier CVaR witnesses are inherited by hash from the passed independent portfolio verification.',
                          'The queries reveal current records; no future scenario is treated as a completed observation.'],
                  python=platform.python_version(), elapsed_seconds=round(time.perf_counter() - started, 3),
                  verifier_sha256=file_digest(Path(__file__)))
    target = ROOT / 'results/budgeted_region_verification.json'
    target.write_text(json.dumps(result, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(dict(passed=True, paths=result['replayed_paths'],
                          observations=result['replayed_observations'],
                          states=result['independent_states'], tamper_rejections=len(tampering),
                          output=str(target))))


if __name__ == '__main__':
    main()
