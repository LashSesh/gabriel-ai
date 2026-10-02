"""Delayed, clipped tail-frequency feedback for frozen causal risk forecasts.

Controller state and projection accounting are exact integers on a rational
lattice. Forecast scaling and scores remain binary64; the controller identity
is an accounting identity, not a conditional coverage or ES calibration claim.
"""
from pathlib import Path
from fractions import Fraction
import hashlib
import json
import math
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_HASH = 'e5723e6f160b37ae552bff2ac11573dfeab7d6d7f4e1f5f4fab3249542285aa9'


def load_protocol():
    raw = (ROOT / 'results/adaptive_risk_protocol.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != PROTOCOL_HASH:
        raise ValueError('adaptive risk protocol changed')
    return json.loads(raw)


def controller_denominator(eta):
    value = Fraction(eta)
    if value < 0:
        raise ValueError('nonnegative rational step required')
    return 40 * value.denominator


def replay_controller(origins, base_q, base_e, rates_column, horizon, eta,
                      lanes=True, beta='1/40', bounds=('-1', '1')):
    """Issue every eligible forecast, processing only currently matured targets.

    Returned update fields are indexed by *issuance*, not feedback date. They
    describe the update performed at origin+horizon using that stored forecast.
    Pending targets have matured_hit=-1 and zero update fields; their issued
    forecasts and controller states are nevertheless present. For horizon lanes,
    preupdate_units equals issued_units. This need not hold for the pooled
    delayed controller, which may be updated by intervening targets.
    """
    eta = Fraction(eta)
    beta = Fraction(beta)
    lower, upper = map(Fraction, bounds)
    if eta < 0 or beta != Fraction(1, 40) or (lower, upper) != (-1, 1):
        raise ValueError('nonnegative eta, beta=1/40 and bounds [-1,1] required')
    if not isinstance(horizon, (int, np.integer)) or isinstance(horizon, bool) or horizon <= 0:
        raise ValueError('positive integer horizon required')
    if not isinstance(lanes, bool):
        raise ValueError('lanes must be Boolean')
    origin = np.asarray(origins)
    if origin.ndim != 1 or len(origin) == 0 or not np.issubdtype(origin.dtype, np.integer):
        raise ValueError('nonempty integer origin vector required')
    if np.any(np.diff(origin) != 1) or origin[0] < 0:
        raise ValueError('contiguous nonnegative origins required')
    q, e, x = map(lambda a: np.asarray(a, dtype=float), (base_q, base_e, rates_column))
    if q.shape != origin.shape or e.shape != origin.shape or x.ndim != 1:
        raise ValueError('forecast or source shape mismatch')
    if origin[-1] != len(x) - 1:
        raise ValueError('origins must cover the source suffix through its last observation')
    if (not np.isfinite(q).all() or not np.isfinite(e).all() or
        not np.isfinite(x).all() or np.any(x <= 0) or np.any(q <= 0) or np.any(q > e)):
        raise ValueError('finite positive rates and 0 < base VaR <= base ES required')
    denominator = controller_denominator(eta)
    if denominator > np.iinfo(np.int64).max // 80 or eta.numerator > np.iinfo(np.int64).max // 80:
        raise ValueError('controller lattice exceeds supported integer storage')
    count = len(origin)
    integer_fields = ['issued_units', 'preupdate_units', 'postupdate_units', 'projection_units']
    out = {name: np.zeros(count, dtype=np.int64) for name in integer_fields}
    out.update(var=np.empty(count), es=np.empty(count),
               matured_hit=np.full(count, -1, dtype=np.int8),
               matured=origin + horizon < len(x), denominator=denominator)
    state = [0] * (horizon if lanes else 1)
    for i, t in enumerate(origin):
        # The oldest issued target is observed exactly at t, before issuing at t.
        j = i - horizon
        if j >= 0:
            slot = int(origin[j] % horizon) if lanes else 0
            loss = float(100 * np.log(x[t] / x[origin[j]]))
            hit = int(loss > out['var'][j])
            before = state[slot]
            trial = before + eta.numerator * (40 * hit - 1)
            after = max(-denominator, min(denominator, trial))
            out['matured_hit'][j] = hit
            out['preupdate_units'][j] = before
            out['postupdate_units'][j] = after
            out['projection_units'][j] = after - trial
            state[slot] = after
        slot = int(t % horizon) if lanes else 0
        out['issued_units'][i] = state[slot]
        scale = math.exp(state[slot] / denominator)
        out['var'][i], out['es'][i] = scale * q[i], scale * e[i]
    if (not np.isfinite(out['var']).all() or not np.isfinite(out['es']).all() or
        np.any(out['var'] <= 0) or np.any(out['var'] > out['es'])):
        raise ValueError('scaled forecast outside scoring domain')
    if not np.array_equal(out['matured_hit'] >= 0, out['matured']):
        raise AssertionError('target maturity alignment failed')
    if lanes and not np.array_equal(out['preupdate_units'][out['matured']],
                                    out['issued_units'][out['matured']]):
        raise AssertionError('lane changed between issuance and its target maturity')
    return out


def risk_strata(base_q, window=250):
    """Predictable split against the previous window, excluding current VaR."""
    q = np.asarray(base_q, dtype=float)
    if q.ndim != 1 or not np.isfinite(q).all() or np.any(q <= 0):
        raise ValueError('positive finite base forecast vector required')
    if not isinstance(window, int) or isinstance(window, bool) or window <= 0:
        raise ValueError('positive integer window required')
    median = np.full(len(q), np.nan)
    labels = np.full(len(q), -1, dtype=np.int8)
    for i in range(1, len(q)):
        median[i] = np.median(q[max(0, i-window):i])
        labels[i] = int(q[i] > median[i])
    return labels, median


def exact_accounting(trace, mask, origins, horizon, eta, lanes=True):
    """Exact projected-update identity, split into contiguous selected blocks.

    Ordinary evaluation periods give one block per lane. A risk-stratum subset
    can be noncontiguous, so boundary changes are summed over its actual blocks;
    subtracting just the first and final state would be invalid for that subset.
    eta=0 has no divided feedback identity and is explicitly excluded.
    """
    eta = Fraction(eta)
    if eta <= 0:
        return None
    origin = np.asarray(origins)
    selected = np.asarray(mask, dtype=bool)
    if selected.shape != origin.shape or np.any(selected & ~trace['matured']):
        raise ValueError('accounting requires a matured-target subset')
    denominator = trace['denominator']
    records = []
    for slot in range(horizon if lanes else 1):
        lane = origin % horizon == slot if lanes else np.ones(len(origin), dtype=bool)
        lane_indices = np.flatnonzero(lane)
        chosen = np.flatnonzero(selected[lane_indices])
        if not len(chosen):
            continue
        breaks = np.r_[0, np.flatnonzero(np.diff(chosen) > 1) + 1, len(chosen)]
        boundary_sum = 0
        for start, end in zip(breaks[:-1], breaks[1:]):
            first, last = lane_indices[chosen[start]], lane_indices[chosen[end-1]]
            boundary_sum += int(trace['postupdate_units'][last]) - int(trace['preupdate_units'][first])
        idx = lane_indices[chosen]
        projection = sum(map(int, trace['projection_units'][idx]))
        hits = sum(map(int, trace['matured_hit'][idx]))
        lhs = Fraction(hits) - Fraction(len(idx), 40)
        rhs = Fraction(boundary_sum - projection, denominator) / eta
        if lhs != rhs:
            raise AssertionError('exact controller accounting failed')
        records.append(dict(lane=slot, n=len(idx), hits=hits,
                            block_count=len(breaks)-1,
                            first_origin_index=int(origin[idx[0]]),
                            last_origin_index=int(origin[idx[-1]]),
                            first_preupdate_units=int(trace['preupdate_units'][idx[0]]),
                            last_postupdate_units=int(trace['postupdate_units'][idx[-1]]),
                            boundary_change_units=boundary_sum,
                            projection_units=projection,
                            denominator=denominator, eta=str(eta),
                            lhs_fraction=str(lhs), rhs_fraction=str(rhs), equal=True))
    return records
