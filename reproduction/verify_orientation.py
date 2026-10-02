"""Independent saved-output replay, exact finite oracles and adversarial checks."""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
from pathlib import Path
from collections import defaultdict
import itertools,json,hashlib
import numpy as np
from orientation import BinaryObservation,profile_graph,face_rows,cycle_mask,rank,parity,support,decode_address,OrientedGabriel,make_profile_core,lifted_path

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results'


def xor_rows(rows,mask):
    v=0
    for i in support(mask):v^=rows[i]
    return v


def verify_report(model,obs,report,oracle):
    rows=list(model.rows)+[1<<i for i,y in obs];rhs=list(model.rhs)+[y for i,y in obs]
    if report['status']=='conflict':
        assert not oracle
        w=report['combination'];assert xor_rows(rows,w)==0 and xor_rows(rhs,w)==1
    elif report['status']=='known':
        assert oracle and {parity(model.target,h) for h in oracle}=={report['value']}
        w=report['combination'];assert xor_rows(rows,w)==model.target and xor_rows(rhs,w)==report['value']
    else:
        assert {parity(model.target,h) for h in oracle}=={0,1}
        a,b=report['completions'];assert a in oracle and b in oracle
        assert parity(model.target,a)==0 and parity(model.target,b)==1


def finite_oracles():
    rng=np.random.default_rng(97600);count=reports=0
    for case in range(80):
        n=int(rng.integers(3,9));m=int(rng.integers(0,n+1))
        rows=[int(x) for x in rng.integers(0,1<<n,m)];rhs=[int(x) for x in rng.integers(0,2,m)]
        ell=int(rng.integers(0,1<<n));model=BinaryObservation(n,rows,rhs,ell)
        valid=[h for h in range(1<<n) if all(parity(a,h)==b for a,b in zip(rows,rhs))]
        costs=[int(x) for x in rng.integers(1,6,n)];available=[j for j in range(n) if rng.random()>.2]
        plan=model.optimal_queries(costs,available)
        best=None
        if valid:
            for mask in range(1<<n):
                J=support(mask)
                if not set(J)<=set(available):continue
                groups=defaultdict(set)
                for h in valid:groups[h&mask].add(parity(ell,h))
                if all(len(g)==1 for g in groups.values()):
                    key=(sum(costs[j] for j in J),len(J),tuple(J))
                    if best is None or key<best:best=key
            if best is None:assert plan['status']=='unobservable'
            else:assert (plan['cost'],len(plan['queries']),tuple(plan['queries']))==best
        else:assert plan['status']=='conflict'
        for trial in range(12):
            obs=[(int(rng.integers(n)),int(rng.integers(2))) for _ in range(trial)]
            feasible=[h for h in valid if all(((h>>i)&1)==y for i,y in obs)]
            verify_report(model,obs,model.observe(obs),feasible);reports+=1
        count+=1
    # Explicit duplicates, impossible base model, unavailable target, invalid addresses.
    mm=BinaryObservation(3,[3],[1],4)
    for obs in [[(2,1)],[(2,1),(2,1)],[(2,1),(2,0)]]:
        feasible=[h for h in range(8) if parity(3,h)==1 and all(((h>>i)&1)==y for i,y in obs)]
        verify_report(mm,obs,mm.observe(obs),feasible)
    assert mm.optimal_queries([1]*3,[0,1])['status']=='unobservable'
    invalid=[-1,16,13,14,15,0,True,1.5]
    for x in invalid:
        try:decode_address(x,operational=True)
        except ValueError:pass
        else:raise AssertionError('invalid address accepted')
    for x in range(1,13):assert decode_address(x,True)==x
    for rows,target in [([1.5],1),([1],.5)]:
        try:BinaryObservation(3,rows,[0],target)
        except ValueError:pass
        else:raise AssertionError('fractional bit mask accepted')
    return dict(random_affine_models=count,independent_query_subset_oracles=count,random_evidence_reports=reports,
                explicit_duplicate_checks=3,invalid_operational_addresses=len(invalid))


def saved_combinatorics(data):
    q=data['queries'];rows=q['model']['rows'];rhs=q['model']['rhs'];ell=q['model']['target']
    histories=q['histories'];V,E,F=profile_graph()
    # Independent catalogue construction from vertex switching plus one seam bit.
    edge_bits={}
    seam={(1,6),(7,12),(6,7)}
    catalogue=set()
    for sector in (0,1):
        for s in range(1<<11):
            node=[0]+[(s>>i)&1 for i in range(11)];bits=0
            for k,(a,b) in enumerate(E):bits|=(node[a-1]^node[b-1]^(sector and (a,b) in seam))<<k
            catalogue.add(bits)
    assert catalogue==set(histories) and len(histories)==4096
    decisions=0
    for name,profile in q['profiles'].items():
        for policy,p in profile['policies'].items():
            J=p['queries'];mask=sum(1<<j for j in J)
            assert len(set(J))==len(J) and set(J)<=set(profile['available'])
            assert p['cost']==sum(profile['costs'][j] for j in J)
            for step in range(len(J)):
                partial=sum(1<<j for j in J[:step]);classes=defaultdict(set)
                for h in histories:classes[h&partial].add((h&ell).bit_count()%2)
                assert all(len(v)==2 for v in classes.values())
            full_groups=defaultdict(set)
            for h in histories:full_groups[h&mask].add((h&ell).bit_count()%2)
            assert all(len(v)==1 for v in full_groups.values())
            for h,y,w,answers in p['records']:
                assert h in catalogue and y==(h&ell).bit_count()%2
                obs=[(j,(answers>>k)&1) for k,j in enumerate(J)]
                assert all(((h>>j)&1)==b for j,b in obs)
                all_rows=rows+[1<<j for j in J];all_rhs=rhs+[b for j,b in obs]
                assert xor_rows(all_rows,w)==ell and xor_rows(all_rhs,w)==y
                decisions+=1
    # Floyd--Warshall independently checks every lifted route and impossible pair.
    pairs=0;largest=[]
    for sector,rr in data['routes'].items():
        n=24;D=np.full((n,n),10000,dtype=int);np.fill_diagonal(D,0)
        bits=rr['bits']
        for k,(a,b) in enumerate(E):
            f=(bits>>k)&1
            for s in (0,1):
                i=2*(a-1)+s;j=2*(b-1)+(s^f);D[i,j]=D[j,i]=1
        A=D==1
        for k in range(n):D=np.minimum(D,D[:,k,None]+D[None,k,:])
        for r in rr['routes']:
            a,s=r['start'];b,t=r['goal'];i=2*(a-1)+s;j=2*(b-1)+t;path=r['route']
            if path is None:assert D[i,j]==10000
            else:
                assert path[0]==r['start'] and path[-1]==r['goal'] and len(path)-1==D[i,j]
                for (a,s),(b,t) in zip(path,path[1:]):assert A[2*(a-1)+s,2*(b-1)+t]
            pairs+=1
        largest.append(int(D[D<10000].max()))
    # Full-profile flatness leaves no global cycle; punctured family retains exactly one.
    family=[]
    for m in range(4,13):
        v,e,f=profile_graph(m);face=face_rows(e,f)
        incidence=[sum(1<<k for k,edge in enumerate(e) if a in edge) for a in v]
        assert len(e)-rank(incidence)-rank(face)==1
        assert len(e)-rank(face)==len(v)
        family.append(m)
    V0,E0,F0=profile_graph(include_anchor=True)
    assert len(E0)-rank(face_rows(E0,F0))==12
    reference_adjacency=sorted([-2]*5+[-.73205]*2+[0]*2+[1.26795]+[2.73205]*2+[4.73205])
    reference_laplacian=[0,1.69722,1.69722,3.43845,4.38197,4.38197,5.30278,5.30278,6]
    spectral_error=max(np.max(abs(np.array(reference_adjacency)-data['topology']['full']['adjacency_spectrum'])),
                       np.max(abs(np.array(reference_laplacian)-data['topology']['full']['laplacian_spectrum'][:9])))
    assert spectral_error<5e-6
    return dict(saved_decisions=decisions,lifted_endpoint_pairs=pairs,lift_component_diameters=largest,
                ring_sizes_checked=family,independent_flat_catalogue=4096,source_spectral_rounding_error=float(spectral_error))


def dense_replay(data,protocol):
    archive=np.load(OUT/'orientation_dynamics.npz');error=0.;states=0
    for r in data['dynamics']:
        seed,sector,mode=r['seed'],r['sector'],r['mode']
        # Source registry is written out independently of the module's graph builder.
        E=sorted({tuple(sorted(e)) for i in range(6) for e in
                  [(1+i,1+(i+1)%6),(7+i,7+(i+1)%6),(1+i,7+i),(1+i,7+(i+1)%6)]})
        bits=sum(1<<k for k,e in enumerate(E) if sector and e in {(1,6),(7,12),(6,7)})
        g,sigma=make_profile_core(seed,bits,mode)
        rng=np.random.default_rng(seed+1000)
        x=rng.uniform(-1,1,12).astype(np.longdouble)
        c=rng.uniform(-1,1,g.c.shape).astype(np.longdouble)
        key=f's{seed}_h{sector}_{mode}';inputs=archive[key+'_input'];stored=archive[key+'_state']
        for u,y in zip(inputs,stored):
            W=np.zeros((12,12),dtype=np.longdouble)
            for i in range(12):
                for j,parent in enumerate(g.parents[i]):
                    a=np.longdouble(sigma[i,j])*.1
                    if mode=='adaptive':
                        for tr in range(2):a+=np.longdouble(.07)*np.sign(c[tr,i,j])*max(abs(c[tr,i,j])-np.longdouble(.08),0)/4
                    W[i,parent]=a
            drive=W@x+g.U.astype(np.longdouble)@u.astype(np.longdouble)+g.bias.astype(np.longdouble)
            xx=(1-g.alpha.astype(np.longdouble))*x+g.alpha.astype(np.longdouble)*np.tanh(drive)
            for tr,beta in enumerate([.03,.2]):
                c[tr]=(1-np.longdouble(beta))*c[tr]+np.longdouble(beta)*(x[:,None]*x[g.parents])
            x=xx;expected=np.concatenate([x,(c*sigma[None,:,:]).ravel()])
            error=max(error,float(np.max(abs(expected-y))));states+=1
    assert error<protocol['tolerance']
    return dict(longdouble_dense_replayed_states=states,maximum_absolute_state_error=error,
                longdouble_mantissa_bits=np.finfo(np.longdouble).nmant+1)


def main():
    data=json.loads((OUT/'orientation_results.json').read_text())
    raw=(OUT/'orientation_protocol.json').read_bytes();protocol=json.loads(raw)
    assert hashlib.sha256(raw).hexdigest()==data['protocol_sha256']
    result=dict(protocol_sha256=data['protocol_sha256'],finite_oracles=finite_oracles(),
                combinatorics=saved_combinatorics(data),numerical=dense_replay(data,protocol))
    (OUT/'orientation_verification.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))

if __name__=='__main__':main()
