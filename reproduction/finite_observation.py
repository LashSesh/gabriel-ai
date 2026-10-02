"""Domain-independent decisions from deterministic finite observation models.

Only this module chooses queries and certifies agreement. Domain semantics and
the hidden realised history are absent from the planner. Integer masks and
positive integer costs make the Bellman worst-cost computation exact.
"""
from dataclasses import dataclass, asdict
from functools import lru_cache, cached_property
from fractions import Fraction
import hashlib
import json
import math


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class Catalogue:
    contract_id: str
    query_names: tuple
    costs: tuple
    rows: tuple
    labels: tuple
    weights: tuple = ()

    def __post_init__(self):
        n, m = len(self.rows), len(self.query_names)
        if not n or not m or len(set(self.query_names)) != m:
            raise ValueError('nonempty finite catalogue and distinct queries required')
        if len(self.labels) != n or len(self.costs) != m:
            raise ValueError('shape mismatch')
        if any(len(row) != m or any(type(y) is not str for y in row) for row in self.rows):
            raise ValueError('observations must be canonical strings')
        if any(type(x) is not int or x <= 0 for x in self.costs):
            raise ValueError('positive integer costs required')
        if any(type(x) is not int for x in self.labels):
            raise ValueError('integer decision labels required')
        if not self.weights:
            object.__setattr__(self, 'weights', (1,) * n)
        if len(self.weights) != n or any(type(w) is not int or w <= 0 for w in self.weights):
            raise ValueError('positive integer multiplicities required')

    @cached_property
    def identity(self):
        return digest(asdict(self))

    def quotient(self):
        """Keep target AND every available query outcome; retain multiplicities."""
        indices, rows, labels, weights, raw_to_group = {}, [], [], [], []
        for row, label, weight in zip(self.rows, self.labels, self.weights):
            key = (label, row)
            if key not in indices:
                indices[key] = len(rows)
                rows.append(row); labels.append(label); weights.append(0)
            j = indices[key]
            weights[j] += weight
            raw_to_group.append(j)
        return Catalogue(self.contract_id, self.query_names, self.costs,
                         tuple(rows), tuple(labels), tuple(weights)), tuple(raw_to_group)


class Planner:
    def __init__(self, catalogue):
        self.c = catalogue
        self.all = (1 << len(catalogue.rows)) - 1
        self.outcomes = []
        for q in range(len(catalogue.query_names)):
            groups = {}
            for i, row in enumerate(catalogue.rows):
                groups[row[q]] = groups.get(row[q], 0) | (1 << i)
            self.outcomes.append(dict(sorted(groups.items())))
        self.label_masks = {}
        for i, label in enumerate(catalogue.labels):
            self.label_masks[label] = self.label_masks.get(label, 0) | (1 << i)
        self.value = lru_cache(None)(self._value)
        self.mass = lru_cache(None)(self._mass)
        self.choice = lru_cache(None)(self._choice)

    def members(self, state):
        while state:
            bit = state & -state
            yield bit.bit_length() - 1
            state ^= bit

    def _mass(self, state):
        return sum(self.c.weights[i] for i in self.members(state))

    def decision(self, state):
        """Empty means conflict, not vacuous agreement."""
        labels = [k for k, mask in self.label_masks.items() if state & mask]
        return labels[0] if len(labels) == 1 else None

    def branches(self, state, q):
        return tuple(mask & state for mask in self.outcomes[q].values() if mask & state)

    def informative(self, state):
        return [(q, self.branches(state, q)) for q in range(len(self.outcomes))
                if len(self.branches(state, q)) > 1]

    def observe(self, state, q, outcome):
        if type(q) is not int or not 0 <= q < len(self.outcomes):
            raise ValueError('unknown query')
        return state & self.outcomes[q].get(outcome, 0)

    def _value(self, state):
        if not state:
            return math.inf
        if self.decision(state) is not None:
            return 0
        best = math.inf
        for q, children in self.informative(state):
            worst = max(self.value(s) for s in children)
            best = min(best, self.c.costs[q] + worst)
        return best

    def cross_pairs(self, state):
        masses = [self.mass(state & mask) for mask in self.label_masks.values()]
        return (sum(masses) ** 2 - sum(m * m for m in masses)) // 2

    def _choice(self, state, policy):
        if not state or self.decision(state) is not None:
            return None
        choices = self.informative(state)
        if not choices:
            return None
        if policy in ('fixed', 'reverse'):
            return choices[0 if policy == 'fixed' else -1][0]
        if policy == 'minimax':
            if math.isinf(self.value(state)):
                return None
            return min(choices, key=lambda qc: (
                self.c.costs[qc[0]] + max(self.value(s) for s in qc[1]), qc[0]))[0]
        if policy == 'ec2':
            total = self.mass(state)
            def gain(qc):
                q, children = qc
                numerator = total * self.cross_pairs(state) - sum(
                    self.mass(s) * self.cross_pairs(s) for s in children)
                return Fraction(numerator, total * self.c.costs[q])
            return max(choices, key=lambda qc: (gain(qc), -qc[0]))[0]
        if policy == 'hypothesis_entropy':
            total = self.mass(state)
            gains = []
            for q, children in choices:
                ps = [self.mass(s) / total for s in children]
                gains.append((q, -sum(p * math.log2(p) for p in ps) / self.c.costs[q]))
            best = max(v for _, v in gains)
            return min(q for q, v in gains if v >= best - 1e-12)
        raise ValueError('unknown policy')


def remove_independent_queries(catalogue):
    """Exact support-product test; preserve optimal WORST cost.

    For query q define z=(target, all other query outcomes). If the realised
    pairs (z,y_q) fill their Cartesian product, q cannot restrict any z.
    Delete it, merge identical remaining (target, observation) rows, and retain
    marginal multiplicity. The extra weight test records prior factorization;
    it is not needed for the worst-case theorem.
    """
    c = catalogue
    original = list(range(len(c.query_names)))
    certificates = []
    while len(c.query_names) > 1:
        removed = False
        for q in range(len(c.query_names)):
            joint = {}
            for row, target, w in zip(c.rows, c.labels, c.weights):
                z = (target, row[:q]+row[q+1:])
                key = (z,row[q]); joint[key] = joint.get(key,0)+w
            zs = {z for z,_ in joint}; ys = {y for _,y in joint}
            if len(joint) != len(zs)*len(ys): continue
            wz = {z:sum(w for (v,y),w in joint.items() if v==z) for z in zs}
            wy = {y:sum(w for (z,v),w in joint.items() if v==y) for y in ys}
            total = sum(joint.values())
            factored = all(w*total==wz[z]*wy[y] for (z,y),w in joint.items())
            before = c.identity
            new = Catalogue(c.contract_id+';independent_query_removed='+c.query_names[q],
                            c.query_names[:q]+c.query_names[q+1:],c.costs[:q]+c.costs[q+1:],
                            tuple(row[:q]+row[q+1:] for row in c.rows),c.labels,c.weights)
            new,_ = new.quotient()
            certificates.append(dict(query=c.query_names[q],original_index=original[q],
                                     before=before, after=new.identity,
                                     distinct_remaining_target_signatures=len(zs),
                                     distinct_query_outcomes=len(ys),distinct_pairs=len(joint),
                                     support_product=True,weight_product=factored))
            del original[q];c=new;removed=True;break
        if not removed: break
    return c, tuple(original), certificates


@dataclass(frozen=True)
class Observation:
    contract_digest: str
    query: int
    outcome: str
    source_id: str
    event_interval: tuple
    received_at: int
    status: str = 'observed'
    kind: str = 'passive'


class Session:
    """Evidence is a constraint, not an independent statistical sample.

    Time fields use one declared integer clock. Delayed observations may be
    added at a later cutoff; interval times are preserved rather than imputed.
    A session is bound to one frozen catalogue and passive immutable values.
    """
    def __init__(self, planner):
        self.planner, self.state = planner, planner.all
        self.seen = {}
        self.ledger = []
        self.cutoff = None

    def ingest(self, observation, cutoff):
        e = observation
        if e.contract_digest != self.planner.c.identity:
            raise ValueError('model or target contract mismatch')
        if e.status != 'observed' or e.kind != 'passive':
            raise ValueError('only actual passive observations enter this session')
        if type(e.outcome) is not str:
            raise ValueError('a canonical observation string is required')
        if not e.source_id or type(e.received_at) is not int or type(cutoff) is not int:
            raise ValueError('invalid provenance or clock')
        a, b = e.event_interval
        if any(type(t) is not int for t in (a, b)) or not a <= b <= e.received_at:
            raise ValueError('invalid completed-event time interval')
        if e.received_at > cutoff:
            raise ValueError('observation unavailable at decision cutoff')
        if self.cutoff is not None and cutoff < self.cutoff:
            raise ValueError('cannot reuse a later session at an earlier cutoff')
        key = e.source_id
        content = (e.query, e.outcome, e.event_interval)
        if key in self.seen:
            if self.seen[key] != content:
                raise ValueError('conflicting reuse of source identity')
            self.cutoff = cutoff
            return False
        before = self.state
        self.state = self.planner.observe(before, e.query, e.outcome)
        self.seen[key] = content
        self.cutoff = cutoff
        self.ledger.append(dict(observation=asdict(e), cutoff=cutoff,
                                before=hex(before), after=hex(self.state)))
        return True

    def result(self):
        label = self.planner.decision(self.state)
        status = 'conflict' if not self.state else ('decided' if label is not None else 'unresolved')
        return dict(status=status, label=label, cutoff=self.cutoff, compatible_count=self.state.bit_count(),
                    compatible_weight=self.planner.mass(self.state))
