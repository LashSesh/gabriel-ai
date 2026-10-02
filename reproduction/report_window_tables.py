"""Render the two manuscript tables from independently checked sealed results."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
a=json.loads((ROOT/'results/window_reachability_study/verified_timing_audit.json').read_text())
o=json.loads((ROOT/'results/reachability_owner_verification.json').read_text())
assert not a['primary_criterion_met'] and o['passed']
lines=[r'\begin{table}[!htbp]',r'\centering',r'\caption{Complete certificate-call comparison against validated adaptive subdivision. Ratios are adaptive/analytic; values above one favor analytic evaluation. Size-specific rows are descriptive; the frozen gate uses the overall row. Process spans are observed ranges.}',r'\label{tab:windowtimes}',r'\begin{tabular}{lrrr}\toprule',r'Nodes & Cases & Median ratio & Process span\\\midrule']
for key,label in [(f'nodes/{n}',str(n)) for n in (7,13,32,64)]+[('overall','All')]:
 d=a['descriptive_groups'][key];v=d['worker_median_adaptive_over_analytic']
 lines.append(f"{label} & {d['distinct_cases']} & {d['median_worker_ratio']:.4f} & [{min(v):.4f}, {max(v):.4f}]\\\\")
lines += [r'\bottomrule\end{tabular}',r'\end{table}']
(ROOT/'results/window_reachability_tables.tex').write_text('\n'.join(lines)+'\n')
lines=[r'\begin{table}[!htbp]',r'\centering\small',r'\caption{Absolute production-owner costs for four-window commands, three fresh workers per request. Setup, native execution, identity checks and storage are included in complete cost. Complete and replay costs are medians; certificate share is the median within-task fraction; no competing-owner speed ratio is measured.}',r'\label{tab:windowowner}',r'\begin{tabular}{rrrrr}\toprule',r'Nodes & Region & Complete (ms) & Certificate share (\%) & Replay (ms)\\\midrule']
for d in o['summary']:
 lines.append(f"{d['nodes']} & {d['region']} & {d['complete_ns']['median']/1e6:.2f} & {100*d['median_certificate_calls_fraction']:.2f} & {d['median_cold_replay_ns']/1e6:.2f}\\\\")
lines += [r'\bottomrule\end{tabular}',r'\end{table}']
(ROOT/'results/reachability_owner_tables.tex').write_text('\n'.join(lines)+'\n')
print('two evidence-bound tables generated')
