"""Independent replay of the saved synthetic current-record study.

Reconstructs each declared loss vector and cash flag without importing the
adapter, verifies exact CVaR primal/dual witnesses without optimization, and
recomputes every acquisition path and summary. All claims are conditional on
the finite, immutable current-record catalogue and specified stress support.
"""
from collections import Counter
from copy import deepcopy
from dataclasses import asdict, replace
from fractions import Fraction as F
from functools import lru_cache
from itertools import product, combinations
import hashlib
import json
import math
from pathlib import Path
import platform
import time

from decision_regions import RegionCatalogue, RegionPlanner, RegionSession, Observation, verify_certificate
from portfolio_risk import verify_robust_cvar_certificate

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_PROTOCOL = 'b1a36f8f5d6d09b09a7807e9eb4435d077aa415681d66d4265a05f1df7fbf247'


def exact(value):
    if type(value) is int:
        return F(value)
    if type(value) is str:
        rational = F(value)
        if str(rational) == value:
            return rational
    raise ValueError('expected a canonical exact rational')


def exact_certificate(value):
    if isinstance(value, dict):
        return {key: exact_certificate(item) for key, item in value.items()}
    if isinstance(value, list):
        return tuple(exact_certificate(item) for item in value)
    if type(value) is str:
        return exact(value)
    if type(value) is int:
        return value
    raise ValueError('unexpected risk-certificate scalar')


def plain(value):
    if type(value) is F:
        return str(value)
    if isinstance(value, dict):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(item) for item in value]
    return value


def independent_loss(protocol, fact, action, horizon):
    # Re-derive using separate component accounting, without loss_vector().
    terms = protocol['action_terms'][action]
    factor = exact(terms['position_fraction'])
    equity = factor * fact['equity']
    duration = factor * fact['duration']
    credit = factor * fact['credit']
    insured_equity = min(equity, F(fact['existing_hedge']) + terms['additional_hedge'])
    fees = F(terms['fee_base']) + terms['fee_liquidity'] * fact['liquidity_multiplier']
    total_exposure = equity + duration + credit
    losses = []
    for stress in protocol['scenarios']:
        equity_shock, duration_shock, credit_shock, liquidity_shock = [exact(v) for v in stress[horizon]]
        components = [equity * equity_shock, duration * duration_shock, credit * credit_shock,
                      fact['liquidity_multiplier'] * liquidity_shock * total_exposure, fees]
        if equity_shock > 0:
            components.append(-insured_equity * equity_shock)
        losses.append(sum(components, F(0)))
    return tuple(losses)


class Oracle:
    """Independent tuple-of-row posterior and set-valued action calculation."""
    def __init__(self, c):
        self.c = c
        self.all = tuple(range(len(c.rows)))
        self.allowed, self.labels = [], []
        for i, scores in enumerate(c.risks):
            feasible = {a for a in range(len(c.action_names))
                        if c.feasible[i][a] and (c.risk_limit is None or scores[a] <= c.risk_limit)}
            best = min((scores[a] for a in feasible), default=None)
            self.allowed.append(frozenset(a for a in feasible if scores[a] - best <= c.epsilon))
            self.labels.append(min(feasible, key=lambda a: (scores[a], a)) if feasible else -1)
        self.value = lru_cache(None)(lambda rows: self._value(rows, False))
        self.strict_value = lru_cache(None)(lambda rows: self._value(rows, True))

    def assessment(self, rows):
        common = [a for a in range(len(self.c.action_names))
                  if rows and all(a in self.allowed[i] for i in rows)]
        possible = [a for a in range(len(self.c.action_names)) if any(a in self.allowed[i] for i in rows)]
        status = ('conflict' if not rows else 'known' if common else 'blocked' if not possible else 'unresolved')
        return dict(status=status, action=self.c.action_names[common[0]] if common else None,
                    acceptable_actions=[self.c.action_names[a] for a in common],
                    possible_actions=[self.c.action_names[a] for a in possible],
                    compatible_count=len(rows), compatible_weight=sum(self.c.weights[i] for i in rows))

    def strict_terminal(self, rows):
        return bool(rows) and len({self.labels[i] for i in rows}) == 1

    def terminal(self, rows, strict=False):
        return self.strict_terminal(rows) if strict else self.assessment(rows)['status'] in ('known', 'blocked')

    def partition(self, rows, query):
        values = sorted({self.c.rows[i][query] for i in rows})
        return tuple(tuple(i for i in rows if self.c.rows[i][query] == value) for value in values)

    def informative(self, rows):
        return [(q, self.partition(rows, q)) for q in range(len(self.c.costs))
                if len({self.c.rows[i][q] for i in rows}) > 1]

    def _value(self, rows, strict):
        if not rows:
            return math.inf
        if self.terminal(rows, strict):
            return 0
        continuation = self.strict_value if strict else self.value
        candidates = [self.c.costs[q] + max(continuation(child) for child in children)
                      for q, children in self.informative(rows)]
        return min(candidates, default=math.inf)

    def choice(self, rows, policy):
        choices = self.informative(rows)
        if not choices or self.terminal(rows, policy.startswith('strict_')):
            return None
        if policy == 'fixed':
            return choices[0][0]
        if policy == 'reverse':
            return choices[-1][0]
        if policy in ('minimax', 'strict_minimax'):
            continuation = self.strict_value if policy.startswith('strict_') else self.value
            if math.isinf(continuation(rows)):
                return None
            return min(choices, key=lambda qc: (
                self.c.costs[qc[0]] + max(continuation(child) for child in qc[1]), qc[0]))[0]
        mass = lambda subset: sum(self.c.weights[i] for i in subset)
        total = mass(rows)
        if policy == 'strict_ec2':
            def pairs(subset):
                groups = Counter()
                for i in subset:
                    groups[self.labels[i]] += self.c.weights[i]
                values = tuple(groups.values())
                return sum(values[i] * values[j] for i in range(len(values)) for j in range(i + 1, len(values)))
            scores = [(q, F(total * pairs(rows) - sum(mass(child) * pairs(child) for child in children),
                            total * self.c.costs[q])) for q, children in choices]
            return max(scores, key=lambda item: (item[1], -item[0]))[0]
        assert policy == 'hypothesis_entropy'
        scores = []
        for q, children in choices:
            # Same declared floating entropy tie tolerance; all certificates
            # and minimax quantities remain exact.
            probabilities = [mass(child) / total for child in children]
            scores.append((q, -sum(v * math.log2(v) for v in probabilities) / self.c.costs[q]))
        best = max(score for _, score in scores)
        return min(q for q, score in scores if score >= best - 1e-12)


def full_book_oracle(rows, meanings, costs):
    valid = []
    for size in range(len(costs) + 1):
        for queries in combinations(range(len(costs)), size):
            # A fixed set succeeds iff it separates every pair of distinct
            # semantic books; harmless metadata differences need not separate.
            if all(meanings[i] == meanings[j] or any(rows[i][q] != rows[j][q] for q in queries)
                   for i in range(len(rows)) for j in range(i + 1, len(rows))):
                valid.append((sum(costs[q] for q in queries), size, queries))
    assert valid
    return min(valid), len(valid)


def ensure_rejected(operation):
    try:
        operation()
    except ValueError:
        return
    raise AssertionError('expected invalid observation rejection')


def guards_and_boundaries():
    c = RegionCatalogue('boundary-toy', ('current_record',), (1,), (('0',), ('1',)),
                        ('a', 'b'), ((0, 2), (2, 0)), epsilon=0, risk_limit=1)
    p = RegionPlanner(c)
    good = Observation(c.identity, 0, '0', 'source', (100, 100), 101)
    for changes, cutoff in [(dict(contract_digest='wrong-contract'), 101),
                            (dict(event_interval=(102, 102), received_at=102), 101),
                            (dict(kind='future-scenario'), 101), (dict(status='predicted'), 101)]:
        ensure_rejected(lambda kw=changes, now=cutoff: RegionSession(p).ingest(replace(good, **kw), now))
    session = RegionSession(p)
    assert session.ingest(good, 101)
    prior = session.state
    assert not session.ingest(good, 102) and len(session.ledger) == 1 and session.state == prior
    ensure_rejected(lambda: session.ingest(replace(good, outcome='1'), 103))
    unknown = RegionSession(p)
    unknown.ingest(replace(good, outcome='forged-outside-catalogue'), 101)
    assert unknown.result()['status'] == 'conflict' and verify_certificate(c, unknown.certificate())
    forged = deepcopy(session.certificate())
    forged['ledger'][0]['observation']['outcome'] = '1'
    assert not verify_certificate(c, forged)
    forged['ledger'][0]['observation']['outcome'] = '0'
    forged['ledger'][0]['observation']['received_at'] = 104
    assert not verify_certificate(c, forged)

    indistinguishable = replace(c, rows=(('same',), ('same',)))
    ip = RegionPlanner(indistinguishable)
    isession = RegionSession(ip)
    isession.ingest(Observation(indistinguishable.identity, 0, 'same', 'same', (100, 100), 101), 101)
    assert isession.result()['status'] == 'unresolved' and math.isinf(ip.value(ip.all))
    assert verify_certificate(indistinguishable, isession.certificate())

    breached = replace(c, risks=((11, 12), (11, 12)), epsilon=2, risk_limit=10)
    # The action regrets relative to the unconstrained minimum are 0 and 1,
    # but no action meets the absolute limit. Relative agreement cannot help.
    assert RegionPlanner(breached).assess(3)['status'] == 'blocked'

    incomplete = RegionCatalogue('incomplete-catalogue-toy', ('visible_current_record',), (1,),
                                 (('observed',),), ('a', 'b'), ((0, 10),), epsilon=0, risk_limit=5)
    miss = RegionSession(RegionPlanner(incomplete))
    miss.ingest(Observation(incomplete.identity, 0, 'observed', 'visible', (100, 100), 101), 101)
    conditional = miss.certificate()
    assert verify_certificate(incomplete, conditional) and conditional['action'] == 'a'
    unmodeled_scores = (F(20), F(0))
    assert unmodeled_scores[incomplete.action_names.index(conditional['action'])] > incomplete.risk_limit
    return dict(observation_guard_rejections=5, duplicate_idempotence_checks=1,
                unknown_outcome_conflicts=1, forged_certificate_rejections=2,
                boundary_counterexamples=dict(
                    observational_equivalence={'status': 'unresolved', 'optimal_cost': 'infinity'},
                    absolute_limit={'unconstrained_regrets': ['0', '1'], 'epsilon': '2',
                                    'risk_limit': '10', 'status': 'blocked'},
                    catalogue_noncoverage={'model_scores': ['0', '10'],
                                          'unmodeled_scores_with_same_visible_record': ['20', '0'],
                                          'certificate_valid_for_model': True,
                                          'selected_action': 'a', 'correct_for_unmodeled_reality': False}),
                limitation='Conditional certificates do not authenticate evidence or detect all unmodeled realities.')


def main():
    start = time.perf_counter()
    raw_protocol = (ROOT / 'results/portfolio_protocol.json').read_bytes()
    assert hashlib.sha256(raw_protocol).hexdigest() == EXPECTED_PROTOCOL
    protocol = json.loads(raw_protocol)
    raw_results = (ROOT / 'results/portfolio_results.json').read_bytes()
    saved = json.loads(raw_results)
    assert saved['protocol_sha256'] == EXPECTED_PROTOCOL
    assert protocol['forecast_queries'] is False
    assert tuple(protocol['query_names']) == ('metadata_tag', 'cash', 'equity', 'credit',
                                             'duration', 'existing_hedge', 'liquidity_multiplier', 'position_registry')
    assert set(protocol['horizons']).isdisjoint(protocol['query_names'])
    assert {s['name'] for s in protocol['scenarios']}.isdisjoint(protocol['query_names'])
    fields = ('equity', 'duration', 'credit', 'liquidity_multiplier', 'existing_hedge', 'cash', 'metadata_tag')
    assert tuple(protocol['fact_values']) == fields
    records, observations, meanings = [], [], []
    for values in product(*(protocol['fact_values'][field] for field in fields)):
        fact = dict(zip(fields, values))
        row = tuple(str(fact[name]) if name != 'position_registry' else
                    ','.join(str(fact[name]) for name in ('equity', 'duration', 'credit'))
                    for name in protocol['query_names'])
        meaning = tuple(fact[name] for name in fields[:-1])
        records.append(dict(facts=fact, row=list(row), semantic=list(meaning)))
        observations.append(row)
        meanings.append(meaning)
    assert records == saved['portfolio_records']
    alpha = exact(protocol['alpha'])
    models = tuple(tuple(exact(v) for v in model['probabilities']) for model in protocol['probability_models'])
    risks, flags, all_losses = [], [], set()
    risk_count, cash_count, hull_strict_gaps = 0, 0, 0
    for i, record in enumerate(records):
        fact, scores, feasible = record['facts'], [], []
        for a, action in enumerate(protocol['action_names']):
            terms = protocol['action_terms'][action]
            cash_required = terms['cash_base'] + terms['cash_liquidity'] * fact['liquidity_multiplier']
            feasible.append(fact['cash'] >= cash_required)
            cash_count += 1
            horizon_risks = []
            for h, horizon in enumerate(protocol['horizons']):
                losses = independent_loss(protocol, fact, action, horizon)
                all_losses.add(losses)
                cert = exact_certificate(saved['risk_certificates'][i][a][h])
                assert verify_robust_cvar_certificate(cert, losses=losses, models=models, alpha=alpha)
                assert cert['max_listed_model_value'] == cert['listed_value']
                assert type(cert['candidate_count']) is int and cert['candidate_count'] > 0
                horizon_risks.append(cert['value'])
                risk_count += 1
                hull_strict_gaps += cert['value'] > cert['listed_value']
            scores.append(max(horizon_risks))
        risks.append(tuple(scores))
        flags.append(tuple(feasible))
    assert plain(risks) == saved['risks']
    assert plain(flags) == saved['feasible']
    assert len(all_losses) == saved['unique_loss_vectors']

    settings = [protocol['primary']] + protocol['controls']
    assert len(saved['studies']) == len(settings) + 1
    summaries, checked_paths, checked_events, planned_states = [], 0, 0, 0
    for index, study in enumerate(saved['studies']):
        if index < len(settings):
            c = RegionCatalogue('portfolio-static-snapshot;' + EXPECTED_PROTOCOL,
                                tuple(protocol['query_names']), tuple(protocol['query_costs']),
                                tuple(observations), tuple(protocol['action_names']), tuple(risks),
                                feasible=tuple(flags), **settings[index])
            semantics = meanings
            scope = 'portfolio-primary' if index == 0 else 'portfolio-control-' + str(index)
        else:
            rows, scores, feasible, semantics = [], [], [], []
            for wear, vibration, crew, tag in product((0, 1), repeat=4):
                rows.append(tuple(str(v) for v in (tag, wear, vibration, crew)))
                scores.append((F(1 + 7 * wear + 5 * vibration), F(4 + 3 * vibration), F(7 + wear)))
                feasible.append((True, crew == 1, True))
                semantics.append((wear, vibration, crew))
            c = RegionCatalogue('industrial-inspection-static-v1',
                                ('metadata_tag', 'wear_record', 'vibration_record', 'crew_record'), (1, 2, 2, 1),
                                tuple(rows), ('continue', 'repair', 'controlled_stop'), tuple(scores),
                                epsilon='1', risk_limit='12', feasible=tuple(feasible))
            scope = 'industrial-inspection'
        assert study['scope'] == scope and study['identity'] == c.identity
        assert study['catalogue'] == plain(asdict(c))
        oracle = Oracle(c)
        assert study['initial'] == oracle.assessment(oracle.all)
        optimal, strict_optimal = oracle.value(oracle.all), oracle.strict_value(oracle.all)
        assert study['optimal_worst_cost'] == optimal
        assert study['strict_optimal_worst_cost'] == strict_optimal
        (full_cost, _, full_queries), valid_static_sets = full_book_oracle(c.rows, semantics, c.costs)
        assert (study['full_book_cost'], tuple(study['full_book_queries'])) == (full_cost, full_queries)
        assert set(study['policies']) == set(protocol['policies'])
        policy_summaries = {}
        for policy, result in study['policies'].items():
            assert len(result['paths']) == len(c.rows)
            costs, lengths, statuses, actions, nuisance = [], [], Counter(), Counter(), 0
            for i, path in enumerate(result['paths']):
                assert type(path['case']) is int and path['case'] == i
                cert = path['certificate']
                assert verify_certificate(c, cert)
                posterior = oracle.all
                cost, queries = 0, []
                for step, entry in enumerate(cert['ledger']):
                    evidence = entry['observation']
                    query = evidence['query']
                    assert type(query) is int and query not in queries
                    if policy == 'full_book':
                        assert query == full_queries[step]
                    else:
                        assert not oracle.terminal(posterior, policy.startswith('strict_'))
                        assert query == oracle.choice(posterior, policy)
                    assert evidence['outcome'] == c.rows[i][query]
                    assert evidence['source_id'] == 'current-record:' + str(query)
                    assert evidence['status'] == 'observed' and evidence['kind'] == 'passive'
                    snapshot = protocol['record_snapshot_completed_at']
                    assert snapshot == 100 and evidence['event_interval'] == [snapshot, snapshot]
                    cost += c.costs[query]
                    assert evidence['received_at'] == snapshot + cost == entry['cutoff']
                    assert entry['before'] == hex(sum(1 << row for row in posterior))
                    posterior = tuple(row for row in posterior if c.rows[row][query] == evidence['outcome'])
                    assert entry['after'] == hex(sum(1 << row for row in posterior))
                    queries.append(query)
                    checked_events += 1
                assert i in posterior and path['queries'] == queries
                assert type(path['cost']) is int and path['cost'] == cost
                assert cert['cutoff'] == (snapshot + cost if queries else None)
                if policy == 'full_book':
                    assert tuple(queries) == full_queries
                    assert len({semantics[row] for row in posterior}) == 1
                else:
                    assert oracle.terminal(posterior, policy.startswith('strict_'))
                assessment = oracle.assessment(posterior)
                for key, value in assessment.items():
                    assert cert[key] == value
                assert assessment['status'] in ('known', 'blocked')
                if assessment['status'] == 'known':
                    selected = c.action_names.index(assessment['action'])
                    assert all(selected in oracle.allowed[row] for row in posterior)
                else:
                    assert all(not oracle.allowed[row] for row in posterior)
                statuses[assessment['status']] += 1
                actions[assessment['action'] or 'none'] += 1
                costs.append(cost)
                lengths.append(len(queries))
                nuisance += 0 in queries
                checked_paths += 1
            expected = dict(case_count=len(c.rows), mean_cost=str(F(sum(costs), len(costs))),
                            worst_cost=max(costs), mean_queries=str(F(sum(lengths), len(lengths))),
                            status_counts=dict(statuses), action_counts=dict(actions),
                            nuisance_queries=nuisance, wrong_decisions=0)
            for key, value in expected.items():
                assert result[key] == value
            policy_summaries[policy] = expected
        assert policy_summaries['minimax']['worst_cost'] == optimal
        assert policy_summaries['strict_minimax']['worst_cost'] == strict_optimal
        assert policy_summaries['full_book']['worst_cost'] == full_cost
        oracle_states = oracle.value.cache_info().currsize + oracle.strict_value.cache_info().currsize
        assert study['visited_planning_states'] == oracle_states
        planned_states += oracle_states
        summaries.append(dict(scope=scope, identity=c.identity, records=len(c.rows),
                              exact_worst_cost=optimal, strict_exact_worst_cost=strict_optimal,
                              minimum_static_full_book_cost=full_cost, full_book_queries=list(full_queries),
                              valid_static_full_book_sets=valid_static_sets,
                              independent_bellman_states=oracle_states, policies=policy_summaries))

    boundaries = guards_and_boundaries()
    report = dict(schema='gabriel.portfolio-verification.v1', passed=True,
                  scope='Independent finite-model replay; synthetic cases, no calibrated financial claim',
                  protocol_sha256=EXPECTED_PROTOCOL,
                  results_sha256=hashlib.sha256(raw_results).hexdigest(),
                  reconstructed_books=len(records), cash_feasibility_checks=cash_count,
                  reconstructed_loss_vectors=risk_count, distinct_loss_vectors=len(all_losses),
                  robust_risk_witnesses_verified=risk_count, robust_optimizer_calls=0,
                  risk_entries_with_strict_hull_vs_listed_gap=hull_strict_gaps,
                  replayed_policy_paths=checked_paths, replayed_passive_observations=checked_events,
                  independent_bellman_states=planned_states, studies=summaries,
                  guard_and_boundary_checks=boundaries,
                  descriptive_fields_not_recomputed=['risk optimizer candidate_count', 'original execution seconds'],
                  limits=['No live market data or operational policy execution.',
                          'Query cost units are synthetic; integer clock increments are replay conventions.',
                          'The robust risk bound covers only the declared scenario support and probability hull.',
                          'Different action on an omitted reality is possible despite a valid conditional certificate.'],
                  python=platform.python_version(), elapsed_seconds=round(time.perf_counter() - start, 3),
                  verifier_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    target = ROOT / 'results/portfolio_verification.json'
    target.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(passed=True, risk_witnesses=risk_count, paths=checked_paths,
                          observations=checked_events, bellman_states=planned_states,
                          output=str(target))))


if __name__ == '__main__':
    main()
