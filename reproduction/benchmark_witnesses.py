"""Construct and validate ambiguity witnesses along the saved decision paths."""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
from pathlib import Path
import numpy as np,json,time
from gabriel import Gabriel,Config
from relaxed_observer import RelaxedObserver
from validated_observer import ValidatedObserver
OUT=Path(__file__).resolve().parents[1]/'results'

def main():
    protocol=dict(budgets='0, floor(J/2), floor(3J/4), floor(9J/10), J-6',policy='saved decision policy; no effect of witness search on acquisition',seed='261025 + 1000*dataset_index + 100*mask_index + budget_index',iterations=24,restarts=2,step='(.15*(1-step/24)+.02) times box width, signed projected gradient',scope='witness success proves ambiguity on that box; failure is inconclusive',validation='100-bit Arb, exact stored dyadic inputs and coefficients; strict distinct point winners')
    (OUT/'witness_protocol.json').write_text(json.dumps(protocol,indent=2));summary=[]
    for di,name in enumerate(['RacketSports','BasicMotions']):
        start=time.perf_counter();d=np.load(OUT/f'external_{name}_model.npz');p=np.load(OUT/f'relaxed_{name}_acquisition.npz');x=d['transformed_test'];n,N,m=x.shape;J=N*m//2
        g=Gabriel(0,Config(input_dim=m),mode='trace_only');a=RelaxedObserver(g,d['trace_observer_coefficients'].T,N);v=ValidatedObserver(g,d['trace_observer_coefficients'].T)
        budgets=[0,J//2,3*J//4,9*J//10,J-6];first=np.zeros((2,5,n,N,m));second=first.copy();found=np.zeros((2,5,n),bool);margins=np.zeros((2,5,n));validation=[]
        for ms,mask in enumerate(['random_half','middle_half']):
            for bi,budget in enumerate(budgets):
                lo=np.where(p['masks'][:,ms],-1.,x.reshape(n,-1));hi=np.where(p['masks'][:,ms],1.,x.reshape(n,-1))
                for qidx in range(budget):
                    q=p['queries'][:,ms,1,qidx];val=p['answers'][:,ms,1,qidx];lo[np.arange(n),q]=val;hi[np.arange(n),q]=val
                lo=lo.reshape(x.shape);hi=hi.reshape(x.shape)
                r=a.find_witness(lo,hi,seed=261025+di*1000+ms*100+bi,iterations=24,restarts=2)
                first[ms,bi]=r['first'];second[ms,bi]=r['second'];margins[ms,bi]=r['margin']
                for i in np.flatnonzero(r['found']):
                    assert np.all(lo[i]<=r['first'][i]) and np.all(r['first'][i]<=hi[i])
                    assert np.all(lo[i]<=r['second'][i]) and np.all(r['second'][i]<=hi[i])
                    va=v.evaluate(r['first'][i]);vb=v.evaluate(r['second'][i])
                    ok=va['winner']>=0 and vb['winner']>=0 and va['winner']!=vb['winner'];found[ms,bi,i]=ok
                    validation.append(dict(mask_index=ms,budget_index=bi,case=int(i),validated=ok,first=va,second=vb))
                row=dict(dataset=name,mask=mask,budget=budget,missing=J,cases=n,float_witnesses=int(r['found'].sum()),validated_witnesses=int(found[ms,bi].sum()))
                summary.append(row);print(row,flush=True)
        np.savez_compressed(OUT/f'witness_{name}.npz',budgets=budgets,first=first,second=second,found=found,margins=margins,model_hash=a.model_hash)
        (OUT/f'witness_{name}_validated.json').write_text(json.dumps(validation,separators=(',',':')))
        print(name,'seconds',time.perf_counter()-start,flush=True)
    (OUT/'witness_summary.json').write_text(json.dumps(summary,indent=2))
if __name__=='__main__':main()
