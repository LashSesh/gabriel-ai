"""Regenerate every manuscript figure/table directly from saved experiment outputs."""
from pathlib import Path
import csv,json
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch,FancyArrowPatch
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results';FIG=ROOT/'figures';FIG.mkdir(exist_ok=True)
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':9,'axes.spines.top':False,'axes.spines.right':False,'savefig.bbox':'tight'})
def table(name):return list(csv.DictReader((OUT/name).open()))
def save(fig,name):
 fig.savefig(FIG/(name+'.pdf'));fig.savefig(FIG/(name+'.png'),dpi=180);plt.close(fig)
def main():
 fig,ax=plt.subplots(figsize=(9.1,4.3));ax.set(xlim=(0,10),ylim=(0,5));ax.axis('off')
 def box(x,y,w,h,txt,color='#edf3f8'):
  ax.add_patch(FancyBboxPatch((x,y),w,h,boxstyle='round,pad=.10',fc=color,ec='#244f6d',lw=1.1));ax.text(x+w/2,y+h/2,txt,ha='center',va='center',fontsize=9)
 def arrow(a,b,label=None):
  ax.add_patch(FancyArrowPatch(a,b,arrowstyle='-|>',mutation_scale=11,color='#244f6d'))
  if label:ax.text((a[0]+b[0])/2,(a[1]+b[1])/2+.14,label,ha='center',fontsize=8)
 box(.1,2,1.3,.9,'Input stream\n$u_t$')
 box(2,3.35,2.35,1.05,'Delay cells\nexact recent samples')
 box(2,1.5,2.35,1.1,'Recurrent cells\nbounded activity $x_t$')
 box(4.95,1.5,2.45,1.1,'Association cells\nlocal traces $c_t^{(r)}$')
 box(4.95,3.35,2.45,1.05,'Pair features\nquadratic delay terms')
 box(8,2.25,1.7,1.35,'Readout\nmeasured task\nperformance')
 arrow((1.4,2.5),(2,3.8));arrow((1.4,2.3),(2,2.05));arrow((4.35,3.87),(4.95,3.87));arrow((4.35,2.05),(4.95,2.05));arrow((7.4,3.8),(8,3.2));arrow((7.4,2.15),(8,2.65))
 ax.annotate('',xy=(3.15,1.42),xytext=(6.15,1.42),arrowprops=dict(arrowstyle='->',connectionstyle='arc3,rad=-.38',color='#b66e24'))
 ax.text(4.65,.62,'Optional plastic feedback: jointly certified',ha='center',color='#97551a',fontsize=9)
 ax.text(4.9,.1,'Implemented hybrid: quadratic delay features + traces from a fixed recurrent observer',ha='center',fontsize=8)
 save(fig,'architecture')
 rows=table('summary.csv');models=['fixed','budget','trace_only','adaptive_x','adaptive_joint'];tasks=['delay6','lag_product','smoothed_covariance']
 labels=['Fixed','Budget','Trace only','Adaptive x','Adaptive joint']
 fig,axs=plt.subplots(1,3,figsize=(9.5,3.4),sharey=True)
 for ax,task,title in zip(axs,tasks,['Delayed sample','Lagged product','Smoothed covariance']):
  rs=[next(r for r in rows if r['model']==m and r['task']==task) for m in models]
  ax.bar(np.arange(5),[float(r['mean']) for r in rs],yerr=[float(r['sd']) for r in rs],color=['#8ba9bd','#afc0cc','#387e8e','#d9a464','#bd7430'],capsize=2)
  ax.set_title(title);ax.set_xticks(range(5),labels,rotation=45,ha='right');ax.axhline(1,color='.6',lw=.7,ls=':');ax.set_ylim(0,1.12)
 axs[0].set_ylabel('Test NMSE (mean ± sample SD, 10 seeds)');fig.tight_layout();save(fig,'ablations')
 fig,axs=plt.subplots(1,2,figsize=(9.3,3.3))
 for name,color,label in [('synchronization.csv','#244f6d','Two initial states'),('recovery.csv','#b66e24','Transient state reset')]:
  rr=table(name);t=np.array([int(r['t']) for r in rr]);d=np.array([float(r['distance']) for r in rr]);b=np.array([float(r['bound']) for r in rr])
  axs[0].semilogy(t,np.maximum(d,1e-16),color=color,label=label);axs[0].semilogy(t,b,'--',color=color,lw=1)
 axs[0].set(xlabel='Synchronous updates',ylabel='Weighted state distance',ylim=(1e-16,3));axs[0].legend(fontsize=8);axs[0].set_title('Measured distances; dashed analytical bounds')
 rr=table('synchronization.csv');t=[int(r['t']) for r in rr]
 axs[1].plot(t,[float(r['certified_fraction']) for r in rr],color='#244f6d',label='Certified channel support')
 axs[1].plot(t,[float(r['support_disagreement']) for r in rr],color='#b66e24',label='Observed support disagreement')
 axs[1].set(xlabel='Synchronous updates',ylabel='Fraction of trace channels',ylim=(-.03,1.03));axs[1].legend(fontsize=8);axs[1].set_title('Support labels require a threshold margin')
 fig.tight_layout();save(fig,'guarantees')
 p=np.load(OUT/'benchmark_seed_00.npz');fig,axs=plt.subplots(2,1,figsize=(9.2,4.8),sharex=True)
 t=np.arange(4100,4600)
 axs[0].plot(t,p['targets'][t,2],color='black',label='Target',lw=1.3)
 axs[0].plot(t,p['fixed_predictions'][t,2],color='#b66e24',label='Fixed activity readout',lw=.85)
 axs[0].plot(t,p['trace_only_predictions'][t,2],color='#27798b',label='Trace readout',lw=.9)
 axs[0].set_ylabel('Smoothed covariance');axs[0].legend(fontsize=8,ncol=3)
 axs[1].plot(t,p['active_fraction'][t],color='#b66e24',label='Active plastic channels')
 axs[1].plot(t,p['total_active_fraction'][t],color='#244f6d',label='Nonzero total weights')
 axs[1].axhline(2/6,color='.5',ls=':',lw=.8,label='Backbone fraction')
 axs[1].set(xlabel='Time index (test segment, seed 0)',ylabel='Fraction');axs[1].legend(fontsize=8,ncol=3)
 fig.tight_layout();save(fig,'behavior')
 # Formatted numerical tables are generated, never transcribed manually.
 names={'input':'Current input','fir12':'Linear delay bank','fixed':'Fixed activity','budget':'Static budget control','trace_only':'Trace observer','adaptive_x':'Plastic activity','adaptive_joint':'Plastic joint','quadratic_delay':'Quadratic delay bank','hybrid_memory':'Hybrid memory'}
 for src,dst,order in [('summary.csv','core_table.tex',['input','fir12','fixed','budget','trace_only','adaptive_x','adaptive_joint']),('extension_summary.csv','extension_table.tex',['adaptive_joint','trace_only','quadratic_delay','hybrid_memory'])]:
  rs=table(src);lines=[]
  for m in order:
   vals=[]
   for task in tasks:
    rr=next(z for z in rs if z['model']==m and z['task']==task)
    mean,sd=float(rr['mean']),float(rr['sd'])
    vals.append('$<10^{-14}$' if mean<1e-14 else f'${mean:.4f}\\pm{sd:.4f}$')
   lines.append(names[m]+' & '+' & '.join(vals)+r' \\')
  (OUT/dst).write_text(r'\begin{tabular}{lccc}\toprule'+'\n'+r'Model & Delay & Lagged product & Covariance \\\midrule'+'\n'+'\n'.join(lines)+'\n'+r'\bottomrule\end{tabular}'+'\n')
if __name__=='__main__':main()
