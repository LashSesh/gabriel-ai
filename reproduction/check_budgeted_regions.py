"""Exhaustive small-table checks for hard-budget expected-cost planning."""
from fractions import Fraction as F
from functools import lru_cache
from itertools import product
from pathlib import Path
import hashlib
import json
import math
import time

from budgeted_regions import BudgetedPlanner
from decision_regions import RegionCatalogue
from benchmark_budgeted_regions import counterexample_catalogue


def independent(c, weights):
    allowed = []
    for i, row in enumerate(c.risks):
        feasible = [a for a in range(len(c.action_names))
                    if c.feasible[i][a] and (c.risk_limit is None or row[a] <= c.risk_limit)]
        minimum = min((row[a] for a in feasible), default=None)
        allowed.append(set(a for a in feasible if row[a] - minimum <= c.epsilon))
    def terminal(rows):
        return bool(rows) and (bool(set.intersection(*(allowed[i] for i in rows))) or
                               not any(allowed[i] for i in rows))
    def choices(rows):
        values = []
        for q in range(len(c.costs)):
            outcomes = sorted({c.rows[i][q] for i in rows})
            if len(outcomes) > 1:
                values.append((q, tuple(tuple(i for i in rows if c.rows[i][q] == y) for y in outcomes)))
        return values
    @lru_cache(None)
    def worst(rows):
        if not rows:
            return math.inf
        if terminal(rows):
            return 0
        return min((c.costs[q] + max(worst(child) for child in children) for q, children in choices(rows)),
                   default=math.inf)
    @lru_cache(None)
    def expected(rows, budget):
        if not rows:
            return math.inf
        if terminal(rows):
            return F(0)
        total = sum(weights[i] for i in rows)
        values = []
        for q, children in choices(rows):
            if c.costs[q] > budget:
                continue
            child_values = [expected(child, budget - c.costs[q]) for child in children]
            if all(value != math.inf for value in child_values):
                values.append(F(c.costs[q]) + sum((sum(weights[i] for i in child) / total * value
                                                  for child, value in zip(children, child_values)), F(0)))
        return min(values, default=math.inf)
    @lru_cache(None)
    def local(rows):
        if worst(rows) == math.inf:
            return math.inf
        if terminal(rows):
            return F(0)
        total = sum(weights[i] for i in rows)
        return min((F(c.costs[q]) + sum((sum(weights[i] for i in child) / total * local(child)
                                         for child in children), F(0))
                    for q, children in choices(rows)
                    if c.costs[q] + max(worst(child) for child in children) == worst(rows)), default=math.inf)
    return terminal, choices, worst, expected, local


def reject(operation, exception=ValueError):
    try:
        operation()
    except exception:
        return
    raise AssertionError('invalid parameter or exhausted state guard accepted')


def main():
    start = time.perf_counter()
    counters = dict(exhaustive_models=0, state_budget_pairs=0, local_lex_states=0,
                    realized_paths=0, invalid_input_rejections=0, guard_rejections=0)
    for masks in product(range(4), repeat=3):
        feasible = tuple(tuple(bool(mask >> a & 1) for a in range(2)) for mask in masks)
        for encoded_rows in product(('0', '1'), repeat=6):
            rows = tuple(encoded_rows[i:i + 2] for i in (0, 2, 4))
            c = RegionCatalogue('budget-exhaustive-three-row', ('q0', 'q1'), (1, 2),
                                rows, ('a', 'b'), ((0, 0),) * 3, feasible=feasible)
            for weights in ((F(1), F(1), F(1)), (F(1, 3), F(2, 3), F(2))):
                p = BudgetedPlanner(c, prior=weights)
                terminal, choices, worst, expected, local = independent(c, weights)
                for state in range(8):
                    subset = tuple(i for i in range(3) if state >> i & 1)
                    assert p.worst(state) == worst(subset)
                    assert p.local_lex_value(state) == local(subset)
                    counters['local_lex_states'] += 1
                    previous = math.inf
                    for budget in range(4):
                        value = p.value(state, budget)
                        assert value == expected(subset, budget)
                        assert value <= previous  # larger cap cannot worsen the optimum
                        assert (value < math.inf) == (bool(subset) and worst(subset) <= budget)
                        previous = value
                        query = p.choice(state, budget)
                        if query is not None:
                            branches = next(children for q, children in choices(subset) if q == query)
                            mass = sum(weights[i] for i in subset)
                            achieved = F(c.costs[query]) + sum((sum(weights[i] for i in child) / mass *
                                                               expected(child, budget - c.costs[query])
                                                               for child in branches), F(0))
                            assert achieved == value
                        else:
                            assert terminal(subset) or value == math.inf
                        counters['state_budget_pairs'] += 1
                if counters['exhaustive_models'] % 64 == 0 and p.worst(p.all) < math.inf:
                    cap = p.worst(p.all)
                    realized = []
                    for i in range(3):
                        state, spent = p.all, 0
                        while not p.base.terminal(state):
                            q = p.choice(state, cap - spent)
                            assert q is not None
                            spent += c.costs[q]
                            state = p.base.observe(state, q, c.rows[i][q])
                        assert spent <= cap
                        realized.append(spent)
                        counters['realized_paths'] += 1
                    assert sum((p.prior[i] * realized[i] for i in range(3)), F(0)) == p.value(p.all, cap)
                counters['exhaustive_models'] += 1

    witness = counterexample_catalogue()
    p = BudgetedPlanner(witness)
    assert p.worst(p.all) == 4
    assert p.local_lex_value(p.all) == F(13, 4)
    assert p.value(p.all, 4) == F(25, 8)
    assert p.value(p.all, 3) == math.inf
    assert p.choice(p.all, 4) == 0
    soft = sum(1 << i for i in range(4))
    assert p.worst(soft) == 2
    assert p.local_lex_value(soft) == 2
    assert p.value(soft, 3) == F(11, 6)
    assert p.choice(soft, 3, 'local_lex') == 1 and p.choice(soft, 3, 'global_lex') == 3
    scaled = BudgetedPlanner(witness, prior=(6, 2, 2, 2, 2, 2))
    assert scaled.identity == p.identity
    changed = BudgetedPlanner(witness, prior=(1, 1, 1, 1, 1, 1))
    assert changed.identity != p.identity
    for prior in [(1, 1), (1, 1, 1, 1, 1, 0), (1, 1, 1, 1, 1, -1),
                  (1, 1, 1, 1, 1, True), (1, 1, 1, 1, 1, 0.5),
                  (1, 1, 1, 1, 1, '2/4')]:
        reject(lambda v=prior: BudgetedPlanner(witness, prior=v))
        counters['invalid_input_rejections'] += 1
    for budget in (-1, True, 0.5, None, '4'):
        reject(lambda v=budget: p.value(p.all, v))
        counters['invalid_input_rejections'] += 1
    for state in (-1, True, 64, 0.5):
        reject(lambda v=state: p.value(v, 4))
        counters['invalid_input_rejections'] += 1
    reject(lambda: BudgetedPlanner(witness, max_states=True))
    counters['invalid_input_rejections'] += 1
    limited = BudgetedPlanner(witness, max_states=1)
    reject(lambda: limited.value(limited.all, 4), RuntimeError)
    reject(lambda: limited.value(1, 0), RuntimeError)  # sticky failure; no cached result can hide exhaustion
    counters['guard_rejections'] += 2
    zero_query = RegionCatalogue('no-query-common-action', (), (), ((), ()), ('a', 'b'), ((0, 1), (1, 0)), epsilon=1)
    zp = BudgetedPlanner(zero_query)
    assert zp.value(zp.all, 0) == 0 and zp.choice(zp.all, 0) is None

    directory = Path(__file__).resolve().parent
    result = dict(schema='gabriel.budgeted-regions.checks.v1', passed=True,
                  scope='Synthetic exhaustive finite-table checks, not a financial performance estimate',
                  counts=counters,
                  counterexample=dict(records=6, queries=5, prior_weights=[3, 1, 1, 1, 1, 1],
                                      worst_cost=4, local_lex_expected='13/4', globally_budgeted_expected='25/8',
                                      local_soft_worst=2, available_soft_budget=3,
                                      local_soft_expected='2', budgeted_soft_expected='11/6'),
                  invariants=['Exact agreement with independent tuple/set Bellman oracle',
                              'Feasible iff positive-support posterior is nonempty and minimax worst cost fits budget',
                              'Expected optimum is nonincreasing in allowed budget',
                              'Chosen query realizes Bellman value with canonical index tie break',
                              'Scaled prior weights preserve normalized identity',
                              'Different normalized prior changes planning identity',
                              'Explicit combined state guard raises and remains failed'],
                  source_sha256={name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
                                 for name in ('budgeted_regions.py', 'check_budgeted_regions.py', 'benchmark_budgeted_regions.py')},
                  elapsed_seconds=round(time.perf_counter() - start, 3))
    target = directory.parent / 'results/budgeted_region_checks.json'
    target.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(dict(passed=True, **counters, output=str(target))))


if __name__ == '__main__':
    main()
