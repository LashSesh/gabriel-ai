"""Recompute stored errors and routing choices; reconstruct one seed's predictions.

No fit or model selection is repeated. Checks saved evidence against the executed
implementation, including normalization and shifted predictions.
"""
import json,csv
import numpy as np
from benchmark_multitime import features,TASKS
from run_experiments import OUT,VALID,TEST

def main():
    error=0.; prediction_error=0.; count=0
    names=['event_hybrid','elapsed_symmetric','elapsed_ordered','elapsed_quadratic','combined']
    for prefix,seeds in [('multitime',range(40,50)),('multitime_routing',range(60,70))]:
        rows=list(csv.DictReader((OUT/(prefix+'_benchmark.csv')).open()))
        for seed in seeds:
            with np.load(OUT/f'multitime_seed_{seed}.npz') as d:
                models=names+(['routed'] if seed>=60 else [])
                for regime,key,idx in [('same_duration','',TEST),('shorter_duration','shift_',np.arange(400,3000))]:
                    y=d[key+'targets']
                    for name in models:
                        p=d[name+'_'+key+'predictions']
                        errors=np.mean((p[idx]-y[idx])**2,axis=0)/np.var(y[idx],axis=0)
                        for j,task in enumerate(TASKS):
                            r=next(r for r in rows if int(r['seed'])==seed and r['regime']==regime and r['model']==name and r['task']==task)
                            error=max(error,abs(errors[j]-float(r['nmse'])));count+=1
                if seed>=60:
                    val=np.array([np.mean((d[n+'_predictions'][VALID]-d['targets'][VALID])**2,axis=0) for n in names])
                    assert np.array_equal(np.argmin(val,axis=0),d['routed_model_indices'])
                    assert np.allclose(val,d['routing_validation_errors'],rtol=0,atol=1e-15)
                    for j,i in enumerate(d['routed_model_indices']):
                        assert np.array_equal(d['routed_predictions'][:,j],d[names[i]+'_predictions'][:,j])
                        assert np.array_equal(d['routed_shift_predictions'][:,j],d[names[i]+'_shift_predictions'][:,j])
                if seed==60:
                    for key in ['', 'shift_']:
                        f=features(d[key+'u'],d[key+'durations'],seed)
                        for name in names:
                            mu=d[name+'_feature_mean'];sd=d[name+'_feature_scale']
                            p=np.c_[np.ones(len(f[name])),(f[name]-mu)/sd]@d[name+'_readout']+d[name+'_target_mean']
                            prediction_error=max(prediction_error,float(np.max(np.abs(p-d[name+'_'+key+'predictions']))))
    assert error<1e-12 and prediction_error<1e-12
    result=dict(checked_nmse_values=count,max_error_discrepancy=float(error),
                reconstructed_prediction_seed=60,max_prediction_discrepancy=prediction_error,
                routing_choices_verified=40,tolerance=1e-12)
    (OUT/'multitime_evidence_verification.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
