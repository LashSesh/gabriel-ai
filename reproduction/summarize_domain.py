"""Generate manuscript tables and a static comparison figure from saved paths."""
from pathlib import Path
from fractions import Fraction
import json
import csv
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
data=json.loads((ROOT/'results/domain_benchmark.json').read_text())
reduced=json.loads((ROOT/'results/domain_reduction.json').read_text())
policies=['fixed','reverse','hypothesis_entropy','ec2','minimax']
short={'conservative_transport':'T','event_order':'E',
       'domain_predicate':'D','frozen_gabriel_readout':'G'}
def number(s):return float(Fraction(s))
def cost(v):return f"{number(v['mean_cost']):.2f}/{v['worst_cost']}"
lines=[r'\begin{table}[htbp]\centering\small',
       r'\caption{Exhaustive finite-model query costs: mean/worst. T is conservative transport; E is event order; D is the domain predicate and G the frozen Gabriel readout. $K$ is the number of independent metadata values. Every policy stops on target agreement; constant queries are skipped.}\label{tab:domain}',
       r'\begin{tabular}{lrrrrrr}\toprule',r'Task & $K$ & Fixed & Reverse & Entropy & EC$^2$ & Minimax \\ \midrule']
for i,s in enumerate(data['studies']):
    if i and i%3==0:lines.append(r'\addlinespace')
    tag=short[s['domain']]+'--'+short[s['target']]
    lines.append(tag+' & '+str(s['nuisance_values'])+' & '+' & '.join(cost(s['policies'][p]) for p in policies)+r' \\')
lines += [r'\bottomrule\end{tabular}',r'\end{table}']
(ROOT/'results/domain_table.tex').write_text('\n'.join(lines)+'\n')
with (ROOT/'results/domain_summary.csv').open('w') as f:
    writer=csv.writer(f);writer.writerow(['domain','target','metadata_values','policy','mean_cost','worst_cost','cases','ambiguous_physical_at_decision'])
    for s in data['studies']:
        for p,v in s['policies'].items():
            writer.writerow([s['domain'],s['target'],s['nuisance_values'],p,v['mean_cost'],v['worst_cost'],v['total'],v['ambiguous_physical_at_decision']])
lines=[r'\begin{table}[htbp]\centering\small',
       r'\caption{Exploratory removal of independent queries, $K=16$. Counts before/after refer to distinct labelled rows and memoized Bellman states. Mean costs after reduction are shown for the two greedy policies; minimax costs are unchanged.}\label{tab:domainreduction}',
       r'\begin{tabular}{lrrrr}\toprule',r'Task & Labelled rows & Bellman states & Entropy & EC$^2$ \\ \midrule']
selected=[]
for s in reduced['studies']:
    if s['nuisance_values']!=16:continue
    selected.append(s)
    tag=short[s['domain']]+'--'+short[s['target']]
    lines.append(f"{tag} & {s['hypotheses_before']}/{s['hypotheses_after']} & {s['bellman_states_before']}/{s['bellman_states_after']} & {number(s['policies']['hypothesis_entropy']['mean_cost']):.2f} & {number(s['policies']['ec2']['mean_cost']):.2f}"+r' \\')
lines += [r'\bottomrule\end{tabular}',r'\end{table}']
(ROOT/'results/domain_reduction_table.tex').write_text('\n'.join(lines)+'\n')
plt.rcParams.update({'font.size':11,'axes.labelsize':11,'legend.fontsize':10})
fig,axes=plt.subplots(2,2,figsize=(8,5.4),layout='constrained',sharey=True)
chosen=['hypothesis_entropy','ec2','minimax']
for ax,s in zip(axes.flat,selected):
    before=next(v for v in data['studies'] if all(v[k]==s[k] for k in ('domain','target','nuisance_values')))
    x=np.arange(3)
    ax.bar(x-.18,[number(before['policies'][p]['mean_cost']) for p in chosen],.36,label='Full catalogue',color='#7184a7')
    ax.bar(x+.18,[number(s['policies'][p]['mean_cost']) for p in chosen],.36,label='Independent queries removed',color='#227a69')
    ax.set_xticks(x,['Entropy',r'EC$^2$','Minimax']);ax.set_ylim(0,3.4)
    ax.set_title(('Transport' if s['domain'].startswith('conservative') else 'Event order')+' / '+('domain target' if s['target']=='domain_predicate' else 'Gabriel target'),fontsize=11)
    ax.set_ylabel('Mean queries');ax.spines[['top','right']].set_visible(False);ax.grid(axis='y',alpha=.18);ax.set_axisbelow(True)
handles,labels=axes[0,0].get_legend_handles_labels()
fig.legend(handles,labels,loc='outside lower center',ncol=2,frameon=False)
fig.savefig(ROOT/'figures/domain_observation.pdf')
fig.savefig(ROOT/'figures/domain_observation.png',dpi=180)
print('wrote domain tables, CSV and figure')
