"""Bounded raw-price forecasting with immutable issues and correction replay.

The ordinary, positive-forecast path reproduces the existing six historical
simulation experts, two severity experts and cumulative transformed pool.  A
revision changes current feedback, evaluated at the *stored* issued banks and
weights.  Previously issued forecasts and proposals are never reconstructed.
"""
from __future__ import annotations

from fractions import Fraction
import hashlib
import importlib.util
import math
from pathlib import Path
import sys

import numpy as np

from .canonical import canonical, loads, digest
from .adapters import default_registry, _legacy, _hex, _integer, _text, _fields


ROOT = Path(__file__).resolve().parents[1]
MAX_SOURCE = 1024
MAX_REVISIONS = 2048
MAX_ISSUES = 512
BETA = 1 / 40
STEP_SCALE = .1
HALF_LIVES = (125, 500)
DECAYS = tuple(2.0 ** (-1.0 / h) for h in HALF_LIVES)
INITIAL_RATIO = 1.5
RATIO_CAP = 20.0


def _module(name):
    if name not in ('severity_risk', 'aggregate_risk'):
        raise ValueError('unsupported stream dependency')
    path = (ROOT / 'reproduction' / (name + '.py')).resolve()
    if name in sys.modules:
        module = sys.modules[name]
        if Path(getattr(module, '__file__', '')).resolve() != path:
            raise ValueError('stream dependency identity collision')
        return module
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError('stream dependency unavailable')
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


def _fraction(value, name, *, positive=False):
    if type(value) is not str or not 1 <= len(value) <= 128:
        raise ValueError(name + ' requires a bounded canonical rational string')
    try:
        result = Fraction(value)
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError(name + ' requires a canonical rational string') from exc
    if str(result) != value or result < 0 or (positive and result == 0):
        raise ValueError(name + ' requires a canonical rational in its declared domain')
    return result


def _finite(value, name):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError('nonfinite ' + name)
    return number


def _hexes(values):
    return [_finite(value, 'serialized numerical state').hex() for value in values]


def _protocol(horizon):
    return {'variance_initial_observations': 60,
            'variance_halflives_observed_intervals': [20, 120],
            'window': 250, 'fast_weights': ['0', '1/4', '1/2', '3/4', '1'],
            'horizons_observed_intervals': [horizon], 'alpha': '39/40'}


class StreamRiskAdapter:
    """Fixed, receipt-driven financial adapter; no external execution."""

    def __init__(self):
        self.ecb = _legacy('ecb_risk')
        self.aggregate = _module('aggregate_risk')
        # Bind the existing severity implementation whose transition formula
        # is used on immutable issued quantiles in the correction-aware fold.
        self.severity = _module('severity_risk')

    def fingerprint(self):
        files = ['gabriel_runtime/stream.py', 'gabriel_runtime/adapters.py',
                 'gabriel_runtime/engine.py', 'gabriel_runtime/canonical.py',
                 'reproduction/ecb_risk.py', 'reproduction/aggregate_risk.py',
                 'reproduction/severity_risk.py']
        import scipy
        return {'adapter': 'stream-risk/v1',
                'source_sha256': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                                  for name in files},
                'numpy_version': np.__version__, 'scipy_version': scipy.__version__,
                'forecast_parameters': _protocol(1) | {'horizons_observed_intervals': [1, 5]},
                'expert_order': list(self.aggregate.EXPERTS),
                'severity_half_lives': list(HALF_LIVES),
                'initial_ratio_hex': INITIAL_RATIO.hex(), 'ratio_cap_hex': RATIO_CAP.hex(),
                'step_scale_hex': STEP_SCALE.hex(),
                'max_source': MAX_SOURCE, 'max_revisions': MAX_REVISIONS,
                'max_issues': MAX_ISSUES,
                'correction': 'replay_feedback_at_immutable_issued_banks_and_weights'}

    def initialize(self, config):
        config = _copy(config)
        _fields(config, 'source_id horizon risk_budget unit_exposure max_units')
        _text(config['source_id'], 'source_id')
        if type(config['horizon']) is not int or config['horizon'] not in (1, 5):
            raise ValueError('stream horizon must be one or five observed intervals')
        _fraction(config['risk_budget'], 'risk_budget')
        _fraction(config['unit_exposure'], 'unit_exposure', positive=True)
        _integer(config['max_units'], 'max_units', maximum=1000000)
        return {'config': config, 'receipts': [], 'issued': [], 'maturity': {},
                'last_status': 'empty', 'last_reason': 'no_source_records'}

    @staticmethod
    def _latest(state):
        latest = {}
        for record in state['receipts']:
            latest[record['index']] = record
        return [latest[index] for index in range(len(latest))]

    @staticmethod
    def _loss(left, right):
        with np.errstate(over='ignore', under='ignore', divide='ignore', invalid='ignore'):
            value = 100 * np.log(np.float64(right) / np.float64(left))
        return _finite(value, 'endpoint log loss')

    def _learner(self, state, latest):
        """Replay revised feedback without reissuing historical decisions."""
        h = state['config']['horizon']
        k = len(self.aggregate.EXPERTS)
        weights = np.full((h, k), 1 / k)
        accumulators = np.zeros(h)
        raw = [INITIAL_RATIO, INITIAL_RATIO]
        ordered = [(state['maturity'][issue['forecast_id']], issue)
                   for issue in state['issued'] if issue['forecast_id'] in state['maturity']]
        ordered.sort(key=lambda pair: (pair[0]['first_matured_at'],
                                      pair[0]['target_index'], pair[0]['issue_position']))
        feedback = []
        for maturity, issue in ordered:
            origin, target = issue['origin_index'], issue['target_index']
            left = float.fromhex(latest[origin]['rate_hex'])
            right = float.fromhex(latest[target]['rate_hex'])
            loss = self._loss(left, right)
            fast_q = float.fromhex(issue['fast_q_hex'])
            response = 1.0 + max(float(loss - fast_q), 0.0) / (BETA * fast_q)
            _finite(response, 'severity response')
            for j, decay in enumerate(DECAYS):
                raw[j] = _finite(decay * raw[j] + (1.0 - decay) * response,
                                 'severity accumulator')
            q = np.array([float.fromhex(value) for value in issue['expert_var_hex']])
            e = np.array([float.fromhex(value) for value in issue['expert_es_hex']])
            issued_weights = np.array([float.fromhex(value) for value in issue['issued_weights_hex']])
            with np.errstate(over='ignore', under='ignore', divide='ignore', invalid='ignore'):
                _, gradient = self.aggregate.transformed_score_gradient(
                    q[None, :], e[None, :], np.array([loss]), issued_weights)
                centered = gradient - gradient.mean()
                norm = float(centered @ centered)
            if not np.isfinite(gradient).all() or not np.isfinite(centered).all():
                raise ValueError('nonfinite feedback gradient')
            _finite(norm, 'squared gradient norm')
            lane = origin % h
            before_weights = weights[lane].copy()
            before = float(accumulators[lane])
            after = _finite(before + norm, 'cumulative gradient energy')
            step = STEP_SCALE / math.sqrt(after) if after > 0 else 0.0
            updated = self.aggregate.project_simplex(before_weights - step * centered)
            if not np.isfinite(updated).all():
                raise ValueError('nonfinite projected learner state')
            stale = float(np.linalg.norm(before_weights - issued_weights))
            feedback.append({'forecast_id': issue['forecast_id'],
                             'first_matured_at': maturity['first_matured_at'],
                             'target_index': target, 'lane': lane, 'loss_hex': loss.hex(),
                             'target_event_at': latest[target]['event_at'],
                             'target_after_issue': latest[target]['event_at'] > issue['issued_at'],
                             'gradient_hex': _hexes(gradient),
                             'centered_gradient_hex': _hexes(centered),
                             'gradient_norm_squared_hex': norm.hex(), 'step_hex': step.hex(),
                             'pre_weights_hex': _hexes(before_weights),
                             'post_weights_hex': _hexes(updated),
                             'accumulator_before_hex': before.hex(),
                             'accumulator_after_hex': after.hex(),
                             'staleness_l2_hex': _finite(stale, 'issued-state discrepancy').hex()})
            weights[lane] = updated
            accumulators[lane] = after
        return {'severity_raw_ratio_hex': _hexes(raw),
                'lane_weights_hex': [_hexes(row) for row in weights],
                'lane_accumulators_hex': _hexes(accumulators),
                'active_feedback': feedback}

    @staticmethod
    def _proposal(config, es):
        exposure = _fraction(config['unit_exposure'], 'unit_exposure', positive=True)
        budget = _fraction(config['risk_budget'], 'risk_budget')
        exact_es = Fraction(es)
        per_unit = exposure * exact_es / 100
        if per_unit <= 0:
            raise ValueError('positive model proxy per unit required')
        units = min(config['max_units'], budget // per_unit)
        proxy = units * per_unit
        next_proxy = (units + 1) * per_unit
        return {'kind': 'read_only_log_loss_proxy', 'units': units,
                'unit_exposure': str(exposure), 'risk_budget': str(budget),
                'es_exact': str(exact_es), 'proxy_loss': str(proxy),
                'next_unit_proxy_loss': str(next_proxy), 'max_units': config['max_units'],
                'budget_satisfied': proxy <= budget,
                'maximum_feasible': units == config['max_units'] or next_proxy > budget}

    def _forecast(self, state, latest, learner, owner_at):
        h = state['config']['horizon']
        origin = len(latest) - 1
        if origin < 60 + h + 250 - 1:
            return None, 'warmup'
        if len(state['issued']) >= MAX_ISSUES:
            return None, 'issuance_capacity'
        rates = np.array([float.fromhex(row['rate_hex']) for row in latest])[:, None]
        protocol = _protocol(h)
        with np.errstate(over='ignore', under='ignore', divide='ignore', invalid='ignore'):
            _, variance = self.ecb.fading_variances(rates, 60, (20, 120))
        if not np.isfinite(variance[60:]).all():
            raise ValueError('nonfinite variance state')
        if np.any(variance[60:] <= 0):
            return None, 'zero_variance_history'
        with np.errstate(over='ignore', under='ignore', divide='ignore', invalid='ignore'):
            _, candidates = self.ecb.forecast_candidates(rates, protocol)
        origins, q_base, e_base = candidates[0, h]
        if int(origins[-1]) != origin:
            raise ValueError('source prefix did not produce the current origin')
        q0, e0 = q_base[-1], e_base[-1]
        if not np.isfinite(q0).all() or not np.isfinite(e0).all():
            raise ValueError('nonfinite base expert forecast')
        if np.any(q0 <= 0) or np.any(e0 < q0):
            return None, 'nonpositive_or_unordered_base_forecast'
        raw = [float.fromhex(x) for x in learner['severity_raw_ratio_hex']]
        q = np.r_[q0, q0[5], q0[5]]
        e = np.r_[e0, q0[5] * min(RATIO_CAP, max(1.0, raw[0])),
                  q0[5] * min(RATIO_CAP, max(1.0, raw[1]))]
        weights = np.array([float.fromhex(value) for value in learner['lane_weights_hex'][origin % h]])
        with np.errstate(over='ignore', under='ignore', divide='ignore', invalid='ignore'):
            var, es = self.aggregate.transformed_mix(q[None, :], e[None, :], weights)
        var, es = _finite(var[0], 'pooled VaR'), _finite(es[0], 'pooled ES')
        if not 0 < var <= es:
            raise ValueError('pooled forecast outside positive ordered domain')
        issue = {'forecast_id': state['config']['source_id'] + ':h' + str(h) + ':i' + str(origin),
                 'prediction_basis': 'next_unreceived_observation',
                 'origin_index': origin, 'target_index': origin + h,
                 'origin_event_at': latest[-1]['event_at'], 'issued_at': owner_at,
                 'receipt_cutoff': latest[-1]['received_at'],
                 'source_digest': digest({'source_id': state['config']['source_id'], 'observations': latest}),
                 'expert_order': list(self.aggregate.EXPERTS),
                 'expert_var_hex': _hexes(q), 'expert_es_hex': _hexes(e),
                 'issued_weights_hex': _hexes(weights),
                 'issued_accumulator_hex': learner['lane_accumulators_hex'][origin % h],
                 'fast_q_hex': float(q0[5]).hex(),
                 'severity_raw_ratio_hex': list(learner['severity_raw_ratio_hex']),
                 'var_hex': var.hex(), 'es_hex': es.hex(),
                 'proposal': self._proposal(state['config'], es)}
        issue['digest'] = digest(issue)
        return issue, None

    def apply(self, state, operation, payload, receipt_at):
        _integer(receipt_at, 'owner operation time')
        if operation != 'record':
            raise ValueError('stream adapter supports only record')
        payload = _copy(payload)
        _fields(payload, 'index event_at received_at revision rate_hex')
        _integer(payload['index'], 'index', maximum=MAX_SOURCE - 1)
        _integer(payload['revision'], 'revision', maximum=MAX_REVISIONS - 1)
        _integer(payload['event_at'], 'event_at')
        _integer(payload['received_at'], 'received_at')
        if _hex(payload['rate_hex'], 'rate_hex') <= 0:
            raise ValueError('positive rate required')
        if not payload['event_at'] <= payload['received_at'] <= receipt_at:
            raise ValueError('event, declared receipt and owner availability ordering')
        for old in state['receipts']:
            if (old['index'], old['revision']) == (payload['index'], payload['revision']):
                if canonical(old) != canonical(payload):
                    raise ValueError('conflicting source revision reuse')
                return _copy(state), {'accepted': False, 'issued': None, 'view': self.view(state)}
        if len(state['receipts']) >= MAX_REVISIONS:
            raise ValueError('source revision capacity exceeded')
        if state['receipts'] and payload['received_at'] < state['receipts'][-1]['received_at']:
            raise ValueError('backdated new source receipt')
        latest = self._latest(state)
        index = payload['index']
        is_new = index == len(latest)
        if is_new:
            if payload['revision'] != 0:
                raise ValueError('first source revision must be zero')
            if latest and payload['event_at'] <= latest[-1]['event_at']:
                raise ValueError('new source event time must increase')
        elif index < len(latest):
            previous = latest[index]
            if (payload['revision'] != previous['revision'] + 1
                    or payload['event_at'] != previous['event_at']):
                raise ValueError('source correction lineage or event time mismatch')
        else:
            raise ValueError('new source slots must be contiguous')
        candidate = _copy(state)
        candidate['receipts'].append(payload)
        latest = self._latest(candidate)
        # Check adjacent return arithmetic even while the model is warming up.
        # A revision can affect the interval immediately before and after it.
        for left_index in (index - 1, index):
            if 0 <= left_index < len(latest) - 1:
                self._loss(float.fromhex(latest[left_index]['rate_hex']),
                           float.fromhex(latest[left_index + 1]['rate_hex']))
        for position, issue in enumerate(candidate['issued']):
            if issue['forecast_id'] not in candidate['maturity'] and issue['target_index'] < len(latest):
                candidate['maturity'][issue['forecast_id']] = {
                    # Actual availability in this owner, not an authenticated
                    # external publication timestamp or a source-index clock.
                    'first_matured_at': receipt_at,
                    'target_index': issue['target_index'], 'issue_position': position}
        learner = self._learner(candidate, latest)
        issue = None
        if is_new:
            issue, reason = self._forecast(candidate, latest, learner, receipt_at)
            candidate['last_status'] = 'issued' if issue is not None else 'unavailable'
            candidate['last_reason'] = reason
            if issue is not None:
                candidate['issued'].append(issue)
        else:
            candidate['last_status'] = 'revised'
            candidate['last_reason'] = 'current_learner_replayed'
        result = {'accepted': True, 'issued': _copy(issue),
                  'view': self._view(candidate, latest, learner)}
        # Canonicalize candidate/result here as well as at the owner boundary.
        # No candidate is returned if a derived value leaves the wire domain.
        return _copy(candidate), _copy(result)

    @staticmethod
    def _view(state, latest, learner):
        return {'semantic_profile': 'stream-risk/v1', 'arithmetic': 'binary64',
                'prediction_basis': 'next_unreceived_observation',
                'source_id': state['config']['source_id'], 'horizon': state['config']['horizon'],
                'source_count': len(latest), 'revision_count': len(state['receipts']),
                'issued_count': len(state['issued']),
                'pending_count': len(state['issued']) - len(state['maturity']),
                'status': state['last_status'], 'reason': state['last_reason'],
                'last_issued_digest': state['issued'][-1]['digest'] if state['issued'] else None,
                'learner': learner}

    def view(self, state):
        latest = self._latest(state)
        return self._view(state, latest, self._learner(state, latest))


def extended_registry():
    return dict(default_registry(), **{'stream-risk/v1': StreamRiskAdapter()})
