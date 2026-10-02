"""Frozen external-data protocol: complete-input classification and archive retrieval.

No test labels enter fitting, hyperparameter selection, masks or query selection.
The original UEA train/test splits are retained; missingness is imposed here.
"""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','1');os.environ.setdefault('OMP_NUM_THREADS','1')
from pathlib import Path
import numpy as np,json,csv,time,copy
from scalable_observation import *
from gabriel import Gabriel,Config
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results';DATA=ROOT/'data'
NAMES=['RacketSports','BasicMotions'];MODELS=['raw_ridge','mean_memory','ordered_memory','trace_observer']
PENALTIES=np.array([1e-4,1e-3,.01,.1,1.,10.,100.,1000.])
POLICIES=['random','recent','coefficient'];MASKS=['random_half','middle_half']

def read_ts(path):
    xs=[];ys=[];started=False
    for line in path.read_text().splitlines():
        if line.strip().lower()=='@data':started=True;continue
        if not started or not line.strip() or line.startswith('#'):continue
        pp=line.strip().split(':');xs.append(np.array([[float(v) for v in ch.split(',')] for ch in pp[:-1]]).T);ys.append(pp[-1])
    x=np.array(xs);assert np.isfinite(x).all();return x,np.array(ys)

def normalizer(x):return x.mean(axis=(0,1)),np.maximum(x.std(axis=(0,1)),1e-12)
def transform(x,norm):return np.tanh((x-norm[0])/(3*norm[1]))
def feature_map(x,h,taus,mode):
    if mode=='raw_ridge':return np.c_[np.ones(len(x)),x.reshape(len(x),-1)]
    if mode in ['mean_memory','ordered_memory']:return memory_features(x,h,taus,mode=='ordered_memory')
    if mode=='trace_observer':
        g=Gabriel(0,Config(input_dim=x.shape[2]),mode='trace_only');rows=[]
        for seq in x:
            g.reset()
            for u in seq:g.step(u)
            rows.append(np.r_[1,g.features(seq[-1],joint=True)])
        return np.array(rows)
    raise ValueError(mode)
def fit_ridge(f,y,nclasses,penalty):
    mu=f[:,1:].mean(0);sd=f[:,1:].std(0);sd=np.where(sd<1e-12,1.,sd);z=(f[:,1:]-mu)/sd;target=np.eye(nclasses)[y];ym=target.mean(0);t=target-ym
    if z.shape[1]<=len(z):w=np.linalg.solve(z.T@z+len(z)*penalty*np.eye(z.shape[1]),z.T@t)
    else:w=z.T@np.linalg.solve(z@z.T+len(z)*penalty*np.eye(len(z)),t)
    c=np.vstack([ym-mu@(w/sd[:,None]),w/sd[:,None]])
    return c

def folds(y,seed):
    rng=np.random.default_rng(seed);f=np.empty(len(y),int)
    for cl in np.unique(y):
        idx=np.flatnonzero(y==cl);rng.shuffle(idx);f[idx]=np.arange(len(idx))%5
    return f

def balanced_accuracy(y,pred):return float(np.mean([np.mean(pred[y==k]==k) for k in np.unique(y)]))

def train_and_evaluate(name,index):
    x,y0=read_ts(DATA/f'{name}_TRAIN.ts');test,yt0=read_ts(DATA/f'{name}_TEST.ts');classes=np.unique(y0);y=np.searchsorted(classes,y0);yt=np.searchsorted(classes,yt0);nc=len(classes);h=np.full(x.shape[1],.1);taus=h.sum()*np.array([1/16,1/4,1,4]);ff=folds(y,93400+index)
    scores=np.zeros((4,len(PENALTIES),5));coeffs={};rows=[]
    for fold in range(5):
        norm=normalizer(x[ff!=fold]);a=transform(x[ff!=fold],norm);v=transform(x[ff==fold],norm)
        for mi,mode in enumerate(MODELS):
            fa=feature_map(a,h,taus,mode);fv=feature_map(v,h,taus,mode)
            for pi,penalty in enumerate(PENALTIES):
                coef=fit_ridge(fa,y[ff!=fold],nc,penalty);scores[mi,pi,fold]=balanced_accuracy(y[ff==fold],np.argmax(fv@coef,axis=1))
    norm=normalizer(x);xn=transform(x,norm);tn=transform(test,norm);saved=dict(train_inputs=x,test_inputs=test,train_labels=y,test_labels=yt,classes=classes,normalization_mean=norm[0],normalization_scale=norm[1],transformed_train=xn,transformed_test=tn,folds=ff,penalties=PENALTIES,cv_scores=scores,taus=taus,durations=h)
    for mi,mode in enumerate(MODELS):
        # Favor stronger regularization in exact CV ties.
        perf=scores[mi].mean(1);pi=int(np.flatnonzero(perf==perf.max())[-1]);fa=feature_map(xn,h,taus,mode);ft=feature_map(tn,h,taus,mode);coef=fit_ridge(fa,y,nc,PENALTIES[pi]);pred=np.argmax(ft@coef,axis=1);coeffs[mode]=coef
        saved[mode+'_coefficients']=coef;saved[mode+'_test_scores']=ft@coef
        rows.append(dict(dataset=name,model=mode,features=fa.shape[1]-1,penalty=PENALTIES[pi],cv_balanced_accuracy=float(perf[pi]),test_accuracy=float(np.mean(pred==yt)),test_balanced_accuracy=balanced_accuracy(yt,pred),correct=int(np.sum(pred==yt)),test_cases=len(yt)))
    dist=((tn.reshape(len(tn),1,-1)-xn.reshape(1,len(xn),-1))**2).sum(-1);pred=y[np.argmin(dist,axis=1)];saved['nearest_neighbor_test_prediction']=pred
    rows.append(dict(dataset=name,model='euclidean_1nn',features=xn.shape[1]*xn.shape[2],penalty='',cv_balanced_accuracy='',test_accuracy=float(np.mean(pred==yt)),test_balanced_accuracy=balanced_accuracy(yt,pred),correct=int(np.sum(pred==yt)),test_cases=len(yt)))
    c,b,Q=compile_readouts(coeffs['ordered_memory'].T,h,taus,x.shape[2]);poly=evaluate_polynomial(c,b,Q,tn.reshape(len(tn),-1));assert np.max(np.abs(poly-saved['ordered_memory_test_scores']))<1e-9
    saved['polynomial_constant']=c;saved['polynomial_linear']=b;saved['polynomial_quadratic']=Q
    saved['exact_train_test_duplicates']=np.array(sum(np.any(np.all(x==t,axis=(1,2))) for t in test))
    np.savez_compressed(OUT/f'external_{name}_model.npz',**saved)
    print(name,'model results',rows,flush=True)
    return rows

def acquire_dataset(name,index):
    start=time.perf_counter();d=np.load(OUT/f'external_{name}_model.npz');x=d['transformed_test'];labels=d['test_labels'];nc=len(d['classes']);cp,bp,Qp=class_pairs(d['polynomial_constant'],d['polynomial_linear'],d['polynomial_quadratic']);reference=np.argmax(d['ordered_memory_test_scores'],axis=1);n=len(x);size=x[0].size;J=size//2
    all_masks=np.zeros((n,2,size),bool);qout=np.full((n,2,3,J),-1,int);answer=np.zeros((n,2,3,J));br=np.zeros((n,2,3,J+1,len(cp),2));verdict=np.full((n,2,3,J+1),-1,int);rows=[]
    for case,seq in enumerate(x):
      truth=seq.ravel()
      for ms,maskname in enumerate(MASKS):
        mask=np.zeros(size,bool)
        if maskname=='random_half':mask[np.random.default_rng(93500+1000*index+case).choice(size,J,replace=False)]=True
        else:
            start_event=seq.shape[0]//4;mask.reshape(seq.shape)[start_event:start_event+seq.shape[0]//2]=True
        assert mask.sum()==J;all_masks[case,ms]=mask;lo=np.where(mask,-1.,truth);hi=np.where(mask,1.,truth);base=CoefficientAudit(cp,bp,Qp,lo,hi)
        true_diff=np.array([d['ordered_memory_test_scores'][case,a]-d['ordered_memory_test_scores'][case,b] for a,b in pairs(nc)])
        for pi,policy in enumerate(POLICIES):
          audit=copy.deepcopy(base);rng=np.random.default_rng(95500+1000*index+case+10000*ms)
          for budget in range(J+1):
            bounds=audit.bounds();v=class_verdict(bounds,nc);br[case,ms,pi,budget]=bounds;verdict[case,ms,pi,budget]=v
            assert np.all(bounds[:,0]-1e-9<=true_diff) and np.all(true_diff<=bounds[:,1]+1e-9)
            assert v<0 or v==reference[case]
            if budget in sorted(set([0,J//4,J//2,3*J//4,J])):
              rows.append(dict(dataset=name,case=case,mask=maskname,policy=policy,queries=budget,missing=J,resolved=int(v>=0),wrong_model_claim=int(v>=0 and v!=reference[case]),label_correct_if_resolved=int(v>=0 and v==labels[case]),full_prediction=int(reference[case]),label=int(labels[case]),max_width=float(np.max(bounds[:,1]-bounds[:,0]))))
            if budget==J:break
            q=audit.choose(policy,rng)
            # Only this line retrieves the selected retained record.
            value=float(truth[q]);qout[case,ms,pi,budget]=q;answer[case,ms,pi,budget]=value;audit.acquire(q,value)
      if case%20==19:print(name,'acquisition cases',case+1,'elapsed',round(time.perf_counter()-start,1),flush=True)
    np.savez_compressed(OUT/f'external_{name}_acquisition.npz',masks=all_masks,queries=qout,answers=answer,bounds=br,verdicts=verdict)
    stops=[]
    for case in range(n):
      for ms,maskname in enumerate(MASKS):
       for pi,policy in enumerate(POLICIES):
        resolved=np.flatnonzero(verdict[case,ms,pi]>=0);assert len(resolved)>0
        stops.append(dict(dataset=name,case=case,mask=maskname,policy=policy,first_resolved_query=int(resolved[0]),missing=J,full_prediction=int(reference[case]),label=int(labels[case])))
    result=dict(dataset=name,cases=n,missing=J,total_audits=n*2*3*(J+1),query_steps=n*2*3*J,elapsed_seconds=time.perf_counter()-start)
    (OUT/f'external_{name}_runtime.json').write_text(json.dumps(result,indent=2));print(result,flush=True)
    return rows,stops

def write_csv(name,rows):
    with (OUT/name).open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)

def main():
    protocol=dict(datasets=NAMES,selection='Chosen for genuine multichannel measurements, public fixed splits and manageable lengths before inspecting test performance.',training='5 stratified folds on original training set only; fold seed 93400+dataset index; all normalization fitted within fold',normalization='per-channel training mean and SD; tanh((x-mu)/(3*sd))',time='0.1 s per sample; piecewise constant model interpolation',taus_relative_to_record=[1/16,1/4,1,4],models=MODELS+['euclidean_1nn'],penalties=PENALTIES.tolist(),tie='strongest ridge penalty among identical mean CV balanced accuracies',initial_state='zero at each record',acquisition_model='ordered_memory, fixed before test acquisition',policies=POLICIES,masks=MASKS,query_cost=1,query_noise=0,decision_margin=1e-10,scope='model-decision preservation; external-label accuracy evaluated separately',no_test_refit=True)
    (OUT/'external_protocol.json').write_text(json.dumps(protocol,indent=2));models=[];rows=[];stops=[]
    for index,name in enumerate(NAMES):models+=train_and_evaluate(name,index)
    write_csv('external_classification.csv',models)
    for index,name in enumerate(NAMES):rr,ss=acquire_dataset(name,index);rows+=rr;stops+=ss
    write_csv('external_acquisition.csv',rows);write_csv('external_stopping.csv',stops)
if __name__=='__main__':main()
