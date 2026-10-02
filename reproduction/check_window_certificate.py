"""Adversarial and independent matrix-exponential checks of window certificates.

Run with python-flint 0.9.0 installed: python reproduction/check_window_certificate.py.
Only the optional new JSON report is written.  Matrix checks act on the full
represented Laplacian and unprepared complex source, independent of the scalar
coefficient derivation.  Root-level certificate verification is a separate check.
"""
from __future__ import annotations

import argparse
from collections import Counter
import copy
from fractions import Fraction
import json
import math
from pathlib import Path
import random
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from flint import acb, acb_mat, arb, ctx, fmpq
from gabriel_runtime.window_certificate import (
    bits_fraction, exact_number, prepare_model, certify_window,
    point_enclosure, derivative_enclosure, ball_bounds, implementation_identity,
)


COUNTS = Counter()
CERTIFICATES = []


def bits(x):
    return struct.pack('>d', x).hex()


def clique(n=2, weight=1.0, degree=None):
    degree = (n - 1) * weight if degree is None else degree
    return {'entities': list(range(n)),
            'laplacian_bits': [[bits(degree if i == j else -weight)
                                for j in range(n)] for i in range(n)]}


def source(values):
    return [{'entity': i, 're_bits': bits(float(re)), 'im_bits': bits(float(im))}
            for i, (re, im) in enumerate(values)]


def require(condition, label):
    if not condition:
        raise AssertionError(label)
    COUNTS[label] += 1


def reject(fn, label):
    try:
        fn()
    except ValueError:
        COUNTS[label] += 1
    else:
        raise AssertionError('expected rejection: ' + label)


def no_floats(value):
    if type(value) is float:
        return False
    if type(value) is dict:
        return all(no_floats(v) for v in value.values())
    if type(value) is list:
        return all(no_floats(v) for v in value)
    return True


def run_case(name, snapshot, q, targets, start, end, threshold, expected, method=None, **kwargs):
    result = certify_window(snapshot, q, targets, start, end, threshold, **kwargs)
    require(result['status'] == expected, name)
    if method:
        require(result['evidence']['method'] == method, name + '_proof_method')
    require(no_floats(result), 'all_output_exact_json')
    resources = result['resources']
    require(resources['point_evaluations'] <= resources['max_point_evaluations']
            and resources['phase_evaluations'] <= resources['max_phase_evaluations']
            and resources['max_precision_bits'] <= resources['precision_cap_bits'], 'resource_caps')
    if result['status'] == 'reachable':
        mass = result['evidence']['mass']
        require(Fraction(mass['lower']) > exact_number(threshold), 'strict_witness_margin')
    CERTIFICATES.append({'name': name, 'snapshot': snapshot, 'source': q,
                         'targets': targets, 'certificate': result})
    return result


def qa(value):
    value = Fraction(value)
    return arb(fmpq(value.numerator, value.denominator))


def full_matrix_mass(snapshot, q, targets, t, precision=384):
    """Independent U=exp(-it L), no mean/deviation or harmonic coefficients."""
    with ctx.workprec(precision):
        n = len(snapshot['entities'])
        by_entity = {v['entity']: v for v in q}
        raw = [(bits_fraction(by_entity[e]['re_bits']), bits_fraction(by_entity[e]['im_bits']))
               for e in snapshot['entities']]
        norm = sum((re * re + im * im for re, im in raw), Fraction(0))
        matrix = acb_mat([[acb(0, qa(-bits_fraction(snapshot['laplacian_bits'][i][j]) * t))
                           for j in range(n)] for i in range(n)])
        evolved = matrix.exp() * acb_mat([[acb(qa(re), qa(im))] for re, im in raw])
        mass = sum((evolved[i, 0].real ** 2 + evolved[i, 0].imag ** 2
                    for i, e in enumerate(snapshot['entities']) if e in targets), arb(0)) / qa(norm)
        return ball_bounds(mass)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT / 'results/window_certificate_checks.json')
    args = parser.parse_args()
    rng = random.Random(2026092701)
    for _ in range(600):
        raw = rng.getrandbits(64)
        if (raw >> 52) & 2047 == 2047:
            continue
        wire = f'{raw:016x}'
        expected = Fraction(*struct.unpack('>d', bytes.fromhex(wire))[0].as_integer_ratio())
        require(bits_fraction(wire) == expected, 'exact_binary64_decode')
    require(bits_fraction('8000000000000000') == 0, 'negative_zero_exact')
    for wire in ('7ff0000000000000', 'fff0000000000000', '7ff8000000000001', 'ABC', '000000000000000G'):
        reject(lambda wire=wire: bits_fraction(wire), 'invalid_or_nonfinite_bits')
    reject(lambda: exact_number(0.25), 'float_query_rejected')
    reject(lambda: exact_number({'numerator': '2', 'denominator': '4'}), 'unreduced_rational_rejected')

    s = clique()
    q = source([(1, 0), (0, 0)])
    m = prepare_model(s, q, [1])
    require((m.a, m.b, m.c, m.omega) == (Fraction(1, 2), Fraction(-1, 2), 0, 2), 'exact_two_node_coefficients')
    run_case('interior_peak', s, q, [1], Fraction(0), Fraction(3), Fraction(9, 10), 'reachable')
    run_case('endpoint_peak_free_exclusion', s, q, [1], Fraction(0), Fraction(1, 4), Fraction(1, 10),
             'excluded', 'endpoint_maximum')
    run_case('negative_window', s, q, [1], Fraction(-3), Fraction(0), Fraction(9, 10), 'reachable')
    run_case('equality_global_peak', s, q, [1], Fraction(-100), Fraction(100), Fraction(1),
             'excluded', 'global_amplitude_exact')
    run_case('singleton_zero_equality', s, q, [1], Fraction(0), Fraction(0), Fraction(0),
             'excluded', 'singleton_point')
    run_case('empty_target', s, q, [], Fraction(-10), Fraction(10), Fraction(0), 'excluded', 'stationary_exact')
    run_case('full_target_reachable', s, q, [0, 1], Fraction(-10), Fraction(10), Fraction(9, 10),
             'reachable', 'stationary_exact')
    run_case('full_target_equality', s, q, [0, 1], Fraction(-10), Fraction(10), Fraction(1),
             'excluded', 'stationary_exact')
    run_case('zero_frequency', clique(weight=0.0, degree=0.5), q, [0], Fraction(-10), Fraction(10),
             Fraction(1, 2), 'reachable', 'stationary_exact')
    run_case('singleton_graph', clique(n=1), source([(1, 1)]), [0], Fraction(-1), Fraction(1), Fraction(1),
             'excluded', 'stationary_exact')
    run_case('uniform_source_stationary', s, source([(1, 1), (1, 1)]), [0], Fraction(0), Fraction(50),
             Fraction(1, 2), 'excluded', 'stationary_exact')

    qi = source([(1, 0), (0, 1)])
    mi = prepare_model(s, qi, [1])
    require(mi.b == 0 and mi.c == Fraction(1, 2), 'imaginary_source_sign')
    run_case('imaginary_sign_positive_time', s, qi, [1], Fraction(1, 4), Fraction(1, 4), Fraction(1, 2), 'reachable')
    run_case('imaginary_sign_negative_time', s, qi, [1], Fraction(-1, 4), Fraction(-1, 4), Fraction(1, 2), 'excluded')

    for name, raw in [('subnormal_source', source([(float.fromhex('0x0.0000000000001p-1022'), 0), (0, 0)])),
                      ('huge_source', source([(1e308, 0), (0, 0)]))]:
        mm = prepare_model(s, raw, [1])
        require((mm.a, mm.b, mm.c) == (m.a, m.b, m.c), name + '_normalization')
        run_case(name, s, raw, [1], Fraction(0), Fraction(3), Fraction(9, 10), 'reachable')
    narrow_start = Fraction.from_float(math.pi / 2)
    narrow_end = Fraction.from_float(math.nextafter(math.pi / 2, math.inf))
    run_case('one_ulp_peak_window', s, q, [1], narrow_start, narrow_end, 1 - Fraction(1, 2 ** 150), 'reachable')
    huge = run_case('huge_phase_window', s, q, [1], bits(1e300), bits(1.1e300), Fraction(9, 10),
                    'reachable', 'critical_point')
    tlo, thi = map(Fraction, (huge['evidence']['time_enclosure']['lower'], huge['evidence']['time_enclosure']['upper']))
    require(bits_fraction(bits(1e300)) <= tlo <= thi <= bits_fraction(bits(1.1e300)), 'huge_critical_witness_inside_window')
    require((tlo.denominator & (tlo.denominator - 1)) == 0 and (thi.denominator & (thi.denominator - 1)) == 0,
            'critical_time_bounds_are_dyadic')

    with ctx.workprec(1200):
        actual = (arb(1) - arb(2).cos()) / 2
        near = ball_bounds(actual.mid())[0]
    escalated = run_case('precision_escalates_only_on_overlap', s, q, [1], Fraction(1), Fraction(1),
                        near + Fraction(1, 2 ** 200), 'excluded')
    require(escalated['resources']['attempted_precisions'] == [128, 256], 'precision_ladder_stops_after_decision')
    uncertain = run_case('precision_cap_abstains', s, q, [1], Fraction(1), Fraction(1), near,
                        'unknown', 'precision_cap')
    require(uncertain['resources']['attempted_precisions'] == [128, 256, 512], 'all_precision_levels_recorded')

    for name, mutate in [
        ('near_clique_weight', lambda x: x['laplacian_bits'][0].__setitem__(1, bits(math.nextafter(-1.0, 0.0)))),
        ('unequal_degree', lambda x: x['laplacian_bits'][1].__setitem__(1, bits(math.nextafter(1.0, 2.0)))),
    ]:
        changed = copy.deepcopy(s)
        mutate(changed)
        run_case(name, changed, q, [1], Fraction(0), Fraction(3), Fraction(1, 2), 'out_of_scope')
    reject(lambda: certify_window(s, q, [1], Fraction(2), Fraction(1), Fraction(1, 2)), 'reversed_window_rejected')
    reject(lambda: certify_window(s, q, [1], Fraction(0), Fraction(1), Fraction(2)), 'invalid_threshold_rejected')
    reject(lambda: prepare_model(s, source([(0, 0), (0, 0)]), [1]), 'zero_source_rejected')
    reject(lambda: prepare_model(s, q, [1, 1]), 'duplicate_target_rejected')
    reject(lambda: certify_window(s, q, [1], Fraction(0), Fraction(1), Fraction(1, 2), precisions=(128, 1024)), 'precision_cap_enforced')

    for trial in range(30):
        n = 2 + trial % 3
        weight = [0.1, 0.25, 0.375][trial % 3]
        # Nonzero delta is intentional: the represented diagonal is retained.
        snapshot = clique(n=n, weight=weight)
        raw = source([(rng.randint(-5, 5) / 4, rng.randint(-5, 5) / 4) for _ in range(n)])
        if all(x['re_bits'] == bits(0.) and x['im_bits'] == bits(0.) for x in raw):
            raw[0]['re_bits'] = bits(1.)
        targets = [i for i in range(n) if (trial + i) % 2]
        model = prepare_model(snapshot, raw, targets)
        t = Fraction(rng.randint(-20, 20), 7)
        direct_lo, direct_hi = full_matrix_mass(snapshot, raw, targets, t)
        harmonic = point_enclosure(model, t, 128)
        hlo, hhi = Fraction(harmonic['lower']), Fraction(harmonic['upper'])
        require(hlo <= direct_hi and direct_lo <= hhi, 'independent_full_matrix_oracle_overlap')
        require(direct_hi - direct_lo < Fraction(1, 2 ** 300), 'independent_matrix_reference_tight')
        require(max(abs(hlo - direct_hi), abs(hhi - direct_lo)) < Fraction(1, 2 ** 100), 'matrix_scalar_agreement')
        dl, du = map(Fraction, derivative_enclosure(model, t - Fraction(1, 16), t + Fraction(1, 16), 128).values())
        with ctx.workprec(384):
            exact_derivative = qa(model.omega) * (-qa(model.b) * qa(model.omega * t).sin()
                                                       + qa(model.c) * qa(model.omega * t).cos())
            rl, ru = ball_bounds(exact_derivative)
        require(dl <= rl <= ru <= du, 'whole_interval_derivative_contains_point')
    represented = prepare_model(clique(n=4, weight=0.1), source([(1, 0)] + [(0, 0)] * 3), [1])
    require(represented.degree - 3 * represented.weight != 0, 'represented_diagonal_offset_preserved')

    report = {'schema': 'gabriel-window-certificate-checks/v1', 'passed': True,
              'check_count': sum(COUNTS.values()), 'checks': dict(sorted(COUNTS.items())),
              'implementation': implementation_identity(), 'certificates': CERTIFICATES,
              'scope': 'synthetic exact-model and bounded numerical verification; no external forecasting claim'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, sort_keys=True, indent=2) + '\n')
    print(json.dumps({'passed': True, 'check_count': report['check_count'],
                      'certificate_count': len(CERTIFICATES), 'output': str(args.output)}, sort_keys=True))


if __name__ == '__main__':
    main()
