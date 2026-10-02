"""Independent byte-preservation checks for the optimized operational owner.

Run from the delivered project: python reproduction/check_fast_owner.py
Only synthetic inputs and temporary SQLite stores are used. Baseline reports are
never overwritten; existing verification functions are rerun in isolation.
"""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import argparse
import copy
import hashlib
import json
import math
import os
import platform
import random
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'reproduction'))
from gabriel_runtime.canonical import canonical, loads, MAX_DEPTH, MAX_INTEGER
from gabriel_runtime.engine import Store
from gabriel_runtime.fast_owner import FastStore
from gabriel_runtime import fast_owner
from gabriel_runtime.adapters import default_registry
from gabriel_runtime.stream import extended_registry
from gabriel_runtime.incremental import incremental_registry
import check_runtime as legacy
import check_incremental as incremental

SEED = 2026092607
COUNTS = Counter()
DETAILS = {}


def exact(a, b, label):
    assert canonical(a) == canonical(b), label
    COUNTS[label] += 1


def rows(store):
    """Compare all stored field values, including the unparsed JSON strings."""
    return {table: store._db.execute('SELECT * FROM ' + table + ' ORDER BY 1').fetchall()
            for table in ('meta', 'contracts', 'journal')}


def same_rows(a, b, label='database_all_rows_exact'):
    assert rows(a) == rows(b), label
    COUNTS[label] += 1


def rejected(fn, label):
    try:
        fn()
    except ValueError:
        COUNTS[label] += 1
        return
    raise AssertionError('accepted invalid input: ' + label)


def nested(n):
    x = None
    for _ in range(n):
        x = [x]
    return x


def clone_checks():
    clone = fast_owner.checked_clone
    rng = random.Random(SEED)
    values = [None, False, True, -MAX_INTEGER, MAX_INTEGER, 0, '',
              ''.join(map(chr, range(128))), {'z': [True, 1, None], 'a': {}},
              nested(MAX_DEPTH), {'\x00': ['\n', '\\', '"']}]
    def value(depth):
        if depth == 0 or rng.randrange(3) == 0:
            return rng.choice([None, True, False, rng.randint(-MAX_INTEGER, MAX_INTEGER),
                               ''.join(chr(rng.randrange(128)) for _ in range(rng.randrange(8)))])
        if rng.randrange(2):
            return [value(depth-1) for _ in range(rng.randrange(4))]
        return {str(i): value(depth-1) for i in range(rng.randrange(4))}
    values += [value(6) for _ in range(250)]
    for x in values:
        y = clone(x)
        exact(y, loads(canonical(x)), 'clone_canonical_bytes_exact')
        # Ensure every mutable node is copied, including repeated input aliases.
        def disjoint(a, b):
            if type(a) in (list, dict):
                assert a is not b
                if type(a) is list:
                    for aa, bb in zip(a, b): disjoint(aa, bb)
                else:
                    for k in a: disjoint(a[k], b[k])
        def same_order(a, b):
            if type(a) is dict:
                assert list(a) == list(b)
                for k in a: same_order(a[k], b[k])
            elif type(a) is list:
                for aa, bb in zip(a, b): same_order(aa, bb)
        same_order(y, loads(canonical(x)))
        COUNTS['clone_recursive_dictionary_order_exact'] += 1
        disjoint(x, y)
        COUNTS['clone_recursive_mutable_ownership'] += 1
    shared = {'leaf': [1, True]}
    x = {'a': shared, 'b': shared}
    y = clone(x)
    y['a']['leaf'].append(2)
    assert y['b']['leaf'] == [1, True] and x['a']['leaf'] == [1, True]
    COUNTS['clone_repeated_alias_expansion_matches_json'] += 1
    class I(int): pass
    class S(str): pass
    class L(list): pass
    class D(dict): pass
    cycle = []; cycle.append(cycle)
    invalid = [0.0, math.nan, math.inf, -math.inf, MAX_INTEGER+1, -MAX_INTEGER-1,
               'nonascii:\u00e4', b'a', (1,), {1: 'value'}, {S('s'): 1}, I(1), S('s'),
               L([1]), D(a=1), {1, 2}, nested(MAX_DEPTH+1), cycle]
    for x in invalid:
        rejected(lambda x=x: clone(x), 'clone_invalid_exact_domain')
        rejected(lambda x=x: canonical(x), 'baseline_invalid_exact_domain')
    DETAILS['canonical_boundary'] = {'maximum_depth_accepted': MAX_DEPTH,
                                     'first_depth_rejected': MAX_DEPTH+1,
                                     'integer_magnitude_limit': MAX_INTEGER,
                                     'all_ASCII_codepoints_checked': 128,
                                     'random_objects': 250}


class AdversarialAdapter:
    """Trusted test reducer with deliberate mutations and invalid return values.

    This exercises isolation, not sandboxing of malicious Python code.
    """
    def __init__(self): self.retained = []
    def fingerprint(self): return {'probe': 'fast-owner-isolation', 'version': 1}
    def initialize(self, config):
        value = {'n': 0, 'echo': {'rows': []}}
        config['nested']['rows'].append('mutated-config')
        self.retained.append(value)
        return value
    def view(self, state):
        out = copy.deepcopy(state)
        state['echo']['rows'].append('mutated-view')
        self.retained.append(out)
        return out
    def apply(self, state, op, payload, at):
        state['n'] += 1
        state['echo'] = copy.deepcopy(payload)
        payload['rows'].append('mutated-payload')
        self.retained.extend([state, state['echo']])
        if op == 'throw': raise ValueError('deliberate failure after mutation')
        if op == 'float-state': state['n'] = .5
        if op == 'bad-result': return state, {'bad': .5}
        if op == 'cycle-result':
            x = []; x.append(x); return state, x
        if op == 'tuple-result': return state, (1,)
        if op == 'bad-pair': return {'state': state}
        if op == 'depth-result': return state, nested(MAX_DEPTH)
        return state, {'count': state['n'], 'echo': state['echo']}


def probe_registry(): return {'probe/v1': AdversarialAdapter()}


def mutation_pair_checks(temp):
    ra, rb = probe_registry(), probe_registry()
    with Store.create(temp/'mut-base.sqlite', ra) as a, FastStore.create(temp/'mut-fast.sqlite', rb) as b:
        def send(ident, op, payload, at):
            cmd = legacy.command(a, ident, 'probe', op, at, payload)
            before = canonical(cmd)
            left, right = a.submit(cmd), b.submit(cmd)
            exact(left, right, 'probe_receipt_exact')
            assert canonical(cmd) == before
            same_rows(a,b)
            exact(a.view('probe'), b.view('probe'), 'probe_view_exact')
            return cmd, left, right
        send('bind', 'bind', {'adapter':'probe/v1', 'config':{'nested':{'rows':[]}}}, 0)
        cmd, left, right = send('good', 'advance', {'rows': [{'a': [True, 1]}]}, 1)
        for registry in (ra, rb):
            for item in registry['probe/v1'].retained:
                item['poison'] = ['later mutation']
        left['result']['echo']['rows'].append('caller-left')
        right['result']['echo']['rows'].append('caller-right')
        same_rows(a,b, 'adapter_and_caller_retention_cannot_mutate_database')
        exact(a.submit(cmd), b.submit(cmd), 'mutated_caller_receipt_retry_exact')
        for operation in ('throw','float-state','bad-result','cycle-result','tuple-result','bad-pair','depth-result'):
            cmd = legacy.command(a, operation, 'probe', operation, 2, {'rows':[]})
            before = rows(a), rows(b), canonical(cmd)
            for owner in (a,b):
                rejected(lambda owner=owner: owner.submit(cmd), 'invalid_reducer_atomic_rejection')
            assert before == (rows(a), rows(b), canonical(cmd))
            COUNTS['invalid_reducer_preserves_all_rows_and_caller'] += 1
        exact(a.audit(), b.audit(), 'probe_full_audit_exact')



class IdentitySensitiveAdapter:
    """Counterexample outside the value-based reducer contract."""
    def fingerprint(self): return {'probe':'scalar-identity-counterexample'}
    def initialize(self, config):
        text = ''.join(['not-an-interned-string-', 'x'*200])
        return {'a':text, 'b':text}
    def view(self, state): return {'same_object': state['a'] is state['b']}
    def apply(self, state, op, payload, at): return state,self.view(state)


def identity_boundary(temp):
    factory=lambda:{'identity/v1':IdentitySensitiveAdapter()}
    with Store.create(temp/'identity-base.sqlite',factory()) as a, FastStore.create(temp/'identity-fast.sqlite',factory()) as b:
        cmd=legacy.command(a,'bind','identity','bind',0,{'adapter':'identity/v1','config':{}})
        left,right=a.submit(cmd),b.submit(cmd)
        assert left['result']=={'same_object':False}
        assert right['result']=={'same_object':True}
        assert canonical(left)!=canonical(right)
        COUNTS['scalar_identity_nonextensional_counterexample']+=1
        DETAILS['equivalence_boundary']={
            'constructed_counterexample':True,
            'reference_bind_result':left['result'], 'optimized_bind_result':right['result'],
            'scope':'Adapter initialize/view compares Python scalar object identities with is. This is outside the required extensional JSON-value reducer assumption; equivalence is not claimed for such adapters.'}


def storage_validation_checks(temp):
    for owner in (Store,FastStore):
        for label,text in [('duplicate','{"count":0,"count":0,"echo":null}'),
                           ('whitespace','{ "count":0,"echo":null}'),
                           ('float','{"count":0.0,"echo":null}')]:
            with owner.create(temp/(owner.__name__+'-stored-'+label+'.sqlite'),legacy.registry()) as s:
                legacy.bind_probe(s)
                s._db.execute('UPDATE contracts SET state_text=?',(text,))
                before=rows(s)
                cmd=legacy.command(s,'after-tamper','probe','advance',1,{})
                rejected(lambda:s.submit(cmd),'live_storage_invalid_canonical_rejected')
                assert rows(s)==before
                rejected(lambda:s.view('probe'),'live_view_invalid_canonical_rejected')


def legacy_checks(temp):
    old_store = legacy.Store
    legacy.COUNTS.clear()
    legacy.Store = FastStore
    fixtures = {}
    try:
        for label, fn in [
            ('core', lambda:legacy.core_checks(temp)),
            ('budgets', lambda:legacy.budget_checks(temp)),
            ('finite', lambda:legacy.finite_checks(temp, fixtures)),
            ('maturity', lambda:legacy.maturity_checks(temp, fixtures)),
            ('maturity_boundaries', lambda:legacy.maturity_boundary_checks(temp, fixtures)),
            ('isolation', lambda:legacy.isolation_checks(temp)),
            ('corruption', lambda:legacy.corruption_checks(temp))]:
            fn()
            print('existing runtime checks with FastStore: ' + label + ' passed', flush=True)
        DETAILS['existing_runtime_checks'] = dict(sorted(legacy.COUNTS.items()))
    finally:
        legacy.Store = old_store
    return fixtures


def all_profile_pairs(temp, fixtures):
    source = json.loads((ROOT/'results/incremental_inputs.json').read_text())
    rates = [float.fromhex(x) for x in source['rates_hex']]
    fixture = {'source': 'results/incremental_inputs.json',
               'source_sha256': hashlib.sha256((ROOT/'results/incremental_inputs.json').read_bytes()).hexdigest(),
               'record_count': 324, 'rates_hex': source['rates_hex'][:325],
               'correction_indices':[0,60,160,315,320,322],
               'horizons':[1,5], 'profiles':['legacy','stream','incremental']}
    fixtures['stream_paths'] = fixture
    for name, factory in [('legacy',default_registry), ('stream',extended_registry),
                          ('incremental',incremental_registry)]:
        horizons = [None] if name == 'legacy' else fixture['horizons']
        for horizon in horizons:
            tag = name + '-' + str(horizon)
            paths = [temp/(tag+'-base.sqlite'), temp/(tag+'-fast.sqlite')]
            commands = []
            with Store.create(paths[0], factory()) as a, FastStore.create(paths[1], factory()) as b:
                def send(ident, op, at, payload, contract='x'):
                    cmd = legacy.command(a, ident, contract, op, at, payload)
                    before = canonical(cmd)
                    receipt = a.submit(cmd)
                    exact(receipt,b.submit(cmd),'profile_receipt_exact')
                    assert canonical(cmd) == before
                    same_rows(a,b)
                    commands.append(cmd)
                    return receipt
                if horizon is None:
                    cfg = legacy.finite_config('fast-owner',2)
                    send('bind','bind',0,{'adapter':'finite-observation/v1','config':cfg})
                    for j in range(2):
                        send('obs%d'%j,'observe',0,legacy.finite_payload(j,str(j),'src%d'%j,0))
                    cfg, steps = legacy.maturity_fixture()
                    send('bind-risk','bind',0,{'adapter':'maturity-risk/v1','config':cfg},'risk')
                    for j,(op,at,p) in enumerate(steps): send('risk%d'%j,op,at,p,'risk')
                else:
                    cfg = incremental.config(horizon,'fast-owner-synthetic')
                    send('bind','bind',0,{'adapter':'stream-risk/v1','config':cfg})
                    for j in range(fixture['record_count']):
                        p = incremental.payload(j,rates[j]); send('r%d'%j,'record',p['received_at'],p)
                    for j,s in enumerate(fixture['correction_indices']):
                        p = incremental.payload(s,rates[s]*(257/256),1,5000+j)
                        send('c%d'%j,'record',p['received_at'],p)
                    p = incremental.payload(324,rates[324],receipt=5010)
                    send('r324','record',5010,p)
                for contract in (['x','risk'] if horizon is None else ['x']):
                    exact(a.view(contract),b.view(contract),'profile_terminal_view_exact')
                previous = rows(a),rows(b)
                exact(a.submit(commands[-1]),b.submit(commands[-1]),'profile_retry_receipt_exact')
                assert previous == (rows(a),rows(b))
                exact(a.audit(), b.audit(), 'profile_full_semantic_audit_exact')
                exact(a.export(),b.export(),'profile_export_direct_bytes_exact')
                head, events = a.head,a.budget['events']
            # Deliberately exchange implementations on each other's DB file.
            with FastStore.open(paths[0],factory(),head,events) as a, Store.open(paths[1],factory(),head,events) as b:
                same_rows(a,b,'opposite_owner_open_all_rows_exact')
                exact(a.export(),b.export(),'opposite_owner_open_export_exact')
                DETAILS.setdefault('profile_paths',[]).append({'profile':name,'horizon':horizon,
                                                             'events':events,'head':head})
            print('differential profile ' + tag + ': passed',flush=True)


def mixed_owner_checks(temp):
    path = temp/'mixed.sqlite'
    with Store.create(path,legacy.registry()) as seed:
        legacy.bind_probe(seed)
        head = seed.head
    with Store.open(path,legacy.registry()) as a, FastStore.open(path,legacy.registry()) as b:
        cmd = legacy.command(a,'base-write','probe','advance',1,{'v':1})
        a.submit(cmd)
        stale = dict(cmd,id='stale')
        rejected(lambda:b.submit(stale),'mixed_owner_stale_frontier_rejected')
        exact(a.submit(cmd),b.submit(cmd),'cross_owner_duplicate_exact')
        cmd = legacy.command(b,'fast-write','probe','advance',2,{'v':2})
        b.submit(cmd)
        exact(a.view('probe'),b.view('probe'),'mixed_owner_reads_latest_committed_state')
        head = a.head
    # Actual overlapping calls: independent SQLite connections/threads share CAS.
    barrier = threading.Barrier(2)
    def writer(cls, ident):
        with cls.open(path,legacy.registry()) as s:
            cmd = {'id':ident,'contract':'probe','op':'advance','at':3,
                   'expected_head':head,'payload':{'thread':ident}}
            barrier.wait(timeout=10)
            try:
                s.submit(cmd); return ('accepted',ident)
            except ValueError as exc:
                assert 'stale' in str(exc); return ('stale',ident)
    with ThreadPoolExecutor(max_workers=2) as pool:
        fa,fb = pool.submit(writer,Store,'base-thread'),pool.submit(writer,FastStore,'fast-thread')
        outcomes = [fa.result(timeout=40),fb.result(timeout=40)]
    assert sorted(x[0] for x in outcomes) == ['accepted','stale']
    COUNTS['concurrent_cross_owner_CAS_single_winner'] += 1
    with FastStore.open(path,legacy.registry()) as s:
        assert s.view('probe')['count'] == 3
        assert s.audit()['events'] == 4
    DETAILS['concurrent_connections'] = outcomes


def crash_child(args):
    with FastStore.open(Path(args.database),legacy.registry()) as store:
        def crash(stage):
            if stage == args.stage: os._exit(77 if stage == 'before_commit' else 78)
        store._test_hook = crash
        store.submit(json.loads(Path(args.command_file).read_text()))
    raise AssertionError('unreached crash hook')


def crash_checks(temp):
    result_rows=[]
    for stage in ('before_commit','after_commit'):
        path=temp/('fast-crash-'+stage+'.sqlite')
        with FastStore.create(path,legacy.registry()) as s:
            legacy.bind_probe(s)
            cmd=legacy.command(s,'crash','probe','advance',1,{'stage':stage})
            before=rows(s)
        commandfile=temp/('fast-crash-'+stage+'.json'); commandfile.write_text(canonical(cmd))
        run=subprocess.run([sys.executable,str(Path(__file__).resolve()),'--crash-child',
                            '--database',str(path),'--stage',stage,'--command-file',str(commandfile)],
                           capture_output=True,text=True,timeout=45)
        assert run.returncode == (77 if stage=='before_commit' else 78),run.stderr
        # Open via the baseline to avoid self-confirming recovery checks.
        with Store.open(path,legacy.registry()) as s:
            if stage=='before_commit':
                assert rows(s)==before; COUNTS['fast_process_exit_before_commit_rollback']+=1
            else:
                assert s.view('probe')['count']==1
                assert s.budget['events']==2
                COUNTS['fast_process_exit_after_commit_persists']+=1
            receipt=s.submit(cmd); saved=rows(s)
            exact(receipt,s.submit(cmd),'fast_crash_retry_exact')
            assert saved==rows(s) and s.view('probe')['count']==1
            COUNTS['fast_crash_retry_single_effect']+=1
            s.audit()
            result_rows.append({'stage':stage,'os_exit_code':run.returncode,
                                'events_after_retry':s.budget['events']})
    return result_rows


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--crash-child',action='store_true')
    parser.add_argument('--database');parser.add_argument('--stage');parser.add_argument('--command-file')
    args=parser.parse_args()
    if args.crash_child: crash_child(args);return
    started=time.perf_counter()
    files=[ROOT/'gabriel_runtime'/name for name in
           ['canonical.py','engine.py','adapters.py','stream.py','incremental.py','fast_owner.py']]
    files += [ROOT/'reproduction'/name for name in
              ['check_runtime.py','check_incremental.py','finite_observation.py',
               'decision_regions.py','sequential_contract.py','maturity_ledger.py',
               'ecb_risk.py','replay_adaptive_maturity.py','aggregate_risk.py','severity_risk.py']]
    files.append(Path(__file__).resolve())
    source_hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}
    fixture={'schema':'gabriel.fast-owner.synthetic-inputs.v1','seed':SEED,'synthetic':True}
    clone_checks(); print('clone domain and alias checks: passed',flush=True)
    with tempfile.TemporaryDirectory(prefix='gabriel-fast-owner-checks-') as d:
        temp=Path(d)
        mutation_pair_checks(temp); print('mutating adapter differential checks: passed',flush=True)
        identity_boundary(temp)
        storage_validation_checks(temp)
        isolated=temp/'legacy';isolated.mkdir()
        fixture['existing_runtime_inputs']=legacy_checks(isolated)
        all_profile_pairs(temp,fixture)
        mixed_owner_checks(temp)
        crashes=crash_checks(temp)
    inputs=ROOT/'results/fast_owner_inputs.json';inputs.write_text(json.dumps(fixture,indent=2)+'\n')
    after_hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}
    assert after_hashes==source_hashes, 'tested source changed during execution'
    report={'schema':'gabriel.fast-owner.executed-checks.v1','status':'passed','seed':SEED,
            'elapsed_seconds':round(time.perf_counter()-started,3),'python':sys.version,
            'sqlite':sqlite3.sqlite_version,'platform':platform.platform(),
            'equivalence_scope':'Extensional deterministic reducers: observable behavior depends on exact JSON values and canonical key order, not immutable Python scalar object identity. The intentionally failing identity-sensitive example records the necessity of this assumption.',
            'comparison':'Direct canonical JSON byte strings and every stored SQL field; no tolerance or hash-only equality.',
            'counts':dict(sorted(COUNTS.items())),'details':DETAILS,'process_crashes':crashes,
            'input_sha256':hashlib.sha256(inputs.read_bytes()).hexdigest(),
            'source_sha256':source_hashes, 'tested_sources_unchanged_during_run':True,
            'not_tested':['Physical power failure or storage corruption beyond synthetic SQL tampering',
                          'Sandboxing or containment of malicious executable adapters',
                          'Concurrent mutation by callers during an in-progress submit',
                          'Predictive accuracy or production throughput']}
    (ROOT/'results/fast_owner_checks.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'status':'passed','elapsed_seconds':report['elapsed_seconds'],'counts':report['counts']},indent=2))

if __name__=='__main__':main()
