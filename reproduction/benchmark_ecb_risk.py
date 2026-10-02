"""Execute the fixed chronological risk-forecast comparison on the ECB snapshot."""
from pathlib import Path
import json,hashlib,time
from fractions import Fraction
import numpy as np
from ecb_risk import load_protocol,load_rates,forecast_candidates,fz_score,metrics,PROTOCOL_HASH

ROOT=Path(__file__).resolve().parents[1]

def main():
    start=time.perf_counter();p=load_protocol();dates,rates=load_rates(p)
    states,preds=forecast_candidates(rates,p)
    archive=dict(dates=dates,rates=rates,variances=states)
    output=dict(schema='gabriel.ecb-risk.results.v1',protocol_sha256=PROTOCOL_HASH,
                source_csv_sha256=p['source_csv_sha256'],raw_observations=len(dates),
                raw_date_range=[str(dates[0]),str(dates[-1])],contracts=[],
                scope='retrospective chronological current-vintage risk forecasts; not trading')
    for (c,h),(ends,q,e) in sorted(preds.items()):
        valid=ends+h<len(dates);ends=ends[valid];q=q[valid];e=e[valid]
        y=100*np.log(rates[ends+h,c]/rates[ends,c])
        name=p['currencies'][c];key=f'{name}_{h}'
        archive[key+'_origins']=ends;archive[key+'_candidate_var']=q;archive[key+'_candidate_es']=e
        archive[key+'_realized']=y
        masks={period:(dates[ends]>=interval[0])&(dates[ends+h]<=interval[1])
               for period,interval in [('development',p['development']),('test',p['test'])]}
        dev=masks['development'];test=masks['test']
        scores=fz_score(q,e,y[:,None],p['alpha'])
        means=scores[dev,1:].mean(axis=0);chosen=int(np.argmin(means))
        primary=p['fast_weights'].index(p['primary_weight'])
        columns=[0,1+p['fast_weights'].index('1'),1+p['fast_weights'].index('0'),1+primary,1+chosen]
        contract=dict(currency=name,horizon=h,selected_weight=p['fast_weights'][chosen],
             development_candidate_fz0={w:float(v) for w,v in zip(p['fast_weights'],means)},
             candidate_columns=columns,models={})
        for model,j in zip(p['models'],columns):
            record={period:metrics(q[m,j],e[m,j],y[m],p['alpha']) for period,m in masks.items()}
            record['yearly_test']={}
            for year in range(2020,2026):
                m=test & (np.char.startswith(dates[ends],str(year)))
                record['yearly_test'][str(year)]=metrics(q[m,j],e[m,j],y[m],p['alpha'])
            contract['models'][model]=record
        contract['periods']={period:dict(n=int(m.sum()),first_origin=str(dates[ends[m][0]]),
            last_origin=str(dates[ends[m][-1]]),last_target=str(dates[ends[m][-1]+h])) for period,m in masks.items()}
        output['contracts'].append(contract)
        print(name,h,'selected',contract['selected_weight'],'testn',int(test.sum()),
              'scores',{m:round(v['test']['mean_fz0'],5) for m,v in contract['models'].items()},flush=True)
    for file in ['ecb_risk.py','benchmark_ecb_risk.py']:
        output.setdefault('source_sha256',{})[file]=hashlib.sha256((ROOT/'reproduction'/file).read_bytes()).hexdigest()
    output['test_contract_cases']=sum(c['periods']['test']['n'] for c in output['contracts'])
    output['test_forecast_pairs']=output['test_contract_cases']*len(p['models'])
    output['seconds']=time.perf_counter()-start
    np.savez_compressed(ROOT/'results/ecb_risk_predictions.npz',**archive)
    output['predictions_sha256']=hashlib.sha256((ROOT/'results/ecb_risk_predictions.npz').read_bytes()).hexdigest()
    (ROOT/'results/ecb_risk_results.json').write_text(json.dumps(output,indent=2,allow_nan=False)+'\n')
    print('saved',output['test_forecast_pairs'],'testforecastpairs',round(output['seconds'],3),'seconds')

if __name__=='__main__':main()
