"""Maturity-lane simplex updates with cumulative, discounted, window or epoch memory.

Only restart discards learned weights. Other variants forget squared gradient
norms, not weights or losses. Memory counts matured observations within each lane.
Binary64 computations; no claim of a global contraction or statistical calibration.
"""
from pathlib import Path
import hashlib,json
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
BETA=1/40

def load_design():
 p=ROOT/'results/forgetting_design_v2.json';raw=p.read_bytes()
 if hashlib.sha256(raw).hexdigest()!=p.with_suffix('.sha256').read_text().split()[0]:raise ValueError('design changed')
 return json.loads(raw)

def project_rows(v):
 x=np.asarray(v,float)
 if x.ndim!=2 or not np.isfinite(x).all():raise ValueError('finite matrix required')
 z=x-x.max(axis=1,keepdims=True);s=np.sort(z,axis=1)[:,::-1]
 sums=np.cumsum(s,axis=1)-1;ranks=np.arange(1,x.shape[1]+1)
 active=s-sums/ranks>0;ix=active.sum(axis=1)-1
 theta=sums[np.arange(len(x)),ix]/(ix+1)
 return np.maximum(z-theta[:,None],0)

def replay(q,e,y,horizon,kind='cumulative',memory=0,c=.1,origins=None):
 q,e,y=np.asarray(q,float),np.asarray(e,float),np.asarray(y,float)
 squeeze=q.ndim==2
 if squeeze:q,e,y=q[:,None,:],e[:,None,:],y[:,None]
 if q.ndim!=3 or q.shape!=e.shape or y.shape!=q.shape[:2] or min(q.shape)<1:raise ValueError('matching nonempty arrays required')
 n,b,k=q.shape
 if (not np.isfinite(q).all() or not np.isfinite(e).all() or np.any(q<=0) or np.any(e<q) or
     not isinstance(horizon,(int,np.integer)) or isinstance(horizon,bool) or horizon<1 or not np.isfinite(c) or c<=0):raise ValueError('invalid forecasts or controls')
 if kind not in ['cumulative','discount','window','restart']:raise ValueError('unknown memory rule')
 if kind!='cumulative' and (not isinstance(memory,(int,np.integer)) or isinstance(memory,bool) or memory<1):raise ValueError('positive integer memory required')
 if origins is None:origins=np.arange(n)
 origins=np.asarray(origins)
 if origins.shape!=(n,) or origins.dtype.kind not in 'iu' or np.any(np.diff(origins)!=1):raise ValueError('contiguous integer origin indices required')
 mature=np.arange(n)+horizon<n
 if not np.isfinite(y[mature]).all():raise ValueError('nonfinite mature outcome')
 a=q/e;bb=1/e;states=np.full((horizon,b,k),1/k);acc=np.zeros((horizon,b));count=np.zeros(horizon,int);epoch=np.zeros(horizon,int)
 ring=np.zeros((horizon,max(1,memory if kind=='window' else 1),b))
 out={name:np.full((n,b,k),np.nan) for name in ['issued_weights','postupdate_weights','centered_gradient']}
 out.update({name:np.full((n,b),np.nan) for name in ['var','es','issued_accumulator','accumulator_after','step','gradient_norm_squared','epoch']})
 out['reset_before_issue']=np.zeros((n,b),bool);out['matured']=mature
 for t in range(n):
  lane=int(origins[t]%horizon);j=t-horizon
  if j>=0:
   w=out['issued_weights'][j]
   aw=np.sum(a[j]*w,axis=1);bw=np.sum(bb[j]*w,axis=1);z=y[j]*bw-aw
   g=-bb[j]/bw[:,None]+a[j]+(z>0)[:,None]*(y[j,:,None]*bb[j]-a[j])/BETA
   g-=g.mean(axis=1,keepdims=True);norm=np.sum(g*g,axis=1)
   if kind=='discount':acc[lane]=2.**(-1/memory)*acc[lane]+norm
   elif kind=='window':
    ring[lane,count[lane]%memory]=norm;acc[lane]=ring[lane].sum(axis=0)
   else:acc[lane]+=norm
   eta=np.divide(c,np.sqrt(acc[lane]),out=np.zeros(b),where=acc[lane]>0)
   post=project_rows(w-eta[:,None]*g)
   out['centered_gradient'][j]=g;out['gradient_norm_squared'][j]=norm;out['step'][j]=eta
   out['accumulator_after'][j]=acc[lane];out['postupdate_weights'][j]=post
   states[lane]=post;count[lane]+=1
   if kind=='restart' and count[lane]%memory==0:
    states[lane]=1/k;acc[lane]=0;epoch[lane]+=1;out['reset_before_issue'][t]=True
  w=states[lane].copy();out['issued_weights'][t]=w;out['issued_accumulator'][t]=acc[lane];out['epoch'][t]=epoch[lane]
  bw=np.sum(bb[t]*w,axis=1);aw=np.sum(a[t]*w,axis=1);out['var'][t]=aw/bw;out['es'][t]=1/bw
 for key,value in out.items():
  if key!='matured' and squeeze:out[key]=value[:,0]
 return out

def synthetic_case(case,n=6000):
 t=np.arange(n);scale=np.full(n,.75);d=np.full(n,.5);tail='uniform'
 if case=='stationary_high':scale[:]=1.5;d[:]=3
 elif case=='scale_switch':scale[t>=3113]=1.5
 elif case=='severity_switch':d[t>=3113]=3
 elif case in ['joint_recurrent','exponential_recurrent']:
  hi=(t//1451)%2==1;scale[hi]=1.5;d[hi]=3
  if case=='exponential_recurrent':tail='exponential'
 elif case=='joint_gradual':
  x=np.clip((t-2113)/2000,0,1);scale=.75+.75*x;d=.5+2.5*x
 elif case!='stationary_low':raise ValueError('unknown synthetic case')
 return scale,d,tail

def synthetic_samples(case_index,case,spec):
 n,r=spec['n'],spec['replicates'];s,d,tail=synthetic_case(case,n)
 q=np.broadcast_to(np.array(spec['expert_scale']),(n,r,4)).copy()
 e=q*(1+np.array(spec['expert_tail_mean']))
 ys=[];seedrecords=[]
 for rep in range(r):
  seed=[spec['seed'],case_index,rep];rng=np.random.default_rng(np.random.SeedSequence(seed))
  hit=rng.random(n)<BETA;body=rng.uniform(-1,1,n)
  excess=rng.uniform(0,2,n)*d if tail=='uniform' else rng.exponential(1,n)*d
  ys.append(s*np.where(hit,1+excess,body));seedrecords.append(seed)
 return q,e,np.stack(ys,axis=1),s,d,tail,seedrecords
