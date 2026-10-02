"""Descriptive post-measurement aggregation; does not alter frozen acceptance.

This audit script was written after all five certificate timing workers finished.
Per-size and branch summaries are descriptive analyses, not replacement gates.
"""
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import statistics


ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT/'results/window_reachability_study'


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    inputs = read(STUDY/'inputs.json')
    evaluation = read(STUDY/'evaluation_final.json')
    summary = read(STUDY/'summary.json')
    verification_path = ROOT/'results/window_reachability_verification.json'
    verification = read(verification_path)
    assert verification['passed'] is True
    assert verification['inputs_sha256'] == sha(STUDY/'inputs.json')
    assert verification['evaluation_sha256'] == sha(STUDY/'evaluation_final.json')
    assert summary['cohort_digest'] == inputs['cohort_digest'] == evaluation['cohort_digest']
    cases = {c['case_id']:c for c in inputs['cases'] if c['cohort']=='primary'}
    results = {(r['case_id'],r['method']):r['result'] for r in evaluation['outputs']}
    groups = defaultdict(list)
    sources = {}
    workers = []
    for path in sorted((STUDY/'timings').glob('worker_*.json')):
        if '.command.' in path.name:
            continue
        data = read(path)
        workers.append(data['worker'])
        sources[path.name] = sha(path)
        assert data['source_sha256'] == evaluation['source_sha256']
        pairs = defaultdict(dict)
        for row in data['rows']:
            pairs[row['repeat'],row['case_id']][row['method']] = row
        for (_,case_id),pair in pairs.items():
            assert set(pair) == {'analytic','adaptive','uniform'}
            assert len({r['status'] for r in pair.values()}) == 1
            analytic = results[case_id,'analytic']
            phase = bool(analytic['resources']['phase_evaluations'])
            point = analytic['evidence']['method']
            categories = ['overall',f"nodes/{cases[case_id]['snapshot_key']}",
                          'branch/phase_needed' if phase else 'branch/endpoint_or_algebraic',
                          'evidence/'+point,'decision/'+analytic['status']]
            sample = dict(worker=data['worker'],case_id=case_id,
                          analytic_ns=pair['analytic']['elapsed_ns'],
                          adaptive_ns=pair['adaptive']['elapsed_ns'],
                          uniform_ns=pair['uniform']['elapsed_ns'])
            for category in categories:
                groups[category].append(sample)
    assert workers == list(range(5))
    descriptions = {}
    for category,rows in groups.items():
        worker_ratios = []
        for worker in workers:
            sample = [r for r in rows if r['worker']==worker]
            worker_ratios.append(statistics.median(r['adaptive_ns']/r['analytic_ns'] for r in sample))
        totals = {m:sum(r[m+'_ns'] for r in rows) for m in ('analytic','adaptive','uniform')}
        descriptions[category] = dict(distinct_cases=len({r['case_id'] for r in rows}),
                                      matched_repeated_calls=len(rows),
                                      worker_median_adaptive_over_analytic=worker_ratios,
                                      median_worker_ratio=statistics.median(worker_ratios),
                                      sum_call_ns=totals,
                                      ratio_of_summed_adaptive_over_analytic=totals['adaptive']/totals['analytic'],
                                      ratio_of_summed_uniform_over_analytic=totals['uniform']/totals['analytic'])
    gates = dict(summary['gates'])
    gates['independent_zero_false_certificates'] = True
    overall = bool(gates['resolution'] and gates['matched_task_timing']
                   and gates['independent_zero_false_certificates'])
    output = dict(schema='gabriel.window-postmeasurement-audit.v1',
                  analysis_timing='written after the five frozen timing workers; groups are descriptive only',
                  protocol_sha256=summary['protocol_sha256'],cohort_digest=inputs['cohort_digest'],
                  source_sha256=evaluation['source_sha256'],raw_worker_sha256=sources,
                  verification_sha256=sha(verification_path),
                  verification_counts={k:verification[k] for k in ('certificates','decisive_certificates','unknown_certificates')},
                  gates=gates,primary_criterion_met=overall,
                  primary_outcome='met' if overall else 'unmet',
                  descriptive_groups=descriptions,
                  interpretive_limits=[
                      'Every primary method returns the same 180 reachable and 76 excluded decisions; no primary coverage advantage.',
                      'Per-size and branch analyses are post-measurement descriptions and cannot replace the registered overall gate.',
                      'Ratios below one mean the analytic implementation is slower than adaptive subdivision.',
                      'Sums aggregate measured certificate-call intervals, excluding Engine production, worker startup, serialization and Store ownership.',
                      'The shared exact model preparation and different certificate work are included; point counts alone do not establish total work.',
                      'This synthetic graph-model verification result does not establish external predictive usefulness or overall system superiority.'])
    target = STUDY/'verified_timing_audit.json'
    target.write_text(json.dumps(output,indent=2)+'\n')
    print(json.dumps({'output':str(target),'primary_outcome':output['primary_outcome'],
                      'overall':descriptions['overall'],'per_nodes':{k:v for k,v in descriptions.items() if k.startswith('nodes/')},
                      'branches':{k:v for k,v in descriptions.items() if k.startswith('branch/')}},indent=2))


if __name__ == '__main__':
    main()
