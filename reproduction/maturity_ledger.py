"""Receipt-causal target maturity and revision-aware feedback replay.

The ledger operates on declared common integer clocks. It binds supplied
predictions and outcomes; it neither authenticates receipts nor verifies an
external scoring rule. Exact JSON excludes floats; binary64 values may be bound
as explicit hexadecimal strings, without turning their arithmetic into a proof.
"""
from dataclasses import dataclass, asdict
from functools import cached_property
import json

from sequential_contract import (EventRevision, BitemporalLedger, canonical,
                                 identity, _text, _clock)


@dataclass(frozen=True, order=True)
class TargetRequirement:
    source_id: str
    record_id: str
    event_start: int
    event_end: int

    def __post_init__(self):
        _text(self.source_id, 'source_id'); _text(self.record_id, 'record_id')
        _clock(self.event_start, 'event_start'); _clock(self.event_end, 'event_end')
        if self.event_start > self.event_end:
            raise ValueError('invalid required event interval')

    @property
    def key(self):
        return self.source_id, self.record_id


@dataclass(frozen=True)
class IssuedForecast:
    forecast_id: str
    origin: int
    target_end: int
    issued_at: int
    requirements: tuple
    prediction_json: str
    lane_id: str
    provenance_json: str

    def __post_init__(self):
        _text(self.forecast_id, 'forecast_id'); _text(self.lane_id, 'lane_id')
        for key in ('origin', 'target_end', 'issued_at'):
            _clock(getattr(self, key), key)
        if not self.origin <= self.issued_at < self.target_end:
            raise ValueError('forecast must be issued after origin and before target completion')
        object.__setattr__(self, 'requirements', tuple(self.requirements))
        if not self.requirements or any(not isinstance(x, TargetRequirement) for x in self.requirements):
            raise ValueError('nonempty typed target requirements required')
        keys = [r.key for r in self.requirements]
        if len(keys) != len(set(keys)):
            raise ValueError('duplicate source-record requirement')
        if any(not self.origin <= r.event_start <= r.event_end <= self.target_end for r in self.requirements):
            raise ValueError('outcome evidence must lie within the target interval')
        if not any(r.event_end == self.target_end for r in self.requirements):
            raise ValueError('at least one observation must witness the target endpoint')
        for key in ('prediction_json', 'provenance_json'):
            try:
                payload = json.loads(getattr(self, key))
            except (TypeError, json.JSONDecodeError) as exc:
                raise ValueError('invalid exact JSON') from exc
            if canonical(payload) != getattr(self, key):
                raise ValueError('noncanonical or inexact JSON')

    @classmethod
    def create(cls, forecast_id, origin, target_end, issued_at, requirements,
               prediction, lane_id='default', provenance=None):
        return cls(forecast_id, origin, target_end, issued_at, tuple(requirements),
                   canonical(prediction), lane_id, canonical({} if provenance is None else provenance))

    @cached_property
    def identity(self):
        return identity(asdict(self))


@dataclass(frozen=True)
class MatureScore:
    forecast_id: str
    forecast_digest: str
    lane_id: str
    target_end: int
    issued_at: int
    first_matured_at: int
    evidence: tuple
    score_json: str

    @property
    def order_key(self):
        return self.first_matured_at, self.target_end, self.issued_at, self.forecast_id

    @cached_property
    def identity(self):
        return identity(asdict(self))


@dataclass(frozen=True)
class FeedbackSnapshot:
    event_cutoff: int
    receipt_cutoff: int
    operation_cutoff: int
    availability_mode: str
    scoring_rule_id: str
    forecasts: tuple
    active: tuple
    pending: tuple

    @cached_property
    def identity(self):
        return identity(asdict(self))

    def replay(self, initial_state, reducer, lane_id=None):
        """Recompute from one current score per target in receipt-maturity order.

        The order position is fixed at the first complete set of received target
        evidence. Later corrections replace its score at that position. This is
        a current-information replay, not a rewrite of historical issued output.
        reducer(state, score_payload) must be deterministic on its supplied data.
        """
        state = json.loads(canonical(initial_state))
        for record in self.active:
            if lane_id is None or record.lane_id == lane_id:
                state = json.loads(canonical(reducer(state, json.loads(record.score_json))))
        return state

    def changes_from(self, previous):
        if not isinstance(previous, FeedbackSnapshot):
            raise ValueError('previous feedback snapshot required')
        if (self.availability_mode != previous.availability_mode or
                self.scoring_rule_id != previous.scoring_rule_id):
            raise ValueError('cannot compare different receipt assumptions or scoring rules')
        old = {r.forecast_id: r for r in previous.active}
        new = {r.forecast_id: r for r in self.active}
        return tuple((key, 'new' if key not in old else 'removed' if key not in new else 'revised')
                     for key in sorted(old.keys() | new.keys())
                     if key not in old or key not in new or old[key].identity != new[key].identity)


class MaturityLedger:
    """Retain immutable issues and receipt-ordered outcome revisions.

    Issue and new receipt operations advance a common declared clock. Replaying
    an identical previously accepted issue/receipt is idempotent; conflicting
    reuse is rejected. All snapshots are as-of selections over retained records.
    A scoring rule is fixed for a ledger and named by a caller-supplied identity.
    """
    def __init__(self, scorer, scoring_rule_id, availability_mode='declared_observed_receipts'):
        if not callable(scorer):
            raise ValueError('callable deterministic scorer required')
        _text(scoring_rule_id, 'scoring_rule_id')
        self.scorer = scorer
        self.scoring_rule_id = scoring_rule_id
        self.ledger = BitemporalLedger(availability_mode)
        self._forecasts = {}
        self._requirements = {}
        self._received = {}
        self._clock = None
        self._operations = []

    @property
    def forecasts(self):
        return tuple(self._forecasts[k] for k in sorted(self._forecasts))

    @property
    def clock(self):
        return self._clock

    def issue(self, forecast):
        if not isinstance(forecast, IssuedForecast):
            raise ValueError('typed immutable forecast required')
        old = self._forecasts.get(forecast.forecast_id)
        if old is not None:
            if old == forecast:
                return False
            raise ValueError('forecast identifier already binds another immutable issue')
        if self._clock is not None and forecast.issued_at < self._clock:
            raise ValueError('cannot backdate a new forecast issue')
        known = {r.key: (r.event_start, r.event_end) for r in forecast.requirements}
        observed = {(r.source_id, r.record_id): (r.event_start, r.event_end)
                    for r in self.ledger.revisions}
        for key, interval in known.items():
            if key in self._requirements and self._requirements[key] != interval:
                raise ValueError('source key reused for a different target interval')
            if key in observed and observed[key] != interval:
                raise ValueError('required source interval conflicts with received record')
        self._requirements.update(known)
        self._forecasts[forecast.forecast_id] = forecast
        self._clock = forecast.issued_at
        self._operations.append(('forecast', forecast))
        return True

    def append(self, record):
        if not isinstance(record, EventRevision):
            raise ValueError('typed outcome revision required')
        version = (record.source_id, record.record_id, record.revision)
        if version in self._received:
            if self._received[version] == record:
                return False
            raise ValueError('conflicting reuse of an observed source revision')
        if self._clock is not None and record.received_at < self._clock:
            raise ValueError('cannot backdate a new receipt')
        interval = self._requirements.get((record.source_id, record.record_id))
        if interval is not None and interval != (record.event_start, record.event_end):
            raise ValueError('receipt does not match the declared target interval')
        self.ledger.append(record)
        self._received[version] = record
        self._clock = record.received_at
        self._operations.append(('receipt', record))
        return True

    def snapshot(self, event_cutoff, receipt_cutoff, operation_cutoff=None):
        """Select by clocks and an optional accepted-operation prefix.

        The prefix index disambiguates observations sharing the same integer
        timestamp. Store it to reconstruct a snapshot issued between two such
        operations. Duplicates never advance this index.
        """
        _clock(event_cutoff, 'event_cutoff'); _clock(receipt_cutoff, 'receipt_cutoff')
        if self._clock is None or receipt_cutoff > self._clock:
            raise ValueError('snapshot extends beyond the observed issue/receipt prefix')
        if operation_cutoff is None:
            operation_cutoff = len(self._operations)
        if type(operation_cutoff) is not int or not 0 <= operation_cutoff <= len(self._operations):
            raise ValueError('invalid accepted-operation prefix')
        selected, first, issued = {}, {}, []
        for kind, record in self._operations[:operation_cutoff]:
            if kind == 'forecast':
                if record.issued_at <= receipt_cutoff:
                    issued.append(record)
            elif record.received_at <= receipt_cutoff:
                key = record.source_id, record.record_id
                first.setdefault(key, record.received_at)
                if record.event_end <= event_cutoff:
                    selected[key] = record
        forecasts = tuple(sorted(issued, key=lambda f: f.forecast_id))
        active, pending = [], []
        for forecast in forecasts:
            keys = tuple(r.key for r in forecast.requirements)
            if forecast.target_end > event_cutoff or any(k not in selected for k in keys):
                pending.append(forecast.forecast_id)
                continue
            evidence = tuple(selected[k] for k in keys)
            score = self.scorer(json.loads(forecast.prediction_json),
                                tuple(json.loads(r.payload_json) for r in evidence))
            # EventRevision requires event_end <= received_at. The endpoint
            # requirement therefore makes first maturity >= target_end.
            matured = max([forecast.issued_at] + [first[k] for k in keys])
            active.append(MatureScore(forecast.forecast_id, forecast.identity,
                                     forecast.lane_id, forecast.target_end,
                                     forecast.issued_at, matured, evidence, canonical(score)))
        active.sort(key=lambda r: r.order_key)
        return FeedbackSnapshot(event_cutoff, receipt_cutoff, operation_cutoff, self.ledger.availability_mode,
                                self.scoring_rule_id, forecasts, tuple(active), tuple(pending))
