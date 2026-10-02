"""Manuscript tables from saved acquisition and architectural results."""
from pathlib import Path
import numpy as np,json,csv
OUT=Path(__file__).resolve().parents[1]/'results'
def main():
    rows=list(csv.DictReader((OUT/'relaxed_stopping.csv').open()));summary=[]
    lines=[r'\begin{tabular}{llrrrr}\toprule',r' & & \multicolumn{2}{c}{Derivative policy} & \multicolumn{2}{c}{Decision policy} \\',r'Dataset & Mask & Hybrid & Affine & Hybrid & Affine \\\midrule']
    for name in ['RacketSports','BasicMotions']:
      for mask,label in [('random_half','Random half'),('middle_half','Middle half')]:
        means=[]
        for policy in ['derivative','decision']:
          for bound in ['old_hybrid','affine_intersection']:
            vals=[int(r['first_resolved_query']) for r in rows if r['dataset']==name and r['mask']==mask and r['policy']==policy and r['bound']==bound];means.append(float(np.mean(vals)))
            summary.append(dict(dataset=name,mask=mask,policy=policy,bound=bound,mean_queries=means[-1],cases=len(vals)))
        lines.append(name+' & '+label+' & '+' & '.join(f'{v:.2f}' for v in means)+r' \\')
    lines += [r'\bottomrule\end{tabular}'];(OUT/'relaxed_table.tex').write_text('\n'.join(lines)+'\n')
    block=json.loads((OUT/'blocks_summary.json').read_text());control=json.loads((OUT/'block_mean_summary.json').read_text());lines=[r'\begin{tabular}{llrrr}\toprule',r'Dataset & Classifier & Correct & Random half & Middle half \\\midrule']
    for idx,name in enumerate(['RacketSports','BasicMotions']):
        n=block[idx]['cases'];d=np.load(OUT/f'external_{name}_model.npz');correct=int((d['trace_observer_test_scores'].argmax(1)==d['test_labels']).sum())
        v=[next(s['mean_queries'] for s in summary if s['dataset']==name and s['mask']==mask and s['policy']=='decision' and s['bound']=='affine_intersection') for mask in ['random_half','middle_half']]
        lines.append(name+f' & Full record, affine & {correct}/{n} & {v[0]:.2f} & {v[1]:.2f}'+r' \\')
        for label,r in [('Block mean',control[idx]),('Block observer',block[idx])]:
            lines.append(name+f' & {label} & {r["correct"]}/{n} & {r["random_half"]["mean_queries"]:.2f} & {r["middle_half"]["mean_queries"]:.2f}'+r' \\')
    lines += [r'\bottomrule\end{tabular}'];(OUT/'blocks_table.tex').write_text('\n'.join(lines)+'\n')
    witnesses=json.loads((OUT/'witness_summary.json').read_text());lines=[r'\begin{tabular}{llrrrrr}\toprule',r'Dataset & Mask & $0$ & $\lfloor J/2\rfloor$ & $\lfloor3J/4\rfloor$ & $\lfloor9J/10\rfloor$ & $J-6$ \\\midrule']
    for name in ['RacketSports','BasicMotions']:
      for mask,label in [('random_half','Random half'),('middle_half','Middle half')]:
        rr=[r for r in witnesses if r['dataset']==name and r['mask']==mask]
        lines.append(name+' & '+label+' & '+' & '.join(str(r['validated_witnesses']) for r in rr)+r' \\')
    lines += [r'\bottomrule\end{tabular}'];(OUT/'witness_table.tex').write_text('\n'.join(lines)+'\n')
    (OUT/'decision_summary.json').write_text(json.dumps(dict(relaxed=summary,witness_boxes=sum(r['cases'] for r in witnesses),validated_ambiguous_boxes=sum(r['validated_witnesses'] for r in witnesses)),indent=2))
if __name__=='__main__':main()
