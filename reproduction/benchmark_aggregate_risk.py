"""Run the prospectively specified new-currency forecast aggregation benchmark.

The protocol is written and primary method selected before this entry point is
executed. No model is tuned on the test losses. Historical ECB reference rates
are current-vintage informational observations, not executable quotes.
"""
from pathlib import Path
import hashlib
import json
import time
import numpy as np

from ecb_risk import load_rates, forecast_candidates, fz_score, metrics
from severity_risk import replay_severity
from aggregate_risk import (EXPERTS, BETA, validate_bank, fit_static,
    transformed_mix, arithmetic_mix, replay_adagrad)

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_FILE = ROOT/'results/aggregate_risk_protocol.json'


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def online_name(c):
    return 'adagrad_c'+format(float(c), 'g').replace('.', 'p')


def dated_mask(dates, origins, horizon, matured, bounds):
    mask = np.zeros(len(origins), bool)
    mask[matured] = ((dates[origins[matured]] >= bounds[0]) &
                     (dates[origins[matured]+horizon] <= bounds[1]))
    return mask


def jensen_components(q, e, y, weights, matured):
    """Retain both nonnegative components, evaluated in binary64 arithmetic."""
    n, k = q.shape
    weights = np.asarray(weights, float)
    if weights.shape == (k,):
        weights = np.broadcast_to(weights, (n,k))
    if weights.shape != (n,k):
        raise ValueError('one simplex vector per forecast required')
    a, b = q/e, 1/e
    aw, bw = np.sum(a*weights,axis=1), np.sum(b*weights,axis=1)
    log_part = np.full(n,np.nan)
    hinge_part = np.full(n,np.nan)
    gap = np.full(n,np.nan)
    reference_gap = np.full(n,np.nan)
    m = matured
    log_part[m] = np.log(bw[m])-np.sum(weights[m]*np.log(b[m]),axis=1)
    hinge_part[m] = (np.sum(weights[m]*np.maximum(y[m,None]*b[m]-a[m],0),axis=1)
                       -np.maximum(y[m]*bw[m]-aw[m],0))/BETA
    gap[m] = log_part[m]+hinge_part[m]
    expert_score = fz_score(q[m],e[m],y[m,None])
    emitted_score = fz_score(aw[m]/bw[m],1/bw[m],y[m])
    reference_gap[m] = np.sum(weights[m]*expert_score,axis=1)-emitted_score
    if np.any(gap[m] < -1e-10):
        raise AssertionError('negative Jensen gap exceeds binary64 tolerance')
    if np.max(np.abs(gap[m]-reference_gap[m])) > 1e-10:
        raise AssertionError('Jensen component identity discrepancy')
    return log_part, hinge_part, gap, reference_gap


def metric_record(q,e,y):
    record = metrics(q,e,y)
    record['absolute_frequency_error'] = abs(record['exceedance_fraction']-BETA)
    record['mean_normalized_es_residual'] = float(np.mean(
        (q+np.maximum(y-q,0)/BETA-e)/q))
    return record


def replay_from_start(q,e,y,h,c,origins,start_index):
    """Expand the declared learning-period replay with unavailable prefix rows."""
    replay = replay_adagrad(q[start_index:],e[start_index:],y[start_index:],h,c,
                           origins=origins[start_index:])
    n,k = q.shape
    uniform = np.full(k,1/k)
    for field,value in list(replay.items()):
        if field.startswith('final_'):
            continue
        if field in ['var','es']:
            prefix = transformed_mix(q[:start_index],e[:start_index],uniform)[
                0 if field=='var' else 1] if start_index else np.empty(0)
        elif field=='issued_weights':
            prefix = np.broadcast_to(uniform,(start_index,k)).copy()
        elif field=='matured':
            prefix = np.zeros(start_index,bool)
        else:
            prefix = np.full((start_index,)+value.shape[1:],np.nan)
        replay[field] = np.concatenate([prefix,value],axis=0)
    return replay


def run(p, protocol_hash):
    """Execute only after source, parent and external primary-selection checks."""
    parent_path = ROOT/p['bank']['parent_protocol_file']
    if sha256(parent_path) != p['bank']['parent_protocol_sha256']:
        raise ValueError('parent protocol changed')
    parent = json.loads(parent_path.read_text())
    if parent['source_csv_sha256'] != p['source_csv_sha256']:
        raise ValueError('mismatched source snapshot')
    source_path = ROOT/p['source_file']
    if sha256(source_path) != p['source_csv_sha256']:
        raise ValueError('source data changed')
    # load_rates reads only these named currency columns. Do not replace a
    # missing or invalid rate or a nonpositive forecast by another value.
    spec, bank, aggregation = p['new_assets'],p['bank'],p['aggregation']
    parent = dict(parent, currencies=spec['currencies'],
                  horizons_observed_intervals=spec['horizons'])
    dates,rates = load_rates(parent)
    if len(dates) != p['source_observations'] or str(dates[-1]) != p['source_last_date']:
        raise ValueError('source date coverage changed')
    states,candidates = forecast_candidates(rates,parent)
    cs = aggregation['eta_scales']
    names = list(EXPERTS)+['selected_expert','arithmetic_fit','transformed_fit',
        'arithmetic_uniform','transformed_uniform']+[online_name(c) for c in cs]
    if p['primary_model'] not in names:
        raise ValueError('primary method is not in the frozen candidate bank')
    if len(set(names)) != len(names):
        raise ValueError('duplicate model names')
    archive = dict(dates=dates,rates=rates,currencies=np.array(spec['currencies']),
        models=np.array(names),experts=np.array(EXPERTS),online_scales=np.array(cs),
        variance_states=states,
        jensen_models=np.array(['transformed_fit','transformed_uniform']+
                                [online_name(c) for c in cs]))
    output = dict(schema='gabriel.aggregate-risk.new-assets.v1',
        protocol_sha256=protocol_hash,source_csv_sha256=p['source_csv_sha256'],
        primary_model=p['primary_model'],model_order=names,expert_order=list(EXPERTS),
        currencies=spec['currencies'],horizons=spec['horizons'],contracts=[],
        design_history=p['design_history'],
        common_window='All horizons use origin dates through the last source index minus maximum horizon; four additional matured one-step origins are retained separately.',
        static_availability='Fitted weights are available after the last development outcome receipt; earlier archived fitted formulas are retrospective and carry an explicit unavailable mask.',
        online_availability='Online weight learning starts at the declared first 2010 origin. Earlier uniform formulas are unavailable placeholders, with NaN updates and an explicit false availability mask; base experts remain warmed from their original first eligible origins.',
        pending_convention='Pending targets retain issued forecasts and weights; outcomes, scores and update states are NaN.',
        aggregation_weighting='The primary mean difference equally weights eight currency-horizon contracts on the same origin dates.',
        numeric_status='binary64 computations; no directed-rounding certificate')
    common_last = len(dates)-1-max(spec['horizons'])
    uniform = np.full(len(EXPERTS),1/len(EXPERTS))
    max_jensen_error = 0.
    for ci,currency in enumerate(spec['currencies']):
        for h in spec['horizons']:
            key = f'{currency}_{h}'
            origins,base_q,base_e = candidates[ci,h]
            matured = origins+h < len(dates)
            y = np.full(len(origins),np.nan)
            y[matured] = 100*np.log(rates[origins[matured]+h,ci]/rates[origins[matured],ci])
            severity = [replay_severity(base_q[:,5],y,h,d,
                bank['initial_ratio'],bank['ratio_cap']) for d in bank['severity_half_lives']]
            q = np.column_stack([base_q,base_q[:,5],base_q[:,5]])
            e = np.column_stack([base_e]+[trace['es'] for trace in severity])
            validate_bank(q,e)
            fit_mask = dated_mask(dates,origins,h,matured,spec['development'])
            if not fit_mask.any():
                raise ValueError('empty development fitting window')
            fit_kwargs = dict(rho=aggregation['ridge'], beta=BETA,
                ftol=aggregation['optimizer']['ftol'],
                maxiter=aggregation['optimizer']['maxiter'])
            fits = {geometry:fit_static(q[fit_mask],e[fit_mask],y[fit_mask],
                                        geometry=geometry,**fit_kwargs)
                    for geometry in ['arithmetic','transformed']}
            fitted_weights = {g:np.array(record['weights']) for g,record in fits.items()}
            dev_scores = np.mean(fz_score(q[fit_mask],e[fit_mask],y[fit_mask,None]),axis=0)
            chosen = int(np.argmin(dev_scores))
            chosen_weight = np.eye(len(EXPERTS))[chosen]
            online_available = dates[origins]>=aggregation['online_start_date']
            start_index = int(np.flatnonzero(online_available)[0])
            online = [replay_from_start(q,e,y,h,c,origins,start_index) for c in cs]
            pairs = [(q[:,j],e[:,j]) for j in range(q.shape[1])]
            pairs += [(q[:,chosen],e[:,chosen]),
                arithmetic_mix(q,e,fitted_weights['arithmetic']),
                transformed_mix(q,e,fitted_weights['transformed']),
                arithmetic_mix(q,e,uniform),transformed_mix(q,e,uniform)]
            pairs += [(trace['var'],trace['es']) for trace in online]
            model_q,model_e = (np.stack([pair[j] for pair in pairs],axis=1) for j in [0,1])
            validate_bank(model_q,model_e)
            model_fz0 = np.full(model_q.shape,np.nan)
            model_fz0[matured] = fz_score(model_q[matured],model_e[matured],y[matured,None])
            common = matured & (dates[origins]>=spec['test_origin_start']) & (origins<=common_last)
            extra = matured & (origins>common_last) if h==1 else np.zeros(len(origins),bool)
            masks = dict(development=fit_mask,common_test=common,extra_h1=extra,
                test_all_matured=matured&(dates[origins]>=spec['test_origin_start']))
            for period,bounds in spec['secondary_periods'].items():
                masks[period] = dated_mask(dates,origins,h,matured,bounds)
            last_fit_receipt = int(np.max(origins[fit_mask]+h))
            jensen_weights = [fitted_weights['transformed'],uniform]+[
                                trace['issued_weights'] for trace in online]
            components = [jensen_components(q,e,y,w,matured) for w in jensen_weights]
            arrays = dict(origins=origins,realized=y,matured=matured,
                expert_var=q,expert_es=e,model_var=model_q,model_es=model_e,
                model_fz0=model_fz0,static_fit_mask=fit_mask,
                static_available_mask=origins>=last_fit_receipt,
                online_available_mask=online_available,
                common_test_mask=common,extra_h1_mask=extra,
                uniform_weights=uniform,selected_expert_weights=chosen_weight,
                static_arithmetic_weights=fitted_weights['arithmetic'],
                static_transformed_weights=fitted_weights['transformed'],
                development_expert_scores=dev_scores,
                severity_issued_raw_ratio=np.stack([t['issued_raw_ratio'] for t in severity],axis=1),
                severity_issued_ratio=np.stack([t['issued_ratio'] for t in severity],axis=1),
                severity_cap_flags=np.stack([t['cap_flag'] for t in severity],axis=1),
                severity_response=severity[0]['R'],
                severity_preupdate_ratio=np.stack([t['preupdate_ratio'] for t in severity],axis=1),
                severity_postupdate_ratio=np.stack([t['postupdate_ratio'] for t in severity],axis=1))
            for field in ['issued_weights','preupdate_weights','postupdate_weights','gradient',
                'centered_gradient','step','gradient_norm_squared','accumulator_before',
                'accumulator_after','score','final_weights','final_accumulators','matured']:
                arrays['online_'+field] = np.stack([t[field] for t in online],axis=1)
            for j,field in enumerate(['jensen_log_component','jensen_hinge_component',
                                     'jensen_gap','jensen_reference_gap']):
                arrays[field] = np.stack([parts[j] for parts in components],axis=1)
            max_jensen_error = max(max_jensen_error,float(np.nanmax(np.abs(
                arrays['jensen_gap']-arrays['jensen_reference_gap']))))
            for period,mask in masks.items(): arrays['mask_'+period] = mask
            for field,array in arrays.items(): archive[key+'_'+field] = array
            record = dict(currency=currency,horizon=h,static_fits=fits,
                selected_expert=EXPERTS[chosen],selected_expert_index=chosen,
                development_expert_scores=dict(zip(EXPERTS,dev_scores.tolist())),
                static_fit_count=int(fit_mask.sum()),
                static_available_from_origin_index=last_fit_receipt,
                static_available_from_date=str(dates[last_fit_receipt]),
                online_available_from_origin_index=int(origins[start_index]),
                online_available_from_date=str(dates[origins[start_index]]),
                all_history_cap_count={str(d):int(trace['cap_flag'].sum())
                    for d,trace in zip(bank['severity_half_lives'],severity)},
                pending_count=int((~matured).sum()),periods={},models={})
            for period,mask in masks.items():
                selected=origins[mask]
                record['periods'][period]=dict(n=int(mask.sum()),
                    first_origin=str(dates[selected[0]]) if len(selected) else None,
                    last_origin=str(dates[selected[-1]]) if len(selected) else None,
                    last_target=str(dates[selected[-1]+h]) if len(selected) else None)
            for j,model in enumerate(names):
                record['models'][model]={period:metric_record(model_q[mask,j],model_e[mask,j],y[mask])
                    for period,mask in masks.items() if mask.any()}
            record['jensen_common_test']={name:dict(
                mean_log_component=float(arrays['jensen_log_component'][common,j].mean()),
                mean_hinge_component=float(arrays['jensen_hinge_component'][common,j].mean()),
                mean_gap=float(arrays['jensen_gap'][common,j].mean()),
                minimum_gap=float(arrays['jensen_gap'][common,j].min()))
                for j,name in enumerate(archive['jensen_models'].tolist())}
            output['contracts'].append(record)
            print('new asset',key,'n',int(common.sum()),'primary',p['primary_model'],
                'FZ0',record['models'][p['primary_model']]['common_test']['mean_fz0'],
                'fitgap',fits['transformed']['certificate']['numerical_gap'],flush=True)
    output['period_contract_cases']={period:sum(r['periods'][period]['n'] for r in output['contracts'])
        for period in output['contracts'][0]['periods']}
    output['period_forecast_pairs']={period:n*len(names) for period,n in output['period_contract_cases'].items()}
    output['archived_candidate_pairs']=sum(len(archive[f"{r['currency']}_{r['horizon']}_origins"])*len(names)
        for r in output['contracts'])
    output['max_jensen_identity_error']=max_jensen_error
    output['common_test_last_origin']=str(dates[common_last])
    output['primary_equal_contract_mean_fz0']=float(np.mean([
        r['models'][p['primary_model']]['common_test']['mean_fz0'] for r in output['contracts']]))
    prediction_path=ROOT/'results/aggregate_risk_predictions.npz'
    np.savez_compressed(prediction_path,**archive)
    output['predictions_sha256']=sha256(prediction_path)
    return output


def main():
    start=time.perf_counter()
    raw=PROTOCOL_FILE.read_bytes()
    protocol_hash=hashlib.sha256(raw).hexdigest()
    p=json.loads(raw)
    # The separate seal detects post-freeze protocol mutation without requiring
    # the source file to hard-code a yet-to-be-selected primary method.
    expected=(ROOT/'results/aggregate_risk_protocol.sha256').read_text().split()[0]
    if protocol_hash != expected:
        raise ValueError('frozen aggregation protocol changed')
    selection=ROOT/p['primary_selection_file']
    if sha256(selection)!=p['primary_selection_sha256']:
        raise ValueError('pre-test primary selection changed')
    output=run(p,protocol_hash)
    output['source_sha256']={name:sha256(ROOT/'reproduction'/name) for name in
        ['benchmark_aggregate_risk.py','aggregate_risk.py','ecb_risk.py','severity_risk.py']}
    output['execution_seconds']=time.perf_counter()-start
    path=ROOT/'results/aggregate_risk_results.json'
    path.write_text(json.dumps(output,indent=2,allow_nan=False)+'\n')
    print('saved',output['period_contract_cases'],'seconds',round(output['execution_seconds'],3),flush=True)


if __name__=='__main__': main()
