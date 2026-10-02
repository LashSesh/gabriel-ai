"""Tables and publication figures from saved outputs; no refitting."""
from pathlib import Path
import csv,json
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from benchmark_phase import NAMES

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results';FIG=ROOT/'figures'

def table(header,rows,caption,label,alignment):
    lines=[r'\begin{table}[!htbp]',r'\centering\small',r'\begin{tabular}{'+alignment+'}',r'\toprule',' & '.join(header)+r' \\',r'\midrule']
    lines += [' & '.join(map(str,row))+r' \\' for row in rows]
    lines += [r'\bottomrule',r'\end{tabular}',r'\caption{'+caption+'}',r'\label{'+label+'}',r'\end{table}']
    return '\n'.join(lines)+'\n'

def main():
    rows=list(csv.DictReader((OUT/'phase_classification.csv').open()));D={(r['dataset'],r['model']):r for r in rows}
    data=[]
    for name in NAMES:
        data.append([name,D[name,'trace_observer']['cases']]+[D[name,m]['correct'] for m in ('trace_observer','real_bank','phase_bank','real_plus_trace','phase_plus_trace')])
    (OUT/'phase_main_table.tex').write_text(table(['Dataset','$n$','Trace','Real','Phase','Real+trace','Phase+trace'],data,'Correct test decisions. Standalone banks have 16 real state coordinates per input channel; the two hybrid heads add the same number of features to the unchanged trace observer. All families are reported, without test-based selection.','tab:phase_main','lrrrrrr'))
    data=[]
    for name in NAMES:
        data.append([name]+[D[name,f'{k}_{b}']['correct'] for b in (3,5,7) for k in ('real','phase')])
    (OUT/'phase_budget_table.tex').write_text(table(['Dataset','Real 3','Phase 3','Real 5','Phase 5','Real 7','Phase 7'],data,'State-budget ablation: correct test decisions of standalone banks. Budgets count real memory coordinates per input channel, not the dimension of the full Gabriel system. Five is neither uniformly best nor a demonstrated universal optimum.','tab:phase_budget','lrrrrrr'))
    stops=list(csv.DictReader((OUT/'phase_stopping.csv').open()));data=[]
    for name in NAMES:
        row=[name]
        for mode in ('real_bank','phase_bank'):
            for mask in ('random_half','middle_half'):
                vals=[float(r['fraction']) for r in stops if r['dataset']==name and r['model']==mode and r['mask']==mask and r['policy']=='coefficient']
                row.append(f'{100*np.mean(vals):.2f}')
        data.append(row)
    (OUT/'phase_retrieval_table.tex').write_text(table(['Dataset','Real random','Real middle','Phase random','Phase middle'],data,'Mean percentage of missing scalars retrieved by the coefficient policy for the standalone 16-coordinate banks. Every stop is validated over its continuous input box. These heads have their own predictive accuracy (Table~\\ref{tab:phase_main}); their counts cannot be substituted for the nonlinear observer or hybrid.','tab:phase_retrieval','lrrrr'))
    plt.rcParams.update({'font.size':8.5,'axes.spines.top':False,'axes.spines.right':False,'pdf.fonttype':42})
    fig=plt.figure(figsize=(7.0,3.0));ax=fig.add_subplot(121,projection='3d')
    age=np.linspace(0,3,220);angle=np.linspace(0,2*np.pi,40);A,Q=np.meshgrid(age,angle);radius=.04*np.exp(A)
    ax.plot_surface(A,radius*np.cos(Q),radius*np.sin(Q),color='#3677a4',alpha=.2,linewidth=0)
    ax.plot(age,.04*np.exp(age)*np.cos(-4*age),.04*np.exp(age)*np.sin(-4*age),color='#c76028',lw=1.8)
    ax.set(xlabel='Backward age a',ylabel='Error 1',zlabel='Error 2',title='Inverse-state error: known input')
    ax.view_init(elev=19,azim=-64);ax.set_box_aspect((1.5,1,1));ax.tick_params(labelsize=7,pad=1)
    ax=fig.add_subplot(122)
    for name,col in zip(NAMES,['#3677a4','#cb6945','#548753','#8561a4']):
        counts=np.array([int(D[name,f'phase_{b}']['correct']) for b in (3,5,7)])
        ax.plot([3,5,7],counts/int(D[name,'trace_observer']['cases'])*100,'o-',label=name,color=col)
    ax.set(xlabel='Real coordinates per channel',ylabel='Test accuracy (%)',title='Phase-bank state budget',xticks=[3,5,7],ylim=(0,100));ax.grid(alpha=.15);ax.legend(fontsize=7.5,loc='lower left')
    fig.subplots_adjust(left=.02,right=.98,top=.84,bottom=.20,wspace=.40)
    for ext in ('pdf','png'):fig.savefig(FIG/f'phase_geometry.{ext}',dpi=180,bbox_inches='tight')
    plt.close(fig)
    summary=dict(classification={name:{m:int(D[name,m]['correct']) for m in ('trace_observer','real_bank','phase_bank','real_plus_trace','phase_plus_trace','phase_3','phase_5','phase_7')} for name in NAMES},status='Generated from saved benchmark; no fit or family selection')
    (OUT/'phase_summary.json').write_text(json.dumps(summary,indent=2))

if __name__=='__main__':main()
