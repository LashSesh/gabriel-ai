"""Development-only aggregation screening: fit 2010--14, validate 2015--19.

No forecasts/outcomes later than 2019 enter any score, fit or replay.
The parent archives are earlier published work, not pristine data.
"""
import sys,json,hashlib,time
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'reproduction'))
from aggregate_risk import (transformed_mix,arithmetic_mix,fit_static,replay_adagrad,EXPERTS)
from ecb_risk import fz_score


def main():
    start=time.perf_counter()
    parent_path=ROOT/'results/adaptive_risk_predictions.npz'
    severity_path=ROOT/'results/severity_risk_predictions.npz'
    parent=np.load(parent_path,allow_pickle=False)
    severity=np.load(severity_path,allow_pickle=False)
    dates=parent['dates'];out=dict(schema='gabriel.aggregate.development-screen.v1',
      fit_period=['2010-01-01','2014-12-31'],validation_period=['2015-01-01','2019-12-31'],
      adamultipliers=[.1,.3,1.],rho=.01,weight_learning_start='2010-01-01',experts=list(EXPERTS),contracts=[],
      source_hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [parent_path,severity_path]},
      note='Design screening only; all evaluated dates <=2019. Historical development data have previously been examined.')
    for currency in ['USD','GBP','JPY','CHF']:
        for h in [1,5]:
            key=f'{currency}_{h}';all_origins=parent[key+'_origins']
            keep=(dates[all_origins]>='2010-01-01')&(dates[all_origins]<='2019-12-31');origins=all_origins[keep]
            q0=parent[key+'_base_candidate_var'][keep]
            e0=parent[key+'_base_candidate_es'][keep]
            q=np.column_stack([q0,q0[:,5],q0[:,5]])
            e=np.column_stack([e0,severity[key+'_candidate_es'][keep,0,0],
                                  severity[key+'_candidate_es'][keep,0,1]])
            y=parent[key+'_realized'][keep].copy();matured=np.arange(len(y))+h<len(y)
            y[~matured]=np.nan
            fit=matured&(dates[origins]>='2010-01-01')&(dates[np.minimum(origins+h,len(dates)-1)]<='2014-12-31')
            valid=matured&(dates[origins]>='2015-01-01')&(dates[np.minimum(origins+h,len(dates)-1)]<='2019-12-31')
            record=dict(currency=currency,horizon=h,n_fit=int(fit.sum()),n_validation=int(valid.sum()),
                        fits={},models={})
            def score(label,Q,E):
                vals=fz_score(Q[valid],E[valid],y[valid])
                record['models'][label]=dict(mean_fz0=float(vals.mean()),
                    exceedance_fraction=float(np.mean(y[valid]>Q[valid])),mean_var=float(Q[valid].mean()),
                    mean_es=float(E[valid].mean()))
            expert_train=fz_score(q[fit],e[fit],y[fit,None]).mean(axis=0)
            winner=int(np.argmin(expert_train));record['dev_best_expert']=EXPERTS[winner]
            record['expert_fit_scores']=expert_train.tolist()
            for j,label in enumerate(EXPERTS):score(label,q[:,j],e[:,j])
            score('dev_best_expert',q[:,winner],e[:,winner])
            uniform=np.full(q.shape[1],1/q.shape[1])
            score('uniform_transformed',*transformed_mix(q,e,uniform))
            score('uniform_arithmetic',*arithmetic_mix(q,e,uniform))
            for geometry,mix in [('transformed',transformed_mix),('arithmetic',arithmetic_mix)]:
                fitted=fit_static(q[fit],e[fit],y[fit],geometry=geometry,rho=.01)
                record['fits'][geometry]=fitted
                score('static_'+geometry,*mix(q,e,fitted['weights']))
            for c in [.1,.3,1.]:
                trace=replay_adagrad(q,e,y,h,c,origins)
                score('online_c'+str(c),trace['var'],trace['es'])
            out['contracts'].append(record)
            print(key,{label:round(v['mean_fz0'],6) for label,v in record['models'].items()
                if label in ['fast_fhs','dev_best_expert','static_transformed','static_arithmetic',
                             'online_c0.1','online_c0.3','online_c1.0']},
                  'gap',record['fits']['transformed']['certificate']['numerical_gap'],flush=True)
    labels=list(out['contracts'][0]['models']);out['macro']={}
    for label in labels:
        values=[r['models'][label]['mean_fz0'] for r in out['contracts']]
        out['macro'][label]=dict(mean_contract_fz0=float(np.mean(values)),
           mean_delta_fast=float(np.mean([v-r['models']['fast_fhs']['mean_fz0'] for v,r in zip(values,out['contracts'])])),
           wins_fast=int(sum(v<r['models']['fast_fhs']['mean_fz0'] for v,r in zip(values,out['contracts']))),
           mean_delta_devbest=float(np.mean([v-r['models']['dev_best_expert']['mean_fz0'] for v,r in zip(values,out['contracts'])])),
           wins_devbest=int(sum(v<r['models']['dev_best_expert']['mean_fz0'] for v,r in zip(values,out['contracts']))))
    out['elapsed_seconds']=time.perf_counter()-start
    target=ROOT/'results/aggregate_development_screen_replayed.json'
    target.write_text(json.dumps(out,indent=2,allow_nan=False)+'\n')
    print('SUMMARY',json.dumps(out['macro'],indent=2),flush=True)
    print('SAVED',target,'seconds',out['elapsed_seconds'],flush=True)


if __name__=='__main__':main()
