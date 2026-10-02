"""Verify every saved bound/score and replay acquisition decisions from records."""
import csv,json
import numpy as np
from benchmark_partial import OUT,POLICIES,TASKS,PREFIX
from partial_observation import VertexAudit,replay_features,sign_verdict

def main():
    rows=list(csv.DictReader((OUT/'partial_benchmark.csv').open()));error=0.;replay_error=0.;policy_choices=0
    with np.load(OUT/'partial_observation_cases.npz') as d:
        for row in rows:
            i=int(row['case']);t=TASKS.index(row['task']);p=POLICIES.index(row['policy']);b=int(row['queries'])
            lo,hi=d['bounds'][i,t,p,b];initial=d['bounds'][i,t,p,0];v=sign_verdict((lo,hi))
            error=max(error,abs(lo-float(row['lower'])),abs(hi-float(row['upper'])),abs(hi-lo-float(row['width'])))
            assert int(row['resolved'])==int(v!=-1)
            assert int(row['wrong_resolved'])==int(v!=-1 and v!=int(d['truth'][i,t]>0))
            assert lo-1e-12<=d['truth'][i,t]<=hi+1e-12
        # All query sequences are reconstructed from saved vertex arrays, without truth access.
        for i in range(len(d['inputs'])):
            missing=np.flatnonzero(d['missing'][i].ravel()).tolist()
            for t in range(2):
                for p,policy in enumerate(POLICIES):
                    values=d['vertex_outputs'][i,:,t].reshape((2,)*len(missing)).copy();coords=missing.copy()
                    rng=np.random.default_rng(91000+i)
                    for b in range(12):
                        if policy=='minimax':
                            scores={q:max(float(np.ptp(np.take(values,k,axis=j))) for k in [0,1]) for j,q in enumerate(coords)}
                            q=min(scores,key=lambda k:(scores[k],k))
                        elif policy=='recent':q=max(coords)
                        else:q=int(rng.choice(coords))
                        assert q==d['queries'][i,t,p,b];policy_choices+=1
                        v=d['answers'][i,t,p,b];j=coords.index(q);s=(v+1)/2
                        values=(1-s)*np.take(values,0,axis=j)+s*np.take(values,1,axis=j);coords.pop(j)
                        replay_error=max(replay_error,abs(values.min()-d['bounds'][i,t,p,b+1,0]),abs(values.max()-d['bounds'][i,t,p,b+1,1]))
        # Fresh state replay and affine-head calculation for all complete inputs.
        for i in range(len(d['inputs'])):
            f=replay_features(d['inputs'][i,PREFIX:],d['durations'][i,PREFIX:],d['prefix_a'][i],d['prefix_r'][i])[0]
            replay_error=max(replay_error,float(np.max(np.abs(f@d['coefficients'].T-d['truth'][i]))))
        # Recreate complete vertex sets directly for two distinct cases.
        for i in [0,127]:
            u=d['inputs'][i,PREFIX:];lo=np.where(d['missing'][i],-1.,u);hi=np.where(d['missing'][i],1.,u)
            for t in range(2):
                a=VertexAudit(lo,hi,d['durations'][i,PREFIX:],d['coefficients'][t],d['prefix_a'][i],d['prefix_r'][i])
                replay_error=max(replay_error,float(np.max(np.abs(a.values.ravel()-d['vertex_outputs'][i,:,t]))))
    assert error<1e-12 and replay_error<1e-12
    result=dict(checked_rows=len(rows),checked_query_choices=policy_choices,
                max_saved_score_discrepancy=float(error),max_replay_discrepancy=float(replay_error),
                reconstructed_vertex_cases=[0,127],all_complete_input_outputs_replayed=True,tolerance=1e-12)
    (OUT/'partial_evidence_verification.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))

if __name__=='__main__':main()
