#!/usr/bin/env python3
"""Independent synthetic algebra checks; does not load the Rust implementation."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import scipy
from scipy.linalg import expm


SEED = 20260927
TOL = 2e-11
TIMES = (0.0, 0.125, 0.5, math.pi / 4, math.pi / 2, -0.7, 5.25)


def normalized_mass(state, source, indices):
    scale = max(np.max(np.abs(source.real)), np.max(np.abs(source.imag)))
    if not scale > 0:
        raise ValueError('nonzero source required')
    den = np.sum(np.abs(source / scale) ** 2)
    return float(np.sum(np.abs(state[indices] / scale) ** 2) / den)


def clique_mass(source, indices, n, weight, time):
    mu = np.mean(source)
    z = mu * np.sum(np.conjugate(source[indices]))
    a = np.sum(np.abs(source[indices]) ** 2)
    theta = n * weight * time
    return float((a + 2 * (1 - np.cos(theta)) *
                  (len(indices) * abs(mu) ** 2 - z.real) -
                  2 * np.sin(theta) * z.imag) / np.sum(np.abs(source) ** 2))


def run():
    rng = np.random.default_rng(SEED)
    records = []
    errors = dict(regional_formula=0.0, classical_mixture=0.0,
                  phase_scale=0.0, permutation=0.0, norm=0.0,
                  rank_residual_complex=0.0, rank_residual_real=0.0,
                  stationary_source=0.0)
    counts = dict(formula_cases=0, classical_cases=0, invariant_cases=0,
                  rank_cases=0, stationary_cases=0)
    for n in (1, 2, 3, 7, 13):
        for w in (0.25, 1.0, 1.7):
            diagonal = float((n - 1) * w)
            matrix = np.full((n, n), -w)
            np.fill_diagonal(matrix, diagonal)
            region = np.arange(0, n, 2)
            sources = {
                'complex': rng.normal(size=n) + 1j * rng.normal(size=n),
                'real': rng.normal(size=n).astype(complex),
                'basis': np.eye(n, dtype=complex)[0],
            }
            propagators = [expm(-1j * t * matrix) for t in TIMES]
            p = np.arange(1, n + 1, dtype=float)
            p /= np.sum(p)
            for time, u in zip(TIMES, propagators):
                beta = 4 * np.sin(n * w * time / 2) ** 2 / n
                got = np.abs(u) ** 2 @ p
                expected = (1 - beta) * p + beta * np.mean(p)
                errors['classical_mixture'] = max(errors['classical_mixture'],
                                                  float(np.max(np.abs(got-expected))))
                counts['classical_cases'] += 1
            for kind, source in sources.items():
                source /= np.linalg.norm(source)
                intensities = []
                expected_readouts, actual_readouts = [], []
                for time, u in zip(TIMES, propagators):
                    evolved = u @ source
                    actual = normalized_mass(evolved, source, region)
                    expected = clique_mass(source, region, n, w, time)
                    actual_readouts.append(actual)
                    expected_readouts.append(expected)
                    errors['regional_formula'] = max(errors['regional_formula'],
                                                      abs(actual - expected))
                    errors['norm'] = max(errors['norm'],
                                         abs(float(np.vdot(evolved, evolved).real) - 1))
                    counts['formula_cases'] += 1
                    intensities.append(np.abs(evolved) ** 2)
                    for factor in (np.exp(0.71j), 1e-80, 1e80, -2.3j):
                        scaled = normalized_mass(u @ (factor * source), factor * source, region)
                        errors['phase_scale'] = max(errors['phase_scale'], abs(scaled - actual))
                        counts['invariant_cases'] += 1
                values = np.asarray(intensities).T
                singular = np.linalg.svd(values, compute_uv=False)
                bound = 3 if kind == 'complex' else 2
                residual = float(singular[bound]) if len(singular) > bound else 0.0
                key = 'rank_residual_complex' if kind == 'complex' else 'rank_residual_real'
                errors[key] = max(errors[key], residual)
                counts['rank_cases'] += 1
                records.append(dict(n=n, weight=w, diagonal=diagonal, source_kind=kind,
                    source_real=source.real.tolist(), source_imag=source.imag.tolist(),
                    region=region.tolist(), formula=expected_readouts, scipy=actual_readouts,
                    singular_values=singular.tolist()))
            for source in (np.ones(n, dtype=complex),
                           np.arange(n, dtype=float).astype(complex) - (n - 1) / 2):
                if not np.linalg.norm(source):
                    continue
                source /= np.linalg.norm(source)
                for u in propagators:
                    errors['stationary_source'] = max(errors['stationary_source'],
                        float(np.max(np.abs(np.abs(u @ source) ** 2 - np.abs(source) ** 2))))
                    counts['stationary_cases'] += 1
            # General permutation test: the inverse map transforms region labels.
            perm = rng.permutation(n)
            inv = np.argsort(perm)
            source = sources['complex']
            u = expm(-0.713j * matrix)
            up = expm(-0.713j * matrix[np.ix_(perm, perm)])
            first = normalized_mass(u @ source, source, region)
            second = normalized_mass(up @ source[perm], source[perm], inv[region])
            errors['permutation'] = max(errors['permutation'], abs(first - second))
            counts['invariant_cases'] += 1

    two = np.array([[1., -1.], [-1., 1.]])
    u = expm(-1j * math.pi / 4 * two)
    source = np.array([1., 1j]) / math.sqrt(2)
    coherent = np.abs(u @ source) ** 2
    mixture = np.abs(u) ** 2 @ np.array([0.5, 0.5])
    assert np.max(np.abs(coherent - [0, 1])) < TOL
    assert np.max(np.abs(mixture - [0.5, 0.5])) < TOL
    directed = np.array([[0., 1., 0.], [0., 0., 1.], [1., 0., 0.]])
    projection = (directed + directed.T) / 2
    assert np.array_equal(projection, (directed.T + directed) / 2)
    assert not np.array_equal(directed, directed.T)
    assert all(value < TOL for value in errors.values()), errors
    return dict(status='passed', kind='synthetic independent algebra diagnostics',
                executes_rust_engine=False, seed=SEED, absolute_tolerance=TOL,
                numpy=np.__version__, scipy=scipy.__version__, times=list(TIMES),
                counts=counts, max_errors=errors,
                coherent_counterexample=coherent.tolist(),
                incoherent_counterexample=mixture.tolist(),
                directed_projection_alias=True, records=records)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[1] /
                        'results' / 'engine_observer_math_checks.json')
    args = parser.parse_args()
    result = run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    print(json.dumps({key: value for key, value in result.items() if key != 'records'}, indent=2))
