"""Training-only exploratory probes preceding the frozen external comparison."""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
import numpy as np,json
from pathlib import Path
from gabriel import Gabriel,Config
from relaxed_observer import RelaxedObserver
OUT=Path(__file__).resolve().parents[1]/'results'
def main():
    widths=[];witnesses=[]
    for name in ['RacketSports','BasicMotions']:
        d=np.load(OUT/f'external_{name}_model.npz');x=d['transformed_train'][:8];n,N,m=x.shape;a=RelaxedObserver(Gabriel(0,Config(input_dim=m),mode='trace_only'),d['trace_observer_coefficients'].T,N)
        perm=np.random.default_rng(260930).permutation(N*m)
        for frac in [.5,.2,.1,.05,.02]:
            hidden=perm[:int(N*m*frac)];lo=x.copy().reshape(n,-1);hi=lo.copy();lo[:,hidden]=-1;hi[:,hidden]=1;lo=lo.reshape(x.shape);hi=hi.reshape(x.shape);r=a.relaxed(lo,hi)
            widths.append(dict(dataset=name,missing_fraction=frac,old_mean_width=float(np.mean(np.diff(r['base']['bounds'][:,2],axis=-1))),new_mean_width=float(np.mean(np.diff(r['bounds'],axis=-1))),old_resolved=int((a.verdicts(r['base']['bounds'][:,2])>=0).sum()),new_resolved=int((a.verdicts(r['bounds'])>=0).sum())))
            if frac in [.5,.1,.02]:
                w=a.find_witness(lo,hi,iterations=16,restarts=1)
                witnesses.append(dict(dataset=name,missing_fraction=frac,found=int(w['found'].sum()),cases=n,min_margin=float(w['margin'].min())))
    (OUT/'relaxed_training_probe.json').write_text(json.dumps(widths,indent=2));(OUT/'relaxed_training_witness_probe.json').write_text(json.dumps(witnesses,indent=2))
if __name__=='__main__':main()
