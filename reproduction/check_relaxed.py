"""Independent tests of scalar relaxations and the full fixed observer."""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
from pathlib import Path
import numpy as np,json,itertools
from gabriel import Gabriel,Config
from relaxed_observer import RelaxedObserver,tanh_parallel
from check_observer import tangent
OUT=Path(__file__).resolve().parents[1]/'results'

def main():
 rng=np.random.default_rng(260926);lower=rng.uniform(-10,8,1000);upper=lower+rng.uniform(0,5,1000);lower[:3]=[0,-2,3];upper[:3]=lower[:3]
 s,o,e=tanh_parallel(lower,upper);xx=lower+np.linspace(0,1,101)[:,None]*(upper-lower)
 assert np.max(abs(np.tanh(xx)-s*xx-o)-e)<1e-14
 checks=0;maximum=0.;gradient=0.
 for seed in range(12):
  g=Gabriel(seed,Config(n=6,degree=2,backbone_degree=1,input_dim=2),mode='trace_only');co=rng.normal(size=(3,21));a=RelaxedObserver(g,co,5)
  truth=rng.uniform(-.8,.8,(5,2));mask=np.zeros(10,bool);mask[rng.choice(10,6,False)]=True;mask=mask.reshape(5,2);lo=np.where(mask,-1,truth);hi=np.where(mask,1,truth);res=a.relaxed(lo,hi)
  xx=[]
  for signs in itertools.product([-1.,1.],repeat=6):
   u=truth.copy();u[mask]=signs;xx.append(u)
  xx=np.concatenate([xx,lo+(hi-lo)*rng.random((60,5,2))])
  for u in xx:
   score,jac=tangent(g,co,u);diff=np.array([score[p]-score[q] for p,q in a.pp]);bb=res['raw'][0]
   assert np.all(bb[:,0]-1e-10<=diff) and np.all(diff<=bb[:,1]+1e-10);checks+=1
  point=a.relaxed(truth,truth);score,jac=tangent(g,co,truth);diff=np.array([score[p]-score[q] for p,q in a.pp]);maximum=max(maximum,float(np.max(abs(point['raw'][0]-diff[:,None]))))
  val,gr,_=a.pair_gradient(np.repeat(truth[None],3,0),np.arange(3),np.array([1.,-1.,1.]))
  ref=np.stack([sg*(jac[p]-jac[q]) for (p,q),sg in zip(a.pp,[1.,-1.,1.])]);gradient=max(gradient,float(np.max(abs(gr-ref))))
  q=a.decision_query(res,lo,hi)[0];assert mask.ravel()[q]
 assert maximum<1e-12 and gradient<1e-12
 # A direct input readout crosses its decision boundary inside the box.
 co=np.zeros((3,21));co[0,1]=1;co[1,1]=-1;co[2,0]=-2
 a=RelaxedObserver(g,co,5);w=a.find_witness(-np.ones((5,2)),np.ones((5,2)),iterations=5,restarts=1)
 assert w['found'][0] and w['first_scores'][0].argmax()!=w['second_scores'][0].argmax()
 out=dict(seed=260926,scalar_intervals=1000,scalar_sample_checks=101000,full_completions=checks,max_singleton_error=maximum,max_independent_gradient_error=gradient,witness_reference_passed=True,tolerance=1e-10,arithmetic='float64, not outward rounded')
 (OUT/'relaxed_checks.json').write_text(json.dumps(out,indent=2));print(json.dumps(out,indent=2))
if __name__=='__main__':main()
