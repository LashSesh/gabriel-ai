"""Plot retained synthetic append timings; no benchmark is executed here."""
from pathlib import Path
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
data = json.loads((ROOT/'results/incremental_benchmark.json').read_text())
assert data['status'] == 'passed'
selected = [r for r in data['terminal_transitions'] if r['transition'] == 'append']
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10.5,
                     'axes.spines.top':False,'axes.spines.right':False,
                     'pdf.fonttype':42})
fig, axes = plt.subplots(1,2,figsize=(8.4,3.6),sharex=True)
colors = {'baseline':'#aa4f19','incremental':'#136f83'}
records=[]
for ax,key,title in zip(axes,['kernel_time','adapter_time'],
                        ['Numerical-call interval','Complete adapter transition']):
    for h,style,mark in [(1,'-','o'),(5,'--','s')]:
        rows=sorted([r for r in selected if r['horizon']==h],key=lambda r:r['source_length'])
        x=np.array([r['source_length'] for r in rows])
        for label in ['baseline','incremental']:
            stats=[r[key][label] for r in rows]
            y=np.array([r['median']*1000 for r in stats])
            lo=np.array([r['min']*1000 for r in stats]); hi=np.array([r['max']*1000 for r in stats])
            ax.errorbar(x,y,yerr=np.array([y-lo,hi-y]),linestyle=style,marker=mark,
                        color=colors[label],capsize=3,linewidth=1.3,markersize=4,
                        label=('Reference' if label=='baseline' else 'Incremental')+f', h={h}')
            for n,median,minimum,maximum in zip(x,y,lo,hi):
                records.append({'interval':key,'horizon':h,'implementation':label,
                                'source_length':int(n),'median_ms':float(median),
                                'min_ms':float(minimum),'max_ms':float(maximum)})
    ax.set_title(title,fontsize=11,pad=8)
    ax.set_xlabel('Source observations after append')
    ax.set_ylabel('Elapsed time (ms; logarithmic scale)')
    ax.set_yscale('log');ax.set_xticks([360,500,800]);ax.grid(alpha=.18,which='both')
handles,labels=axes[0].get_legend_handles_labels()
fig.legend(handles,labels,loc='lower center',ncol=4,frameon=False,bbox_to_anchor=(.5,-.025),fontsize=9.5)
fig.tight_layout(rect=(0,.09,1,1),w_pad=1.6)
(ROOT/'figures').mkdir(exist_ok=True)
fig.savefig(ROOT/'figures/incremental_execution.pdf',bbox_inches='tight')
fig.savefig(ROOT/'figures/incremental_execution.png',dpi=180,bbox_inches='tight')
(ROOT/'results/incremental_figure_data.json').write_text(json.dumps({
    'source':'incremental_benchmark.json','synthetic':True,'summary':'median and observed range of three paired local trials',
    'records':records},indent=2)+'\n')
print('saved incremental_execution.pdf/png and retained plot values')
