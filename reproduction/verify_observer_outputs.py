"""Inspect ALL stored claims; replay first and last case, every policy and query.

The small independent tangent reference is in check_observer.py. This path replay
reuses production interval arithmetic and is not an independent proof kernel.
"""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','1');os.environ.setdefault('OMP_NUM_THREADS','1')
from pathlib import Path
import numpy as np,json,time
from gabriel import Gabriel,Config
from observer_bounds import ObserverBounds
from benchmark_observer import NAMES
OUT=Path(__file__).resolve().parents[1]/'results'

def main():
 report={};total=0;rng=np.random.default_rng(250927)
 for name in NAMES:
  start=time.perf_counter();d=np.load(OUT/f'external_{name}_model.npz');z=np.load(OUT/f'observer_{name}_acquisition.npz');old=np.load(OUT/f'external_{name}_acquisition.npz')
  x=d['transformed_test'];n,N,m=x.shape;a=ObserverBounds(Gabriel(0,Config(input_dim=m),mode='trace_only'),d['trace_observer_coefficients'].T,N)
  score=a.point(x);pred=score.argmax(1);diff=np.stack([score[:,p]-score[:,q] for p,q in a.pp],1)
  assert np.array_equal(z['masks'],old['masks']) and np.array_equal(z['queries'][:,:,:2],old['queries'][:,:,:2])
  assert a.model_hash==str(z['model_hash'])
  bounds=z['bounds'];v=z['verdicts'];ref=diff[:,None,None,None,None,:]
  excess=float(max(np.max(bounds[...,0]-ref),np.max(ref-bounds[...,1])))
  nesting=float(max(np.max(bounds[:,:,:,1:,...,1]-bounds[:,:,:,:-1,...,1]),np.max(bounds[:,:,:,:-1,...,0]-bounds[:,:,:,1:,...,0])))
  assert np.array_equal(a.verdicts(bounds),v);wrong=int(np.sum((v>=0)&(v!=pred[:,None,None,None,None])))
  q=z['queries'];truth=x.reshape(n,-1);ans=np.take_along_axis(np.broadcast_to(truth[:,None,None,:],q.shape[:-1]+(truth.shape[-1],)),q,-1);assert np.array_equal(ans,z['answers'])
  for case in range(n):
   for ms in range(2):
    for pi in range(3):assert np.array_equal(np.sort(q[case,ms,pi]),np.flatnonzero(z['masks'][case,ms]))
  cases=np.array([0,n-1]);replay=selection_error=0.;steps=completionchecks=0
  for ms in range(2):
   for pi in range(3):
    lo=np.where(z['masks'][cases,ms],-1,truth[cases]).reshape(2,N,m);hi=np.where(z['masks'][cases,ms],1,truth[cases]).reshape(2,N,m)
    for t in range(q.shape[-1]+1):
     res=a.analyze(lo,hi);bb=res['bounds'];replay=max(replay,float(np.max(abs(bb-bounds[cases,ms,pi,t]))))
     if t in [0,q.shape[-1]//2]:
      for repeat in range(12):
       u=lo+(hi-lo)*rng.uniform(size=lo.shape);sc=a.point(u);df=np.stack([sc[:,p]-sc[:,qq] for p,qq in a.pp],1)
       assert np.all(bb[...,0]-1e-9<=df[:,None]) and np.all(df[:,None]<=bb[...,1]+1e-9);completionchecks+=2
     if t==q.shape[-1]:break
     chosen=q[cases,ms,pi,t]
     if pi==2:assert np.array_equal(chosen,a.query(res,lo,hi))
     c=res['contributions'].reshape(2,a.P,-1);sel=np.max(c.sum(-1)-np.take_along_axis(c,chosen[:,None,None],axis=2)[...,0],1)
     selection_error=max(selection_error,float(np.max(abs(sel-z['selection_upper_radius'][cases,ms,pi,t]))))
     values=z['answers'][cases,ms,pi,t];lo.reshape(2,-1)[np.arange(2),chosen]=values;hi.reshape(2,-1)[np.arange(2),chosen]=values;steps+=2
  for item in json.loads((OUT/f'observer_{name}_records.json').read_text()):
   rec=item['record'];assert a.verify_record(rec,rec['calibration_id'])
  assert max(excess,nesting,replay,selection_error)<1e-8 and wrong==0
  report[name]=dict(all_range_sets=int(v.size),all_input_audit_states=int(v.size//3),all_bound_excess=excess,all_nesting_excess=nesting,wrong_resolved_model_claims=wrong,replayed_cases=cases.tolist(),replayed_query_steps=steps,replayed_bound_error=replay,replayed_selection_error=selection_error,random_completion_checks=completionchecks,elapsed_seconds=time.perf_counter()-start)
  total+=v.size;print(name,report[name],flush=True)
 report['total_range_sets']=int(total);report['scope']='All saved ranges, answers, verdicts, path membership and nesting checked. First/last record, all masks and policies replayed. No retraining. Numerical tolerance 1e-8; not directed rounding.'
 (OUT/'observer_verification.json').write_text(json.dumps(report,indent=2));print('Observer output verification complete.',flush=True)
if __name__=='__main__':main()
