"""Generate the manuscript replay table and evidence cross-check from archived JSON.

Run after benchmark_replay_owner.py --summarize in the full research project.
The compact runtime omits the independent native certificate required here.
"""
from pathlib import Path
import json
import hashlib
import zipfile

ROOT=Path(__file__).resolve().parents[1]
data=json.loads((ROOT/'results/replay_benchmark.json').read_text())
assert data['timed_opens']==66
checks=json.loads((ROOT/'results/replay_owner_checks.json').read_text())
cli=json.loads((ROOT/'results/replay_owner_cli_checks.json').read_text())
cert=json.loads((ROOT/'native_pse/benchmark-results/indexed/results/verification_report.json').read_text())
assert all(x['status']=='passed' for x in [checks,cli,cert])
assert cli['subprocess_commands']==103
for case in data['cases'].values():
    assert case['status']=='passed'
    for name,digest in case['source_sha256'].items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest,name
lines=[r'\begin{table}[H]\centering\small',
    r'\caption{Complete fresh-owner replay on synthetic histories. Fast and replay columns give median opening seconds; the ratio is the median of paired fast/replay times, with its observed range. Register size denotes width; stream size denotes observations. Database preparation and output comparisons are excluded.}\label{tab:replayopens}',
    r'\begin{tabular}{llrrrr}\toprule',
    r'Case & Size & Fast (s) & Replay (s) & Ratio & Range \\ \midrule']
longest=[]
for case_name,case in data['cases'].items():
    for row in case['rows']:
        label='Registers' if case_name=='registers' else '$h='+case_name[1:]+'$'
        size=row.get('width',row.get('source_length'))
        a,b=[row['median_seconds'][k] for k in ['fast','replay']]
        lo,hi=row['paired_ratio_range'];ratio=row['median_paired_ratio']
        lines.append(f'{label} & {size} & {a:.3f} & {b:.3f} & {ratio:.3f} & {lo:.3f}--{hi:.3f} '+r'\\')
        if size==800:
            longest.append({'horizon':row['horizon'],'fast_seconds':a,'replay_seconds':b,'time_reduction_percent':100*(1-b/a),'paired_ratio':ratio,'database_bytes':row['database_bytes']})
lines+=[r'\bottomrule\end{tabular}\end{table}']
assert len(longest)==2
for row in longest:
    lines.append(r'For horizon $h=%d$ at 800 observations, the median opening time falls from %.2f to %.2f seconds (%.1f\%%); the unchanged database occupies %.2f MB (decimal).'%(row['horizon'],row['fast_seconds'],row['replay_seconds'],row['time_reduction_percent'],row['database_bytes']/1e6))
(ROOT/'results/replay_benchmark_table.tex').write_text('\n'.join(lines)+'\n')
review={'status':'passed','timed_opens':66,'longest_histories':longest,
    'runtime_checks':{'corrupted_databases_rejected':len(checks['corruption_cases']),'cli_commands':cli['subprocess_commands'],'counts':checks['counts']},
    'finite_index':cert['independent_verification'],
    'invalid_index_certificates_rejected':len(cert['invalid_certificates']),
    'regenerated_index_bytes_identical':cert['regenerated_files_byte_identical'],
    'rust_integration':'Reconstructed optional feature; not compiled or run in recovered environment. Default path remains packed.',
    'lost_previous_raw_results':'Earlier unarchived timing summaries are not used as reproduced numerical evidence.',
    'source_preservation':json.loads((ROOT/'audit/replay_source_preservation.json').read_text())}
(ROOT/'audit/replay_execution_review.json').write_text(json.dumps(review,indent=2)+'\n')
print(json.dumps({'timed_opens':66,'longest_histories':longest},indent=2))
