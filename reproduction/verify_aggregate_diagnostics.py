"""Independent audit of post-test concentration and optimization diagnostics.

Reconstructs scores, gradient-energy fractions, and subperiod projection bounds
from archived issued forecasts and updates. Numerical checks do not establish
a causal explanation or a future forecasting advantage.
"""
from pathlib import Path
import hashlib,json
import numpy as np
from verify_aggregate_risk import ref_score,compare,require
ROOT=Path(__file__).resolve().parents[1]


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    path=ROOT/'results/aggregate_risk_diagnostics.json';d=json.loads(path.read_text())
    z=np.load(ROOT/'results/aggregate_risk_predictions.npz',allow_pickle=False)
    p=json.loads((ROOT/'results/aggregate_risk_protocol.json').read_text())
    require(digest(ROOT/'results/aggregate_risk_predictions.npz')==d['predictions_sha256'],'prediction identity')
    require(digest(ROOT/'reproduction/diagnose_aggregate_risk.py')==d['checks']['source_sha256'],'diagnostic source identity')
    names=z['models'].tolist();primary=names.index(p['primary_model'])
    c=p['aggregation']['primary_c'];j=p['aggregation']['eta_scales'].index(c)
    comps=d['comparators'];cube=[];energy_fractions=[];worst=0.;checks=0
    residuals=dict(convexity=-float('inf'),projection=-float('inf'),diameter=-float('inf'))
    for record in d['contracts']:
        key=f"{record['currency']}_{record['horizon']}";h=record['horizon']
        get=lambda f:z[key+'_'+f]
        origins=get('origins');common=get('common_test_mask');learn=get('online_matured')[:,j]
        q,e,y=get('model_var'),get('model_es'),get('realized')
        scores=np.full(q.shape,np.nan,dtype=np.longdouble)
        mature=get('matured');scores[mature]=ref_score(q[mature],e[mature],y[mature,None])
        cube.append(np.stack([scores[common,primary]-scores[common,names.index(name)] for name in comps],axis=1))
        norm=np.asarray(get('online_gradient_norm_squared')[:,j],np.longdouble)
        w=np.asarray(get('online_issued_weights')[:,j],np.longdouble)
        after=np.asarray(get('online_postupdate_weights')[:,j],np.longdouble)
        grad=np.asarray(get('online_centered_gradient')[:,j],np.longdouble)
        steps=np.asarray(get('online_step')[:,j],np.longdouble)
        for lane in range(h):
            ix=np.flatnonzero(learn&(origins%h==lane));test=np.flatnonzero(common&(origins%h==lane))
            # Independent sums, rather than reading producer accumulator fields.
            inherited=norm[ix[ix<test[0]]].sum();total=norm[ix].sum();fraction=inherited/total
            r=record['lane_state'][lane]
            worst=max(worst,compare(r['test_initial_accumulator'],inherited,'inherited gradient sum'),
                      compare(r['final_accumulator'],total,'final gradient sum'),
                      compare(r['pre_test_gradient_energy_fraction'],fraction,'inherited fraction'))
            energy_fractions.append(fraction)
        fixed={'transformed_fit':get('static_transformed_weights'),
               'selected_expert':get('selected_expert_weights'),
               'fast_fhs':np.eye(len(z['experts']))[z['experts'].tolist().index('fast_fhs')]}
        for comparator,u in fixed.items():
            for period,aggregate in record['bounds'][comparator].items():
                mask=learn if period=='all_learning' else get('mask_'+period)
                for row in aggregate['lanes']:
                    lane=row['lane'];ix=np.flatnonzero(mask&(origins%h==lane))
                    require(len(ix)==row['n'] and np.all(np.diff(origins[ix])==h),'lane period contiguity')
                    require(np.all(np.diff(steps[ix][steps[ix]>0])<=1e-15),'nonmonotone positive steps')
                    regret=scores[ix,primary]-scores[ix,names.index(comparator)]
                    linear=np.sum(grad[ix]*(w[ix]-u),axis=1)
                    dist=np.sum((w[ix]-u)**2,axis=1);enddist=np.sum((after[ix]-u)**2,axis=1)
                    active=steps[ix]>0;bound=np.zeros(len(ix),dtype=np.longdouble)
                    bound[active]=(dist[active]-enddist[active])/(2*steps[ix][active])+steps[ix][active]*norm[ix][active]/2
                    diameter=(1/steps[ix[-1]]+sum(steps[ix]*norm[ix])/2) if steps[ix[-1]]>0 else 0
                    residuals['convexity']=max(residuals['convexity'],float(np.max(regret-linear)))
                    residuals['projection']=max(residuals['projection'],float(np.max(linear-bound)))
                    residuals['diameter']=max(residuals['diameter'],float(regret.sum()-diameter))
                    for field,value in [('realized_regret',regret.sum()),('linearized_regret',linear.sum()),
                        ('projection_path_bound',bound.sum()),('diameter_actual_step_bound',diameter)]:
                        worst=max(worst,compare(row[field],value,'subperiod '+field))
                    if period!='all_learning':
                        require(row['zero_start_square_root_bound'] is None,'subperiod falsely reset accumulator')
                    checks+=1
    for value in residuals.values():require(value<=2e-8,'invalid observed path inequality')
    cube=np.stack(cube,axis=1);date=cube.mean(axis=1);sensitivity={}
    for j,name in enumerate(comps):
        values=date[:,j];r=d['pooled_comparisons'][name];order=np.argsort(values)[::-1]
        worst=max(worst,compare(r['mean_difference'],values.mean(),'primary comparator difference'))
        for k in [1,5,10]:
            keep=np.ones(len(values),bool);keep[order[:k]]=False
            found=values[keep].mean();stored=r['sensitivity_after_removing_largest_adverse_dates'][str(k)]
            require(stored['retained_dates']==int(keep.sum()),'sensitivity retained count')
            worst=max(worst,compare(stored['mean_difference'],found,'largest-date removal mean'))
            sensitivity.setdefault(name,{})[str(k)]=float(found)
        require(sensitivity[name]['1']>0,'one-date removal no longer leaves positive primary deficit')
    fractions=np.asarray(energy_fractions)
    stats=d['mechanism_summary']['inherited_gradient_energy_fraction']
    for field,value in [('mean',fractions.mean()),('median',np.median(fractions)),('minimum',fractions.min()),('maximum',fractions.max())]:
        worst=max(worst,compare(stats[field],value,'fraction statistic '+field))
    require(checks==d['checks']['lane_period_comparator_checks']==288,'checked lane comparisons')
    result=dict(status='passed',diagnostics_sha256=digest(path),source_sha256=digest(Path(__file__)),
        lane_fraction_reconstructions=len(fractions),lane_period_fixed_comparator_bounds=checks,
        maximum_numerical_difference=worst,maximum_inequality_residuals=residuals,
        inherited_fraction_minimum=float(fractions.min()),inherited_fraction_maximum=float(fractions.max()),
        adverse_date_removal=sensitivity,
        interpretation='Post-test descriptions and realized-path numerical inequalities; no causal attribution or predictive improvement established')
    target=ROOT/'results/aggregate_risk_diagnostics_verification.json'
    target.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
