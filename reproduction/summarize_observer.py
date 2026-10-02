"""Regenerate manuscript tables and plain JSON summaries from saved outputs."""
from pathlib import Path
import numpy as np,csv,json
from benchmark_observer import NAMES,POLICIES,MASKS,ENCLOSURES
OUT=Path(__file__).resolve().parents[1]/'results'

def main():
 rows=list(csv.DictReader((OUT/'observer_stopping.csv').open()));summary=[]
 tab=[r'\begin{tabular}{llrrrr}\toprule',r'Dataset & Mask & Missing & Random & Recent & Derivative \\ \midrule']
 ab=[r'\begin{tabular}{llrrr}\toprule',r'Dataset & Mask & Basic & Structured & Hybrid \\ \midrule']
 for name in NAMES:
  z=np.load(OUT/f'observer_{name}_acquisition.npz')
  for ms,mask in enumerate(MASKS):
   vals=[];av=[];J=z['queries'].shape[-1]
   for policy in POLICIES:
    rr=[r for r in rows if r['dataset']==name and r['mask']==mask and r['policy']==policy and r['enclosure']=='hybrid'];v=np.array([int(r['first_resolved_query']) for r in rr]);vals.append(v.mean())
    summary.append(dict(dataset=name,mask=mask,policy=policy,enclosure='hybrid',mean_stop=float(v.mean()),median_stop=float(np.median(v)),min_stop=int(v.min()),max_stop=int(v.max()),missing=J,cases=len(v),resolved_at_half=int(np.sum(v<=J//2)),resolved_at_three_quarters=int(np.sum(v<=3*J//4)),resolved_before_full=int(np.sum(v<J))))
   for en in ENCLOSURES:av.append(np.mean([int(r['first_resolved_query']) for r in rows if r['dataset']==name and r['mask']==mask and r['policy']=='derivative' and r['enclosure']==en]))
   label='Random half' if ms==0 else 'Middle half';tab.append(f'{name} & {label} & {J} & '+' & '.join(f'{v:.2f}' for v in vals)+r' \\');ab.append(f'{name} & {label} & '+' & '.join(f'{v:.2f}' for v in av)+r' \\')
 tab.append(r'\bottomrule\end{tabular}');ab.append(r'\bottomrule\end{tabular}')
 (OUT/'observer_acquisition_table.tex').write_text('\n'.join(tab));(OUT/'observer_ablation_table.tex').write_text('\n'.join(ab))
 (OUT/'observer_summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary,indent=2))
 nr=list(csv.DictReader((OUT/'observer_noise.csv').open()));nt=[r'\begin{tabular}{lrrrrrr}\toprule',r'Dataset / radius & 0 & 0.005 & 0.01 & 0.02 & 0.05 & 0.10 \\ \midrule']
 for name in NAMES:
  rr=[r for r in nr if r['dataset']==name and r['enclosure']=='hybrid'];nt.append(name+' & '+' & '.join(r['resolved']+'/'+r['cases'] for r in rr)+r' \\')
 nt.append(r'\bottomrule\end{tabular}');(OUT/'observer_noise_table.tex').write_text('\n'.join(nt))
if __name__=='__main__':main()
