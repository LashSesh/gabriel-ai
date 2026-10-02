"""Figures and tables built from executed outputs, not hand-entered results."""
import csv
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
from multitime import OrderedMemory
ROOT=Path(__file__).resolve().parents[1]
LABELS={'event_hybrid':'Event hybrid','elapsed_symmetric':'Elapsed symmetric',
 'elapsed_ordered':'Elapsed ordered','elapsed_quadratic':'Elapsed quadratic','combined':'Concatenated','routed':'Selected heads'}

def texnum(x, digits):
    s=f'{x:.{digits}g}'
    if 'e' not in s:return s
    a,b=s.split('e')
    return a+r'\times10^{'+str(int(b))+'}'

def main():
    rows=list(csv.DictReader((ROOT/'results/multitime_routing_summary.csv').open()))
    tasks=['event_delay6','physical_fast','physical_slow','ordered_history']
    for regime in ['same_duration','shorter_duration']:
        lines=[r'\begin{tabular}{lrrrr}\toprule',r'Model & Event delay & Fast filter & Slow filter & Order \\\midrule']
        for model,label in LABELS.items():
            vals=[]
            for task in tasks:
                r=next(r for r in rows if r['regime']==regime and r['model']==model and r['task']==task)
                x=float(r['mean']);s=float(r['sd'])
                vals.append('$<10^{-14}$' if x<1e-14 else '$'+texnum(x,3)+r' \pm '+texnum(s,2)+'$')
            lines.append(label+' & '+' & '.join(vals)+r' \\')
        lines.append(r'\bottomrule\end{tabular}')
        (ROOT/f'results/multitime_{regime}_table.tex').write_text('\n'.join(lines)+'\n')
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False,'pdf.fonttype':42})
    fig,ax=plt.subplots(1,2,figsize=(10,3.4),layout='constrained')
    for path,color,name in [([[.8,0],[0,.4]],'#196B8C','A then B'),([[0,.8],[.4,0]],'#C66235','B then A')]:
        m=OrderedMemory((1.,));coords=[m.a[0].copy()]
        for u in path:
            for _ in range(100):m.advance(u,np.log(2)/100);coords.append(m.a[0].copy())
        z=np.array(coords);ax[0].plot(z[:,0],z[:,1],color=color,label=name,lw=2)
    ax[0].scatter([.2],[.2],c='black',s=28,zorder=4)
    ax[0].annotate('same endpoint\norder = +0.04 / -0.04',(.2,.2),(.04,.34),arrowprops={'arrowstyle':'->'},fontsize=9)
    ax[0].set(xlabel='$a_1$',ylabel='$a_2$',title='A. Means coincide; ordered memory differs',xlim=(-.01,.42),ylim=(-.01,.44));ax[0].legend(frameon=False,loc='upper right',fontsize=9)
    models=['elapsed_symmetric','elapsed_quadratic','combined','elapsed_ordered']
    for off,regime,color,label in [(-.18,'same_duration','#196B8C','Original durations'),(.18,'shorter_duration','#C66235','Shorter durations')]:
        rr=[next(r for r in rows if r['model']==m and r['regime']==regime and r['task']=='ordered_history') for m in models]
        ax[1].bar(np.arange(4)+off,[float(r['mean']) for r in rr],width=.34,yerr=[float(r['sd']) for r in rr],color=color,label=label,capsize=3)
    ax[1].set_xticks(range(4),['Symmetric','Quadratic','Concatenated','Ordered'],rotation=20)
    ax[1].set(yscale='log',ylabel='Order-task test NMSE',title='B. Fresh-seed routing cohort');ax[1].legend(frameon=False,fontsize=9)
    for ext in ['pdf','png']:fig.savefig(ROOT/f'figures/multitime.{ext}',dpi=180)
    plt.close(fig)
    fig,ax=plt.subplots(figsize=(10,4.4));ax.axis('off');ax.set_xlim(0,10);ax.set_ylim(0,4.4)
    def box(x,y,w,h,text,color):
        ax.add_patch(FancyBboxPatch((x,y),w,h,boxstyle='round,pad=0.08',facecolor=color,edgecolor='#405365',linewidth=1))
        ax.text(x+w/2,y+h/2,text,ha='center',va='center',fontsize=10)
    box(.1,1.6,2.0,1.15,'Typed input\nvalue, duration,\nevent boundary','#E8EDF2')
    box(3,2.6,3.4,1.15,'Event clock\ndelay bank + graph traces\nadvance once per event','#DDEAF1')
    box(3,.6,3.4,1.15,'Elapsed-time clock\nmultiscale means + order\nexact held-interval flow','#F5E3D7')
    box(7.3,1.6,2.5,1.15,'Frozen readout heads\nsource selected\non validation data','#E0EBDF')
    for p,q in [((2.2,2.25),(2.9,3.15)),((2.2,2.05),(2.9,1.2)),((6.5,3.15),(7.2,2.3)),((6.5,1.2),(7.2,2.05))]:
        ax.annotate('',q,p,arrowprops={'arrowstyle':'->','color':'#405365','lw':1.5})
    ax.text(5,.04,'Refining an interval preserves its duration and event boundary.',ha='center',fontsize=10)
    fig.tight_layout()
    for ext in ['pdf','png']:fig.savefig(ROOT/f'figures/multitime_architecture.{ext}',dpi=180)
    plt.close(fig)

if __name__=='__main__':main()
