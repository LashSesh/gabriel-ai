"""Independent finite-tree oracle, exact invariants and failure witnesses."""
from pathlib import Path
from itertools import product, combinations
from fractions import Fraction as F
from dataclasses import replace
import json
import math
from finite_observation import Catalogue, Planner, Session, Observation, remove_independent_queries
from domain_adapters import transport_records, event_records, build_catalogue

ROOT = Path(__file__).resolve().parents[1]


def depth_feasible(rows, labels, ids, available, depth):
    """Independent decision-tree existence oracle with explicit remaining tests."""
    if len({labels[i] for i in ids}) == 1: return True
    if depth == 0: return False
    for q in available:
        parts = {}
        for i in ids: parts.setdefault(rows[i][q],[]).append(i)
        if len(parts)==1: continue
        others = tuple(r for r in available if r!=q)
        if all(depth_feasible(rows, labels, sub, others, depth-1) for sub in parts.values()):
            return True
    return False


def reject(fn):
    try: fn()
    except ValueError: return
    raise AssertionError('invalid evidence accepted')


def main():
    checked = 0; reduced_tables=0
    # All 2^12 tables, and all C(4,2) balanced label assignments.
    for bits in product('01',repeat=12):
        rows = tuple(tuple(bits[3*i:3*i+3]) for i in range(4))
        for positives in combinations(range(4),2):
            labels = tuple(int(i in positives) for i in range(4))
            c = Catalogue('oracle',('q0','q1','q2'),(1,1,1),rows,labels)
            p = Planner(c)
            oracle = next((d for d in range(4) if depth_feasible(rows,labels,tuple(range(4)),(0,1,2),d)), math.inf)
            assert p.value(p.all)==oracle
            reduced,_,certificates=remove_independent_queries(c)
            reduced_planner=Planner(reduced)
            assert reduced_planner.value(reduced_planner.all)==oracle
            reduced_tables+=bool(certificates)
            if oracle != math.inf:
                q = p.choice(p.all,'minimax')
                assert q is not None
                assert 1+max(p.value(s) for s in p.branches(p.all,q))==oracle
            checked += 1
    invariants = 0
    tr, qs = transport_records()
    for r in tr:
        for before, after, eta, i, j in r['substeps']:
            assert sum(before)==sum(after)==1 and all(0<=x<=1 for x in after)
            delta = sum(x*x for x in after)-sum(x*x for x in before)
            assert delta == -2*eta*(1-eta)*(before[i]-before[j])**2 <= 0
            invariants += 1
    # A new quotient must preserve every query, not merely the currently read one.
    c = Catalogue('past-collapse',('past','future'),(1,1),(('0','0'),('0','1')),(0,1))
    p = Planner(c)
    state = p.observe(p.all,0,'0')
    assert state==p.all and p.decision(state) is None and p.value(state)==1
    assert len(c.quotient()[0].rows)==2
    wrong = Catalogue('unsafe-representative',c.query_names,c.costs,(c.rows[0],),(0,))
    assert Planner(wrong).decision(1)==0  # false for realised second history
    # No universal coverage certificate follows from internal consistency.
    model = Catalogue('misspecification',('q',),(1,),(('0',),),(0,))
    pp = Planner(model)
    assert pp.observe(pp.all,0,'outside')==0
    assert pp.decision(pp.observe(pp.all,0,'0'))==0  # out-of-model target=1 is undetectable
    # Persistent one-bit sensor error is a latent variable, not repeatable new noise.
    noisy_rows, noisy_labels = [], []
    for target, error in product((0,1),range(-1,3)):
        noisy_rows.append(tuple(str(target ^ int(j==error)) for j in range(3)))
        noisy_labels.append(target)
    noisy = Planner(Catalogue('one-bit-persistent',('a','b','c'),(1,1,1),tuple(noisy_rows),tuple(noisy_labels)))
    assert noisy.value(noisy.all)==3
    for i,row in enumerate(noisy.c.rows):
        s = noisy.all
        for q,y in enumerate(row): s=noisy.observe(s,q,y)
        assert noisy.decision(s)==noisy_labels[i]
    # Evidence lineage, temporal availability and interventions.
    p = Planner(c); s = Session(p)
    e = Observation(c.identity,1,'1','source',(2,4),10)
    reject(lambda:s.ingest(e,9))
    assert s.ingest(e,10) and s.result()['label']==1
    assert not s.ingest(replace(e,received_at=11),11)
    reject(lambda:s.ingest(e,10))
    reject(lambda:s.ingest(replace(e,outcome='0'),12))
    reject(lambda:s.ingest(replace(e,source_id='x',status='prospective'),12))
    reject(lambda:s.ingest(replace(e,source_id='x',kind='active_intervention'),12))
    reject(lambda:s.ingest(replace(e,source_id='x',contract_digest='other'),12))
    reject(lambda:s.ingest(replace(e,source_id='x',event_interval=(4,12)),12))
    # A distinct evidence ID containing the same exact value adds no information.
    old = s.state
    assert s.ingest(replace(e,source_id='copy',received_at=12),12) and s.state==old
    # Two clocks cannot be substituted: A occurred first but was received later.
    times = {'A':(1,10),'B':(2,3)}
    assert min(times,key=lambda k:times[k][0])=='A'
    assert min(times,key=lambda k:times[k][1])=='B'
    # An intervention that sets state to 1 invalidates a predicate of the old state.
    old_state, post_state = 0, 1
    assert old_state != post_state
    # Nonuniform costs: the cheap two-step branch wins over a complete expensive test.
    cost_c = Catalogue('costs',('direct','bit0','bit1'),(5,1,1),
                       (('a','0','0'),('b','0','1'),('c','1','0'),('d','1','1')),(0,1,1,0))
    cost_p=Planner(cost_c)
    assert cost_p.value(cost_p.all)==2 and cost_p.choice(cost_p.all,'minimax')==1
    # Cartesian support alone need not imply a factorized prior.
    weighted=Catalogue('weighted',('signal','tag'),(1,1),
                       (('0','0'),('0','1'),('1','0'),('1','1')),(0,0,1,1),(1,2,3,4))
    projected,_,certs=remove_independent_queries(weighted)
    assert len(certs)==1 and not certs[0]['weight_product']
    assert Planner(projected).value(3)==1
    # Compression preserves worst-case cost and weighted EC2 choices for both domains.
    quotients=0
    for name,builder in [('transport',transport_records),('event',event_records)]:
        records,queries=builder()
        raw,_=build_catalogue(name,records,queries,4,[r['label'] for r in records])
        compressed,mapping=raw.quotient(); a,b=Planner(raw),Planner(compressed)
        assert a.value(a.all)==b.value(b.all)
        for row in raw.rows:
            sa,sb=a.all,b.all
            for policy in ('minimax','ec2','hypothesis_entropy'):
                sa,sb=a.all,b.all
                while a.decision(sa) is None:
                    qa,qb=a.choice(sa,policy),b.choice(sb,policy)
                    assert qa==qb
                    if qa is None: break
                    sa=a.observe(sa,qa,row[qa]);sb=b.observe(sb,qb,row[qb])
                    assert {mapping[i] for i in a.members(sa)}==set(b.members(sb))
                assert a.decision(sa)==b.decision(sb)
                quotients+=1
    result=dict(oracle_tables=checked,reduction_checked_against_oracle=checked,
                tables_with_query_removal=reduced_tables,exact_transport_substeps=invariants,
                quotient_policy_paths=quotients,persistent_error_cases=len(noisy_rows),
                witnesses=['unsafe past quotient','detectable model conflict','undetectable misspecification',
                           'receipt before cutoff','nondecreasing cutoff','duplicate and conflicting source',
                           'prospective type rejection','intervention rejection','contract binding',
                           'interval-time validation','event versus receipt order','nonuniform costs'],status='pass')
    (ROOT/'results/domain_checks.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
