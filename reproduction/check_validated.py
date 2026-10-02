"""Exhaustive discrete stopping checks and independent Arb edge recurrence."""
import itertools,json
from pathlib import Path
import numpy as np
from flint import arb,ctx
from gabriel import Gabriel,Config
from validated_observer import ValidatedObserver
from observer_bounds import ObserverBounds
from benchmark_blocks import stop_votes

def main():
    count=0
    for vote in itertools.product(range(4),repeat=5):
      vote=np.array(vote);full=int(np.bincount(vote,minlength=4).argmax())
      for mask in itertools.product([False,True],repeat=5):
        known=np.array(mask);winner,used,left=stop_votes(vote,known,range(5),4)
        assert winner==full and len(set(used))==len(used) and all(not known[b] for b in used)
        if left:
            seen=known.copy();seen[used]=True;cc=np.bincount(vote[seen],minlength=4)
            assert all(winner==k or cc[winner]>cc[k]+left for k in range(4))
        count+=1
    rng=np.random.default_rng(261101);checked=0;maxerr=0.
    for seed in range(5):
        g=Gabriel(seed,Config(n=6,degree=2,backbone_degree=1,input_dim=2),mode='trace_only')
        co=rng.normal(size=(3,1+2+6*3));v=ValidatedObserver(g,co);a=ObserverBounds(g,co,8)
        for case in range(4):
            u=rng.uniform(-1,1,(8,2));scores=v.scores(u);point=a.point(u)[0]
            maxerr=max(maxerr,max(abs(float(s)-p) for s,p in zip(scores,point)))
            # Independent edge-by-edge trace state at higher precision.
            ctx.prec=160;x=[arb(0) for i in range(6)];c=[[[arb(0) for j in range(2)] for i in range(6)] for r in range(2)]
            for event in u:
                c=[[[ (1-arb(float(g.beta[r,0,0])))*c[r][i][j]+arb(float(g.beta[r,0,0]))*x[i]*x[int(g.parents[i,j])] for j in range(2)] for i in range(6)] for r in range(2)]
                xx=[]
                for i in range(6):
                    d=arb(float(g.bias[i]))
                    for j in range(2):d+=arb(float(g.base[i,j]))*x[int(g.parents[i,j])]
                    for j in range(2):d+=arb(float(g.U[i,j]))*arb(float(event[j]))
                    al=arb(float(g.alpha[i]));xx.append((1-al)*x[i]+al*d.tanh())
                x=xx
            f=[arb(1)]+[arb(float(z)) for z in u[-1]]+x+[sum(c[r][i],arb(0))/2 for r in range(2) for i in range(6)]
            ref=[sum((arb(float(w))*z for w,z in zip(row,f)),arb(0)) for row in co]
            assert all(s.contains(t) for s,t in zip(scores,ref));checked+=len(scores)
    assert maxerr<1e-10
    out=dict(exhaustive_vote_cases=count,independent_edge_reference_scores=checked,max_float_point_difference=maxerr,arb_precision=100,reference_precision=160)
    (Path(__file__).resolve().parents[1]/'results'/'validated_checks.json').write_text(json.dumps(out,indent=2));print(out)
if __name__=='__main__':main()
