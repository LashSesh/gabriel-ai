"""Independent lane-first, extended-precision verification of finite gradient memory.

The reference does not import the production projection, replay or expectation.
The full research design, all22methods and selected operating fallback are audited.
"""
from pathlib import Path
import json,hashlib,time
import numpy as np
ROOT=Path(__file__).resolve().parents[1];LD=np.longdouble;BETA=LD(1)/40

def project(x):
 # Active-set water filling, independent of the producer's sorting algorithm.
 active=np.ones(x.shape,bool)
 for _ in range(x.shape[1]+1):
  theta=(np.sum(np.where(active,x,0),axis=1)-1)/active.sum(axis=1)
  new=x>theta[:,None]
  if np.array_equal(new,active):return np.maximum(x-theta[:,None],0)
  active=new
 raise AssertionError('active-set projection failed')

def reference(q,e,y,h,kind,memory,c,origins=None):
 q,e,y=np.asarray(q,LD),np.asarray(e,LD),np.asarray(y,LD);single=q.ndim==2
 if single:q,e,y=q[:,None],e[:,None],y[:,None]
 n,b,k=q.shape;orig=np.arange(n) if origins is None else np.asarray(origins)
 trace={name:np.full((n,b,k),np.nan,dtype=LD) for name in ['issued_weights','postupdate_weights','centered_gradient']}
 trace.update({name:np.full((n,b),np.nan,dtype=LD) for name in ['var','es','issued_accumulator','accumulator_after','step','gradient_norm_squared','epoch']});trace['reset_before_issue']=np.zeros((n,b),bool)
 a=q/e;bb=1/e
 for lane in range(h):
  w=np.full((b,k),LD(1)/k);energy=np.zeros(b,dtype=LD);history=[];epoch=0;completed=0
  for index in np.flatnonzero(orig%h==lane):
   trace['issued_weights'][index]=w;trace['issued_accumulator'][index]=energy;trace['epoch'][index]=epoch
   aq=np.sum(w*a[index],axis=1);be=np.sum(w*bb[index],axis=1);trace['var'][index]=aq/be;trace['es'][index]=1/be
   if index+h>=n:continue
   g=-bb[index]/be[:,None]+a[index]
   positive=y[index]*be>aq
   g+=positive[:,None]*(y[index,:,None]*bb[index]-a[index])/BETA
   g-=np.mean(g,axis=1,keepdims=True);g2=np.sum(g*g,axis=1)
   if kind=='discount':energy=np.exp(-np.log(LD(2))/memory)*energy+g2
   elif kind=='window':
    history.append(g2.copy());energy=np.sum(history[-memory:],axis=0,dtype=LD)
   else:energy=energy+g2
   eta=np.divide(LD(c),np.sqrt(energy),out=np.zeros(b,dtype=LD),where=energy>0)
   w=project(w-eta[:,None]*g);trace['postupdate_weights'][index]=w;trace['centered_gradient'][index]=g;trace['accumulator_after'][index]=energy;trace['step'][index]=eta;trace['gradient_norm_squared'][index]=g2
   completed+=1
   if kind=='restart' and completed%memory==0:
    w=np.full((b,k),LD(1)/k);energy=np.zeros(b,dtype=LD);epoch+=1;trace['reset_before_issue'][index+h]=True
 for key,val in trace.items():
  if single:trace[key]=val[:,0]
 return trace

def score(q,e,y):return np.log(e)+(q+np.maximum(y-q,0)/BETA)/e-1

def expected(q,e,s,d,tail):
 q,e=np.asarray(q,LD),np.asarray(e,LD);s,d=np.asarray(s,LD),np.asarray(d,LD)
 def uniform_excess(lo,hi):
  return np.where(q<=lo,(lo+hi)/2-q,np.where(q>=hi,0,(hi-q)**2/(2*(hi-lo))))
 body=uniform_excess(-s,s)
 if tail=='uniform':upper=uniform_excess(s,s*(1+2*d))
 else:upper=np.where(q<=s,s*(1+d)-q,s*d*np.exp(-(q-s)/(s*d)))
 return np.log(e)+(q+((1-BETA)*body+BETA*upper)/BETA)/e-1

def compare(x,y,atol=1e-9):
 a,b=np.asarray(x),np.asarray(y);assert a.shape==b.shape
 assert np.allclose(a,b,atol=atol,rtol=1e-10,equal_nan=True)
 if a.dtype.kind=="b" or b.dtype.kind=="b":return float(np.any(a!=b))
 finite=np.isfinite(a)&np.isfinite(b);return float(np.max(np.abs(a[finite]-b[finite]))) if finite.any() else 0.

def generic_checks():
 from forgetting_risk import replay
 from aggregate_risk import replay_adagrad
 rng=np.random.default_rng(2026092622);counts=dict(replays=0,causal_variants=0,unit_scalings=0,regret_checks=0,old_controller_matches=0)
 for h in [1,5]:
  q=rng.uniform(.5,2,(101,5));e=q+rng.uniform(.1,1,(101,5));y=rng.normal(0,2,101);orig=np.arange(31,132)
  for kind in ['cumulative','discount','window','restart']:
   for memory in [3,7]:
    z=replay(q,e,y,h,kind,memory,.1,orig);ref=reference(q,e,y,h,kind,memory,.1,orig)
    for key in ref:compare(z[key],ref[key]);counts['replays']+=1 if key=='var' else 0
    altered=y.copy();altered[-h:]=np.inf;other=replay(q,e,altered,h,kind,memory,.1,orig);compare(z['issued_weights'],other['issued_weights']);counts['causal_variants']+=1
    short=replay(q[:-13],e[:-13],y[:-13],h,kind,memory,.1,orig[:-13]);compare(z['issued_weights'][:-13],short['issued_weights']);counts['causal_variants']+=1
    for scale in [.01,3,100]:
     scaled=replay(q*scale,e*scale,y*scale,h,kind,memory,.1,orig);compare(scaled['issued_weights'],z['issued_weights']);compare(scaled['var'],scale*z['var']);counts['unit_scalings']+=1
    for lane in range(h):
     for epoch in np.unique(z['epoch'][orig%h==lane]):
      ix=np.flatnonzero((orig%h==lane)&(z['epoch']==epoch)&(np.arange(len(orig))+h<len(orig)))
      if not len(ix):continue
      eta=z['step'][ix];g2=z['gradient_norm_squared'][ix];positive=eta>0;r=1/eta[positive]
      bound=(r[0]+np.maximum(np.diff(r),0).sum()+.5*np.sum(eta*g2)) if len(r) else 0
      for u in np.eye(q.shape[1]):
       qb=(q[ix]/e[ix])@u/((1/e[ix])@u);eb=1/((1/e[ix])@u)
       regret=np.sum(score(z['var'][ix],z['es'][ix],y[ix])-score(qb,eb,y[ix]));assert regret<=bound+1e-9;counts['regret_checks']+=1
   if kind=='cumulative':
    prior=replay_adagrad(q,e,y,h,.1,orig);compare(z['issued_weights'],prior['issued_weights']);counts['old_controller_matches']+=1
 # Nonmonotone-step counterexample to incorrectly retaining only the final reciprocal step.
 w=np.full(4,.25);u=np.array([1.,0,0,0]);energy=0.;regret=0.;quadratic=0.;inverse=[]
 for t in range(62):
  g=np.array([-1.,-1,1,1])*(1 if t==0 else 1e-6 if t==61 else 0)
  energy=.5*energy+g@g;eta=.1/np.sqrt(energy);regret+=g@(w-u);quadratic+=.5*eta*(g@g);inverse.append(1/eta);w=np.asarray(project((w-eta*g)[None])[0],float)
 naive=inverse[-1]+quadratic;correct=inverse[0]+np.maximum(np.diff(inverse),0).sum()+quadratic
 assert naive<regret<=correct
 counts['nonmonotone_counterexample']=dict(regret=regret,invalid_final_step_bound=naive,valid_variation_bound=correct)
 return counts

def main():
 start=time.perf_counter();p=json.loads((ROOT/'results/forgetting_design_v2.json').read_text());spec=p['synthetic'];final=json.loads((ROOT/'results/forgetting_final_selection.json').read_text());abl=json.loads((ROOT/'results/forgetting_ablation_design.json').read_text());variants=final['all_variants']+abl['variants']
 counts=dict(synthetic_replication_model_latency_cases=0,synthetic_metrics=0,saved_trace_arrays=0,seed_reconstructions=0,development_cases=0);maxima=dict(metrics=0.,traces=0.,development=0.)
 records=[]
 for file in ['forgetting_synthetic.json','forgetting_refinement_synthetic.json','forgetting_ablation_synthetic.json']:records+=json.loads((ROOT/'results'/file).read_text())['records']
 bykey={(r['case'],r['latency'],r['model'],r['replicate']):r for r in records};saved=np.load(ROOT/'results/forgetting_synthetic.npz',allow_pickle=False)
 for ci,case in enumerate(spec['cases']):
  n=spec['n'];t=np.arange(n);s=np.full(n,.75);d=np.full(n,.5);tail='uniform'
  if case=='stationary_high':s[:]=1.5;d[:]=3
  if case=='scale_switch':s[t>=3113]=1.5
  if case=='severity_switch':d[t>=3113]=3
  if case in ['joint_recurrent','exponential_recurrent']:
   hi=(t//1451)%2==1;s[hi]=1.5;d[hi]=3
   if case=='exponential_recurrent':tail='exponential'
  if case=='joint_gradual':x=np.clip((t-2113)/2000,0,1);s=.75+.75*x;d=.5+2.5*x
  y=saved[f'{case}_1_losses'];compare(y,saved[f'{case}_5_losses'])
  q=np.broadcast_to(np.array([.75,.75,1.5,1.5]),(n,spec['replicates'],4));e=q*np.array([1.5,4,1.5,4])
  for rep in range(spec['replicates']):
   rng=np.random.default_rng(np.random.SeedSequence([spec['seed'],ci,rep]));hits=rng.random(n)<.025;body=rng.uniform(-1,1,n);ex=rng.uniform(0,2,n)*d if tail=='uniform' else rng.exponential(1,n)*d
   compare(y[:,rep],s*np.where(hits,1+ex,body));counts['seed_reconstructions']+=1
  for h in spec['latencies']:
   mask=(t>=spec['warmup'])&(t+h<n);masks=dict(all=mask,early=mask&(t<3113),late=mask&(t>=3113))
   for v in variants:
    z=reference(q,e,y,h,v['kind'],v['memory'],v['c']);conditional=expected(z['var'],z['es'],s[:,None],d[:,None],tail)-np.log(s*(1+d))[:,None];actual=score(z['var'],z['es'],y)
    for rep in range(spec['replicates']):
     r=bykey[case,h,v['name'],rep]
     for period,mask in masks.items():
      dif=abs(float(conditional[mask,rep].mean())-r['periods'][period]['conditional_excess_fz0']);dif2=abs(float(actual[mask,rep].mean())-r['periods'][period]['realized_fz0']);assert max(dif,dif2)<1e-9;maxima['metrics']=max(maxima['metrics'],dif,dif2);counts['synthetic_metrics']+=2
     counts['synthetic_replication_model_latency_cases']+=1
    for field in z:
     name=f'{case}_{h}_{v["name"]}_{field}'
     if name in saved.files:maxima['traces']=max(maxima['traces'],compare(saved[name],z[field][:,0]));counts['saved_trace_arrays']+=1
   print('reference synthetic',case,h,flush=True)
 old=np.load(ROOT/'results/adaptive_risk_predictions.npz',allow_pickle=False);severity=np.load(ROOT/'results/severity_risk_predictions.npz',allow_pickle=False);dates=old['dates'];dev=[]
 for name in ['forgetting_development.json','forgetting_refinement_development.json','forgetting_ablation_development.json']:dev+=json.loads((ROOT/'results'/name).read_text())['records']
 devmap={(r['currency'],r['horizon'],r['model']):r for r in dev}
 for currency in p['development']['currencies']:
  for h in [1,5]:
   key=f'{currency}_{h}';allorig=old[key+'_origins'];keep=(dates[allorig]>='2010-01-01')&(dates[allorig]<='2019-12-31');orig=allorig[keep];qb=old[key+'_base_candidate_var'][keep];eb=old[key+'_base_candidate_es'][keep];q=np.column_stack([qb,qb[:,5],qb[:,5]]);e=np.column_stack([eb,severity[key+'_candidate_es'][keep,0,0],severity[key+'_candidate_es'][keep,0,1]]);y=old[key+'_realized'][keep].copy();mature=np.arange(len(orig))+h<len(orig);y[~mature]=np.nan;valid=mature&(dates[orig]>='2015-01-01')&(dates[np.minimum(orig+h,len(dates)-1)]<='2019-12-31')
   for v in variants:
    z=reference(q,e,y,h,v['kind'],v['memory'],v['c'],orig);value=float(score(z['var'][valid],z['es'][valid],y[valid]).mean());dif=abs(value-devmap[currency,h,v['name']]['mean_fz0']);assert dif<1e-9;maxima['development']=max(maxima['development'],dif);counts['development_cases']+=1
   print('reference development',key,flush=True)
 assert final['primary_model']=='cumulative' and not final['eligible']
 result=dict(status='passed',counts=counts,max_absolute_differences=maxima,generic_checks=generic_checks(),selection='unchanged cumulative learner; no candidate eligible',market=json.loads((ROOT/'results/forgetting_market_status.json').read_text()),arithmetic='Independent extended-precision cross-check, not directed-rounding validation.',execution_seconds=time.perf_counter()-start,source_sha256={n:hashlib.sha256((ROOT/'reproduction'/n).read_bytes()).hexdigest() for n in ['forgetting_risk.py','verify_forgetting.py']})
 (ROOT/'results/forgetting_verification.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2),flush=True)
if __name__=='__main__':main()
