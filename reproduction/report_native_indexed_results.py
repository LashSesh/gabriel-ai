"""Regenerate manuscript tables from the executed native comparison; no timings."""
from pathlib import Path
import hashlib
import importlib.util
import json
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / 'native_pse/benchmark-results/indexed_engine'
OUT = ROOT / 'results'


def main():
    d = json.loads((BENCH / 'executed/results.json').read_text())
    protocol = json.loads((BENCH / 'protocol.json').read_text())
    spec = importlib.util.spec_from_file_location('native_reproduction', BENCH / 'reproduce.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    summary = module.summarize(protocol, d['engine_runs'], d['first_runs'], d['micro_run'])
    if summary != d['summary']:
        raise RuntimeError('Recomputed summary differs from archived raw observations')
    if not d['source_unchanged'] or not all(d[k]['bytes_identical'] for k in ['engine_golden','micro_golden']):
        raise RuntimeError('Source or exact-output gate not satisfied')
    before = json.loads((BENCH / 'executed/source_hashes_before.json').read_text())
    after = json.loads((BENCH / 'executed/source_hashes_after.json').read_text())
    if before != after:
        raise RuntimeError('Historical sources changed during measurement')
    current_matches = module.source_hashes() == after
    snapshot = ROOT / 'audit/native_indexed_measured_sources.zip'
    # Later implementations have their own measurements. Preserve this earlier
    # experiment by checking all its original source bytes, never by relabelling
    # old timings as a measurement of the modified tree.
    with zipfile.ZipFile(snapshot) as archive:
        if archive.testzip() is not None:
            raise RuntimeError('Corrupt historical measured-source archive')
        for name, digest in after.items():
            if hashlib.sha256(archive.read('native_pse/' + name)).hexdigest() != digest:
                raise RuntimeError('Historical source snapshot mismatch: ' + name)
    cert = json.loads((ROOT / 'native_pse/benchmark-results/indexed/results/verification_report.json').read_text())
    for name, digest in cert['data_sha256'].items():
        actual = hashlib.sha256((ROOT / 'native_pse/crates/pse-metatron/data' / name).read_bytes()).hexdigest()
        if actual != digest:
            raise RuntimeError('Compiled table inputs differ from certified bytes: ' + name)

    def cell(row):
        return r'$%.3f\,[%.3f,\,%.3f]$' % tuple(row[k] for k in
                    ['median_paired_ratio','min_paired_ratio','max_paired_ratio'])

    def row(group, comparison, n, workload=None):
        return next(x for x in summary[group] if x['comparison']==comparison
                    and x.get('entities',x.get('n'))==n
                    and (workload is None or x['workload']==workload))

    lines = [r'\begin{table}[H]\centering\small',
             r'\caption{Complete native engine comparisons. Entries are median paired ratios with observed ranges across five pairs. Ratios above one favour indexed and memoized execution, respectively. Warm rows use observation throughput; first-call rows use inverse elapsed time for the first macrostep in a fresh process.}',
             r'\label{tab:indexedengine}',r'\begin{tabular}{llrr}\toprule',
             r'Interval & Sources & Indexed / packed & Memoized / indexed \\\midrule']
    for group,label in [('engine','Warm'),('first_macrostep','First call')]:
        for n in [3,5,7,8]:
            lines.append('%s & %d & %s & %s \\\\' % (label,n,
                cell(row(group,'indexed_vs_packed',n)),cell(row(group,'memoized_vs_indexed',n))))
        if group=='engine': lines.append(r'\midrule')
    lines.extend([r'\bottomrule\end{tabular}',r'\end{table}',''])
    lines.extend([r'\begin{table}[H]\centering\small',
             r'\caption{Complete-signature kernel comparisons in one executable. Entries are median paired ratios with observed ranges across seven pairs of 512 calls. Hit rates cover timed memoized calls only, after warmup. Each changing corpus is reused across passes.}',
             r'\label{tab:indexedmicro}',r'\begin{tabular}{llrrr}\toprule',
             r'$n$ & Inputs & Indexed / packed & Memoized / indexed & Hits (\%) \\\midrule'])
    hits = []
    for n in [3,5,7]:
        for w in ['fixed','changing','collision']:
            if n==3 and w=='collision': continue
            rows = [v for v in d['micro_run']['measurements'] if v['comparison']=='memoized_vs_indexed'
                    and v['variant']=='memoized' and v['n']==n and v['workload']==w]
            calls = sum(v['calls'] for v in rows)
            counts = {k:sum(v['memo_cache_after'][k]-v['memo_cache_before'][k] for v in rows)
                      for k in ['hits','misses','bypasses','evictions']}
            if counts['hits']+counts['misses']+counts['bypasses'] != calls:
                raise RuntimeError('Cache accounting disagrees with calls')
            hit_rate = 100*counts['hits']/calls
            hits.append({'n':n,'workload':w,'calls':calls,'hit_percent':hit_rate,**counts})
            lines.append('%d & %s & %s & %s & %.2f \\\\' % (n,w.capitalize(),
                cell(row('micro','indexed_vs_packed',n,w)),cell(row('micro','memoized_vs_indexed',n,w)),hit_rate))
    lines.extend([r'\bottomrule\end{tabular}',r'\end{table}',''])
    (OUT / 'native_indexed_tables.tex').write_text('\n'.join(lines))
    evidence = {'summary_recomputed_from_raw':True,'native_source_guard_matches_current_files':current_matches,
                'historical_measured_sources_verified_in_snapshot':True,
                'historical_measured_source_archive':'audit/native_indexed_measured_sources.zip',
                'compiled_input_tables_match_offline_certificate':True,'cache_accounting':hits,
                'engine_timed_ticks':sum(v['ticks'] for r in d['engine_runs'] for v in r['raw']['measurements']),
                'first_macrosteps':len(d['first_runs']),
                'micro_timed_calls':sum(v['calls'] for v in d['micro_run']['measurements'])}
    (OUT / 'native_indexed_reporting_checks.json').write_text(json.dumps(evidence,indent=2)+'\n')
    print(json.dumps(evidence,indent=2))


if __name__ == '__main__':
    main()
