"""Exact parity observation with bounded persistent report errors.

The latent record satisfies an affine binary model. A query reads one coordinate
of a frozen report; at most t reported coordinates differ from that record.
This does not assert that a physically defective connection is still flat.
"""
from itertools import combinations
from math import comb
import hashlib
import json
from orientation import (BinaryObservation, elimination, particular, parity,
                         support, profile_graph, face_rows, cycle_mask,
                         nullspace, span_masks)
from finite_observation import Catalogue, Planner


def error_masks(indices, budget):
    for size in range(min(budget, len(indices)) + 1):
        for subset in combinations(indices, size):
            yield sum(1 << j for j in subset)


class BoundedErrorObservation:
    def __init__(self, model, budget, pattern_limit=100000):
        if not isinstance(model, BinaryObservation):
            raise ValueError('an affine BinaryObservation is required')
        if type(budget) is not int or budget < 0:
            raise ValueError('nonnegative integer error budget required')
        if type(pattern_limit) is not int or pattern_limit < 1:
            raise ValueError('positive integer pattern limit required')
        self.model, self.budget, self.pattern_limit = model, budget, pattern_limit
        contract = dict(n=model.n, rows=model.rows, rhs=model.rhs,
                        target=model.target, budget=budget,
                        noise='persistent-coordinate-flips', duplicate='reject')
        self.identity = hashlib.sha256(json.dumps(contract, sort_keys=True).encode()).hexdigest()

    def observe(self, observations):
        obs = list(observations)
        # Validate before enumeration, including the empty-observation case.
        if any(type(j) is not int or type(y) is not int or y not in (0, 1) for j, y in obs):
            raise ValueError('integer coordinate and bit values required')
        self.model.observe(obs)
        if len({j for j, _ in obs}) != len(obs):
            raise ValueError('query each coordinate at most once; duplicates are not independent')
        indices = [int(j) for j, _ in obs]
        count = sum(comb(len(obs), k) for k in range(min(self.budget, len(obs)) + 1))
        if count > self.pattern_limit:
            raise ValueError('error-pattern enumeration guard')
        branches, witnesses = [], {}
        for error in error_masks(indices, self.budget):
            corrected = [(j, int(y) ^ ((error >> j) & 1)) for j, y in obs]
            result = self.model.observe(corrected)
            if result['status'] == 'ambiguous':
                return dict(status='ambiguous', identity=self.identity,
                            witnesses=[dict(record=a, error=error)
                                       for a in result['completions']])
            branches.append(dict(error=error, **result))
            if result['status'] == 'known':
                value = result['value']
                if value not in witnesses:
                    basis, conflict = elimination(
                        list(self.model.rows) + [1 << j for j, _ in corrected],
                        list(self.model.rhs) + [y for _, y in corrected])
                    assert conflict is None
                    witnesses[value] = dict(record=particular(basis), error=error)
                if len(witnesses) == 2:
                    return dict(status='ambiguous', identity=self.identity,
                                witnesses=[witnesses[0], witnesses[1]])
        if not witnesses:
            return dict(status='conflict', identity=self.identity, branches=branches)
        return dict(status='known', value=next(iter(witnesses)), identity=self.identity,
                    witness=next(iter(witnesses.values())), branches=branches)


def check_certificate(observer, observations, result):
    """Check XOR proofs and complete error-pattern coverage, without elimination."""
    model, budget = observer.model, observer.budget
    obs = list(observations)
    if result.get('identity') != observer.identity or len({j for j, _ in obs}) != len(obs):
        return False
    if any(type(j) is not int or not 0 <= j < model.n or y not in (0, 1) for j, y in obs):
        return False
    indices = [j for j, _ in obs]
    def valid_witness(w, label):
        a, error = w['record'], w['error']
        return (type(a) is int and 0 <= a < 1 << model.n
                and error in set(error_masks(indices, budget))
                and all(parity(r, a) == b for r, b in zip(model.rows, model.rhs))
                and all(((a >> j) & 1) == (y ^ ((error >> j) & 1)) for j, y in obs)
                and parity(model.target, a) == label)
    if result.get('status') == 'ambiguous':
        return len(result.get('witnesses', [])) == 2 and all(
            valid_witness(w, h) for h, w in enumerate(result['witnesses']))
    if result.get('status') not in ('known', 'conflict'):
        return False
    branches = result.get('branches', [])
    expected = list(error_masks(indices, budget))
    if len(branches) != len(expected) or {r['error'] for r in branches} != set(expected):
        return False
    feasible = 0
    for branch in branches:
        rows = list(model.rows) + [1 << j for j, _ in obs]
        rhs = list(model.rhs) + [y ^ ((branch['error'] >> j) & 1) for j, y in obs]
        w = branch.get('combination', -1)
        if type(w) is not int or not 0 <= w < 1 << len(rows):
            return False
        rr = bb = 0
        for k in support(w):
            rr ^= rows[k]; bb ^= rhs[k]
        if branch['status'] == 'conflict':
            if rr != 0 or bb != 1: return False
        elif branch['status'] == 'known' and result['status'] == 'known':
            feasible += 1
            if rr != model.target or bb != result['value'] or branch['value'] != bb:
                return False
        else:
            return False
    return (feasible == 0 if result['status'] == 'conflict' else
            feasible > 0 and valid_witness(result['witness'], result['value']))


class AnnularErrorPolicy:
    """Read two rings, then choose exact tests on a canonical 24-record state.

The exact Bellman continuation is optimal CONDITIONAL on this twelve-query
prefix. The module makes no global optimality claim for the whole policy.
"""
    def __init__(self):
        self.vertices, self.edges, self.faces = profile_graph()
        self.rows = face_rows(self.edges, self.faces)
        self.inner = cycle_mask(self.edges, list(range(1, 7)))
        self.outer = cycle_mask(self.edges, list(range(7, 13)))
        self.rings = self.inner | self.outer
        self.prefix = support(self.inner) + support(self.outer)
        self.remaining = [j for j in range(24) if not (self.rings >> j) & 1]
        self.canonical_report = 1 << self.prefix[0]
        self.code = sorted(span_masks(nullspace(self.rows, 24)))
        self.candidates = [a for a in self.code
                           if ((a ^ self.canonical_report) & self.rings).bit_count() <= 1]
        assert len(self.candidates) == 24
        catalogue = Catalogue(
            'annular-persistent-one-error-after-ring-disagreement',
            tuple(str(j) for j in self.remaining), (1,) * 12,
            tuple(tuple(str((a >> j) & 1) for j in self.remaining) for a in self.candidates),
            tuple(parity(self.inner, a) for a in self.candidates))
        self.planner = Planner(catalogue)
        self.planner.value(self.planner.all)

    def execute(self, fetch, continuation='minimax'):
        observations = []
        def read(j):
            y = fetch(j)
            if type(y) is not int or y not in (0, 1): raise ValueError('a binary report is required')
            observations.append((j, y))
            return y
        report = sum(read(j) << j for j in self.prefix)
        if parity(self.inner, report) == parity(self.outer, report):
            return dict(status='known', value=parity(self.inner, report), observations=observations,
                        normalization=0, continuation_states=[])
        # Adding a flat offset maps every odd ring report to one canonical coset.
        corrected = report ^ self.canonical_report
        basis, conflict = elimination(list(self.rows) + [1 << j for j in self.prefix],
                                      [0] * len(self.rows) + [(corrected >> j) & 1 for j in self.prefix])
        assert conflict is None
        offset = particular(basis)
        state = self.planner.all; path = [state]
        while state and self.planner.decision(state) is None:
            q = self.planner.choice(state, continuation)
            if q is None: break
            j = self.remaining[q]
            value = read(j) ^ ((offset >> j) & 1)
            state = self.planner.observe(state, q, str(value)); path.append(state)
        if not state:
            return dict(status='conflict', observations=observations,
                        normalization=offset, continuation_states=path)
        value = self.planner.decision(state)
        if value is None:
            return dict(status='ambiguous', observations=observations,
                        normalization=offset, continuation_states=path)
        return dict(status='known', value=value ^ parity(self.inner, offset),
                    observations=observations, normalization=offset, continuation_states=path)

    def bellman_certificate(self):
        nodes = {}; pending = [self.planner.all]
        while pending:
            state = pending.pop()
            if str(state) in nodes: continue
            label = self.planner.decision(state)
            branches = []
            if label is None:
                for q, children in self.planner.informative(state):
                    branches.append(dict(query=q, children=list(children)))
                    pending.extend(children)
            nodes[str(state)] = dict(label=label, value=self.planner.value(state),
                                     choice=self.planner.choice(state, 'minimax'), branches=branches)
        return dict(candidates=self.candidates, remaining=self.remaining,
                    root=self.planner.all, nodes=nodes)
