"""Replay every path without trusting the planner's saved masks or decisions.

Also execute the separately declared exploratory query-reduction study. The
primary benchmark archive remains unchanged.
"""
from pathlib import Path
from fractions import Fraction
from dataclasses import asdict
import hashlib
import json
from finite_observation import Catalogue, Planner, remove_independent_queries
from benchmark_domain import execute_case, validated_labels
from domain_adapters import transport_records, event_records

ROOT=Path(__file__).resolve().parents[1]


def from_json(d):
    return Catalogue(d['contract_id'],tuple(d['query_names']),tuple(d['costs']),
                     tuple(tuple(r) for r in d['rows']),tuple(d['labels']),tuple(d['weights']))


def independent_replay(c, small, mapping, runs, expected_policy=None):
    decisions=0
    for run in runs:
        ids=set(range(len(c.rows)));cost=0;seen=set()
        for step in run['path']:
            q,y=step['query'],step['outcome']
            assert q not in seen and c.rows[run['case']][q]==y
            seen.add(q);cost+=c.costs[q]
            ids={i for i in ids if c.rows[i][q]==y}
            assert run['case'] in ids
            assert {mapping[i] for i in ids}=={j for j in range(len(small.rows)) if int(step['state'],16)&(1<<j)}
            assert step['cost']==cost
        labs={c.labels[i] for i in ids}
        assert cost==run['cost'] and labs=={run['label']} and run['status']=='decided'
        decisions+=1
    return decisions


def main():
    source=ROOT/'results/domain_benchmark.json'
    data=json.loads(source.read_text())
    assert data['protocol_sha256']==hashlib.sha256((ROOT/'results/domain_protocol.json').read_bytes()).hexdigest()
    reviewed=0;reduced_runs=0; reduction=[]; point_checks=0
    for name,builder in [('conservative_transport',transport_records),('event_order',event_records)]:
        records,_=builder();labels,points=validated_labels(records)
        # JSON represents configuration tuples as lists; compare serialized values.
        assert json.loads(json.dumps(points))==data['point_certificates'][name]
        point_checks+=len(records)
    for study in data['studies']:
        c=from_json(study['catalogue']);small,mapping=c.quotient();p=Planner(small)
        assert c.identity==study['catalogue_digest'] and small.identity==study['compressed_digest']
        for policy,results in study['policies'].items():
            reviewed+=independent_replay(c,small,mapping,results['runs'])
            for r in results['runs']:
                replay=execute_case(p,c.rows[r['case']],policy)
                assert replay['path']==r['path'] and replay['label']==r['label']
            assert results['mean_cost']==str(Fraction(sum(r['cost'] for r in results['runs']),len(c.rows)))
        projected,kept,certificates=remove_independent_queries(small)
        pp=Planner(projected)
        assert pp.value(pp.all)==p.value(p.all)
        # Every decision outcome and remaining table row has a preimage.
        proj_keys={(label,row):i for i,(label,row) in enumerate(zip(projected.labels,projected.rows))}
        new_mapping=tuple(proj_keys[(c.labels[i],tuple(c.rows[i][q] for q in kept))] for i in range(len(c.rows)))
        rcat=Catalogue(projected.contract_id,projected.query_names,projected.costs,
                       tuple(tuple(row[q] for q in kept) for row in c.rows),c.labels,c.weights)
        res=dict(domain=study['domain'],target=study['target'],nuisance_values=study['nuisance_values'],
                 catalogue=asdict(projected),kept_query_indices=kept,certificates=certificates,
                 primary_catalogue_digest=c.identity,
                 hypotheses_before=len(small.rows),hypotheses_after=len(projected.rows),
                 bellman_states_before=study['bellman_states'],bellman_states_after=pp.value.cache_info().currsize,
                 minimax_worst=pp.value(pp.all),policies={})
        for policy in study['policies']:
            runs=[]
            for i,row in enumerate(rcat.rows):
                rr=execute_case(pp,row,policy);rr['case']=i;runs.append(rr)
            reduced_runs+=independent_replay(rcat,projected,new_mapping,runs)
            res['policies'][policy]=dict(mean_cost=str(Fraction(sum(r['cost'] for r in runs),len(runs))),
                                        worst_cost=max(r['cost'] for r in runs),runs=runs)
        reduction.append(res)
    # Product support is necessary for this sufficient reduction test; mere
    # marginal target balance is not enough (XOR makes both queries essential).
    xor=Catalogue('xor',('a','b'),(1,1),(('0','0'),('0','1'),('1','0'),('1','1')),(0,1,1,0))
    rx,_,cert=remove_independent_queries(xor)
    assert not cert and rx==xor
    correlated=Catalogue('correlated',('signal','metadata'),(5,1),(('0','0'),('1','1')),(0,1))
    rc,_,cert=remove_independent_queries(correlated)
    assert not cert and rc==correlated and Planner(rc).value(3)==1
    final=dict(primary_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
               exploratory_protocol_sha256=hashlib.sha256((ROOT/'results/domain_reduction_protocol.json').read_bytes()).hexdigest(),
               primary_paths_replayed=reviewed,reduced_paths_replayed=reduced_runs,
               arb_point_records_recomputed=point_checks,precision_bits=[100,160],
               product_counterexamples=['XOR synergy','correlated inexpensive metadata'],
               studies=reduction,status='pass')
    (ROOT/'results/domain_reduction.json').write_text(json.dumps(final,indent=2)+'\n')
    print({k:v for k,v in final.items() if k!='studies'})
    for s in reduction:
        if s['nuisance_values']==16:
            print(s['domain'],s['target'],'hypotheses',s['hypotheses_before'],s['hypotheses_after'],
                  'states',s['bellman_states_before'],s['bellman_states_after'],
                  'costs',{p:v['mean_cost'] for p,v in s['policies'].items()})


if __name__=='__main__':main()
