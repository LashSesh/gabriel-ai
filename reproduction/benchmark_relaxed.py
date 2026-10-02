"""Frozen-head 2x2 comparison: old/new bounds and old/new query policies.

The prior derivative paths are unchanged. New decision queries use the current
box only. No labels or true hidden values enter query choice. Witness search
is post-hoc on saved boxes and does not influence either path.
"""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','1');os.environ.setdefault('OMP_NUM_THREADS','1')
from pathlib import Path
import numpy as np,json,time,csv,zipfile
from gabriel import Gabriel,Config
from relaxed_observer import RelaxedObserver
OUT=Path(__file__).resolve().parents[1]/'results'
NAMES=['RacketSports','BasicMotions'];MASKS=['random_half','middle_half'];POLICIES=['derivative','decision'];BOUNDS=['old_hybrid','affine_intersection']

def csvwrite(name,rows):
 with (OUT/name).open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)

def run(name):
 d=np.load(OUT/f'external_{name}_model.npz');old=np.load(OUT/f'observer_{name}_acquisition.npz');x=d['transformed_test'];n,N,m=x.shape;J=x[0].size//2;truth=x.reshape(n,-1)
 a=RelaxedObserver(Gabriel(0,Config(input_dim=m),mode='trace_only'),d['trace_observer_coefficients'].T,N);score=a.point(x);pred=score.argmax(1);diff=np.stack([score[:,p]-score[:,q] for p,q in a.pp],1)
 bounds=np.zeros((n,2,2,J+1,2,a.P,2));raw=np.zeros((n,2,2,J+1,a.P,2));vout=np.full((n,2,2,J+1,2),-1,int);queries=np.zeros((n,2,2,J),int);answers=np.zeros((n,2,2,J));start=time.perf_counter()
 for ms,mask in enumerate(MASKS):
  for pi,policy in enumerate(POLICIES):
   lo=np.where(old['masks'][:,ms],-1,truth).reshape(x.shape);hi=np.where(old['masks'][:,ms],1,truth).reshape(x.shape);running=None
   for t in range(J+1):
    r=a.relaxed(lo,hi);bb=r['bounds'];raw[:,ms,pi,t]=r['raw']
    if running is not None:bb=np.stack([np.maximum(bb[...,0],running[...,0]),np.minimum(bb[...,1],running[...,1])],-1)
    running=bb;r['bounds']=bb
    allb=np.stack([r['base']['bounds'][:,2],bb],1);bounds[:,ms,pi,t]=allb;v=a.verdicts(allb);vout[:,ms,pi,t]=v
    assert np.all(allb[...,0]-1e-8<=diff[:,None]) and np.all(diff[:,None]<=allb[...,1]+1e-8)
    assert np.all((v<0)|(v==pred[:,None]))
    if pi==0:assert np.max(abs(allb[:,0]-old['bounds'][:,ms,2,t,2]))<1e-8
    if t==J:break
    q=old['queries'][:,ms,2,t] if pi==0 else a.decision_query(r,lo,hi)
    assert np.all(hi.reshape(n,-1)[np.arange(n),q]>lo.reshape(n,-1)[np.arange(n),q])
    value=truth[np.arange(n),q];queries[:,ms,pi,t]=q;answers[:,ms,pi,t]=value
    lo.reshape(n,-1)[np.arange(n),q]=value;hi.reshape(n,-1)[np.arange(n),q]=value
    if t%75==0:print(name,mask,policy,t,J,round(time.perf_counter()-start,1),flush=True)
   print(name,mask,policy,'finished',round(time.perf_counter()-start,1),flush=True)
 target=OUT/f'relaxed_{name}_acquisition.npz';temporary=target.with_suffix('.pending.npz')
 np.savez_compressed(temporary,masks=old['masks'],queries=queries,answers=answers,bounds=bounds,raw_affine_bounds=raw,verdicts=vout,model_hash=a.model_hash)
 with zipfile.ZipFile(temporary) as z:assert z.testzip() is None
 temporary.replace(target)
 rows=[]
 for case in range(n):
  for ms,mask in enumerate(MASKS):
   for pi,policy in enumerate(POLICIES):
    for en,bnd in enumerate(BOUNDS):
     ids=np.flatnonzero(vout[case,ms,pi,:,en]>=0);assert len(ids)
     rows.append(dict(dataset=name,case=case,mask=mask,policy=policy,bound=bnd,first_resolved_query=int(ids[0]),missing=J,full_prediction=int(pred[case]),label=int(d['test_labels'][case])))
 (OUT/f'relaxed_{name}_runtime.json').write_text(json.dumps(dict(seconds=time.perf_counter()-start,input_box_states=n*2*2*(J+1),range_sets=int(vout.size),queries=int(queries.size)),indent=2));return rows

def main():
 protocol=dict(date='2026-09-25',selection='Methods specified after training-only probes on first eight training records per dataset; no head refitting',frozen_model='same trace observer as preceding study',datasets=NAMES,policies=POLICIES,bounds=BOUNDS,affine='parallel secant-slope tanh residual bounds; centered quadratic history residual',nesting='running intersection under exact compatible queries',decision_rule='midpoint candidate; least-proven rival; largest interval derivative contribution',decision_margin=1e-10,arithmetic='float64 screening; independent validated arithmetic is separate',scope='development on previously examined tasks, not fresh confirmation')
 (OUT/'relaxed_protocol.json').write_text(json.dumps(protocol,indent=2));rows=[]
 for name in NAMES:rows+=run(name);csvwrite('relaxed_stopping.csv',rows)
 print('Relaxed comparison complete.',flush=True)
if __name__=='__main__':main()
