"""Fair sequential cell schedules; no stale neighbor values."""
import json
import numpy as np
from gabriel import Gabriel
from run_experiments import OUT,savecsv

def main():
    rng=np.random.default_rng(5401);a=Gabriel(17);b=Gabriel(17)
    cert=a.certificate();r=cert['trace_scale'];k=cert['kappa']
    b.x=rng.uniform(-1,1,b.x.shape);b.c=rng.uniform(-1,1,b.c.shape)
    initial=a.distance(b,r);rows=[]
    for sweep in range(301):
        d=a.distance(b,r);bound=initial*k**sweep
        rows.append(dict(sweep=sweep,distance=d,bound=bound))
        assert d<=bound+1e-12
        if sweep == 300: break
        u=rng.uniform(-1,1,2)
        for i in rng.permutation(a.config.n):a.step_cell(i,u);b.step_cell(i,u)
    # Entire synchronous map and a one-cell update must agree at that cell
    # when evaluated from the same old state.
    c=Gabriel(40);d=Gabriel(40)
    c.x=rng.uniform(-1,1,c.x.shape);c.c=rng.uniform(-1,1,c.c.shape)
    d.x=c.x.copy();d.c=c.c.copy();u=rng.uniform(-1,1,2)
    c.step(u);d.step_cell(3,u)
    error=max(abs(c.x[3]-d.x[3]),np.max(np.abs(c.c[:,3,:]-d.c[:,3,:])))
    assert error<1e-14
    savecsv('asynchronous.csv',rows)
    result=dict(seed=5401,sweeps=300,cell_updates=300*a.config.n,fairness='each cell exactly once per random permutation sweep',input='held constant within each sweep',same_cell_reference_error=float(error),final_distance=rows[-1]['distance'],max_bound_excess=max(x['distance']-x['bound'] for x in rows),checks_passed=True)
    (OUT/'asynchronous.json').write_text(json.dumps(result,indent=2)+'\n');print(result)
if __name__=='__main__':main()
