"""Independent Fraction replay of the adaptive risk calibration layer.

The reference controller below does not import the production controller, its
integer lattice, its selection or metric helpers. Its inputs are the archived
parent forecasts, compared against the independently checked parent experiment.
Float forecast scaling and log losses are cross-checked, not interval certified.
Imports of production functions appear only in function-under-test checks.
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
PROTOCOL_HASH = 'e5723e6f160b37ae552bff2ac11573dfeab7d6d7f4e1f5f4fab3249542285aa9'
ATOL = 1e-10
RTOL = 1e-10


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compare(actual, expected, name):
    actual, expected = np.asarray(actual), np.asarray(expected)
    require(actual.shape == expected.shape, name + ': shape')
    require(np.allclose(actual, expected, atol=ATOL, rtol=RTOL, equal_nan=True), name + ': values')
    finite = np.isfinite(actual) & np.isfinite(expected)
    maximum = float(np.max(np.abs(actual[finite] - expected[finite]))) if finite.any() else 0.0
    return maximum


def exact_array(actual, expected, name):
    require(np.array_equal(actual, expected), name + ': exact array')


def independent_controller(origins, base_q, base_e, rates, h, eta, pooled=False):
    """Receipt-index replay with immutable issued thresholds and Fraction state."""
    eta, beta = Fraction(eta), Fraction(1, 40)
    lower, upper = Fraction(-1), Fraction(1)
    origins = np.asarray(origins)
    count = len(origins)
    index = {int(t): i for i, t in enumerate(origins)}
    state = [Fraction(0) for _ in range(1 if pooled else h)]
    denominator = 40 * eta.denominator
    out = dict(var=np.empty(count), es=np.empty(count),
               issued_units=np.empty(count, dtype=np.int64),
               matured_hit=np.full(count, -1, dtype=np.int64),
               preupdate_units=np.zeros(count, dtype=np.int64),
               postupdate_units=np.zeros(count, dtype=np.int64),
               projection_units=np.zeros(count, dtype=np.int64))
    for i, event in enumerate(origins):
        t = int(event)
        if t-h in index:
            old = index[t-h]
            lane = 0 if pooled else (t-h) % h
            observed_loss = 100 * math.log(float(rates[t]) / float(rates[t-h]))
            hit = int(observed_loss > out['var'][old])
            before = state[lane]
            unconstrained = before + eta * (hit-beta)
            after = min(upper, max(lower, unconstrained))
            projection = after - unconstrained
            out['matured_hit'][old] = hit
            for key, value in [('preupdate_units', before), ('postupdate_units', after),
                               ('projection_units', projection)]:
                units = value * denominator
                require(units.denominator == 1, 'reference units are integral')
                out[key][old] = units.numerator
            state[lane] = after
        lane = 0 if pooled else t % h
        theta = state[lane]
        units = theta * denominator
        require(units.denominator == 1, 'issued reference units are integral')
        out['issued_units'][i] = units.numerator
        # A scalar libm exponential is independent of a vectorized production path.
        scale = math.exp(float(theta))
        out['var'][i] = float(base_q[i]) * scale
        out['es'][i] = float(base_e[i]) * scale
    return out, denominator


def independent_metrics(q, e, y):
    q, e, y = [np.asarray(a, dtype=np.longdouble) for a in (q, e, y)]
    require(len(y) > 0, 'empty metric selection')
    require(np.isfinite(q).all() and np.isfinite(e).all() and np.isfinite(y).all(), 'finite metrics')
    require(np.all((q > 0) & (e >= q)), 'metric forecast order')
    excess = np.maximum(y-q, 0)
    hit = int(np.count_nonzero(y > q))
    score = np.log(e) - 1 + q/e + 40*excess/e
    residual = q + 40*excess-e
    return dict(n=len(y), mean_fz0=float(np.mean(score)), exceedances=hit,
                exceedance_fraction=hit/len(y),
                absolute_frequency_gap_from_beta=abs(hit/len(y)-1/40),
                mean_es_identification_residual=float(np.mean(residual)),
                mean_var=float(np.mean(q)), mean_es=float(np.mean(e)))


def independent_strata(q):
    values = np.asarray(q)
    medians = np.full(len(values), np.nan)
    strata = np.full(len(values), -1, dtype=np.int64)
    for i in range(1, len(values)):
        medians[i] = np.median(values[max(0, i-250):i])
        strata[i] = int(values[i] > medians[i])
    return strata, medians


def accounting(reference, denominator, eta, mask):
    before = reference['preupdate_units'][mask]
    after = reference['postupdate_units'][mask]
    projected = reference['projection_units'][mask]
    hits = reference['matured_hit'][mask]
    require(np.all(hits >= 0), 'accounting includes immature outcome')
    state_change = Fraction(sum(int(a)-int(b) for a, b in zip(after, before)), denominator)
    projection = Fraction(sum(map(int, projected)), denominator)
    feedback = Fraction(eta)*(int(hits.sum())-Fraction(len(hits), 40))
    require(state_change == feedback + projection, 'exact state accounting')
    return dict(n=len(hits), hits=int(hits.sum()), projection_count=int(np.count_nonzero(projected)),
                state_change=state_change, feedback=feedback, signed_projection=projection,
                residual=state_change-feedback-projection)


def production_checks(protocol, dates, rates, parent_protocol):
    from adaptive_risk import replay_controller  # Function under test only.
    from ecb_risk import forecast_candidates  # Previously checked function under test.
    seed = protocol['verification_seed']
    rng = np.random.default_rng(seed)
    _, baseline = forecast_candidates(rates, parent_protocol)
    variants = []
    compared = 0
    selection_rechecks = 0
    selections = {(z['currency'], z['horizon']): z for z in json.loads((ROOT/'results/adaptive_risk_results.json').read_text())['contracts']}
    for cut in [500, int(np.searchsorted(dates, '2020-01-01'))-1,
                int(np.searchsorted(dates, '2026-01-01'))-1]:
        changed = rates.copy()
        changed[cut+1:] *= np.exp(rng.normal(0, .04, size=changed[cut+1:].shape))
        for label, x in [('future_perturbation', changed), ('suffix_truncation', rates[:cut+1])]:
            _, candidates = forecast_candidates(x, parent_protocol)
            for (currency, h), (origins, q, e) in baseline.items():
                kept = origins <= cut
                o2, q2, e2 = candidates[currency, h]
                keep2 = o2 <= cut
                exact_array(origins[kept], o2[keep2], 'prefix origins')
                exact_array(q[kept], q2[keep2], 'prefix parent VaR')
                exact_array(e[kept], e2[keep2], 'prefix parent ES')
                for lanes in [True, False]:
                    expected = replay_controller(origins, q[:, 5], e[:, 5], rates[:, currency], h,
                                                 protocol['primary_eta'], lanes=lanes)
                    actual = replay_controller(o2, q2[:, 5], e2[:, 5], x[:, currency], h,
                                               protocol['primary_eta'], lanes=lanes)
                    for field in ['var', 'es', 'issued_units']:
                        exact_array(expected[field][kept], actual[field][keep2], 'causal '+field)
                    matured_before_cut = origins+h <= cut
                    m2 = o2+h <= cut
                    for field in ['matured_hit', 'preupdate_units', 'postupdate_units', 'projection_units']:
                        exact_array(expected[field][matured_before_cut], actual[field][m2], 'matured causal '+field)
                    compared += int(kept.sum())
                if dates[cut] == '2019-12-31':
                    development = np.zeros(len(o2), dtype=bool)
                    matured = o2+h < len(x)
                    development[matured] = ((dates[o2[matured]] >= protocol['development'][0]) &
                                             (dates[o2[matured]+h] <= protocol['development'][1]))
                    yd = 100*np.log(x[o2[development]+h,currency]/x[o2[development],currency])
                    eta_scores = []
                    for eta in protocol['eta_grid']:
                        trial = replay_controller(o2,q2[:,5],e2[:,5],x[:,currency],h,eta)
                        eta_scores.append(independent_metrics(trial['var'][development],trial['es'][development],yd)['mean_fz0'])
                    static_scores = []
                    for theta in protocol['static_theta_grid']:
                        scale = math.exp(float(Fraction(theta)))
                        static_scores.append(independent_metrics(q2[development,5]*scale,e2[development,5]*scale,yd)['mean_fz0'])
                    contract = selections[protocol['currencies'][currency],h]
                    require(int(np.argmin(eta_scores)) == contract['selected_eta_index'], 'future changed eta selection')
                    require(int(np.argmin(static_scores)) == contract['selected_static_index'], 'future changed static selection')
                    for eta, value in zip(protocol['eta_grid'], eta_scores):
                        compare(contract['development_lane_fz0'][eta], value, 'prefix eta development score')
                    for theta, value in zip(protocol['static_theta_grid'], static_scores):
                        compare(contract['development_static_fz0'][theta], value, 'prefix static development score')
                    selection_rechecks += 1
            variants.append(dict(cutoff=str(dates[cut]), variant=label))
    # A changed target is unavailable before its endpoint; the issued threshold
    # remains immutable after its outcome becomes known.
    timing = 0
    for h in [1, 5]:
        origins = np.arange(0, 30)
        q, e = np.ones(30), np.full(30, 2.)
        x = np.ones(30)
        receipt = 13
        changed = x.copy(); changed[receipt] = math.exp(.1)
        for lanes in [True, False]:
            a = replay_controller(origins, q, e, x, h, '1/20', lanes=lanes)
            b = replay_controller(origins, q, e, changed, h, '1/20', lanes=lanes)
            for field in ['var', 'es', 'issued_units']:
                exact_array(a[field][:receipt], b[field][:receipt], 'target used before maturity')
            require(a['matured_hit'][receipt-h] == 0 and b['matured_hit'][receipt-h] == 1,
                    'changed target did not alter correct matured hit')
            require(a['issued_units'][receipt] != b['issued_units'][receipt], 'feedback not applied before new issuance')
            ref, den = independent_controller(origins, q, e, changed, h, '1/20', pooled=not lanes)
            for field in ['issued_units', 'matured_hit', 'preupdate_units', 'postupdate_units', 'projection_units']:
                exact_array(b[field], ref[field], 'maturity reference '+field)
            timing += 1
    stress = 0
    for h in [1, 5]:
        origins = np.arange(0, 1200)
        q = np.full(1200, .0001); e = np.full(1200, .0002)
        for mode, x in [('upward', np.exp(np.arange(1200)*.001)), ('downward', np.ones(1200))]:
            for lanes in [True, False]:
                ref, den = independent_controller(origins, q, e, x, h, '1/5', pooled=not lanes)
                actual = replay_controller(origins, q, e, x, h, '1/5', lanes=lanes)
                for field in ref:
                    if field in ['var', 'es']:
                        compare(actual[field], ref[field], 'stress '+field)
                    else:
                        exact_array(actual[field], ref[field], 'stress exact '+field)
                require(np.count_nonzero(ref['projection_units']) > 0, 'stress did not exercise clipping')
                stress += 1
        actual = replay_controller(origins, q, e, np.ones(1200), h, '0')
        exact_array(actual['var'], q, 'zero eta VaR')
        exact_array(actual['es'], e, 'zero eta ES')
        exact_array(actual['issued_units'], np.zeros(1200, dtype=int), 'zero eta state')
    invalid = []
    args = dict(origins=np.arange(12), base_q=np.ones(12), base_e=np.full(12, 2.),
                rates_column=np.ones(12), horizon=1, eta='1/20')
    # Added after the production API settles; each mutation violates its model.
    for key, value in [('horizon', 0), ('horizon', -1), ('eta', '-1/20'),
                       ('beta', '0'), ('beta', '1'), ('bounds', ('1', '-1')),
                       ('base_q', np.zeros(12)), ('base_q', np.full(12, 3.)),
                       ('base_e', np.full(12, np.nan)),
                       ('rates_column', np.zeros(12)), ('origins', np.arange(11))]:
        test = dict(args); test[key] = value
        try:
            replay_controller(**test)
        except (ValueError, TypeError):
            invalid.append(key)
        else:
            raise AssertionError('invalid controller input accepted: '+key)
    return dict(seed=seed, prefix_variants=variants,
                prefix_controller_forecasts_checked=compared, development_selection_rechecks=selection_rechecks, maturity_timing_cases=timing,
                projection_stress_cases=stress, zero_eta_cases=2, invalid_inputs_rejected=len(invalid))



def reference_accounting_records(trace, denominator, eta, mask, origins, h, pooled=False):
    eta = Fraction(eta)
    if eta == 0:
        return None
    result = []
    for lane in range(1 if pooled else h):
        keep = mask & (np.ones(len(origins), dtype=bool) if pooled else origins % h == lane)
        idx = np.flatnonzero(keep)
        if not len(idx):
            continue
        acc = accounting(trace, denominator, eta, keep)
        stride = 1 if pooled else h
        blocks = 1 + int(np.count_nonzero(np.diff(origins[idx]) != stride))
        change_units = acc['state_change'] * denominator
        projection_units = acc['signed_projection'] * denominator
        lhs = Fraction(acc['hits'])-Fraction(len(idx), 40)
        rhs = (acc['state_change']-acc['signed_projection'])/eta
        require(lhs == rhs, 'reference exact divided identity')
        result.append(dict(lane=lane, n=len(idx), hits=acc['hits'], block_count=blocks,
                           first_origin_index=int(origins[idx[0]]), last_origin_index=int(origins[idx[-1]]),
                           first_preupdate_units=int(trace['preupdate_units'][idx[0]]),
                           last_postupdate_units=int(trace['postupdate_units'][idx[-1]]),
                           boundary_change_units=int(change_units), projection_units=int(projection_units),
                           denominator=denominator, eta=str(eta), lhs_fraction=str(lhs),
                           rhs_fraction=str(rhs), equal=True))
    return result


def compare_summary(actual, q, e, y, mask, name, trace=None, denominator=None,
                    eta=None, origins=None, h=None, pooled=False):
    if not mask.any():
        require(actual is None, name+': empty metric')
        return 0.0
    expected = independent_metrics(q[mask], e[mask], y[mask])
    if trace is None:
        expected.update(projection_count=0, signed_projection=0., signed_projection_exact='0',
                        exact_controller_accounting=None)
    else:
        acc = accounting(trace, denominator, eta, mask)
        expected.update(projection_count=acc['projection_count'],
                        signed_projection=float(acc['signed_projection']),
                        signed_projection_exact=str(acc['signed_projection']),
                        exact_controller_accounting=reference_accounting_records(
                            trace, denominator, eta, mask, origins, h, pooled))
    require(actual.keys() == expected.keys(), name+': metric keys')
    maximum = 0.0
    for key, value in expected.items():
        if isinstance(value, float):
            maximum = max(maximum, compare(actual[key], value, name+'/'+key))
        else:
            require(actual[key] == value, name+'/'+key+': exact mismatch')
    return maximum


def pending_parent_reference(rates, states, origins, c, h, parent):
    """Independent final-unit sorted tail for the previously unarchived last h rows."""
    qcols, ecols = [], []
    n, alpha = parent['window'], Fraction(parent['alpha'])
    endpoint = origins[:, None] - np.arange(n-1, -1, -1)[None, :]
    start = endpoint-h
    history = 100*np.log(rates[endpoint, c]/rates[start, c])
    scenarios = [history]
    for text in parent['fast_weights']:
        w = float(Fraction(text))
        v = w*states[:, 0, c]+(1-w)*states[:, 1, c]
        scenarios.append(history*np.sqrt(v[origins, None]/v[start]))
    for block in scenarios:
        ordered = np.sort(block, axis=1)
        quantile_index = math.ceil(alpha*n)-1
        qcols.append(ordered[:, quantile_index])
        tail_mass = (1-alpha)*n
        whole = tail_mass.numerator//tail_mass.denominator
        remainder = float(tail_mass-whole)
        ecols.append((ordered[:, n-whole:].sum(axis=1)+remainder*ordered[:, n-whole-1])/float(tail_mass))
    return np.stack(qcols, axis=1), np.stack(ecols, axis=1)


def main():
    started = time.perf_counter()
    protocol_path = ROOT/'results/adaptive_risk_protocol.json'
    p = json.loads(protocol_path.read_text())
    require(digest(protocol_path) == PROTOCOL_HASH, 'frozen adaptive protocol')
    parent_path = ROOT/'results/ecb_risk_protocol.json'
    parent = json.loads(parent_path.read_text())
    require(digest(parent_path) == p['parent_protocol_sha256'], 'parent protocol binding')
    source = ROOT/'data/ecb_eurofxref-hist_20260926.csv'
    require(digest(source) == p['source_csv_sha256'], 'source CSV binding')
    rows = sorted(csv.DictReader(io.StringIO(source.read_text())), key=lambda z:z['Date'])
    dates = np.array([row['Date'] for row in rows])
    rates = np.array([[float(row[c]) for c in p['currencies']] for row in rows])
    require(len(set(dates)) == len(dates) and np.all(dates[1:] > dates[:-1]), 'ordered unique dates')
    require(np.all(rates > 0) and np.isfinite(rates).all(), 'valid source rates')
    result_path = ROOT/'results/adaptive_risk_results.json'
    results = json.loads(result_path.read_text())
    archive_path = ROOT/'results/adaptive_risk_predictions.npz'
    require(results['protocol_sha256'] == PROTOCOL_HASH, 'result adaptive protocol')
    require(results['parent_protocol_sha256'] == digest(parent_path), 'result parent protocol')
    require(results['source_csv_sha256'] == digest(source), 'result source binding')
    require(results['predictions_sha256'] == digest(archive_path), 'adaptive archive binding')
    for filename, value in results['source_sha256'].items():
        require(digest(ROOT/'reproduction'/filename) == value, 'producer source binding '+filename)
    archive = np.load(archive_path, allow_pickle=False)
    exact_array(archive['dates'], dates, 'archived dates')
    exact_array(archive['rates'], rates, 'archived rates')
    exact_array(archive['eta_grid'], p['eta_grid'], 'eta grid')
    exact_array(archive['static_theta_grid'], p['static_theta_grid'], 'static grid')
    denominators = [40*Fraction(eta).denominator for eta in p['eta_grid']]
    exact_array(archive['eta_denominators'], denominators, 'eta denominators')
    require(results['raw_observations'] == len(dates), 'raw row count')
    require(results['raw_date_range'] == [str(dates[0]), str(dates[-1])], 'raw date range')
    require(results['design_history'] == p['design_history'], 'design-history statement')
    # Verify that the reused parent archive is precisely the one independently
    # checked previously; this phase verifies the new controller layer.
    parent_results_path = ROOT/'results/ecb_risk_results.json'
    parent_archive_path = ROOT/'results/ecb_risk_predictions.npz'
    parent_check = json.loads((ROOT/'results/ecb_risk_verification.json').read_text())
    require(parent_check['status'] == 'passed', 'parent check status')
    require(parent_check['results_sha256'] == digest(parent_results_path), 'parent result provenance')
    require(parent_check['prediction_archive_sha256'] == digest(parent_archive_path), 'parent archive provenance')
    parent_archive = np.load(parent_archive_path, allow_pickle=False)
    exact_array(parent_archive['rates'], rates, 'parent rates')
    periods = ['development', 'retrospective', 'temporal_extension']
    expected_contracts = {(c,h) for c in p['currencies'] for h in p['horizons_observed_intervals']}
    require(len(results['contracts']) == len(expected_contracts), 'number of contracts')
    require({(z['currency'], z['horizon']) for z in results['contracts']} == expected_contracts, 'contract coverage')
    errors = dict(realized=0., pending_parent_var=0., pending_parent_es=0.,
                  controller_var=0., controller_es=0., static_var=0., static_es=0., metrics=0., selection=0.)
    totals = dict(controller_forecast_pairs=0, static_forecast_pairs=0, parent_forecast_pairs_reused=0,
                  pending_parent_forecast_pairs_reconstructed=0, metric_records=0,
                  exact_accounting_records=0, pending_contract_cases=0,
                  controller_float_values_not_bitwise_equal=0, static_float_values_not_bitwise_equal=0)
    period_cases = {period:0 for period in periods}
    checked = []
    for item in results['contracts']:
        currency, h = item['currency'], item['horizon']
        c = p['currencies'].index(currency)
        key = currency+'_'+str(h)
        origins = np.arange(parent['variance_initial_observations']+h+parent['window']-1, len(dates))
        exact_array(archive[key+'_origins'], origins, key+' origins')
        matured = origins+h < len(dates)
        exact_array(archive[key+'_matured'], matured, key+' maturity mask')
        y = np.full(len(origins), np.nan)
        for i in np.flatnonzero(matured):
            t = origins[i]
            y[i] = 100*math.log(float(rates[t+h,c])/float(rates[t,c]))
        errors['realized'] = max(errors['realized'], compare(archive[key+'_realized'], y, key+' realized'))
        base_q, base_e = archive[key+'_base_candidate_var'], archive[key+'_base_candidate_es']
        require(base_q.shape == (len(origins), 6) and base_e.shape == base_q.shape, key+' base shape')
        exact_array(origins[matured], parent_archive[key+'_origins'], key+' parent origins')
        exact_array(base_q[matured], parent_archive[key+'_candidate_var'], key+' unchanged base VaR')
        exact_array(base_e[matured], parent_archive[key+'_candidate_es'], key+' unchanged base ES')
        pq, pe = pending_parent_reference(rates, parent_archive['variances'], origins[~matured], c, h, parent)
        errors['pending_parent_var'] = max(errors['pending_parent_var'], compare(base_q[~matured], pq, key+' pending base VaR'))
        errors['pending_parent_es'] = max(errors['pending_parent_es'], compare(base_e[~matured], pe, key+' pending base ES'))
        totals['parent_forecast_pairs_reused'] += int(matured.sum())*6
        totals['pending_parent_forecast_pairs_reconstructed'] += int((~matured).sum())*6
        lane_references = []
        for j, eta in enumerate(p['eta_grid']):
            trace, denominator = independent_controller(origins, base_q[:,5], base_e[:,5], rates[:,c], h, eta)
            lane_references.append((trace, denominator))
            for field, value in trace.items():
                found = archive[key+'_lane_'+field][:,j]
                if field in ['var', 'es']:
                    errors['controller_'+field] = max(errors['controller_'+field], compare(found, value, key+'/lane/'+eta+'/'+field))
                    totals['controller_float_values_not_bitwise_equal'] += int(np.count_nonzero(found != value))
                else:
                    exact_array(found, value, key+'/lane/'+eta+'/'+field)
            exact_array(trace['matured_hit'] >= 0, matured, key+' independent maturity')
            exact_array(trace['preupdate_units'][matured], trace['issued_units'][matured], key+' lane issuance immutable')
            require(np.all(np.abs(trace['issued_units']) <= denominator), key+' state bound')
            require(item['all_history_projection_counts']['lane_'+eta] == int(np.count_nonzero(trace['projection_units'])), key+' all-history projection count')
            totals['controller_forecast_pairs'] += len(origins)
        pooled, poolden = independent_controller(origins, base_q[:,5], base_e[:,5], rates[:,c], h, p['primary_eta'], pooled=True)
        require(int(archive[key+'_pooled_denominator']) == poolden, key+' pool denominator')
        for field, value in pooled.items():
            found = archive[key+'_pooled_'+field]
            if field in ['var', 'es']:
                errors['controller_'+field] = max(errors['controller_'+field], compare(found, value, key+'/pooled/'+field))
                totals['controller_float_values_not_bitwise_equal'] += int(np.count_nonzero(found != value))
            else:
                exact_array(found, value, key+'/pooled/'+field)
        require(item['all_history_projection_counts']['pooled_primary'] == int(np.count_nonzero(pooled['projection_units'])), key+' pooled projection count')
        totals['controller_forecast_pairs'] += len(origins)
        static_q = np.stack([base_q[:,5]*math.exp(float(Fraction(theta))) for theta in p['static_theta_grid']], axis=1)
        static_e = np.stack([base_e[:,5]*math.exp(float(Fraction(theta))) for theta in p['static_theta_grid']], axis=1)
        for field, value in [('var', static_q), ('es', static_e)]:
            found = archive[key+'_static_'+field]
            errors['static_'+field] = max(errors['static_'+field], compare(found, value, key+' static '+field))
            totals['static_float_values_not_bitwise_equal'] += int(np.count_nonzero(found != value))
        totals['static_forecast_pairs'] += static_q.size
        strata, medians = independent_strata(base_q[:,5])
        exact_array(archive[key+'_risk_stratum'], strata, key+' predictable stratum')
        compare(archive[key+'_prior_var_median'], medians, key+' prior median')
        masks = {}
        for period in periods:
            lo, hi = p[period]
            mask = np.zeros(len(origins), dtype=bool)
            mask[matured] = ((dates[origins[matured]] >= lo) & (dates[origins[matured]] <= hi) &
                             (dates[origins[matured]+h] >= lo) & (dates[origins[matured]+h] <= hi))
            masks[period] = mask
            expected_period = dict(n=int(mask.sum()), first_origin=str(dates[origins[mask][0]]),
                                   last_origin=str(dates[origins[mask][-1]]), last_target=str(dates[origins[mask][-1]+h]))
            require(item['periods'][period] == expected_period, key+'/'+period+' endpoint mask')
            period_cases[period] += int(mask.sum())
        require(not np.any(sum(m.astype(int) for m in masks.values()) > 1), key+' reporting periods overlap')
        dev = masks['development']
        lane_means = [independent_metrics(trace['var'][dev], trace['es'][dev], y[dev])['mean_fz0']
                      for trace, denominator in lane_references]
        static_means = [independent_metrics(static_q[dev,j], static_e[dev,j], y[dev])['mean_fz0']
                        for j in range(len(p['static_theta_grid']))]
        chosen_eta = min(range(len(lane_means)), key=lambda j:(lane_means[j],j))
        chosen_static = min(range(len(static_means)), key=lambda j:(static_means[j],j))
        require(item['selected_eta_index'] == chosen_eta and item['selected_eta'] == p['eta_grid'][chosen_eta], key+' eta selection')
        require(item['selected_static_index'] == chosen_static and item['selected_static_theta'] == p['static_theta_grid'][chosen_static], key+' static selection')
        require(item['primary_eta'] == p['primary_eta'], key+' primary eta')
        for j, eta in enumerate(p['eta_grid']):
            errors['selection'] = max(errors['selection'], compare(item['development_lane_fz0'][eta], lane_means[j], key+' development eta score'))
        for j, theta in enumerate(p['static_theta_grid']):
            errors['selection'] = max(errors['selection'], compare(item['development_static_fz0'][theta], static_means[j], key+' development static score'))
        primary = p['eta_grid'].index(p['primary_eta'])
        lane_p, den_p = lane_references[primary]
        lane_s, den_s = lane_references[chosen_eta]
        specs = [
            ('raw_hs', base_q[:,0], base_e[:,0], None, None, None, False),
            ('fast_fhs', base_q[:,5], base_e[:,5], None, None, None, False),
            ('multiscale_fhs', base_q[:,3], base_e[:,3], None, None, None, False),
            ('static_selected', static_q[:,chosen_static], static_e[:,chosen_static], None, None, None, False),
            ('lane_primary', lane_p['var'], lane_p['es'], lane_p, den_p, p['primary_eta'], False),
            ('lane_selected', lane_s['var'], lane_s['es'], lane_s, den_s, p['eta_grid'][chosen_eta], False),
            ('pooled_primary', pooled['var'], pooled['es'], pooled, poolden, p['primary_eta'], True)]
        require(list(item['models']) == p['reported_models'], key+' model order')
        def check_metric(actual, q, e, mask, label, trace=None, den=None, eta=None, pool=False):
            error = compare_summary(actual,q,e,y,mask,label,trace,den,eta,origins,h,pool)
            errors['metrics'] = max(errors['metrics'], error)
            totals['metric_records'] += 1
            if actual is not None and actual['exact_controller_accounting'] is not None:
                totals['exact_accounting_records'] += len(actual['exact_controller_accounting'])
        for model,q,e,trace,den,eta,pool in specs:
            record = item['models'][model]
            for period, mask in masks.items():
                check_metric(record[period],q,e,mask,key+'/'+model+'/'+period,trace,den,eta,pool)
                years = sorted(set(str(x)[:4] for x in dates[origins[mask]]))
                require(list(record['yearly'][period]) == years, key+' yearly partition')
                annual_count = 0
                for year in years:
                    m = mask & (np.char.startswith(dates[origins],year))
                    annual_count += int(m.sum())
                    check_metric(record['yearly'][period][year],q,e,m,key+'/'+model+'/'+period+'/'+year,trace,den,eta,pool)
                require(annual_count == int(mask.sum()), key+' yearly count')
                strata_count = 0
                for label, value in [('at_or_below_previous_median',0),('above_previous_median',1)]:
                    m = mask & (strata == value)
                    strata_count += int(m.sum())
                    check_metric(record['risk_strata'][period][label],q,e,m,key+'/'+model+'/'+period+'/'+label,trace,den,eta,pool)
                require(strata_count == int(mask.sum()), key+' strata partition')
        for j, eta in enumerate(p['eta_grid']):
            trace, den = lane_references[j]
            for period, mask in masks.items():
                check_metric(item['candidates']['lane_eta_'+eta][period],trace['var'],trace['es'],mask,key+'/candidate/'+eta+'/'+period,trace,den,eta)
                if Fraction(eta) > 0:
                    expected = reference_accounting_records(trace,den,eta,mask,origins,h)
                    require(item['controller_accounting']['lane_eta_'+eta][period] == expected, key+' duplicate lane accounting')
        for j, theta in enumerate(p['static_theta_grid']):
            for period, mask in masks.items():
                check_metric(item['candidates']['static_theta_'+theta][period],static_q[:,j],static_e[:,j],mask,key+'/static/'+theta+'/'+period)
        for period,mask in masks.items():
            expected = reference_accounting_records(pooled,poolden,p['primary_eta'],mask,origins,h,True)
            require(item['controller_accounting']['pooled_primary'][period] == expected, key+' duplicate pooled accounting')
        require(item['eligible_issuances'] == len(origins), key+' issuance count')
        require(item['matured_issuances'] == int(matured.sum()), key+' matured count')
        require(item['pending_issuances'] == h, key+' pending count')
        totals['pending_contract_cases'] += h
        checked.append(dict(currency=currency,horizon=h,eligible_issuances=len(origins),
                            selected_eta=p['eta_grid'][chosen_eta], selected_static_theta=p['static_theta_grid'][chosen_static],
                            minimum_eta_selection_gap=float(np.sort(lane_means)[1]-np.sort(lane_means)[0]),
                            minimum_static_selection_gap=float(np.sort(static_means)[1]-np.sort(static_means)[0])))
    require(results['period_contract_cases'] == period_cases, 'period case totals')
    forecast_pairs = {period:n*len(p['reported_models']) for period,n in period_cases.items()}
    require(results['period_forecast_pairs'] == forecast_pairs, 'reported forecast pair totals')
    require(results['pending_contract_cases'] == totals['pending_contract_cases'], 'pending total')
    all_pairs = totals['controller_forecast_pairs']+totals['static_forecast_pairs']+totals['parent_forecast_pairs_reused']+totals['pending_parent_forecast_pairs_reconstructed']
    require(results['archive_candidate_pairs_including_pending'] == all_pairs, 'all candidate pair total')
    causal = production_checks(p,dates,rates,parent)
    result = dict(schema='gabriel.adaptive-risk.verification.v1', status='passed',
                  protocol_sha256=PROTOCOL_HASH, source_csv_sha256=digest(source),
                  prediction_archive_sha256=digest(archive_path), results_sha256=digest(result_path),
                  parent_verification_sha256=digest(ROOT/'results/ecb_risk_verification.json'),
                  verifier_sha256=digest(Path(__file__)),
                  verification_layer='Independent Fraction controller replay and selection/metric reconstruction from unchanged, previously independently verified parent forecasts; independent final-unit tail reconstruction for pending parent rows.',
                  reused_parent_verification=parent_check['reference'],
                  tolerance=dict(absolute=ATOL,relative=RTOL),maximum_absolute_differences=errors,
                  counts=totals,period_contract_cases=period_cases,period_forecast_pairs=forecast_pairs,
                  production_function_tests=causal,contracts=checked,
                  limits=['Exact state/projection accounting does not certify binary64 exp/log, VaR or ES arithmetic.',
                          'This verifier checks implementation against its frozen protocol, not conditional calibration or population performance.',
                          'The 2020-2025 comparison is retrospective for this design; 2026 is a short descriptive extension.',
                          'Current revised ECB data lack archived original release vintages.',
                          'Candidate and forecast row counts are dependent and are not independent sample sizes.'],
                  seconds=time.perf_counter()-started)
    (ROOT/'results/adaptive_risk_verification.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps({key:result[key] for key in ['status','counts','maximum_absolute_differences','seconds']},indent=2))


if __name__ == '__main__':
    main()
