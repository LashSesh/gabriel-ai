"""Independent replay and causality checks for the frozen ECB risk study.

The numerical reference below does not import production forecast, state, tail,
score or metric helpers. It sorts loss scenarios in final forecast units and
integrates the empirical upper tail with its fractional boundary mass. Extended
precision is a cross-check, not an interval enclosure or arithmetic certificate.
Production imports occur only inside explicit function-under-test checks.
"""
from pathlib import Path
from fractions import Fraction
import csv
import hashlib
import io
import json
import math
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
FROZEN_PROTOCOL_HASH = '04f39c50fb6d7eab9d59bad70548fa23dc15cc964816e37db7cad8baf73bde93'
ATOL = 1e-10
RTOL = 1e-10


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def compare(actual, expected, name):
    actual = np.asarray(actual)
    expected = np.asarray(expected)
    require(actual.shape == expected.shape, name + ': shape')
    require(np.allclose(actual, expected, atol=ATOL, rtol=RTOL,
                        equal_nan=True), name + ': numerical mismatch')
    finite = np.isfinite(actual) & np.isfinite(expected)
    return float(np.max(np.abs(actual[finite] - expected[finite]))) if finite.any() else 0.0


def reference_states(rates, initial, halflives):
    """Scalar extended-precision recursion, independently parsed decimal rates."""
    q = np.full((len(rates), len(halflives), rates.shape[1]), np.nan,
                dtype=np.longdouble)
    losses = np.log(rates[1:] / rates[:-1]) * np.longdouble(100)
    for c in range(rates.shape[1]):
        for k, half in enumerate(halflives):
            decay = np.exp(-np.log(np.longdouble(2)) / half)
            state = sum(v * v for v in losses[:initial, c]) / initial
            q[initial, k, c] = state
            for t in range(initial + 1, len(rates)):
                state = decay * state + (1 - decay) * losses[t - 1, c] ** 2
                q[t, k, c] = state
    return q


def reference_tail(scenarios, alpha):
    """Integral of the empirical quantile function, using a descending sort."""
    ordered = np.sort(scenarios, axis=1)[:, ::-1]
    n = ordered.shape[1]
    mass = (1 - alpha) * n
    whole = mass.numerator // mass.denominator
    remainder = mass - whole
    sums = np.sum(ordered[:, :whole], axis=1, dtype=np.longdouble)
    if remainder:
        sums += (np.longdouble(remainder.numerator) / remainder.denominator) * ordered[:, whole]
    expected_shortfall = sums / (np.longdouble(mass.numerator) / mass.denominator)
    # At alpha=0 use the minimum of the finite support as the reported quantile.
    ascending_index = max(0, (alpha.numerator * n + alpha.denominator - 1) // alpha.denominator - 1)
    quantile = ordered[:, n - 1 - ascending_index]
    return quantile, expected_shortfall


def reference_forecasts(rates, states, c, h, protocol):
    initial, window = protocol['variance_initial_observations'], protocol['window']
    origins = np.arange(initial + h + window - 1, len(rates) - h)
    endpoints = origins[:, None] - np.arange(window - 1, -1, -1)[None, :]
    starts = endpoints - h
    require(starts.min() == initial, 'first scenario state is not initialized')
    require(np.all(endpoints <= origins[:, None]), 'future scenario endpoint')
    history = 100 * np.log(rates[endpoints, c] / rates[starts, c])
    columns = [history]
    for text in protocol['fast_weights']:
        frac = Fraction(text)
        w = np.longdouble(frac.numerator) / frac.denominator
        v = w * states[:, 0, c] + (1 - w) * states[:, 1, c]
        # Direct final-unit scenarios avoid production's normalize/tail/rescale path.
        columns.append(history * np.sqrt(v[origins, None] / v[starts]))
    pairs = [reference_tail(s, Fraction(protocol['alpha'])) for s in columns]
    q = np.stack([item[0] for item in pairs], axis=1)
    e = np.stack([item[1] for item in pairs], axis=1)
    y = 100 * np.log(rates[origins + h, c] / rates[origins, c])
    return origins, q, e, y


def scores(q, e, y, alpha):
    tail_inverse = np.longdouble(alpha.denominator) / (alpha.denominator - alpha.numerator)
    require(np.isfinite(q).all() and np.isfinite(e).all() and np.isfinite(y).all(), 'nonfinite score input')
    require(np.all(e > 0) and np.all(q <= e), 'invalid VaR/ES order or ES sign')
    excess = np.maximum(y - q, 0)
    return np.log(e) - 1 + q / e + tail_inverse * excess / e


def summary(q, e, y, alpha):
    invtail = np.longdouble(alpha.denominator) / (alpha.denominator - alpha.numerator)
    n = len(y)
    hits = int(np.count_nonzero(y > q))
    return dict(n=n, mean_fz0=float(np.mean(scores(q, e, y, alpha))),
                exceedances=hits, exceedance_fraction=hits/n,
                mean_es_identification_residual=float(np.mean(q + invtail*np.maximum(y-q, 0) - e)),
                mean_var=float(np.mean(q)), mean_es=float(np.mean(e)))


def check_summary(actual, reference, name):
    require(actual.keys() == reference.keys(), name + ': metric keys')
    worst = 0.0
    for key, value in reference.items():
        if isinstance(value, int):
            require(actual[key] == value, name + ': ' + key)
        else:
            worst = max(worst, compare(actual[key], value, name + ': ' + key))
    return worst


def exact_tail_checks(seed):
    from ecb_risk import tail, fz_score  # Functions under test only.
    rng = np.random.default_rng(seed)
    n_cases = 0
    worst = 0.0
    for n in [1, 2, 3, 5, 7, 10, 39, 40, 41, 250]:
        for alpha in map(Fraction, ['0', '1/2', '3/4', '37/40', '39/40']):
            for values in [np.arange(n)-n//2, np.zeros(n, dtype=int), rng.integers(-40, 41, size=n)]:
                ordered = sorted(map(int, values))
                k = max(0, math.ceil(alpha*n)-1)
                q = ordered[k]
                # Exact rational CVaR optimization objective at an empirical quantile.
                es = Fraction(q) + sum(Fraction(max(v-q, 0)) for v in ordered) / (n*(1-alpha))
                foundq, founde = tail(np.array([values], dtype=float), str(alpha))
                require(foundq[0] == q, 'exact finite tail quantile')
                worst = max(worst, compare(founde[0], float(es), 'exact finite tail ES'))
                n_cases += 1
    invalid = [(1, 0, 0), (1, -1, 0), (2, 1, 0), (0, 1, float('nan'))]
    for q, e, y in invalid:
        try:
            fz_score(q, e, y)
        except ValueError:
            continue
        raise AssertionError('invalid FZ input accepted')
    return dict(exact_rational_cases=n_cases, max_absolute_es_difference=worst,
                invalid_score_cases_rejected=len(invalid))


def causality_checks(rates, dates, protocol, contracts):
    from ecb_risk import forecast_candidates  # Function under test only.
    base_state, base = forecast_candidates(rates, protocol)
    cuts = [500, int(np.searchsorted(dates, '2020-01-01'))-1,
            int(np.searchsorted(dates, '2022-07-01'))-1]
    rng = np.random.default_rng(protocol['seed_for_verification_only'])
    cases = []
    selection_tests = 0
    for cut in cuts:
        altered = rates.copy()
        altered[cut+1:] *= np.exp(rng.normal(0, .35, size=altered[cut+1:].shape))
        perturbed_state, perturbed = forecast_candidates(altered, protocol)
        truncated_state, truncated = forecast_candidates(rates[:cut+1], protocol)
        require(np.array_equal(base_state[:cut+1], perturbed_state[:cut+1], equal_nan=True), 'future mutation changed past state')
        require(np.array_equal(base_state[:cut+1], truncated_state, equal_nan=True), 'truncation changed state')
        rows = 0
        for key, (origins, q, e) in base.items():
            keep = origins <= cut
            for comparison in [perturbed, truncated]:
                o2, q2, e2 = comparison[key]
                k2 = o2 <= cut
                require(np.array_equal(origins[keep], o2[k2]), 'causal origin mismatch')
                require(np.array_equal(q[keep], q2[k2]), 'future changed past VaR')
                require(np.array_equal(e[keep], e2[k2]), 'future changed past ES')
            rows += int(keep.sum()) * q.shape[1]
        if dates[cut] == '2019-12-31':
            for comparison, x in [(perturbed, altered), (truncated, rates[:cut+1])]:
                for item in contracts:
                    c = protocol['currencies'].index(item['currency'])
                    h = item['horizon']
                    origins, q, e = comparison[c, h]
                    ends = origins+h
                    keep = (origins >= np.searchsorted(dates, protocol['development'][0])) & (ends <= cut)
                    o = origins[keep]
                    y = 100*np.log(x[o+h, c]/x[o, c])
                    means = scores(q[keep, 1:], e[keep, 1:], y[:, None], Fraction(protocol['alpha'])).mean(axis=0)
                    chosen = min(range(len(means)), key=lambda i: (means[i], i))
                    require(protocol['fast_weights'][chosen] == item['selected_weight'], 'future affected development selection')
                    for j, weight in enumerate(protocol['fast_weights']):
                        compare(means[j], item['development_candidate_fz0'][weight], 'mutation selection score')
                    selection_tests += 1
        cases.append(dict(last_retained_date=str(dates[cut]), prefix_observations=cut+1,
                          forecast_pairs_bitwise_unchanged_per_variant=rows,
                          variants=['positive_random_future_perturbation', 'suffix_truncation']))
    return dict(cases=cases, development_selection_rechecks=selection_tests,
                seed=protocol['seed_for_verification_only'])


def main():
    started = time.perf_counter()
    protocol_path = ROOT/'results/ecb_risk_protocol.json'
    protocol = json.loads(protocol_path.read_text())
    require(sha256(protocol_path) == FROZEN_PROTOCOL_HASH, 'frozen protocol hash')
    result_path = ROOT/'results/ecb_risk_results.json'
    results = json.loads(result_path.read_text())
    source = ROOT/'data/ecb_eurofxref-hist_20260926.csv'
    require(sha256(source) == protocol['source_csv_sha256'] == results['source_csv_sha256'], 'CSV source checksum')
    require(results['protocol_sha256'] == FROZEN_PROTOCOL_HASH, 'result protocol hash')
    for name, digest in results['source_sha256'].items():
        require(sha256(ROOT/'reproduction'/name) == digest, 'production source checksum: '+name)
    pred_path = ROOT/'results/ecb_risk_predictions.npz'
    require(sha256(pred_path) == results['predictions_sha256'], 'prediction archive checksum')
    records = sorted(csv.DictReader(io.StringIO(source.read_text())), key=lambda r:r['Date'])
    dates = np.array([r['Date'] for r in records])
    require(len(set(dates)) == len(dates) and np.all(dates[:-1] < dates[1:]), 'unique ordered dates')
    rates = np.array([[np.longdouble(r[c]) for c in protocol['currencies']] for r in records])
    require(np.isfinite(rates).all() and np.all(rates > 0), 'positive complete raw data')
    require(results['raw_observations'] == len(dates), 'raw observation count')
    require(results['raw_date_range'] == [str(dates[0]), str(dates[-1])], 'raw date range')
    archive = np.load(pred_path, allow_pickle=False)
    require(np.array_equal(archive['dates'], dates), 'archived dates')
    require(np.array_equal(archive['rates'], rates.astype(float)), 'archived rates')
    states = reference_states(rates, protocol['variance_initial_observations'], protocol['variance_halflives_observed_intervals'])
    errors = dict(variances=compare(archive['variances'], states, 'state replay'),
                  var=0.0, es=0.0, realized=0.0, metrics=0.0, selection=0.0)
    pair_count = 0
    metric_records = 0
    test_cases = 0
    checked_contracts = []
    alpha = Fraction(protocol['alpha'])
    expected_contracts = {(c, h) for c in protocol['currencies'] for h in protocol['horizons_observed_intervals']}
    require({(x['currency'], x['horizon']) for x in results['contracts']} == expected_contracts, 'contract coverage')
    require(len(results['contracts']) == len(expected_contracts), 'duplicate contracts')
    for item in results['contracts']:
        name, h = item['currency'], item['horizon']
        c = protocol['currencies'].index(name)
        key = name+'_'+str(h)
        origins, q, e, y = reference_forecasts(rates, states, c, h, protocol)
        require(np.array_equal(archive[key+'_origins'], origins), key+': origins')
        for suffix, ref, err in [('candidate_var', q, 'var'), ('candidate_es', e, 'es'), ('realized', y, 'realized')]:
            errors[err] = max(errors[err], compare(archive[key+'_'+suffix], ref, key+': '+suffix))
        pair_count += q.size
        # Explicit four-bound checks, rather than relying on ordered endpoints.
        masks = {}
        for period in ['development', 'test']:
            lo, hi = protocol[period]
            mask = (dates[origins] >= lo) & (dates[origins] <= hi) & (dates[origins+h] >= lo) & (dates[origins+h] <= hi)
            masks[period] = mask
            record = dict(n=int(mask.sum()), first_origin=str(dates[origins[mask][0]]),
                          last_origin=str(dates[origins[mask][-1]]), last_target=str(dates[origins[mask][-1]+h]))
            require(item['periods'][period] == record, key+': '+period+' period')
        require(not np.any(masks['development'] & masks['test']), 'overlapping development/test decisions')
        test_cases += int(masks['test'].sum())
        means = scores(q[masks['development'], 1:], e[masks['development'], 1:], y[masks['development'], None], alpha).mean(axis=0)
        chosen = min(range(len(means)), key=lambda i: (means[i], i))
        require(item['selected_weight'] == protocol['fast_weights'][chosen], key+': development-selected weight')
        require(list(item['development_candidate_fz0']) == protocol['fast_weights'], 'weight order')
        for j, weight in enumerate(protocol['fast_weights']):
            errors['selection'] = max(errors['selection'], compare(item['development_candidate_fz0'][weight], means[j], key+': development grid score'))
        expected_columns = [0, 1+protocol['fast_weights'].index('1'), 1+protocol['fast_weights'].index('0'),
                            1+protocol['fast_weights'].index(protocol['primary_weight']), 1+chosen]
        require(item['candidate_columns'] == expected_columns, key+': candidate columns')
        require(list(item['models']) == protocol['models'], key+': model order')
        for model, col in zip(protocol['models'], expected_columns):
            for period, mask in masks.items():
                ref = summary(q[mask, col], e[mask, col], y[mask], alpha)
                errors['metrics'] = max(errors['metrics'], check_summary(item['models'][model][period], ref, key+'/'+model+'/'+period))
                metric_records += 1
            annual_total = 0
            for year in range(2020, 2026):
                mask = masks['test'] & (dates[origins] >= str(year)+'-01-01') & (dates[origins] <= str(year)+'-12-31')
                ref = summary(q[mask, col], e[mask, col], y[mask], alpha)
                errors['metrics'] = max(errors['metrics'], check_summary(item['models'][model]['yearly_test'][str(year)], ref, key+'/'+model+'/'+str(year)))
                annual_total += int(mask.sum())
                metric_records += 1
            require(annual_total == int(masks['test'].sum()), 'yearly counts')
        checked_contracts.append(dict(currency=name, horizon=h, archive_forecast_pairs=q.size,
                                      development_n=int(masks['development'].sum()), test_n=int(masks['test'].sum()),
                                      selected_weight=item['selected_weight'],
                                      minimum_development_selection_gap=float(np.sort(means)[1]-np.sort(means)[0])))
    require(results['test_contract_cases'] == test_cases, 'test cases')
    require(results['test_forecast_pairs'] == test_cases*len(protocol['models']), 'test pairs')
    tails = exact_tail_checks(protocol['seed_for_verification_only'])
    causal = causality_checks(rates.astype(float), dates, protocol, results['contracts'])
    out = dict(schema='gabriel.ecb-risk.verification.v1', status='passed',
               protocol_sha256=FROZEN_PROTOCOL_HASH, source_csv_sha256=sha256(source),
               prediction_archive_sha256=sha256(pred_path), results_sha256=sha256(result_path),
               verifier_sha256=sha256(Path(__file__)), raw_rows=len(dates),
               independently_recomputed_forecast_pairs=pair_count,
               metric_records_recomputed=metric_records, test_contract_cases=test_cases,
               test_forecast_pairs=test_cases*len(protocol['models']),
               reference='independent extended-precision states and final-unit sorted scenario integration; exact rational finite-tail test cases',
               tolerance=dict(absolute=ATOL, relative=RTOL), maximum_absolute_differences=errors,
               longdouble_mantissa_bits=int(np.finfo(np.longdouble).nmant),
               exact_tail_tests=tails, causality=causal, contracts=checked_contracts,
               limits=['No directed-rounding or interval certificate for logarithms or variance estimates.',
                       'Current revised snapshot; no historical release vintages or as-was-known execution backtest.',
                       'Overlapping horizons and currencies share observations; row counts are not independent sample sizes.',
                       'Yearly metrics group by forecast-origin year; a target can cross a year boundary within the same development/test period.',
                       'Empirical comparison is descriptive; no population significance or universal-superiority claim.'],
               seconds=time.perf_counter()-started)
    (ROOT/'results/ecb_risk_verification.json').write_text(json.dumps(out, indent=2, allow_nan=False)+'\n')
    print(json.dumps({k:out[k] for k in ['status', 'independently_recomputed_forecast_pairs',
                                      'metric_records_recomputed', 'maximum_absolute_differences', 'seconds']}, indent=2))


if __name__ == '__main__':
    main()
