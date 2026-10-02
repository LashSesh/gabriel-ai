"""Mean-only control with the same five blocks, CV and vote stopping rule."""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
import numpy as np,json,csv
from flint import arb,ctx
from benchmark_blocks import BLOCKS,OUT,stop_votes,vote_winner
from benchmark_external import normalizer,transform,fit_ridge,balanced_accuracy,PENALTIES

def features(x):
    z=x.reshape(len(x),BLOCKS,x.shape[1]//BLOCKS,x.shape[2]).mean(2)
    return np.concatenate([np.ones(z.shape[:-1]+(1,)),z],axis=2)

def main():
    summaries=[];rows=[]
    for name in ['RacketSports','BasicMotions']:
        d=np.load(OUT/f'external_{name}_model.npz');x=d['train_inputs'];y=d['train_labels'];yt=d['test_labels'];K=len(d['classes']);ff=d['folds'];cv=np.zeros((len(PENALTIES),5))
        for fold in range(5):
            norm=normalizer(x[ff!=fold]);fa=features(transform(x[ff!=fold],norm));fv=features(transform(x[ff==fold],norm))
            for pi,p in enumerate(PENALTIES):
                co=fit_ridge(fa.reshape(-1,fa.shape[-1]),np.repeat(y[ff!=fold],BLOCKS),K,p)
                pred,_,_=vote_winner(fv@co);cv[pi,fold]=balanced_accuracy(y[ff==fold],pred)
        perf=cv.mean(1);pi=int(np.flatnonzero(perf==perf.max())[-1]);fa=features(d['transformed_train']);ft=features(d['transformed_test']);co=fit_ridge(fa.reshape(-1,fa.shape[-1]),np.repeat(y,BLOCKS),K,PENALTIES[pi]);pred,votes,_=vote_winner(ft@co)
        # Independent validated linear mean calculation from exact stored inputs.
        ctx.prec=100;bb=d['transformed_test'].reshape(len(yt),BLOCKS,x.shape[1]//BLOCKS,x.shape[2]);validation=[]
        for i in range(len(yt)):
            for b in range(BLOCKS):
                f=[arb(1)]+[sum((arb(float(v)) for v in bb[i,b,:,j]),arb(0))/bb.shape[2] for j in range(bb.shape[3])]
                ss=[sum((arb(float(w))*v for w,v in zip(row,f)),arb(0)) for row in co.T]
                w=int(votes[i,b]);assert all(w==j or ss[w]-ss[j]>0 for j in range(K))
                validation.append(dict(case=i,block=b,winner=w,bounds=[[[str(int(z)) for z in s.lower().man_exp()],[str(int(z)) for z in s.upper().man_exp()]] for s in ss]))
        old=np.load(OUT/f'observer_{name}_acquisition.npz');local=[]
        for i in range(len(yt)):
          for ms,mask in enumerate(['random_half','middle_half']):
            missing=old['masks'][i,ms].reshape(BLOCKS,-1).sum(1);winner,used,remaining=stop_votes(votes[i],missing==0,np.arange(BLOCKS),K);assert winner==pred[i]
            local.append(dict(dataset=name,case=i,mask=mask,queries=int(missing[used].sum()),missing=int(missing.sum()),prediction=int(pred[i]),label=int(yt[i])))
        summary=dict(dataset=name,model='block_mean_vote',correct=int((pred==yt).sum()),cases=len(yt),penalty=float(PENALTIES[pi]),cv_balanced_accuracy=float(perf[pi]),validated_votes=len(yt)*BLOCKS)
        for mask in ['random_half','middle_half']:
            rr=[r for r in local if r['mask']==mask];summary[mask]=dict(mean_queries=float(np.mean([r['queries'] for r in rr])),mean_fraction=float(np.mean([r['queries']/r['missing'] for r in rr])))
        summaries.append(summary);rows+=local
        np.savez_compressed(OUT/f'block_mean_{name}.npz',coefficients=co,cv_scores=cv,prediction=pred,votes=votes)
        (OUT/f'block_mean_{name}_validated.json').write_text(json.dumps(validation,separators=(',',':')));print(summary,flush=True)
    (OUT/'block_mean_summary.json').write_text(json.dumps(summaries,indent=2))
    with (OUT/'block_mean_stopping.csv').open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=rows[0].keys());w.writeheader();w.writerows(rows)
if __name__=='__main__':main()
