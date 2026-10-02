"""Plot descriptive matched-owner timing results; no confidence intervals."""
from pathlib import Path
import json
import statistics
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
data=json.loads((ROOT/'results/fast_owner_benchmark.json').read_text())
assert data['status']=='passed'
fig,axes=plt.subplots(2,2,figsize=(10.8,7.3),layout='constrained')
colors={'reference_owner':'#566573','fast_owner':'#147d92'}
labels={'reference_owner':'Reference owner','fast_owner':'Structural-copy owner'}
source={}
ax=axes[0,0];widths=[r['width'] for r in data['register']];x=np.arange(len(widths))
for shift,key in [(-.18,'reference_owner'),(.18,'fast_owner')]:
    vals=[r['summary'][key]['median']*1000/r['commands_per_trial'] for r in data['register']]
    low=[v-r['summary'][key]['minimum']*1000/r['commands_per_trial'] for v,r in zip(vals,data['register'])]
    high=[r['summary'][key]['maximum']*1000/r['commands_per_trial']-v for v,r in zip(vals,data['register'])]
    ax.bar(x+shift,vals,.34,color=colors[key],label=labels[key],yerr=[low,high],capsize=3)
    source['register_'+key+'_ms_per_command']=vals
ax.set_xticks(x,[str(w) for w in widths]);ax.set_xlabel('Number of integer registers');ax.set_ylabel('Time per durable command (ms)')
ax.set_title('(a) Domain-independent accumulator');ax.legend(fontsize=8)
ax=axes[0,1]
for stream in data['stream']:
    h=stream['horizon'];ns=[c['source_length'] for c in stream['checkpoints']]
    for key in colors:
        values=[c['transition_summaries']['append'][key]['median']*1000 for c in stream['checkpoints']]
        ax.plot(ns,values,marker='o' if h==1 else 's',linestyle='-' if h==1 else '--',color=colors[key],label=f'{labels[key]}, h={h}')
        source[f'append_h{h}_{key}_median_ms']=values
ax.set_xlabel('Start of 21-observation neighborhood');ax.set_ylabel('Complete durable append (ms)')
ax.set_title('(b) Unchanged incremental stream profile');ax.legend(fontsize=7)
ax=axes[1,0]; names=[]; vectors={k:[] for k in colors}
for stream in data['stream']:
    c=stream['checkpoints'][-1]
    for kind,short in [('early_correction_then_append','Early'),('recent_correction_then_append','Recent')]:
        names.append(f'{short}\nh={stream["horizon"]}')
        for key in colors:vectors[key].append(c['transition_summaries'][kind][key]['median']*1000)
x=np.arange(len(names))
for shift,key in [(-.18,'reference_owner'),(.18,'fast_owner')]:ax.bar(x+shift,vectors[key],.34,color=colors[key])
ax.set_xticks(x,names);ax.set_ylabel('Correction + durable append (ms)');ax.set_title('(c) Neighborhood beginning at 800 observations')
source['correction_bundle_labels']=names;source['correction_bundle_median_ms']=vectors
ax=axes[1,1]
for stream in data['stream']:
    h=stream['horizon'];ns=[c['source_length'] for c in stream['checkpoints']]
    for key in colors:
        values=[c['cold_open_summary'][key]['median'] for c in stream['checkpoints']]
        ax.plot(ns,values,marker='o' if h==1 else 's',linestyle='-' if h==1 else '--',color=colors[key])
        source[f'cold_open_h{h}_{key}_seconds']=values
ax.set_xlabel('Number of source observations');ax.set_ylabel('Fresh-adapter open with full replay (s)');ax.set_title('(d) Warm filesystem; 5 / 1 / 1 paired runs')
for ax in axes.flat:
    ax.spines[['top','right']].set_visible(False);ax.grid(axis='y',alpha=.2);ax.set_axisbelow(True)
fig.savefig(ROOT/'figures/fast_owner_execution.pdf')
fig.savefig(ROOT/'figures/fast_owner_execution.png',dpi=170)
(ROOT/'results/fast_owner_figure_data.json').write_text(json.dumps(source,sort_keys=True,indent=2)+'\n')
print('Saved figures/fast_owner_execution.pdf and .png and results/fast_owner_figure_data.json')
