"""Frozen-model observer verification and acquisition, with no fitting.

Protocol constants are declared before test execution. These are development
datasets already used by the project, not fresh confirmatory held-out datasets.
Random/recent paths and all masks are inherited unchanged from the ordered-head
experiment; derivative queries see only currently disclosed values and bounds.
"""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','1');os.environ.setdefault('OMP_NUM_THREADS','1')
from pathlib import Path
import numpy as np,json,csv,time,hashlib
from gabriel import Gabriel,Config
from observer_bounds import ObserverBounds
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results'
NAMES=['RacketSports','BasicMotions'];POLICIES=['random','recent','derivative'];MASKS=['random_half','middle_half'];ENCLOSURES=['basic','structured','hybrid'];RADII=[0.,.005,.01,.02,.05,.1]

def write_csv(name,rows):
    with (OUT/name).open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)

def run(name):
    start=time.perf_counter();d=np.load(OUT/f'external_{name}_model.npz');old=np.load(OUT/f'external_{name}_acquisition.npz')
    x=d['transformed_test'];n,N,m=x.shape;J=N*m//2;truth=x.reshape(n,-1);a=ObserverBounds(Gabriel(0,Config(input_dim=m),mode='trace_only'),d['trace_observer_coefficients'].T,N)
    score=a.point(x);error=float(np.max(abs(score-d['trace_observer_test_scores'])));assert error<1e-12
    reference=score.argmax(1);diff=np.stack([score[:,p]-score[:,q] for p,q in a.pp],axis=1);masks=old['masks']
    br=np.zeros((n,2,3,J+1,3,a.P,2));verdict=np.full((n,2,3,J+1,3),-1,int);query=np.full((n,2,3,J),-1,int);answer=np.zeros((n,2,3,J));selection=np.zeros((n,2,3,J));stops=[];noise=[];records=[]
    h=hashlib.sha256()
    for ar in [d['normalization_mean'],d['normalization_scale']]:h.update(ar.tobytes())
    calibration_id=name+':train-normalizer:'+h.hexdigest()+':0.1-second-event'
    for ms,maskname in enumerate(MASKS):
      for pi,policy in enumerate(POLICIES):
        lo=np.where(masks[:,ms],-1,truth).reshape(x.shape);hi=np.where(masks[:,ms],1,truth).reshape(x.shape);recorded=False
        for budget in range(J+1):
          res=a.analyze(lo,hi);bb=res['bounds'];v=a.verdicts(bb);br[:,ms,pi,budget]=bb;verdict[:,ms,pi,budget]=v
          assert np.all(bb[...,0]-1e-9<=diff[:,None]) and np.all(diff[:,None]<=bb[...,1]+1e-9)
          assert np.all((v<0)|(v==reference[:,None]))
          if budget>0:
            prev=br[:,ms,pi,budget-1]
            assert np.all(bb[...,0]>=prev[...,0]-1e-8) and np.all(bb[...,1]<=prev[...,1]+1e-8)
          if pi==2 and not recorded and v[0,2]>=0:
            record=a.record(lo[0],hi[0],calibration_id);assert a.verify_record(record,calibration_id)
            records.append(dict(dataset=name,mask=maskname,case=0,queries=budget,record=record));recorded=True
          if budget==J:break
          q=old['queries'][:,ms,pi,budget] if pi<2 else a.query(res,lo,hi)
          assert np.all(hi.reshape(n,-1)[np.arange(n),q]>lo.reshape(n,-1)[np.arange(n),q])
          c=res['contributions'].reshape(n,a.P,-1);selection[:,ms,pi,budget]=np.max(c.sum(-1)-np.take_along_axis(c,q[:,None,None],axis=2)[...,0],axis=1)
          values=truth[np.arange(n),q];query[:,ms,pi,budget]=q;answer[:,ms,pi,budget]=values
          lo.reshape(n,-1)[np.arange(n),q]=values;hi.reshape(n,-1)[np.arange(n),q]=values
          if budget%50==0:print(name,maskname,policy,budget,'/',J,'seconds',round(time.perf_counter()-start,1),flush=True)
        print(name,maskname,policy,'finished',round(time.perf_counter()-start,1),flush=True)
    for case in range(n):
      for ms,maskname in enumerate(MASKS):
       for pi,policy in enumerate(POLICIES):
        for en,enclosure in enumerate(ENCLOSURES):
          ids=np.flatnonzero(verdict[case,ms,pi,:,en]>=0);assert len(ids)>0
          stops.append(dict(dataset=name,case=case,mask=maskname,policy=policy,enclosure=enclosure,first_resolved_query=int(ids[0]),missing=J,full_prediction=int(reference[case]),label=int(d['test_labels'][case])))
    for rho in RADII:
      res=a.analyze(np.maximum(-1,x-rho),np.minimum(1,x+rho));v=a.verdicts(res['bounds'])
      assert np.all((v<0)|(v==reference[:,None]))
      for en,enclosure in enumerate(ENCLOSURES):noise.append(dict(dataset=name,radius=rho,enclosure=enclosure,cases=n,resolved=int(np.sum(v[:,en]>=0)),correct_label_resolved=int(np.sum((v[:,en]>=0)&(v[:,en]==d['test_labels'])))))
    np.savez_compressed(OUT/f'observer_{name}_acquisition.npz',masks=masks,queries=query,answers=answer,bounds=br,verdicts=verdict,selection_upper_radius=selection,model_hash=a.model_hash,reference=reference)
    (OUT/f'observer_{name}_records.json').write_text(json.dumps(records,indent=2))
    (OUT/f'observer_{name}_runtime.json').write_text(json.dumps(dict(dataset=name,elapsed_seconds=time.perf_counter()-start,audit_input_states=n*2*3*(J+1),range_sets=int(verdict.size),queries=int(query.size),frozen_score_error=error,model_hash=a.model_hash),indent=2))
    return stops,noise

def main():
    protocol=dict(date='2026-09-25',datasets=NAMES,fitted_model='existing frozen trace_observer from external_*_model.npz',refit=False,graph_seed=0,initialization='zero per complete finite record',masks='identical saved masks from ordered-head audit',policies=POLICIES,enclosures=ENCLOSURES,random_recent='identical saved query paths; do not depend on head',derivative_query='minimize maximum frozen interval-gradient radius after deleting one coordinate contribution',query_noise=0,query_cost=1,input_domain=[-1,1],noise_radii_normalized=RADII,decision_margin=1e-10,arithmetic='float64; checks at 1e-9, nesting at 1e-8; no outward rounding',scope='conditional complete-model winner, not true label or physical safety',data_reuse='development comparison on tasks previously examined, not independent replication',selection_rule='fixed before this observer acquisition run')
    (OUT/'observer_protocol.json').write_text(json.dumps(protocol,indent=2));stops=[];noise=[]
    for name in NAMES:
        ss,nn=run(name);stops+=ss;noise+=nn
        write_csv('observer_stopping.csv',stops);write_csv('observer_noise.csv',noise)
    print('Observer benchmark complete.',flush=True)
if __name__=='__main__':main()
