"""Exact expected acquisition under a hard pathwise budget on a frozen model.

The posterior row set alone is insufficient for this constrained objective:
remaining budget is part of the planning state. At budget equal to the minimum
worst cost, this solves the GLOBAL lexicographic (worst, expected) objective.
The comparison local_lex policy minimizes worst continuation at every posterior;
it can discard useful slack in a branch that does not control the root maximum.

This is finite constrained dynamic programming, not a new general principle.
Priors describe catalogue weights, not an empirically calibrated population.
"""
from fractions import Fraction
from functools import lru_cache
import math

from decision_regions import RegionCatalogue, RegionPlanner, exact_rational
from finite_observation import digest


class BudgetedPlanner:
    def __init__(self, catalogue, prior=None, max_states=100000):
        if not isinstance(catalogue, RegionCatalogue):
            raise TypeError('RegionCatalogue required')
        if type(max_states) is not int or max_states <= 0:
            raise ValueError('positive integer state limit required')
        values = tuple(exact_rational(v) for v in (catalogue.weights if prior is None else prior))
        if len(values) != len(catalogue.rows) or any(v <= 0 for v in values):
            raise ValueError('one strictly positive exact prior weight per row required')
        total = sum(values, Fraction(0))
        self.prior = tuple(v / total for v in values)
        self.c = catalogue
        self.base = RegionPlanner(catalogue, max_states=max_states)
        self.all = self.base.all
        self.max_states = max_states
        self._visited = set()
        self._guard_failed = False
        self._mass = lru_cache(None)(self._compute_mass)
        self._expected = lru_cache(None)(self._compute_expected)
        self._local_lex = lru_cache(None)(self._compute_local_lex)
        self.identity = digest(dict(schema='gabriel.budgeted-regions.planning.v1',
                                    model_identity=catalogue.identity,
                                    prior=[str(v) for v in self.prior],
                                    objective='minimum-expected-cost-under-pathwise-budget',
                                    terminal='known-or-blocked'))

    def _alive(self):
        if self._guard_failed:
            raise RuntimeError('budgeted planning state guard previously exceeded')

    def _fail_guard(self):
        self._guard_failed = True
        raise RuntimeError('budgeted planning combined state guard exceeded')

    def _touch(self, key):
        self._alive()
        if key not in self._visited:
            if self.state_count >= self.max_states:
                self._fail_guard()
            self._visited.add(key)

    @property
    def state_count(self):
        return len(self._visited) + len(self.base._visited)

    def _validate(self, state, budget=None):
        self._alive()
        self.base._validate_state(state)
        if budget is not None and (type(budget) is not int or budget < 0):
            raise ValueError('remaining budget must be a nonnegative integer')

    def _compute_mass(self, state):
        return sum((self.prior[i] for i in self.base.members(state)), Fraction(0))

    def mass(self, state):
        self._validate(state)
        return self._mass(state)

    def worst(self, state):
        self._validate(state)
        try:
            result = self.base.value(state)
        except RuntimeError:
            self._guard_failed = True
            raise
        if self.state_count > self.max_states:
            self._fail_guard()
        return result

    def value(self, state, budget):
        """Minimum exact expected cost among all policies obeying this cap."""
        self._validate(state, budget)
        if budget is None:
            raise ValueError('an explicit integer remaining budget is required')
        return self._expected(state, budget)

    def _compute_expected(self, state, budget):
        self._touch(('expected', state, budget))
        if not state or self.worst(state) > budget:
            return math.inf
        if self.base.terminal(state):
            return Fraction(0)
        candidates = []
        for query, children in self.base.informative(state):
            cost = self.c.costs[query]
            if cost > budget:
                continue
            continuations = [self.value(child, budget - cost) for child in children]
            # Every possible branch must be feasible. Positive prior weights
            # prevent a zero-weight branch from silently escaping the hard cap.
            if any(v == math.inf for v in continuations):
                continue
            expected = Fraction(cost) + sum((self.mass(child) / self.mass(state) * value
                                             for child, value in zip(children, continuations)), Fraction(0))
            candidates.append(expected)
        return min(candidates, default=math.inf)

    def local_lex_value(self, state):
        """Expected cost after minimizing worst continuation at EVERY state."""
        self._validate(state)
        return self._local_lex(state)

    def _compute_local_lex(self, state):
        self._touch(('local_lex', state))
        worst = self.worst(state)
        if not state or worst == math.inf:
            return math.inf
        if self.base.terminal(state):
            return Fraction(0)
        candidates = []
        for query, children in self.base.informative(state):
            cost = self.c.costs[query]
            if cost + max(self.worst(child) for child in children) != worst:
                continue
            candidates.append(Fraction(cost) + sum((self.mass(child) / self.mass(state) *
                                                    self.local_lex_value(child) for child in children), Fraction(0)))
        return min(candidates, default=math.inf)

    def choice(self, state, budget, policy='global_lex'):
        self._validate(state, budget)
        if budget is None or policy not in ('global_lex', 'local_lex'):
            raise ValueError('explicit integer budget and recognized policy required')
        if not state or self.base.terminal(state) or self.worst(state) > budget:
            return None
        if policy == 'global_lex':
            target = self.value(state, budget)
            if target == math.inf:
                return None
            for query, children in self.base.informative(state):
                cost = self.c.costs[query]
                if cost > budget:
                    continue
                continuation = [self.value(child, budget - cost) for child in children]
                if any(v == math.inf for v in continuation):
                    continue
                score = Fraction(cost) + sum((self.mass(child) / self.mass(state) * value
                                              for child, value in zip(children, continuation)), Fraction(0))
                if score == target:
                    return query
        else:
            target, worst = self.local_lex_value(state), self.worst(state)
            for query, children in self.base.informative(state):
                cost = self.c.costs[query]
                if cost + max(self.worst(child) for child in children) != worst:
                    continue
                score = Fraction(cost) + sum((self.mass(child) / self.mass(state) *
                                              self.local_lex_value(child) for child in children), Fraction(0))
                if score == target:
                    return query
        raise AssertionError('finite Bellman value lacks a realizing query')
