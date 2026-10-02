"""Independent finite-window checks; not a directed-rounding proof kernel."""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
from pathlib import Path
import numpy as np,json,itertools,copy
from gabriel import Gabriel,Config
from observer_bounds import ObserverBounds
OUT=Path(__file__).resolve().parents[1]/'results'

def tangent(g,co,u):
    """Forward sensitivities of the ORIGINAL x,c recurrences, without M."""
    N,m=u.shape;n=g.config.n;R=len(g.beta);d=g.config.degree
    x=np.zeros(n);c=np.zeros((R,n,d));dx=np.zeros((n,N*m));dc=np.zeros((R,n,d,N*m))
    B=np.zeros((n,n));B[np.arange(n)[:,None],g.parents]=g.base
    for t,ut in enumerate(u):
        drive=B@x+g.U@ut+g.bias;v=np.tanh(drive)
        ddrive=B@dx;ddrive[:,t*m:(t+1)*m]+=g.U
        dc=(1-g.beta[...,None])*dc+g.beta[...,None]*(dx[:,None,:]*x[g.parents][:,:,None]+x[:,None,None]*dx[g.parents])[None]
        c=(1-g.beta)*c+g.beta*(x[:,None]*x[g.parents])[None]
        dx=(1-g.alpha)[:,None]*dx+g.alpha[:,None]*(1-v*v)[:,None]*ddrive
        x=(1-g.alpha)*x+g.alpha*v
    f=np.r_[1,u[-1],x,c.mean(-1).ravel()]
    df=np.zeros((len(f),N*m));df[1:1+m,(N-1)*m:N*m]=np.eye(m)
    df[1+m:1+m+n]=dx;df[1+m+n:]=dc.mean(2).reshape(R*n,N*m)
    return co@f,(co@df).reshape(len(co),N,m)

def main():
    rng=np.random.default_rng(250926);maxpoint=maxcollapse=maxgrad=0.;samples=vertices=subsets=0
    for seed in range(12):
        g=Gabriel(seed,Config(n=6,degree=2,backbone_degree=1,input_dim=2),mode='trace_only');N=5
        co=rng.normal(size=(3,1+2+6+12));a=ObserverBounds(g,co,N)
        truth=rng.uniform(-.8,.8,(N,2));mask=np.zeros(N*2,bool);mask[rng.choice(N*2,6,False)]=True;mask=mask.reshape(N,2)
        lo=np.where(mask,-1,truth);hi=np.where(mask,1,truth);res=a.analyze(lo,hi,True);bounds=res['bounds'][0]
        vv=[]
        for signs in itertools.product([-1.,1.],repeat=6):
            v=truth.copy();v[mask]=signs;vv.append(v)
        interior=lo+(hi-lo)*rng.uniform(size=(60,N,2));xx=np.concatenate([vv,interior]);vertices+=len(vv)
        for u in xx:
            scores,jac=tangent(g,co,u);diff=np.array([scores[i]-scores[j] for i,j in a.pp]);deriv=np.array([jac[i]-jac[j] for i,j in a.pp])
            assert np.all(bounds[...,0]-1e-10<=diff) and np.all(diff<=bounds[...,1]+1e-10)
            assert np.all(res['gradient_lower'][0]-1e-10<=deriv) and np.all(deriv<=res['gradient_upper'][0]+1e-10)
            maxpoint=max(maxpoint,float(np.max(abs(scores-a.point(u)[0]))));samples+=1
        one=a.analyze(truth,truth,True);scores,jac=tangent(g,co,truth)
        diff=np.array([scores[i]-scores[j] for i,j in a.pp]);jac=np.array([jac[i]-jac[j] for i,j in a.pp])
        maxcollapse=max(maxcollapse,float(np.max(abs(one['bounds'][0]-diff[None,:,None]))))
        maxgrad=max(maxgrad,float(np.max(abs(one['gradient_lower'][0]-jac))),float(np.max(abs(one['gradient_upper'][0]-jac))))
        q=int(a.query(res,lo,hi)[0]);oldL=np.maximum(abs(res['gradient_lower'][0]),abs(res['gradient_upper'][0]))
        frozen=res['contributions'][0].sum((1,2))-res['contributions'][0].reshape(a.P,-1)[:,q]
        for answer in [-1.,-.43,0.,.71,1.]:
            ll=lo.copy();hh=hi.copy();ll.flat[q]=answer;hh.flat[q]=answer
            sub=a.analyze(ll,hh,True);bb=sub['bounds'][0]
            assert np.all(bb[...,0]>=bounds[...,0]-1e-9) and np.all(bb[...,1]<=bounds[...,1]+1e-9)
            newL=np.maximum(abs(sub['gradient_lower'][0]),abs(sub['gradient_upper'][0]))
            assert np.all(newL<=oldL+1e-10)
            assert np.all(2*sub['contributions'][0].sum((1,2))<=2*frozen+1e-9);subsets+=1
        record=a.record(lo,hi,'synthetic-normalization-1');assert a.verify_record(record,'synthetic-normalization-1')
        for key,val in [('model_hash','wrong'),('calibration_id','wrong'),('verdict',77),('clock','elapsed'),('margin',0.)]:
            altered=copy.deepcopy(record);altered[key]=val;assert not a.verify_record(altered,'synthetic-normalization-1')
        assert not a.verify_record(record,'stale-calibration')
        for ll,hh in [(lo*float('nan'),hi),(hi,lo),(lo-3,hi)]:
            try:a.analyze(ll,hh)
            except ValueError:pass
            else:raise AssertionError('bad box accepted')
    assert maxpoint<1e-12 and maxcollapse<1e-12 and maxgrad<1e-12
    # Endpoint rates beta=1, alpha=1 are allowed; zero uncertainty must collapse.
    edge=Gabriel(30,Config(n=6,degree=2,backbone_degree=1,input_dim=2,betas=(1.,.03),leaks=(1.,)),mode='trace_only')
    co=rng.normal(size=(3,21));aa=ObserverBounds(edge,co,5);u=rng.uniform(-1,1,(5,2));s,j=tangent(edge,co,u);bb=aa.analyze(u,u)
    assert np.max(abs(bb['bounds'][0]-np.array([s[i]-s[jj] for i,jj in aa.pp])[None,:,None]))<1e-12
    # Equal trace rates and opposite head coefficients cancel identically.
    edge=Gabriel(31,Config(n=6,degree=2,backbone_degree=1,input_dim=2,betas=(.2,.2)),mode='trace_only')
    co=np.zeros((3,21));co[:,0]=[1.,0.,-1.];co[:,9:15]=rng.normal(size=(3,6));co[:,15:21]=-co[:,9:15]
    aa=ObserverBounds(edge,co,5);bb=aa.analyze(-np.ones((5,2)),np.ones((5,2)));widths=bb['bounds'][0,...,1]-bb['bounds'][0,...,0]
    assert np.max(widths[1:])==0 and np.max(widths[0])>0
    # Source diagnostics: valid maps without a shared target or uniform loss.
    x=0.
    for k in range(200):x=.5*x+(-1 if k%2 else 1)
    product=float(np.prod([1-1/(k+2)**2 for k in range(10000)]))
    result=dict(seed=250926,graphs=12,completion_checks=samples,vertices=vertices,strict_box_restrictions=subsets,max_original_score_error=maxpoint,max_singleton_bound_error=maxcollapse,max_singleton_derivative_error=maxgrad,tolerance=1e-10,source_counterexamples=dict(alternating_affine_last=x,alternating_limit_magnitude=2/3,nonuniform_common_target_product_10000=product,product_limit=.5,disconnected_domain_jacobian_norm=0,disconnected_cross_lipschitz_ratio=2,rank_deficient_pullback_eigenvalues=[0,1]),scope='Float64 checks of exact-real interval derivations; no physical calibration or target-label guarantee.')
    result['endpoint_rate_check']=True;result['exact_trace_cancellation_basic_max_width']=float(np.max(widths[0]));result['exact_trace_cancellation_structured_max_width']=float(np.max(widths[1]))
    OUT.mkdir(exist_ok=True);(OUT/'observer_checks.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
if __name__=='__main__':main()
