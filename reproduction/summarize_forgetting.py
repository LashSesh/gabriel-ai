"""Paired known-law and development summaries; no further method selection."""
from pathlib import Path
import json,csv
import numpy as np
from scipy.stats import t as student_t
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=Path(__file__).resolve().parents[1]

def interval(x):
 x=np.asarray(x,float);m=float(x.mean());se=float(x.std(ddof=1)/np.sqrt(len(x)));half=float(student_t.ppf(.975,len(x)-1)*se)
 return dict(mean=m,lower=m-half,upper=m+half,n=len(x))

def main():
 p=json.loads((ROOT/'results/forgetting_design_v2.json').read_text());final=json.loads((ROOT/'results/forgetting_final_selection.json').read_text());variants=final['all_variants']+json.loads((ROOT/'results/forgetting_ablation_design.json').read_text())['variants'];models=[v['name'] for v in variants];cases=p['synthetic']['cases'];hs=p['synthetic']['latencies'];records=[];dev=[]
 for tag in ['','_refinement','_ablation']:
  records+=json.loads((ROOT/'results'/f'forgetting{tag}_synthetic.json').read_text())['records'];dev+=json.loads((ROOT/'results'/f'forgetting{tag}_development.json').read_text())['records']
 lookup={(r['case'],r['latency'],r['model'],r['replicate']):r for r in records}
 a=np.empty((len(cases),len(hs),len(models),32))
 for ci,case in enumerate(cases):
  for hi,h in enumerate(hs):
   for mi,model in enumerate(models):
    a[ci,hi,mi]=[lookup[case,h,model,rep]['periods']['all']['conditional_excess_fz0'] for rep in range(32)]
 baseline=models.index('cumulative');changing=np.array([not c.startswith('stationary') for c in cases]);devmean={m:float(np.mean([r['mean_fz0'] for r in dev if r['model']==m])) for m in models};rows=[];matched=[];percase=[]
 for mi,v in enumerate(variants):
  difference=a[:,:,mi]-a[:,:,baseline];moving=difference[changing].mean(axis=(0,1));stationary=difference[~changing].mean(axis=(0,1))
  row=dict(**v,development_mean=devmean[v['name']],development_delta=devmean[v['name']]-devmean['cumulative'],changing_excess_mean=float(a[changing,:,mi].mean()),changing_difference=interval(moving),stationary_difference=interval(stationary),maximum_stationary_case_latency_penalty=float(difference[~changing].mean(axis=2).max()),eligible=final['candidates'].get(v['name'],{}).get('eligible',False),role='screened' if v['name'] in final['candidates'] else 'post-screen matched-step control');rows.append(row)
  if v['kind']!='cumulative':
   ref='cumulative' if v['c']==.1 else 'cumulative_c'+str(v['c']).replace('.','p');ri=models.index(ref);d=(a[:,:,mi]-a[:,:,ri])[changing].mean(axis=(0,1));matched.append(dict(model=v['name'],reference=ref,kind=v['kind'],memory=v['memory'],c=v['c'],development_difference=devmean[v['name']]-devmean[ref],changing_difference=interval(d)))
  for ci,case in enumerate(cases):
   for hi,h in enumerate(hs):percase.append(dict(case=case,latency=h,model=v['name'],excess_mean=float(a[ci,hi,mi].mean()),difference=interval(difference[ci,hi])))
 summary=dict(schema='gabriel.forgetting.summary.v1',rows=rows,matched_controls=matched,per_case=percase,primary_model=final['primary_model'],eligible=final['eligible'],record_count=len(records),scope='All synthetic comparisons are constructed mechanism/development experiments; intervals are marginal paired t intervals over32 independent replicate groups, with both latencies and all selected cases averaged within each group. No market transfer was executed.')
 (ROOT/'results/forgetting_summary.json').write_text(json.dumps(summary,indent=2)+'\n')
 with (ROOT/'results/forgetting_summary.csv').open('w',newline='') as f:
  fields=['model','kind','memory','c','development_mean','development_delta','changing_difference','lower','upper','max_stationary_penalty','eligible','role'];w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
  for r in rows:w.writerow(dict(model=r['name'],kind=r['kind'],memory=r['memory'],c=r['c'],development_mean=r['development_mean'],development_delta=r['development_delta'],changing_difference=r['changing_difference']['mean'],lower=r['changing_difference']['lower'],upper=r['changing_difference']['upper'],max_stationary_penalty=r['maximum_stationary_case_latency_penalty'],eligible=r['eligible'],role=r['role']))
 lines=[r'\begin{tabular}{lrrrrr}\toprule',r'Rule & $m$ & $c$ & $\Delta$ development & $\Delta$ changing law & Worst stationary $\Delta$\\\midrule']
 labels={'cumulative':'Cumulative','discount':'Discounted','window':'Window','restart':'Restart'}
 # Group same-rule settings to keep interpretation visible.
 for r in sorted(rows,key=lambda x:(['cumulative','discount','window','restart'].index(x['kind']),x['memory'],x['c'])):
  lines.append(f"{labels[r['kind']]} & {r['memory'] or '--'} & {r['c']:g} & {r['development_delta']:+.5f} & {r['changing_difference']['mean']:+.5f} & {r['maximum_stationary_case_latency_penalty']:+.5f}\\\\")
 lines.append(r'\bottomrule\end{tabular}');(ROOT/'results/forgetting_selection_table.tex').write_text('\n'.join(lines)+'\n')
 fig,axes=plt.subplots(1,2,figsize=(10,3.8),layout='constrained')
 colors=['#1565c0','#42a5f5','#ef6c00','#ffb74d']
 for (kind,memory),color in zip([('discount',125),('discount',500),('window',125),('window',500)],colors):
  group=sorted([x for x in matched if x['kind']==kind and x['memory']==memory],key=lambda x:x['c']);x=[r['c'] for r in group];means=np.array([r['changing_difference']['mean'] for r in group]);lo=np.array([r['changing_difference']['lower'] for r in group]);hi=np.array([r['changing_difference']['upper'] for r in group]);label=f'{kind.capitalize()}, {memory}'
  axes[0].errorbar(x,means,yerr=[means-lo,hi-means],label=label,color=color,marker='o',capsize=2);axes[1].plot(x,[r['development_difference'] for r in group],color=color,marker='o',label=label)
 for ax in axes:ax.axhline(0,color='black',lw=.7);ax.set_xscale('log',base=2);ax.set_xticks([.025,.05,.1,.2],['0.025','0.05','0.1','0.2']);ax.set_xlabel('Step multiplier c');ax.grid(alpha=.15)
 axes[0].set_title('Changing known laws');axes[0].set_ylabel('Conditional expected-score difference');axes[1].set_title('Old-currency development, 2015–2019');axes[1].set_ylabel('Development FZ0 difference');axes[0].legend(fontsize=8);fig.savefig(ROOT/'figures/forgetting_matched_controls.pdf');fig.savefig(ROOT/'figures/forgetting_matched_controls.png',dpi=170);plt.close(fig)
 # Reference path is fixed replicationzero, not the best observed example.
 ar=np.load(ROOT/'results/forgetting_synthetic.npz',allow_pickle=False);key='joint_recurrent_1';t=np.arange(6000);true=ar[key+'_scale']*(1+ar[key+'_tail_mean']);fig,ax=plt.subplots(figsize=(9.5,3.1),layout='constrained');ax.plot(t,true,color='black',lw=1.5,label='True conditional ES')
 for model,color in [('cumulative','#1565c0'),('discount_125','#ef6c00'),('restart_125','#8e24aa')]:ax.plot(t,ar[key+'_'+model+'_es'],lw=.8,alpha=.85,label=model.replace('_',' '),color=color)
 ax.set_xlabel('Synthetic origin');ax.set_ylabel('Issued ES');ax.set_title('Known recurrent law, latency one, replication zero');ax.legend(fontsize=8,ncol=2);fig.savefig(ROOT/'figures/forgetting_path.pdf');fig.savefig(ROOT/'figures/forgetting_path.png',dpi=170);plt.close(fig)
 print('ROWS',len(rows),'METRIC_RECORDS',len(records),'PRIMARY',final['primary_model'])
 for name in ['discount_125','discount_500','restart_125','restart_500']:
  r=next(r for r in rows if r['name']==name);print(name,r['changing_difference'],'dev',r['development_delta'])
if __name__=='__main__':main()
