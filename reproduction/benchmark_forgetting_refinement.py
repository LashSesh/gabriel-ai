"""Declared development-stage step-size refinement; no new market data access."""
from pathlib import Path
import json,hashlib,time
import numpy as np
from forgetting_risk import load_design,replay,synthetic_samples,ROOT
from severity_risk import analytic_score_diagnostics
from ecb_risk import fz_score

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
 start=time.perf_counter();p=load_design();spec=p['synthetic'];path=ROOT/'results/forgetting_refinement_design.json';raw=path.read_bytes()
 assert sha(path)==path.with_suffix('.sha256').read_text().split()[0];plan=json.loads(raw);variants=plan['variants'];records=[]
 for ci,case in enumerate(spec['cases']):
  q,e,y,s,d,tail,seeds=synthetic_samples(ci,case,spec)
  for h in spec['latencies']:
   t=np.arange(spec['n']);mask=(t>=spec['warmup'])&(t+h<spec['n']);masks=dict(all=mask,early=mask&(t<3113),late=mask&(t>=3113))
   for v in variants:
    z=replay(q,e,y,h,v['kind'],v['memory'],v['c'])
    expected=analytic_score_diagnostics(z['var'],z['es'],s[:,None],d[:,None],'bounded' if tail=='uniform' else tail)['expected_fz0'];excess=expected-np.log(s*(1+d))[:,None];real=fz_score(z['var'],z['es'],y)
    for rep in range(spec['replicates']):records.append(dict(case=case,latency=h,replicate=rep,seed=seeds[rep],model=v['name'],periods={k:dict(n=int(m.sum()),conditional_excess_fz0=float(excess[m,rep].mean()),realized_fz0=float(real[m,rep].mean())) for k,m in masks.items()}))
   print('refined synthetic',case,h,flush=True)
 (ROOT/'results/forgetting_refinement_synthetic.json').write_text(json.dumps(dict(records=records,refinement_sha256=sha(path)),indent=2)+'\n')
 old=np.load(ROOT/'results/adaptive_risk_predictions.npz',allow_pickle=False);severity=np.load(ROOT/'results/severity_risk_predictions.npz',allow_pickle=False);dates=old['dates'];dev=[]
 for currency in p['development']['currencies']:
  for h in p['development']['horizons']:
   key=f'{currency}_{h}';allorig=old[key+'_origins'];keep=(dates[allorig]>='2010-01-01')&(dates[allorig]<='2019-12-31');orig=allorig[keep];qb=old[key+'_base_candidate_var'][keep];eb=old[key+'_base_candidate_es'][keep]
   q=np.column_stack([qb,qb[:,5],qb[:,5]]);e=np.column_stack([eb,severity[key+'_candidate_es'][keep,0,0],severity[key+'_candidate_es'][keep,0,1]]);y=old[key+'_realized'][keep].copy();mature=np.arange(len(orig))+h<len(orig);y[~mature]=np.nan
   valid=mature&(dates[orig]>='2015-01-01')&(dates[np.minimum(orig+h,len(dates)-1)]<='2019-12-31')
   for v in variants:
    z=replay(q,e,y,h,v['kind'],v['memory'],v['c'],orig);dev.append(dict(currency=currency,horizon=h,model=v['name'],n=int(valid.sum()),mean_fz0=float(fz_score(z['var'][valid],z['es'][valid],y[valid]).mean())))
   print('refined development',key,flush=True)
 (ROOT/'results/forgetting_refinement_development.json').write_text(json.dumps(dict(records=dev),indent=2)+'\n')
 first=json.loads((ROOT/'results/forgetting_selection.json').read_text());base=first['candidates']['cumulative'];means={**first['candidates']}
 for v in variants:
  name=v['name'];sm={f'{case}_{h}':float(np.mean([r['periods']['all']['conditional_excess_fz0'] for r in records if r['case']==case and r['latency']==h and r['model']==name])) for case in spec['cases'] for h in spec['latencies']}
  means[name]=dict(development_mean=float(np.mean([r['mean_fz0'] for r in dev if r['model']==name])),synthetic_means=sm)
  x=means[name];x['maximum_stationary_penalty']=max(sm[key]-base['synthetic_means'][key] for key in sm if key.startswith('stationary'));x['mean_changing_difference']=float(np.mean([sm[key]-base['synthetic_means'][key] for key in sm if not key.startswith('stationary')]))
  x['eligible']=bool(x['development_mean']<base['development_mean'] and x['maximum_stationary_penalty']<=.02 and x['mean_changing_difference']<0)
 eligible=[name for name,x in means.items() if x['eligible']];primary=min(eligible,key=lambda n:means[n]['development_mean']) if eligible else 'cumulative'
 allvariants=[dict(**v,c=p['c']) for v in p['variants']]+variants
 selection=dict(schema='gabriel.forgetting.final-selection.v1',primary_model=primary,eligible=eligible,candidates=means,all_variants=allvariants,design_sha256=sha(ROOT/'results/forgetting_design_v2.json'),refinement_sha256=sha(path),first_selection_sha256=sha(ROOT/'results/forgetting_selection.json'),source_sha256={name:sha(ROOT/'results'/name) for name in ['forgetting_refinement_synthetic.json','forgetting_refinement_development.json']},execution_seconds=time.perf_counter()-start)
 (ROOT/'results/forgetting_final_selection.json').write_text(json.dumps(selection,indent=2)+'\n')
 for n,x in means.items():print(n,x['development_mean'],x['maximum_stationary_penalty'],x['mean_changing_difference'],x['eligible'],flush=True)
 print('PRIMARY',primary,'seconds',selection['execution_seconds'],flush=True)
if __name__=='__main__':main()
