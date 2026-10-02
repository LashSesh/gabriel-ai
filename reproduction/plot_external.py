"""Produce manuscript tables/figure from the delivered external test outputs."""
from pathlib import Path
import csv
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results';FIG=ROOT/'figures'
def main():
 rows=list(csv.DictReader((OUT/'external_classification.csv').open()))
 names={'raw_ridge':'Flattened ridge','mean_memory':'Mean memory','ordered_memory':'Ordered memory','trace_observer':'Fixed trace observer','euclidean_1nn':'Euclidean 1-NN'}
 t=['\\begin{tabular}{lrrr}\\toprule','Model & RacketSports & Bal. acc. & BasicMotions \\\\', '\\midrule']
 for mode,label in names.items():
  r,b=[next(x for x in rows if x['dataset']==d and x['model']==mode) for d in ['RacketSports','BasicMotions']]
  t.append(f"{label} & {r['correct']}/152 ({100*float(r['test_accuracy']):.2f}\\%) & {100*float(r['test_balanced_accuracy']):.2f}\\% & {b['correct']}/40 ({100*float(b['test_accuracy']):.1f}\\%) \\\\")
 t+=['\\bottomrule\\end{tabular}'];(OUT/'external_classification_table.tex').write_text('\n'.join(t)+'\n')
 s=list(csv.DictReader((OUT/'external_stopping.csv').open()))
 t=['\\begin{tabular}{llrrrr}\\toprule','Dataset & Mask & Missing & Random & Recent & Coefficient \\\\', '\\midrule']
 summary=[]
 for ds,j in [('RacketSports',90),('BasicMotions',300)]:
  for ms,label in [('random_half','Random half'),('middle_half','Middle half')]:
   means=[]
   for pol in ['random','recent','coefficient']:
    vals=np.array([int(x['first_resolved_query']) for x in s if x['dataset']==ds and x['mask']==ms and x['policy']==pol]);means.append(vals.mean())
    summary.append(dict(dataset=ds,mask=ms,policy=pol,missing=j,cases=len(vals),mean_queries=float(vals.mean()),median_queries=float(np.median(vals)),min_queries=int(vals.min()),max_queries=int(vals.max())))
   t.append(f'{ds} & {label} & {j} & '+ ' & '.join(f'{v:.2f}' for v in means)+r' \\')
 t+=['\\bottomrule\\end{tabular}'];(OUT/'external_acquisition_table.tex').write_text('\n'.join(t)+'\n')
 with (OUT/'external_acquisition_summary.csv').open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=summary[0]);w.writeheader();w.writerows(summary)
 plt.rcParams.update({'font.size':9,'axes.spines.top':False,'axes.spines.right':False,'pdf.fonttype':42})
 fig,axes=plt.subplots(2,2,figsize=(7,4.6),sharex=True,sharey=True,constrained_layout=True)
 for di,ds in enumerate(['RacketSports','BasicMotions']):
  a=np.load(OUT/f'external_{ds}_acquisition.npz');j=a['queries'].shape[-1]
  for mi,mask in enumerate(['random missing entries','missing middle events']):
   ax=axes[di,mi]
   for pi,(label,color,ls) in enumerate([('Random','#8c9299',':'),('Recent','#d1812c','--'),('Coefficient','#276b94','-')]):
    ax.plot(100*np.arange(j+1)/j,100*(a['verdicts'][:,mi,pi]>=0).mean(0),label=label,color=color,ls=ls,lw=1.7)
   ax.set_title(ds+' / '+mask,fontsize=9);ax.set_xlim(75,100);ax.set_ylim(-2,102);ax.grid(alpha=.2);ax.set_xticks([75,80,85,90,95,100])
   if di==1:ax.set_xlabel('Missing values retrieved (%)')
   if mi==0:ax.set_ylabel('Decisions resolved (%)')
 axes[0,0].legend(fontsize=8,loc='upper left',frameon=False)
 fig.savefig(FIG/'external_acquisition.pdf');fig.savefig(FIG/'external_acquisition.png',dpi=180)
if __name__=='__main__':main()
