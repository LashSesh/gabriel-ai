"""Executed differential checks for complete expected-byte semantic replay.

Run from the project: python reproduction/check_replay_owner.py
Synthetic SQLite mutation fixtures are regenerated, never trusted checkpoints.
"""
from pathlib import Path
import hashlib
import json
import shutil
import sqlite3
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'reproduction')]
from gabriel_runtime.canonical import canonical
from gabriel_runtime.engine import Store
from gabriel_runtime.fast_owner import FastStore
from gabriel_runtime.replay_owner import ReplayStore
import check_fast_owner as prior
import check_runtime as legacy

OWNERS = [Store, FastStore, ReplayStore]


def hashes():
    paths = list((ROOT/'gabriel_runtime').glob('*.py')) + [Path(__file__),
        ROOT/'reproduction/check_fast_owner.py', ROOT/'reproduction/check_runtime.py']
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}


def mutation_checks(temp):
    good = temp/'valid.sqlite'
    with Store.create(good, legacy.registry()) as s:
        legacy.bind_probe(s)
        for i in range(1, 9):
            s.submit(legacy.command(s, 'event-'+str(i), 'probe', 'advance', i, {'i': i}))
        expected_audit, expected_export = canonical(s.audit()), canonical(s.export())
    for owner in OWNERS:
        with owner.open(good, legacy.registry()) as s:
            assert canonical(s.audit()) == expected_audit
            assert canonical(s.export()) == expected_export
    cases = []
    with sqlite3.connect(good) as db:
        for field in ['record_text', 'receipt_text']:
            text = db.execute('SELECT '+field+' FROM journal WHERE sequence=2').fetchone()[0]
            value = json.loads(text)
            mutations = {
                'leading-space': ' '+text, 'trailing-space': text+' ',
                'pretty': json.dumps(value, indent=2),
                'reverse-keys': json.dumps(dict(reversed(list(value.items()))), separators=(',',':')),
                'duplicate-key': '{"sequence":2,'+text[1:],
                'float-sequence': text.replace('"sequence":2', '"sequence":2.0'),
                'wrong-sequence': canonical(value | {'sequence': 99}),
                'escaped-key': text.replace('"sequence"', '"\\u0073equence"'),
                'truncated': text[:-1], 'array': '[]', 'null': 'null',
                'boolean': 'true', 'number': '2', 'nan': 'NaN', 'infinity': 'Infinity',
                'non-ascii': '"é"', 'deep': '['*66+'0'+']'*66,
                'sql-blob': text.encode('ascii')}
            for label, mutated in mutations.items():
                cases.append((field+'/'+label, 'UPDATE journal SET '+field+'=? WHERE sequence=2', (mutated,)))
    for field in ['state_text', 'config_text']:
        for label, text in [('syntax','{'), ('null','null'), ('empty','{}'), ('blob',b'{}')]:
            cases.append((field+'/'+label, 'UPDATE contracts SET '+field+'=?', (text,)))
    cases.extend([
        ('missing-record','DELETE FROM journal WHERE sequence=2',()),
        ('missing-binding','DELETE FROM contracts',()),
        ('unknown-adapter','UPDATE contracts SET adapter=?',('missing/v1',)),
        ('wrong-command-id','UPDATE journal SET command_id=? WHERE sequence=2',('changed',)),
        ('wrong-contract','UPDATE journal SET contract_id=? WHERE sequence=2',('changed',)),
        ('wrong-head','UPDATE meta SET head=?',('0'*64,)),
        ('wrong-count','UPDATE meta SET event_count=event_count+1',()),
        ('wrong-bytes','UPDATE meta SET byte_count=byte_count+1',()),
        ('wrong-clock','UPDATE meta SET last_at=last_at+1',())])
    outcomes=[]
    for i, (label, sql, args) in enumerate(cases):
        p=temp/('mutated-'+str(i)+'.sqlite'); shutil.copy2(good,p)
        with sqlite3.connect(p) as db: db.execute(sql,args)
        rejected=[]
        for owner in OWNERS:
            try:
                opened=owner.open(p,legacy.registry())
            except (ValueError, TypeError):
                rejected.append(owner.__name__)
            else:
                opened.close(); raise AssertionError('accepted '+label+' using '+owner.__name__)
        outcomes.append({'case':label,'rejected_by':rejected})
    assert len(outcomes)==53
    return outcomes


class CountingAdapter:
    def __init__(self): self.calls=0
    def fingerprint(self): return {'adapter':'replay-depth-probe/v1'}
    def initialize(self, config): return {'nested':prior.nested(config['depth']), 'n':0}
    def apply(self,state,op,payload,at):
        self.calls+=1; state['n']+=1
        return state, {'n':state['n']}
    def view(self,state): return {'n':state['n']}


def depth_checks(temp):
    rows=[]
    for depth in [0,60,61,62,63]:
        p=temp/('depth-'+str(depth)+'.sqlite')
        with Store.create(p,{'count/v1':CountingAdapter()}) as s:
            s.submit(legacy.command(s,'bind','x','bind',0,{'adapter':'count/v1','config':{'depth':depth}}))
            for i in range(1,5): s.submit(legacy.command(s,str(i),'x','next',i,{}))
        row={'depth':depth,'owners':{}}
        for owner in OWNERS:
            adapter=CountingAdapter()
            try: opened=owner.open(p,{'count/v1':adapter})
            except ValueError:
                row['owners'][owner.__name__]={'accepted':False,'open_apply_calls':adapter.calls}
            else:
                assert adapter.calls==4
                opened.audit(); assert adapter.calls==8
                row['owners'][owner.__name__]={'accepted':True,'open_apply_calls':4,'after_audit_apply_calls':8}
                opened.close()
        assert all(x['accepted']==(depth<=61) for x in row['owners'].values())
        rows.append(row)
    return rows


def main():
    started=time.perf_counter(); before=hashes()
    fixtures={'schema':'gabriel.replay-owner.synthetic-inputs.v1','synthetic':True}
    prior.FastStore=ReplayStore
    prior.COUNTS.clear(); prior.DETAILS.clear()
    with tempfile.TemporaryDirectory(prefix='gabriel-replay-checks-') as d:
        temp=Path(d)
        mutations=mutation_checks(temp); depths=depth_checks(temp)
        print('53 corruption cases and aggregate-depth boundaries: passed',flush=True)
        prior.mutation_pair_checks(temp)
        prior.storage_validation_checks(temp)
        isolated=temp/'legacy'; isolated.mkdir()
        fixtures['existing_runtime_inputs']=prior.legacy_checks(isolated)
        prior.all_profile_pairs(temp,fixtures)
        prior.mixed_owner_checks(temp)
    assert before==hashes(), 'tested source changed'
    inputs=ROOT/'results/replay_owner_inputs.json';inputs.write_text(json.dumps(fixtures,indent=2)+'\n')
    report={'schema':'gabriel.replay-owner.executed-checks.v1','status':'passed',
        'elapsed_seconds':time.perf_counter()-started,'python':sys.version,
        'corruption_cases':mutations,'aggregate_depth_and_full_replay':depths,
        'counts':dict(prior.COUNTS),'details':prior.DETAILS,'source_sha256':before,
        'input_sha256':hashlib.sha256(inputs.read_bytes()).hexdigest(),
        'scope':'Deterministic value-based adapters; exact canonical values, all stored SQL rows, acceptance on synthetic corruptions. Every transition is recomputed.',
        'not_tested':['New physical-crash trials: live submit inherits FastStore unchanged.',
                      'Malicious executable adapters, resource exhaustion, predictive superiority.']}
    (ROOT/'results/replay_owner_checks.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'status':'passed','elapsed_seconds':report['elapsed_seconds'],'counts':report['counts']}))


if __name__=='__main__': main()
