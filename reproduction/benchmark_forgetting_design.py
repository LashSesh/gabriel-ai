"""Frozen mechanism study and old-asset selection; no unused market columns read."""
from pathlib import Path
import json,hashlib,time
import numpy as np
from forgetting_risk import load_design,replay,synthetic_samples,ROOT
from severity_risk import analytic_score_diagnostics
from ecb_risk import fz_score

def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def main():
 start=time.perf_counter();p=load_design();spec=p['synthetic'];variants=p['variants'];records=[];archive={}
 for ci,case in enumerate(spec['cases']):
  q,e,y,s,d,tail,seeds=synthetic_samples(ci,case,spec)
  for h in spec['latencies']:
   t=np.arange(spec['n']);mask=(t>=spec['warmup'])&(t+h<spec['n']);masks=dict(all=mask,early=mask&(t<3113),late=mask&(t>=3113))
   key=f'{case}_{h}'
   for v in variants:
    z=replay(q,e,y,h,v['kind'],v['memory'],p['c'])
    expected=analytic_score_diagnostics(z['var'],z['es'],s[:,None],d[:,None],'bounded' if tail=='uniform' else tail)['expected_fz0']
    excess=expected-np.log(s*(1+d))[:,None];real=fz_score(z['var'],z['es'],y)
    for rep in range(spec['replicates']):
     records.append(dict(case=case,latency=h,replicate=rep,seed=seeds[rep],model=v['name'],periods={k:dict(n=int(m.sum()),conditional_excess_fz0=float(excess[m,rep].mean()),realized_fz0=float(real[m,rep].mean())) for k,m in masks.items()}))
    for field in ['var','es','issued_weights','issued_accumulator','accumulator_after','step','gradient_norm_squared','epoch','reset_before_issue']:
     archive[key+'_'+v['name']+'_'+field]=z[field][:,0]
   archive[key+'_losses']=y;archive[key+'_expert_var']=q[:,0];archive[key+'_expert_es']=e[:,0];archive[key+'_scale']=s;archive[key+'_tail_mean']=d
   print('synthetic',case,h,flush=True)
 out=dict(schema='gabriel.forgetting.synthetic.v1',design_sha256=digest(ROOT/'results/forgetting_design_v2.json'),records=records,replicates=spec['replicates'],scope='Known constructed distributions; design experiments, not an independent synthetic holdout',replicate_zero_traces='All algorithms; all losses, seeds and per-replication metrics retained')
 np.savez_compressed(ROOT/'results/forgetting_synthetic.npz',**archive);out['archive_sha256']=digest(ROOT/'results/forgetting_synthetic.npz')
 (ROOT/'results/forgetting_synthetic.json').write_text(json.dumps(out,indent=2)+'\n')
 # Retained old-currency archives only; outcomes after2019 are never evaluated.
 old=np.load(ROOT/'results/adaptive_risk_predictions.npz',allow_pickle=False);severity=np.load(ROOT/'results/severity_risk_predictions.npz',allow_pickle=False);dates=old['dates'];dev=[]
 for currency in p['development']['currencies']:
  for h in p['development']['horizons']:
   key=f'{currency}_{h}';allorig=old[key+'_origins'];keep=(dates[allorig]>='2010-01-01')&(dates[allorig]<='2019-12-31');orig=allorig[keep]
   qb=old[key+'_base_candidate_var'][keep];eb=old[key+'_base_candidate_es'][keep]
   q=np.column_stack([qb,qb[:,5],qb[:,5]]);e=np.column_stack([eb,severity[key+'_candidate_es'][keep,0,0],severity[key+'_candidate_es'][keep,0,1]])
   y=old[key+'_realized'][keep].copy();mature=np.arange(len(orig))+h<len(orig);y[~mature]=np.nan
   valid=mature&(dates[orig]>='2015-01-01')&(dates[np.minimum(orig+h,len(dates)-1)]<='2019-12-31')
   for v in variants:
    z=replay(q,e,y,h,v['kind'],v['memory'],p['c'],orig)
    dev.append(dict(currency=currency,horizon=h,model=v['name'],n=int(valid.sum()),mean_fz0=float(fz_score(z['var'][valid],z['es'][valid],y[valid]).mean())))
   print('development',key,flush=True)
 (ROOT/'results/forgetting_development.json').write_text(json.dumps(dict(records=dev,design_sha256=out['design_sha256'],source_sha256={n:digest(ROOT/'results'/n) for n in ['adaptive_risk_predictions.npz','severity_risk_predictions.npz']}),indent=2)+'\n')
 # Frozen selection: market validation plus controlled responsiveness/stationary gate.
 means={}
 for v in variants:
  name=v['name'];sm={f'{case}_{h}':float(np.mean([r['periods']['all']['conditional_excess_fz0'] for r in records if r['case']==case and r['latency']==h and r['model']==name])) for case in spec['cases'] for h in spec['latencies']}
  means[name]=dict(development_mean=float(np.mean([r['mean_fz0'] for r in dev if r['model']==name])),synthetic_means=sm)
 base=means['cumulative'];eligible=[]
 for v in variants:
  name=v['name'];x=means[name];stationary=[x['synthetic_means'][key]-base['synthetic_means'][key] for key in x['synthetic_means'] if key.startswith('stationary')];moving=[x['synthetic_means'][key]-base['synthetic_means'][key] for key in x['synthetic_means'] if not key.startswith('stationary')]
  x['maximum_stationary_penalty']=max(stationary);x['mean_changing_difference']=float(np.mean(moving));x['eligible']=bool(name!='cumulative' and x['development_mean']<base['development_mean'] and max(stationary)<=.02 and np.mean(moving)<0)
  if x['eligible']:eligible.append(name)
 primary=min(eligible,key=lambda name:means[name]['development_mean']) if eligible else 'cumulative'
 selection=dict(schema='gabriel.forgetting.selection.v1',design_sha256=out['design_sha256'],primary_model=primary,eligible=eligible,candidates=means,source_sha256={name:digest(ROOT/'results'/name) for name in ['forgetting_synthetic.json','forgetting_development.json']},code_sha256={name:digest(ROOT/'reproduction'/name) for name in ['forgetting_risk.py','benchmark_forgetting_design.py']},execution_seconds=time.perf_counter()-start)
 (ROOT/'results/forgetting_selection.json').write_text(json.dumps(selection,indent=2)+'\n')
 print('SELECTION',json.dumps(selection['candidates'],indent=2),flush=True);print('PRIMARY',primary,'seconds',selection['execution_seconds'],flush=True)
if __name__=='__main__':main()
