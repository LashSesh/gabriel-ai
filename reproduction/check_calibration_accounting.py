"""Exact finite-path accounting and illustrative calibration counterexamples.

This standard-library-only check derives the clipped recurrence independently
with Fraction arithmetic. It verifies algebraic statements and constructed
examples, not the empirical risk implementation or true conditional coverage.
Exponential scales and the displayed ES residual are binary64 illustrations;
the corresponding hit bits are also justified analytically by their margins.
"""
from fractions import Fraction as F
from itertools import product
from pathlib import Path
import json
import math

ROOT = Path(__file__).resolve().parents[1]
LOWER, UPPER, BETA = F(-1), F(1), F(1, 40)


def step(theta, hit, eta):
    if hit not in (0, 1) or not LOWER <= theta <= UPPER or eta < 0:
        raise ValueError('bounded state, binary hit and nonnegative rate required')
    proposal = theta + eta * (hit - BETA)
    after = min(UPPER, max(LOWER, proposal))
    return after, after - proposal


def path(hits, eta, initial=F(0)):
    states, projection = [initial], []
    for hit in hits:
        after, debit = step(states[-1], hit, eta)
        states.append(after)
        projection.append(debit)
    return states, projection


def check_window(hits, states, projection, eta, start, end):
    if eta <= 0 or end <= start:
        raise ValueError('accounting identity needs a positive rate and nonempty window')
    count = end - start
    hit_sum = sum(hits[start:end])
    p_sum = sum(projection[start:end], F(0))
    discrepancy = F(hit_sum) - count * BETA
    assert discrepancy == (states[end] - states[start] - p_sum) / eta
    upper_debit = sum((max(-p, F(0)) for p in projection[start:end]), F(0))
    lower_debit = sum((max(p, F(0)) for p in projection[start:end]), F(0))
    frequency = F(hit_sum, count)
    lower = BETA + (LOWER - states[start] - lower_debit) / (eta * count)
    upper = BETA + (UPPER - states[start] + upper_debit) / (eta * count)
    assert lower <= frequency <= upper
    symmetric = (max(UPPER - states[start], states[start] - LOWER)
                 + sum(map(abs, projection[start:end]), F(0))) / (eta * count)
    assert abs(frequency - BETA) <= symmetric
    return upper_debit, lower_debit


def main():
    counts = dict(exhaustive_paths=0, exact_updates=0, finite_windows=0,
                  upper_envelope_cases=0, two_sided_envelope_cases=0,
                  rejected_accounting_domains=0)
    rates = (F(1, 100), F(1, 20), F(1, 5), F(3))
    initials = (F(-1), F(-39, 40), F(0), F(3, 4), F(1))
    # All 2^8 bit strings; all windows use the actual start state, including
    # saturated and nonzero-start cases. Rate 3 is an algebra stress case,
    # outside the empirical rate catalogue but valid for the identity.
    for eta, initial, hits in product(rates, initials, product((0, 1), repeat=8)):
        states, projection = path(hits, eta, initial)
        counts['exhaustive_paths'] += 1
        counts['exact_updates'] += len(hits)
        for start in range(len(hits)):
            for end in range(start + 1, len(hits) + 1):
                check_window(hits, states, projection, eta, start, end)
                counts['finite_windows'] += 1

    eta = F(1, 20)
    # An interior reporting window is not a fresh zero-initialized learner.
    hits = (1, 0, 1, 0, 0, 1)
    states, projection = path(hits, eta)
    start, end = 1, 5
    actual = F(sum(hits[start:end])) - (end - start) * BETA
    correct = (states[end] - states[start] - sum(projection[start:end], F(0))) / eta
    wrong_zero_restart = (states[end] - sum(projection[start:end], F(0))) / eta
    assert actual == correct and wrong_zero_restart != correct

    # A noncontiguous stratum has multiple state-boundary segments.
    selected = (0, 2)
    selected_lhs = sum((F(hits[i]) - BETA for i in selected), F(0))
    selected_boundary = sum((states[i + 1] - states[i] for i in selected), F(0))
    selected_p = sum((projection[i] for i in selected), F(0))
    assert selected_lhs == (selected_boundary - selected_p) / eta
    assert selected_lhs != (states[3] - states[0] - selected_p) / eta

    clipping_extremes = []
    for hit, boundary in ((0, LOWER), (1, UPPER)):
        repeated = (hit,) * 1000
        extreme_states, extreme_p = path(repeated, eta)
        upper_debit, lower_debit = check_window(repeated, extreme_states, extreme_p, eta, 0, 1000)
        assert extreme_states[-1] == boundary
        assert extreme_states[-2] == boundary
        assert extreme_p[-1] == -eta * (hit - BETA)
        assert F(sum(repeated), 1000) == hit != BETA
        clipping_extremes.append(dict(hit=hit, n=1000, final_state=str(boundary),
                                      upper_debit=str(upper_debit), lower_debit=str(lower_debit),
                                      frequency=str(F(hit)), target=str(BETA),
                                      final_projection=str(extreme_p[-1])))

    # A perfect frequency cycle with badly wrong tail severity. Classification
    # is proved by Y=0<Q and Y=40>Q with exp(theta)<=1; binary64 is only used
    # to display the scales and irrational ES residual.
    losses = [0.0] * 39 + [40.0]
    cycle_hits = [0] * 39 + [1]
    cycle_states, cycle_p = path(cycle_hits, eta)
    assert cycle_states == [F(-j, 800) for j in range(40)] + [F(0)]
    assert all(p == 0 for p in cycle_p)
    assert F(sum(cycle_hits), 40) == BETA
    thresholds = [math.exp(float(theta)) for theta in cycle_states[:-1]]
    assert all(0 < q <= 1 for q in thresholds)
    assert [int(y > q) for y, q in zip(losses, thresholds)] == cycle_hits
    residuals = [q + max(y - q, 0.0) / float(BETA) - q
                 for y, q in zip(losses, thresholds)]
    mean_residual = math.fsum(residuals) / 40
    analytic_value_binary64 = 40 - math.exp(-39 / 800)
    assert math.isclose(mean_residual, analytic_value_binary64, rel_tol=0, abs_tol=1e-12)
    assert mean_residual > 39
    long_states, long_p = path(cycle_hits * 10, eta)
    assert all(long_states[k] == 0 for k in range(0, 401, 40))
    assert all(p == 0 for p in long_p)
    check_window(cycle_hits * 10, long_states, long_p, eta, 0, 400)

    # Envelope comparisons use rational logarithms s=log(Y/q). Because exp
    # is strictly increasing, b=1{s>theta} is exact without evaluating exp.
    # None denotes a nonpositive loss, automatically a nonexceedance and
    # compatible with the one-sided upper envelope.
    state_grid = [F(i, 40) for i in range(-40, 41)]
    for rate in rates[:3]:
        upper_log = UPPER - rate * (1 - BETA)
        lower_log = LOWER + rate * BETA
        samples = (None, LOWER - 5, LOWER - rate, F(0), upper_log, upper_log - F(1, 100))
        for theta, score in product(state_grid, samples):
            assert score is None or score <= upper_log
            hit = 0 if score is None else int(score > theta)
            _, p = step(theta, hit, rate)
            assert p >= 0  # No negative projection: no upper saturation debit.
            counts['upper_envelope_cases'] += 1
        for theta, score in product(state_grid, (lower_log, (lower_log + upper_log) / 2, upper_log)):
            assert lower_log <= score <= upper_log
            _, p = step(theta, int(score > theta), rate)
            assert p == 0
            counts['two_sided_envelope_cases'] += 1

    # Stale feedback defeats that envelope implication if the update state is
    # not the state that generated the retained threshold.
    issued, current, score = F(-1), F(1), F(0)
    assert score <= UPPER - eta * (1 - BETA)
    retained_hit = int(score > issued)
    after, stale_projection = step(current, retained_hit, eta)
    assert retained_hit == 1 and after == UPPER and stale_projection < 0

    # Independent lanes can be pooled algebraically without independence.
    lane_sequences = ((1, 0, 0, 0), (0, 1, 0), (1, 1), (0,), (0, 0, 0, 0, 1))
    total_hits = total_n = 0
    total_boundary = total_projection = F(0)
    for seq in lane_sequences:
        lane_states, lane_p = path(seq, eta)
        total_hits += sum(seq)
        total_n += len(seq)
        total_boundary += lane_states[-1] - lane_states[0]
        total_projection += sum(lane_p, F(0))
    assert total_projection == 0
    assert F(total_hits) - total_n * BETA == (total_boundary - total_projection) / eta
    assert abs(F(total_hits, total_n) - BETA) <= F(len(lane_sequences)) / (eta * total_n)

    # A zero-rate baseline is well-defined but not a divided feedback identity.
    zero_states, zero_p = path((0, 1, 1), F(0), F(3, 4))
    assert zero_states == [F(3, 4)] * 4 and zero_p == [F(0)] * 3
    for arguments in (((0,), [F(0), F(0)], [F(0)], F(0), 0, 1),
                      ((0,), [F(0), F(0)], [F(0)], eta, 0, 0)):
        try:
            check_window(*arguments)
        except ValueError:
            counts['rejected_accounting_domains'] += 1
        else:
            raise AssertionError('invalid accounting domain accepted')

    result = dict(
        status='pass',
        scope='Constructed finite-path algebra checks; not a conditional calibration test.',
        arithmetic='Exact Fraction states, updates, clipping and bounds; binary64 exp only for the ES illustration.',
        counts=counts,
        enumeration=dict(path_length=8, rates=list(map(str, rates)), initial_states=list(map(str, initials)),
                         beta=str(BETA), bounds=[str(LOWER), str(UPPER)], seed=None),
        reporting_window=dict(start=start, end=end, initial_state=str(states[start]),
                              discrepancy=str(actual), correct_rhs=str(correct),
                              incorrect_zero_restart_rhs=str(wrong_zero_restart)),
        clipping_extremes=clipping_extremes,
        perfect_frequency_wrong_es=dict(
            construction='39 zero losses then one loss of 40; q=e=1; eta=1/20; theta0=0.',
            exact_hits_per_period=1, period=40, exact_final_state='0', exact_projection_sum='0',
            exact_frequency='1/40', repeated_periods_checked=10,
            exact_last_issue_state='-39/800',
            es_residual_analytic='40-exp(-39/800)>39',
            es_residual_binary64=mean_residual,
            expected_shortfall_of_equal_weight_outcome_block=40,
            status='Synthetic counterexample; exact states/bits, binary64 severity illustration.'),
        stale_envelope_counterexample=dict(issued_state=str(issued), update_state=str(current),
                                           log_normalized_loss=str(score), retained_hit=retained_hit,
                                           projection=str(stale_projection),
                                           conclusion='The envelope needs the update state to equal the original issuance state.'),
        pooled_identity=dict(lanes=len(lane_sequences), n=total_n, hits=total_hits,
                             state_change=str(total_boundary), projection_sum=str(total_projection)),
        conditional_counterexample=dict(regime_probabilities=['1/2','1/2'],
                                        conditional_breach_probabilities=['0','1/20'],
                                        unconditional_breach_probability='1/40',
                                        evidence='Exact mixture probability; aggregate frequency does not imply conditional calibration.'),
        zero_rate='Baseline state stays fixed; divided identity deliberately unavailable.',
        assumptions='Envelope checks compare exact log-normalized losses with the issuance state; no future financial envelope is inferred.'
    )
    assert F(1, 2) * F(0) + F(1, 2) * F(1, 20) == BETA
    destination = ROOT / 'results/calibration_accounting_checks.json'
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps(dict(status=result['status'], counts=counts,
                          es_residual_binary64=mean_residual), sort_keys=True))


if __name__ == '__main__':
    main()
