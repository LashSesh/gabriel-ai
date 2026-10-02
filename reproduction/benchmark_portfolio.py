"""Execute the fixed finite current-record acquisition study.

Every catalogue case and complete query transcript is retained. Uniform case
means are catalogue summaries, not estimated operational frequencies.
"""
from pathlib import Path
from dataclasses import asdict
from fractions import Fraction as F
from collections import Counter
import json,time
from decision_regions import RegionPlanner,RegionSession,Observation,verify_certificate
from portfolio_adapter import (load_protocol,book_records,evaluate_books,catalogue,
                               minimum_full_book_set,inspection_catalogue,rational_json)
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results'


def execute(planner,row_index,policy,full_queries,snapshot):
    session=RegionSession(planner);cost=0;queries=[]
    if policy=='full_book':
        selected=iter(full_queries)
    while True:
        if policy=='full_book':
            q=next(selected,None)
        else:
            if planner.terminal(session.state,policy):break
            q=planner.choice(session.state,policy)
        if q is None:break
        cost+=planner.c.costs[q]
        received=snapshot+cost
        session.ingest(Observation(planner.c.identity,q,planner.c.rows[row_index][q],
                       f'current-record:{q}',(snapshot,snapshot),received),received)
        queries.append(q)
        if len(queries)>len(planner.c.query_names):raise RuntimeError('repeated acquisition')
    certificate=session.certificate()
    assert verify_certificate(planner.c,certificate)
    assert session.state>>row_index&1
    result=session.result()
    assert result['status'] in ('known','blocked')
    if result['status']=='known':
        a=planner.c.action_names.index(result['action'])
        assert planner.c.acceptable_masks[row_index]>>a&1
    else:assert planner.c.acceptable_masks[row_index]==0
    return dict(case=row_index,cost=cost,queries=queries,certificate=certificate)


def study(c,semantic,policies,snapshot,max_states,scope):
    planner=RegionPlanner(c,max_states=max_states)
    full_cost,full_count,full_queries=minimum_full_book_set(c.rows,semantic,c.costs)
    exact=planner.value(planner.all);strict=planner.strict_value(planner.all)
    result=dict(scope=scope,catalogue=rational_json(asdict(c)),identity=c.identity,
                initial=planner.assess(planner.all),optimal_worst_cost=exact,
                strict_optimal_worst_cost=strict,
                full_book_cost=full_cost,full_book_queries=full_queries,policies={})
    for policy in policies:
        paths=[execute(planner,i,policy,full_queries,snapshot) for i in range(len(c.rows))]
        counts=Counter(p['certificate']['status'] for p in paths)
        costs=[p['cost'] for p in paths]
        result['policies'][policy]=dict(paths=paths,case_count=len(paths),
                 mean_cost=str(F(sum(costs),len(costs))),worst_cost=max(costs),
                 mean_queries=str(F(sum(len(p['queries']) for p in paths),len(paths))),
                 status_counts=dict(counts),action_counts=dict(Counter(p['certificate']['action'] or 'none' for p in paths)),
                 nuisance_queries=sum(0 in p['queries'] for p in paths),wrong_decisions=0)
    assert result['policies']['minimax']['worst_cost']==exact
    assert result['policies']['strict_minimax']['worst_cost']==strict
    result['visited_planning_states']=len(planner._visited)
    return result


def main():
    start=time.perf_counter();p,digest=load_protocol();records=book_records(p)
    risks,flags,risk_certificates,unique=evaluate_books(p,records)
    output=dict(protocol_sha256=digest,scope='synthetic exhaustive passive current-record decisions',
                portfolio_records=records,risks=risks,feasible=flags,risk_certificates=risk_certificates,
                unique_loss_vectors=unique,studies=[])
    for index,settings in enumerate([p['primary']]+p['controls']):
        c=catalogue(p,digest,records,risks,flags,**settings)
        s=study(c,[r['semantic'] for r in records],p['policies'],p['record_snapshot_completed_at'],
                p['max_planner_states'],'portfolio-primary' if index==0 else 'portfolio-control-'+str(index))
        output['studies'].append(s)
        print(s['scope'],settings,'minimax',s['optimal_worst_cost'],
              'strict',s['strict_optimal_worst_cost'],'full',s['full_book_cost'],
              'means',{k:v['mean_cost'] for k,v in s['policies'].items()},flush=True)
    c,semantic=inspection_catalogue()
    s=study(c,semantic,p['policies'],p['record_snapshot_completed_at'],p['max_planner_states'],'industrial-inspection')
    output['studies'].append(s)
    print(s['scope'],'minimax',s['optimal_worst_cost'],'full',s['full_book_cost'],flush=True)
    output['seconds']=time.perf_counter()-start
    (OUT/'portfolio_results.json').write_text(json.dumps(rational_json(output),separators=(',',':'),allow_nan=False)+'\n')
    print('WROTE portfolio_results.json',round(output['seconds'],3),'seconds',flush=True)


if __name__=='__main__':main()
