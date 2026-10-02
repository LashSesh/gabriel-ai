"""Execute the sealed transfer test only after final development selection."""
from pathlib import Path
import json,hashlib,time
import numpy as np
from forgetting_risk import replay,ROOT
from aggregate_risk import fit_static,transformed_mix,arithmetic_mix,EXPERTS
from ecb_risk import load_rates,forecast_candidates,fz_score,metrics
from severity_risk import replay_severity
from summarize_aggregate_risk import shared_bootstrap

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
 start=time.perf_counter();path=ROOT/'results/forgetting_market_protocol.json';raw=path.read_bytes();p=json.loads(raw)
 assert sha(path)==path.with_suffix('.sha256').read_text().split()[0]
 selection=ROOT/'results/forgetting_final_selection.json';assert sha(selection)==p['selection_sha256']
 if p['primary_model']=='cumulative':
  status=dict(status='not_executed',reason='No new candidate passed development selection; unused currency outcomes not accessed',currencies=p['currencies'],protocol_sha256=sha(path),selection_sha256=sha(selection))
  (ROOT/'results/forgetting_market_status.json').write_text(json.dumps(status,indent=2)+'\n');print(status);return
 parent=json.loads((ROOT/'results/ecb_risk_protocol.json').read_text());parent['currencies']=p['currencies'];parent['horizons_observed_intervals']=p['horizons']
 assert parent['source_csv_sha256']==p['source_csv_sha256'];dates,rates=load_rates(parent);states,bank=forecast_candidates(rates,parent)
 variants=p['variants'];models=list(EXPERTS)+['selected_expert','arithmetic_fit','arithmetic_uniform','transformed_fit']+[v['name'] for v in variants]
 archive=dict(dates=dates,rates=rates,currencies=np.array(p['currencies']),models=np.array(models),experts=np.array(EXPERTS));records=[];diffs=[];common_origins=None
 for ci,currency in enumerate(p['currencies']):
  for h in p['horizons']:
   key=f'{currency}_{h}';orig,qb,eb=bank[ci,h];y=np.full(len(orig),np.nan);mature=orig+h<len(dates);y[mature]=100*np.log(rates[orig[mature]+h,ci]/rates[orig[mature],ci])
   sev=[replay_severity(qb[:,5],y,h,d,1.5,20)['es'] for d in [125,500]]
   q=np.column_stack([qb,qb[:,5],qb[:,5]]);e=np.column_stack([eb,*sev]);keep=dates[orig]>='2010-01-01';orig,q,e,y=orig[keep],q[keep],e[keep],y[keep];mature=orig+h<len(dates)
   fit=mature&(dates[orig]>='2010-01-01')&(dates[np.minimum(orig+h,len(dates)-1)]<='2019-12-31')
   fits={g:fit_static(q[fit],e[fit],y[fit],g,.01) for g in ['arithmetic','transformed']};chosen=int(np.argmin(fz_score(q[fit],e[fit],y[fit,None]).mean(axis=0)))
   pairs=[(q[:,j],e[:,j]) for j in range(8)]+[(q[:,chosen],e[:,chosen]),arithmetic_mix(q,e,fits['arithmetic']['weights']),arithmetic_mix(q,e,np.full(8,1/8)),transformed_mix(q,e,fits['transformed']['weights'])]
   for v in variants:
    trace=replay(q,e,y,h,v['kind'],v['memory'],v['c'],orig);pairs.append((trace['var'],trace['es']))
    archive[key+'_'+v['name']+'_weights']=trace['issued_weights']
    if v['name'] in [p['primary_model'],'cumulative']:
     for field,array in trace.items():archive[key+'_'+v['name']+'_'+field]=array
   mq,me=(np.column_stack([x[j] for x in pairs]) for j in range(2));score=np.full(mq.shape,np.nan);score[mature]=fz_score(mq[mature],me[mature],y[mature,None])
   common=mature&(dates[orig]>='2020-01-01')&(orig<=len(dates)-1-5);extra=mature&(dates[orig]>='2020-01-01')&(orig>len(dates)-1-5)
   if common_origins is None:common_origins=orig[common]
   assert np.array_equal(common_origins,orig[common])
   masks=dict(common=common,extra_h1=extra,development=fit,secondary_2020_2025=common&(dates[np.minimum(orig+h,len(dates)-1)]<='2025-12-31'),secondary_2026=common&(dates[orig]>='2026-01-01'))
   pi=models.index(p['primary_model']);diffs.append(np.column_stack([score[common,pi]-score[common,models.index(m)] for m in p['comparators']]))
   metrics_record={name:{period:metrics(mq[mask,j],me[mask,j],y[mask]) for period,mask in masks.items() if mask.any()} for j,name in enumerate(models)}
   records.append(dict(currency=currency,horizon=h,selected_expert=EXPERTS[chosen],fits=fits,models=metrics_record,n_common=int(common.sum()),static_available_from=str(dates[np.max(orig[fit]+h)])))
   for field,array in dict(origins=orig,realized=y,matured=mature,expert_var=q,expert_es=e,model_var=mq,model_es=me,model_fz0=score,fit_mask=fit,common_mask=common,extra_h1_mask=extra,static_available_mask=orig>=np.max(orig[fit]+h)).items():archive[key+'_'+field]=array
   print('transfer',key,'primary',metrics_record[p['primary_model']]['common']['mean_fz0'],flush=True)
 bootstrap,arrays=shared_bootstrap(np.stack(diffs,axis=1),p['comparators'],lengths=p['bootstrap']['lengths'],replicates=p['bootstrap']['replicates'],seed=p['bootstrap']['seed'])
 arrays['differences']=np.stack(diffs,axis=1);arrays['common_origins']=common_origins;np.savez_compressed(ROOT/'results/forgetting_market_bootstrap.npz',**arrays)
 np.savez_compressed(ROOT/'results/forgetting_market_predictions.npz',**archive)
 means={name:float(np.mean([r['models'][name]['common']['mean_fz0'] for r in records])) for name in models}
 comparisons={m:dict(difference=means[p['primary_model']]-means[m],contracts_better=sum(r['models'][p['primary_model']]['common']['mean_fz0']<r['models'][m]['common']['mean_fz0'] for r in records)) for m in p['comparators']}
 out=dict(schema='gabriel.forgetting.market.v1',primary_model=p['primary_model'],protocol_sha256=sha(path),model_order=models,records=records,means=means,comparisons=comparisons,bootstrap=bootstrap,common_dates=len(common_origins),common_cases=len(common_origins)*8,common_first=str(dates[common_origins[0]]),common_last=str(dates[common_origins[-1]]),archive_sha256=sha(ROOT/'results/forgetting_market_predictions.npz'),bootstrap_sha256=sha(ROOT/'results/forgetting_market_bootstrap.npz'),execution_seconds=time.perf_counter()-start)
 (ROOT/'results/forgetting_market_results.json').write_text(json.dumps(out,indent=2)+'\n');print('COMPARISONS',comparisons,'GATE',bootstrap['conjunctive_gate_passed'],flush=True)
if __name__=='__main__':main()
