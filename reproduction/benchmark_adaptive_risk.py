"""Execute the frozen delayed tail-feedback comparison on the ECB snapshot."""
from pathlib import Path
from fractions import Fraction
import hashlib
import json
import time
import numpy as np
from ecb_risk import (load_protocol as parent_protocol, load_rates, forecast_candidates,
                      fz_score, metrics, PROTOCOL_HASH as PARENT_HASH)
from adaptive_risk import (load_protocol, replay_controller, risk_strata,
                           exact_accounting, controller_denominator, PROTOCOL_HASH)

ROOT = Path(__file__).resolve().parents[1]


def main():
    start = time.perf_counter()
    p, parent = load_protocol(), parent_protocol()
    if p['parent_protocol_sha256'] != PARENT_HASH or p['source_csv_sha256'] != parent['source_csv_sha256']:
        raise ValueError('parent/source binding mismatch')
    dates, rates = load_rates(parent)
    _, forecasts = forecast_candidates(rates, parent)
    eta_grid = p['eta_grid']
    primary = eta_grid.index(p['primary_eta'])
    static_grid = p['static_theta_grid']
    periods = ['development', 'retrospective', 'temporal_extension']
    archive = dict(dates=dates, rates=rates, eta_grid=np.array(eta_grid),
                   eta_denominators=np.array([controller_denominator(e) for e in eta_grid]),
                   static_theta_grid=np.array(static_grid))
    output = dict(schema='gabriel.adaptive-risk.results.v1', protocol_sha256=PROTOCOL_HASH,
                  parent_protocol_sha256=PARENT_HASH,
                  source_csv_sha256=p['source_csv_sha256'],
                  raw_observations=len(dates), raw_date_range=[str(dates[0]), str(dates[-1])],
                  design_history=p['design_history'],
                  scope='descriptive chronological current-vintage risk forecasts; not trading',
                  archive_pending_update_convention='Pending hits -1 and update units 0; explicit maturity mask. Fields indexed by issuance.',
                  contracts=[])
    candidate_pairs = 0
    for (c, h), (origins, base_q, base_e) in sorted(forecasts.items()):
        name = p['currencies'][c]
        key = f'{name}_{h}'
        matured = origins + h < len(dates)
        y = np.full(len(origins), np.nan)
        y[matured] = 100 * np.log(rates[origins[matured]+h, c] / rates[origins[matured], c])
        masks = {}
        for period in periods:
            interval = p[period]
            mask = np.zeros(len(origins), dtype=bool)
            mask[matured] = ((dates[origins[matured]] >= interval[0]) &
                             (dates[origins[matured]+h] <= interval[1]))
            if not mask.any():
                raise ValueError('empty reporting period')
            masks[period] = mask
        controllers = [replay_controller(origins, base_q[:,5], base_e[:,5], rates[:,c], h, eta)
                       for eta in eta_grid]
        pooled = replay_controller(origins, base_q[:,5], base_e[:,5], rates[:,c], h,
                                   p['primary_eta'], lanes=False)
        static_scale = np.exp(np.array([float(Fraction(t)) for t in static_grid]))
        static_q, static_e = base_q[:,5,None]*static_scale, base_e[:,5,None]*static_scale
        strata, median = risk_strata(base_q[:,5])
        arrays = dict(origins=origins, realized=y, matured=matured,
                      base_candidate_var=base_q, base_candidate_es=base_e,
                      static_var=static_q, static_es=static_e,
                      risk_stratum=strata, prior_var_median=median,
                      pooled_denominator=np.array(pooled['denominator']))
        for field in ['var','es','issued_units','matured_hit','preupdate_units','postupdate_units','projection_units']:
            arrays['lane_'+field] = np.stack([z[field] for z in controllers], axis=1)
            arrays['pooled_'+field] = pooled[field]
        for field, value in arrays.items():
            archive[key+'_'+field] = value
        dev = masks['development']
        lane_means = [float(fz_score(z['var'][dev], z['es'][dev], y[dev]).mean()) for z in controllers]
        static_means = fz_score(static_q[dev], static_e[dev], y[dev,None]).mean(axis=0)
        selected_eta = int(np.argmin(lane_means))
        selected_static = int(np.argmin(static_means))
        contract = dict(currency=name, horizon=h, primary_eta=p['primary_eta'],
                        selected_eta=eta_grid[selected_eta], selected_eta_index=selected_eta,
                        selected_static_theta=static_grid[selected_static], selected_static_index=selected_static,
                        development_lane_fz0=dict(zip(eta_grid, lane_means)),
                        development_static_fz0={k:float(v) for k,v in zip(static_grid,static_means)},
                        periods={}, models={}, candidates={}, controller_accounting={})
        for period, mask in masks.items():
            idx = origins[mask]
            contract['periods'][period] = dict(n=int(mask.sum()), first_origin=str(dates[idx[0]]),
                  last_origin=str(dates[idx[-1]]), last_target=str(dates[idx[-1]+h]))

        def summarize(q, e, mask, trace=None, eta=None, lanes=True):
            if not mask.any():
                return None
            result = metrics(q[mask], e[mask], y[mask])
            result['absolute_frequency_gap_from_beta'] = abs(result['exceedance_fraction']-1/40)
            result['projection_count'] = 0
            result['signed_projection'] = 0.0
            result['signed_projection_exact'] = '0'
            result['exact_controller_accounting'] = None
            if trace is not None:
                correction = sum(map(int, trace['projection_units'][mask]))
                result['projection_count'] = int(np.count_nonzero(trace['projection_units'][mask]))
                result['signed_projection'] = float(Fraction(correction, trace['denominator']))
                result['signed_projection_exact'] = str(Fraction(correction, trace['denominator']))
                result['exact_controller_accounting'] = exact_accounting(trace,mask,origins,h,eta,lanes)
            return result

        model_specs = [
            ('raw_hs', base_q[:,0], base_e[:,0], None, None, True),
            ('fast_fhs', base_q[:,5], base_e[:,5], None, None, True),
            ('multiscale_fhs', base_q[:,3], base_e[:,3], None, None, True),
            ('static_selected', static_q[:,selected_static], static_e[:,selected_static], None, None, True),
            ('lane_primary', controllers[primary]['var'], controllers[primary]['es'], controllers[primary], p['primary_eta'], True),
            ('lane_selected', controllers[selected_eta]['var'], controllers[selected_eta]['es'], controllers[selected_eta], eta_grid[selected_eta], True),
            ('pooled_primary', pooled['var'], pooled['es'], pooled, p['primary_eta'], False),
        ]
        if [spec[0] for spec in model_specs] != p['reported_models']:
            raise AssertionError('model order mismatch')
        for model,q,e,trace,eta,lanes in model_specs:
            record = {period:summarize(q,e,mask,trace,eta,lanes) for period,mask in masks.items()}
            record['yearly'] = {}
            record['risk_strata'] = {}
            for period,mask in masks.items():
                years = sorted(set(dates[origins[mask]].astype('U4')))
                record['yearly'][period] = {
                    str(year):summarize(q,e,mask & (dates[origins].astype('U4')==year),trace,eta,lanes)
                    for year in years}
                record['risk_strata'][period] = {
                    label:summarize(q,e,mask & (strata==value),trace,eta,lanes)
                    for label,value in [('at_or_below_previous_median',0),('above_previous_median',1)]}
            contract['models'][model] = record
        for j,eta in enumerate(eta_grid):
            trace = controllers[j]
            contract['candidates']['lane_eta_'+eta] = {
                period:summarize(trace['var'],trace['es'],mask,trace,eta) for period,mask in masks.items()}
            if Fraction(eta) > 0:
                contract['controller_accounting']['lane_eta_'+eta] = {
                    period:exact_accounting(trace,mask,origins,h,eta) for period,mask in masks.items()}
        for j,theta in enumerate(static_grid):
            contract['candidates']['static_theta_'+theta] = {
                period:summarize(static_q[:,j],static_e[:,j],mask) for period,mask in masks.items()}
        contract['controller_accounting']['pooled_primary'] = {
            period:exact_accounting(pooled,mask,origins,h,p['primary_eta'],False) for period,mask in masks.items()}
        contract['eligible_issuances'] = len(origins)
        contract['matured_issuances'] = int(matured.sum())
        contract['pending_issuances'] = int((~matured).sum())
        contract['all_history_projection_counts'] = {
            'lane_'+eta:int(np.count_nonzero(trace['projection_units'])) for eta,trace in zip(eta_grid,controllers)}
        contract['all_history_projection_counts']['pooled_primary'] = int(np.count_nonzero(pooled['projection_units']))
        output['contracts'].append(contract)
        # Six unchanged base, five static, four lane, and one pooled candidate.
        candidate_pairs += len(origins)*16
        print(name,h,'selected eta',contract['selected_eta'],'static',contract['selected_static_theta'],
              'retro',{m:round(v['retrospective']['mean_fz0'],5) for m,v in contract['models'].items()},
              'extension',{m:round(v['temporal_extension']['mean_fz0'],5) for m,v in contract['models'].items()},flush=True)
    output['period_contract_cases'] = {period:sum(c['periods'][period]['n'] for c in output['contracts']) for period in periods}
    output['period_forecast_pairs'] = {period:n*len(p['reported_models']) for period,n in output['period_contract_cases'].items()}
    output['archive_candidate_pairs_including_pending'] = candidate_pairs
    output['pending_contract_cases'] = sum(c['pending_issuances'] for c in output['contracts'])
    for name in ['adaptive_risk.py','benchmark_adaptive_risk.py','ecb_risk.py']:
        output.setdefault('source_sha256',{})[name] = hashlib.sha256((ROOT/'reproduction'/name).read_bytes()).hexdigest()
    target = ROOT/'results/adaptive_risk_predictions.npz'
    np.savez_compressed(target,**archive)
    output['predictions_sha256'] = hashlib.sha256(target.read_bytes()).hexdigest()
    output['seconds'] = time.perf_counter()-start
    (ROOT/'results/adaptive_risk_results.json').write_text(json.dumps(output,indent=2,allow_nan=False)+'\n')
    print('saved',output['period_forecast_pairs'], 'pending',output['pending_contract_cases'],
          'elapsed',round(output['seconds'],3),flush=True)


if __name__ == '__main__':
    main()
