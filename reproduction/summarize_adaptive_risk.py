"""Generate manuscript summaries from the frozen adaptive-risk results."""
from pathlib import Path
import csv,json
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=Path(__file__).resolve().parents[1]

def main():
 r=json.loads((ROOT/'results/adaptive_risk_results.json').read_text())
 periods=['retrospective','temporal_extension'];models=['raw_hs','fast_fhs','multiscale_fhs','static_selected','lane_primary','lane_selected','pooled_primary']
 rows=[];summary={}
 for period in periods:
  summary[period]={}
  for model in models:
   wins=ties=losses=gw=gt=gl=0
   for c in r['contracts']:
    a=c['models'][model][period];b=c['models']['fast_fhs'][period]
    delta=a['mean_fz0']-b['mean_fz0'];gap=a['absolute_frequency_gap_from_beta']-b['absolute_frequency_gap_from_beta']
    wins+=delta < -1e-12;losses+=delta>1e-12;ties+=abs(delta)<=1e-12
    gw+=gap < -1e-12;gl+=gap>1e-12;gt+=abs(gap)<=1e-12
    rows.append(dict(period=period,currency=c['currency'],horizon=c['horizon'],model=model,n=a['n'],mean_fz0=a['mean_fz0'],fz0_difference_from_fast=delta,exceedances=a['exceedances'],exceedance_percent=100*a['exceedance_fraction'],frequency_gap_difference_pp=100*gap,es_residual=a['mean_es_identification_residual'],selected_eta=c['selected_eta'],selected_static_theta=c['selected_static_theta']))
   summary[period][model]={'fz0_better_tied_worse':[wins,ties,losses],'frequency_gap_better_tied_worse':[gw,gt,gl]}
 with (ROOT/'results/adaptive_risk_summary.csv').open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
 summary.update(period_contract_cases=r['period_contract_cases'],period_forecast_pairs=r['period_forecast_pairs'],all_history_projection_count=sum(sum(c['all_history_projection_counts'].values()) for c in r['contracts']))
 (ROOT/'results/adaptive_risk_summary.json').write_text(json.dumps(summary,indent=2)+'\n')
 table=[r'\begin{tabular}{@{}lrrrrr@{}}\toprule',r'Currency & $h$ & Fast FZ0 & $\Delta$ static & $\Delta$ primary & $\Delta$ selected\\\midrule']
 for period,label in zip(periods,['Retrospective: 2020--2025','Temporal extension: 2026 through 25 September']):
  table.append(r'\multicolumn{6}{l}{\textit{'+label+r'}}\\')
  for c in r['contracts']:
   m=c['models'];b=m['fast_fhs'][period]['mean_fz0'];ds=[m[k][period]['mean_fz0']-b for k in ['static_selected','lane_primary','lane_selected']]
   table.append(c['currency']+f" & {c['horizon']} & {b:.4f}"+''.join(f' & {v:+.4f}' for v in ds)+r'\\')
  if period==periods[0]:table.append(r'\midrule')
 table.append(r'\bottomrule\end{tabular}');(ROOT/'results/adaptive_score_table.tex').write_text('\n'.join(table)+'\n')
 table=[r'\begin{tabular}{@{}lrrrrrr@{}}\toprule',r'Currency & $h$ & $n$ & Fast & Static & Primary & Selected\\\midrule']
 for c in r['contracts']:
  m=c['models'];p='temporal_extension';table.append(c['currency']+f" & {c['horizon']} & {m['fast_fhs'][p]['n']}"+''.join(f" & {m[k][p]['exceedances']}" for k in ['fast_fhs','static_selected','lane_primary','lane_selected'])+r'\\')
 table.append(r'\bottomrule\end{tabular}');(ROOT/'results/adaptive_counts_table.tex').write_text('\n'.join(table)+'\n')
 plt.rcParams.update({'font.size':8,'pdf.fonttype':42,'ps.fonttype':42})
 fig,axes=plt.subplots(2,2,figsize=(6.35,5.1),layout='constrained')
 labels=[f"{c['currency']}  h={c['horizon']}" for c in r['contracts']]
 for row,p in enumerate(periods):
  ds=[];dg=[]
  for c in r['contracts']:
   b=c['models']['fast_fhs'][p];a=c['models']['lane_primary'][p]
   ds.append(a['mean_fz0']-b['mean_fz0']);dg.append(100*(a['absolute_frequency_gap_from_beta']-b['absolute_frequency_gap_from_beta']))
  for col,values in enumerate([ds,dg]):
   ax=axes[row,col];y=np.arange(len(values));ax.barh(y,values,color=['#336e94' if v<0 else '#b56a35' for v in values],height=.65)
   ax.set_yticks(y,labels if col==0 else ['']*len(labels));ax.invert_yaxis();ax.axvline(0,color='0.3',lw=.7);ax.grid(axis='x',alpha=.2);ax.set_axisbelow(True)
   ax.set_xlabel('FZ0 change (primary minus fast)' if col==0 else 'Breach-frequency error change (pp)')
   ax.set_title(('2020–2025 retrospective' if row==0 else '2026 temporal extension')+('' if col==0 else ': calibration'),fontsize=9)
 fig.savefig(ROOT/'figures/adaptive_risk_tradeoff.pdf');fig.savefig(ROOT/'figures/adaptive_risk_tradeoff.png',dpi=170);plt.close(fig)
 print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
