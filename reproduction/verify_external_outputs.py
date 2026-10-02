"""Replay delivered classifiers and audit selected paths; check all saved bounds.

The replay shares the production feature/transition functions. Independent direct
vertex and polynomial tests are in check_scalable.py. All bounds and decisions
are inspected; query/path recomputation covers first and last test cases only.
"""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
os.environ.setdefault('OMP_NUM_THREADS','1')
from pathlib import Path
import csv,json,copy
import numpy as np
from benchmark_external import read_ts,normalizer,transform,feature_map,fit_ridge,folds,MODELS,NAMES,POLICIES,MASKS
from scalable_observation import *
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results'

def main():
 report={};counts=0
 for di,name in enumerate(NAMES):
  d=np.load(OUT/f'external_{name}_model.npz');a=np.load(OUT/f'external_{name}_acquisition.npz')
  x,y0=read_ts(ROOT/'data'/f'{name}_TRAIN.ts');test,yt0=read_ts(ROOT/'data'/f'{name}_TEST.ts')
  assert np.array_equal(x,d['train_inputs']) and np.array_equal(test,d['test_inputs'])
  y=np.searchsorted(d['classes'],y0);yt=np.searchsorted(d['classes'],yt0)
  assert np.array_equal(y,d['train_labels']) and np.array_equal(yt,d['test_labels'])
  assert np.array_equal(folds(y,93400+di),d['folds'])
  norm=normalizer(x);xn=transform(x,norm);tn=transform(test,norm)
  assert np.array_equal(xn,d['transformed_train']) and np.array_equal(tn,d['transformed_test'])
  error=0.;fit_error=0.
  for mi,mode in enumerate(MODELS):
   f=feature_map(tn,d['durations'],d['taus'],mode);scores=f@d[mode+'_coefficients']
   error=max(error,float(np.max(abs(scores-d[mode+'_test_scores']))))
   cv=d['cv_scores'][mi].mean(1);pi=np.flatnonzero(cv==cv.max())[-1]
   fit=fit_ridge(feature_map(xn,d['durations'],d['taus'],mode),y,len(d['classes']),d['penalties'][pi])
   fit_error=max(fit_error,float(np.max(abs(fit-d[mode+'_coefficients']))))
  c,b,Q=d['polynomial_constant'],d['polynomial_linear'],d['polynomial_quadratic']
  scores=evaluate_polynomial(c,b,Q,tn.reshape(len(tn),-1));error=max(error,float(np.max(abs(scores-d['ordered_memory_test_scores']))))
  pp=pairs(len(d['classes']));diff=np.array([scores[:,p]-scores[:,q] for p,q in pp]).T
  bounds=a['bounds'];ref=diff[:,None,None,None,:]
  excess=float(max(np.max(bounds[...,0]-ref),np.max(ref-bounds[...,1])))
  nesting=float(max(np.max(bounds[...,1:,:,1]-bounds[...,:-1,:,1]),np.max(bounds[...,:-1,:,0]-bounds[...,1:,:,0])))
  pred=scores.argmax(1);verdict=a['verdicts'];wrong=int(np.sum((verdict>=0)&(verdict!=pred[:,None,None,None])))
  # Reconstruct every saved class verdict directly from pairwise inequalities.
  wins=np.tile(np.eye(len(d['classes']),dtype=bool),bounds.shape[:-2]+(1,1))
  for j,(p,q) in enumerate(pp):wins[...,p,q]=bounds[...,j,0]>1e-10;wins[...,q,p]=bounds[...,j,1]<-1e-10
  winners=wins.all(-1);recomputed=np.where(winners.sum(-1)==1,winners.argmax(-1),-1)
  assert np.array_equal(recomputed,verdict)
  truth=tn.reshape(len(tn),-1);q=a['queries'];answers=np.take_along_axis(np.broadcast_to(truth[:,None,None,:],q.shape[:-1]+(truth.shape[-1],)),q,axis=-1)
  assert np.array_equal(answers,a['answers'])
  for case in range(len(tn)):
   for ms in range(2):
    for pi in range(3):assert np.array_equal(np.sort(q[case,ms,pi]),np.flatnonzero(a['masks'][case,ms]))
  # Full path and policy replay for two independently fixed case indices.
  replay=0.;steps=0;cp,bp,qp=class_pairs(c,b,Q)
  for case in [0,len(tn)-1]:
   for ms in range(2):
    mask=a['masks'][case,ms];lo=np.where(mask,-1,truth[case]);hi=np.where(mask,1,truth[case])
    for pi,policy in enumerate(POLICIES):
     audit=CoefficientAudit(cp,bp,qp,lo,hi);rng=np.random.default_rng(95500+1000*di+case+10000*ms)
     for t in range(q.shape[-1]+1):
      replay=max(replay,float(np.max(abs(audit.bounds()-bounds[case,ms,pi,t]))))
      if t<q.shape[-1]:
       chosen=audit.choose(policy,rng);assert chosen==q[case,ms,pi,t]
       audit.acquire(chosen,a['answers'][case,ms,pi,t]);steps+=1
  assert max(error,fit_error,excess,nesting,replay)<1e-9 and wrong==0
  report[name]=dict(classifier_replay_error=error,full_training_refit_error=fit_error,all_bound_excess=excess,all_nesting_excess=nesting,wrong_resolved_model_claims=wrong,audit_states=int(verdict.size),full_path_cases=[0,len(tn)-1],replayed_query_steps=steps,query_path_error=replay,exact_train_test_duplicates=int(d['exact_train_test_duplicates']))
  counts+=verdict.size
 report['total_audit_states']=int(counts);report['tolerance']=1e-9;report['scope']='All saved bounds, answers and verdicts checked; four dataset/case combinations fully replayed. Feature-map functions reused. CV not rerun.'
 (OUT/'external_verification.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
if __name__=='__main__':main()
