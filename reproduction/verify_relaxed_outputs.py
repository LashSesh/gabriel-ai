"""Stored range/path checks and complete first/last-case audit replay."""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
from pathlib import Path
import numpy as np,json
from gabriel import Gabriel,Config
from relaxed_observer import RelaxedObserver
OUT=Path(__file__).resolve().parents[1]/'results'

def main():
    states=queries=steps=0;maxerr=0.;counts=[]
    for name in ['RacketSports','BasicMotions']:
        d=np.load(OUT/f'external_{name}_model.npz');p=np.load(OUT/f'relaxed_{name}_acquisition.npz');x=d['transformed_test'];n,N,m=x.shape;J=N*m//2
        a=RelaxedObserver(Gabriel(0,Config(input_dim=m),mode='trace_only'),d['trace_observer_coefficients'].T,N);assert p['model_hash'].item()==a.model_hash
        b=p['bounds'];v=p['verdicts'];scores=a.point(x);pred=scores.argmax(1);truth=np.stack([scores[:,i]-scores[:,j] for i,j in a.pp],1)[:,None,None,None,None,:]
        assert np.all(b[...,0]<=truth+1e-8) and np.all(b[...,1]>=truth-1e-8)
        assert np.array_equal(v,a.verdicts(b));assert np.all((v<0)|(v==pred[:,None,None,None,None]))
        assert np.all(np.diff(b[...,0],axis=3)>=-1e-8) and np.all(np.diff(b[...,1],axis=3)<=1e-8)
        assert np.all(b[:,:,:,:,1,:,0]>=b[:,:,:,:,0,:,0]-1e-8) and np.all(b[:,:,:,:,1,:,1]<=b[:,:,:,:,0,:,1]+1e-8)
        q=p['queries'];ans=p['answers']
        for i in range(n):
          for ms in range(2):
            hidden=np.flatnonzero(p['masks'][i,ms])
            for pi in range(2):
                assert np.array_equal(np.sort(q[i,ms,pi]),hidden)
                assert np.array_equal(ans[i,ms,pi],x[i].ravel()[q[i,ms,pi]])
        for i in [0,n-1]:
          for ms in range(2):
           for pi in range(2):
            lo=np.where(p['masks'][i,ms],-1,x[i].ravel()).reshape(N,m);hi=np.where(p['masks'][i,ms],1,x[i].ravel()).reshape(N,m);running=None
            for t in range(J+1):
                r=a.relaxed(lo,hi);bb=r['bounds'][0]
                if running is not None:bb=np.stack([np.maximum(bb[:,0],running[:,0]),np.minimum(bb[:,1],running[:,1])],-1)
                running=bb;r['bounds']=bb[None]
                ref=np.stack([r['base']['bounds'][0,2],bb]);err=max(float(abs(ref-b[i,ms,pi,t]).max()),float(abs(r['raw'][0]-p['raw_affine_bounds'][i,ms,pi,t]).max()));maxerr=max(maxerr,err);assert err<1e-8
                if t==J:break
                chosen=int(a.query(r['base'],lo,hi)[0]) if pi==0 else int(a.decision_query(r,lo,hi)[0]);assert chosen==q[i,ms,pi,t]
                lo.ravel()[chosen]=hi.ravel()[chosen]=ans[i,ms,pi,t];steps+=1
        counts.append(dict(dataset=name,resolved_at_three_quarters=int((v[:,:,:,3*J//4]>=0).sum()),box_states=n*4*(J+1)))
        states+=n*4*(J+1);queries+=q.size;print(name,'verified',flush=True)
    out=dict(input_box_states=states,range_sets=states*2,query_answers=int(queries),replayed_query_steps=steps,max_replay_difference=maxerr,datasets=counts,arithmetic='float64 checks; not validated box enclosures')
    (OUT/'relaxed_verification.json').write_text(json.dumps(out,indent=2));print(out)
if __name__=='__main__':main()
