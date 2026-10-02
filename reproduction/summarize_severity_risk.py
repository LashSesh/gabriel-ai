"""Descriptive severity summaries and a synthetic response figure.

This script never tunes models. It validates saved market metrics against the
forecast archive, retains every frozen method, and computes paired Monte Carlo
intervals across independent synthetic replicates. These intervals do not apply
to market data or to correlated observations within a replicate.
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
from scipy.stats import t as student_t

ROOT = Path(__file__).resolve().parents[1]
MODELS = ['fast_base', 'frequency_only', 'severity_125', 'joint_125',
          'severity_500', 'joint_500', 'static_severity', 'static_joint']
PERIODS = ['retrospective_2020_2025', 'retrospective_2026']
CASE_LABELS = {'stationary_bounded':'Stationary', 'sustained_shift':'Sustained shift',
               'recurrent_shift':'Recurrent shift', 'exponential_shift':'Exponential tail',
               'underestimated_quantile':'Low quantile'}
PAIRS = [('severity_125','fast_base'),('severity_125','static_severity'),
         ('joint_125','frequency_only'),('joint_125','static_joint'),
         ('severity_500','fast_base'),('severity_500','static_severity'),
         ('joint_500','frequency_only'),('joint_500','static_joint'),
         ('frequency_only','fast_base'),('static_severity','fast_base'),
         ('static_joint','frequency_only')]
SYN_METRICS = ['realized_mean_fz0','analytic_conditional_expected_fz0',
               'relative_es_absolute_error','breach_fraction','normalized_es_residual',
               'cap_fraction','quantile_score_excess','severity_score_excess']
TOL = 1e-10


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def json_read(path):
    return json.loads(path.read_text())


def mean_interval(values):
    """Monte Carlo t interval for the mean of independent replicate values."""
    values = np.asarray(values, dtype=float)
    require(values.ndim == 1 and len(values) == 32, 'Expected 32 independent replicates')
    require(np.isfinite(values).all(), 'Nonfinite replicate summary')
    mean = float(np.mean(values))
    sd = float(np.std(values, ddof=1))
    se = sd / np.sqrt(len(values))
    critical = float(student_t.ppf(.975, len(values)-1))
    half = critical * se
    return dict(replicates=len(values),mean=mean,sd=sd,standard_error=float(se),
                ci95_lower=mean-half,ci95_upper=mean+half,t_critical=critical,
                interval='Approximate replicate-level Monte Carlo t interval; not market inference')


def archive_market_metrics(q,e,y,caps,beta):
    require(np.isfinite(q).all() and np.isfinite(e).all() and np.isfinite(y).all(),
            'Nonfinite scored market rows')
    require(np.all((q>0)&(e>=q)), 'Invalid ratio forecast domain')
    residual=q+np.maximum(y-q,0)/beta-e
    scores=np.log(e)+(q+np.maximum(y-q,0)/beta)/e-1
    hits=y>q
    return dict(n=len(y),mean_fz0=float(scores.mean()),exceedances=int(hits.sum()),
                exceedance_fraction=float(hits.mean()),
                mean_es_identification_residual=float(residual.mean()),
                mean_normalized_es_residual=float((residual/q).mean()),
                mean_var=float(q.mean()),mean_es=float(e.mean()),
                cap_count=int(caps.sum()),cap_fraction=float(caps.mean()))


def market_summary(protocol,results,archive):
    require(results['model_order']==MODELS, 'Changed market model order')
    require(list(archive['models'])==MODELS,'Changed market archive model order')
    require(len(results['contracts'])==8,'Expected eight market contracts')
    rows=[]; by_contract={}; beta=1/40
    dates=archive['dates']
    for contract in results['contracts']:
        cur,h=contract['currency'],contract['horizon']; key=f'{cur}_{h}'
        origins=archive[key+'_origins']; matured=archive[key+'_matured']
        qall,eall,y=archive[key+'_model_var'],archive[key+'_model_es'],archive[key+'_realized']
        caps=archive[key+'_model_cap_flags']
        require(qall.shape==eall.shape==(len(origins),8),'Bad market forecast shape')
        for period in PERIODS:
            start,end=protocol['market'][period]
            mask=np.zeros(len(origins),dtype=bool)
            mask[matured]=(dates[origins[matured]]>=start)&(dates[origins[matured]+h]<=end)
            require(int(mask.sum())==contract['periods'][period]['n'],'Period membership mismatch')
            models={}
            for j,model in enumerate(MODELS):
                computed=archive_market_metrics(qall[mask,j],eall[mask,j],y[mask],caps[mask,j],beta)
                saved=contract['models'][model][period]
                for metric,value in computed.items():
                    require(np.isclose(value,saved[metric],atol=TOL,rtol=TOL),
                            f'Market metric mismatch {key}/{period}/{model}/{metric}')
                reference='frequency_only' if model in ['joint_125','joint_500','static_joint'] else 'fast_base'
                row=dict(currency=cur,horizon=h,period=period,model=model,
                    matched_quantile_reference=reference,**computed,
                    fz0_difference_vs_fast=computed['mean_fz0']-contract['models']['fast_base'][period]['mean_fz0'],
                    fz0_difference_vs_matched_reference=computed['mean_fz0']-contract['models'][reference][period]['mean_fz0'],
                    breach_percent=100*computed['exceedance_fraction'],
                    absolute_breach_deviation_pp=100*abs(computed['exceedance_fraction']-beta))
                rows.append(row);models[model]=row
            by_contract[cur,h,period]=models
    require(len(rows)==128,'Expected 8 contracts x 2 periods x 8 methods')
    comparisons={}
    for period in PERIODS:
        comparisons[period]={}
        for model in MODELS:
            selected=[r for r in rows if r['period']==period and r['model']==model]
            def counts(field):
                x=np.array([r[field] for r in selected])
                return dict(lower=int(np.sum(x < -TOL)),tie=int(np.sum(abs(x)<=TOL)),
                            higher=int(np.sum(x>TOL)),differences=x.tolist(),
                            min=float(x.min()),max=float(x.max()))
            comparisons[period][model]=dict(
                vs_fast=counts('fz0_difference_vs_fast'),
                matched_reference=selected[0]['matched_quantile_reference'],
                vs_matched=counts('fz0_difference_vs_matched_reference'),
                breach_percent_range=[min(r['breach_percent'] for r in selected),max(r['breach_percent'] for r in selected)],
                cap_count=sum(r['cap_count'] for r in selected))
    return dict(rows=rows,row_count=len(rows),comparisons=comparisons,
                period_contract_cases={p:sum(c['periods'][p]['n'] for c in results['contracts']) for p in PERIODS},
                period_forecast_pairs={p:sum(r['n'] for r in rows if r['period']==p) for p in PERIODS},
                static_ratios={f"{c['currency']}_{c['horizon']}":c['static_ratios'] for c in results['contracts']},
                all_history_cap_count={m:sum(c['all_history_cap_count'][m] for c in results['contracts']) for m in MODELS}),by_contract


def synthetic_summary(protocol,results):
    models=MODELS+['oracle_truth']
    require(results['model_order']==models,'Changed synthetic model order')
    require(len(results['records'])==320,'Expected 5 cases x 2 latencies x 32 replicates')
    cases=[c['name'] for c in protocol['synthetic']['cases']]
    summaries=[]; comparisons=[]
    for case in cases:
        for latency in protocol['synthetic']['latencies']:
            group=sorted([r for r in results['records'] if r['case']==case and r['latency']==latency],
                         key=lambda r:r['replicate'])
            require([r['replicate'] for r in group]==list(range(32)), 'Missing or duplicate replicate')
            for period in ['all','early','late']:
                for model in models:
                    row=dict(case=case,latency=latency,period=period,model=model,
                             n_per_replicate=group[0]['models'][model][period]['n'])
                    for metric in SYN_METRICS:
                        row[metric]=mean_interval([r['models'][model][period][metric] for r in group])
                    summaries.append(row)
                    # Analytic excess must split into quantile and severity terms.
                    for rec in group:
                        v=rec['models'][model][period];truth=rec['models']['oracle_truth'][period]
                        residual=v['analytic_conditional_expected_fz0']-truth['analytic_conditional_expected_fz0']-v['quantile_score_excess']-v['severity_score_excess']
                        require(abs(residual)<TOL,'Synthetic expected-score decomposition mismatch')
                        require(v['quantile_score_excess']>=-TOL and v['severity_score_excess']>=-TOL,
                                'Negative oracle-cost component')
                for first,second in PAIRS:
                    for metric in SYN_METRICS:
                        differences=[r['models'][first][period][metric]-r['models'][second][period][metric] for r in group]
                        comparisons.append(dict(case=case,latency=latency,period=period,
                            first=first,second=second,metric=metric,**mean_interval(differences)))
    require(len(summaries)==270,'Incomplete synthetic method summaries')
    require(len(comparisons)==2640,'Incomplete synthetic paired comparisons')
    return dict(replicates=32,case_count=5,latencies=[1,5],aggregate_method_rows=summaries,
                paired_comparisons=comparisons,maximum_saved_decomposition_residual=results['max_decomposition_residual'],
                interpretation='Intervals quantify Monte Carlo uncertainty across independent generated sequences; repeated origins within a sequence are not independent replicates.')


def write_csv(path,rows):
    with path.open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]))
        writer.writeheader();writer.writerows(rows)


def interval_label(row):
    return f"${row['mean']:+.3f}\\,\\pm\\,{(row['ci95_upper']-row['ci95_lower'])/2:.3f}$"


def tables(folder,market,synthetic):
    lines=[r'\begin{tabular}{lrrrrrr}',r'\toprule',
        r'Contract & $\Delta S_{125}$ & $\Delta J_{125}$ & $\Delta S_{500}$ & $\Delta J_{500}$ & $\Delta S_{\rm fix}$ & $\Delta J_{\rm fix}$ \\',r'\midrule']
    for period,label in zip(PERIODS,['2020--2025, retrospective','2026 through 25 September, retrospective']):
        lines.append(r'\multicolumn{7}{l}{\textit{'+label+r'}} \\')
        for cur in ['USD','GBP','JPY','CHF']:
            for h in [1,5]:
                m=market[cur,h,period]
                cells=[f'{cur}, {h}']
                cells += [f"{m[name]['fz0_difference_vs_matched_reference']:+.4f}" for name in MODELS[2:]]
                lines.append(' & '.join(cells)+r' \\')
        lines.append(r'\midrule')
    lines[-1]=r'\bottomrule';lines.append(r'\end{tabular}')
    (folder/'severity_market_table.tex').write_text('\n'.join(lines)+'\n')
    index={(r['case'],r['latency'],r['period'],r['first'],r['second'],r['metric']):r
           for r in synthetic['paired_comparisons']}
    lines=[r'\begin{tabular}{lrllll}',r'\toprule',
           r'Generating process & Delay & $S_{125}-$base & $S_{125}-S_{\rm fix}$ & $J_{125}-$Freq & $J_{125}-J_{\rm fix}$ \\',r'\midrule']
    for case,label in CASE_LABELS.items():
        for h in [1,5]:
            cells=[label if h==1 else '',str(h)]
            for first,second in PAIRS[:4]:
                row=index[case,h,'all',first,second,'analytic_conditional_expected_fz0']
                cells.append(interval_label(row))
            lines.append(' & '.join(cells)+r' \\')
        lines.append(r'\addlinespace[2pt]')
    lines += [r'\bottomrule',r'\end{tabular}']
    (folder/'severity_synthetic_table.tex').write_text('\n'.join(lines)+'\n')
    by={(r['case'],r['latency'],r['period'],r['model']):r for r in synthetic['aggregate_method_rows']}
    lines=[r'\begin{tabular}{lrrrrrrrrr}',r'\toprule',
           r'Process & Delay & \multicolumn{2}{c}{Base} & \multicolumn{2}{c}{Freq} & \multicolumn{2}{c}{$S_{125}$} & \multicolumn{2}{c}{$J_{125}$} \\',
           r' & & $C_Q$ & $C_E$ & $C_Q$ & $C_E$ & $C_Q$ & $C_E$ & $C_Q$ & $C_E$ \\',r'\midrule']
    for case,label in CASE_LABELS.items():
        for h in [1,5]:
            cells=[label if h==1 else '',str(h)]
            for model in ['fast_base','frequency_only','severity_125','joint_125']:
                r=by[case,h,'all',model]
                cells.extend(f"{r[k]['mean']:.3f}" for k in ['quantile_score_excess','severity_score_excess'])
            lines.append(' & '.join(cells)+r' \\')
    lines += [r'\bottomrule',r'\end{tabular}']
    (folder/'severity_decomposition_table.tex').write_text('\n'.join(lines)+'\n')


def figure(folder,archive,synthetic):
    plt.rcParams.update({'font.size':8,'axes.titlesize':9,'axes.labelsize':8,
                        'xtick.labelsize':7,'ytick.labelsize':7,'legend.fontsize':7,
                        'pdf.fonttype':42,'ps.fonttype':42,'savefig.facecolor':'white'})
    fig=plt.figure(figsize=(6.3,5.7),layout='constrained')
    grid=fig.add_gridspec(2,2,height_ratios=[1,1.55])
    ax=fig.add_subplot(grid[0,:]);left=fig.add_subplot(grid[1,0]);right=fig.add_subplot(grid[1,1],sharey=left)
    key='sustained_shift_5';origins=archive[key+'_origins'];scale=archive[key+'_scale']
    mask=(origins>=2000)&(origins<7995)
    ax.plot(origins[mask],archive[key+'_true_es'][mask]/scale[mask],color='black',lw=1.6,label='Truth')
    styles=[('fast_base','Base','#777777','--'),('severity_125','Severity 125','#167d9a','-'),
            ('severity_500','Severity 500','#d68a20','-'),('joint_125','Joint 125','#934b87','-')]
    for model,label,color,line in styles:
        j=MODELS.index(model)
        ax.plot(origins[mask],archive[key+'_model_es'][mask,j]/scale[mask],color=color,
                lw=.55 if model=='joint_125' else 1.05,ls=':' if model=='joint_125' else line,
                alpha=.65 if model=='joint_125' else 1,zorder=2 if model=='joint_125' else 3,label=label)
    ax.axvline(4000,color='#999999',ls=':',lw=.8)
    ax.set(title='A  Synthetic example: sustained severity shift, replicate 0, delay 5',
           xlabel='Forecast origin',ylabel='ES / true quantile')
    ax.legend(ncol=5,frameon=False,loc='upper left',bbox_to_anchor=(0,1.02))
    ax.grid(alpha=.17);ax.set_xlim(2000,7995)
    index={(r['case'],r['latency'],r['period'],r['first'],r['second'],r['metric']):r
           for r in synthetic['paired_comparisons']}
    labels=[];positions=[]
    for i,(case,label) in enumerate(CASE_LABELS.items()):
        for offset,h in enumerate([1,5]):
            positions.append(i*2.5+offset);labels.append(f'{label}\nDelay {h}' if h==1 else f'Delay {h}')
    for axes,pair,title,color in [(left,PAIRS[0],'B  Severity 125 minus base','#167d9a'),
                                   (right,PAIRS[2],'C  Joint 125 minus frequency','#934b87')]:
        k=0
        for case in CASE_LABELS:
            for h in [1,5]:
                r=index[case,h,'all',*pair,'analytic_conditional_expected_fz0']
                axes.errorbar(r['mean'],positions[k],xerr=[[r['mean']-r['ci95_lower']],[r['ci95_upper']-r['mean']]],
                              fmt='o' if h==1 else 's',ms=4,color=color,capsize=2,lw=.8,
                              markerfacecolor=color if h==1 else 'white')
                k+=1
        axes.axvline(0,color='#777777',lw=.8);axes.grid(axis='x',alpha=.17)
        axes.set_title(title,loc='left');axes.set_xlabel('Expected FZ0 difference\nNegative values favor adaptation')
        axes.set_yticks(positions,labels if axes is left else ['']*len(labels))
        axes.set_ylim(max(positions)+.7,-1)
    # Do not suppress shared labels through shared-axis assignment.
    left.set_yticks(positions,labels);right.tick_params(labelleft=False)
    fig.savefig(folder/'severity_response.pdf',metadata={'CreationDate':None,'ModDate':None})
    fig.savefig(folder/'severity_response.png',dpi=180)
    plt.close(fig)


def main():
    folder=ROOT/'results';figures=ROOT/'figures'
    paths={name:folder/name for name in ['severity_risk_protocol.json','severity_risk_results.json',
           'severity_risk_predictions.npz','severity_synthetic_results.json','severity_synthetic_results.npz']}
    protocol=json_read(paths['severity_risk_protocol.json'])
    market_result=json_read(paths['severity_risk_results.json']);synthetic_result=json_read(paths['severity_synthetic_results.json'])
    protocol_hash=digest(paths['severity_risk_protocol.json'])
    for obj in [market_result,synthetic_result]:require(obj['protocol_sha256']==protocol_hash,'Protocol hash mismatch')
    require(market_result['predictions_sha256']==digest(paths['severity_risk_predictions.npz']),'Market archive hash mismatch')
    require(synthetic_result['exemplar_predictions_sha256']==digest(paths['severity_synthetic_results.npz']),'Synthetic archive hash mismatch')
    with np.load(paths['severity_risk_predictions.npz'],allow_pickle=False) as archive:
        market,by_contract=market_summary(protocol,market_result,archive)
    synthetic=synthetic_summary(protocol,synthetic_result)
    result=dict(schema='gabriel.severity-risk.summary.v1',sources={name:digest(path) for name,path in paths.items()},
                summary_source_sha256=digest(Path(__file__)),market=market,synthetic=synthetic,
                interpretation=dict(market='All market periods were previously inspected; results are descriptive retrospective comparisons.',
                 synthetic='Independent generated replicates test mechanism behavior under declared distributions, not market superiority.',
                 difference='First model minus reference mean FZ0; negative favors first, not a return or a percentage.',
                 decomposition='Oracle expected-score excess = quantile cost + severity cost. Both are nonnegative; neither is observable without a known conditional distribution.'))
    (folder/'severity_summary.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    write_csv(folder/'severity_summary.csv',market['rows'])
    flat=[]
    for row in synthetic['aggregate_method_rows']:
        base={k:row[k] for k in ['case','latency','period','model','n_per_replicate']}
        for metric in SYN_METRICS:
            base.update({f'{metric}_{field}':row[metric][field] for field in ['mean','ci95_lower','ci95_upper']})
        flat.append(base)
    write_csv(folder/'severity_synthetic_summary.csv',flat)
    write_csv(folder/'severity_synthetic_comparisons.csv',synthetic['paired_comparisons'])
    tables(folder,by_contract,synthetic)
    with np.load(paths['severity_synthetic_results.npz'],allow_pickle=False) as archive:
        require(list(archive['models'])==MODELS+['oracle_truth'],'Changed exemplar model order')
        figure(figures,archive,synthetic)
    print(json.dumps(dict(market_rows=len(market['rows']),synthetic_method_rows=len(flat),
        paired_comparisons=len(synthetic['paired_comparisons']),market=market['comparisons']),indent=2))


if __name__=='__main__':
    main()
