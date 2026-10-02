"""Replay adapters for two unchanged Gabriel research implementations.

Only package-local legacy modules and a fixed scoring rule are loaded.  The
adapters perform no network access or external effects.  Exact JSON is the wire
format; hexadecimal strings retain finite binary64 inputs without suggesting
that the corresponding score calculation is exact real arithmetic.
"""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

from .canonical import canonical, loads


_ROOT = Path(__file__).resolve().parents[1]
_LEGACY = _ROOT / 'reproduction'
_DEPENDENCIES = {
    'finite_observation': (),
    'decision_regions': ('finite_observation',),
    'sequential_contract': ('decision_regions',),
    'maturity_ledger': ('sequential_contract',),
    'ecb_risk': (),
    'replay_adaptive_maturity': ('ecb_risk', 'sequential_contract', 'maturity_ledger'),
}
_MAX_HISTORY = 256
_SCORER = 'binary64-upper-loss-hit-primary-v1'


def _legacy(name):
    """Resolve a fixed local module and reject a same-name foreign module."""
    if name not in _DEPENDENCIES:
        raise ValueError('unsupported legacy module')
    path = (_LEGACY / (name + '.py')).resolve()
    for dependency in _DEPENDENCIES[name]:
        _legacy(dependency)
    old = sys.modules.get(name)
    if old is not None:
        if Path(getattr(old, '__file__', '')).resolve() != path:
            raise ValueError('legacy import identity collision: ' + name)
        return old
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError('legacy module is unavailable: ' + name)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def _copy(value):
    return loads(canonical(value))


def _fields(value, names):
    if type(value) is not dict or set(value) != set(names.split()):
        raise ValueError('adapter payload fields: ' + names)


def _text(value, name, limit=128):
    if type(value) is not str or not value or not value.isascii() or len(value) > limit:
        raise ValueError(name + ' must be a nonempty bounded ASCII string')
    return value


def _integer(value, name, minimum=0, maximum=2**53-1):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(name + ' must be an integer in the declared range')
    return value


def _hex(value, name):
    if type(value) is not str or len(value) > 32:
        raise ValueError(name + ' must be a finite canonical binary64 hex string')
    try:
        result = float.fromhex(value)
    except (ValueError, OverflowError) as exc:
        raise ValueError(name + ' must be a finite canonical binary64 hex string') from exc
    if not math.isfinite(result) or result.hex() != value:
        raise ValueError(name + ' must be a finite canonical binary64 hex string')
    return result


def _fingerprint(adapter, modules):
    files = {str(Path('reproduction') / (name + '.py')):
             hashlib.sha256((_LEGACY / (name + '.py')).read_bytes()).hexdigest()
             for name in sorted(modules)}
    files['gabriel_runtime/adapters.py'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    for name in ('engine.py', 'canonical.py'):
        files['gabriel_runtime/' + name] = hashlib.sha256(
            Path(__file__).with_name(name).read_bytes()).hexdigest()
    return {'adapter': adapter, 'source_sha256': files,
            'max_history_operations': _MAX_HISTORY}


class FiniteObservationAdapter:
    """Bounded exact-catalogue adapter; the planner and session are unchanged."""

    def __init__(self):
        self.legacy = _legacy('finite_observation')

    def fingerprint(self):
        result = _fingerprint('finite-observation/v1', ['finite_observation'])
        result.update(max_rows=32, max_queries=12, query_policy='minimax')
        return result

    def initialize(self, config):
        config = _copy(config)
        _fields(config, 'contract_id query_names costs rows labels weights')
        _text(config['contract_id'], 'contract_id', 512)
        for key in ('query_names', 'costs', 'rows', 'labels', 'weights'):
            if type(config[key]) is not list:
                raise ValueError(key + ' must be a JSON list')
        if not 1 <= len(config['rows']) <= 32 or not 1 <= len(config['query_names']) <= 12:
            raise ValueError('finite catalogue workload cap exceeded')
        for value in config['query_names']:
            _text(value, 'query_name')
        for row in config['rows']:
            if type(row) is not list:
                raise ValueError('catalogue rows must be JSON lists')
            for outcome in row:
                if type(outcome) is not str or not outcome.isascii() or len(outcome) > 256:
                    raise ValueError('bounded canonical outcome strings required')
        # The legacy constructor checks shape, costs, labels and multiplicities.
        catalogue = self._catalogue(config)
        config['weights'] = list(catalogue.weights)
        return {'config': config, 'observations': []}

    def _catalogue(self, config):
        return self.legacy.Catalogue(
            config['contract_id'], tuple(config['query_names']), tuple(config['costs']),
            tuple(tuple(row) for row in config['rows']), tuple(config['labels']),
            tuple(config['weights']))

    def _session(self, state):
        session = self.legacy.Session(self.legacy.Planner(self._catalogue(state['config'])))
        for payload in state['observations']:
            observation = self.legacy.Observation(
                session.planner.c.identity, payload['query'], payload['outcome'],
                payload['source_id'], tuple(payload['event_interval']),
                payload['received_at'], payload['status'], payload['kind'])
            session.ingest(observation, payload['cutoff'])
        return session

    @staticmethod
    def _project(session):
        value = session.planner.value(session.state)
        return {'semantic_profile': 'finite-catalogue/v1',
                'catalogue_digest': session.planner.c.identity,
                'result': session.result(), 'compatible_mask': hex(session.state),
                'next_query': session.planner.choice(session.state, 'minimax'),
                'worst_case_cost': None if math.isinf(value) else value,
                'cost_status': 'infinite' if math.isinf(value) else 'finite',
                'evidence_count': len(session.ledger)}

    def apply(self, state, operation, payload, receipt_at):
        _integer(receipt_at, 'owner receipt time')
        if operation != 'observe':
            raise ValueError('finite adapter supports only observe')
        payload = _copy(payload)
        _fields(payload, 'query outcome source_id event_interval received_at status kind cutoff')
        _text(payload['source_id'], 'source_id')
        _integer(payload['query'], 'query')
        _integer(payload['received_at'], 'received_at')
        _integer(payload['cutoff'], 'cutoff')
        if type(payload['event_interval']) is not list or len(payload['event_interval']) != 2:
            raise ValueError('event_interval must be a two-integer JSON list')
        for clock in payload['event_interval']:
            _integer(clock, 'event_interval')
        if not payload['received_at'] <= payload['cutoff'] <= receipt_at:
            raise ValueError('observation unavailable at requested cutoff or owner receipt')
        if len(state['observations']) >= _MAX_HISTORY:
            raise ValueError('finite history capacity exceeded')
        session = self._session(state)
        observation = self.legacy.Observation(
            session.planner.c.identity, payload['query'], payload['outcome'],
            payload['source_id'], tuple(payload['event_interval']),
            payload['received_at'], payload['status'], payload['kind'])
        accepted = session.ingest(observation, payload['cutoff'])
        candidate = _copy(state)
        # Even a native source-level no-op can advance the native cutoff.
        candidate['observations'].append(payload)
        return candidate, {'accepted': accepted, 'view': self._project(session)}

    def view(self, state):
        return self._project(self._session(state))


class MaturityRiskAdapter:
    """Replay existing endpoint scoring and clipped integer lane controllers."""

    def __init__(self):
        self.legacy = _legacy('maturity_ledger')
        self.contract = _legacy('sequential_contract')
        self.risk = _legacy('replay_adaptive_maturity')

    def fingerprint(self):
        result = _fingerprint('maturity-risk/v1', _DEPENDENCIES)
        result.update(scoring_rule_id=_SCORER, numpy_version=self.risk.np.__version__,
                      controller_denominator=800, controller_bounds=[-800, 800])
        return result

    def initialize(self, config):
        config = _copy(config)
        _fields(config, 'scoring_rule_id availability_mode initial_states')
        if config['scoring_rule_id'] != _SCORER:
            raise ValueError('unsupported risk scoring rule')
        if config['availability_mode'] not in (
                'declared_observed_receipts', 'historical_replay_without_vintages'):
            raise ValueError('unsupported availability convention')
        states = config['initial_states']
        if type(states) is not dict or not 1 <= len(states) <= 16:
            raise ValueError('one to sixteen initial learner lanes required')
        for lane, checkpoint in states.items():
            _text(lane, 'lane_id')
            _fields(checkpoint, 'theta_units updates')
            _integer(checkpoint['theta_units'], 'theta_units', -800, 800)
            _integer(checkpoint['updates'], 'updates')
        return {'config': config, 'operations': [], 'last_query': None}

    def _score(self, prediction, outcomes):
        # Finite endpoints can still overflow on binary64 division.  Preserve
        # the original scorer, then reject its nonfinite computed score.
        with self.risk.np.errstate(over='ignore', under='ignore', divide='ignore', invalid='ignore'):
            score = self.risk.score_outcome(prediction, outcomes)
        _hex(score['realized_log_loss_hex'], 'realized score')
        if type(score['hit']) is not bool:
            raise ValueError('scorer returned a non-Boolean exceedance')
        return score

    def _issue(self, payload, config):
        _fields(payload, 'forecast_id origin target_end issued_at requirements prediction lane_id provenance')
        for field in ('forecast_id', 'lane_id'):
            _text(payload[field], field)
        for field in ('origin', 'target_end', 'issued_at'):
            _integer(payload[field], field)
        if payload['lane_id'] not in config['initial_states']:
            raise ValueError('unbound learner lane')
        _fields(payload['prediction'], 'var_hex es_hex')
        q = _hex(payload['prediction']['var_hex'], 'var_hex')
        e = _hex(payload['prediction']['es_hex'], 'es_hex')
        if not 0 < q <= e:
            raise ValueError('risk predictions require 0 < VaR <= ES')
        if type(payload['provenance']) is not dict:
            raise ValueError('provenance must be a JSON object')
        requirements = payload['requirements']
        if type(requirements) is not list or len(requirements) != 2:
            raise ValueError('risk score requires two ordered target endpoints')
        parsed = []
        for row, clock in zip(requirements, (payload['origin'], payload['target_end'])):
            _fields(row, 'source_id record_id event_start event_end')
            _text(row['source_id'], 'source_id'); _text(row['record_id'], 'record_id')
            _integer(row['event_start'], 'event_start'); _integer(row['event_end'], 'event_end')
            if row['event_start'] != clock or row['event_end'] != clock:
                raise ValueError('risk requirements must name origin and target endpoints in order')
            parsed.append(self.legacy.TargetRequirement(**row))
        return self.legacy.IssuedForecast.create(
            payload['forecast_id'], payload['origin'], payload['target_end'],
            payload['issued_at'], parsed, payload['prediction'],
            payload['lane_id'], payload['provenance'])

    def _outcome(self, payload):
        _fields(payload, 'source_id record_id revision event_interval received_at vintage_id payload')
        for field in ('source_id', 'record_id', 'vintage_id'):
            _text(payload[field], field)
        _integer(payload['revision'], 'revision')
        _integer(payload['received_at'], 'received_at')
        interval = payload['event_interval']
        if type(interval) is not list or len(interval) != 2:
            raise ValueError('event_interval must be a two-integer JSON list')
        for clock in interval:
            _integer(clock, 'event interval')
        if interval[0] != interval[1]:
            raise ValueError('risk outcomes are point endpoint observations')
        _fields(payload['payload'], 'rate_hex')
        if _hex(payload['payload']['rate_hex'], 'rate_hex') <= 0:
            raise ValueError('positive finite endpoint rate required')
        return self.contract.EventRevision.create(
            payload['source_id'], payload['record_id'], payload['revision'],
            tuple(interval), payload['received_at'], payload['vintage_id'], payload['payload'])

    def _ledger(self, state):
        config = state['config']
        ledger = self.legacy.MaturityLedger(
            self._score, config['scoring_rule_id'], config['availability_mode'])
        for entry in state['operations']:
            if entry['op'] == 'issue':
                accepted = ledger.issue(self._issue(entry['payload'], config))
            else:
                accepted = ledger.append(self._outcome(entry['payload']))
            if not accepted:
                raise ValueError('stored maturity history contains a nonaccepted operation')
        return ledger

    def _project(self, ledger, state, query):
        issuance_basis = ('historical_declaration'
                          if state['config']['availability_mode'] == 'historical_replay_without_vintages'
                          else 'declared_owner_receipt')
        if query is None:
            return {'semantic_profile': 'maturity-risk/v1', 'arithmetic': 'binary64',
                    'issuance_basis': issuance_basis,
                    'feedback': None, 'feedback_digest': None,
                    'controller_states': _copy(state['config']['initial_states']),
                    'module_operation_count': len(state['operations'])}
        snapshot = ledger.snapshot(query['event_cutoff'], query['receipt_cutoff'],
                                   query['operation_cutoff'])
        controllers = {
            lane: snapshot.replay(initial, self.risk.reduce_controller, lane)
            for lane, initial in state['config']['initial_states'].items()}
        # Dataclass tuples are converted only here at the documented legacy
        # boundary, not silently by the exact JSON canonicalizer.
        feedback = json.loads(self.contract.canonical(asdict(snapshot)))
        return {'semantic_profile': 'maturity-risk/v1', 'arithmetic': 'binary64',
                'issuance_basis': issuance_basis,
                'feedback': feedback, 'feedback_digest': snapshot.identity,
                'controller_states': controllers,
                'module_operation_count': len(state['operations'])}

    def apply(self, state, operation, payload, receipt_at):
        _integer(receipt_at, 'owner receipt time')
        payload = _copy(payload)
        candidate = _copy(state)
        ledger = self._ledger(state)
        if operation == 'query':
            _fields(payload, 'event_cutoff receipt_cutoff operation_cutoff')
            _integer(payload['event_cutoff'], 'event_cutoff')
            _integer(payload['receipt_cutoff'], 'receipt_cutoff')
            if payload['operation_cutoff'] is not None:
                _integer(payload['operation_cutoff'], 'operation_cutoff')
            if max(payload['event_cutoff'], payload['receipt_cutoff']) > receipt_at:
                raise ValueError('query cutoffs exceed owner receipt time')
            result = self._project(ledger, candidate, payload)
            candidate['last_query'] = payload
            return candidate, result
        if operation not in ('issue', 'outcome'):
            raise ValueError('risk adapter supports issue, outcome and query')
        if operation == 'issue':
            record = self._issue(payload, state['config'])
            if record.issued_at > receipt_at:
                raise ValueError('future forecast issue')
            if (state['config']['availability_mode'] == 'declared_observed_receipts'
                    and record.issued_at != receipt_at):
                raise ValueError('declared live issue must occur at the owner receipt time')
            accepted = ledger.issue(record)
        else:
            record = self._outcome(payload)
            if record.received_at > receipt_at:
                raise ValueError('future endpoint receipt')
            accepted = ledger.append(record)
        if accepted:
            if len(state['operations']) >= _MAX_HISTORY:
                raise ValueError('maturity history capacity exceeded')
            candidate['operations'].append({'op': operation, 'payload': payload})
        query = {'event_cutoff': ledger.clock, 'receipt_cutoff': ledger.clock,
                 'operation_cutoff': None}
        result = self._project(ledger, candidate, query)
        candidate['last_query'] = query
        return candidate, {'accepted': accepted, 'view': result}

    def view(self, state):
        return self._project(self._ledger(state), state, state['last_query'])


def default_registry():
    return {'finite-observation/v1': FiniteObservationAdapter(),
            'maturity-risk/v1': MaturityRiskAdapter()}
