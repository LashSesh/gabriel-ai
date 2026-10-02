"""Finite abstraction, causality and independent point-reference checks."""
import itertools,json
from pathlib import Path
import numpy as np
from flint import arb,ctx
from prefix_observer import forced_winner,representations,checkpoints,acquire
from validated_prefix import feature_balls
from validated_observer import ValidatedObserver
from gabriel import Gabriel,Config
ROOT=Path(__file__).resolve().parents[1]

def main():
    states=0;completions=0
    for K in [4,6]:
        for partial in itertools.product(range(-1,K),repeat=5):
            v=np.array(partial);unknown=v<0;count=np.bincount(v[~unknown],minlength=K);R=int(unknown.sum());possible=set()
            for rest in itertools.product(range(K),repeat=R):
                cc=count+np.bincount(rest,minlength=K);possible.add(int(cc.argmax()));completions+=1
            a=forced_winner(count,R,True)
            assert (a>=0)==(len(possible)==1)
            if a>=0:assert possible=={a}
            strict=forced_winner(count,R,False)
            if strict>=0:assert possible=={strict}
            states+=1
    rng=np.random.default_rng(260925);u=rng.uniform(-1,1,(2,11,3));cuts=checkpoints(11);f=representations(u)
    checks=0
    for j,t in enumerate(cuts[:-1]):
        w=u.copy();w[:,t:]=rng.uniform(-1,1,w[:,t:].shape);fw=representations(w)
        assert np.array_equal(f['shared_prefix'][:,:j+1],fw['shared_prefix'][:,:j+1]);checks+=1
    co=rng.normal(size=(4,148));g=Gabriel(0,Config(input_dim=3),mode='trace_only')
    direct=ValidatedObserver(g,co,160);balls=feature_balls(u[0],cuts,100);refs=0
    # Evaluate independent full-prefix recurrence, rather than relying on one-pass snapshots.
    for t,(ff,_) in zip(cuts,balls):
        ss=[sum((arb(float(a))*b for a,b in zip(row,ff)),arb(0)) for row in co]
        rr=direct.scores(u[0,:t])
        assert all(s.contains(r) for s,r in zip(ss,rr));refs+=len(rr)
    # Full enumeration also checked the sharp rule at zero known votes and all ties.
    out=dict(partial_vote_states=states,enumerated_completions=completions,causal_prefix_checks=checks,independent_arb_score_references=refs,seed=260925)
    (ROOT/'results/prefix_checks.json').write_text(json.dumps(out,indent=2));print(out)
if __name__=='__main__':main()
