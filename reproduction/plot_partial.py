"""Build publication figures and tables from saved partial-observation results."""
import csv
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=Path(__file__).resolve().parents[1]

def main():
    rows=list(csv.DictReader((ROOT/'results/partial_summary.csv').open()))
    def get(t,p,b):return next(r for r in rows if r['task']==t and r['policy']==p and int(r['queries'])==b)
    tasks=['order_state_tau2','frozen_order_readout'];policies=['random','recent','minimax']
    labels={'random':'Random','recent':'Recent first','minimax':'Minimax width'}
    colors={'random':'#86919D','recent':'#196B8C','minimax':'#C66235'}
    lines=[r'\begin{tabular}{llrrrr}\toprule',r'Observable & Query rule & At 4 & At 8 & Box at 8 & Width at 8 \\\midrule']
    for t,name in zip(tasks,['Order state','Frozen readout']):
        for p in policies:
            a=get(t,p,4);b=get(t,p,8)
            lines.append(f'{name} & {labels[p]} & {a["resolved"]} & {b["resolved"]} & {b["box_resolved"]} & {float(b["mean_relative_width"]):.4f}'+r' \\')
    lines.append(r'\bottomrule\end{tabular}')
    (ROOT/'results/partial_table.tex').write_text('\n'.join(lines)+'\n')
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False,'pdf.fonttype':42})
    fig,ax=plt.subplots(1,2,figsize=(10,3.5),layout='constrained')
    for p in policies:
        y=[100*int(get(tasks[1],p,b)['resolved'])/128 for b in range(13)]
        ax[0].plot(range(13),y,'o-',color=colors[p],label=labels[p],markersize=3)
    ax[0].set(xlabel='Queried missing scalar entries',ylabel='Resolved signs (%)',xlim=(0,12),ylim=(0,103),title='A. Frozen readout; 128 buffered cases')
    ax[0].legend(frameon=False,fontsize=9)
    xs=np.arange(2)
    ax[1].bar(xs-.18,[int(get(t,'minimax',8)['resolved']) for t in tasks],.34,color='#C66235',label='Exact vertex range')
    ax[1].bar(xs+.18,[int(get(t,'minimax',8)['box_resolved']) for t in tasks],.34,color='#86919D',label='Coordinate-box propagation')
    ax[1].set_xticks(xs,['Order state','Frozen readout']);ax[1].set(ylabel='Resolved cases out of 128',ylim=(0,145),title='B. Same eight minimax queries')
    ax[1].legend(frameon=False,fontsize=9)
    for ext in ['pdf','png']:fig.savefig(ROOT/f'figures/partial_observation.{ext}',dpi=180)
    plt.close(fig)

if __name__=='__main__':main()
