"""Five bounded local observers: grouped CV and exact vote stopping.

An architectural alternative, not a certificate for the old full-record head.
Five equal blocks and left-to-right acquisition are fixed in this script.
No tuning of block count or query order is performed on either test set.
"""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
from pathlib import Path
import numpy as np,json,csv,time
from benchmark_external import read_ts,normalizer,transform,feature_map,fit_ridge,folds,balanced_accuracy,PENALTIES
from gabriel import Gabriel,Config
from validated_observer import ValidatedObserver
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results';BLOCKS=5

def features(x):
    n,N,m=x.shape
    if N%BLOCKS:raise ValueError('equal blocks required')
    return feature_map(x.reshape(n*BLOCKS,N//BLOCKS,m),None,None,'trace_observer').reshape(n,BLOCKS,-1)

def vote_winner(scores):
    votes=scores.argmax(-1);count=np.eye(scores.shape[-1],dtype=int)[votes].sum(1)
    return count.argmax(1),votes,count

def stop_votes(votes,known,order,K):
    """Stop only under strict dominance, including conservative tie handling."""
    seen=known.copy();count=np.bincount(votes[seen],minlength=K);used=[]
    for b in list(order)+[-1]:
        remaining=int((~seen).sum());a=int(count.argmax())
        if all(a==k or count[a]>count[k]+remaining for k in range(K)):return a,used,remaining
        if b==-1:
            assert remaining==0
            return a,used,remaining # fully observed deterministic smallest-label tie
        if not seen[b]:seen[b]=True;count[votes[b]]+=1;used.append(int(b))
    raise AssertionError

def run(name,index):
    start=time.perf_counter();d=np.load(OUT/f'external_{name}_model.npz');x=d['train_inputs'];test=d['test_inputs'];y=d['train_labels'];yt=d['test_labels'];K=len(d['classes']);ff=d['folds'];cv=np.zeros((len(PENALTIES),5))
    for fold in range(5):
        norm=normalizer(x[ff!=fold]);fa=features(transform(x[ff!=fold],norm));fv=features(transform(x[ff==fold],norm))
        for pi,p in enumerate(PENALTIES):
            co=fit_ridge(fa.reshape(-1,fa.shape[-1]),np.repeat(y[ff!=fold],BLOCKS),K,p)
            pred,_,_=vote_winner(fv@co);cv[pi,fold]=balanced_accuracy(y[ff==fold],pred)
    perf=cv.mean(1);pi=int(np.flatnonzero(perf==perf.max())[-1]);fa=features(d['transformed_train']);ft=features(d['transformed_test']);co=fit_ridge(fa.reshape(-1,fa.shape[-1]),np.repeat(y,BLOCKS),K,PENALTIES[pi]);scores=ft@co;pred,votes,count=vote_winner(scores)
    # Validate every test block, including votes not read by an early policy.
    verifier=ValidatedObserver(Gabriel(0,Config(input_dim=x.shape[-1]),mode='trace_only'),co.T);validated=[]
    testblocks=d['transformed_test'].reshape(len(test),BLOCKS,x.shape[1]//BLOCKS,x.shape[2])
    for i in range(len(test)):
        row=[verifier.evaluate(block) for block in testblocks[i]]
        assert [r['winner'] for r in row]==votes[i].tolist();validated.append(row)
    old=np.load(OUT/f'observer_{name}_acquisition.npz');rows=[];paths=np.full((len(test),2,BLOCKS),-1,int)
    for i in range(len(test)):
      for ms,maskname in enumerate(['random_half','middle_half']):
        missing=old['masks'][i,ms].reshape(BLOCKS,-1).sum(1);known=missing==0
        winner,used,remaining=stop_votes(votes[i],known,np.arange(BLOCKS),K)
        assert winner==pred[i];paths[i,ms,:len(used)]=used
        rows.append(dict(dataset=name,case=i,mask=maskname,queries=int(missing[used].sum()),missing=int(missing.sum()),blocks_read=len(used),blocks_unread=remaining,full_prediction=int(pred[i]),label=int(yt[i])))
    summary=dict(dataset=name,blocks=BLOCKS,events_per_block=x.shape[1]//BLOCKS,penalty=float(PENALTIES[pi]),cv_balanced_accuracy=float(perf[pi]),correct=int((pred==yt).sum()),cases=len(test),balanced_accuracy=balanced_accuracy(yt,pred),validated_block_winners=len(test)*BLOCKS,precision_bits=100,seconds=time.perf_counter()-start,query_order='left to right; already complete blocks processed without queries',scope='new majority classifier, not old head preservation')
    for ms,mask in enumerate(['random_half','middle_half']):
        rr=[r for r in rows if r['mask']==mask];summary[mask]=dict(mean_queries=float(np.mean([r['queries'] for r in rr])),mean_fraction=float(np.mean([r['queries']/r['missing'] for r in rr])),early_cases=sum(r['queries']<r['missing'] for r in rr))
    np.savez_compressed(OUT/f'blocks_{name}.npz',coefficients=co,cv_scores=cv,penalties=PENALTIES,test_scores=scores,votes=votes,prediction=pred,query_block_paths=paths,masks=old['masks'])
    (OUT/f'blocks_{name}_validated.json').write_text(json.dumps(validated,separators=(',',':')))
    print(summary,flush=True);return rows,summary

def main():
    protocol=dict(blocks=BLOCKS,selection='fixed before executing this alternative; no search over block counts',training='block labels inherit record label; 5 folds grouped by record; fold-specific input normalization; ridge selected by record-level majority balanced accuracy',decision='strict observed vote dominance over every rival plus all unread votes; deterministic lowest-label tie only after full observation',scope='development on previously inspected external datasets; fresh independent evaluation still needed',arithmetic='all test block winners validated with 100-bit Arb; votes and stopping use exact integers')
    (OUT/'blocks_protocol.json').write_text(json.dumps(protocol,indent=2));rows=[];summary=[]
    for index,name in enumerate(['RacketSports','BasicMotions']):
        rr,ss=run(name,index);rows+=rr;summary.append(ss)
    with (OUT/'blocks_stopping.csv').open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=rows[0].keys());w.writeheader();w.writerows(rows)
    (OUT/'blocks_summary.json').write_text(json.dumps(summary,indent=2))
if __name__=='__main__':main()
