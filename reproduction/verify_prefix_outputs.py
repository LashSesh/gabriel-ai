"""Replay final fits, decisions and dependency-restricted acquisition paths."""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
from pathlib import Path
from fractions import Fraction
import numpy as np,json,csv,hashlib
from benchmark_external import read_ts,normalizer,transform,folds,PENALTIES
from prefix_observer import MODELS,representations,fit_heads,predict,acquire
from benchmark_prefix import mask_array,PROTOCOL_HASH
from validated_prefix import validate_record
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results'

def exact(z):
    a,e=map(int,z)
    return Fraction(a*2**e) if e>=0 else Fraction(a,2**(-e))

def main():
    assert hashlib.sha256((OUT/'prefix_protocol.json').read_bytes()).hexdigest()==PROTOCOL_HASH
    max_co=0.;max_score=0.;points=0;stop_count=0;replayed=0;models=[]
    stops=list(csv.DictReader((OUT/'prefix_stopping.csv').open()))
    for index,name in enumerate(['RacketSports','BasicMotions','NATOPS','Epilepsy']):
        d=np.load(OUT/f'prefix_{name}.npz');x,yy=read_ts(ROOT/'data'/f'{name}_TRAIN.ts');xt,yyt=read_ts(ROOT/'data'/f'{name}_TEST.ts')
        classes=np.unique(yy);y=np.searchsorted(classes,yy);yt=np.searchsorted(classes,yyt);K=len(classes)
        assert np.array_equal(d['test_labels'],yt) and np.array_equal(d['folds'],folds(y,93400+index))
        xn=transform(x,normalizer(x));tn=transform(xt,normalizer(x))
        assert np.array_equal(xn,d['transformed_train']) and np.array_equal(tn,d['transformed_test'])
        assert np.array_equal(d['masks'],mask_array(name,index,tn))
        fa=representations(xn);ft=representations(tn);coeff={}
        for mi,model in enumerate(MODELS):
            perf=d['cv_scores'][mi].mean(1);pi=np.flatnonzero(perf==perf.max())[-1]
            co=fit_heads(fa[model],y,K,PENALTIES[pi],model);coeff[model]=d[model+'_coefficients']
            err=float(abs(co-coeff[model]).max());max_co=max(max_co,err);assert err<1e-9
            pr,v,ss=predict(ft[model],coeff[model]);err=float(abs(ss-d[model+'_scores']).max());max_score=max(max_score,err);assert err<1e-10
            assert np.array_equal(v,d[model+'_votes']) and np.array_equal(pr,d[model+'_prediction'])
            models.append(dict(dataset=name,model=model,correct=int((pr==yt).sum())))
        validated=json.loads((OUT/f'prefix_{name}_validated.json').read_text())
        for i,record in enumerate(validated):
            for model in MODELS:
                for b,r in enumerate(record['models'][model]):
                    win=int(r['winner']);assert win==d[model+'_votes'][i,b]
                    intervals=[tuple(map(exact,z)) for z in r['bounds']]
                    assert all(lo<=hi for lo,hi in intervals)
                    assert all(k==win or intervals[win][0]>hi for k,(lo,hi) in enumerate(intervals));points+=1
        for row in [r for r in stops if r['dataset']==name]:
            model=row['model'];i=int(row['case']);ms=['random_half','middle_half','stream_all'].index(row['mask']);rule=['strict','tie_aware'].index(row['rule']);mask=d['masks'][i,ms]
            path=d[model+'_query_paths'][i,ms,rule];path=path[path>=0]
            assert len(path)==len(np.unique(path)) and np.all(mask[path]) and len(path)==int(row['queries'])
            if model=='full_observer':expected=np.flatnonzero(mask)
            else:
                rr=acquire(d[model+'_votes'][i],mask,d['checkpoints'],tn.shape[-1],K,model,bool(rule));expected=rr['queries']
                assert rr['winner']==int(row['prediction']) and rr['remaining']==int(row['unread_votes'])
                # No exposed vote may depend on an unread coordinate.
                left=mask.copy();left[path]=False
                for b in np.flatnonzero(rr['seen']):
                    a=0 if model!='reset_blocks' or b==0 else d['checkpoints'][b-1]
                    assert not left[a*tn.shape[-1]:d['checkpoints'][b]*tn.shape[-1]].any()
            assert np.array_equal(path,expected)
            assert int(row['prediction'])==d[model+'_prediction'][i] and int(row['label'])==yt[i];stop_count+=1
        for i in [0,len(tn)-1]:
            ref=validate_record(tn[i],d['checkpoints'],coeff,160)
            for model in MODELS:
                for got,old in zip(ref[model],validated[i]['models'][model]):
                    assert got['winner']==old['winner']
                    for newbounds,oldbounds in zip(got['bounds'],old['bounds']):
                        a,b=map(exact,oldbounds);c,e=map(exact,newbounds);assert a<=c<=e<=b
                    replayed+=1
    ans=dict(validated_point_winners=points,stopping_records=stop_count,replayed_point_winners_160bit=replayed,max_coefficient_error=max_co,max_score_error=max_score,protocol_sha256=PROTOCOL_HASH,final_fits_replayed=20,cv_selection_replayed=True,cv_training_rerun_in_verifier=False)
    (OUT/'prefix_verification.json').write_text(json.dumps(ans,indent=2));print(ans)
if __name__=='__main__':main()

