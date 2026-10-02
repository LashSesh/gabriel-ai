"""Publication table and vector figure from executed, saved exact results."""
from pathlib import Path
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
s=json.loads((ROOT/'results/robust_orientation_summary.json').read_text())
labels={'ring_minimax':'Two rings + minimax','ring_ec2':r'Two rings + EC$^2$',
        'ring_fixed':'Two rings + lexical','lexical_robust_prefix':'Lexical robust scan',
        'full_robust':'Complete robust read'}
lines=[r'\begin{table}[!htbp]\centering',
       r'\caption{Exact one-error orientation decisions on 102400 latent-record/error cases per policy. All policies have zero wrong or unresolved outputs within the declared model. Means use the uniform finite catalogue, not an estimated deployment error distribution.}',
       r'\label{tab:robustorientation}',r'\begin{tabular}{lrrr}\toprule',
       r'Policy & Clean report & Maximum & Catalogue mean \\\midrule']
for name,m in s['policies'].items():
    lines.append(labels[name]+f" & {m['clean_queries'][0]} & {m['maximum_queries']} & {m['mean_queries']:.2f}"+r' \\')
lines.extend([r'\bottomrule\end{tabular}',r'\end{table}'])
(ROOT/'results/robust_orientation_table.tex').write_text('\n'.join(lines)+'\n')
plt.rcParams.update({'font.size':9,'axes.spines.top':False,'axes.spines.right':False,
                     'pdf.fonttype':42,'ps.fonttype':42})
fig,axs=plt.subplots(1,2,figsize=(7.0,2.8),gridspec_kw={'width_ratios':[1.4,1]},layout='constrained')
styles=[('ring_minimax','#17647b','-'),('ring_fixed','#ad672a','--'),
        ('lexical_robust_prefix','#7b6b99','-.'),('full_robust','#666666',':')]
x=np.arange(11,25)
for name,color,ls in styles:
    m=s['policies'][name]
    cdf=[sum(v for k,v in m['query_histogram'].items() if int(k)<=q)/m['cases'] for q in x]
    label='Two rings + minimax / EC²' if name=='ring_minimax' else labels[name]
    axs[0].step(x,cdf,where='post',label=label,color=color,linestyle=ls,linewidth=1.8)
axs[0].set(xlim=(11,24.5),ylim=(0,1.04),xlabel='Distinct queried reports',ylabel='Fraction decided',
           title='A  Query cost by policy')
axs[0].set_xticks([12,16,17,20,24]);axs[0].legend(loc='lower right',fontsize=7,frameon=True,framealpha=1,edgecolor='white')
axs[1].bar([0,1,2],[1,2,3],color=['#96b7c3','#4c879c','#17647b'],width=.58)
axs[1].axhline(3,color='#ad672a',ls='--',lw=1)
axs[1].set_xticks([0,1,2],['One ring\n6 reports','Both rings\n12 reports','All edges\n24 reports'])
axs[1].set(ylabel='Opposite-target separation',ylim=(0,3.75),title='B  Fixed-set separation')
axs[1].text(1,3.12,'Uniform one-error threshold',ha='center',fontsize=7)
axs[1].set_yticks([0,1,2,3])
fig.savefig(ROOT/'figures/robust_orientation.pdf')
fig.savefig(ROOT/'figures/robust_orientation.png',dpi=180)
plt.close(fig)
print('Saved robust orientation table and PDF/PNG figure.')
