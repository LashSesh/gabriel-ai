"""Independent exact checks for the bounded common-ratio severity objective.

Fraction arithmetic verifies weighted recurrence, constrained first-order
optimality, corrections, tail functionals and moment distinctions. Logarithmic
score displays are explicitly binary64 illustrations, not interval proofs.
No empirical forecasting advantage or actual transcendental discount is proved.
"""
from fractions import Fraction as F
from itertools import product
from pathlib import Path
import json
import math

ROOT = Path(__file__).resolve().parents[1]
BETA = F(1, 40)
PRIOR = F(3, 2)


def update_path(observations, discount, prior=PRIOR):
    states = [prior]
    for observation in observations:
        assert observation >= 1
        states.append(discount * states[-1] + (1 - discount) * observation)
    return states


def weights(n, discount):
    return [discount ** n] + [(1 - discount) * discount ** (n - i) for i in range(1, n + 1)]


def quantile_tail(losses, probabilities, alpha):
    ordered = sorted(zip(losses, probabilities))
    cumulative = F(0)
    for loss, probability in ordered:
        cumulative += probability
        if cumulative >= alpha:
            quantile = loss
            break
    remaining, total = 1 - alpha, F(0)
    for loss, probability in reversed(ordered):
        used = min(probability, remaining)
        total += used * loss
        remaining -= used
        if remaining == 0:
            break
    assert remaining == 0
    return quantile, total / (1 - alpha)


def cdf_integral(losses, probabilities, alpha, start, stop):
    if stop < start:
        return -cdf_integral(losses, probabilities, alpha, stop, start)
    cuts = sorted(set([start, stop] + [x for x in losses if start < x < stop]))
    integral = F(0)
    for left, right in zip(cuts, cuts[1:]):
        middle = (left + right) / 2
        cdf = sum((p for x, p in zip(losses, probabilities) if x <= middle), F(0))
        integral += (right - left) * (cdf - alpha)
    return integral


def uniform_excess(lower, upper, quantile):
    if quantile <= lower:
        return (lower + upper) / 2 - quantile
    if quantile >= upper:
        return F(0)
    return (upper - quantile) ** 2 / (2 * (upper - lower))


def decomposition(psi, truth_es, emitted_es):
    assert psi >= truth_es > 0 and emitted_es > 0
    quantile_term = math.log(float(psi / truth_es))
    severity_term = math.log(float(emitted_es / psi)) + float(psi / emitted_es) - 1
    direct = math.log(float(emitted_es / truth_es)) + float(psi / emitted_es) - 1
    assert quantile_term >= -1e-12 and severity_term >= -1e-12
    discrepancy = abs(direct - quantile_term - severity_term)
    assert discrepancy < 1e-12
    return discrepancy


def main():
    counts = dict(recurrence_prefixes=0, constrained_optima=0, reciprocal_variational_checks=0,
                  exact_corrections=0, correction_cap_bounds=0, fading_checks=0,
                  discrete_quantile_functionals=0, continuous_quantile_functionals=0,
                  score_decompositions_binary64=0, alternating_counterexamples=0)
    discounts = (F(1, 2), F(3, 4), F(9, 10))
    levels = (F(1), F(3, 2), F(4), F(100))
    caps = (F(1), F(2), F(20))
    max_decomposition_error = 0.0
    for discount, observations in product(discounts, product(levels, repeat=4)):
        states = update_path(observations, discount)
        alternative = update_path(observations, discount, F(7, 4))
        for n in range(1, 5):
            w = weights(n, discount)
            assert sum(w, F(0)) == 1
            explicit = sum((a * b for a, b in zip(w, [PRIOR] + list(observations[:n]))), F(0))
            assert states[n] == explicit >= 1
            counts['recurrence_prefixes'] += 1
            assert alternative[n] - states[n] == discount ** n * (F(7, 4) - PRIOR)
            counts['fading_checks'] += 1
            for cap in caps:
                optimum = min(cap, states[n])
                reciprocal = 1 / optimum
                gradient = states[n] - 1 / reciprocal
                assert states[n] - optimum == max(states[n] - cap, F(0))
                counts['constrained_optima'] += 1
                for j in range(21):
                    candidate = 1 / cap + F(j, 20) * (1 - 1 / cap)
                    # Necessary and sufficient first-order condition for the
                    # strictly convex reciprocal objective on the interval.
                    assert gradient * (candidate - reciprocal) >= 0
                    counts['reciprocal_variational_checks'] += 1
        for i in range(4):
            changed = list(observations)
            delta = F(-1, 4) if observations[i] > 1 else F(1, 2)
            changed[i] += delta
            replay = update_path(changed, discount)[-1]
            correction = (1 - discount) * discount ** (3 - i) * delta
            assert replay == states[-1] + correction
            counts['exact_corrections'] += 1
            for cap in caps:
                assert abs(min(cap, replay) - min(cap, states[-1])) <= abs(correction)
                counts['correction_cap_bounds'] += 1
        changed = [x + (F(1, 2) if i % 2 == 0 or x == 1 else F(-1, 4))
                   for i, x in enumerate(observations)]
        deltas = [y - x for x, y in zip(observations, changed)]
        terms = [(1 - discount) * discount ** (3 - i) * d for i, d in enumerate(deltas)]
        replay = update_path(changed, discount)[-1]
        assert replay - states[-1] == sum(terms, F(0))
        assert abs(replay - states[-1]) <= sum(map(abs, terms), F(0))
        counts['exact_corrections'] += 1

    # Clipping the accumulator loses the exact weighted objective.
    correct = update_path((F(100), F(1)), F(1, 2))
    bad_first = min(F(2), correct[1])
    bad_second = (bad_first + 1) / 2
    assert correct == [PRIOR, F(203, 4), F(207, 8)]
    assert min(F(2), correct[-1]) == 2 and bad_second == F(3, 2)
    assert correct[-1] - bad_second > 0  # Reciprocal derivative points away.

    # Common ratio fitting balances normalized, not raw, residuals.
    quantiles, normalized = (F(1), F(2)), (F(1), F(3))
    ratio = sum(normalized) / 2
    assert sum((r - ratio for r in normalized), F(0)) / 2 == 0
    raw_residual = sum((q * (r - ratio) for q, r in zip(quantiles, normalized)), F(0)) / 2
    assert raw_residual == F(1, 2)

    # Independent sorted-tail and step-CDF integral calculations, including
    # atoms, both sides of the quantile, and negative body losses.
    losses = tuple(map(F, (-2, 0, 1, 4)))
    for raw_weights, alpha, q in product(product((1, 2), repeat=4),
            (F(1, 2), F(3, 4), F(39, 40)),
            (F(1, 4), F(1, 2), F(1), F(2), F(4), F(6))):
        probabilities = tuple(F(w, sum(raw_weights)) for w in raw_weights)
        qstar, esstar = quantile_tail(losses, probabilities, alpha)
        beta = 1 - alpha
        psi = q + sum((p * max(y - q, F(0)) for y, p in zip(losses, probabilities)), F(0)) / beta
        at_quantile = qstar + sum((p * max(y - qstar, F(0)) for y, p in zip(losses, probabilities)), F(0)) / beta
        assert at_quantile == esstar > 0
        assert psi >= esstar
        assert psi - esstar == cdf_integral(losses, probabilities, alpha, qstar, q) / beta
        mean_normalized = sum((p * (1 + max(y - q, F(0)) / (beta * q))
                               for y, p in zip(losses, probabilities)), F(0))
        assert q * mean_normalized == psi
        counts['discrete_quantile_functionals'] += 1
        for ratio in (F(1), F(3, 2), F(20)):
            error = decomposition(psi, esstar, ratio * q)
            max_decomposition_error = max(max_decomposition_error, error)
            counts['score_decompositions_binary64'] += 1

    # The known-law bounded synthetic case has an exact .39*s functional
    # upward bias when its issued quantile is .8 times the true quantile.
    misspecified_targets = []
    for scale, tail_mean, factor in product((F(1, 2), F(1), F(2)),
            (F(1, 2), F(3), F(30)),
            (F(1, 2), F(4, 5), F(1), F(3, 2), F(3))):
        q, esstar = scale * factor, scale * (1 + tail_mean)
        excess = ((1 - BETA) * uniform_excess(-scale, scale, q)
                  + BETA * uniform_excess(scale, scale * (1 + 2 * tail_mean), q))
        psi = q + excess / BETA
        assert psi >= esstar
        counts['continuous_quantile_functionals'] += 1
        if factor <= 1:
            assert psi / scale == 1 + tail_mean + (1 - BETA) * (1 - factor) ** 2 / (4 * BETA)
        if factor == F(4, 5):
            assert (psi - esstar) / scale == F(39, 100)
            if scale == 1 and tail_mean in (F(1, 2), F(3)):
                misspecified_targets.append(dict(tail_mean=str(tail_mean), ratio_target=str(psi / q),
                                                   true_es=str(esstar), fixed_q_optimal_es=str(psi)))
        for ratio in (F(1), F(3, 2), F(20)):
            error = decomposition(psi, esstar, ratio * q)
            max_decomposition_error = max(max_decomposition_error, error)
            counts['score_decompositions_binary64'] += 1

    alternating = []
    for discount, big in product((F(0), F(1, 2), F(9, 10)), (F(2), F(4), F(20))):
        before_big = (1 + discount * big) / (1 + discount)
        before_small = (big + discount) / (1 + discount)
        constant = (1 + big) / 2
        assert before_big == discount * before_small + 1 - discount
        assert before_small == discount * before_big + (1 - discount) * big
        assert 1 <= before_big < constant < before_small <= big
        # Exact derivative signs establish both losses exceed the constant
        # comparator. The numerical log gap is only a displayed illustration.
        def objective(k, r):
            return math.log(float(k)) + float(r / k) - 1
        gap = (objective(before_big, big) + objective(before_small, F(1))
               - objective(constant, big) - objective(constant, F(1))) / 2
        assert gap > 0
        counts['alternating_counterexamples'] += 1
        alternating.append(dict(discount=str(discount), big=str(big),
                                before_big=str(before_big), before_small=str(before_small),
                                constant=str(constant), mean_score_gap_binary64=gap))

    result = dict(
        status='pass', counts=counts,
        arithmetic='Exact Fraction algebra; binary64 logarithms only for explicitly labelled score illustrations.',
        empirical_claim='None. Checks do not establish future calibration or actual binary64 rounding guarantees.',
        recurrence=dict(prior='3/2', prior_mass='1', discounts=list(map(str, discounts)),
                        levels=list(map(str, levels)), path_length=4, caps=list(map(str, caps)),
                        exact_weights='lambda^n prior; (1-lambda)*lambda^(n-i) observations'),
        clipping_accumulator_counterexample=dict(discount='1/2', cap='2', observations=['100','1'],
                                                 correct_states=list(map(str, correct)),
                                                 correct_emitted_ratio='2', wrong_second_state=str(bad_second)),
        normalized_vs_raw=dict(quantiles=['1','2'], observations=['1','3'], ratio='2',
                               normalized_mean='0', raw_mean=str(raw_residual)),
        underestimated_quantile_targets=misspecified_targets,
        cap_underestimation=dict(correct_quantile='1', true_es='31', ratio_cap='20',
                                 best_admissible_es='20', population_normalized_cap_residual='11'),
        alternating_counterexamples=alternating,
        maximum_decomposition_discrepancy_binary64=max_decomposition_error,
        decomposition_tolerance=1e-12,
        correction_scope='Fixed retained positions, original quantiles, unchanged discount and prior; not a counterfactual forecast history.'
    )
    destination = ROOT / 'results/severity_objective_checks.json'
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps(dict(status='pass', counts=counts,
                          maximum_decomposition_discrepancy_binary64=max_decomposition_error), sort_keys=True))


if __name__ == '__main__':
    main()
