"""Frozen common-date comparison and dependent bootstrap for joint-risk pools.

All assets, horizons and methods share resampled origin-date blocks. Intervals
are approximate historical resampling diagnostics, not distribution-free or
prospective market guarantees. This module performs no model selection.
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
PRIMARY_ASSETS = ('AUD', 'CAD', 'NOK', 'SEK')
HORIZONS = (1, 5)
LENGTHS = (20, 60)
REPLICATES = 5000
SEED = 2026092608
BETA = 1/40
TOL = 2e-9
TRANSFORMED = ('transformed_uniform', 'transformed_fit',
               'adagrad_c0p1', 'adagrad_c0p3', 'adagrad_c1')
LABELS = {'selected_expert':'Development-best expert',
          'arithmetic_fit':'Fitted arithmetic pool',
          'transformed_fit':'Fitted transformed pool',
          'arithmetic_uniform':'Uniform arithmetic pool',
          'transformed_uniform':'Uniform transformed pool',
          'adagrad_c0p1':'Adaptive pool, c=0.1',
          'adagrad_c0p3':'Adaptive pool, c=0.3',
          'adagrad_c1':'Adaptive pool, c=1'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def score(q, e, y):
    q, e, y = np.broadcast_arrays(np.asarray(q, float), np.asarray(e, float),
                                  np.asarray(y, float))
    require(np.isfinite(q).all() and np.isfinite(e).all() and np.isfinite(y).all(),
            'Finite scored forecasts and outcomes required')
    require(np.all((q > 0) & (e >= q)), 'Positive ordered risk forecasts required')
    return np.log(e)+(q+np.maximum(y-q, 0)/BETA)/e-1


def circle_block_starts(n, length, replicates=REPLICATES, seed=SEED):
    """Draw fixed-length circular blocks, truncate their concatenation to n."""
    for value, name in ((n, 'n'), (length, 'length'), (replicates, 'replicates')):
        require(isinstance(value, (int, np.integer)) and not isinstance(value, bool)
                and value > 0, name+' must be a positive integer')
    require(isinstance(seed, (int, np.integer)) and not isinstance(seed, bool)
            and seed >= 0, 'nonnegative integer seed required')
    require(length <= n, 'block length cannot exceed the retained date count')
    rng = np.random.default_rng(np.random.SeedSequence([seed, length]))
    return rng.integers(0, n, size=(replicates, (n+length-1)//length), dtype=np.int32)


def bootstrap_from_starts(date_differences, starts, length, batch=128):
    """Reconstruct paired means from saved starts without generating randomness."""
    values = np.asarray(date_differences, float)
    starts = np.asarray(starts)
    require(values.ndim == 2 and len(values) > 0 and np.isfinite(values).all(),
            'Finite dates-by-comparators differences required')
    n = len(values)
    require(starts.ndim == 2 and starts.dtype.kind in 'iu' and
            starts.shape[1] == (n+length-1)//length and
            np.all((starts >= 0) & (starts < n)), 'invalid saved block starts')
    require(isinstance(batch, int) and batch > 0, 'positive batch required')
    out = np.empty((len(starts), values.shape[1]))
    offsets = np.arange(length)
    for first in range(0, len(starts), batch):
        current = starts[first:first+batch]
        indices = ((current[..., None]+offsets) % n).reshape(len(current), -1)[:, :n]
        out[first:first+len(current)] = values[indices].mean(axis=1)
    return out


def shared_bootstrap(differences, comparators, lengths=LENGTHS,
                     replicates=REPLICATES, seed=SEED):
    """One shared resampling law for dates x contracts x comparator differences."""
    values = np.asarray(differences, float)
    require(values.ndim == 3 and min(values.shape) > 0 and np.isfinite(values).all(),
            'Finite dates-by-contracts-by-comparators array required')
    require(len(comparators) == values.shape[2] and len(set(comparators)) == len(comparators),
            'Unique matching comparator names required')
    require(len(lengths) > 0 and len(set(lengths)) == len(lengths), 'unique block lengths required')
    date_means = values.mean(axis=1)
    observed = date_means.mean(axis=0)
    arrays = {'date_comparator_differences':date_means,
              'contract_comparator_differences':values.mean(axis=0)}
    intervals = []
    for length in lengths:
        starts = circle_block_starts(len(values), length, replicates, seed)
        means = bootstrap_from_starts(date_means, starts, length)
        arrays[f'block_starts_{length}'] = starts
        arrays[f'bootstrap_means_{length}'] = means
        bounds = np.quantile(means, [.025, .95, .975], axis=0, method='linear')
        for j, comparator in enumerate(comparators):
            intervals.append(dict(comparator=comparator, block_length=int(length),
                observed_difference=float(observed[j]),
                one_sided95_upper=float(bounds[1, j]),
                two_sided95_lower=float(bounds[0, j]),
                two_sided95_upper=float(bounds[2, j]),
                strictly_negative_upper=bool(bounds[1, j] < 0),
                bootstrap_mean=float(means[:, j].mean()),
                bootstrap_sd=float(means[:, j].std(ddof=1))))
    passed = all(row['strictly_negative_upper'] for row in intervals)
    summary = dict(dates=values.shape[0], contracts=values.shape[1],
        comparators=list(comparators), replicates=replicates, seed=seed,
        block_lengths=list(lengths), quantile_method='numpy linear',
        rng='Generator(PCG64(SeedSequence([seed, block_length])))',
        resampling='Circular blocks of common origin-date vectors; truncate concatenation to original date count',
        weighting='Equal contracts within each common date, then equal retained dates',
        sign='Primary minus comparator mean FZ0; negative favors primary',
        success_rule='All comparator one-sided 95% upper percentile limits below zero at BOTH block lengths',
        conjunctive_gate_passed=passed, intervals=intervals,
        interpretation='Approximate dependent historical bootstrap; stationarity and sufficiently weak dependence are not established for this single market path. Not distribution-free future-market coverage.',
        multiplicity='Strictly conjunctive intersection-union criterion, not post hoc selection among comparisons; all intervals and comparator results retained.')
    return summary, arrays


def jensen_components(q, e, weights, y, pooled_scores):
    q, e, w, y = map(lambda x: np.asarray(x, float), (q, e, weights, y))
    require(q.ndim == 2 and q.shape == e.shape == w.shape and y.shape == (len(q),),
            'Matching expert, weight and target arrays required')
    require(np.isfinite(w).all() and w.min() >= -1e-12 and
            np.max(np.abs(w.sum(axis=1)-1)) < 1e-10, 'invalid saved simplex weights')
    b = 1/e
    hinge = (y[:, None]-q)/e
    log_gap = np.log(np.sum(w*b, axis=1))-np.sum(w*np.log(b), axis=1)
    hinge_gap = (np.sum(w*np.maximum(hinge, 0), axis=1)
                 - np.maximum(np.sum(w*hinge, axis=1), 0))/BETA
    expert_mean = np.sum(w*score(q, e, y[:, None]), axis=1)
    identity_residual = expert_mean-np.asarray(pooled_scores)-log_gap-hinge_gap
    require(min(log_gap.min(), hinge_gap.min()) >= -TOL, 'negative Jensen component beyond tolerance')
    require(np.max(np.abs(identity_residual)) <= TOL, 'Jensen score identity failed')
    total = log_gap+hinge_gap
    return dict(n=len(y), mean_log_gap=float(log_gap.mean()),
        mean_hinge_gap=float(hinge_gap.mean()), mean_total_gap=float(total.mean()),
        minimum_total_gap=float(total.min()),
        strictly_positive_count_tolerance_1e12=int((total > 1e-12).sum()),
        minimum_log_gap=float(log_gap.min()), minimum_hinge_gap=float(hinge_gap.min()),
        maximum_identity_residual=float(np.max(np.abs(identity_residual)))), (log_gap, hinge_gap)


def model_metrics(q, e, y):
    fz = score(q, e, y)
    hits = y > q
    return dict(n=len(y), mean_fz0=float(fz.mean()), exceedances=int(hits.sum()),
        exceedance_fraction=float(hits.mean()),
        mean_es_identification_residual=float(np.mean(q+np.maximum(y-q, 0)/BETA-e)),
        mean_var=float(q.mean()), mean_es=float(e.mean()))


def main():
    result_path = ROOT/'results/aggregate_risk_results.json'
    protocol_path = ROOT/'results/aggregate_risk_protocol.json'
    prediction_path = ROOT/'results/aggregate_risk_predictions.npz'
    results = json.loads(result_path.read_text())
    protocol = json.loads(protocol_path.read_text())
    if 'protocol_sha256' in results:
        require(results['protocol_sha256'] == digest(protocol_path), 'producer protocol identity mismatch')
    archive = np.load(prediction_path, allow_pickle=False)
    primary = results.get('primary_model', protocol.get('primary_model'))
    require(isinstance(primary, str), 'frozen primary model not found')
    models = list(map(str, archive['models']))
    require(primary in models and len(models) == len(set(models)), 'invalid method order or primary')
    comparators = ['arithmetic_fit', 'arithmetic_uniform', 'selected_expert']
    if primary.startswith('adagrad_'):
        comparators.append('transformed_fit')
    require(all(x in models for x in comparators), 'missing comparator')
    dates = archive['dates']
    contracts = [(c, h) for c in PRIMARY_ASSETS for h in HORIZONS]
    rows, jensen, retained = [], [], []
    common_origins = None
    bootstrap_arrays = {'models':np.asarray(models), 'primary_model':np.asarray(primary),
                        'comparators':np.asarray(comparators),
                        'contracts':np.asarray([f'{c}_{h}' for c, h in contracts])}
    maximum_score_residual = 0.
    common_all_scores = []
    for currency, horizon in contracts:
        key = f'{currency}_{horizon}'
        origins = archive[key+'_origins']
        mask = archive[key+'_common_test_mask'].astype(bool)
        y = archive[key+'_realized']
        qall, eall = archive[key+'_model_var'], archive[key+'_model_es']
        require(qall.shape == eall.shape == (len(origins), len(models)), 'forecast matrix shape mismatch')
        require(mask.shape == origins.shape and mask.any(), 'invalid common-date mask')
        selected_origins = origins[mask]
        require(np.all(archive[key+'_matured'][mask]), 'common-date target has not matured')
        require(np.all(np.diff(selected_origins) == 1), 'common origin dates are not contiguous')
        require(np.all(dates[selected_origins] >= '2020-01-01') and
                np.all(dates[selected_origins+horizon] <= '2026-09-25'),
                'common-date target outside frozen test period')
        if common_origins is None:
            common_origins = selected_origins
        require(np.array_equal(selected_origins, common_origins), 'contracts do not share exact origin dates')
        actual_scores = score(qall[mask], eall[mask], y[mask, None])
        saved_scores = archive[key+'_model_fz0'][mask]
        residual = float(np.max(np.abs(actual_scores-saved_scores)))
        maximum_score_residual = max(maximum_score_residual, residual)
        require(residual <= TOL, 'saved proper-score mismatch')
        common_all_scores.append(actual_scores)
        pi = models.index(primary)
        retained.append(np.column_stack([actual_scores[:, pi]-actual_scores[:, models.index(c)]
                                         for c in comparators]))
        periods = {'primary_common_2020_2026':mask,
                   'secondary_2020_2025':mask & (dates[origins] <= '2025-12-31') &
                     (dates[np.minimum(origins+horizon, len(dates)-1)] <= '2025-12-31'),
                   'secondary_2026':mask & (dates[origins] >= '2026-01-01')}
        if key+'_extra_h1_mask' in archive:
            periods['excluded_common_tail_h1'] = archive[key+'_extra_h1_mask'].astype(bool)
        for period, pmask in periods.items():
            if not pmask.any():
                continue
            for i, model in enumerate(models):
                metrics = model_metrics(qall[pmask, i], eall[pmask, i], y[pmask])
                primary_score = score(qall[pmask, pi], eall[pmask, pi], y[pmask]).mean()
                rows.append(dict(currency=currency, horizon=horizon, period=period,
                                 model=model, **metrics,
                                 primary_minus_model_fz0=float(primary_score-metrics['mean_fz0'])))
        qbank, ebank = archive[key+'_expert_var'][mask], archive[key+'_expert_es'][mask]
        for method in TRANSFORMED:
            if method == 'transformed_uniform':
                weights = np.broadcast_to(archive[key+'_uniform_weights'], qbank.shape)
            elif method == 'transformed_fit':
                weights = np.broadcast_to(archive[key+'_static_transformed_weights'], qbank.shape)
            else:
                index = ('adagrad_c0p1', 'adagrad_c0p3', 'adagrad_c1').index(method)
                weights = archive[key+'_online_issued_weights'][mask, index]
            record, gap_arrays = jensen_components(qbank, ebank, weights, y[mask],
                                                    actual_scores[:, models.index(method)])
            jensen.append(dict(currency=currency, horizon=horizon, model=method, **record))
            bootstrap_arrays[key+'_'+method+'_jensen_log'] = gap_arrays[0]
            bootstrap_arrays[key+'_'+method+'_jensen_hinge'] = gap_arrays[1]
    differences = np.stack(retained, axis=1)
    score_cube = np.stack(common_all_scores, axis=1)
    boot_summary, resample_arrays = shared_bootstrap(differences, comparators)
    bootstrap_arrays.update(resample_arrays)
    bootstrap_arrays.update(common_origins=common_origins, common_dates=dates[common_origins],
                            paired_differences=differences,
                            common_all_scores=score_cube)
    summaries = []
    for j, comparator in enumerate(comparators):
        per_contract = differences[:, :, j].mean(axis=0)
        summaries.append(dict(comparator=comparator, mean_difference=float(per_contract.mean()),
            contracts_better=int((per_contract < -1e-12).sum()),
            contracts_worse=int((per_contract > 1e-12).sum()),
            contracts_tied=int((np.abs(per_contract) <= 1e-12).sum()),
            per_contract=[dict(currency=c, horizon=h, difference=float(d))
                          for (c,h),d in zip(contracts,per_contract)],
            largest_contract_loss=float(per_contract.max())))
    output = dict(schema='gabriel.aggregate-risk.summary.v1',
        protocol_sha256=digest(protocol_path), results_sha256=digest(result_path),
        predictions_sha256=digest(prediction_path), primary_model=primary,
        models=models, primary_assets=list(PRIMARY_ASSETS), horizons=list(HORIZONS),
        first_common_origin=str(dates[common_origins[0]]),
        last_common_origin=str(dates[common_origins[-1]]),
        common_dates=len(common_origins), primary_contract_cases=len(common_origins)*len(contracts),
        all_model_common_means=[dict(model=model,
            mean_fz0=float(score_cube[:, :, i].mean()),
            primary_minus_model_fz0=float((score_cube[:, :, models.index(primary)]-
                                           score_cube[:, :, i]).mean()))
            for i, model in enumerate(models)],
        primary_comparisons=summaries, dependent_bootstrap=boot_summary,
        rows=rows, jensen=jensen, maximum_score_recomputation_residual=maximum_score_residual,
        scope='Previously unscored assets on one archived ECB source and already examined calendar periods; correlated asset transfer, not independent temporal replication.',
        comparison='Negative primary-minus-comparator FZ0 favors primary; neither returns nor percentage improvement.',
        jensen_interpretation='Pointwise dominance over randomized expert selection with identical weights in expectation; does not imply dominance over the best expert.',
        regret='Any pathwise optimization-regret diagnostic remains in the producer results and concerns its declared comparator and feedback order; bootstrap intervals are not regret bounds.')
    target = ROOT/'results/aggregate_risk_summary.json'
    target.write_text(json.dumps(output, indent=2, allow_nan=False)+'\n')
    np.savez_compressed(ROOT/'results/aggregate_bootstrap.npz', **bootstrap_arrays)
    with (ROOT/'results/aggregate_summary.csv').open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    write_tables(output)
    write_figure(output)
    print(json.dumps(dict(primary_model=primary, common_dates=len(common_origins),
        primary_contract_cases=len(common_origins)*8,
        bootstrap_gate_passed=boot_summary['conjunctive_gate_passed'],
        comparisons=[{k:v for k,v in x.items() if k != 'per_contract'} for x in summaries]), indent=2))


def tex_escape(text):
    return str(text).replace('_', r'\_')


def write_tables(summary):
    primary = summary['primary_model']
    comparisons = summary['primary_comparisons']
    lines = [r'\begin{tabular}{lrrrr}\toprule',
             r'Comparator & $\Delta$ & Upper 95\%, $L=20$ & Upper 95\%, $L=60$ & Better/8\\\midrule']
    for comparison in comparisons:
        name = comparison['comparator']
        upper = {row['block_length']:row['one_sided95_upper']
                 for row in summary['dependent_bootstrap']['intervals'] if row['comparator'] == name}
        lines.append(f"{tex_escape(LABELS.get(name,name))} & {comparison['mean_difference']:.5f} & "
                     f"{upper[20]:.5f} & {upper[60]:.5f} & {comparison['contracts_better']}"+r'\\')
    lines += [r'\bottomrule\end{tabular}']
    (ROOT/'results/aggregate_bootstrap_table.tex').write_text('\n'.join(lines)+'\n')
    lines = [r'\begin{tabular}{llrrrr}\toprule',
             r'Currency & $h$ & Primary score & $\Delta$ fitted arithmetic & $\Delta$ uniform arithmetic & $\Delta$ best expert\\\midrule']
    for c in PRIMARY_ASSETS:
        for h in HORIZONS:
            scores = {r['model']:r['mean_fz0'] for r in summary['rows']
                      if r['currency']==c and r['horizon']==h and r['period']=='primary_common_2020_2026'}
            p = scores[primary]
            lines.append(f'{c} & {h} & {p:.5f} & '+
                ' & '.join(f'{p-scores[m]:.5f}' for m in
                           ('arithmetic_fit','arithmetic_uniform','selected_expert'))+r'\\')
    lines += [r'\bottomrule\end{tabular}']
    (ROOT/'results/aggregate_contract_table.tex').write_text('\n'.join(lines)+'\n')


def write_figure(summary):
    plt.rcParams.update({'font.size':9, 'axes.spines.top':False, 'axes.spines.right':False})
    figure, axes = plt.subplots(1, 2, figsize=(11, 4.2), gridspec_kw={'width_ratios':[1.55,1]})
    contracts = [f'{c}, h={h}' for c in PRIMARY_ASSETS for h in HORIZONS]
    y = np.arange(len(contracts))
    comparisons = summary['primary_comparisons']
    for k, comparison in enumerate(comparisons):
        offset = (k-(len(comparisons)-1)/2)*.13
        axes[0].plot([x['difference'] for x in comparison['per_contract']], y+offset,
            'o', ms=4, label=LABELS.get(comparison['comparator'],comparison['comparator']))
    axes[0].axvline(0, color='0.5', lw=.8)
    axes[0].set_yticks(y, contracts); axes[0].invert_yaxis()
    axes[0].set_xlabel('Primary minus comparator mean FZ0')
    axes[0].set_title('Common-date asset-transfer comparison')
    axes[0].legend(fontsize=7, loc='best')
    values = []
    for method in TRANSFORMED:
        selected = [x for x in summary['jensen'] if x['model']==method]
        values.append((np.mean([x['mean_log_gap'] for x in selected]),
                       np.mean([x['mean_hinge_gap'] for x in selected])))
    values = np.asarray(values)
    x = np.arange(len(TRANSFORMED))
    axes[1].bar(x, values[:,0], label='Inverse-ES dispersion')
    axes[1].bar(x, values[:,1], bottom=values[:,0], label='Threshold dispersion')
    axes[1].set_xticks(x, ['Uniform','Fitted','c=0.1','c=0.3','c=1'], rotation=30, ha='right')
    axes[1].set_ylabel('Mean weighted-expert score minus pool score')
    axes[1].set_title('Pointwise convexity gain')
    axes[1].legend(fontsize=7)
    figure.tight_layout()
    for suffix in ('pdf','png'):
        figure.savefig(ROOT/f'figures/aggregate_risk_comparison.{suffix}', dpi=180)
    plt.close(figure)


if __name__ == '__main__':
    main()
