"""Synthetic buffered-input acquisition, with frozen rules and readout.

The queried archive already contains the held input values. This evaluates
which missing RECORD to retrieve, not physical sensing of a bygone signal.
Reference truth is the complete-input MODEL output, not an empirical target.
"""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
os.environ.setdefault('OMP_NUM_THREADS','1')
import json,csv,time,copy
from pathlib import Path
import numpy as np
from partial_observation import VertexAudit,replay_features,interval_bounds,sign_verdict,TAUS

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results'
N=128;PREFIX=32;WINDOW=16;MISSING=12
POLICIES=['random','recent','minimax'];TASKS=['order_state_tau2','frozen_order_readout']

class BufferedArchive:
    def __init__(self,values):self._values=np.array(values,float).ravel()
    def query(self,coordinate):return float(self._values[coordinate])

def frozen_coefficients():
    c=np.zeros((2,16));c[0,4+8+1]=1.
    with np.load(OUT/'multitime_seed_60.npz') as d:
        w=d['elapsed_ordered_readout'][:,3];mu=d['elapsed_ordered_feature_mean'];sd=d['elapsed_ordered_feature_scale']
        c[1,1:]=w[1:]/sd;c[1,0]=d['elapsed_ordered_target_mean'][3]+w[0]-c[1,1:]@mu
    return c

def main():
    coeff=frozen_coefficients();start=time.perf_counter()
    protocol=dict(cases=N,prefix=PREFIX,window=WINDOW,missing_scalar_fields=MISSING,
        input_seed_offset=90000,random_policy_seed_offset=91000,taus=TAUS.tolist(),
        durations='loguniform(.1,2)',input_values='independent uniform[-1,1]',
        missingness='12 distinct uniform scalar positions among 32 window entries',
        initial_state='zero before the fully observed 32-event prefix',
        policies=POLICIES,tasks=TASKS,query_cost=1,query_noise=0,maximum_queries=12,
        numerical_margin=1e-12,scope='retrieval of exact entries in a buffered synthetic record',
        readout_source='multitime_seed_60.npz; frozen elapsed_ordered head, target column 3',
        truth='complete-input model output; not a regression-target coverage claim',
        policy_access='input bounds, durations, prefix state, coefficients, previously acquired fields only')
    (OUT/'partial_protocol.json').write_text(json.dumps(protocol,indent=2))
    us=[];hs=[];masks=[];prefix_a=[];prefix_r=[];vertices=[];truths=[];midpoints=[];initial_intervals=[]
    ranges=np.zeros((N,2,3,13,2));queries=np.zeros((N,2,3,12),int);answers=np.zeros((N,2,3,12))
    boxranges=np.zeros_like(ranges);rows=[]
    for case in range(N):
        rng=np.random.default_rng(90000+case);u=rng.uniform(-1,1,(PREFIX+WINDOW,2));h=np.exp(rng.uniform(np.log(.1),np.log(2),len(u)))
        p=replay_features(u[:PREFIX],h[:PREFIX])[0];a0=p[4:12].reshape(4,2);r0=p[12:]
        uw=u[PREFIX:];hw=h[PREFIX:];mask=np.zeros(uw.shape,bool);mask.ravel()[rng.choice(uw.size,MISSING,replace=False)]=True
        lower=np.where(mask,-1.,uw);upper=np.where(mask,1.,uw)
        truth=replay_features(uw,hw,a0,r0)[0]@coeff.T
        audits=[VertexAudit(lower,upper,hw,c,a0,r0) for c in coeff]
        us.append(u);hs.append(h);masks.append(mask);prefix_a.append(a0);prefix_r.append(r0)
        vertices.append(np.column_stack([a.values.ravel() for a in audits]));truths.append(truth)
        midpoints.append([float(a.values.mean()) for a in audits]);initial_intervals.append([interval_bounds(lower,upper,hw,c,a0,r0) for c in coeff])
        archive=BufferedArchive(uw)
        for task,base in enumerate(audits):
            for pol,policy in enumerate(POLICIES):
                audit=copy.deepcopy(base);prng=np.random.default_rng(91000+case)
                for budget in range(13):
                    bounds=audit.bounds();ranges[case,task,pol,budget]=bounds
                    bb=interval_bounds(audit.lower,audit.upper,hw,coeff[task],a0,r0);boxranges[case,task,pol,budget]=bb
                    verdict=sign_verdict(bounds);box_verdict=sign_verdict(bb)
                    rows.append(dict(case=case,task=TASKS[task],policy=policy,queries=budget,
                        width=bounds[1]-bounds[0],box_width=bb[1]-bb[0],
                        relative_width=(bounds[1]-bounds[0])/(base.bounds()[1]-base.bounds()[0]),
                        resolved=int(verdict!=-1),wrong_resolved=int(verdict!=-1 and verdict!=int(truth[task]>0)),
                        box_resolved=int(box_verdict!=-1),truth=truth[task],lower=bounds[0],upper=bounds[1]))
                    assert bounds[0]-1e-12<=truth[task]<=bounds[1]+1e-12
                    assert bb[0]-1e-12<=bounds[0]<=bounds[1]<=bb[1]+1e-12
                    assert not(verdict!=-1 and verdict!=int(truth[task]>0))
                    if budget==12:break
                    q=audit.choose(policy,prng);v=archive.query(q)
                    queries[case,task,pol,budget]=q;answers[case,task,pol,budget]=v
                    audit.acquire(q,v)
        if case%16==15:print('partial cases',case+1,'completed',flush=True)
    np.savez_compressed(OUT/'partial_observation_cases.npz',inputs=us,durations=hs,missing=masks,
        prefix_a=prefix_a,prefix_r=prefix_r,coefficients=coeff,vertex_outputs=vertices,
        truth=truths,midpoint_predictions=midpoints,initial_interval_bounds=initial_intervals,
        bounds=ranges,box_bounds=boxranges,queries=queries,answers=answers)
    with (OUT/'partial_benchmark.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    summary=[]
    for task in TASKS:
        for policy in POLICIES:
            for budget in range(13):
                rr=[r for r in rows if r['task']==task and r['policy']==policy and r['queries']==budget]
                summary.append(dict(task=task,policy=policy,queries=budget,
                    resolved=sum(r['resolved'] for r in rr),wrong_resolved=sum(r['wrong_resolved'] for r in rr),
                    box_resolved=sum(r['box_resolved'] for r in rr),
                    mean_relative_width=float(np.mean([r['relative_width'] for r in rr])),
                    mean_width=float(np.mean([r['width'] for r in rr]))))
    with (OUT/'partial_summary.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(summary[0]));w.writeheader();w.writerows(summary)
    result=dict(cases=N,scored_audits=len(rows),midpoint_wrong_signs=np.sum((np.array(midpoints)>0)!=(np.array(truths)>0),axis=0).tolist(),
        wrong_resolved=sum(r['wrong_resolved'] for r in rows),runtime_seconds=time.perf_counter()-start,
        feature_enumerations=N*2,vertices_per_initial_audit=2**MISSING)
    (OUT/'partial_run_summary.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))
    for row in summary:
        if row['queries'] in [0,4,8,12]:print(row)

if __name__=='__main__':main()
