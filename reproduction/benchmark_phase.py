"""Execute the saved phase-memory protocol without fitting on test labels."""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
os.environ.setdefault('OMP_NUM_THREADS','1')
from pathlib import Path
import json,hashlib,csv,time
import numpy as np
from benchmark_external import read_ts,normalizer,transform,folds,balanced_accuracy,fit_ridge,feature_map,PENALTIES
from phase_memory import features,compile_head,acquire,parameters

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results'
HASH='e2a4471c375fd7324b84c128eb799c8c9f2bfa129ecddd0200a0f1831cffceeb'
NAMES=['RacketSports','BasicMotions','NATOPS','Epilepsy']
MODELS=['real_bank','phase_bank','real_plus_trace','phase_plus_trace','trace_observer','real_3','phase_3','real_5','phase_5','real_7','phase_7']

def representations(x,h):
    f={k:features(x,h,k.startswith('phase'),int(k.rsplit('_',1)[-1]) if k[-1].isdigit() else 16)
       for k in MODELS if k not in ('trace_observer','real_plus_trace','phase_plus_trace')}
    f['trace_observer']=feature_map(x,h,None,'trace_observer')
    for k in ('real','phase'):f[k+'_plus_trace']=np.c_[f['trace_observer'],f[k+'_bank'][:,1:]]
    return f

def write_csv(path,rows):
    with path.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)

def main():
    assert hashlib.sha256((OUT/'phase_protocol.json').read_bytes()).hexdigest()==HASH
    rows=[];stops=[];start=time.perf_counter()
    for di,name in enumerate(NAMES):
        x,yy=read_ts(ROOT/'data'/f'{name}_TRAIN.ts');xt,yyt=read_ts(ROOT/'data'/f'{name}_TEST.ts')
        classes=np.unique(yy);y=np.searchsorted(classes,yy);yt=np.searchsorted(classes,yyt);K=len(classes)
        assert set(yyt)<=set(classes)
        h=np.full(x.shape[1],1/x.shape[1]);ff=folds(y,93400+di);cv=np.zeros((len(MODELS),len(PENALTIES),5))
        for fold in range(5):
            norm=normalizer(x[ff!=fold]);fa=representations(transform(x[ff!=fold],norm),h);fv=representations(transform(x[ff==fold],norm),h)
            for mi,mode in enumerate(MODELS):
                for pi,p in enumerate(PENALTIES):
                    co=fit_ridge(fa[mode],y[ff!=fold],K,p)
                    cv[mi,pi,fold]=balanced_accuracy(y[ff==fold],(fv[mode]@co).argmax(1))
        norm=normalizer(x);xn=transform(x,norm);tn=transform(xt,norm);fa=representations(xn,h);ft=representations(tn,h)
        old=np.load(OUT/f'prefix_{name}.npz');assert np.array_equal(old['folds'],ff) and np.array_equal(old['transformed_test'],tn)
        saved=dict(transformed_train=xn,transformed_test=tn,train_labels=y,test_labels=yt,classes=classes,durations=h,folds=ff,cv_scores=cv,normalization_mean=norm[0],normalization_scale=norm[1],penalties=PENALTIES,masks=old['masks'][:,:2],protocol_sha256=np.array(HASH))
        local=[]
        for mi,mode in enumerate(MODELS):
            perf=cv[mi].mean(1);pi=int(np.flatnonzero(perf==perf.max())[-1]);co=fit_ridge(fa[mode],y,K,PENALTIES[pi]);scores=ft[mode]@co;pred=scores.argmax(1)
            saved[mode+'_coefficients']=co;saved[mode+'_features_train']=fa[mode];saved[mode+'_features_test']=ft[mode];saved[mode+'_scores']=scores;saved[mode+'_prediction']=pred
            local.append(dict(dataset=name,model=mode,features=fa[mode].shape[1]-1,penalty=float(PENALTIES[pi]),cv_balanced_accuracy=float(perf[pi]),correct=int((pred==yt).sum()),cases=len(yt),balanced_accuracy=balanced_accuracy(yt,pred)))
        assert np.array_equal(saved['trace_observer_prediction'],old['full_observer_prediction'])
        assert np.max(abs(saved['trace_observer_coefficients']-old['full_observer_coefficients'][0]))<1e-10
        for row in local:
            mode=row['model'];control=mode.replace('phase','real') if mode.startswith('phase') else 'trace_observer'
            a=saved[mode+'_prediction']==yt;b=saved[control+'_prediction']==yt
            row.update(control=control,gained=int((a&~b).sum()),lost=int((~a&b).sum()))
        rows+=local
        for mode in ('real_bank','phase_bank'):
            b,c=compile_head(saved[mode+'_coefficients'],h,x.shape[2],mode=='phase_bank')
            assert np.max(abs(b+tn.reshape(len(tn),-1)@c-saved[mode+'_scores']))<1e-9
            saved[mode+'_intercept']=b;saved[mode+'_linear_coefficients']=c
            paths=np.full((len(tn),2,2,tn[0].size),-1,np.int32)
            for i,seq in enumerate(tn):
              for ms,maskname in enumerate(['random_half','middle_half']):
                mask=saved['masks'][i,ms]
                for pol,policy in enumerate(['coefficient','recent']):
                    rr=acquire(seq.ravel(),mask,b,c,policy);q=rr['queries'];paths[i,ms,pol,:len(q)]=q
                    assert rr['winner']==saved[mode+'_prediction'][i]
                    stops.append(dict(dataset=name,model=mode,case=i,mask=maskname,policy=policy,queries=len(q),missing=int(mask.sum()),fraction=len(q)/mask.sum(),prediction=rr['winner'],label=int(yt[i]),strict=rr['strict']))
            saved[mode+'_query_paths']=paths
        np.savez_compressed(OUT/f'phase_{name}.npz',**saved)
        write_csv(OUT/'phase_classification.csv',rows);write_csv(OUT/'phase_stopping.csv',stops)
        print(name,[(z['model'],z['correct'],round(z['cv_balanced_accuracy'],4)) for z in local], 'seconds',round(time.perf_counter()-start,1),flush=True)
    (OUT/'phase_runtime.json').write_text(json.dumps(dict(seconds=time.perf_counter()-start,protocol_sha256=HASH,models=len(MODELS),datasets=len(NAMES),new_fits=4*len(MODELS),fold_fits=4*len(MODELS)*5*len(PENALTIES),acquisition_paths=len(stops)),indent=2))

if __name__=='__main__':main()
