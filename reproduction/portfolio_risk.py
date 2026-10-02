"""Exact finite CVaR and CVaR under convex-mixture model uncertainty.

Losses and probability inputs are integers or fractions.Fraction values. Floats
are rejected rather than silently interpreting binary approximations as decimal
financial data. Positive values denote losses; negative values denote gains.

The finite Rockafellar--Uryasev representation is established methodology:
    CVaR_alpha(p) = min_eta eta + E_p[(loss-eta)+] / (1-alpha).
For uncertainty over conv(p_1,...,p_M), maximizing CVaR is equivalent to
min_eta max_m f_m(eta). It is generally NOT max_m CVaR(p_m). This module
supplies exact primal/dual witnesses, not a new general risk measure.

All conclusions concern the declared scenario support and probability models;
the code does not calibrate those models or bound unmodeled market outcomes.
No third-party dependencies are required.
"""
from fractions import Fraction
from itertools import combinations


ZERO = Fraction(0)
ONE = Fraction(1)


def _fraction(value, name):
    if type(value) not in (int, Fraction):
        raise ValueError(f'{name} must be an int or Fraction, not a float/bool')
    return Fraction(value)


def _loss_alpha(losses, alpha):
    try:
        xs = tuple(_fraction(x, 'loss') for x in losses)
    except TypeError as exc:
        raise ValueError('losses must be a finite iterable') from exc
    if not xs:
        raise ValueError('at least one loss is required')
    a = _fraction(alpha, 'alpha')
    if not ZERO <= a < ONE:
        raise ValueError('alpha must satisfy 0 <= alpha < 1')
    return xs, a


def _probabilities(probabilities, length):
    try:
        ps = tuple(_fraction(p, 'probability') for p in probabilities)
    except TypeError as exc:
        raise ValueError('probabilities must be a finite iterable') from exc
    if len(ps) != length or any(p < ZERO for p in ps) or sum(ps, ZERO) != ONE:
        raise ValueError('probabilities must match losses, be nonnegative and sum to one')
    return ps


def _objective(xs, ps, a, eta):
    return eta + sum((p * max(x-eta, ZERO) for x, p in zip(xs, ps)), ZERO)/(ONE-a)


def _slopes(xs, ps, a, eta):
    """Left and right derivatives, including the atom at eta exactly."""
    left = ONE - sum((p for x, p in zip(xs, ps) if x >= eta), ZERO)/(ONE-a)
    right = ONE - sum((p for x, p in zip(xs, ps) if x > eta), ZERO)/(ONE-a)
    return left, right


def _certificate_at(xs, ps, a, eta):
    """Construct a tail dual witness; eta must minimize this distribution."""
    excesses = tuple(max(x-eta, ZERO) for x in xs)
    capacities = tuple(p/(ONE-a) for p in ps)
    tail = [cap if x > eta else ZERO for x, cap in zip(xs, capacities)]
    remaining = ONE-sum(tail, ZERO)
    if remaining < ZERO:
        raise ValueError('eta has more than one unit of compulsory tail mass')
    for i, x in enumerate(xs):
        if x == eta:
            take = min(remaining, capacities[i])
            tail[i] = take
            remaining -= take
    if remaining != ZERO:
        raise ValueError('eta does not support a complete CVaR tail witness')
    value = _objective(xs, ps, a, eta)
    cert = dict(losses=xs, probabilities=ps, alpha=a, value=value, eta=eta,
                excesses=excesses, tail_capacities=capacities,
                tail_weights=tuple(tail))
    verify_cvar_certificate(cert)
    return cert


def cvar_certificate(losses, probabilities, alpha):
    """Return exact optimum, primal threshold and feasible maximizing tail.

    tail_weights q satisfy sum(q)=1 and 0<=q_s<=p_s/(1-alpha).
    Equality of sum(q_s loss_s) and the primal objective certifies optimality.
    Atoms on the threshold are allocated only the remaining needed tail mass.
    """
    xs, a = _loss_alpha(losses, alpha)
    ps = _probabilities(probabilities, len(xs))
    eta = min(set(xs), key=lambda t: (_objective(xs, ps, a, t), t))
    return _certificate_at(xs, ps, a, eta)


def cvar(losses, probabilities, alpha):
    """Return finite-distribution CVaR as a Fraction."""
    return cvar_certificate(losses, probabilities, alpha)['value']


def verify_cvar_certificate(certificate, *, losses=None, probabilities=None, alpha=None):
    """Check an exact primal/dual witness WITHOUT searching for an optimum.

    Optional expected inputs bind the certificate to a caller's contract.
    The verifier is independent of the threshold candidate-selection algorithm.
    """
    try:
        xs, a = _loss_alpha(certificate['losses'], certificate['alpha'])
        ps = _probabilities(certificate['probabilities'], len(xs))
        eta = _fraction(certificate['eta'], 'eta')
        value = _fraction(certificate['value'], 'value')
        q = tuple(_fraction(t, 'tail weight') for t in certificate['tail_weights'])
        excess = tuple(_fraction(t, 'excess') for t in certificate['excesses'])
        caps = tuple(_fraction(t, 'tail capacity') for t in certificate['tail_capacities'])
    except (KeyError, TypeError) as exc:
        raise ValueError('incomplete or malformed CVaR certificate') from exc
    if losses is not None and tuple(_fraction(x, 'expected loss') for x in losses) != xs:
        raise ValueError('loss contract mismatch')
    if probabilities is not None and _probabilities(probabilities, len(xs)) != ps:
        raise ValueError('probability contract mismatch')
    if alpha is not None and _fraction(alpha, 'expected alpha') != a:
        raise ValueError('alpha contract mismatch')
    if excess != tuple(max(x-eta, ZERO) for x in xs):
        raise ValueError('wrong positive-part primal excess')
    expected_caps = tuple(p/(ONE-a) for p in ps)
    if caps != expected_caps or len(q) != len(xs):
        raise ValueError('wrong dual capacities or shape')
    if sum(q, ZERO) != ONE or any(t < ZERO or t > cap for t, cap in zip(q, caps)):
        raise ValueError('infeasible tail weights')
    primal = eta + sum((p*z for p, z in zip(ps, excess)), ZERO)/(ONE-a)
    dual = sum((t*x for t, x in zip(q, xs)), ZERO)
    if primal != value or dual != value:
        raise ValueError('primal/dual gap or inconsistent reported value')
    return True


def robust_cvar(losses, models, alpha):
    """Exact max_{p in conv(models)} CVaR_alpha(p), with a <=2-model witness.

    Candidate thresholds comprise all distinct loss knots and all crossings of
    the model objective lines between consecutive knots. At an optimal knot or
    crossing, zero belongs to the convex hull of active subgradient intervals.
    One active model, or a mixture of two, supplies a matching lower witness.
    No LP solver or floating-point optimizer is used.
    """
    xs, a = _loss_alpha(losses, alpha)
    try:
        ps = tuple(_probabilities(p, len(xs)) for p in models)
    except TypeError as exc:
        raise ValueError('models must be a nonempty iterable of distributions') from exc
    if not ps:
        raise ValueError('at least one probability model is required')
    knots = sorted(set(xs))
    candidates = set(knots)
    for lo, hi in zip(knots, knots[1:]):
        midpoint = (lo+hi)/2
        lines = []
        for p in ps:
            above = [(x, probability) for x, probability in zip(xs, p) if x > midpoint]
            slope = ONE-sum((probability for _, probability in above), ZERO)/(ONE-a)
            intercept = sum((x*probability for x, probability in above), ZERO)/(ONE-a)
            lines.append((slope, intercept))
        for (slope1, offset1), (slope2, offset2) in combinations(lines, 2):
            if slope1 != slope2:
                crossing = (offset2-offset1)/(slope1-slope2)
                if lo < crossing < hi:
                    candidates.add(crossing)
    def upper(t):
        return max(_objective(xs, p, a, t) for p in ps)
    eta = min(candidates, key=lambda t: (upper(t), t))
    objectives = tuple(_objective(xs, p, a, eta) for p in ps)
    value = max(objectives)
    active = tuple(i for i, objective in enumerate(objectives) if objective == value)
    slopes = tuple(_slopes(xs, p, a, eta) for p in ps)
    mixture = [ZERO]*len(ps)
    single = next((i for i in active if slopes[i][0] <= ZERO <= slopes[i][1]), None)
    if single is not None:
        mixture[single] = ONE
    else:
        negative = next((i for i in active if slopes[i][1] < ZERO), None)
        positive = next((i for i in active if slopes[i][0] > ZERO), None)
        if negative is None or positive is None:
            raise ArithmeticError('exact upper optimum lacks a stationary active mixture')
        left = slopes[negative][1]
        right = slopes[positive][0]
        mixture[negative] = right/(right-left)
        mixture[positive] = -left/(right-left)
    mixed_p = tuple(sum((weight*p[j] for weight, p in zip(mixture, ps)), ZERO)
                    for j in range(len(xs)))
    lower = _certificate_at(xs, mixed_p, a, eta)
    listed_certificates = tuple(cvar_certificate(xs, p, a) for p in ps)
    listed_values = tuple(cert['value'] for cert in listed_certificates)
    result = dict(losses=xs, models=ps, alpha=a, value=value, eta=eta,
                  model_objectives=objectives, active_models=active,
                  model_subgradients=slopes, mixture_weights=tuple(mixture),
                  mixture_probabilities=mixed_p, lower_certificate=lower,
                  listed_values=listed_values, listed_value=max(listed_values),
                  listed_certificates=listed_certificates,
                  candidate_count=len(candidates))
    verify_robust_cvar_certificate(result)
    return result


def verify_robust_cvar_certificate(certificate, *, losses=None, models=None, alpha=None):
    """Validate matching hull upper/lower bounds without candidate enumeration.

    For any distribution in the hull, its CVaR is no greater than the largest
    model primal objective at the supplied eta. The supplied feasible mixture
    and its exact primal/dual CVaR witness attain that upper bound.
    """
    try:
        xs, a = _loss_alpha(certificate['losses'], certificate['alpha'])
        ps = tuple(_probabilities(p, len(xs)) for p in certificate['models'])
        if not ps:
            raise ValueError('empty model family')
        value = _fraction(certificate['value'], 'value')
        eta = _fraction(certificate['eta'], 'eta')
        mixture = _probabilities(certificate['mixture_weights'], len(ps))
        mixed_p = _probabilities(certificate['mixture_probabilities'], len(xs))
        objectives = tuple(_fraction(x, 'model objective') for x in certificate['model_objectives'])
        lower = certificate['lower_certificate']
    except (KeyError, TypeError) as exc:
        raise ValueError('incomplete or malformed robust CVaR certificate') from exc
    if losses is not None and tuple(_fraction(x, 'expected loss') for x in losses) != xs:
        raise ValueError('loss contract mismatch')
    if models is not None and tuple(_probabilities(p, len(xs)) for p in models) != ps:
        raise ValueError('model contract mismatch')
    if alpha is not None and _fraction(alpha, 'expected alpha') != a:
        raise ValueError('alpha contract mismatch')
    computed = tuple(_objective(xs, p, a, eta) for p in ps)
    if objectives != computed or max(computed) != value:
        raise ValueError('invalid robust upper bound')
    reconstructed = tuple(sum((weight*p[j] for weight, p in zip(mixture, ps)), ZERO)
                          for j in range(len(xs)))
    if mixed_p != reconstructed or sum(weight > ZERO for weight in mixture) > 2:
        raise ValueError('invalid mixture witness')
    verify_cvar_certificate(lower, losses=xs, probabilities=mixed_p, alpha=a)
    if lower['value'] != value:
        raise ValueError('robust upper/lower certificate gap')
    # These extra fields are descriptive; check them as well when supplied.
    if 'active_models' in certificate:
        active = tuple(i for i, v in enumerate(computed) if v == value)
        if tuple(certificate['active_models']) != active:
            raise ValueError('incorrect active-model registry')
    if 'model_subgradients' in certificate:
        slopes = tuple(_slopes(xs, p, a, eta) for p in ps)
        if tuple(certificate['model_subgradients']) != slopes:
            raise ValueError('incorrect subgradient intervals')
    if any(key in certificate for key in ('listed_value','listed_values','listed_certificates')):
        try:
            listed_certificates = tuple(certificate['listed_certificates'])
            listed_values = tuple(_fraction(v, 'listed value') for v in certificate['listed_values'])
            listed_value = _fraction(certificate['listed_value'], 'maximum listed value')
        except (KeyError, TypeError) as exc:
            raise ValueError('incomplete listed-model risk certificates') from exc
        if len(listed_certificates) != len(ps) or len(listed_values) != len(ps):
            raise ValueError('wrong number of listed-model certificates')
        for p, cert, listed in zip(ps, listed_certificates, listed_values):
            verify_cvar_certificate(cert, losses=xs, probabilities=p, alpha=a)
            if cert['value'] != listed:
                raise ValueError('incorrect listed-model value')
        if max(listed_values) != listed_value:
            raise ValueError('incorrect maximum listed-model value')
    return True
