"""Independent small-box, substitution, multichannel and timing checks."""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
import numpy as np,itertools,copy,json,time,csv
from pathlib import Path
from scalable_observation import *
from partial_observation import replay_features
OUT=Path(__file__).resolve().parents[1]/'results'
def main():
 rng=np.random.default_rng(93024);compile_error=0.;recenter_error=0.;bound_excess=-np.inf;query_excess=-np.inf;nest_excess=-np.inf;refine_error=0.
 for trial in range(100):
  dim=2+trial%3;n=4;h=rng.uniform(.1,2,n);taus=np.array([.5,2.,8.,32.]);u=rng.uniform(-1,1,(20,n,dim));co=rng.normal(size=(3,1+dim+4*(dim+len(pairs(dim)))))
  c,b,Q=compile_readouts(co,h,taus,dim);vals=evaluate_polynomial(c,b,Q,u.reshape(20,-1));ref=memory_features(u,h,taus)@co.T;compile_error=max(compile_error,float(np.max(np.abs(vals-ref))))
  repeated=memory_features(np.repeat(u,3,axis=1),np.repeat(h/3,3),taus)@co.T;refine_error=max(refine_error,float(np.max(np.abs(vals-repeated))))
  lo=u[0].ravel().copy();hi=lo.copy();idx=np.sort(rng.choice(n*dim,8,replace=False));lo[idx]=-1;hi[idx]=1
  a=CoefficientAudit(c,b,Q,lo,hi);v=np.array(list(itertools.product([-1.,1.],repeat=8)));full=np.tile(lo,(256,1));full[:,idx]=v;truth=evaluate_polynomial(c,b,Q,full);bounds=a.bounds();bound_excess=max(bound_excess,float(np.max(bounds[:,0]-truth.min(0))),float(np.max(truth.max(0)-bounds[:,1])))
  scores=a.scores()
  for j,q in enumerate(a.ids):
   for z in [-1.,-.3,.2,1.]:
    aa=copy.deepcopy(a);aa.acquire(int(q),z);bb=aa.bounds();query_excess=max(query_excess,float(np.max(bb[:,1]-bb[:,0])-scores[j]));nest_excess=max(nest_excess,float(np.max(bounds[:,0]-bb[:,0])),float(np.max(bb[:,1]-bounds[:,1])))
  q=a.choose();val=float(u[1].ravel()[q]);a.acquire(q,val);lo[q]=hi[q]=val;fresh=CoefficientAudit(c,b,Q,lo,hi);recenter_error=max(recenter_error,float(np.max(np.abs(a.bounds()-fresh.bounds()))))
  assert a.acquire(q,val) is False
  try:a.acquire(q,val+.01)
  except ValueError:pass
  else:raise AssertionError('conflict accepted')
 # Explicit strict enclosure: x*y+x*z+y*z has range [-1,3], coefficient box [-3,3].
 Q=np.ones((1,3,3))-np.eye(3)[None];a=CoefficientAudit([0.],np.zeros((1,3)),Q,[-1]*3,[1]*3);v=np.array(list(itertools.product([-1.,1.],repeat=3)));true=evaluate_polynomial([0.],np.zeros((1,3)),Q,v).ravel();assert (true.min(),true.max())==(-1,3)
 # Direct agreement with the preceding two-channel state interface.
 u=rng.uniform(-1,1,(10,8,2));h=rng.uniform(.1,1,8);old=replay_features(u,h);new=memory_features(u,h,[.5,2,8,32]);two_error=float(np.max(np.abs(new-np.delete(old,3,axis=1))))
 assert max(compile_error,recenter_error,bound_excess,query_excess,nest_excess,refine_error,two_error)<1e-10
 result=dict(random_boxes=100,vertices_per_box=256,interior_replays=2000,compile_error=compile_error,recenter_error=recenter_error,bound_excess=bound_excess,query_excess=query_excess,nesting_excess=nest_excess,refinement_error=refine_error,two_channel_error=two_error,strict_enclosure_example=dict(exact=[-1,3],enclosure=a.bounds().tolist()),tolerance=1e-10)
 (OUT/'scalable_checks.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
 rows=[]
 for j in [12,24,48,96,192,384,768]:
  mat=rng.normal(size=(1,j,j));mat=np.triu(mat,1);mat=mat+mat.transpose(0,2,1);b=rng.normal(size=(1,j));a=CoefficientAudit([0],b,mat,-np.ones(j),np.ones(j));times=[]
  for repeat in range(7):
   start=time.perf_counter();a.bounds();a.scores();times.append(time.perf_counter()-start)
  rows.append(dict(missing=j,coefficient_bytes=a.Q.nbytes+a.l.nbytes+a.c.nbytes,median_bound_all_scores_seconds=float(np.median(times)),repeats=7))
 with (OUT/'scalable_timing.csv').open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=rows[0]);w.writeheader();w.writerows(rows)
 print(rows)
if __name__=='__main__':main()
