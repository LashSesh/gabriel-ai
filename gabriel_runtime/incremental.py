"""Derived, bounded execution caches for the unchanged stream-risk/v1 contract.

Caches are optional acceleration, not accepted evidence or persisted state.  The
baseline stream adapter defines the public transition; only numerical evaluation
work is reused.  Source/issue dependency keys inspect actual fields, not a caller
supplied digest.  Numerical recurrences retain the baseline binary64 order.
"""
from __future__ import annotations

import hashlib
import math
from fractions import Fraction

import numpy as np

from .canonical import canonical
from .adapters import default_registry
from .stream import (StreamRiskAdapter, ROOT, MAX_SOURCE, MAX_ISSUES, BETA,
                     STEP_SCALE, DECAYS, INITIAL_RATIO, _copy, _finite, _hexes)


class _CurrentOriginECB:
    """Private executor for calls made by the inherited _forecast method.

    This proxy is not a replacement public forecast_candidates API: its bank
    contains only the current origin.  The inherited transition consumes only
    that final row.  Other attributes retain their reference implementation.
    """

    def __init__(self, owner, reference):
        self.owner = owner
        self.reference = reference

    def __getattr__(self, name):
        return getattr(self.reference, name)

    def fading_variances(self, rates, initial=60, halflives=(20, 120)):
        x = np.asarray(rates, dtype=float)
        # The cache is bounded to the actual scalar stream profile.  Calls
        # outside that profile retain the reference function's behavior.
        if (x.ndim != 2 or x.shape[1] != 1 or len(x) > MAX_SOURCE
                or initial != 60 or tuple(halflives) != (20, 120)):
            return self.reference.fading_variances(rates, initial, halflives)
        if len(x) <= initial or np.any(x <= 0) or not np.isfinite(x).all():
            raise ValueError('positive finite rate matrix required')
        tokens = tuple(float(v).hex() for v in x[:, 0])
        old = self.owner._variance_cache
        common = 0
        if old is not None:
            for a, b in zip(tokens, old['tokens']):
                if a != b:
                    break
                common += 1
        losses = np.full_like(x, np.nan)
        states = np.full((len(x), len(halflives), x.shape[1]), np.nan)
        if common:
            losses[:common] = old['losses'][:common]
        first_loss = max(1, common)
        losses[first_loss:] = 100 * np.log(x[first_loss:] / x[first_loss - 1:-1])
        if common > initial:
            states[:common] = old['states'][:common]
            first_update = common
            self.owner._metrics['cache_reuses'] += 1
        else:
            if old is not None:
                self.owner._metrics['cache_resets'] += 1
            states[initial] = np.mean(losses[1:initial + 1] ** 2, axis=0)[None, :]
            self.owner._metrics['variance_steps'] += 1
            first_update = initial + 1
        decay = 2. ** (-1 / np.asarray(halflives, dtype=float))
        for t in range(first_update, len(x)):
            states[t] = decay[:, None] * states[t - 1] + (1 - decay[:, None]) * losses[t] ** 2
            self.owner._metrics['variance_steps'] += 1
        # Cached arrays are never the caller-visible returned arrays.
        self.owner._variance_cache = {
            'tokens': tokens, 'losses': losses.copy(), 'states': states.copy()}
        return losses, states

    def forecast_candidates(self, rates, protocol):
        x = np.asarray(rates, dtype=float)
        initial = protocol['variance_initial_observations']
        _, states = self.fading_variances(
            x, initial, protocol['variance_halflives_observed_intervals'])
        wsize = protocol['window']
        weights = list(map(lambda z: float(Fraction(z)), protocol['fast_weights']))
        output = {}
        for c in range(x.shape[1]):
            for h in protocol['horizons_observed_intervals']:
                first = initial + h + wsize - 1
                if len(x) <= first:
                    continue
                ends = np.array([len(x) - 1], dtype=int)
                y = np.full(len(x), np.nan)
                y[h:] = 100 * np.log(x[h:, c] / x[:-h, c])
                # The union of every reference historical scenario row is
                # y[initial+h:].  Retain its validity check even though only
                # the current quantile/mean row is evaluated.
                if not np.isfinite(y[initial + h:]).all():
                    raise ValueError('finite scenario rows required')
                block = np.lib.stride_tricks.sliding_window_view(y, wsize)[ends - wsize + 1]
                qs, ess = [], []
                q, e = self.reference.tail(block, protocol['alpha'])
                self.owner._metrics['forecast_scenario_rows'] += len(block)
                qs.append(q)
                ess.append(e)
                for w in weights:
                    var = w * states[:, 0, c] + (1 - w) * states[:, 1, c]
                    # Preserve the full-history guard, including mixtures;
                    # checking only the last scenario window changes semantics.
                    if np.any(var[initial:] <= 0):
                        raise ValueError('positive variance required')
                    z = np.full(len(x), np.nan)
                    z[initial + h:] = y[initial + h:] / np.sqrt(h * var[initial:-h])
                    if not np.isfinite(z[initial + h:]).all():
                        raise ValueError('finite scenario rows required')
                    zblock = np.lib.stride_tricks.sliding_window_view(z, wsize)[ends - wsize + 1]
                    q, e = self.reference.tail(zblock, protocol['alpha'])
                    self.owner._metrics['forecast_scenario_rows'] += len(zblock)
                    scale = np.sqrt(h * var[ends])
                    qs.append(q * scale)
                    ess.append(e * scale)
                output[c, h] = (ends, np.stack(qs, axis=1), np.stack(ess, axis=1))
        return states, output


class IncrementalStreamRiskAdapter(StreamRiskAdapter):
    """Same public transition, with one bounded cache for each numerical fold.

    The execution fingerprint intentionally differs from StreamRiskAdapter.
    A database must therefore be opened with its explicitly selected profile.
    """

    COUNTERS = ('variance_steps', 'forecast_scenario_rows',
                'gradient_evaluations', 'projections', 'severity_steps',
                'cache_resets', 'cache_reuses')

    def __init__(self):
        super().__init__()
        self._ecb_reference = self.ecb
        self.ecb = _CurrentOriginECB(self, self._ecb_reference)
        self._learner_cache = None
        self._variance_cache = None
        self.reset_metrics()

    def fingerprint(self):
        value = super().fingerprint()
        value['execution'] = 'bounded-incremental/v1'
        value['source_sha256']['gabriel_runtime/incremental.py'] = hashlib.sha256(
            (ROOT / 'gabriel_runtime/incremental.py').read_bytes()).hexdigest()
        return value

    def reset_metrics(self):
        """Reset diagnostics without changing or invalidating numerical caches."""
        self._metrics = {name: 0 for name in self.COUNTERS}

    def metrics(self):
        """Return cumulative work counts; they are not protocol state."""
        return dict(self._metrics)

    def clear_cache(self):
        """Discard all derived numerical work without changing public state."""
        if self._learner_cache is not None or self._variance_cache is not None:
            self._metrics['cache_resets'] += 1
        self._learner_cache = None
        self._variance_cache = None

    @staticmethod
    def _feedback_token(maturity, issue, latest):
        # Cover every consumed field by its actual value, including issue time,
        # indexes, bank, issuance weights, and endpoint event time.  Including
        # additional fields is deliberately conservative, never authoritative.
        return canonical({'maturity': maturity, 'issue': issue,
                          'left': latest[issue['origin_index']],
                          'right': latest[issue['target_index']]})

    def _learner(self, state, latest):
        h = state['config']['horizon']
        k = len(self.aggregate.EXPERTS)
        ordered = [(state['maturity'][issue['forecast_id']], issue)
                   for issue in state['issued'] if issue['forecast_id'] in state['maturity']]
        ordered.sort(key=lambda pair: (pair[0]['first_matured_at'],
                                      pair[0]['target_index'], pair[0]['issue_position']))
        # Public owner-reachable states obey these limits.  A direct diagnostic
        # call with an oversized state uses the baseline without caching it.
        if len(ordered) > MAX_ISSUES or len(latest) > MAX_SOURCE:
            return super()._learner(state, latest)
        context = canonical(state['config'])
        tokens = [self._feedback_token(m, issue, latest) for m, issue in ordered]
        old = self._learner_cache
        compatible = old is not None and old['context'] == context
        common = 0
        if compatible:
            for a, b in zip(tokens, old['tokens']):
                if a != b:
                    break
                common += 1
        if common:
            checkpoint = old['checkpoints'][common - 1]
            weights = checkpoint['weights'].copy()
            accumulators = checkpoint['accumulators'].copy()
            raw = list(checkpoint['raw'])
            feedback = old['feedback'][:common]
            contributions = old['contributions'][:common]
            checkpoints = old['checkpoints'][:common]
        else:
            weights = np.full((h, k), 1 / k)
            accumulators = np.zeros(h)
            raw = [INITIAL_RATIO, INITIAL_RATIO]
            feedback, contributions, checkpoints = [], [], []
        if old is not None and not common and (old['tokens'] or not compatible):
            self._metrics['cache_resets'] += 1
        reused = common > 0
        dirty_lanes = set()
        for position in range(common, len(ordered)):
            maturity, issue = ordered[position]
            origin, target = issue['origin_index'], issue['target_index']
            lane = origin % h
            same = (compatible and position < len(old['tokens'])
                    and tokens[position] == old['tokens'][position])
            if same:
                contribution = old['contributions'][position]
                loss = contribution['loss']
                response = contribution['response']
                gradient = contribution['gradient']
                centered = contribution['centered']
                norm = contribution['norm']
                issued_weights = contribution['issued_weights']
                reused = True
            else:
                dirty_lanes.add(lane)
                if compatible and position < len(old['feedback']):
                    dirty_lanes.add(old['feedback'][position]['lane'])
                left = float.fromhex(latest[origin]['rate_hex'])
                right = float.fromhex(latest[target]['rate_hex'])
                loss = self._loss(left, right)
                fast_q = float.fromhex(issue['fast_q_hex'])
                response = 1.0 + max(float(loss - fast_q), 0.0) / (BETA * fast_q)
                _finite(response, 'severity response')
                # Preserve the baseline order: severity validation occurs
                # before gradient validation in this feedback round.
                gradient = centered = norm = issued_weights = None
            for j, decay in enumerate(DECAYS):
                raw[j] = _finite(decay * raw[j] + (1.0 - decay) * response,
                                 'severity accumulator')
            self._metrics['severity_steps'] += 1
            if not same:
                q = np.array([float.fromhex(value) for value in issue['expert_var_hex']])
                e = np.array([float.fromhex(value) for value in issue['expert_es_hex']])
                issued_weights = np.array([float.fromhex(value) for value in issue['issued_weights_hex']])
                with np.errstate(over='ignore', under='ignore', divide='ignore', invalid='ignore'):
                    _, gradient = self.aggregate.transformed_score_gradient(
                        q[None, :], e[None, :], np.array([loss]), issued_weights)
                    self._metrics['gradient_evaluations'] += 1
                    centered = gradient - gradient.mean()
                    norm = float(centered @ centered)
                if not np.isfinite(gradient).all() or not np.isfinite(centered).all():
                    raise ValueError('nonfinite feedback gradient')
                _finite(norm, 'squared gradient norm')
                contribution = {'loss': loss, 'response': response,
                                'gradient': gradient.copy(), 'centered': centered.copy(),
                                'norm': norm, 'issued_weights': issued_weights.copy()}
            if same and lane not in dirty_lanes:
                # No changed predecessor in this lane: the checkpoint and
                # diagnostic row are identical even if other lanes changed.
                row = old['feedback'][position]
                weights[lane] = old['checkpoints'][position]['weights'][lane]
                accumulators[lane] = old['checkpoints'][position]['accumulators'][lane]
            else:
                before_weights = weights[lane].copy()
                before = float(accumulators[lane])
                after = _finite(before + norm, 'cumulative gradient energy')
                step = STEP_SCALE / math.sqrt(after) if after > 0 else 0.0
                updated = self.aggregate.project_simplex(before_weights - step * centered)
                self._metrics['projections'] += 1
                if not np.isfinite(updated).all():
                    raise ValueError('nonfinite projected learner state')
                stale = float(np.linalg.norm(before_weights - issued_weights))
                row = {'forecast_id': issue['forecast_id'],
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
                       'staleness_l2_hex': _finite(stale, 'issued-state discrepancy').hex()}
                weights[lane] = updated
                accumulators[lane] = after
            feedback.append(row)
            contributions.append(contribution)
            checkpoints.append({'weights': weights.copy(),
                                'accumulators': accumulators.copy(), 'raw': tuple(raw)})
        if reused:
            self._metrics['cache_reuses'] += 1
        result = {'severity_raw_ratio_hex': _hexes(raw),
                  'lane_weights_hex': [_hexes(row) for row in weights],
                  'lane_accumulators_hex': _hexes(accumulators),
                  'active_feedback': feedback}
        self._learner_cache = {'context': context, 'tokens': tokens,
                               'feedback': feedback, 'contributions': contributions,
                               'checkpoints': checkpoints}
        # Returned mutable views cannot poison derived cache entries.
        return _copy(result)


def incremental_registry():
    """Explicit alternate execution registry; never a migration by guessing."""
    return dict(default_registry(), **{'stream-risk/v1': IncrementalStreamRiskAdapter()})
