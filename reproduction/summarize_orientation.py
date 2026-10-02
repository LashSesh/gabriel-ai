"""Generate the manuscript table and exact-model illustration from saved results."""
from pathlib import Path
import json
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT=Path(__file__).resolve().parents[1]


def main():
    data=json.loads((ROOT/'results/orientation_results.json').read_text())
    labels={'unit':'Unit costs','expensive_inner':'Inner edges cost 9','inner_unavailable':'Inner edges unavailable'}
    rows=[]
    for k,z in data['queries']['profiles'].items():
        cells=[]
        for policy in ('optimal','lexical','reverse','random'):
            p=z['policies'][policy];cells.append(f"{p['query_count']} / {p['cost']}")
        rows.append(labels[k]+' & '+' & '.join(cells)+r' \\')
    table=r'''\begin{table}[!htbp]\centering
\caption{Exact cycle-parity observation. Each entry is queries / total cost and applies to all 4096 compatible sign assignments. The random control is one fixed permutation, not an average over policies.}
\begin{tabular}{lrrrr}\toprule
Access model & Optimal & Lexical & Reverse & Random \\\midrule
'''+ '\n'.join(rows)+r'''
\bottomrule\end{tabular}\label{tab:orientationqueries}
\end{table}
'''
    (ROOT/'results/orientation_table.tex').write_text(table)
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False,'pdf.fonttype':42})
    fig,(ax,bx)=plt.subplots(1,2,figsize=(9.2,3.9),gridspec_kw={'width_ratios':[1.13,1]})
    angles=np.pi/2-np.arange(6)*np.pi/3
    positions={i+1:np.array([np.cos(a),np.sin(a)])*r for r in [1] for i,a in enumerate(angles)}
    positions.update({i+7:np.array([np.cos(a),np.sin(a)])*2 for i,a in enumerate(angles)})
    edges=data['topology']['operational']['edges'];seam={(1,6),(7,12),(6,7)}
    for aa,bb in edges:
        a,b=positions[aa],positions[bb];negative=(aa,bb) in seam
        ax.plot([a[0],b[0]],[a[1],b[1]],color='#b73d36' if negative else '#718797',
                lw=2.8 if negative else 1.2,zorder=1)
    for v,p in positions.items():
        ax.scatter(*p,s=270,facecolors='#eaf0f5',edgecolors='#285776',zorder=3)
        ax.text(*p,str(v),ha='center',va='center',zorder=4,fontsize=9)
    ax.scatter(0,0,s=160,marker='x',color='#939393');ax.text(0,-.28,'reference only',ha='center',fontsize=8,color='#626262')
    ax.set_aspect('equal');ax.axis('off');ax.set_title('A. Locally flat, globally twisted',fontsize=10,pad=10)
    ax.text(0,-2.6,'Red: sign -1. Every triangle has product +1.\nEach ring has product -1.',ha='center',va='center',fontsize=9)
    ax.set_ylim(-2.93,2.35);ax.set_xlim(-2.3,2.3)
    z=data['queries']['profiles']['unit']['policies'];policies=['optimal','lexical','reverse','random']
    values=[z[k]['query_count'] for k in policies]
    bars=bx.barh(np.arange(4),values,color=['#285776','#a6b3bc','#6e9189','#a6b3bc'],height=.55)
    bx.set_yticks(range(4),['Exact optimum','Lexical order','Reverse order','Fixed random order'])
    bx.invert_yaxis();bx.set_xlim(0,25.5);bx.set_xticks([0,6,12,18,24]);bx.set_xlabel('Queried signs out of 24')
    bx.set_title('B. Determining the global loop parity',fontsize=10,pad=10)
    bx.axvline(24,color='#aaa',ls=':',lw=1)
    for rect,v in zip(bars,values):bx.text(v+.35,rect.get_y()+rect.get_height()/2,str(v),va='center')
    bx.text(.03,-.26,'Exact finite model; no measurement noise.\nThe reverse control also attains the optimum.',transform=bx.transAxes,fontsize=9)
    fig.tight_layout(w_pad=2.3)
    fig.savefig(ROOT/'figures/orientation_transport.pdf',bbox_inches='tight')
    fig.savefig(ROOT/'figures/orientation_transport.png',bbox_inches='tight',dpi=170)
    plt.close(fig)

if __name__=='__main__':main()
