"""Binary64 same-position correction of a discounted sufficient statistic.

The identity is exact in real arithmetic for fixed decay, initial checkpoint,
number/order of updates and all other stored scores. This implementation uses
ordinary floating point. It changes no originally issued quantile or forecast.
"""
import math


def correct_discounted_score(final_state, decay, update_count, position,
                             old_score, new_score):
    """Replace one score at one-based position; retain every kernel weight.

    Uses one power evaluation and a fixed number of scalar arithmetic operations,
    independent of the number of updates. This is not a constant bit-complexity
    or wall-clock guarantee, nor a directed-rounding arithmetic certificate.
    """
    if type(update_count) is not int or type(position) is not int or not 1 <= position <= update_count:
        raise ValueError('valid one-based update position and positive count required')
    try:
        state, decay, old, new = map(float, (final_state,decay,old_score,new_score))
    except (TypeError,ValueError,OverflowError) as exc:
        raise ValueError('finite scalar state, decay and scores required') from exc
    if not all(math.isfinite(x) for x in (state,decay,old,new)) or not 0 < decay < 1:
        raise ValueError('finite state/scores and decay strictly between zero and one required')
    weight = (1.0-decay) * decay ** (update_count-position)
    corrected = state + weight * (new-old)
    if not math.isfinite(corrected):
        raise ValueError('corrected state overflowed binary64')
    return corrected


def severity_readout(raw_state, cap=20.0):
    """Cap only the emitted ratio, leaving the raw statistic unchanged."""
    raw, cap = float(raw_state), float(cap)
    if not math.isfinite(raw) or not math.isfinite(cap) or cap < 1:
        raise ValueError('finite raw statistic and cap at least one required')
    return {'raw_state':raw,'ratio':min(cap,max(1.0,raw)),
            'lower_cap_active':raw < 1.0,'upper_cap_active':raw > cap}
