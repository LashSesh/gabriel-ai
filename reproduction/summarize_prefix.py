"""Tables and a scientific figure generated exclusively from saved outputs."""
from pathlib import Path
import numpy as np,csv,json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results'
NAMES=['RacketSports','BasicMotions','NATOPS','Epilepsy']
MODELS=['full_observer','reset_blocks','shared_prefix','stage_prefix','stage_mean']
LABELS=['Full observer','Reset blocks','Shared prefix','Stage prefix','Stage mean']
MASKS=['random_half','middle_half','stream_all']

def main():
    models=list(csv.DictReader((OUT/'prefix_models.csv').open()));stops=list(csv.DictReader((OUT/'prefix_stopping.csv').open()));summary=[]
    for name in NAMES:
      for model in MODELS:
       row=next(r for r in models if r['dataset']==name and r['model']==model);ans=dict(row)
       for mask in MASKS:
        rr=[r for r in stops if r['dataset']==name and r['model']==model and r['mask']==mask and r['rule']=='tie_aware']
        strict=[r for r in stops if r['dataset']==name and r['model']==model and r['mask']==mask and r['rule']=='strict']
        q=np.array([int(r['queries']) for r in rr]);j=np.array([int(r['missing']) for r in rr]);sq=np.array([int(r['queries']) for r in strict]);assert np.all(q<=sq)
        ans[mask]=dict(missing=int(j[0]),mean_queries=float(q.mean()),mean_fraction=float(np.mean(q/j)),median_fraction=float(np.median(q/j)),early=int((q<j).sum()),strict_mean_queries=float(sq.mean()),tie_improved_cases=int((q<sq).sum()),saved_by_tie_mean=float((sq-q).mean()))
       summary.append(ans)
    (OUT/'prefix_summary.json').write_text(json.dumps(summary,indent=2))
    for subset,key in [(NAMES[:2],'development'),(NAMES[2:],'new')]:
      lines=[r'\begin{tabular}{llrrrrr}\toprule',r'Dataset & Classifier & Correct & BA (\%) & Random & Middle & Stream \\\midrule']
      for name in subset:
       for model,label in zip(MODELS,LABELS):
        r=next(r for r in summary if r['dataset']==name and r['model']==model)
        nums=[f"{100*r[mask]['mean_fraction']:.2f}" for mask in MASKS]
        lines.append(f"{name if model=='full_observer' else ''} & {label} & {r['correct']}/{r['cases']} & {100*float(r['balanced_accuracy']):.2f} & "+' & '.join(nums)+r' \\')
       if name!=subset[-1]:lines.append(r'\midrule')
      lines.append(r'\bottomrule\end{tabular}');(OUT/f'prefix_{key}_table.tex').write_text('\n'.join(lines)+'\n')
    # Paired changes guard against treating equal counts as equal predictions.
    lines=[r'\begin{tabular}{llrrrr}\toprule',r'Dataset & Prefix head & Changed & Lost & Gained & Net \\\midrule']
    for name in NAMES:
     for model,label in [('shared_prefix','Shared'),('stage_prefix','Stage')]:
      r=next(r for r in summary if r['dataset']==name and r['model']==model)
      lines.append(f"{name} & {label} & {r['changed']} & {r['lost']} & {r['gained']} & {int(r['gained'])-int(r['lost']):+d}"+r' \\')
    lines.append(r'\bottomrule\end{tabular}');(OUT/'prefix_paired_table.tex').write_text('\n'.join(lines)+'\n')
    plt.rcParams.update({'font.size':9,'pdf.fonttype':42})
    fig,axs=plt.subplots(2,2,figsize=(7,5.4),sharex=True)
    colors=['#666666','#be7531','#2473a6','#23834c','#ad5791'];markers=['s','D','o','^','x']
    for ax,name in zip(axs.flat,NAMES):
      for model,label,c,m in zip(MODELS,LABELS,colors,markers):
       r=next(r for r in summary if r['dataset']==name and r['model']==model)
       ax.scatter(100*r['stream_all']['mean_fraction'],100*float(r['balanced_accuracy']),color=c,marker=m,s=52,label=label,zorder=3)
      ax.set_title(name);ax.grid(alpha=.2);ax.set_xlim(55,104)
      ax.set_ylabel('Balanced accuracy (%)')
    for ax in axs[-1]:ax.set_xlabel('Mean record observed from start (%)')
    handles,labels=axs[0,0].get_legend_handles_labels();fig.legend(handles,labels,ncol=3,loc='lower center',frameon=False)
    fig.tight_layout(rect=(0,.10,1,1));fig.savefig(ROOT/'figures/prefix_tradeoff.pdf');fig.savefig(ROOT/'figures/prefix_tradeoff.png',dpi=160);plt.close(fig)
    print('20 model summaries; three tables; one figure')
if __name__=='__main__':main()
