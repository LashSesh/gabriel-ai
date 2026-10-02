"""Compare acquisition objectives on the existing frozen synthetic studies.

No risk scores, priors in the original studies, or original output files are
modified. The new objective uses their explicit uniform catalogue distribution.
"""
from collections import Counter
from dataclasses import asdict
from fractions import Fraction as F
import hashlib
import json
from pathlib import Path
import time

from budgeted_regions import BudgetedPlanner
from decision_regions import RegionCatalogue, RegionSession, Observation, verify_certificate

ROOT = Path(__file__).resolve().parents[1]
POLICIES = ('old_minimax', 'reverse', 'local_lex', 'global_lex')


def plain(value):
    if type(value) is F:
        return str(value)
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    return value


def counterexample_catalogue():
    # Six distinguishable labels; all tests are available from the initial state.
    # q0=ABCD, q1=AB, q2=AC, q3=A, q4=E, with costs 1,1,1,1,3.
    sets = ({0, 1, 2, 3}, {0, 1}, {0, 2}, {0}, {4})
    return RegionCatalogue('budget-slack-counterexample-v1', ('q0', 'q1', 'q2', 'q3', 'q4'),
                           (1, 1, 1, 1, 3), tuple(tuple(str(int(i in subset)) for subset in sets) for i in range(6)),
                           tuple('ABCDEF'), tuple(tuple(0 if a == i else 1 for a in range(6)) for i in range(6)),
                           weights=(3, 1, 1, 1, 1, 1))


def execute(planner, case, policy, budget):
    session = RegionSession(planner.base)
    cost, queries = 0, []
    while not planner.base.terminal(session.state):
        if policy in ('old_minimax', 'reverse'):
            query = planner.base.choice(session.state, 'minimax' if policy == 'old_minimax' else 'reverse')
        else:
            query = planner.choice(session.state, budget - cost, policy)
        if query is None:
            raise AssertionError('benchmark policy failed to terminate on observable catalogue')
        assert query not in queries
        cost += planner.c.costs[query]
        session.ingest(Observation(planner.c.identity, query, planner.c.rows[case][query],
                                   'current-record:' + str(query), (100, 100), 100 + cost), 100 + cost)
        queries.append(query)
    cert = session.certificate()
    assert verify_certificate(planner.c, cert)
    assert session.state & (1 << case)
    if cert['status'] == 'known':
        action = planner.c.action_names.index(cert['action'])
        assert planner.c.acceptable_masks[case] & (1 << action)
    else:
        assert cert['status'] == 'blocked' and planner.c.acceptable_masks[case] == 0
    return dict(case=case, cost=cost, queries=queries, certificate=cert, budget=budget,
                budget_compliant=cost <= budget, planning_identity=planner.identity)


def study(catalogue, scope, slack=(0, 1, 2)):
    planner = BudgetedPlanner(catalogue)
    root_worst = planner.worst(planner.all)
    local = planner.local_lex_value(planner.all)
    output = dict(scope=scope, catalogue=plain(asdict(catalogue)), model_identity=catalogue.identity,
                  planning_identity=planner.identity, prior=[str(v) for v in planner.prior],
                  root_worst_cost=root_worst, local_lex_expected_cost=str(local), budgets=[])
    for extra in slack:
        budget = root_worst + extra
        optimum = planner.value(planner.all, budget)
        record = dict(budget=budget, optimal_expected_cost=str(optimum), policies={})
        for policy in POLICIES:
            paths = [execute(planner, case, policy, budget) for case in range(len(catalogue.rows))]
            mean = sum((planner.prior[i] * path['cost'] for i, path in enumerate(paths)), F(0))
            violations = sum(not path['budget_compliant'] for path in paths)
            result = dict(paths=paths, mean_cost=str(mean), worst_cost=max(p['cost'] for p in paths),
                          mean_queries=str(sum((planner.prior[i] * len(path['queries'])
                                                for i, path in enumerate(paths)), F(0))),
                          budget_feasible=not violations, budget_violations=violations,
                          status_counts=dict(Counter(p['certificate']['status'] for p in paths)),
                          action_counts=dict(Counter(p['certificate']['action'] or 'none' for p in paths)),
                          wrong_decisions=0)
            if policy == 'global_lex':
                assert mean == optimum and violations == 0
            elif policy == 'local_lex':
                assert mean == local and violations == 0
            record['policies'][policy] = result
        output['budgets'].append(record)
    output['combined_planning_states'] = planner.state_count
    print(scope, 'worst', root_worst, 'local', local,
          'budget frontier', [(b['budget'], b['optimal_expected_cost']) for b in output['budgets']], flush=True)
    return output


def main():
    start = time.perf_counter()
    raw = (ROOT / 'results/portfolio_results.json').read_bytes()
    source = json.loads(raw)
    verified = json.loads((ROOT / 'results/portfolio_verification.json').read_text())
    source_hash = hashlib.sha256(raw).hexdigest()
    assert verified['passed'] is True and verified['results_sha256'] == source_hash
    output = dict(schema='gabriel.budgeted-regions.benchmark.v1',
                  scope='Exact finite static-model planning; uniform synthetic priors in the five existing studies',
                  original_results_sha256=source_hash, protocol_sha256=source['protocol_sha256'], studies=[])
    for saved in source['studies']:
        catalogue = RegionCatalogue(**saved['catalogue'])
        assert catalogue.identity == saved['identity']
        output['studies'].append(study(catalogue, saved['scope']))
    output['counterexample'] = study(counterexample_catalogue(), 'constructed-nonuniform-slack-counterexample', slack=(0,))
    output['seconds'] = time.perf_counter() - start
    destination = ROOT / 'results/budgeted_portfolio_results.json'
    destination.write_text(json.dumps(output, separators=(',', ':'), allow_nan=False) + '\n')
    print('WROTE', destination, 'seconds', round(output['seconds'], 3), flush=True)


if __name__ == '__main__':
    main()
