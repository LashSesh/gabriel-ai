"""Reload dyadic certificates, witness membership and all block stopping costs."""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
from pathlib import Path
import numpy as np,json,csv
from flint import arb,ctx
from gabriel import Gabriel,Config
from validated_observer import ValidatedObserver
from benchmark_blocks import stop_votes
OUT=Path(__file__).resolve().parents[1]/'results'

def decode(record):
    bounds=[(arb(tuple(map(int,a))),arb(tuple(map(int,b)))) for a,b in record['bounds']]
    w=record['winner'];assert 0<=w<len(bounds)
    assert all(a<=b for a,b in bounds)
    assert all(w==j or bounds[w][0]>bounds[j][1] for j in range(len(bounds)))
    return bounds

def main():
    ctx.prec=120;witnesses=votes=stops=replay=0
    for name in ['RacketSports','BasicMotions']:
        d=np.load(OUT/f'external_{name}_model.npz');p=np.load(OUT/f'relaxed_{name}_acquisition.npz');w=np.load(OUT/f'witness_{name}.npz');x=d['transformed_test'];n,N,m=x.shape;cert=json.loads((OUT/f'witness_{name}_validated.json').read_text());seen=set()
        checker=ValidatedObserver(Gabriel(0,Config(input_dim=m),mode='trace_only'),d['trace_observer_coefficients'].T,precision=120)
        for row in cert:
            ms,bi,i=row['mask_index'],row['budget_index'],row['case'];key=(ms,bi,i);assert key not in seen;seen.add(key)
            assert row['validated'] and w['found'][ms,bi,i]
            a=decode(row['first']);b=decode(row['second']);assert row['first']['winner']!=row['second']['winner']
            lo=np.where(p['masks'][i,ms],-1,x[i].ravel());hi=np.where(p['masks'][i,ms],1,x[i].ravel());budget=int(w['budgets'][bi]);q=p['queries'][i,ms,1,:budget];ans=p['answers'][i,ms,1,:budget];lo[q]=hi[q]=ans
            for field in ['first','second']:
                u=w[field][ms,bi,i].ravel();assert np.all(lo<=u) and np.all(u<=hi)
            if i in [int(np.flatnonzero(w['found'][ms,bi])[0]),int(np.flatnonzero(w['found'][ms,bi])[-1])]:
                for field,bb in [('first',a),('second',b)]:
                    ss=checker.scores(w[field][ms,bi,i]);assert all(low<=s.lower() and s.upper()<=high for (low,high),s in zip(bb,ss));replay+=1
            witnesses+=1
        assert len(seen)==int(w['found'].sum())
        for prefix,filename in [('blocks','blocks_stopping.csv'),('block_mean','block_mean_stopping.csv')]:
            z=np.load(OUT/f'{prefix}_{name}.npz');vc=json.loads((OUT/f'{prefix}_{name}_validated.json').read_text())
            records=[(i,b,vc[i][b]) for i in range(n) for b in range(5)] if prefix=='blocks' else [(r['case'],r['block'],r) for r in vc]
            for i,b,record in records:decode(record);assert record['winner']==z['votes'][i,b];votes+=1
            rows=[r for r in csv.DictReader((OUT/filename).open()) if r['dataset']==name]
            for r in rows:
                i=int(r['case']);ms=['random_half','middle_half'].index(r['mask']);missing=p['masks'][i,ms].reshape(5,-1).sum(1)
                winner,used,left=stop_votes(z['votes'][i],missing==0,range(5),len(d['classes']))
                assert winner==z['prediction'][i] and int(missing[used].sum())==int(r['queries'])
                if prefix=='blocks':assert np.array_equal(z['query_block_paths'][i,ms,:len(used)],used)
                stops+=1
    out=dict(validated_ambiguity_records=witnesses,validated_block_votes=votes,replayed_stopping_records=stops,high_precision_witness_point_replays=replay,validation='exact stored dyadic endpoint comparisons; witness membership; selected points recomputed at 120 bits')
    (OUT/'decision_record_verification.json').write_text(json.dumps(out,indent=2));print(out)
if __name__=='__main__':main()
