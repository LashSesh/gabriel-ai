# Vendored verbatim from gabriel_runtime/window_certificate.py (inherited runtime, source SHA-256
# b344b7282c8c28262236e680d68fe58bfda67ecc45073c3b8d38f0b11214925c) for the native PSE graph worker (ADR-18). The dedicated certificate
# process imports this copy; implementation_identity() binds the bytes of this file.
"""Bounded continuous-time regional certificates for an exact clique model.

The model is mathematical evolution of the represented binary64 Laplacian and
the exact raw source bits, normalized over the reals.  It is deliberately not
the rounded source preparation or libm execution of the older point observer.

For a represented clique L = delta P + rho (I-P), write q = m + d, with
m = sum(q)/n.  Removing a global phase gives m + exp(-i*n*w*t) d.  Thus regional
mass is a + b*cos(omega*t) + c*sin(omega*t), with rational coefficients.  Its
maximum over a compact interval occurs at an endpoint or a phase maximum.
Arb bounds the phase quotients before any integer candidate is selected.
No floating-point candidate search, sampling, or tolerance supplies coverage.

The trust base includes Python integer arithmetic and python-flint/Arb.  This
is a numerical certificate implementation, not a proof-assistant theorem.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import threading

import flint
from flint import arb, ctx, fmpq


CERTIFICATE_SCHEMA = 'gabriel-clique-window-certificate/v1'
MODEL_PROFILE = 'exact-raw-source-represented-clique/v1'
DEFAULT_PRECISIONS = (128, 256, 512)
MAX_PRECISION_BITS = 512
MAX_NODES = 64
MAX_RATIONAL_BITS = 8192
MAX_OUTPUT_INTEGER_BITS = 12288
_ARB_LOCK = threading.RLock()


class OutOfScope(ValueError):
    """A valid represented matrix is outside the exact clique profile."""


def rational_string(value):
    """Canonical exact JSON representation: integer or reduced p/q string."""
    value = Fraction(value)
    if max(abs(value.numerator).bit_length(), value.denominator.bit_length()) > MAX_OUTPUT_INTEGER_BITS:
        raise ArithmeticError('exact certificate integer serialization cap exceeded')
    return str(value)


def bits_fraction(value):
    """Decode finite IEEE-754 binary64 bits directly to an exact dyadic."""
    if (type(value) is not str or len(value) != 16
            or any(c not in '0123456789abcdef' for c in value)):
        raise ValueError('binary64 requires sixteen lowercase hexadecimal bit digits')
    raw = int(value, 16)
    sign, exponent, mantissa = raw >> 63, (raw >> 52) & 2047, raw & ((1 << 52) - 1)
    if exponent == 2047:
        raise ValueError('nonfinite binary64 quantity')
    if exponent:
        mantissa |= 1 << 52
        power = exponent - 1023 - 52
    else:
        power = -1074
    numerator = -mantissa if sign else mantissa
    return Fraction(numerator << power) if power >= 0 else Fraction(numerator, 1 << -power)


def exact_number(value):
    """Accept wire bits, a Fraction/int, or canonical rational JSON.

    String arguments always denote 16-digit binary64 bits.  To avoid ambiguity,
    rational wire values use {'numerator': '<int>', 'denominator': '<positive>'}.
    Python floats are intentionally rejected.
    """
    if type(value) is str:
        return bits_fraction(value)
    if type(value) is int:
        result = Fraction(value)
    elif type(value) is Fraction:
        result = value
    elif type(value) is dict and set(value) == {'numerator', 'denominator'}:
        ns, ds = value['numerator'], value['denominator']
        if type(ns) is not str or type(ds) is not str or len(ns) > 2500 or len(ds) > 2500:
            raise ValueError('invalid rational wire value')
        try:
            n, d = int(ns), int(ds)
        except ValueError as exc:
            raise ValueError('invalid rational wire value') from exc
        if str(n) != ns or str(d) != ds or d <= 0:
            raise ValueError('noncanonical rational wire value')
        result = Fraction(n, d)
        if str(result.numerator) != ns or str(result.denominator) != ds:
            raise ValueError('rational wire value must be reduced')
    else:
        raise ValueError('expected finite binary64 bits or an exact rational')
    if max(abs(result.numerator).bit_length(), result.denominator.bit_length()) > MAX_RATIONAL_BITS:
        raise ValueError('rational resource cap exceeded')
    return result


def _digest(value):
    data = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)
    return hashlib.sha256(data.encode('ascii')).hexdigest()


def implementation_identity():
    return {'schema': CERTIFICATE_SCHEMA, 'model_profile': MODEL_PROFILE,
            'python_flint_version': flint.__version__,
            'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'default_precisions': list(DEFAULT_PRECISIONS),
            'max_precision_bits': MAX_PRECISION_BITS, 'max_nodes': MAX_NODES,
            'max_rational_bits': MAX_RATIONAL_BITS,
            'max_output_integer_bits': MAX_OUTPUT_INTEGER_BITS}


@dataclass(frozen=True)
class HarmonicModel:
    a: Fraction
    b: Fraction
    c: Fraction
    omega: Fraction
    n: int
    weight: Fraction
    degree: Fraction
    norm_squared: Fraction
    entities: tuple
    targets: tuple
    input_sha256: str

    @property
    def amplitude_squared(self):
        return self.b * self.b + self.c * self.c

    @property
    def stationary(self):
        return self.omega == 0 or self.amplitude_squared == 0

    @property
    def stationary_value(self):
        if not self.stationary:
            raise ValueError('model is not stationary')
        return self.a + self.b if self.omega == 0 else self.a

    def global_upper_leq(self, threshold):
        gap = Fraction(threshold) - self.a
        return gap >= 0 and gap * gap >= self.amplitude_squared

    def model_payload(self):
        return {'profile': MODEL_PROFILE, 'n': self.n,
                'entities': list(self.entities), 'targets': list(self.targets),
                'input_sha256': self.input_sha256,
                'normalization': 'exact-raw-source-l2',
                'a': str(self.a), 'b': str(self.b), 'c': str(self.c),
                'omega': str(self.omega), 'weight': str(self.weight),
                'degree': str(self.degree),
                'delta': str(self.degree - (self.n - 1) * self.weight),
                'rho': str(self.degree + self.weight),
                'norm_squared': str(self.norm_squared),
                'amplitude_squared': str(self.amplitude_squared)}


def prepare_model(snapshot, source, targets):
    """Validate exact clique structure and derive exact rational coefficients.

    snapshot has ordered ``entities`` and dense ``laplacian_bits``.  Its
    diagonal is the represented degree, not a reconstructed sum of weights.
    Optional snapshot metadata does not change the mathematical model.
    """
    if type(snapshot) is not dict:
        raise ValueError('snapshot must be an object')
    entities, matrix = snapshot.get('entities'), snapshot.get('laplacian_bits')
    if (type(entities) is not list or not 1 <= len(entities) <= MAX_NODES
            or any(type(x) is not int or x < 0 for x in entities)
            or len(set(entities)) != len(entities)):
        raise ValueError('invalid ordered snapshot entities')
    n = len(entities)
    if type(matrix) is not list or len(matrix) != n or any(type(row) is not list or len(row) != n for row in matrix):
        raise ValueError('invalid dense represented Laplacian')
    lap = [[bits_fraction(x) for x in row] for row in matrix]
    if type(source) is not list or len(source) != n:
        raise ValueError('source must cover all entities once')
    by_entity = {}
    for term in source:
        if type(term) is not dict or set(term) != {'entity', 're_bits', 'im_bits'}:
            raise ValueError('invalid raw source record')
        entity = term['entity']
        if type(entity) is not int or entity not in entities or entity in by_entity:
            raise ValueError('source must cover all entities once')
        by_entity[entity] = (bits_fraction(term['re_bits']), bits_fraction(term['im_bits']))
    if (type(targets) is not list or any(type(x) is not int or x not in entities for x in targets)
            or len(set(targets)) != len(targets)):
        raise ValueError('targets must be unique snapshot entities')
    q = [by_entity[x] for x in entities]
    norm = sum((re * re + im * im for re, im in q), Fraction(0))
    if norm == 0:
        raise ValueError('raw source must have nonzero exact norm')
    degree = lap[0][0]
    weight = -lap[0][1] if n > 1 else Fraction(0)
    if degree < 0 or weight < 0:
        raise OutOfScope('negative degree or edge weight outside clique profile')
    for i in range(n):
        for j in range(n):
            if lap[i][j] != (degree if i == j else -weight):
                raise OutOfScope('represented Laplacian is not an exact equal-degree uniform clique')
    mr = sum((v[0] for v in q), Fraction(0)) / n
    mi = sum((v[1] for v in q), Fraction(0)) / n
    a = b = c = Fraction(0)
    target_set = set(targets)
    for entity, (qr, qi) in zip(entities, q):
        if entity in target_set:
            dr, di = qr - mr, qi - mi
            a += mr * mr + mi * mi + dr * dr + di * di
            b += 2 * (mr * dr + mi * di)
            # Im(m * conjugate(d)) = mi*dr - mr*di; U has exp(-i*omega*t).
            c += 2 * (mr * di - mi * dr)
    binding = {'entities': entities, 'laplacian_bits': matrix,
               'source': [{**next(term for term in source if term['entity'] == e)} for e in entities],
               'targets': [e for e in entities if e in target_set]}
    return HarmonicModel(a / norm, b / norm, c / norm, n * weight, n,
                         weight, degree, norm, tuple(entities), tuple(binding['targets']), _digest(binding))


def _arb(value):
    value = Fraction(value)
    return arb(fmpq(value.numerator, value.denominator))


def _dyadic(value):
    if not value.is_exact():
        raise ArithmeticError('expected an exact outward Arb endpoint')
    mantissa, exponent = value.man_exp()
    mantissa, exponent = int(mantissa), int(exponent)
    return Fraction(mantissa << exponent) if exponent >= 0 else Fraction(mantissa, 1 << -exponent)


def ball_bounds(value):
    """Outward exact dyadic bounds for a finite Arb ball at current precision."""
    if not value.is_finite():
        raise ArithmeticError('Arb returned a nonfinite enclosure')
    return _dyadic(value.lower()), _dyadic(value.upper())


def _bounds_payload(lower, upper):
    return {'lower': rational_string(lower), 'upper': rational_string(upper)}


def _precision(value):
    if type(value) is not int or not 32 <= value <= MAX_PRECISION_BITS:
        raise ValueError('precision outside declared 32..512 bit cap')
    return value


def point_enclosure(model, t, precision=128):
    """Rigorous point oracle shared by the solver and independent baselines."""
    t = exact_number(t)
    _precision(precision)
    if model.stationary or t == 0:
        value = model.stationary_value if model.stationary else model.a + model.b
        return _bounds_payload(value, value)
    with _ARB_LOCK, ctx.workprec(precision):
        sine, cosine = _arb(model.omega * t).sin_cos()
        lower, upper = ball_bounds(_arb(model.a) + _arb(model.b) * cosine + _arb(model.c) * sine)
        # Unitarity and exact normalization prove this independent range cap.
        return _bounds_payload(max(Fraction(0), lower), min(Fraction(1), upper))


def derivative_enclosure(model, start, end, precision=128):
    """Rigorous f' enclosure on a whole interval; no analytic extrema logic."""
    start, end = exact_number(start), exact_number(end)
    _precision(precision)
    if start > end:
        raise ValueError('ordered interval required')
    if model.stationary:
        return _bounds_payload(Fraction(0), Fraction(0))
    with _ARB_LOCK, ctx.workprec(precision):
        left, right = model.omega * start, model.omega * end
        phase = arb(fmpq((left + right).numerator, (left + right).denominator)) / 2
        radius = _arb((right - left) / 2)
        phase = phase + arb(0, radius.upper())
        sine, cosine = phase.sin_cos()
        lower, upper = ball_bounds(_arb(model.omega) * (-_arb(model.b) * sine + _arb(model.c) * cosine))
        return _bounds_payload(lower, upper)


def _ceil(value):
    return -((-value.numerator) // value.denominator)


def _floor(value):
    return value.numerator // value.denominator


def _phase_geometry(model, start, end, precision):
    with _ARB_LOCK, ctx.workprec(precision):
        phi = arb.atan2(_arb(model.c), _arb(model.b))
        period = 2 * arb.pi()
        left = ball_bounds((_arb(model.omega * start) - phi) / period)
        right = ball_bounds((_arb(model.omega * end) - phi) / period)
        possible_first, possible_last = _ceil(left[0]), _floor(right[1])
        definite_first, definite_last = _ceil(left[1]), _floor(right[0])
        geometry = {'phase': _bounds_payload(*ball_bounds(phi)),
                    'start_quotient': _bounds_payload(*left),
                    'end_quotient': _bounds_payload(*right),
                    'possible_first_index': str(possible_first),
                    'possible_last_index': str(possible_last)}
        if possible_first > possible_last:
            return geometry, None, None
        if definite_first <= definite_last:
            # The middle certified index stays away from boundary rounding.
            index = (definite_first + definite_last) // 2
            critical = ball_bounds((phi + period * index) / _arb(model.omega))
            return geometry, index, critical
        return geometry, None, None


def _maximum_rational_bounds(model, threshold):
    """Rational enclosure of the peak with lower > threshold when peak > it.

    U=1+D bounds sqrt(D).  For s=h-a>=0, sqrt(D)-s=(D-s*s)/(sqrt(D)+s),
    so replacing its denominator by U+s supplies an exact positive margin.
    This settles arbitrarily close rational thresholds without precision loops.
    """
    d, s = model.amplitude_squared, threshold - model.a
    u = 1 + d
    if s < 0:
        lower = model.a
    else:
        margin = (d - s * s) / (u + s)
        # A dyadic margin avoids multiplying already large rational
        # denominators merely to state a strict witness inequality.
        exponent = margin.numerator.bit_length() - margin.denominator.bit_length() - 2
        epsilon = Fraction(1 << exponent) if exponent >= 0 else Fraction(1, 1 << -exponent)
        lower = threshold + epsilon
    return max(Fraction(0), lower), min(Fraction(1), model.a + u)


def certify_window(snapshot, source, targets, start_bits, end_bits, threshold_bits,
                   *, precisions=DEFAULT_PRECISIONS):
    """Certify ``exists t in [start,end]: regional_mass(t) > threshold``.

    Returns reachable, excluded, unknown, or out_of_scope.  Every certified
    decision carries rational evidence.  Exhausting the fixed precision ladder
    produces unknown; exact equality is never decided by a tolerance.
    """
    start, end, threshold = map(exact_number, (start_bits, end_bits, threshold_bits))
    if start > end:
        raise ValueError('window start must not exceed its end')
    if not 0 <= threshold <= 1:
        raise ValueError('threshold must lie in [0,1]')
    if type(precisions) not in (tuple, list) or not 1 <= len(precisions) <= 8:
        raise ValueError('precision ladder must contain 1..8 entries')
    ladder = tuple(_precision(p) for p in precisions)
    if list(ladder) != sorted(set(ladder)):
        raise ValueError('precision ladder must be strictly increasing')
    resources = {'precision_cap_bits': ladder[-1], 'precision_ladder': list(ladder),
                 'attempted_precisions': [], 'point_evaluations': 0,
                 'phase_evaluations': 0, 'max_precision_bits': 0,
                 'max_output_integer_bits': MAX_OUTPUT_INTEGER_BITS,
                 'max_point_evaluations': 3 * len(ladder),
                 'max_phase_evaluations': len(ladder)}
    result = {'schema': CERTIFICATE_SCHEMA, 'model_profile': MODEL_PROFILE,
              'query': {'start': str(start), 'end': str(end), 'threshold': str(threshold)},
              'resources': resources}
    try:
        model = prepare_model(snapshot, source, targets)
    except OutOfScope as exc:
        return {**result, 'status': 'out_of_scope', 'reason': str(exc)}
    result['model'] = model.model_payload()

    def finish(status, evidence):
        return {**result, 'status': status, 'evidence': evidence}

    if model.stationary:
        value = model.stationary_value
        return finish('reachable' if value > threshold else 'excluded',
                      {'method': 'stationary_exact', 'value': str(value),
                       'time': str(start), 'mass': _bounds_payload(value, value)})
    if model.global_upper_leq(threshold):
        return finish('excluded', {'method': 'global_amplitude_exact',
                                  'supremum_upper': str(threshold),
                                  'offset': str(model.a), 'radicand': str(model.amplitude_squared)})
    last = None
    for precision in ladder:
        resources['attempted_precisions'].append(precision)
        resources['max_precision_bits'] = precision
        endpoints = []
        try:
            for t in ((start,) if start == end else (start, end)):
                resources['point_evaluations'] += 1
                mass = point_enclosure(model, t, precision)
                endpoints.append({'time': str(t), 'mass': mass})
                if Fraction(mass['lower']) > threshold:
                    return finish('reachable', {'method': 'rational_point', 'precision_bits': precision,
                                                'time': str(t), 'mass': mass})
            if start == end:
                if Fraction(endpoints[0]['mass']['upper']) <= threshold:
                    return finish('excluded', {'method': 'singleton_point', 'precision_bits': precision,
                                               'endpoints': endpoints,
                                               'supremum_upper': endpoints[0]['mass']['upper']})
                last = {'reason': 'singleton_threshold_overlap', 'endpoints': endpoints}
                continue
            resources['phase_evaluations'] += 1
            geometry, index, critical = _phase_geometry(model, start, end, precision)
            possible_first = int(geometry['possible_first_index'])
            possible_last = int(geometry['possible_last_index'])
            if possible_first > possible_last and all(Fraction(x['mass']['upper']) <= threshold for x in endpoints):
                return finish('excluded', {'method': 'endpoint_maximum', 'precision_bits': precision,
                                           'endpoints': endpoints, 'phase_geometry': geometry,
                                           'supremum_upper': str(max(Fraction(x['mass']['upper']) for x in endpoints))})
            if critical is not None:
                lo, hi = critical
                # First try a simple rational point witness.  Its check does
                # not depend on the phase-location reasoning that proposed it.
                candidate = (lo + hi) / 2
                if (start <= candidate <= end and
                        max(abs(candidate.numerator).bit_length(), candidate.denominator.bit_length()) <= MAX_RATIONAL_BITS):
                    resources['point_evaluations'] += 1
                    mass = point_enclosure(model, candidate, precision)
                    if Fraction(mass['lower']) > threshold:
                        return finish('reachable', {'method': 'rational_point', 'precision_bits': precision,
                                                    'time': str(candidate), 'mass': mass})
                if start <= lo <= hi <= end:
                    lower, upper = _maximum_rational_bounds(model, threshold)
                    assert lower > threshold
                    return finish('reachable', {'method': 'critical_point', 'precision_bits': precision,
                                                'phase_index': str(index),
                                                'time_enclosure': _bounds_payload(lo, hi),
                                                'mass': _bounds_payload(lower, upper),
                                                'value': {'offset': str(model.a), 'radicand': str(model.amplitude_squared)},
                                                'phase_geometry': geometry})
            last = {'reason': 'phase_or_threshold_overlap', 'endpoints': endpoints,
                    'phase_geometry': geometry}
        except ArithmeticError as exc:
            last = {'reason': 'interval_resource_or_enclosure_limit', 'detail': str(exc)}
    return finish('unknown', {'method': 'precision_cap', **(last or {}),
                              'reason': (last or {}).get('reason', 'precision_cap_exhausted')})


def certify(snapshot, request, *, precisions=DEFAULT_PRECISIONS):
    """Small convenience API for a single window request."""
    required = {'source', 'targets', 'start_bits', 'end_bits', 'threshold_bits'}
    if type(request) is not dict or set(request) != required:
        raise ValueError('single-window request has invalid fields')
    return certify_window(snapshot, **request, precisions=precisions)
