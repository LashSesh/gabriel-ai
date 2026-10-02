"""Independent real-matrix recurrence replay and Arb point/box validation.

Arb evaluates the mathematical held-input filters from stored binary64 parameters,
normalized inputs and fitted coefficients interpreted as exact dyadic numbers.
It does not validate the statistical adequacy of [-1,1] or the preprocessing map.
"""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
from pathlib import Path
import json,time,hashlib,argparse
import numpy as np
from scipy.linalg import expm
from flint import arb,acb,ctx
from phase_memory import parameters
from benchmark_phase import HASH,MODELS,NAMES
from benchmark_external import fit_ridge
from validated_prefix import feature_balls,endpoints

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results'

def compile_arb(head,h,m,phase,budget):
    lam,om=parameters(phase,budget);R=len(lam);K=head.shape[1]
    future=arb(0);kernels=[]
    for hv in h[::-1]:
        dt=arb(float(hv));row=[]
        for l,w in zip(lam,om):
            p=acb(-arb(float(l)),arb(float(w)))
            row.append(arb(float(l))*(p*dt).exp().__sub__(1)/p*(p*future).exp())
        kernels.append(row);future+=dt
    kernels=kernels[::-1]
    H=[[arb(float(v)) for v in row] for row in head]
    C=[]
    imag_ids=np.flatnonzero(om)
    for row in kernels:
      for j in range(m):
        vals=[sum((row[r].real*H[1+r*m+j][k] for r in range(R)),arb(0)) for k in range(K)]
        if phase:
            vals=[v+sum((row[r].imag*H[1+(R+s)*m+j][k] for s,r in enumerate(imag_ids)),arb(0)) for k,v in enumerate(vals)]
        C.append(vals)
    return H[0],C,kernels

def bank_feature_balls(u,kernels,phase,budget):
    lam,om=parameters(phase,budget);m=u.shape[1]
    x=[[arb(float(v)) for v in row] for row in u]
    re=[sum((row[r].real*x[t][j] for t,row in enumerate(kernels)),arb(0)) for r in range(len(lam)) for j in range(m)]
    im=[sum((row[r].imag*x[t][j] for t,row in enumerate(kernels)),arb(0)) for r in np.flatnonzero(om) for j in range(m)]
    return re+(im if phase else [])

def lower_repr(x):return [str(int(v)) for v in x.lower().man_exp()]

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--precision',type=int,default=100)
    precision=parser.parse_args().precision
    if precision < 100:raise ValueError('at least 100 bits required')
    assert hashlib.sha256((OUT/'phase_protocol.json').read_bytes()).hexdigest()==HASH
    begin=time.perf_counter();ctx.prec=precision;records={};point_count=0;box_count=0;replay_count=0
    max_error=0.;min_margin=float('inf');refits=0
    for name in NAMES:
        d=np.load(OUT/f'phase_{name}.npz');u=d['transformed_test'];h=d['durations'];m=u.shape[2];K=len(d['classes'])
        compiled={};cert=[]
        # Independently refit all final ridge heads from saved features and frozen penalty.
        for mi,mode in enumerate(MODELS):
            perf=d['cv_scores'][mi].mean(1);pi=np.flatnonzero(perf==perf.max())[-1]
            fitted=fit_ridge(d[mode+'_features_train'],d['train_labels'],K,d['penalties'][pi])
            assert np.max(abs(fitted-d[mode+'_coefficients']))<1e-12;refits+=1
            if mode in ('real_plus_trace','phase_plus_trace','trace_observer'):continue
            budget=int(mode[-1]) if mode[-1].isdigit() else 16;phase=mode.startswith('phase')
            compiled[mode]=compile_arb(d[mode+'_coefficients'],h,m,phase,budget)
            # Real 2x2 augmented matrix exponentials are independent of complex expm1 code.
            lam,omega=parameters(phase,budget);state=np.zeros((len(u),len(lam),m,2))
            trans=[]
            for l,w in zip(lam,omega):
                M=np.array([[-l,-w,l],[w,-l,0.],[0.,0.,0.]])
                trans.append(expm(M*h[0]))
            for event in u.transpose(1,0,2):
                for r,F in enumerate(trans):state[:,r]=state[:,r]@F[:2,:2].T+event[:,:,None]*F[:2,2]
            f=state[:,:,:,0].reshape(len(u),-1)
            if phase:f=np.c_[f,state[:,:,:,1][:,omega!=0].reshape(len(u),-1)]
            err=float(np.max(abs(np.c_[np.ones(len(u)),f]-d[mode+'_features_test'])))
            assert err<2e-12;max_error=max(max_error,err)
        for case,seq in enumerate(u):
            truth=[arb(float(v)) for v in seq.ravel()];item=dict(case=case,points={},stops=[])
            bank_balls={}
            for mode,(b,c,kernels) in compiled.items():
                scores=[b[k]+sum((v*row[k] for v,row in zip(truth,c)),arb(0)) for k in range(K)]
                result=endpoints(scores);assert result['winner']==int(d[mode+'_prediction'][case]) and result['winner']>=0
                item['points'][mode]=result;point_count+=1
                if mode.endswith('_bank'):
                    bank_balls[mode]=bank_feature_balls(seq,kernels,mode=='phase_bank',16)
                    for ms in range(2):
                      for pol in range(2):
                        path=d[mode+'_query_paths'][case,ms,pol];path=path[path>=0]
                        missing=d['masks'][case,ms].copy();assert len(set(path.tolist()))==len(path) and missing[path].all()
                        # Reconstruct the declared static policy independently from saved coefficients.
                        coeff=d[mode+'_linear_coefficients'];ids=np.flatnonzero(missing)
                        importance=np.ptp(coeff,axis=1)
                        order=ids[np.lexsort((ids,-importance[ids]))] if pol==0 else ids[::-1]
                        assert np.array_equal(path,order[:len(path)]);replay_count+=1
                        missing[path]=False;winner=int(d[mode+'_prediction'][case]);margins=[]
                        for rival in range(K):
                            if rival==winner:continue
                            dif=[row[winner]-row[rival] for row in c]
                            center=b[winner]-b[rival]+sum((v*dd for v,dd,unknown in zip(truth,dif,missing) if not unknown),arb(0))
                            radius=sum((abs(dd) for dd,unknown in zip(dif,missing) if unknown),arb(0))
                            low=center-radius
                            assert low>0,(name,case,mode,ms,pol,low)
                            min_margin=min(min_margin,float(low.lower()));margins.append(dict(rival=rival,lower=lower_repr(low)))
                        item['stops'].append(dict(model=mode,mask=ms,policy=pol,queries=len(path),unread=int(missing.sum()),winner=winner,strict_margin_lower=margins));box_count+=1
            core=feature_balls(seq,[len(seq)],precision)[0][0]
            for mode in ('trace_observer','real_plus_trace','phase_plus_trace'):
                f=core if mode=='trace_observer' else core+bank_balls[mode.replace('_plus_trace','_bank')]
                head=d[mode+'_coefficients'];scores=[sum((arb(float(a))*z for a,z in zip(head[:,k],f)),arb(0)) for k in range(K)]
                result=endpoints(scores);assert result['winner']==int(d[mode+'_prediction'][case]) and result['winner']>=0
                item['points'][mode]=result;point_count+=1
            cert.append(item)
            if (case+1)%50==0:print(name,case+1,'seconds',round(time.perf_counter()-begin,1),flush=True)
        records[name]=cert
        (OUT/f'phase_{name}_validated.json').write_text(json.dumps(dict(precision_bits=precision,records=cert),separators=(',',':')))
        print(name,'validated',len(cert),'seconds',round(time.perf_counter()-begin,1),flush=True)
    result=dict(protocol_sha256=HASH,precision_bits=precision,strict_point_winners=point_count,strict_input_box_stops=box_count,independent_policy_replays=replay_count,final_head_refits=refits,real_matrix_max_feature_error=max_error,smallest_certified_stop_margin=min_margin,seconds=time.perf_counter()-begin,scope='Stored normalized inputs, fitted heads, parameters and durations treated as exact dyadic values. No dataset coverage or statistical calibration proof.')
    (OUT/'phase_validation_summary.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))

if __name__=='__main__':main()
