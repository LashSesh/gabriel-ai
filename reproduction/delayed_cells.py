"""Local Gabriel updates with timestamped, bounded-age neighbor messages.

Trace blocks remain local to the postsynaptic cell. The event simulator supplies
historical neighbor activities. Equal-schedule contraction is not equivalence to
synchronous computation on a changing input stream.
"""
import numpy as np
from gabriel import soft_threshold

def step_delayed(g,cell,u,neighbor_values):
    p=g.config;i=int(cell);u=np.asarray(u,float);neighbors=np.asarray(neighbor_values,float)
    if neighbors.shape!=(p.degree,) or not np.isfinite(neighbors).all() or np.any(abs(neighbors)>1):raise ValueError('invalid neighbor message')
    if u.shape!=(p.input_dim,) or not np.isfinite(u).all():raise ValueError('invalid input')
    old=g.x[i];w=g.base[i].copy()
    if g.mode=='adaptive':w+=(g.gains[:,0,0,None]*soft_threshold(g.c[:,i,:],g.lam[:,0,0,None])).sum(0)/p.degree
    value=(1-g.alpha[i])*old+g.alpha[i]*np.tanh(w@neighbors+g.U[i]@u+g.bias[i])
    if g.mode in ('adaptive','trace_only'):g.c[:,i,:]=(1-g.beta[:,0,:])*g.c[:,i,:]+g.beta[:,0,:]*(old*neighbors)[None,:]
    g.x[i]=value

def messages(history,parents,now,ages,max_age):
    ages=np.asarray(ages)
    if not np.issubdtype(ages.dtype,np.integer) or ages.shape!=parents.shape or np.any(ages<0) or np.any(ages>max_age):raise ValueError('invalid message age')
    return np.array([history[max(0,now-int(age))][int(parent)] for parent,age in zip(parents,ages)])
