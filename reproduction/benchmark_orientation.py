"""Execute the frozen orientation protocol; synthetic mechanism study only."""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
from pathlib import Path
import json,hashlib,itertools,time
import numpy as np
from orientation import (profile_graph,face_rows,cycle_mask,rank,nullspace,span_masks,
                        parity,support,sign_bits,switching_mask,lifted_path,
                        BinaryObservation,OrientedGabriel,make_profile_core,double_cover)

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results'


def topology(vertices,edges,faces):
    lookup={v:i for i,v in enumerate(vertices)}
    incidence=[sum(1<<k for k,e in enumerate(edges) if v in e) for v in vertices]
    boundary=face_rows(edges,faces);r1=rank(incidence);r2=rank(boundary)
    adjacency=np.array([[int(tuple(sorted((a,b))) in edges) for b in vertices] for a in vertices])
    D=np.where(adjacency,1,10000);np.fill_diagonal(D,0)
    for k in range(len(vertices)):D=np.minimum(D,D[:,k,None]+D[None,k,:])
    ecc=D.max(1)
    vertex_cut=None
    for size in range(1,int(adjacency.sum(1).min())+1):
        for cut in itertools.combinations(vertices,size):
            remaining=set(vertices)-set(cut);seen={min(remaining)};stack=list(seen)
            while stack:
                a=stack.pop()
                for b in remaining-seen:
                    if tuple(sorted((a,b))) in edges:seen.add(b);stack.append(b)
            if seen!=remaining:vertex_cut=list(cut);break
        if vertex_cut is not None:break
    # Every nontrivial vertex subset determines an edge cut; complementary cuts coincide.
    cut_values=[sum(bool(((s>>lookup[a])^(s>>lookup[b]))&1) for a,b in edges)
                for s in range(1,1<<(len(vertices)-1))]
    return dict(vertices=list(vertices),edges=edges,faces=faces,rank_boundary1=r1,rank_boundary2=r2,
                betti=[len(vertices)-r1,len(edges)-r1-r2,len(faces)-r2],
                degree=adjacency.sum(1).tolist(),diameter=int(D.max()),radius=int(ecc.min()),
                center=np.array(vertices)[ecc==ecc.min()].tolist(),vertex_connectivity=len(vertex_cut),
                first_vertex_cut=vertex_cut,edge_connectivity=min(cut_values),
                adjacency_spectrum=np.linalg.eigvalsh(adjacency).tolist(),
                laplacian_spectrum=np.linalg.eigvalsh(np.diag(adjacency.sum(1))-adjacency).tolist())


def run_queries(vertices,edges,faces):
    rows=face_rows(edges,faces);ell=cycle_mask(edges,list(range(1,7)));n=len(edges)
    model=BinaryObservation(n,rows,[0]*len(rows),ell)
    histories=sorted(span_masks(nullspace(rows,n)))
    classes=[parity(ell,h) for h in histories]
    assert len(histories)==4096 and classes.count(1)==2048
    profiles={
        'unit':([1]*n,list(range(n))),
        'expensive_inner':([9 if a<=6 and b<=6 else 1 for a,b in edges],list(range(n))),
        'inner_unavailable':([1]*n,[i for i,(a,b) in enumerate(edges) if not(a<=6 and b<=6)])}
    results={}
    rng=np.random.default_rng(97599)
    random_order=rng.permutation(n).tolist()
    for name,(costs,available) in profiles.items():
        best=model.optimal_queries(costs,available)
        assert best['status']=='known_plan'
        plans={'optimal':best['queries'], 'lexical':[i for i in range(n) if i in available],
               'reverse':[i for i in reversed(range(n)) if i in available],
               'random':[i for i in random_order if i in available]}
        records={}
        for policy,order in plans.items():
            prefix=[]
            for j in order:
                if model.observe([(k,0) for k in prefix])['status']=='known':break
                prefix.append(j)
            assert model.observe([(k,0) for k in prefix])['status']=='known'
            evidence=[]
            for h,y in zip(histories,classes):
                obs=[(k,(h>>k)&1) for k in prefix];report=model.observe(obs)
                assert report['status']=='known' and report['value']==y
                # Store every exact answer and the row-combination proof.
                evidence.append([h,y,report['combination'],sum(bit<<j for j,(_,bit) in enumerate(obs))])
            records[policy]=dict(queries=prefix,query_count=len(prefix),cost=sum(costs[k] for k in prefix),records=evidence)
        results[name]=dict(costs=costs,available=available,optimization=best,policies=records)
    # Independent lower bound from all 5-element query sets: no target in the augmented row span.
    rank0=rank(rows);five_count=0
    for J in itertools.combinations(range(n),5):
        r=rows+tuple(1<<j for j in J)
        assert rank(r+(ell,))==rank(r)+1;five_count+=1
    # Removing all crossing edges makes the global parity unobservable even after all remaining queries.
    crossing=support(sign_bits(edges,True))
    unavailable=model.optimal_queries([1]*n,[i for i in range(n) if i not in crossing])
    assert unavailable['status']=='unobservable'
    # Off-model witness: outer-ring evidence cannot establish the assumed triangle relations.
    expensive=results['expensive_inner']['policies']['optimal']['queries']
    inner_only=next(k for k in support(ell) if k not in expensive)
    corrupt=1<<inner_only
    report=model.observe([(k,(corrupt>>k)&1) for k in expensive])
    assert report['status']=='known' and report['value']!=parity(ell,corrupt)
    return dict(model=dict(n=n,rows=rows,rhs=[0]*len(rows),target=ell),histories=histories,
                positive_sector=classes.count(0),negative_sector=classes.count(1),profiles=results,
                lower_bound_five_subsets=five_count,unavailable_crossing=crossing,
                unobservable=unavailable,off_model_witness=dict(bits=corrupt,observed=expensive,
                declared_answer=report['value'],actual_target=parity(ell,corrupt),
                violated_faces=[i for i,r in enumerate(rows) if parity(r,corrupt)]))


def run_routes(vertices,edges,faces):
    all_routes={}
    for sector in (0,1):
        bits=sign_bits(edges,bool(sector));nodes=list(itertools.product(vertices,(0,1)))
        records=[]
        for start in nodes:
            for goal in nodes:
                route=lifted_path(vertices,edges,bits,start,goal)
                records.append(dict(start=start,goal=goal,route=route))
        all_routes[str(sector)]=dict(bits=bits,reachable=sum(r['route'] is not None for r in records),
                                   pairs=len(records),routes=records)
    return all_routes


def run_dynamics(protocol):
    V,E,F=profile_graph();saved={};metrics=[]
    for seed in protocol['seeds']:
      for sector in (0,1):
       for mode in protocol['modes']:
        bits=sign_bits(E,bool(sector));g,sigma=make_profile_core(seed,bits,mode)
        rng=np.random.default_rng(seed+1000)
        g.x=rng.uniform(-1,1,12);g.c=rng.uniform(-1,1,g.c.shape)
        model=OrientedGabriel(g,sigma);sgn=rng.choice([-1,1],12)
        switched=model.change_frames(sgn);cover=double_cover(g,sigma)
        other=OrientedGabriel(g,sigma)
        other.x=rng.uniform(-1,1,12);other.d=rng.uniform(-1,1,other.d.shape)
        cert=g.certificate();scale=cert['trace_scale'];kappa=cert['kappa']
        inputs=rng.uniform(-1,1,(protocol['steps'],2));head=rng.uniform(-1,1,24)
        snapshots=[];rawdiff=[];invariantdiff=[];coverdiff=[];originaldiff=[];gaugeerr=[];dist=[]
        initial=max(np.max(abs(model.x-other.x)),np.max(abs(model.d-other.d))/scale)
        for t,u in enumerate(inputs):
            model.step(u);switched.step(u);cover.step(u);g.step(u);other.step(u)
            snapshots.append(np.concatenate([model.x,model.d.ravel()]))
            originaldiff.append(max(np.max(abs(model.x-g.x)),np.max(abs(model.d-sigma[None,:,:]*g.c))))
            gaugeerr.append(max(np.max(abs(switched.x-sgn*model.x)),np.max(abs(switched.d-model.d))))
            invariantdiff.append(abs(head@(model.trace_features()-switched.trace_features())))
            raw0=(model.d*model.sigma[None,:,:]).mean(2).ravel()
            raw1=(switched.d*switched.sigma[None,:,:]).mean(2).ravel()
            rawdiff.append(abs(head@(raw0-raw1)))
            coverdiff.append(max(np.max(abs(cover.x[::2]-model.x)),np.max(abs(cover.x[1::2]+model.x)),
                                 np.max(abs(cover.c[:,::2]-model.d)),np.max(abs(cover.c[:,1::2]-model.d))))
            distance=max(np.max(abs(model.x-other.x)),np.max(abs(model.d-other.d))/scale)
            dist.append(distance)
            assert distance<=initial*kappa**(t+1)+protocol['tolerance']
        maxerr=max(max(originaldiff),max(gaugeerr),max(coverdiff),max(invariantdiff))
        assert maxerr<protocol['tolerance']
        key=f's{seed}_h{sector}_{mode}'
        saved[key+'_input']=inputs;saved[key+'_state']=snapshots;saved[key+'_gauge']=sgn
        saved[key+'_raw_readout_difference']=rawdiff;saved[key+'_distance']=dist
        saved[key+'_contraction_bound']=initial*kappa**np.arange(1,len(inputs)+1)
        saved[key+'_head']=head
        metrics.append(dict(seed=seed,sector=sector,mode=mode,steps=len(inputs),certificate=cert,
                            maximum_original_error=max(originaldiff),maximum_gauge_error=max(gaugeerr),
                            maximum_cover_error=max(coverdiff),maximum_invariant_readout_error=max(invariantdiff),
                            maximum_raw_readout_difference=max(rawdiff),initial_distance=initial,
                            final_distance=dist[-1]))
    np.savez_compressed(OUT/'orientation_dynamics.npz',**saved)
    return metrics


def main():
    start=time.perf_counter();raw=(OUT/'orientation_protocol.json').read_bytes();protocol=json.loads(raw)
    V,E,F=profile_graph();struct={'full':topology(*profile_graph(include_anchor=True)),
                                'operational':topology(V,E,F)}
    queries=run_queries(V,E,F);routes=run_routes(V,E,F);dynamics=run_dynamics(protocol)
    result=dict(protocol_sha256=hashlib.sha256(raw).hexdigest(),topology=struct,
                queries=queries,routes=routes,dynamics=dynamics,seconds=time.perf_counter()-start)
    (OUT/'orientation_results.json').write_text(json.dumps(result,indent=2))
    summary=dict(protocol_sha256=result['protocol_sha256'],flat_assignments=len(queries['histories']),
                 topology={k:{x:v[x] for x in ('betti','radius','center','rank_boundary1','rank_boundary2')}
                           for k,v in struct.items()},
                 retrieval={k:{p:{x:r[x] for x in ('query_count','cost')} for p,r in v['policies'].items()}
                            for k,v in queries['profiles'].items()},
                 exact_decisions=sum(len(r['records']) for v in queries['profiles'].values() for r in v['policies'].values()),
                 five_query_sets=queries['lower_bound_five_subsets'],dynamic_runs=len(dynamics),
                 max_gauge_error=max(r['maximum_gauge_error'] for r in dynamics),
                 max_cover_error=max(r['maximum_cover_error'] for r in dynamics),
                 max_original_error=max(r['maximum_original_error'] for r in dynamics),
                 max_invariant_readout_error=max(r['maximum_invariant_readout_error'] for r in dynamics),
                 max_raw_readout_difference=max(r['maximum_raw_readout_difference'] for r in dynamics),
                 seconds=result['seconds'])
    (OUT/'orientation_summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary,indent=2))

if __name__=='__main__':main()
