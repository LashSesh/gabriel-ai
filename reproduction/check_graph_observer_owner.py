#!/usr/bin/env python3
"""Execute bounded graph-observer integration, replay and durable-command checks.

Synthetic model observations only. Timings include fresh native process startup,
full Engine reconstruction, source/executable hashes, JSON, and SQLite EXTRA
commit. Store creation, bind, append_batch and audit are outside query timings.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gabriel_runtime.canonical import canonical, loads
from gabriel_runtime.engine import Store
from gabriel_runtime.graph_observer import (ADAPTER, BACKENDS, CAPS, SCHEMA,
    GraphObserverAdapter, bits, number, demo_query, _source_hashes)


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True)+'\n', encoding='ascii')


def command(owner, operation, payload, key):
    return {'id':key, 'contract':'graph', 'op':operation, 'at':owner.budget['events'],
            'expected_head':owner.head, 'payload':payload}


def submit(owner, operation, payload, key):
    return owner.submit(command(owner, operation, payload, key))


def setup(path, adapter, backend, caps=None, n=13):
    owner = Store.create(path, {ADAPTER:adapter})
    submit(owner, 'bind', {'adapter':ADAPTER, 'config':{'backend':backend, **(caps or CAPS)}}, 'bind')
    submit(owner, 'append_batch', {'entities':list(range(n))}, 'batch')
    return owner


def expect_rollback(owner, operation, payload, key):
    before = canonical(owner.export()), owner.head, owner.budget
    try:
        submit(owner, operation, payload, key)
    except ValueError:
        pass
    else:
        raise AssertionError('request unexpectedly accepted: '+key)
    assert before == (canonical(owner.export()), owner.head, owner.budget), key


def functional_checks(directory, executable, expected_sha256):
    adapter = GraphObserverAdapter(executable, expected_sha256)
    reports = []
    answers = {}
    for backend in BACKENDS:
        path = directory / (backend+'.sqlite')
        with setup(path, adapter, backend) as owner:
            q = demo_query()
            cmd = command(owner, 'query', q, 'query')
            receipt = owner.submit(cmd)
            answers[backend] = receipt['result']['issue']['native_result']
            old_records = owner.export()['records']
            before_budget = owner.budget
            assert owner.submit(cmd) == receipt
            assert owner.budget == before_budget
            submit(owner, 'append_batch', {'entities':[0,1,2]}, 'later-batch')
            assert owner.export()['records'][:len(old_records)] == old_records
            invalid = []
            p=copy.deepcopy(q);p['targets']=[0,0];invalid.append(('duplicate-target',p))
            p=copy.deepcopy(q);p['targets']=[63];invalid.append(('unknown-target',p))
            p=copy.deepcopy(q);p['source'][0]['entity']=63;invalid.append(('unknown-source',p))
            p=copy.deepcopy(q);p['source'][0]['entity']=1;invalid.append(('duplicate-source',p))
            p=copy.deepcopy(q);p['times_bits']=['7ff0000000000000'];invalid.append(('infinity',p))
            p=copy.deepcopy(q);p['times_bits']=['7ff8000000000000'];invalid.append(('nan',p))
            p=copy.deepcopy(q);p['times_bits']=['3FF0000000000000'];invalid.append(('uppercase',p))
            p=copy.deepcopy(q);p['extra']=0;invalid.append(('unknown-field',p))
            p=copy.deepcopy(q);p['times_bits']=[bits(0)]*257;invalid.append(('query-cap',p))
            p=copy.deepcopy(q)
            for entry in p['source']:entry['re_bits']=entry['im_bits']=bits(0)
            invalid.append(('zero-source',p))
            for name, payload in invalid:expect_rollback(owner,'query',payload,name)
            expect_rollback(owner,'append_batch',{'entities':[0,0]},'duplicate-batch')
            expect_rollback(owner,'append_batch',{'entities':[]},'empty-batch')
            expect_rollback(owner,'unknown',{},'unknown-operation')
            anchor={'head':owner.head,'events':owner.budget['events']}
            audit=owner.audit(expected_head=anchor['head'],expected_events=anchor['events'])
            write(directory/(backend+'.journal.json'),owner.export())
        # The same executable bytes can move without changing semantic identity.
        relocated=directory/(backend+'-relocated-executable')
        shutil.copy2(executable,relocated)
        relocated_adapter=GraphObserverAdapter(relocated,expected_sha256)
        assert adapter.fingerprint()==relocated_adapter.fingerprint()
        with Store.open(path,{ADAPTER:relocated_adapter},
                        expected_head=anchor['head'],expected_events=anchor['events']) as reopened:
            assert reopened.head==anchor['head']
        # A modified copied executable is rejected before any subprocess runs.
        with relocated.open('ab') as stream:stream.write(b'\x00')
        try:relocated_adapter.fingerprint()
        except ValueError:pass
        else:raise AssertionError('changed binary was accepted')
        relocated.unlink()
        reports.append({'backend':backend,'audit':audit,'rollback_cases':len(invalid)+3,
                        'identical_retry':True,'published_prefix_preserved':True,
                        'same_binary_relocation_replayed':True,'modified_binary_rejected':True})
    reference=answers['spectral_full']
    max_error=0.0
    for backend, answer in answers.items():
        assert answer['snapshot']['identity']==reference['snapshot']['identity']
        for a,b in zip(answer['query_results'][0]['values'],reference['query_results'][0]['values']):
            error=abs(number(a['mass_bits'])-number(b['mass_bits']))
            max_error=max(max_error,error)
            assert error<=2e-10
            assert a['decision']==b['decision']
    soft={'max_nodes':2,'max_batches':1,'max_queries':1}
    with setup(directory/'soft-caps.sqlite',adapter,'auto_region',soft,n=2) as owner:
        submit(owner,'query',demo_query(2,1),'first')
        expect_rollback(owner,'query',demo_query(2,1),'total-query-cap')
        expect_rollback(owner,'append_batch',{'entities':[0,1]},'batch-cap')
        expect_rollback(owner,'append_batch',{'entities':[2]},'node-cap')
        owner.audit()
    source_key=next(iter(adapter.sources)); original=adapter.sources[source_key]
    adapter.sources[source_key]='0'*64
    try:adapter.fingerprint()
    except ValueError:pass
    else:raise AssertionError('source mismatch accepted')
    adapter.sources[source_key]=original
    native_job={'schema':SCHEMA,'backend':'auto_region','batches':[list(range(13))],
                'queries':[demo_query()]}
    native_bad=[]
    def bad(name,job):native_bad.append((name,canonical(job).encode('ascii')))
    p=copy.deepcopy(native_job);p['extra']=0;bad('unknown-root-field',p)
    p=copy.deepcopy(native_job);p['batches']=[[0,0]];bad('duplicate-entity',p)
    p=copy.deepcopy(native_job);p['batches']=[[0]]*129;bad('batch-hard-cap',p)
    p=copy.deepcopy(native_job);p['queries']=[demo_query(13,257)];bad('time-hard-cap',p)
    p=copy.deepcopy(native_job);p['queries'][0]['source'][0]['re_bits']='7ff8000000000000';bad('nonfinite',p)
    p=copy.deepcopy(native_job);p['queries'][0]['targets']=[63];bad('unknown-target',p)
    raw=canonical(native_job)
    native_bad.append(('duplicate-key',raw.replace('{','{"backend":"auto_region",',1).encode('ascii')))
    native_bad.append(('oversize',b' '*(4*1024*1024+1)))
    for name,raw in native_bad:
        p=subprocess.run([str(executable)],input=raw,capture_output=True,timeout=30)
        assert p.returncode!=0,(name,p.stdout)
    return {'status':'passed','backends':reports,'soft_cap_rollbacks':3,
            'native_direct_rejections':[name for name,_ in native_bad],
            'source_mismatch_rejected':True,'max_cross_backend_mass_error':max_error,
            'answers':answers}


def durable_timings(directory, executable, expected_sha256, repeats):
    adapter=GraphObserverAdapter(executable,expected_sha256)
    records=[]
    for repeat in range(repeats):
        for n in [13,64]:
            for count in [1,16,256]:
                order=list(BACKENDS)
                order=order[repeat%3:]+order[:repeat%3]
                responses={}
                for backend in order:
                    path=directory/f'durable-{repeat}-{n}-{count}-{backend}.sqlite'
                    with setup(path,adapter,backend,n=n) as owner:
                        payload=demo_query(n,count)
                        cmd=command(owner,'query',payload,'timed-query')
                        start=time.perf_counter_ns()
                        receipt=owner.submit(cmd)
                        elapsed=time.perf_counter_ns()-start
                        response=receipt['result']['issue']['native_result']
                        responses[backend]=response
                        records.append({'repeat':repeat,'nodes':n,'times':count,'backend':backend,
                                        'query_command_ns':elapsed,'response':response,
                                        'journal_head':owner.head,'command':cmd})
                    path.unlink()
                ref=responses['spectral_full']['query_results'][0]['values']
                for backend in BACKENDS:
                    for a,b in zip(responses[backend]['query_results'][0]['values'],ref):
                        assert abs(number(a['mass_bits'])-number(b['mass_bits']))<=2e-10
                        assert a['decision']==b['decision']
    summaries=[]
    for n in [13,64]:
        for count in [1,16,256]:
            selected=[r for r in records if r['nodes']==n and r['times']==count]
            baseline={r['repeat']:r['query_command_ns'] for r in selected if r['backend']=='spectral_full'}
            for backend in BACKENDS:
                values=[r['query_command_ns'] for r in selected if r['backend']==backend]
                ratios=[baseline[r['repeat']]/r['query_command_ns'] for r in selected if r['backend']==backend]
                summaries.append({'nodes':n,'times':count,'backend':backend,'repeats':repeats,
                                  'median_command_ns':statistics.median(values),
                                  'median_paired_speedup':statistics.median(ratios),
                                  'min_paired_speedup':min(ratios),'max_paired_speedup':max(ratios)})
    return {'scope':'one durable existing-Store.submit query command; includes fresh subprocess, full Engine replay, hashes, JSON and SQLite EXTRA commit',
            'excluded':'Store setup, bind, append_batch and later audit',
            'kind':'synthetic-clique; no predictive-accuracy experiment',
            'clock':'time.perf_counter_ns', 'repeats':repeats,
            'records':records,'summary':summaries}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable',required=True,type=Path)
    parser.add_argument('--sha256',required=True)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--repeats',type=int,default=7)
    parser.add_argument('--skip-timings',action='store_true')
    args=parser.parse_args()
    if not 1<=args.repeats<=31:raise ValueError('repeats must be in [1,31]')
    args.output.mkdir(parents=True,exist_ok=False)
    executable=args.executable.resolve(strict=True)
    before=_source_hashes()
    result={'functional':functional_checks(args.output,executable,args.sha256),
            'executable_sha256':args.sha256,'source_hashes_before':before,
            'python_version':sys.version,'command':sys.argv,
            'runner_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    if not args.skip_timings:result['timings']=durable_timings(args.output,executable,args.sha256,args.repeats)
    result['source_hashes_after']=_source_hashes()
    assert before==result['source_hashes_after']
    write(args.output/'results.json',result)
    print(json.dumps({'status':'passed','output':str(args.output),
                      'max_cross_backend_mass_error':result['functional']['max_cross_backend_mass_error'],
                      'durable_timing_cases':len(result.get('timings',{}).get('summary',[]))}))

if __name__=='__main__':main()
