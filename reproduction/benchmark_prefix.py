"""Execute the saved, hashed prefix protocol without modifying it."""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
os.environ.setdefault('OMP_NUM_THREADS','1')
from pathlib import Path
import numpy as np,json,csv,time,hashlib
from benchmark_external import read_ts,normalizer,transform,folds,balanced_accuracy,PENALTIES
from prefix_observer import MODELS,checkpoints,representations,fit_heads,predict,acquire
from validated_prefix import validate_record
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results';DATA=ROOT/'data'
PROTOCOL_HASH='21eb0411b51766b26291972de8f9220a186dfc0f4ede150b72676dabfb9278ee'

def mask_array(name,index,xt):
    n,N,m=xt.shape;S=N*m;ans=np.ones((n,3,S),bool)
    if index<2:ans[:,:2]=np.load(OUT/f'observer_{name}_acquisition.npz')['masks']
    else:
        ans[:,:2]=False
        for i in range(n):
            ids=np.random.default_rng(93500+1000*index+i).choice(S,S//2,replace=False)
            ans[i,0,ids]=True
            ans[i,1].reshape(N,m)[N//4:N//4+N//2]=True
    return ans

def run(name,index):
    begin=time.perf_counter();x,yy=read_ts(DATA/f'{name}_TRAIN.ts');xt,yyt=read_ts(DATA/f'{name}_TEST.ts')
    classes=np.unique(yy);y=np.searchsorted(classes,yy);yt=np.searchsorted(classes,yyt)
    assert set(yyt)<=set(classes);K=len(classes);cuts=checkpoints(x.shape[1]);ff=folds(y,93400+index)
    cv=np.zeros((len(MODELS),len(PENALTIES),5))
    for fold in range(5):
        norm=normalizer(x[ff!=fold]);fa=representations(transform(x[ff!=fold],norm));fv=representations(transform(x[ff==fold],norm))
        for mi,model in enumerate(MODELS):
            for pi,p in enumerate(PENALTIES):
                co=fit_heads(fa[model],y[ff!=fold],K,p,model)
                pr,_,_=predict(fv[model],co);cv[mi,pi,fold]=balanced_accuracy(y[ff==fold],pr)
    norm=normalizer(x);xn=transform(x,norm);tn=transform(xt,norm)
    fa=representations(xn);ft=representations(tn);coeffs={};rows=[];saved={}
    for mi,model in enumerate(MODELS):
        perf=cv[mi].mean(1);pi=int(np.flatnonzero(perf==perf.max())[-1])
        co=fit_heads(fa[model],y,K,PENALTIES[pi],model);pred,votes,scores=predict(ft[model],co);coeffs[model]=co
        for key,val in [('coefficients',co),('prediction',pred),('votes',votes),('scores',scores)]:saved[model+'_'+key]=val
        rows.append(dict(dataset=name,model=model,penalty=float(PENALTIES[pi]),cv_balanced_accuracy=float(perf[pi]),correct=int((pred==yt).sum()),cases=len(yt),accuracy=float((pred==yt).mean()),balanced_accuracy=balanced_accuracy(yt,pred),heads=5 if model.startswith('stage_') else 1,features=fa[model].shape[-1]-1))
    full=saved['full_observer_prediction']
    for row in rows:
        pred=saved[row['model']+'_prediction'];row.update(changed=int((pred!=full).sum()),lost=int(((full==yt)&(pred!=yt)).sum()),gained=int(((full!=yt)&(pred==yt)).sum()))
    # Old models must reproduce the original selected heads and predictions.
    if index<2:
        old=np.load(OUT/f'external_{name}_model.npz');blocks=np.load(OUT/f'blocks_{name}.npz')
        assert np.array_equal(full,old['trace_observer_test_scores'].argmax(1))
        assert np.allclose(coeffs['full_observer'][0],old['trace_observer_coefficients'],rtol=0,atol=1e-10)
        assert np.array_equal(saved['reset_blocks_prediction'],blocks['prediction'])
    print(name,'fitted',[(r['model'],r['correct'],round(r['cv_balanced_accuracy'],4)) for r in rows],flush=True)
    validated=[];retries=0
    for i,u in enumerate(tn):
        for precision in [100,160,256]:
            v=validate_record(u,cuts,coeffs,precision)
            if all(z['winner']>=0 for rr in v.values() for z in rr):break
            retries+=1
        if any(z['winner']<0 for rr in v.values() for z in rr):raise RuntimeError('unresolved point winner: no early certification')
        for model in MODELS:assert [z['winner'] for z in v[model]]==saved[model+'_votes'][i].tolist()
        validated.append(dict(precision_bits=precision,models=v))
        if (i+1)%40==0:print(name,'validated',i+1,'seconds',round(time.perf_counter()-begin,1),flush=True)
    masks=mask_array(name,index,tn);stops=[]
    for model in MODELS:
        paths=np.full((len(tn),3,2,tn[0].size),-1,np.int32)
        for i in range(len(tn)):
            for ms,maskname in enumerate(['random_half','middle_half','stream_all']):
                for rule,tie in enumerate([False,True]):
                    mask=masks[i,ms]
                    if model=='full_observer':
                        rr=dict(winner=int(full[i]),queries=np.flatnonzero(mask),remaining=0,seen=np.ones(1,bool))
                    else:rr=acquire(saved[model+'_votes'][i],mask,cuts,x.shape[2],K,model,tie)
                    assert rr['winner']==saved[model+'_prediction'][i]
                    q=rr['queries'];paths[i,ms,rule,:len(q)]=q
                    stops.append(dict(dataset=name,model=model,case=i,mask=maskname,rule='tie_aware' if tie else 'strict',queries=len(q),missing=int(mask.sum()),fraction=len(q)/mask.sum(),unread_votes=rr['remaining'],exposed_votes=int(rr['seen'].sum()),prediction=rr['winner'],label=int(yt[i])))
        saved[model+'_query_paths']=paths
    np.savez_compressed(OUT/f'prefix_{name}.npz',**saved,classes=classes,train_labels=y,test_labels=yt,transformed_train=xn,transformed_test=tn,folds=ff,normalization_mean=norm[0],normalization_scale=norm[1],checkpoints=cuts,cv_scores=cv,penalties=PENALTIES,masks=masks)
    (OUT/f'prefix_{name}_validated.json').write_text(json.dumps(validated,separators=(',',':')))
    (OUT/f'prefix_{name}_runtime.json').write_text(json.dumps(dict(seconds=time.perf_counter()-begin,point_winners=len(tn)*21,precision_retries=retries,protocol_sha256=PROTOCOL_HASH),indent=2))
    return rows,stops

def main():
    assert hashlib.sha256((OUT/'prefix_protocol.json').read_bytes()).hexdigest()==PROTOCOL_HASH
    rows=[];stops=[]
    for index,name in enumerate(['RacketSports','BasicMotions','NATOPS','Epilepsy']):
        rr,ss=run(name,index);rows+=rr;stops+=ss
        # Checkpoints retain completed datasets if a later execution is interrupted.
        for fn,data in [('prefix_models.csv',rows),('prefix_stopping.csv',stops)]:
            with (OUT/fn).open('w',newline='') as f:
                w=csv.DictWriter(f,fieldnames=data[0]);w.writeheader();w.writerows(data)
if __name__=='__main__':main()
