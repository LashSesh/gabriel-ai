"""Exact acceptable-action planning for a finite, frozen observation contract.

This is a finite specialization of decision-region determination, not a new
general stopping rule. Each row is a current immutable fact record. ``risks``
contains already computed model-robust action scores; uncertainty over future
scenarios must be integrated by the adapter, never supplied as an observation.

Risk arithmetic and Bellman costs are exact. Hypothesis-entropy query ordering
uses floating logarithms and is only a heuristic. EC2 here is the established
strict-label baseline, not an approximation algorithm for overlapping regions.
"""
from dataclasses import dataclass
from fractions import Fraction
from functools import cached_property, lru_cache
import math
import re

from finite_observation import Observation, Session, digest


def exact_rational(value):
    """Accept exact integers/Fractions or canonical reduced rational strings."""
    if type(value) is int:
        return Fraction(value)
    if type(value) is Fraction:
        return value
    if type(value) is str and re.fullmatch(r'-?(?:0|[1-9][0-9]*)(?:/[1-9][0-9]*)?', value):
        result = Fraction(value)
        if str(result) == value:
            return result
    raise ValueError('exact rational required: int, Fraction or canonical reduced string')


@dataclass(frozen=True)
class RegionCatalogue:
    contract_id: str
    query_names: tuple
    costs: tuple
    rows: tuple
    action_names: tuple
    risks: tuple  # row-major: risks[fact_record][action]
    epsilon: object = '0'
    risk_limit: object = None
    weights: tuple = ()
    max_rows: int = 4096
    feasible: tuple = ()  # optional row-major adapter feasibility flags

    def __post_init__(self):
        if type(self.contract_id) is not str or not self.contract_id:
            raise ValueError('nonempty contract identity required')
        if type(self.max_rows) is not int or self.max_rows <= 0:
            raise ValueError('positive integer catalogue guard required')
        for name in ('query_names', 'costs', 'action_names', 'weights'):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        object.__setattr__(self, 'rows', tuple(tuple(row) for row in self.rows))
        n, m, k = len(self.rows), len(self.query_names), len(self.action_names)
        if not n or n > self.max_rows:
            raise ValueError('nonempty catalogue must satisfy max_rows')
        for names in (self.query_names, self.action_names):
            if any(type(x) is not str or not x for x in names) or len(set(names)) != len(names):
                raise ValueError('distinct nonempty string names required')
        if not k or len(self.costs) != m:
            raise ValueError('at least one action and one cost per query required')
        if any(type(x) is not int or x <= 0 for x in self.costs):
            raise ValueError('positive integer query costs required')
        if any(len(row) != m or any(type(x) is not str for x in row) for row in self.rows):
            raise ValueError('observation rows must contain canonical strings')
        risks = tuple(tuple(exact_rational(v) for v in row) for row in self.risks)
        if len(risks) != n or any(len(row) != k for row in risks):
            raise ValueError('one rational score per fact record and action required')
        epsilon = exact_rational(self.epsilon)
        if epsilon < 0:
            raise ValueError('epsilon must be nonnegative')
        limit = None if self.risk_limit is None else exact_rational(self.risk_limit)
        object.__setattr__(self, 'risks', risks)
        object.__setattr__(self, 'epsilon', epsilon)
        object.__setattr__(self, 'risk_limit', limit)
        flags = (tuple(tuple(row) for row in self.feasible) if self.feasible else
                 tuple((True,) * k for _ in range(n)))
        if len(flags) != n or any(len(row) != k or any(type(v) is not bool for v in row)
                                  for row in flags):
            raise ValueError('one exact Boolean feasibility flag per record and action required')
        object.__setattr__(self, 'feasible', flags)
        if not self.weights:
            object.__setattr__(self, 'weights', (1,) * n)
        if len(self.weights) != n or any(type(w) is not int or w <= 0 for w in self.weights):
            raise ValueError('positive integer multiplicities required')

    @cached_property
    def identity(self):
        # This binds all scores, outcomes, costs, priors, action ordering and the
        # target definition. The computational guard is not part of the model.
        return digest(dict(schema='gabriel.decision-regions.model.v1',
                           contract_id=self.contract_id, query_names=self.query_names,
                           costs=self.costs, rows=self.rows, action_names=self.action_names,
                           risks=[[str(v) for v in row] for row in self.risks],
                           epsilon=str(self.epsilon),
                           risk_limit=None if self.risk_limit is None else str(self.risk_limit),
                           weights=self.weights, feasible=self.feasible))

    @cached_property
    def acceptable_masks(self):
        masks = []
        for row, flags in zip(self.risks, self.feasible):
            feasible = [a for a, value in enumerate(row)
                        if flags[a] and (self.risk_limit is None or value <= self.risk_limit)]
            if not feasible:
                masks.append(0)
                continue
            best = min(row[a] for a in feasible)
            masks.append(sum(1 << a for a in feasible if row[a] - best <= self.epsilon))
        return tuple(masks)

    @cached_property
    def strict_labels(self):
        """First minimum feasible action; -1 is the no-feasible-action label."""
        labels = []
        for row, flags in zip(self.risks, self.feasible):
            feasible = [a for a, value in enumerate(row)
                        if flags[a] and (self.risk_limit is None or value <= self.risk_limit)]
            labels.append(min(feasible, key=lambda a: (row[a], a)) if feasible else -1)
        return tuple(labels)


class RegionPlanner:
    """Exact worst-cost planning with an explicit exponential-state guard."""
    POLICIES = ('minimax', 'fixed', 'reverse', 'hypothesis_entropy',
                'strict_minimax', 'strict_ec2')

    def __init__(self, catalogue, max_states=100000):
        if not isinstance(catalogue, RegionCatalogue):
            raise TypeError('RegionCatalogue required')
        if type(max_states) is not int or max_states <= 0:
            raise ValueError('positive integer state guard required')
        self.c = catalogue
        self.max_states = max_states
        self.all = (1 << len(catalogue.rows)) - 1
        self.outcomes = []
        for q in range(len(catalogue.query_names)):
            groups = {}
            for i, row in enumerate(catalogue.rows):
                groups[row[q]] = groups.get(row[q], 0) | (1 << i)
            self.outcomes.append(dict(sorted(groups.items())))
        self.label_masks = {}
        for i, label in enumerate(catalogue.strict_labels):
            self.label_masks[label] = self.label_masks.get(label, 0) | (1 << i)
        self._visited = set()
        self.value = lru_cache(None)(lambda state: self._value(state, False))
        self.strict_value = lru_cache(None)(lambda state: self._value(state, True))

    def _validate_state(self, state):
        if type(state) is not int or state < 0 or state & ~self.all:
            raise ValueError('invalid compatible-record mask')

    def members(self, state):
        self._validate_state(state)
        while state:
            bit = state & -state
            yield bit.bit_length() - 1
            state ^= bit

    def mass(self, state):
        return sum(self.c.weights[i] for i in self.members(state))

    def assess(self, state):
        self._validate_state(state)
        common, possible = (1 << len(self.c.action_names)) - 1, 0
        for i in self.members(state):
            common &= self.c.acceptable_masks[i]
            possible |= self.c.acceptable_masks[i]
        if not state:
            common = 0
        status = ('conflict' if not state else 'known' if common else
                  'blocked' if not possible else 'unresolved')
        actions = tuple(a for i, a in enumerate(self.c.action_names) if common >> i & 1)
        return dict(status=status, action=actions[0] if actions else None,
                    acceptable_actions=actions,
                    possible_actions=tuple(a for i, a in enumerate(self.c.action_names)
                                           if possible >> i & 1),
                    compatible_count=state.bit_count(), compatible_weight=self.mass(state))

    def strict_terminal(self, state):
        self._validate_state(state)
        return bool(state) and sum(bool(state & mask) for mask in self.label_masks.values()) == 1

    def terminal(self, state, policy='minimax'):
        if policy not in self.POLICIES:
            raise ValueError('unknown policy')
        return (self.strict_terminal(state) if policy.startswith('strict_') else
                self.assess(state)['status'] in ('known', 'blocked'))

    def branches(self, state, query):
        self._validate_state(state)
        self._validate_query(query)
        return tuple(state & mask for mask in self.outcomes[query].values() if state & mask)

    def _validate_query(self, query):
        if type(query) is not int or not 0 <= query < len(self.outcomes):
            raise ValueError('unknown query')

    def informative(self, state):
        self._validate_state(state)
        return [(q, self.branches(state, q)) for q in range(len(self.outcomes))
                if len(self.branches(state, q)) > 1]

    def observe(self, state, query, outcome):
        self._validate_state(state)
        self._validate_query(query)
        if type(outcome) is not str:
            raise ValueError('canonical observation string required')
        return state & self.outcomes[query].get(outcome, 0)

    def _value(self, state, strict):
        self._validate_state(state)
        key = (state, strict)
        if key not in self._visited:
            if len(self._visited) >= self.max_states:
                raise RuntimeError('exact decision-region state guard exceeded')
            self._visited.add(key)
        if not state:
            return math.inf
        terminal = self.strict_terminal(state) if strict else self.terminal(state)
        if terminal:
            return 0
        recurse = self.strict_value if strict else self.value
        return min((self.c.costs[q] + max(recurse(child) for child in children)
                    for q, children in self.informative(state)), default=math.inf)

    def choice(self, state, policy='minimax'):
        self._validate_state(state)
        if policy not in self.POLICIES:
            raise ValueError('unknown policy')
        if not state or self.terminal(state, policy):
            return None
        choices = self.informative(state)
        if not choices:
            return None
        if policy in ('fixed', 'reverse'):
            return choices[0 if policy == 'fixed' else -1][0]
        if policy in ('minimax', 'strict_minimax'):
            value = self.strict_value if policy == 'strict_minimax' else self.value
            if math.isinf(value(state)):
                return None
            return min(choices, key=lambda qc: (
                self.c.costs[qc[0]] + max(value(child) for child in qc[1]), qc[0]))[0]
        if policy == 'strict_ec2':
            def cross_pairs(s):
                masses = [self.mass(s & mask) for mask in self.label_masks.values()]
                return (sum(masses) ** 2 - sum(w * w for w in masses)) // 2
            total = self.mass(state)
            def gain(qc):
                q, children = qc
                return Fraction(total * cross_pairs(state) - sum(
                    self.mass(child) * cross_pairs(child) for child in children),
                    total * self.c.costs[q])
            return max(choices, key=lambda qc: (gain(qc), -qc[0]))[0]
        total = self.mass(state)
        def entropy_gain(qc):
            q, children = qc
            probabilities = [self.mass(child) / total for child in children]
            return -sum(p * math.log2(p) for p in probabilities) / self.c.costs[q]
        gains = [(q, entropy_gain((q, children))) for q, children in choices]
        best = max(gain for _, gain in gains)
        return min(q for q, gain in gains if gain >= best - 1e-12)


class RegionSession(Session):
    """Reuse passive immutable-record ingestion and integer-clock semantics."""
    def ingest(self, observation, cutoff):
        if (not isinstance(observation, Observation) or type(observation.source_id) is not str or
            not isinstance(observation.event_interval, (tuple, list)) or
            len(observation.event_interval) != 2):
            raise ValueError('valid passive Observation and string source identity required')
        self.planner._validate_query(observation.query)
        return super().ingest(observation, cutoff)

    def result(self):
        return dict(self.planner.assess(self.state), cutoff=self.cutoff)

    def certificate(self):
        c = self.planner.c
        report = self.result()
        # Lists and plain numbers make the certificate JSON round-trip stable.
        return dict(schema='gabriel.decision-regions.certificate.v1',
                    model_identity=c.identity, target='common-epsilon-feasible-action',
                    action_order=list(c.action_names), epsilon=str(c.epsilon),
                    risk_limit=None if c.risk_limit is None else str(c.risk_limit),
                    ledger=[dict(entry, observation=dict(entry['observation'],
                                 event_interval=list(entry['observation']['event_interval'])))
                            for entry in self.ledger], cutoff=self.cutoff,
                    compatible_mask=hex(self.state),
                    acceptable_masks=[dict(row=i, mask=hex(c.acceptable_masks[i]))
                                      for i in self.planner.members(self.state)],
                    status=report['status'], action=report['action'],
                    acceptable_actions=list(report['acceptable_actions']),
                    possible_actions=list(report['possible_actions']),
                    compatible_count=report['compatible_count'],
                    compatible_weight=report['compatible_weight'])


def verify_certificate(catalogue, certificate):
    """Independent replay: no RegionPlanner or cached acceptance masks used.

    This verifies a conditional finite-model claim, not truth/authenticity of
    the supplied evidence, adapter calibration or completeness of the model.
    """
    try:
        return _verify_certificate(catalogue, certificate)
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, OverflowError):
        return False


def _verify_certificate(c, cert):
    if not isinstance(c, RegionCatalogue) or type(cert) is not dict:
        return False
    keys = {'schema', 'model_identity', 'target', 'action_order', 'epsilon', 'risk_limit',
            'ledger', 'cutoff', 'compatible_mask', 'acceptable_masks', 'status', 'action',
            'acceptable_actions', 'possible_actions', 'compatible_count', 'compatible_weight'}
    if set(cert) != keys:
        return False
    if (cert['schema'] != 'gabriel.decision-regions.certificate.v1' or
        cert['model_identity'] != c.identity or cert['target'] != 'common-epsilon-feasible-action' or
        cert['action_order'] != list(c.action_names) or cert['epsilon'] != str(c.epsilon) or
        cert['risk_limit'] != (None if c.risk_limit is None else str(c.risk_limit))):
        return False
    indices = list(range(len(c.rows)))
    def mask(rows):
        return hex(sum(1 << i for i in rows))
    cutoff, seen = None, set()
    if type(cert['ledger']) is not list:
        return False
    for entry in cert['ledger']:
        if type(entry) is not dict or set(entry) != {'observation', 'cutoff', 'before', 'after'}:
            return False
        evidence, now = entry['observation'], entry['cutoff']
        if (type(evidence) is not dict or set(evidence) != {
                'contract_digest', 'query', 'outcome', 'source_id', 'event_interval',
                'received_at', 'status', 'kind'}):
            return False
        q, outcome = evidence['query'], evidence['outcome']
        interval = evidence['event_interval']
        if type(now) is not int or (cutoff is not None and now < cutoff):
            return False
        if (evidence['contract_digest'] != c.identity or evidence['status'] != 'observed' or
            evidence['kind'] != 'passive' or type(q) is not int or not 0 <= q < len(c.costs) or
            type(outcome) is not str or type(evidence['source_id']) is not str or
            not evidence['source_id'] or evidence['source_id'] in seen or
            type(interval) is not list or len(interval) != 2 or
            any(type(t) is not int for t in interval) or type(evidence['received_at']) is not int or
            not interval[0] <= interval[1] <= evidence['received_at'] <= now):
            return False
        if entry['before'] != mask(indices):
            return False
        indices = [i for i in indices if c.rows[i][q] == outcome]
        if entry['after'] != mask(indices):
            return False
        seen.add(evidence['source_id'])
        cutoff = now
    # Repeated identical evidence can advance a live Session cutoff without
    # creating a second ledger entry. It never removes an evidence constraint.
    final_cutoff = cert['cutoff']
    if cutoff is None:
        if final_cutoff is not None:
            return False
    elif type(final_cutoff) is not int or final_cutoff < cutoff:
        return False
    if cert['compatible_mask'] != mask(indices):
        return False
    acceptable_sets, masks = [], []
    for i in indices:
        scores = c.risks[i]
        feasible = {a for a in range(len(c.action_names))
                    if c.feasible[i][a] and (c.risk_limit is None or scores[a] <= c.risk_limit)}
        if feasible:
            minimum = min(scores[a] for a in feasible)
            acceptable = {a for a in feasible if scores[a] <= minimum + c.epsilon}
        else:
            acceptable = set()
        acceptable_sets.append(acceptable)
        masks.append(dict(row=i, mask=hex(sum(2 ** a for a in acceptable))))
    common = set.intersection(*acceptable_sets) if acceptable_sets else set()
    possible = set.union(*acceptable_sets) if acceptable_sets else set()
    status = ('conflict' if not indices else 'known' if common else
              'blocked' if not possible else 'unresolved')
    actions = [c.action_names[a] for a in range(len(c.action_names)) if a in common]
    expected = dict(acceptable_masks=masks, status=status, action=actions[0] if actions else None,
                    acceptable_actions=actions,
                    possible_actions=[c.action_names[a] for a in range(len(c.action_names)) if a in possible],
                    compatible_count=len(indices), compatible_weight=sum(c.weights[i] for i in indices))
    # JSON comparison keeps booleans distinct from integers in untrusted fields.
    return digest({key: cert[key] for key in expected}) == digest(expected)


def run_policy(planner, row_index, policy='minimax', include_certificate=False):
    """Execute one immutable catalogue row; no future scenario query exists."""
    if type(row_index) is not int or not 0 <= row_index < len(planner.c.rows):
        raise ValueError('invalid realised fact-record index')
    if policy not in planner.POLICIES:
        raise ValueError('unknown policy')
    session = RegionSession(planner)
    queries, cost = [], 0
    while not planner.terminal(session.state, policy):
        query = planner.choice(session.state, policy)
        if query is None:
            break
        session.ingest(Observation(planner.c.identity, query, planner.c.rows[row_index][query],
                                   'query:' + str(query), (0, 0), 0), cutoff=0)
        queries.append(query)
        cost += planner.c.costs[query]
    result = dict(session.result(), cost=cost, query_count=len(queries), queries=queries,
                  policy=policy, policy_terminal=planner.terminal(session.state, policy),
                  compatible_mask=hex(session.state))
    if include_certificate:
        result['certificate'] = session.certificate()
    return result
