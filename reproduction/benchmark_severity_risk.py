"""Execute the frozen market and independently seeded severity comparisons."""
from pathlib import Path
import hashlib
import json
import time
import numpy as np
from ecb_risk import fz_score, metrics
from severity_risk import (load_protocol, replay_severity, replay_frequency,
    synthetic_sample, analytic_score_diagnostics, BETA, PROTOCOL_HASH)

ROOT = Path(__file__).resolve().parents[1]


def fit_ratio(q,y,mask,cap):
    if not mask.any():
        raise ValueError('empty static fitting sample')
    raw = float(np.mean(1+np.maximum(y[mask]-q[mask],0)/(BETA*q[mask])))
    return raw,min(cap,max(1.0,raw))


def assemble(q_streams,e_streams,y,latency,fit_mask,p):
    half_lives = p['half_lives_completed_observations']
    traces = [[replay_severity(q_streams[:,s],y,latency,d,p['initial_ratio'],p['ratio_cap'])
               for d in half_lives] for s in range(2)]
    statics = [fit_ratio(q_streams[:,s],y,fit_mask,p['ratio_cap']) for s in range(2)]
    pairs = [(q_streams[:,0],e_streams[:,0]),(q_streams[:,1],e_streams[:,1]),
             (q_streams[:,0],traces[0][0]['es']),(q_streams[:,1],traces[1][0]['es']),
             (q_streams[:,0],traces[0][1]['es']),(q_streams[:,1],traces[1][1]['es']),
             (q_streams[:,0],q_streams[:,0]*statics[0][1]),
             (q_streams[:,1],q_streams[:,1]*statics[1][1])]
    q,e = (np.stack([pair[j] for pair in pairs],axis=1) for j in range(2))
    caps = np.stack([np.zeros(len(y),bool),np.zeros(len(y),bool),traces[0][0]['cap_flag'],
        traces[1][0]['cap_flag'],traces[0][1]['cap_flag'],traces[1][1]['cap_flag'],
        np.full(len(y),statics[0][0]>p['ratio_cap']),
        np.full(len(y),statics[1][0]>p['ratio_cap'])],axis=1)
    archive = dict(q_streams=q_streams,base_es_streams=e_streams,model_var=q,model_es=e,
                   model_cap_flags=caps,static_raw_ratios=np.array([r[0] for r in statics]),
                   static_ratios=np.array([r[1] for r in statics]))
    for field in ['es','issued_raw_ratio','issued_ratio','cap_flag','preupdate_ratio','postupdate_ratio']:
        archive['candidate_'+field] = np.stack([np.stack([t[field] for t in stream],axis=1)
                                                for stream in traces],axis=1)
    archive['R'] = np.stack([traces[s][0]['R'] for s in range(2)],axis=1)
    for s in range(2):
        if not np.array_equal(traces[s][0]['R'],traces[s][1]['R'],equal_nan=True):
            raise AssertionError('responses must be independent of severity half-life')
    return archive


def market_metrics(q,e,y,cap_flags):
    record = metrics(q,e,y)
    record['mean_normalized_es_residual'] = float(np.mean((q+np.maximum(y-q,0)/BETA-e)/q))
    record['cap_count'] = int(cap_flags.sum())
    record['cap_fraction'] = float(cap_flags.mean())
    return record


def run_market(p):
    archive_path = ROOT/'results/adaptive_risk_predictions.npz'
    if hashlib.sha256(archive_path.read_bytes()).hexdigest()!=p['parent_predictions_sha256']:
        raise ValueError('parent adaptive forecast archive changed')
    parent = np.load(archive_path,allow_pickle=False)
    dates,rates = parent['dates'],parent['rates']
    params = p['market']
    output = dict(schema='gabriel.severity-risk.market.v1',protocol_sha256=PROTOCOL_HASH,
       parent_predictions_sha256=p['parent_predictions_sha256'],
       design_history=params['design_history'],contracts=[],
       normalized_es_residual='(Q + max(Y-Q,0)/beta - E)/Q = R-E/Q',
       pending_convention='Responses and pre/post-update states NaN; issued forecasts and states retained.',
       static_availability='Static formulas before the last development target receipt are retrospective/in-sample evaluations; the fitted ratio is first available after processing that receipt, before issuing at that same origin.',
       model_order=p['models'])
    archive = dict(dates=dates,rates=rates,models=np.array(p['models']),
       stream_order=np.array(p['quantile_streams']),
       half_lives=np.array(p['half_lives_completed_observations']),
       decays=2.0**(-1/np.array(p['half_lives_completed_observations'],float)))
    periods = ['development','retrospective_2020_2025','retrospective_2026']
    for currency in params['currencies']:
        for h in params['horizons']:
            key = f'{currency}_{h}'
            origins,y,matured = (parent[key+'_'+field] for field in ['origins','realized','matured'])
            q_streams = np.stack([parent[key+'_base_candidate_var'][:,5],parent[key+'_lane_var'][:,2]],axis=1)
            e_streams = np.stack([parent[key+'_base_candidate_es'][:,5],parent[key+'_lane_es'][:,2]],axis=1)
            masks = {}
            for period in periods:
                bounds=params[period];mask=np.zeros(len(origins),bool)
                mask[matured]=(dates[origins[matured]]>=bounds[0])&(dates[origins[matured]+h]<=bounds[1])
                masks[period]=mask
            arrays=assemble(q_streams,e_streams,y,h,masks['development'],p)
            last_fit_receipt=int(np.max(origins[masks['development']]+h))
            arrays.update(origins=origins,realized=y,matured=matured,
                          static_fit_mask=masks['development'],
                          static_available_mask=origins>=last_fit_receipt)
            for field,array in arrays.items():archive[key+'_'+field]=array
            record=dict(currency=currency,horizon=h,
                static_raw_ratios={s:float(v) for s,v in zip(p['quantile_streams'],arrays['static_raw_ratios'])},
                static_ratios={s:float(v) for s,v in zip(p['quantile_streams'],arrays['static_ratios'])},
                static_fit_count=int(masks['development'].sum()),
                static_available_from_origin_index=last_fit_receipt,
                static_available_from_date=str(dates[last_fit_receipt]),periods={},models={})
            for period,mask in masks.items():
                selected=origins[mask]
                record['periods'][period]=dict(n=int(mask.sum()),first_origin=str(dates[selected[0]]),
                    last_origin=str(dates[selected[-1]]),last_target=str(dates[selected[-1]+h]))
            for j,model in enumerate(p['models']):
                record['models'][model]={period:market_metrics(arrays['model_var'][mask,j],
                    arrays['model_es'][mask,j],y[mask],arrays['model_cap_flags'][mask,j])
                    for period,mask in masks.items()}
            record['all_history_cap_count']={model:int(arrays['model_cap_flags'][:,j].sum())
                                             for j,model in enumerate(p['models'])}
            output['contracts'].append(record)
            print('market',key,'ratios',record['static_ratios'],'2020-25',
                {m:round(v['retrospective_2020_2025']['mean_fz0'],5) for m,v in record['models'].items()},flush=True)
    output['period_contract_cases']={period:sum(c['periods'][period]['n'] for c in output['contracts']) for period in periods}
    output['period_forecast_pairs']={period:n*len(p['models']) for period,n in output['period_contract_cases'].items()}
    target=ROOT/'results/severity_risk_predictions.npz'
    np.savez_compressed(target,**archive)
    output['predictions_sha256']=hashlib.sha256(target.read_bytes()).hexdigest()
    return output


def run_synthetic(p):
    spec=p['synthetic'];models=p['models']+['oracle_truth']
    output=dict(schema='gabriel.severity-risk.synthetic.v1',protocol_sha256=PROTOCOL_HASH,
       model_order=models,replicates=spec['replicates'],records=[],
       static_cutoff_interpretation='Fit origins with origin+latency<=2000: feedback is received before first scored issue at t=2000.',
       static_availability='Static ratios first available at origin2000; prefit archived static formulas are retrospective values, not issued available forecasts.',
       normalized_es_residual='(Q + max(Y-Q,0)/beta - E)/Q = R-E/Q',
       relative_es_absolute_error='mean(abs(E-true_ES)/true_ES)',
       diagnostic='Conditional expected FZ0 excess over oracle = quantile_score_excess + severity_score_excess; diagnostic added without changing frozen models or selection.',
       pending_loss_note='Synthetic full generated losses retained as DGP truth; pending losses never enter feedback or evaluation.',
       max_decomposition_residual=0.0)
    archive=dict(models=np.array(models),half_lives=np.array(p['half_lives_completed_observations']),
                 decays=2.0**(-1/np.array(p['half_lives_completed_observations'],float)))
    for ci,case in enumerate(spec['cases']):
        for rep in range(spec['replicates']):
            sample=synthetic_sample(ci,rep,p)
            origins,y=sample['origins'],sample['losses']
            for latency in spec['latencies']:
                frequency=replay_frequency(sample['base_var'],sample['base_es'],y,latency)
                matured=origins+latency<len(origins)
                fit=origins+latency<=spec['warmup']
                q_streams=np.stack([sample['base_var'],frequency['var']],axis=1)
                e_streams=np.stack([sample['base_es'],frequency['es']],axis=1)
                arrays=assemble(q_streams,e_streams,y,latency,fit,p)
                q=np.column_stack([arrays['model_var'],sample['true_var']])
                e=np.column_stack([arrays['model_es'],sample['true_es']])
                caps=np.column_stack([arrays['model_cap_flags'],np.zeros(len(origins),bool)])
                diagnostics=analytic_score_diagnostics(q,e,sample['scale'][:,None],
                                            sample['tail_mean'][:,None],sample['tail'])
                score=fz_score(q,e,y[:,None])
                residual=(q+np.maximum(y[:,None]-q,0)/BETA-e)/q
                relative_error=np.abs(e-sample['true_es'][:,None])/sample['true_es'][:,None]
                output['max_decomposition_residual']=max(output['max_decomposition_residual'],
                    float(np.max(np.abs(diagnostics['decomposition_residual']))))
                masks=dict(all=matured&(origins>=spec['warmup']),
                           early=matured&(origins>=spec['warmup'])&(origins<4000),
                           late=matured&(origins>=4000))
                record=dict(case=case['name'],case_index=ci,replicate=rep,latency=latency,
                    seed=sample['seed'],static_fit_count=int(fit.sum()),
                    static_raw_ratios=arrays['static_raw_ratios'].tolist(),
                    static_ratios=arrays['static_ratios'].tolist(),models={})
                for j,model in enumerate(models):
                    record['models'][model]={}
                    for period,mask in masks.items():
                        record['models'][model][period]=dict(n=int(mask.sum()),
                            realized_mean_fz0=float(score[mask,j].mean()),
                            analytic_conditional_expected_fz0=float(diagnostics['expected_fz0'][mask,j].mean()),
                            relative_es_absolute_error=float(relative_error[mask,j].mean()),
                            breach_fraction=float(np.mean(y[mask]>q[mask,j])),
                            normalized_es_residual=float(residual[mask,j].mean()),
                            cap_fraction=float(caps[mask,j].mean()),
                            quantile_score_excess=float(diagnostics['quantile_score_excess'][mask,j].mean()),
                            severity_score_excess=float(diagnostics['severity_score_excess'][mask,j].mean()))
                output['records'].append(record)
                if rep==0:
                    key=f'{case["name"]}_{latency}'
                    arrays.update(origins=origins,losses=y,scale=sample['scale'],tail_mean=sample['tail_mean'],
                        true_var=sample['true_var'],true_es=sample['true_es'],generated_tail=sample['generated_tail'],
                        model_var=q,model_es=e,model_cap_flags=caps,matured=matured,static_fit_mask=fit,
                        static_available_mask=origins>=spec['warmup'],
                        seed=np.array(sample['seed']))
                    for field in ['var','es','issued_units','preupdate_units','postupdate_units','projection_units','matured_hit']:
                        arrays['frequency_'+field]=frequency[field]
                    for field,array in diagnostics.items():arrays['analytic_'+field]=array
                    for field,array in arrays.items():archive[key+'_'+field]=array
        records=[r for r in output['records'] if r['case']==case['name']]
        for latency in spec['latencies']:
            group=[r for r in records if r['latency']==latency]
            print('synthetic',case['name'],latency,'lateexpected',
                {m:round(float(np.mean([r['models'][m]['late']['analytic_conditional_expected_fz0'] for r in group])),5)
                 for m in models},flush=True)
    target=ROOT/'results/severity_synthetic_results.npz'
    np.savez_compressed(target,**archive)
    output['exemplar_predictions_sha256']=hashlib.sha256(target.read_bytes()).hexdigest()
    output['replicate_contracts']=len(output['records'])
    output['reported_aggregate_records']=len(output['records'])*len(models)*3
    return output


def main():
    start=time.perf_counter();p=load_protocol()
    market=run_market(p)
    synthetic=run_synthetic(p)
    hashes={name:hashlib.sha256((ROOT/'reproduction'/name).read_bytes()).hexdigest()
            for name in ['severity_risk.py','benchmark_severity_risk.py','ecb_risk.py']}
    for output,name in [(market,'severity_risk_results.json'),(synthetic,'severity_synthetic_results.json')]:
        output['source_sha256']=hashes
        output['combined_execution_seconds']=time.perf_counter()-start
        (ROOT/'results'/name).write_text(json.dumps(output,indent=2,allow_nan=False)+'\n')
    print('saved',market['period_forecast_pairs'],'synthetic',synthetic['replicate_contracts'],
          'elapsed',round(time.perf_counter()-start,3),flush=True)


if __name__=='__main__':main()
