"""Independent replay of matured severity sufficient statistics and experiments.

Oracles do not call the production severity/frequency recursions, sample
constructor, positive-part formula or metrics. Long-double replay and selected
explicit geometric weighted sums cross-check binary64; neither is interval
arithmetic. Previously verified quantile streams remain an explicit dependency.
"""
from pathlib import Path
from fractions import Fraction
import hashlib
import json
import math
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_HASH = 'bf2b7ff636eebede7ad1e168689d836a653ddde0077314f3916fbc8691c7cc91'
ATOL, RTOL = 1e-10, 1e-10
LD = np.longdouble


def require(ok, message):
    if not ok:
        raise AssertionError(message)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compare(actual, expected, message):
    actual, expected = np.asarray(actual), np.asarray(expected)
    require(actual.shape == expected.shape, message+': shape')
    require(np.allclose(actual, expected, atol=ATOL, rtol=RTOL, equal_nan=True), message+': values')
    mask = np.isfinite(actual) & np.isfinite(expected)
    return float(np.max(np.abs(actual[mask]-expected[mask]))) if mask.any() else 0.


def exact(actual, expected, message):
    require(np.array_equal(actual, expected), message+': exact values')


def severity_reference(q, y, latency, half_life, initial=1.5, cap=20):
    """Independent long-double state; information is consumed at target maturity."""
    q, y = np.asarray(q, dtype=LD), np.asarray(y, dtype=LD)
    n = len(q)
    decay = np.exp(-np.log(LD(2))/half_life)
    raw = np.empty(n, dtype=LD)
    ratio = np.empty(n, dtype=LD)
    pre, post, R = [np.full(n, np.nan, dtype=LD) for _ in range(3)]
    state = LD(initial)
    for i in range(n):
        target = i-latency
        if target >= 0:
            # q[target] is the frozen forecast issued at that target's origin.
            evidence = 1+40*max(y[target]-q[target], LD(0))/q[target]
            R[target], pre[target] = evidence, state
            state = decay*state+(1-decay)*evidence
            post[target] = state
        raw[i] = state
        ratio[i] = min(LD(cap), max(LD(1), state))
    return dict(es=q*ratio, issued_raw_ratio=raw, issued_ratio=ratio,
                cap_flag=raw > cap, R=R, preupdate_ratio=pre, postupdate_ratio=post,
                matured=np.arange(n)+latency<n, decay=decay)


def weighted_reference(q, y, origin, latency, half_life, initial=1.5):
    """Explicit pseudo-observation plus every matured geometric-weight term."""
    n_updates = max(0, origin-latency+1)
    lam = np.exp(-np.log(LD(2))/half_life)
    q, y = np.asarray(q, dtype=LD), np.asarray(y, dtype=LD)
    R = 1+40*np.maximum(y[:n_updates]-q[:n_updates], LD(0))/q[:n_updates]
    ages = np.arange(n_updates-1, -1, -1)
    return lam**n_updates*LD(initial)+(1-lam)*np.sum(lam**ages*R, dtype=LD)


def frequency_reference(q, e, y, latency):
    """Fraction lane state, independent from the producer's integer lattice."""
    q, e, y = np.asarray(q), np.asarray(e), np.asarray(y)
    state = [Fraction(0) for _ in range(latency)]
    fq, fe = np.empty(len(q)), np.empty(len(q))
    issued = np.empty(len(q), dtype=np.int64)
    hits = np.full(len(q), -1, dtype=np.int64)
    pre,post,projection = [np.zeros(len(q),dtype=np.int64) for _ in range(3)]
    for t in range(len(q)):
        j = t-latency
        if j >= 0:
            lane = j % latency
            hit = int(y[j] > fq[j])
            hits[j] = hit
            before = state[lane]
            trial = before+Fraction(40*hit-1,800)
            state[lane] = min(Fraction(1), max(Fraction(-1),trial))
            pre[j],post[j],projection[j] = int(before*800),int(state[lane]*800),int((state[lane]-trial)*800)
        theta = state[t % latency]
        issued[t] = int(theta*800)
        scale = math.exp(float(theta))
        fq[t], fe[t] = q[t]*scale, e[t]*scale
    return dict(var=fq,es=fe,issued_units=issued,matured_hit=hits,preupdate_units=pre,postupdate_units=post,projection_units=projection)


def positive_part_reference(q, scale, d, tail):
    """Analytic mixture stop-loss integral; all distribution branches explicit."""
    q, scale, d = np.broadcast_arrays(np.asarray(q,dtype=LD),np.asarray(scale,dtype=LD),np.asarray(d,dtype=LD))
    x = q/scale
    body = np.where(x <= -1, -x, np.where(x < 1, (1-x)**2/4, LD(0)))
    if tail == 'bounded':
        hi = 1+2*d
        severe = np.where(x <= 1, 1+d-x, np.where(x < hi, (hi-x)**2/(4*d), LD(0)))
    elif tail == 'exponential':
        severe = np.where(x <= 1, 1+d-x, d*np.exp(-(x-1)/d))
    else:
        raise ValueError('unknown synthetic tail')
    return scale*(LD(39)/40*body+severe/40)


def independent_sample(index, replicate, protocol):
    spec = protocol['synthetic']; case = spec['cases'][index]
    n = spec['origins']; t = np.arange(n)
    scale = 1+.25*np.sin(2*np.pi*t/800)
    if case['name'] == 'stationary_bounded':
        d = np.full(n,.5)
    elif case['name'] == 'recurrent_shift':
        d = np.where((t//1000)%2 == 0,.5,3.)
    else:
        d = np.where(t<4000,.5,3.)
    rng = np.random.Generator(np.random.PCG64(np.random.SeedSequence([2026092604,index,replicate])))
    U = rng.random(n); V = rng.random(n)
    body = -1+2*V
    tail = 1+2*d*V if case['tail']=='bounded' else 1-d*np.log1p(-V)
    y = scale*np.where(U>=39/40,tail,body)
    q = scale*case['q_factor']; e = 1.5*q
    return dict(scale=scale,d=d,losses=y,base_var=q,base_es=e,generated_tail=U>=39/40,
                true_var=scale,true_es=scale*(1+d))


def metric_reference(q,e,y,cap_flags=None,scale=None,d=None,tail=None,true_es=None):
    q,e,y = [np.asarray(x,dtype=LD) for x in (q,e,y)]
    require(len(q)>0 and np.isfinite(q).all() and np.isfinite(e).all() and np.isfinite(y).all(), 'valid metric rows')
    require(np.all((q>0)&(e>=q)), 'valid metric forecast domain')
    excess = np.maximum(y-q,LD(0))
    score = np.log(e)-1+q/e+40*excess/e
    residual = q+40*excess-e
    values = dict(n=len(q),mean_fz0=float(np.mean(score)),exceedances=int(np.count_nonzero(y>q)),
                  exceedance_fraction=float(np.mean(y>q)),
                  mean_es_identification_residual=float(np.mean(residual)),
                  mean_var=float(np.mean(q)),mean_es=float(np.mean(e)),
                  cap_fraction=0. if cap_flags is None else float(np.mean(cap_flags)))
    if scale is not None:
        expected_excess = positive_part_reference(q,scale,d,tail)
        expected_score = np.log(e)-1+q/e+40*expected_excess/e
        values.update(analytic_expected_fz0=float(np.mean(expected_score)),
                      relative_es_absolute_error=float(np.mean(np.abs(e/np.asarray(true_es,dtype=LD)-1))),
                      normalized_es_residual=float(np.mean(residual/np.asarray(true_es,dtype=LD))))
    return values


def production_function_checks(protocol):
    from severity_risk import replay_severity, conditional_positive_part  # Functions under test only.
    rng = np.random.default_rng(2026092605)
    n = 1200
    q = 1+rng.random(n)
    y = rng.normal(0,3,n)
    cases = 0
    for latency in [1,5]:
        for half in protocol['half_lives_completed_observations']:
            full = replay_severity(q,y,latency,half)
            for cutoff in [17,411,900]:
                altered_y, altered_q = y.copy(), q.copy()
                # At t=cutoff only outcomes at origins <= cutoff-latency mature.
                altered_y[cutoff-latency+1:] += 1000
                altered_q[cutoff+1:] *= 2
                changed = replay_severity(altered_q,altered_y,latency,half)
                truncated = replay_severity(q[:cutoff+1],y[:cutoff+1],latency,half)
                for other in [changed,truncated]:
                    for field in ['es','issued_raw_ratio','issued_ratio','cap_flag']:
                        exact(full[field][:cutoff+1],other[field][:cutoff+1],'severity suffix causality '+field)
                cases += 2
            # Perturb the first loss: unavailable until the exact target endpoint.
            zeros = np.zeros(n); shock = zeros.copy(); shock[0] = 10
            a = replay_severity(np.ones(n),zeros,latency,half)
            b = replay_severity(np.ones(n),shock,latency,half)
            exact(a['es'][:latency],b['es'][:latency],'outcome used before maturity')
            require(b['issued_raw_ratio'][latency] > a['issued_raw_ratio'][latency], 'matured outcome unused')
    # Deliberately enormous finite shock: emission clips, sufficient state must not.
    qshock, yshock = np.ones(24), np.zeros(24); yshock[0] = 1000
    shock = replay_severity(qshock,yshock,1,1)
    ref = severity_reference(qshock,yshock,1,1)
    for field in ['es','issued_raw_ratio','issued_ratio','R','preupdate_ratio','postupdate_ratio']:
        compare(shock[field],ref[field],'uncapped accumulator shock '+field)
    require(shock['issued_raw_ratio'][1] > 10000, 'accumulator was clipped')
    require(shock['es'][2] == 20, 'tail severity memory lost after shock')
    clipped_state = 1.5; wrong = []
    for t in range(24):
        if t:
            evidence = 1+40*max(yshock[t-1]-1,0)
            clipped_state = min(20,max(1,.5*clipped_state+.5*evidence))
        wrong.append(clipped_state)
    require(wrong[2] == 10.5 and shock['issued_ratio'][2] == 20, 'counterexample does not distinguish wrong accumulator clipping')
    recovery = int(np.flatnonzero((np.arange(24)>1)&(shock['issued_ratio']<20))[0])
    require(recovery == 12, 'unexpected exact shock recovery')
    # Closed-form conditional loss checks cover body, body edge, tail and far tail.
    maximum = 0.; formulas = 0
    for tail in ['bounded','exponential']:
        for scale in [.5,1.,2.]:
            for d in [.1,.5,3.]:
                values = np.array([.1,.5,.8,.99,1.,1.1,1+2*d,2+2*d])*scale
                found = conditional_positive_part(values,np.full(8,scale),np.full(8,d),tail)
                ref = positive_part_reference(values,np.full(8,scale),np.full(8,d),tail)
                maximum = max(maximum,compare(found,ref,'positive-part closed form'))
                formulas += len(values)
    # Pending values need not exist; any immature suffix is excluded from updates.
    pending_cases = 0
    for latency in [1,5]:
        unfinished = y.copy(); unfinished[-latency:] = np.nan
        a = replay_severity(q,y,latency,125)
        b = replay_severity(q,unfinished,latency,125)
        exact(a['es'],b['es'],'pending loss changed issued forecast')
        require(np.isnan(b['R'][-latency:]).all(),'pending ratio fabricated')
        pending_cases += 1
    invalid = 0
    good = dict(issued_q=np.ones(10),losses=np.zeros(10),latency=1,half_life=125)
    for key,value in [('latency',0),('latency',-1),('half_life',0),('half_life',-1),
                      ('initial',.5),('cap',.5),('issued_q',np.zeros(10)),
                      ('issued_q',np.full(10,np.inf)),('losses',np.full(10,np.nan)),
                      ('losses',np.zeros(9))]:
        case = dict(good); case[key] = value
        try:
            replay_severity(**case)
        except (ValueError,TypeError):
            invalid += 1
        else:
            raise AssertionError('invalid severity input accepted: '+key)
    from benchmark_severity_risk import fit_ratio  # Function under test only.
    static_checks = 0
    for latency in [1,5]:
        cutoff = 411
        fit = np.arange(n)+latency <= cutoff
        base = fit_ratio(q,y,fit,protocol['ratio_cap'])
        changed_y,changed_q = y.copy(),q.copy()
        changed_y[cutoff-latency+1:] += 1000
        changed_q[cutoff+1:] *= 2
        observed = fit_ratio(changed_q,changed_y,fit,protocol['ratio_cap'])
        require(base == observed,'unmatured data changed static fit')
        truncated = fit_ratio(q[:cutoff+1],y[:cutoff+1],fit[:cutoff+1],protocol['ratio_cap'])
        require(base == truncated,'future suffix removal changed static fit')
        static_checks += 2
    return dict(suffix_variants=cases,maturity_cases=4,pending_cases=pending_cases,static_fit_causality_rechecks=static_checks,
                analytic_positive_part_cases=formulas,max_positive_part_difference=maximum,
                invalid_inputs_rejected=invalid,
                huge_shock=dict(initial_raw_after_shock=float(shock['issued_raw_ratio'][1]),
                                first_uncapped_emission_after_shock_origin=recovery,
                                correct_second_postshock_emission=20.,incorrect_clipped_state_emission=wrong[2]))


def scalar_record_compare(actual, expected, name):
    require(actual.keys()==expected.keys(),name+': keys '+str((set(actual)-set(expected),set(expected)-set(actual))))
    worst = 0.
    for key,value in expected.items():
        if isinstance(value,float):
            worst = max(worst,compare(actual[key],value,name+'/'+key))
        else:
            require(actual[key]==value,name+'/'+key)
    return worst


def reference_static_ratio(q,y,mask,cap=20):
    q,y = np.asarray(q,dtype=LD),np.asarray(y,dtype=LD)
    require(mask.any(),'empty static development set')
    R = 1+40*np.maximum(y[mask]-q[mask],LD(0))/q[mask]
    mean = np.mean(R,dtype=LD)
    return float(min(LD(cap),max(LD(1),mean))),float(mean)


def monte_carlo_reference(values):
    from scipy.optimize import brentq
    from scipy.special import stdtr
    x = np.asarray(values,dtype=LD);n=len(x)
    critical = brentq(lambda z:stdtr(n-1,z)-.975,1.,4.,xtol=1e-14)
    mean = np.mean(x,dtype=LD)
    spread = np.sqrt(np.sum((x-mean)**2,dtype=LD)/(n-1))
    half_width = LD(critical)*spread/np.sqrt(LD(n))
    return dict(n=n,mean=float(mean),sd=float(spread),ci95_low=float(mean-half_width),ci95_high=float(mean+half_width))


def market_metric_reference(q,e,y,caps):
    result = metric_reference(q,e,y,caps)
    q,e,y = [np.asarray(x,dtype=LD) for x in (q,e,y)]
    result['mean_normalized_es_residual'] = float(np.mean((q+40*np.maximum(y-q,LD(0))-e)/q))
    result['cap_count'] = int(np.count_nonzero(caps))
    return result


def analytic_reference(q,e,s,d,tail):
    q,e,s,d = np.broadcast_arrays(*[np.asarray(x,dtype=LD) for x in (q,e,s,d)])
    psi = q+40*positive_part_reference(q,s,d,tail)
    truth = s*(1+d)
    expected_score = np.log(e)+psi/e-1
    quantile_gap = np.log(psi/truth)
    severity_gap = np.log(e/psi)+psi/e-1
    residual = expected_score-np.log(truth)-quantile_gap-severity_gap
    return dict(expected_fz0=expected_score,quantile_score_excess=quantile_gap,
                severity_score_excess=severity_gap,decomposition_residual=residual,psi=psi)


def synthetic_metric_reference(q,e,y,caps,diagnostics,true_es,mask,j):
    q,e,y = [np.asarray(x,dtype=LD) for x in (q[mask,j],e[mask,j],y[mask])]
    excess = np.maximum(y-q,LD(0))
    return dict(n=int(mask.sum()),realized_mean_fz0=float(np.mean(np.log(e)+q/e+40*excess/e-1)),
                analytic_conditional_expected_fz0=float(np.mean(diagnostics['expected_fz0'][mask,j])),
                relative_es_absolute_error=float(np.mean(np.abs(e-np.asarray(true_es[mask],dtype=LD))/true_es[mask])),
                breach_fraction=float(np.mean(y>q)),normalized_es_residual=float(np.mean((q+40*excess-e)/q)),
                cap_fraction=float(np.mean(caps[mask,j])),
                quantile_score_excess=float(np.mean(diagnostics['quantile_score_excess'][mask,j])),
                severity_score_excess=float(np.mean(diagnostics['severity_score_excess'][mask,j])))


def assemble_reference(qs,es,y,latency,fit,p):
    traces = [[severity_reference(qs[:,s],y,latency,h,p['initial_ratio'],p['ratio_cap'])
               for h in p['half_lives_completed_observations']] for s in range(2)]
    static = [reference_static_ratio(qs[:,s],y,fit,p['ratio_cap']) for s in range(2)]
    q = np.stack([qs[:,0],qs[:,1],qs[:,0],qs[:,1],qs[:,0],qs[:,1],qs[:,0],qs[:,1]],axis=1).astype(LD)
    e = np.stack([es[:,0],es[:,1],traces[0][0]['es'],traces[1][0]['es'],
                  traces[0][1]['es'],traces[1][1]['es'],qs[:,0]*static[0][0],qs[:,1]*static[1][0]],axis=1).astype(LD)
    n=len(q)
    caps = np.stack([np.zeros(n,bool),np.zeros(n,bool),traces[0][0]['cap_flag'],traces[1][0]['cap_flag'],
                     traces[0][1]['cap_flag'],traces[1][1]['cap_flag'],
                     np.full(n,static[0][1]>p['ratio_cap']),np.full(n,static[1][1]>p['ratio_cap'])],axis=1)
    return traces,static,q,e,caps


def trace_checks(archive,key,traces,static,q,e,caps,qs,es,y,latency,p,errors,counts):
    for field,value in [('q_streams',qs),('base_es_streams',es),('model_var',q),('model_es',e),
                        ('static_raw_ratios',np.array([x[1] for x in static])),('static_ratios',np.array([x[0] for x in static]))]:
        errors['archive_forecasts'] = max(errors['archive_forecasts'],compare(archive[key+'_'+field],value,key+'/'+field))
    exact(archive[key+'_model_cap_flags'],caps,key+' model cap flags')
    for s in range(2):
        for j,half in enumerate(p['half_lives_completed_observations']):
            ref = traces[s][j]
            for field in ['es','issued_raw_ratio','issued_ratio','preupdate_ratio','postupdate_ratio']:
                errors['states'] = max(errors['states'],compare(archive[key+'_candidate_'+field][:,s,j],ref[field],key+'/'+field))
            exact(archive[key+'_candidate_cap_flag'][:,s,j],ref['cap_flag'],key+' cap flag')
            for t in sorted(set([0,latency,latency+17,min(2000,len(y)-1),len(y)-1])):
                weighted = weighted_reference(qs[:,s],y,t,latency,half,p['initial_ratio'])
                errors['explicit_weights'] = max(errors['explicit_weights'],compare(ref['issued_raw_ratio'][t],weighted,key+' explicit weights'))
                counts['explicit_weighted_sum_checks'] += 1
        errors['responses'] = max(errors['responses'],compare(archive[key+'_R'][:,s],traces[s][0]['R'],key+' response'))
    counts['archived_severity_state_rows'] += len(y)*4


def summary_checks(synthetic,market,p):
    """Independently check all replicate means and paired Monte Carlo intervals."""
    from scipy.optimize import brentq
    from scipy.special import stdtr
    path=ROOT/'results/severity_summary.json'
    summary=json.loads(path.read_text())
    for name,value in summary['sources'].items():
        require(digest(ROOT/'results'/name)==value,'summary source binding '+name)
    require(digest(ROOT/'reproduction/summarize_severity_risk.py')==summary['summary_source_sha256'],'summary implementation binding')
    items={(r['case_index'],r['replicate'],r['latency']):r for r in synthetic['records']}
    byname={case['name']:i for i,case in enumerate(p['synthetic']['cases'])}
    tcrit=brentq(lambda z:stdtr(31,z)-.975,1.,4.,xtol=1e-14)
    maximum=0.;checked=0
    metric_names=['realized_mean_fz0','analytic_conditional_expected_fz0','relative_es_absolute_error',
                  'breach_fraction','normalized_es_residual','cap_fraction','quantile_score_excess','severity_score_excess']
    def check_interval(actual,values,label):
        nonlocal maximum,checked
        x=np.asarray(values,dtype=LD);n=len(x)
        require(n==32 and actual['replicates']==n,label+' replicate count')
        mean=np.sum(x,dtype=LD)/n
        sd=np.sqrt(np.sum((x-mean)**2,dtype=LD)/(n-1))
        se=sd/np.sqrt(LD(n));half=LD(tcrit)*se
        expected=dict(mean=mean,sd=sd,standard_error=se,ci95_lower=mean-half,ci95_upper=mean+half,t_critical=tcrit)
        for key,value in expected.items():
            maximum=max(maximum,compare(actual[key],value,label+'/'+key))
        checked+=1
    method_rows=summary['synthetic']['aggregate_method_rows']
    require(len(method_rows)==270,'method summary completeness')
    method_keys=set()
    for row in method_rows:
        ci,h,period,model=byname[row['case']],row['latency'],row['period'],row['model']
        key=(ci,h,period,model);require(key not in method_keys,'duplicate method summary');method_keys.add(key)
        group=[items[ci,rep,h]['models'][model][period] for rep in range(32)]
        require(row['n_per_replicate']==group[0]['n'],'summary window count')
        for metric in metric_names:
            check_interval(row[metric],[r[metric] for r in group],str(key)+'/'+metric)
    comparisons=summary['synthetic']['paired_comparisons']
    require(len(comparisons)==2640,'paired comparison completeness')
    comparison_keys=set()
    for row in comparisons:
        ci,h,period=byname[row['case']],row['latency'],row['period']
        first,second,metric=row['first'],row['second'],row['metric']
        key=(ci,h,period,first,second,metric);require(key not in comparison_keys,'duplicate paired comparison');comparison_keys.add(key)
        values=[LD(items[ci,rep,h]['models'][first][period][metric])-LD(items[ci,rep,h]['models'][second][period][metric]) for rep in range(32)]
        check_interval(row,values,str(key))
    # Retained market summary rows are descriptive values; there are no market CIs.
    market_index={(r['currency'],r['horizon']):r for r in market['contracts']}
    market_rows=summary['market']['rows'];require(len(market_rows)==128,'market summary rows')
    market_keys=set()
    for row in market_rows:
        key=(row['currency'],row['horizon'],row['period'],row['model'])
        require(key not in market_keys,'duplicate market summary');market_keys.add(key)
        contract=market_index[key[:2]];period,model=key[2:]
        original=contract['models'][model][period]
        for metric,value in original.items():
            maximum=max(maximum,compare(row[metric],value,str(key)+'/'+metric))
        reference='frequency_only' if model in ['joint_125','joint_500','static_joint'] else 'fast_base'
        require(row['matched_quantile_reference']==reference,'summary matched quantile reference')
        expected={
            'fz0_difference_vs_fast':original['mean_fz0']-contract['models']['fast_base'][period]['mean_fz0'],
            'fz0_difference_vs_matched_reference':original['mean_fz0']-contract['models'][reference][period]['mean_fz0'],
            'breach_percent':100*original['exceedance_fraction'],
            'absolute_breach_deviation_pp':100*abs(original['exceedance_fraction']-1/40)}
        for metric,value in expected.items():maximum=max(maximum,compare(row[metric],value,str(key)+'/'+metric))
    return dict(summary_sha256=digest(path),method_summary_rows=270,paired_comparison_rows=2640,
                independently_recomputed_monte_carlo_intervals=checked,market_summary_rows=128,
                maximum_absolute_difference=maximum,t_critical_reference=tcrit,
                inference_scope='Approximate replicate-level Monte Carlo intervals; no observed-market confidence intervals.')


def main():
    started = time.perf_counter()
    protocol_path=ROOT/'results/severity_risk_protocol.json'
    require(digest(protocol_path)==PROTOCOL_HASH,'frozen severity protocol')
    p=json.loads(protocol_path.read_text())
    parent_path=ROOT/'results/adaptive_risk_predictions.npz'
    require(digest(parent_path)==p['parent_predictions_sha256'],'parent forecast archive binding')
    parent_check_path=ROOT/'results/adaptive_risk_verification.json'
    parent_check=json.loads(parent_check_path.read_text())
    require(parent_check['status']=='passed' and parent_check['prediction_archive_sha256']==digest(parent_path),'parent independent verification binding')
    require(parent_check['protocol_sha256']==p['parent_adaptive_protocol_sha256'],'parent protocol binding')
    market_path=ROOT/'results/severity_risk_results.json'
    synthetic_path=ROOT/'results/severity_synthetic_results.json'
    market=json.loads(market_path.read_text());synthetic=json.loads(synthetic_path.read_text())
    for output in [market,synthetic]:
        require(output['protocol_sha256']==PROTOCOL_HASH,'result protocol binding')
        for name,value in output['source_sha256'].items():
            require(digest(ROOT/'reproduction'/name)==value,'producer checksum '+name)
    market_archive_path=ROOT/'results/severity_risk_predictions.npz'
    synthetic_archive_path=ROOT/'results/severity_synthetic_results.npz'
    require(digest(market_archive_path)==market['predictions_sha256'],'market archive binding')
    require(digest(synthetic_archive_path)==synthetic['exemplar_predictions_sha256'],'synthetic archive binding')
    parent=np.load(parent_path,allow_pickle=False)
    archive=np.load(market_archive_path,allow_pickle=False)
    synth_archive=np.load(synthetic_archive_path,allow_pickle=False)
    dates=parent['dates'];rates=parent['rates']
    exact(archive['dates'],dates,'market dates');exact(archive['rates'],rates,'market rates')
    exact(archive['models'],p['models'],'market model order')
    exact(archive['stream_order'],p['quantile_streams'],'market quantile stream order')
    exact(archive['half_lives'],p['half_lives_completed_observations'],'market half lives')
    require(market['design_history']==p['market']['design_history'],'retrospective design history')
    expected_contracts={(c,h) for c in p['market']['currencies'] for h in p['market']['horizons']}
    require(len(market['contracts'])==len(expected_contracts),'market contract count')
    require({(r['currency'],r['horizon']) for r in market['contracts']}==expected_contracts,'market contract completeness')
    counts=dict(market_contracts=0,market_metric_records=0,market_archived_model_pairs=0,
                synthetic_replication_contracts=0,synthetic_metric_records=0,
                synthetic_reconstructed_model_pairs=0,exemplar_model_pairs=0,
                archived_severity_state_rows=0,explicit_weighted_sum_checks=0)
    errors=dict(archive_forecasts=0.,states=0.,responses=0.,explicit_weights=0.,
                market_metrics=0.,synthetic_metrics=0.,analytic_diagnostics=0.,static_fit=0.)
    periods=['development','retrospective_2020_2025','retrospective_2026']
    period_cases={name:0 for name in periods}
    for item in market['contracts']:
        name,h=item['currency'],item['horizon'];key=name+'_'+str(h)
        origins,y,matured=[parent[key+'_'+field] for field in ['origins','realized','matured']]
        for field,value in [('origins',origins),('matured',matured)]:exact(archive[key+'_'+field],value,key+'/'+field)
        compare(archive[key+'_realized'],y,key+' realized losses')
        qs=np.stack([parent[key+'_base_candidate_var'][:,5],parent[key+'_lane_var'][:,2]],axis=1)
        es=np.stack([parent[key+'_base_candidate_es'][:,5],parent[key+'_lane_es'][:,2]],axis=1)
        masks={}
        for period in periods:
            lo,hi=p['market'][period]
            mask=np.zeros(len(origins),bool)
            mask[matured]=((dates[origins[matured]]>=lo)&(dates[origins[matured]]<=hi)&
                           (dates[origins[matured]+h]>=lo)&(dates[origins[matured]+h]<=hi))
            masks[period]=mask;period_cases[period]+=int(mask.sum())
            required=dict(n=int(mask.sum()),first_origin=str(dates[origins[mask][0]]),
                          last_origin=str(dates[origins[mask][-1]]),last_target=str(dates[origins[mask][-1]+h]))
            require(item['periods'][period]==required,key+' period mask '+period)
        require(item['static_fit_count']==int(masks['development'].sum()),key+' static fit count')
        exact(archive[key+'_static_fit_mask'],masks['development'],key+' static fitting mask')
        first_available = int(np.max(origins[masks['development']]+h))
        exact(archive[key+'_static_available_mask'],origins>=first_available,key+' static availability mask')
        traces,static,q,e,caps=assemble_reference(qs,es,y,h,masks['development'],p)
        trace_checks(archive,key,traces,static,q,e,caps,qs,es,y,h,p,errors,counts)
        for s,stream in enumerate(p['quantile_streams']):
            errors['static_fit']=max(errors['static_fit'],compare(item['static_ratios'][stream],static[s][0],key+' static ratio'),
                                     compare(item['static_raw_ratios'][stream],static[s][1],key+' raw static ratio'))
        require(list(item['models'])==p['models'],key+' reported models')
        for j,model in enumerate(p['models']):
            require(item['all_history_cap_count'][model]==int(caps[:,j].sum()),key+' all-history cap count')
            for period,mask in masks.items():
                reference=market_metric_reference(q[mask,j],e[mask,j],y[mask],caps[mask,j])
                errors['market_metrics']=max(errors['market_metrics'],scalar_record_compare(item['models'][model][period],reference,key+'/'+model+'/'+period))
                counts['market_metric_records']+=1
        counts['market_contracts']+=1;counts['market_archived_model_pairs']+=q.size
    require(market['period_contract_cases']==period_cases,'market period totals')
    require(market['period_forecast_pairs']=={k:v*len(p['models']) for k,v in period_cases.items()},'market forecast totals')
    spec=p['synthetic'];models=p['models']+['oracle_truth'];n=spec['origins'];origins=np.arange(n)
    exact(synth_archive['models'],models,'synthetic model order')
    require(synthetic['model_order']==models,'synthetic result model order')
    require(synthetic['replicates']==spec['replicates'],'synthetic replication count')
    indexed={(r['case_index'],r['replicate'],r['latency']):r for r in synthetic['records']}
    required_keys={(ci,r,h) for ci in range(len(spec['cases'])) for r in range(spec['replicates']) for h in spec['latencies']}
    require(set(indexed)==required_keys and len(indexed)==len(synthetic['records']),'synthetic case completeness')
    for ci,case in enumerate(spec['cases']):
        for rep in range(spec['replicates']):
            sample=independent_sample(ci,rep,p);y=sample['losses']
            for h in spec['latencies']:
                item=indexed[ci,rep,h];key=case['name']+'_'+str(h)
                require(item['case']==case['name'] and item['seed']==[2026092604,ci,rep],key+' seeds')
                freq=frequency_reference(sample['base_var'],sample['base_es'],y,h)
                qs=np.stack([sample['base_var'],freq['var']],axis=1)
                es=np.stack([sample['base_es'],freq['es']],axis=1)
                # Information available before issuance at warmup includes a
                # target maturing at that same event, then state/fit precede issue.
                fit=origins+h<=spec['warmup'];matured=origins+h<n
                require(item['static_fit_count']==int(fit.sum()),key+' maturity-limited static fit')
                traces,static,q,e,caps=assemble_reference(qs,es,y,h,fit,p)
                q=np.column_stack([q,sample['true_var']]);e=np.column_stack([e,sample['true_es']])
                caps=np.column_stack([caps,np.zeros(n,bool)])
                diagnostics=analytic_reference(q,e,sample['scale'][:,None],sample['d'][:,None],case['tail'])
                require(np.min(diagnostics['quantile_score_excess'])>=-1e-14,'negative analytic quantile excess')
                require(np.min(diagnostics['severity_score_excess'])>=-1e-14,'negative analytic severity excess')
                compare(diagnostics['decomposition_residual'],np.zeros_like(q),key+' analytic decomposition')
                for s in range(2):
                    errors['static_fit']=max(errors['static_fit'],compare(item['static_ratios'][s],static[s][0],key+' synthetic static ratio'),
                                             compare(item['static_raw_ratios'][s],static[s][1],key+' synthetic static raw'))
                masks=dict(all=matured&(origins>=spec['warmup']),early=matured&(origins>=spec['warmup'])&(origins<4000),late=matured&(origins>=4000))
                require(np.array_equal(masks['all'],masks['early']|masks['late']),'synthetic period partition')
                require(list(item['models'])==models,key+' synthetic models')
                for j,model in enumerate(models):
                    for period,mask in masks.items():
                        reference=synthetic_metric_reference(q,e,y,caps,diagnostics,sample['true_es'],mask,j)
                        errors['synthetic_metrics']=max(errors['synthetic_metrics'],scalar_record_compare(item['models'][model][period],reference,key+'/'+str(rep)+'/'+model+'/'+period))
                        counts['synthetic_metric_records']+=1
                if rep==0:
                    trace_checks(synth_archive,key,traces,static,q,e,caps,qs,es,y,h,p,errors,counts)
                    for field,value in [('origins',origins),('matured',matured),('static_fit_mask',fit),('static_available_mask',origins>=spec['warmup']),('generated_tail',sample['generated_tail']),('seed',np.array([2026092604,ci,rep]))]:
                        exact(synth_archive[key+'_'+field],value,key+'/'+field)
                    for field,value in [('losses',y),('scale',sample['scale']),('tail_mean',sample['d']),('true_var',sample['true_var']),('true_es',sample['true_es'])]:
                        errors['archive_forecasts']=max(errors['archive_forecasts'],compare(synth_archive[key+'_'+field],value,key+'/'+field))
                    for field,value in freq.items():
                        if np.issubdtype(value.dtype,np.integer):exact(synth_archive[key+'_frequency_'+field],value,key+'/frequency/'+field)
                        else:errors['archive_forecasts']=max(errors['archive_forecasts'],compare(synth_archive[key+'_frequency_'+field],value,key+'/frequency/'+field))
                    for field,value in diagnostics.items():
                        errors['analytic_diagnostics']=max(errors['analytic_diagnostics'],compare(synth_archive[key+'_analytic_'+field],value,key+'/analytic/'+field))
                    counts['exemplar_model_pairs']+=q.size
                counts['synthetic_replication_contracts']+=1;counts['synthetic_reconstructed_model_pairs']+=q.size
        print('verified synthetic',case['name'],spec['replicates'],'replicates',flush=True)
    require(synthetic['replicate_contracts']==counts['synthetic_replication_contracts'],'replicate contract total')
    require(synthetic['reported_aggregate_records']==counts['synthetic_metric_records'],'synthetic metric record total')
    require(synthetic['max_decomposition_residual']<1e-10,'producer decomposition arithmetic residual')
    functional=production_function_checks(p)
    summary_validation=summary_checks(synthetic,market,p)
    result=dict(schema='gabriel.severity-risk.verification.v1',status='passed',protocol_sha256=PROTOCOL_HASH,
                market_results_sha256=digest(market_path),synthetic_results_sha256=digest(synthetic_path),
                market_predictions_sha256=digest(market_archive_path),synthetic_exemplar_sha256=digest(synthetic_archive_path),
                parent_verification_sha256=digest(parent_check_path),verifier_sha256=digest(Path(__file__)),
                reference='Independent longdouble sufficient-statistic replay, Fraction synthetic frequency states, explicit geometric weighted sums, and analytic mixture stop-loss integration; quantile parent archive bound to its previous independent verification.',
                tolerance=dict(absolute=ATOL,relative=RTOL),longdouble_mantissa_bits=int(np.finfo(LD).nmant),
                counts=counts,maximum_absolute_differences=errors,production_function_checks=functional,summary_checks=summary_validation,
                limits=['Longdouble and binary64 consistency is not a directed-rounding or interval proof.',
                        'All market windows are retrospective for this design; no untouched market evaluation remains.',
                        'Synthetic latency means delayed individual targets, not aggregated returns.',
                        'Archived static formulas before their fit cutoff are retrospective fitted values, not then-issued forecasts; availability masks are verified.',
                        'Implementation agreement and empirical objective minimization do not establish conditional calibration or universal predictive superiority.'],
                seconds=time.perf_counter()-started)
    (ROOT/'results/severity_risk_verification.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps({key:result[key] for key in ['status','counts','maximum_absolute_differences','seconds']},indent=2))


if __name__=='__main__':main()
