#!/usr/bin/env python3
"""Produce the complete-task table and figure from archived matched raw records."""
from pathlib import Path
import argparse, collections, hashlib, json, statistics, zipfile
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=Path(__file__).resolve().parents[1]
def main():
 p=argparse.ArgumentParser();p.add_argument('--archive',type=Path,default=ROOT/'audit/strict_batch_owner_measurements.zip');a=p.parse_args()
 with zipfile.ZipFile(a.archive) as z:
  workers=[json.loads(z.read(f'worker_{i}/worker.json')) for i in range(3)]
 records=[r for w in workers for r in w['records']]; replays=[r for w in workers for r in w['revalidation_replays']]
 groups={}
 for r in records: groups.setdefault((r['worker'],r['task_id']),{})[r['variant']]=r
 def rows(cohort):
  out=[]
  for n in sorted({r['nodes'] for r in records if r['cohort']==cohort}):
   for k in sorted({r['windows'] for r in records if r['cohort']==cohort}):
    pairs=[v for v in groups.values() if v['legacy_scalar']['cohort']==cohort and v['legacy_scalar']['nodes']==n and v['legacy_scalar']['windows']==k]
    if not pairs: continue
    times={v:statistics.median([g[v]['elapsed_ns'] for g in pairs])/1e6 for v in ('legacy_scalar','strict_batch')}
    ratios=[g['legacy_scalar']['elapsed_ns']/g['strict_batch']['elapsed_ns'] for g in pairs]
    replay_map={(r['worker'],r['task_id'],r['variant']):r['elapsed_ns'] for r in replays}
    replay_ratios=[replay_map[(g['legacy_scalar']['worker'],g['legacy_scalar']['task_id'],'legacy_scalar')]/replay_map[(g['legacy_scalar']['worker'],g['legacy_scalar']['task_id'],'strict_batch')] for g in pairs]
    out.append(dict(nodes=n,windows=k,pairs=len(pairs),median_complete_ms=times,median_paired_speedup=statistics.median(ratios),ratio_min=min(ratios),ratio_max=max(ratios),median_replay_speedup=statistics.median(replay_ratios)))
  return out
 primary,controls=rows('primary'),rows('controls')
 statuses=collections.Counter(c['status'] for r in records for c in r['receipt']['result']['issue']['certificates'])
 report={'archive_sha256':hashlib.sha256(a.archive.read_bytes()).hexdigest(),'primary_cells':primary,'control_cells':controls,'timed_certificate_status_counts':dict(statuses)}
 (ROOT/'results/epoch_owner_study/cell_summary.json').write_text(json.dumps(report,indent=2)+'\n')
 table=[r'\begin{table}[htbp]\centering\small',r'\caption{Complete native--Store tasks with scalar and shared model preparation. Each row pools two fixed sources across three workers. Times are profile medians; ratios are medians of paired times, not ratios of medians. Replay is separately timed full semantic reopening. Values above one favor batching.}\label{tab:batchowner}',r'\begin{tabular}{rr rrrr}\toprule',r'$n$ & Windows & Scalar (ms) & Batch (ms) & Task ratio & Replay ratio\\\midrule']
 for x in primary:
  table.append(f"{x['nodes']} & {x['windows']} & {x['median_complete_ms']['legacy_scalar']:.2f} & {x['median_complete_ms']['strict_batch']:.2f} & {x['median_paired_speedup']:.3f} & {x['median_replay_speedup']:.3f} \\\\")
 table+=['\\bottomrule\\end{tabular}','\\end{table}']
 (ROOT/'results/epoch_owner_tables.tex').write_text('\n'.join(table)+'\n')
 plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
 fig,ax=plt.subplots(figsize=(7.0,3.9),layout='constrained')
 colors=['#68788a','#2a7e8e','#3856a6','#a33f35']
 for n,color in zip([7,13,32,64],colors):
  cells=[r for r in primary if r['nodes']==n]
  ax.plot(range(4),[r['median_paired_speedup'] for r in cells],marker='o',label=f'{n} nodes',color=color)
 ax.axhline(1,color='0.3',lw=1,ls='--');ax.axhline(1.1,color='0.65',lw=.8,ls=':')
 ax.set_xticks(range(4),['1','4','16','32']);ax.set_xlabel('Distinct windows in one atomic observation');ax.set_ylabel('Median paired complete-task ratio\nscalar time / batch time')
 ax.set_ylim(.9,max(x['median_paired_speedup'] for x in primary)+.07);ax.legend(frameon=False,ncols=2,loc='upper left');ax.grid(axis='y',alpha=.18)
 fig.savefig(ROOT/'figures/epoch_owner_speedup.pdf');fig.savefig(ROOT/'figures/epoch_owner_speedup.png',dpi=170);plt.close(fig)
 print(json.dumps(report,indent=2))
if __name__=='__main__': main()
