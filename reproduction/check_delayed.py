"""Executed delayed-communication tests and deliberately invalid-contract controls."""
from pathlib import Path
import numpy as np,json,csv
from gabriel import Gabriel
from delayed_cells import step_delayed,messages
OUT=Path(__file__).resolve().parents[1]/'results'
def main():
 rows=[];max_excess=-np.inf;saved={}
 for age in [0,12,48,96]:
  rng=np.random.default_rng(97000+age);a=Gabriel(3);b=Gabriel(3);r=a.certificate()['trace_scale'];k=a.certificate()['kappa'];n=a.config.n;B=2*n-1;steps=12000
  for label,g in [('a',a),('b',b)]:
   g.x=rng.uniform(-1,1,n);g.c=rng.uniform(-1,1,g.c.shape)
   saved[f'age_{age}_initial_activity_{label}']=g.x.copy();saved[f'age_{age}_initial_traces_{label}']=g.c.copy()
  ha=[a.x.copy()];hb=[b.x.copy()];dist=[a.distance(b,r)];inputs=rng.uniform(-1,1,(steps,2));schedule=np.concatenate([rng.permutation(n) for _ in range((steps+n-1)//n)])[:steps];ages=rng.integers(0,age+1,(steps,a.config.degree));cs=[]
  for t,i in enumerate(schedule):
   step_delayed(a,i,inputs[t],messages(ha,a.parents[i],t,ages[t],age));step_delayed(b,i,inputs[t],messages(hb,b.parents[i],t,ages[t],age));ha.append(a.x.copy());hb.append(b.x.copy());dist.append(a.distance(b,r))
  dist=np.array(dist);envelope=np.array([dist[max(0,t-age):t+1].max() for t in range(steps+1)]);epoch=B+age;bound=dist[0]*k**(np.arange(steps+1)//epoch);excess=float(np.max(envelope-bound));max_excess=max(max_excess,excess)
  local=float(np.max(envelope[epoch:]-k*envelope[:-epoch]));assert excess<1e-12 and local<1e-12
  rows.append(dict(max_age=age,fairness_window=B,steps=steps,kappa=k,initial_distance=dist[0],final_distance=dist[-1],bound_final=bound[-1],max_bound_excess=excess,max_epoch_excess=local))
  saved[f'age_{age}_inputs']=inputs;saved[f'age_{age}_schedule']=schedule;saved[f'age_{age}_message_ages']=ages;saved[f'age_{age}_distance']=dist;saved[f'age_{age}_envelope']=envelope;saved[f'age_{age}_bound']=bound;saved[f'age_{age}_activity_a']=np.array(ha);saved[f'age_{age}_activity_b']=np.array(hb)
  print(rows[-1],flush=True)
 # No fairness: a never-updated coordinate retains its discrepancy exactly.
 a=Gabriel(3);b=Gabriel(3);b.x[-1]=1.;r=a.certificate()['trace_scale']
 for t in range(500):a.step_cell(0,[0,0]);b.step_cell(0,[0,0])
 assert b.x[-1]-a.x[-1]==1.
 # Same schedule and constant forcing converge to the synchronous fixed point.
 fixed=Gabriel(3)
 for t in range(6000):fixed.step([.2,-.3])
 a=Gabriel(3);history=[a.x.copy()]
 for t in range(30000):
  i=t%a.config.n;age=48;step_delayed(a,i,[.2,-.3],messages(history,a.parents[i],t,np.full(a.config.degree,age),age));history.append(a.x.copy())
 steady_error=a.distance(fixed,r);assert steady_error<1e-8
 # Changing inputs: zero-delay and delayed execution need not have same trajectory.
 a=Gabriel(3);b=Gabriel(3);history=[b.x.copy()];difference=[]
 for t in range(1000):
  i=t%48;u=[np.sin(t/13),np.cos(t/17)];a.step_cell(i,u);step_delayed(b,i,u,messages(history,b.parents[i],t,np.full(6,48),48));history.append(b.x.copy());difference.append(a.distance(b,r))
 assert max(difference)>1e-4
 result=dict(tested_maximum_ages=[0,12,48,96],fairness_window=95,paired_steps_per_age=12000,tolerance=1e-12,max_bound_excess=max_excess,starved_coordinate_difference=1.,constant_input_fixed_point_error=steady_error,different_schedule_or_delay_not_same_stream_state=max(difference),scope='simulated local message reads; no multi-process or hardware performance claim')
 (OUT/'delayed_checks.json').write_text(json.dumps(result,indent=2));np.savez_compressed(OUT/'delayed_cases.npz',**saved)
 with (OUT/'delayed_summary.csv').open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=rows[0]);w.writeheader();w.writerows(rows)
 print(json.dumps(result,indent=2))
if __name__=='__main__':main()
