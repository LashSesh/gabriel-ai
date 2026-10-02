"""Check sealed owner evidence, certificate identity and independently aggregate costs."""
from __future__ import annotations
import argparse,hashlib,json,statistics,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def digest(x):
    return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('ascii')).hexdigest()
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--archive',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    evaluation=json.loads((ROOT/'results/window_reachability_study/evaluation_final.json').read_text())
    expected={r['case_id']:r['result'] for r in evaluation['outputs'] if r['method']=='analytic'}
    inputs=json.loads((ROOT/'results/window_reachability_study/inputs.json').read_text())
    with zipfile.ZipFile(args.archive) as z:
        assert z.testzip() is None
        manifest=json.loads(z.read('manifest.json'))
        assert set(z.namelist())==set(manifest)|{'manifest.json'}
        for path,meta in manifest.items():
            raw=z.read(path);assert len(raw)==meta['bytes'] and hashlib.sha256(raw).hexdigest()==meta['sha256']
        summary=json.loads(z.read('summary.json'));protocol=json.loads(z.read('protocol.json'))
        assert hashlib.sha256((ROOT/'reproduction/benchmark_reachability_owner.py').read_bytes()).hexdigest()==protocol['collector_sha256']
        workers=[json.loads(z.read(f'worker_{i}/worker.json')) for i in range(3)]
        assert len({w['pid'] for w in workers})==3
        records=[];answers=0
        for i,w in enumerate(workers):
            assert w['cohort_digest']==inputs['cohort_digest'] and len(w['records'])==8 and len(w['cold_replays'])==8
            for path,sha in w['source_sha256'].items():
                assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==sha
            assert len({r['task_id'] for r in w['records']})==8
            assert all(a['semantic_replay'] and a['external_anchors_checked'] and a['closed_database_unchanged'] for a in w['cold_replays'])
            for r in w['records']:
                assert r['commands_sha256']==digest(r['commands']) and r['receipt_sha256']==digest(r['receipt'])
                assert sum(r['phase_ns'].values())==r['elapsed_ns']>0
                assert all(t>=0 for t in r['phase_ns'].values())
                assert sum(r['certificate_calls_ns'])==r['certificate_calls_total_ns']<=r['phase_ns']['observe']
                assert r['certificate_calls_fraction']==r['certificate_calls_total_ns']/r['elapsed_ns']
                assert r['receipt']['head']==r['owner_head'] and r['receipt']['sequence']==r['owner_events']==2
                raw=z.read(f"worker_{i}/{r['database_filename']}")
                assert len(raw)==r['database_bytes'] and hashlib.sha256(raw).hexdigest()==r['database_sha256']
                issue=r['receipt']['result']['issue']
                assert issue['native_snapshot']==inputs['snapshots'][str(r['nodes'])]['response']
                assert len(issue['certificates'])==len(r['case_ids'])==4
                assert issue['certificates']==[expected[c] for c in r['case_ids']]
                assert len(r['commands'])==2 and r['commands'][0]['op']=='bind' and r['commands'][1]['op']=='observe'
                assert digest(r['commands'][1]['payload'])==r['input_sha256']
                answers+=4;records.append(r)
        rows=[]
        for row in summary['summary']:
            selected=[r for r in records if r['task_id']==row['task_id']]
            replays=[r for w in workers for r in w['cold_replays'] if r['task_id']==row['task_id']]
            assert len(selected)==len(replays)==3
            expected_ns=dict(median=statistics.median(r['elapsed_ns'] for r in selected),minimum=min(r['elapsed_ns'] for r in selected),maximum=max(r['elapsed_ns'] for r in selected))
            assert row['complete_ns']==expected_ns
            assert row['median_certificate_calls_ns']==statistics.median(r['certificate_calls_total_ns'] for r in selected)
            assert row['median_certificate_calls_fraction']==statistics.median(r['certificate_calls_fraction'] for r in selected)
            assert row['median_cold_replay_ns']==statistics.median(r['elapsed_ns'] for r in replays)
            rows.append(row)
    result=dict(schema='gabriel.owner-window-independent-check.v1',passed=True,records=len(records),certificates=answers,
                sealed_files=len(manifest),source_files_per_worker=len(workers[0]['source_sha256']),
                database_byte_checks=24,semantic_replay_claims_crosschecked=24,
                archive_sha256=hashlib.sha256(args.archive.read_bytes()).hexdigest(),
                verifier_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                evaluation_sha256=hashlib.sha256((ROOT/'results/window_reachability_study/evaluation_final.json').read_bytes()).hexdigest(),
                summary=rows,scope='Independent artifact hashes, input/output binding, all certificate bytes and timing aggregation; semantic replay separately executed by the functional/owner checks.')
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ('passed','records','certificates','database_byte_checks')}))
if __name__=='__main__':main()
