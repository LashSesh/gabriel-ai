"""Additional analytical reference and module-composition checks."""
import json
import numpy as np
from scipy.optimize import brentq
from gabriel import Gabriel
from run_experiments import OUT,savecsv

def main():
    rng=np.random.default_rng(9204)
    a=[Gabriel(31),Gabriel(32)];b=[Gabriel(31),Gabriel(32)]
    c=a[0].certificate();r=c['trace_scale'];k=c['kappa'];coupling=.002
    cross=[float(coupling*np.max(m.alpha*np.abs(m.U[:,0]))) for m in a]
    knet=k+max(cross)
    for m in b:
        m.x=rng.uniform(-1,1,m.x.shape);m.c=rng.uniform(-1,1,m.c.shape)
    d0=max(m.distance(n,r) for m,n in zip(a,b));rows=[]
    for t in range(1201):
        dist=max(m.distance(n,r) for m,n in zip(a,b))
        rows.append(dict(t=t,distance=dist,bound=knet**t*d0))
        assert dist<=knet**t*d0+1e-12
        u=rng.uniform(-1,1,2)
        # Compute both module inputs before any activity is updated.
        for system in [a,b]:
            inputs=[u+np.array([coupling*system[1-i].x.mean(),0.]) for i in [0,1]]
            for m,v in zip(system,inputs):m.step(v)
    savecsv('composition.csv',rows)
    # Compare vectorized code against an independently indexed one-step evaluation.
    m=Gabriel(45);m.x=rng.uniform(-1,1,m.x.shape);m.c=rng.uniform(-1,1,m.c.shape)
    u=rng.uniform(-1,1,2);oldx=m.x.copy();oldc=m.c.copy();wx=m.weights()
    nx=np.empty_like(oldx);nc=np.empty_like(oldc)
    for i in range(m.config.n):
        net=sum(float(wx[i,j])*float(oldx[m.parents[i,j]]) for j in range(m.config.degree))
        net+=sum(float(m.U[i,j])*float(u[j]) for j in range(2))+float(m.bias[i])
        nx[i]=(1-m.alpha[i])*oldx[i]+m.alpha[i]*np.tanh(net)
        for ell,beta in enumerate(m.config.betas):
            for j in range(m.config.degree):
                nc[ell,i,j]=(1-beta)*oldc[ell,i,j]+beta*oldx[i]*oldx[m.parents[i,j]]
    m.step(u)
    scalar_error=max(float(np.max(np.abs(m.x-nx))),float(np.max(np.abs(m.c-nc))))
    assert scalar_error<1e-14
    root=brentq(lambda x: np.tanh(1.25*x)-x,.01,.99999,xtol=1e-14)
    result=dict(coupling=coupling,module_kappa=k,intermodule_gains=cross,network_kappa=knet,final_distance=rows[-1]['distance'],scalar_reference_error=scalar_error,frozen_coordinate_counterexample_fixed_point=root,checks_passed=True)
    (OUT/'composition.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
if __name__=='__main__':main()
