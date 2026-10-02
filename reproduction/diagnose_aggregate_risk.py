"""Post-test exploratory diagnosis of the frozen aggregation experiment.

This script changes no forecasts, parameters, primary method, evaluation window
or confirmatory claim. Leave-largest-contribution-out calculations are explicitly
descriptive sensitivity calculations, not replacement evaluation results.
"""
from pathlib import Path
import hashlib
import json
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
COMPARATORS=('arithmetic_fit','selected_expert','fast_fhs')
FIXED_TRANSFORMED=('transformed_fit','selected_expert','fast_fhs')
TOL=2e-8


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def vector_stats(values):
    x=np.asarray(values,float)
    if x.size==0:
        return dict(n=0)
    return dict(n=int(len(x)),mean=float(x.mean()),median=float(np.median(x)),
        minimum=float(x.min()),maximum=float(x.max()),
        q25=float(np.quantile(x,.25)),q75=float(np.quantile(x,.75)))


def loss_score(q,e,y):
    return np.log(e)+(q+np.maximum(y-q,0)*40)/e-1


def fixed_comparator_bounds(origins,h,mask,trace,q,e,y,u,control_scores,c):
    """Binary64 checks of realized regret <= subgradient <= projection bound.

    Each selected lane subsequence is required to be contiguous. The common-test
    calculation retains the inherited accumulator and actual first weight;
    neither is reset. The simple square-root bound is reported only on the
    complete learning history, whose initial accumulator is zero.
    """
    rows=[]
    for lane in range(h):
        ix=np.flatnonzero(mask & (origins%h==lane))
        if not len(ix):
            continue
        if len(ix)>1 and not np.all(np.diff(origins[ix])==h):
            raise AssertionError('bound selection must be contiguous within each lane')
        w,after=trace['issued_weights'][ix],trace['postupdate_weights'][ix]
        g=trace['centered_gradient'][ix]
        norm,step=trace['gradient_norm_squared'][ix],trace['step'][ix]
        before_acc=trace['accumulator_before'][ix]
        after_acc=trace['accumulator_after'][ix]
        if not np.isfinite(w).all() or not np.isfinite(after).all():
            raise AssertionError('finite issued and updated weights required')
        direct=loss_score(q[ix],e[ix],y[ix])-control_scores[ix]
        linear=np.sum(g*(w-u),axis=1)
        projection=np.zeros(len(ix))
        active=step>0
        projection[active]=((np.sum((w[active]-u)**2,axis=1)
            -np.sum((after[active]-u)**2,axis=1))/(2*step[active])
            +step[active]*norm[active]/2)
        convex_violation=float(np.max(direct-linear))
        projection_violation=float(np.max(linear-projection))
        if max(convex_violation,projection_violation)>TOL:
            raise AssertionError('fixed-comparator regret inequality violated')
        if np.any(~active & (norm!=0)):
            raise AssertionError('zero step with nonzero gradient')
        general_bound=float(1/step[-1]+np.sum(step*norm)/2) if step[-1]>0 else 0.
        # D^2=2 is the squared Euclidean diameter of the simplex.
        if float(direct.sum())>general_bound+TOL:
            raise AssertionError('diameter/actual-step upper bound violated')
        sqrt_bound=float((1/c+c)*np.sqrt(after_acc[-1])) if before_acc[0]==0 else None
        rows.append(dict(lane=lane,n=int(len(ix)),
            realized_regret=float(direct.sum()),linearized_regret=float(linear.sum()),
            projection_path_bound=float(projection.sum()),
            diameter_actual_step_bound=general_bound,
            zero_start_square_root_bound=sqrt_bound,
            initial_accumulator=float(before_acc[0]),final_accumulator=float(after_acc[-1]),
            initial_squared_distance=float(np.sum((w[0]-u)**2)),
            final_squared_distance=float(np.sum((after[-1]-u)**2)),
            maximum_convexity_residual=convex_violation,
            maximum_projection_residual=projection_violation))
    count=sum(row['n'] for row in rows)
    aggregate={name:float(sum(row[name] for row in rows)) for name in
        ['realized_regret','linearized_regret','projection_path_bound','diameter_actual_step_bound']}
    aggregate['n']=count
    aggregate['mean_realized_regret']=aggregate['realized_regret']/count
    aggregate['mean_projection_path_bound']=aggregate['projection_path_bound']/count
    aggregate['mean_diameter_actual_step_bound']=aggregate['diameter_actual_step_bound']/count
    aggregate['zero_start_square_root_bound']=(float(sum(row['zero_start_square_root_bound'] for row in rows))
        if all(row['zero_start_square_root_bound'] is not None for row in rows) else None)
    aggregate['lanes']=rows
    return aggregate


def weights_record(weights,trace,mask,experts):
    w=weights[mask]
    update_mask=mask & np.isfinite(trace['step'])
    movement=np.sum(np.abs(trace['postupdate_weights'][update_mask]
                       -trace['preupdate_weights'][update_mask]),axis=1)
    return dict(n=int(mask.sum()),
        mean=dict(zip(experts,w.mean(axis=0).tolist())),
        minimum=dict(zip(experts,w.min(axis=0).tolist())),
        maximum=dict(zip(experts,w.max(axis=0).tolist())),
        standard_deviation=dict(zip(experts,w.std(axis=0).tolist())),
        mean_active_experts=float(np.mean(np.sum(w>1e-12,axis=1))),
        update_l1=vector_stats(movement),
        step=vector_stats(trace['step'][update_mask]),
        gradient_norm_squared=vector_stats(trace['gradient_norm_squared'][update_mask]),
        zero_movement_count=int(np.sum(movement<=1e-15)))


def main():
    protocol_path=ROOT/'results/aggregate_risk_protocol.json'
    result_path=ROOT/'results/aggregate_risk_results.json'
    archive_path=ROOT/'results/aggregate_risk_predictions.npz'
    p=json.loads(protocol_path.read_text());r=json.loads(result_path.read_text())
    if digest(protocol_path)!=r['protocol_sha256'] or digest(archive_path)!=r['predictions_sha256']:
        raise ValueError('frozen experiment provenance mismatch')
    z=np.load(archive_path,allow_pickle=False)
    models=z['models'].tolist();experts=z['experts'].tolist();dates=z['dates']
    primary=p['primary_model'];primary_index=models.index(primary)
    c=p['aggregation']['primary_c']
    online_index=list(p['aggregation']['eta_scales']).index(c)
    out=dict(schema='gabriel.aggregate-risk.diagnostics.v1',
        status='post-test exploratory mechanism diagnosis; no new model or tuning',
        primary_model=primary,comparators=list(COMPARATORS),
        protocol_sha256=r['protocol_sha256'],predictions_sha256=r['predictions_sha256'],
        interpretation='Positive score difference means the frozen primary is worse. Concentration and weight-path descriptions are observational; they do not identify the causal effect of changing an algorithm.',
        removal_sensitivity='Deletion of largest adverse dates describes concentration only; all original dates remain in the primary result and no replacement success criterion is evaluated.',
        regret_scope='Fixed-comparator bounds use fixed weights in transformed coordinates. Arithmetic-pool constant weights induce changing transformed weights proportional to arithmetic_weight times current_expert_ES, and are not assigned the fixed-comparator bound.',
        fitting_scope='Development and all-learning comparisons involving fitted static controls are retrospective mathematical comparisons, because their complete 2010-2019 fitting data were not available before the fitting cutoff. They are not out-of-sample performance claims.',
        period_scope='Secondary 2020-2025 and 2026 windows retain the frozen origin-and-target-inside-period rule. They exclude crossing targets and retain the separately recorded final one-step origins, so their union is not exactly the common primary-origin window.',
        numeric_status='binary64 verification, tolerance 2e-8; not a directed-rounding proof',
        contracts=[])
    common_origins=None;date_contract_differences=[]
    for record in r['contracts']:
        currency,h=record['currency'],record['horizon'];key=f'{currency}_{h}'
        def field(name): return z[key+'_'+name]
        origins=field('origins');y=field('realized');scores=field('model_fz0')
        common=field('common_test_mask');learning=field('online_matured')[:,online_index]
        period_masks={name:field('mask_'+name) for name in
            ['common_test','test_2020_2025','test_2026']}
        period_masks['development']=field('static_fit_mask')
        period_masks['all_learning']=learning
        trace={name:field('online_'+name)[:,online_index] for name in
            ['issued_weights','preupdate_weights','postupdate_weights','centered_gradient',
             'step','gradient_norm_squared','accumulator_before','accumulator_after']}
        if common_origins is None: common_origins=origins[common]
        if not np.array_equal(common_origins,origins[common]):
            raise AssertionError('common dates do not match across contracts')
        differences=np.stack([scores[:,primary_index]-scores[:,models.index(name)]
                              for name in COMPARATORS],axis=1)
        date_contract_differences.append(differences[common])
        contract=dict(currency=currency,horizon=h,selected_expert=record['selected_expert'],
            differences={},weights={},gradient_history={},bounds={})
        for period,mask in period_masks.items():
            contract['differences'][period]={name:dict(n=int(mask.sum()),
                mean_difference=float(differences[mask,j].mean()),
                summed_difference=float(differences[mask,j].sum()),
                positive_count=int(np.sum(differences[mask,j]>0)),
                maximum_adverse_difference=float(differences[mask,j].max()),
                minimum_difference=float(differences[mask,j].min()))
                for j,name in enumerate(COMPARATORS)}
            contract['weights'][period]=weights_record(trace['issued_weights'],trace,mask,experts)
        for period in ['all_learning','common_test']:
            mask=period_masks[period]
            available=np.flatnonzero(mask)
            energy=trace['gradient_norm_squared'][mask]
            order=available[np.argsort(energy)[::-1][:5]]
            energy_sum=float(energy.sum())
            contract['gradient_history'][period]=dict(total_squared_gradient=energy_sum,
                top_five=[dict(origin=str(dates[origins[ix]]),target=str(dates[origins[ix]+h]),
                    squared_gradient=float(trace['gradient_norm_squared'][ix]),
                    share_of_selected_total=float(trace['gradient_norm_squared'][ix]/energy_sum)
                    if energy_sum else 0.,realized_loss=float(y[ix]),
                    issued_var=float(field('model_var')[ix,primary_index]),
                    issued_es=float(field('model_es')[ix,primary_index]),
                    step=float(trace['step'][ix]),
                    update_l1=float(np.sum(np.abs(trace['postupdate_weights'][ix]
                                                -trace['preupdate_weights'][ix])))) for ix in order])
        lane_states=[]
        for lane in range(h):
            all_ix=np.flatnonzero(learning&(origins%h==lane))
            test_ix=np.flatnonzero(common&(origins%h==lane))
            initial=float(trace['accumulator_before'][test_ix[0]])
            final=float(trace['accumulator_after'][all_ix[-1]])
            lane_states.append(dict(lane=lane,
                first_test_origin=str(dates[origins[test_ix[0]]]),
                test_initial_accumulator=initial,final_accumulator=final,
                pre_test_gradient_energy_fraction=initial/final if final else 0.,
                first_test_weights=trace['issued_weights'][test_ix[0]].tolist(),
                last_test_weights=trace['issued_weights'][test_ix[-1]].tolist(),
                first_test_step=float(trace['step'][test_ix[0]]),
                last_test_step=float(trace['step'][test_ix[-1]])))
        contract['lane_state']=lane_states
        fixed={'transformed_fit':field('static_transformed_weights'),
               'selected_expert':field('selected_expert_weights'),
               'fast_fhs':np.eye(len(experts))[experts.index('fast_fhs')]}
        for comparator,u in fixed.items():
            contract['bounds'][comparator]={period:fixed_comparator_bounds(origins,h,mask,
                trace,field('model_var')[:,primary_index],field('model_es')[:,primary_index],y,
                u,scores[:,models.index(comparator)],c)
                for period,mask in period_masks.items() if period!='development'}
        out['contracts'].append(contract)
    cube=np.stack(date_contract_differences,axis=1)
    date_diff=cube.mean(axis=1)
    out['common_dates']=len(common_origins)
    out['common_contracts']=len(out['contracts'])
    out['pooled_comparisons']={}
    for j,name in enumerate(COMPARATORS):
        values=date_diff[:,j]
        positive_sum=float(np.maximum(values,0).sum())
        adverse_order=np.argsort(values)[::-1]
        top=[]
        for ix in adverse_order[:10]:
            top.append(dict(origin=str(dates[common_origins[ix]]),
                equal_contract_difference=float(values[ix]),
                contribution_to_overall_mean=float(values[ix]/len(values)),
                contract_differences={f"{record['currency']}_{record['horizon']}":float(cube[ix,k,j])
                                      for k,record in enumerate(out['contracts'])}))
        out['pooled_comparisons'][name]=dict(
            mean_difference=float(values.mean()),summed_date_difference=float(values.sum()),
            sum_positive_date_differences=positive_sum,
            sum_negative_date_differences=float(np.minimum(values,0).sum()),
            positive_date_count=int(np.sum(values>0)),top_ten_adverse_dates=top,
            largest_one_share_of_positive_sum=float(values[adverse_order[0]]/positive_sum)
                if positive_sum else None,
            largest_five_share_of_positive_sum=float(values[adverse_order[:5]].sum()/positive_sum)
                if positive_sum else None,
            sensitivity_after_removing_largest_adverse_dates={str(k):dict(
                retained_dates=len(values)-k,
                mean_difference=float(np.delete(values,adverse_order[:k]).mean())) for k in [1,5,10]},
            contract_contributions={f"{record['currency']}_{record['horizon']}":float(cube[:,k,j].mean()/len(out['contracts']))
                                    for k,record in enumerate(out['contracts'])},
            predeclared_periods={period:dict(
                equal_contract_mean_difference=float(np.mean([
                    record['differences'][period][name]['mean_difference'] for record in out['contracts']])),
                contract_cases=int(sum(record['differences'][period][name]['n'] for record in out['contracts'])))
                for period in ['test_2020_2025','test_2026']})
    out['checks']=dict(all_fixed_comparator_inequalities_passed=True,
        fixed_comparators=list(FIXED_TRANSFORMED),
        periods=['all_learning','common_test','test_2020_2025','test_2026'],
        lane_period_comparator_checks=sum(len(v['lanes']) for rec in out['contracts']
            for comparator in rec['bounds'].values() for v in comparator.values()),
        source_sha256=digest(Path(__file__)))
    old_energy=np.array([lane['pre_test_gradient_energy_fraction']
        for contract in out['contracts'] for lane in contract['lane_state']])
    step_ratios=np.array([lane['last_test_step']/lane['first_test_step']
        for contract in out['contracts'] for lane in contract['lane_state']])
    out['mechanism_summary']=dict(
        inherited_gradient_energy_fraction=vector_stats(old_energy),
        last_over_first_test_step_ratio=vector_stats(step_ratios),
        fixed_comparator_equal_contract_bounds={name:{field:float(np.mean([
            contract['bounds'][name]['common_test'][field] for contract in out['contracts']]))
            for field in ['mean_realized_regret','mean_projection_path_bound',
                          'mean_diameter_actual_step_bound']} for name in FIXED_TRANSFORMED},
        supported_observations=[
            'All common-test primary score deficits are small net differences between larger positive and negative daily contributions.',
            'The 2010-2019 gradient history remains permanently present in every final AdaGrad accumulator; all lane step sizes decline across the test window.',
            'The primary has positive regret against development-selected experts and fast FHS while satisfying all checked fixed-comparator regret inequalities.',
            'The arithmetic-fit deficit is concentrated in the AUD five-step contract; the short 2026 secondary period has a different average comparison sign from 2020-2025.'],
        next_research_hypothesis='A predeclared comparison of finite-memory or restarted weight adaptation against the frozen cumulative-gradient learner can test whether responsiveness to changing expert quality improves score. Controlled switches with known risks should separate adaptation speed from estimation noise before another untouched financial evaluation.',
        causal_limit='The saved trajectory does not establish that old gradient energy caused a forecast deficit, that deleting extreme outcomes would be justified, or that discounting or restarting would improve accuracy. Those are untested interventions. No alternative method is selected by this diagnosis.')
    path=ROOT/'results/aggregate_risk_diagnostics.json'
    path.write_text(json.dumps(out,indent=2,allow_nan=False)+'\n')
    print(json.dumps(dict(status='passed',file=str(path),
        differences={k:v['mean_difference'] for k,v in out['pooled_comparisons'].items()},
        checks=out['checks']),indent=2))


if __name__=='__main__': main()
