"""Independent numerical audit of the frozen joint-risk aggregation study.

Reference formulas do not call production aggregation, gradient, simplex,
optimization-objective, score, or controller helpers. Forecast references reuse
only the independent extended-precision scalar recursion and sorted final-unit
empirical-tail integrator from verify_ecb_risk.py. Function-under-test imports
occur inside explicit comparisons. Tolerances are numerical cross-checks, not
interval enclosures or exact floating-point certificates.
"""
from pathlib import Path
from fractions import Fraction
import csv
import hashlib
import io
import itertools
import json
import math
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
ATOL = 2e-9
RTOL = 2e-9
FROZEN_PROTOCOL_HASH = '0f674533411924d18f38e5ee9651630eeaf40c1f6d6b85d10fdc8627ea2a1246'


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def compare(found, reference, name, atol=ATOL, rtol=RTOL):
    f, r = np.asarray(found), np.asarray(reference)
    require(f.shape == r.shape, name + ': shape mismatch')
    require(np.allclose(f, r, atol=atol, rtol=rtol, equal_nan=True),
            name + ': numerical mismatch; maximum ' + str(np.nanmax(np.abs(f-r))))
    valid = np.isfinite(f) & np.isfinite(r)
    return float(np.max(np.abs(f[valid]-r[valid]))) if valid.any() else 0.0


def ref_score(q, e, y, beta=Fraction(1,40)):
    q, e, y = np.broadcast_arrays(np.asarray(q,np.longdouble),
                                  np.asarray(e,np.longdouble),
                                  np.asarray(y,np.longdouble))
    require(np.isfinite(q).all() and np.isfinite(e).all() and np.isfinite(y).all(),
            'reference score requires finite values')
    require(np.all(q>0) and np.all(e>=q), 'reference forecast domain')
    invbeta = np.longdouble(beta.denominator)/beta.numerator
    return np.log(e) - 1 + q/e + invbeta*np.maximum(y-q,0)/e


def ref_pool(q,e,w):
    q,e,w = np.asarray(q,np.longdouble),np.asarray(e,np.longdouble),np.asarray(w,np.longdouble)
    reciprocal = np.sum(w/e,axis=-1)
    return np.sum(w*q/e,axis=-1)/reciprocal, 1/reciprocal


def ref_gap(q,e,w,y,beta=Fraction(1,40)):
    q,e,w,y = [np.asarray(x,np.longdouble) for x in [q,e,w,y]]
    bbar=np.sum(w/e,axis=-1)
    d=(y[...,None]-q)/e
    loggap=np.log(bbar)+np.sum(w*np.log(e),axis=-1)
    hingegap=(np.sum(w*np.abs(d),axis=-1)-np.abs(np.sum(w*d,axis=-1)))/2
    hingegap*=np.longdouble(beta.denominator)/beta.numerator
    return loggap,hingegap


def ref_gradient(q,e,w,y,beta=Fraction(1,40)):
    q,e,w=np.asarray(q,np.longdouble),np.asarray(e,np.longdouble),np.asarray(w,np.longdouble)
    a=q/e; b=1/e
    abar=np.sum(w*a); bbar=np.sum(w*b)
    multiplier=(np.longdouble(beta.denominator)/beta.numerator) if y*bbar>abar else 0
    g=-b/bbar+a+multiplier*(np.longdouble(y)*b-a)
    return g


def ref_projection(v):
    """Active-set elimination, independent of the sorted-threshold algorithm."""
    x=np.asarray(v,np.longdouble)
    require(x.ndim==1 and len(x)>0 and np.isfinite(x).all(),'invalid projection reference')
    active=np.ones(len(x),dtype=bool)
    for _ in range(len(x)):
        threshold=(sum(x[active])-1)/int(active.sum())
        revised=active & (x>threshold)
        if np.array_equal(revised,active):
            break
        active=revised
    out=np.zeros_like(x); out[active]=x[active]-threshold
    require(abs(out.sum()-1)<1e-13 and np.all(out>=0),'projection reference failure')
    return out


def ref_objective(q,e,y,w,rho=.01,beta=Fraction(1,40)):
    aq,ae=ref_pool(q,e,w)
    w=np.asarray(w,np.longdouble)
    return np.mean(ref_score(aq,ae,y,beta))+np.longdouble(rho)/2*np.sum((w-1/len(w))**2)


def reference_all_forecasts(rates,states,c,h,protocol):
    """Every eligible issue, including targets still pending in source snapshot."""
    from verify_ecb_risk import reference_tail
    initial,window=protocol['variance_initial_observations'],protocol['window']
    origins=np.arange(initial+h+window-1,len(rates))
    ends=origins[:,None]-np.arange(window-1,-1,-1)[None,:]
    starts=ends-h
    history=np.longdouble(100)*np.log(rates[ends,c]/rates[starts,c])
    blocks=[history]
    for txt in protocol['fast_weights']:
        f=Fraction(txt); w=np.longdouble(f.numerator)/f.denominator
        v=w*states[:,0,c]+(1-w)*states[:,1,c]
        blocks.append(history*np.sqrt(v[origins,None]/v[starts]))
    tails=[reference_tail(x,Fraction(protocol['alpha'])) for x in blocks]
    q=np.stack([v[0] for v in tails],axis=1)
    e=np.stack([v[1] for v in tails],axis=1)
    y=np.full(len(origins),np.nan,dtype=np.longdouble)
    mature=origins+h<len(rates)
    y[mature]=100*np.log(rates[origins[mature]+h,c]/rates[origins[mature],c])
    return origins,q,e,y,mature


def ref_online(q,e,origins,y,h,c=1.,beta=Fraction(1,40)):
    """Independent chronological replay with explicit origin-keyed issue history."""
    q,e=np.asarray(q,np.longdouble),np.asarray(e,np.longdouble)
    k=q.shape[1]; states=[np.full(k,np.longdouble(1)/k) for _ in range(h)]
    norms=np.zeros(h,dtype=np.longdouble)
    issued={}; out=[]; outq=[]; oute=[]; accumulated=[]
    for i,t in enumerate(origins):
        lane=int(t)%h
        if int(t)-h in issued:
            j,wold=issued[int(t)-h]
            require(np.isfinite(y[j]),'pending target used as feedback')
            require(np.max(np.abs(states[lane]-wold))<1e-12,'lane state changed before maturity')
            g=ref_gradient(q[j],e[j],wold,y[j],beta)
            g-=np.mean(g)
            norms[lane]+=sum(g*g)
            if norms[lane]>0:
                states[lane]=ref_projection(states[lane]-np.longdouble(c)*g/np.sqrt(norms[lane]))
        w=states[lane].copy(); issued[int(t)]=(i,w)
        iq,ie=ref_pool(q[i],e[i],w)
        outq.append(iq);oute.append(ie);out.append(w);accumulated.append(norms[lane])
    return dict(var=np.array(outq),es=np.array(oute),weights=np.array(out),
                issued_accumulator=np.array(accumulated))


def generic_checks():
    import aggregate_risk as tested
    rng=np.random.default_rng(2026092607)
    maxima={k:0. for k in ['pool','jensen_identity','gradient','finite_difference','projection',
                             'controller_var','controller_es','controller_weights','unit_rescaling']}
    counts={k:0 for k in ['jensen_rows','vertices','gradients','finite_differences','projections',
                          'controller_runs','causal_prefix_variants','pending_variants','invalid_inputs',
                          'regret_comparators','zero_gradient_runs']}
    for k in [1,2,3,8]:
        q=np.exp(rng.normal(0,.5,(83,k)))
        e=q*(1+rng.random((83,k))*2)
        w=rng.dirichlet(np.ones(k)); y=rng.normal(1,2,83)
        Q,E=tested.transformed_mix(q,e,w)
        rq,re=ref_pool(q,e,w)
        maxima['pool']=max(maxima['pool'],compare(Q,rq,'mixture Q'),compare(E,re,'mixture E'))
        require(np.all(Q>=q.min(axis=1)-1e-12) and np.all(Q<=q.max(axis=1)+1e-12),'quantile convex hull')
        require(np.all(E>=e.min(axis=1)-1e-12) and np.all(E<=e.max(axis=1)+1e-12),'ES convex hull')
        lg,hg=ref_gap(q,e,w,y)
        direct=np.sum(np.asarray(w,np.longdouble)*ref_score(q,e,y[:,None]),axis=1)-ref_score(rq,re,y)
        maxima['jensen_identity']=max(maxima['jensen_identity'],compare(lg+hg,direct,'Jensen decomposition'))
        require(np.min(lg)>-1e-13 and np.min(hg)>-1e-13,'negative Jensen component')
        counts['jensen_rows']+=len(q)
        for j in range(k):
            vertex=np.eye(k)[j]; vq,ve=tested.transformed_mix(q,e,vertex)
            compare(vq,q[:,j],'vertex Q');compare(ve,e[:,j],'vertex E');counts['vertices']+=1
        obj,g=tested.transformed_score_gradient(q,e,y,w,rho=.01)
        refg=np.mean([ref_gradient(qq,ee,w,yy) for qq,ee,yy in zip(q,e,y)],axis=0)+.01*(w-1/k)
        maxima['gradient']=max(maxima['gradient'],compare(g,refg,'mean gradient'))
        compare(obj,ref_objective(q,e,y,w),'regularized objective');counts['gradients']+=1
        # Tangent finite differences preserve the simplex and avoid all hinge ties.
        if k>1:
            for j in range(k-1):
                d=np.eye(k)[j]-np.eye(k)[-1];eps=1e-6
                require(np.min(w)>eps,'finite difference crossed simplex edge')
                fp=float(ref_objective(q,e,y,w+eps*d));fm=float(ref_objective(q,e,y,w-eps*d))
                numerical=(fp-fm)/(2*eps)
                maxima['finite_difference']=max(maxima['finite_difference'],compare(numerical,float(g@d),'tangent finite difference',atol=2e-7,rtol=2e-7))
                counts['finite_differences']+=1
        for scale in [.001,7.,1000.]:
            sq,se=tested.transformed_mix(q*scale,e*scale,w)
            maxima['unit_rescaling']=max(maxima['unit_rescaling'],compare(sq/scale,Q,'unit scaled Q'),compare(se/scale,E,'unit scaled E'))
            so,sg=tested.transformed_score_gradient(q*scale,e*scale,y*scale,w,rho=.01)
            compare(so-obj,math.log(scale),'score unit shift');compare(sg,g,'unit invariant gradient')
    # Opposite hinge signs yield strict threshold diversification; equal experts yield zero.
    q=np.array([[1.,3.]]);e=np.array([[2.,4.]]);w=np.array([.5,.5])
    lg,hg=ref_gap(q,e,w,np.array([1.5]));require(lg[0]>0 and hg[0]>0,'straddled hinge strict gain')
    Q,E=tested.transformed_mix(q,e,w);compare(Q,np.array([5/3]),'rational sample Q');compare(E,np.array([8/3]),'rational sample E')
    require(ref_score(Q,E,[1.5])[0]<ref_score(q,e,[[1.5]])[0].min(),'strict illustrative dominance missing')
    require(ref_score(Q,E,[0.])[0]>ref_score(q,e,[[0.]])[0].min(),'best-expert counterexample missing')
    for k in [1,2,8]:
        for scale in [.001,1.,1000.]:
            for _ in range(50):
                v=rng.normal(0,scale,k)
                p=tested.project_simplex(v);r=ref_projection(v)
                maxima['projection']=max(maxima['projection'],compare(p,r,'active-set projection'))
                require(p.min()>=0 and abs(p.sum()-1)<1e-10,'simplex feasibility')
                compare(tested.project_simplex(p),p,'projection idempotence')
                counts['projections']+=1
    for h in [1,5,11]:
        for c in [.1,.3,1.]:
            n=143;k=4
            q=np.exp(rng.normal(0,.2,(n,k)));e=q*(1+rng.random((n,k)))
            y=rng.normal(0,3,n);origins=np.arange(317,317+n)
            found=tested.replay_adagrad(q,e,y,h,c,origins=origins)
            reference=ref_online(q,e,origins,y,h,c)
            for field,refname,error in [('var','var','controller_var'),('es','es','controller_es'),('issued_weights','weights','controller_weights')]:
                maxima[error]=max(maxima[error],compare(found[field],reference[refname],'online '+field))
            matured=np.arange(n)+h<n
            require(np.array_equal(found['matured'],matured),'maturity mask')
            compare(found['preupdate_weights'][matured],found['issued_weights'][matured],'original issue update weight')
            require(np.isnan(found['gradient'][~matured]).all(),'pending gradients must not exist')
            for missing in [np.nan,np.inf,-np.inf]:
                pending=y.copy();pending[-h:]=missing
                other=tested.replay_adagrad(q,e,pending,h,c,origins=origins)
                require(np.array_equal(found['var'],other['var']) and np.array_equal(found['issued_weights'],other['issued_weights']),'pending values affect output')
                counts['pending_variants']+=1
            for cut in [17,79,119]:
                q2,e2,y2=q.copy(),e.copy(),y.copy()
                q2[cut+1:]*=2;e2[cut+1:]*=2;y2[cut-h+1:]+=100
                mutated=tested.replay_adagrad(q2,e2,y2,h,c,origins=origins)
                short=tested.replay_adagrad(q[:cut+1],e[:cut+1],y[:cut+1],h,c,origins=origins[:cut+1])
                for other in [mutated,short]:
                    for field in ['var','es','issued_weights']:
                        require(np.array_equal(found[field][:cut+1],other[field][:cut+1]),'future suffix changed '+field)
                    counts['causal_prefix_variants']+=1
            online=ref_score(found['var'][matured],found['es'][matured],y[matured]).sum()
            bound=(1/c+c)*np.sqrt(found['final_accumulators']).sum()
            for u in list(np.eye(k))+[np.full(k,1/k),rng.dirichlet(np.ones(k))]:
                uq,ue=ref_pool(q[matured],e[matured],u)
                regret=online-ref_score(uq,ue,y[matured]).sum()
                require(regret<=bound+1e-8,'pathwise regret inequality')
                counts['regret_comparators']+=1
            scaled=tested.replay_adagrad(7*q,7*e,7*y,h,c,origins=origins)
            compare(scaled['issued_weights'],found['issued_weights'],'online unit invariant weights')
            counts['controller_runs']+=1
    for k in [1,4,8]:
        q=np.full((45,k),2.);e=np.full((45,k),3.);y=np.arange(45)%4
        for h in [1,5]:
            found=tested.replay_adagrad(q,e,y,h,.3)
            compare(found['issued_weights'],np.full((45,k),1/k),'identical expert weights')
            require(np.all(found['final_accumulators']==0),'identical expert nonzero centered gradient')
            require(np.all(found['step'][found['matured']]==0),'zero gradient took a step')
            compare(found['var'],np.full(45,2.),'identical expert Q');compare(found['es'],np.full(45,3.),'identical expert E')
            counts['zero_gradient_runs']+=1
    goodq=np.ones((9,2));goode=2*goodq;goody=np.zeros(9)
    invalid=[lambda:tested.validate_bank(np.zeros((9,2)),goode),
             lambda:tested.validate_bank(goodq,goodq/2),
             lambda:tested.validate_bank(np.full((9,2),np.nan),goode),
             lambda:tested.replay_adagrad(goodq,goode,np.full(9,np.nan),1,1.),
             lambda:tested.replay_adagrad(goodq,goode,goody,0,1.),
             lambda:tested.replay_adagrad(goodq,goode,goody,True,1.),
             lambda:tested.replay_adagrad(goodq,goode,goody,1,0.),
             lambda:tested.replay_adagrad(goodq,goode,goody,1,np.inf),
             lambda:tested.replay_adagrad(goodq,goode,goody,1,1.,origins=np.arange(9)*2),
             lambda:tested.transformed_mix(goodq,goode,[.1,.1]),
             lambda:tested.transformed_score_gradient(goodq,goode,goody,[.5,.5],rho=np.nan),
             lambda:tested.arithmetic_score_gradient(goodq,goode,goody,[.5,.5],rho=np.inf)]
    for call in invalid:
        try:call()
        except ValueError:counts['invalid_inputs']+=1
        else:raise AssertionError('invalid aggregation input accepted')
    return dict(counts=counts,max_absolute_differences=maxima,
                scope='constructed numerical, causal and edge cases; not a statistical or rounding guarantee')


def check_fit(record,q,e,y):
    """Validate every saved optimizer candidate and actual feasible dual witness."""
    geometry=record['geometry'];rho=record['rho'];k=q.shape[1]
    errors=[];failed=[]
    for i,item in enumerate(record['starts']):
        require(item['start']==i,'optimizer start order')
        w=np.asarray(item['weights'],np.longdouble)
        require(w.shape==(k,) and w.min()>=-1e-15 and abs(w.sum()-1)<1e-10,'candidate infeasible')
        if geometry=='transformed':val=ref_objective(q,e,y,w,rho)
        else:
            val=ref_score(np.asarray(q,np.longdouble)@w,np.asarray(e,np.longdouble)@w,y).mean()+rho/2*sum((w-1/k)**2)
        errors.append(compare(item['objective'],val,'fit start objective'))
        require(item['success']==(item['status']==0),'SLSQP status/success mismatch')
        if not item['success']:failed.append(i)
    selected=min(range(len(record['starts'])),key=lambda i:(record['starts'][i]['objective'],i))
    require(record['selected_start']==selected,'incorrect best located optimizer start')
    compare(record['weights'],record['starts'][selected]['weights'],'selected fit weights')
    compare(record['objective'],record['starts'][selected]['objective'],'selected fit objective')
    details=dict(starts=len(record['starts']),failed_starts=failed,max_objective_difference=max(errors))
    if geometry=='transformed':
        cert=record['certificate'];w=np.asarray(record['weights'],np.longdouble)
        lam=np.asarray(cert['dual_lambda'],np.longdouble)
        require(lam.shape==(len(y),) and lam.min()>=0 and lam.max()<=1,'infeasible hinge dual witness')
        q,e,y=[np.asarray(x,np.longdouble) for x in [q,e,y]]
        a=q/e;b=1/e;c=y[:,None]*b-a;bw=b@w;aw=a@w
        diff=w-np.longdouble(1)/k
        smooth=np.mean(-np.log(bw)+aw)-1+np.longdouble(rho)/2*sum(diff*diff)
        smoothg=np.mean(-b/bw[:,None]+a,axis=0)+rho*diff
        dualg=smoothg+40*np.mean(c*lam[:,None],axis=0)
        lower=smooth-sum(smoothg*w)+min(dualg)
        objective=ref_objective(q,e,y,w,rho)
        errors.append(compare(cert['lower_bound'],lower,'certificate lower bound'))
        errors.append(compare(cert['objective'],objective,'certificate objective'))
        errors.append(compare(cert['numerical_gap'],objective-lower,'certificate objective gap'))
        require(objective-lower>=-1e-10,'numerically negative convex bound gap')
        # Any feasible point must lie above the reconstructed lower bound.
        for u in list(np.eye(k))+[np.full(k,1/k)]:
            require(ref_objective(q,e,y,u,rho)>=lower-1e-10,'dual lower bound exceeds feasible objective')
        details.update(numerical_gap=float(objective-lower),dual_witness_rows=len(lam),
                       lp_success=bool(cert['lp_success']),max_objective_difference=max(errors))
    return details


def ref_metrics(q,e,y):
    q,e,y=[np.asarray(x,np.longdouble) for x in [q,e,y]]
    r=q+40*np.maximum(y-q,0)-e
    hit=y>q
    return dict(n=len(y),mean_fz0=float(ref_score(q,e,y).mean()),
        exceedances=int(hit.sum()),exceedance_fraction=float(hit.mean()),
        mean_es_identification_residual=float(r.mean()),mean_var=float(q.mean()),
        mean_es=float(e.mean()),absolute_frequency_error=float(abs(hit.mean()-np.longdouble(1)/40)),
        mean_normalized_es_residual=float(np.mean(r/q)))


def check_metrics(record,q,e,y,label):
    expected=ref_metrics(q,e,y)
    require(record.keys()==expected.keys(),label+' metric keys')
    worst=0.
    for k,v in expected.items():
        if isinstance(v,int):require(record[k]==v,label+' '+k)
        else:worst=max(worst,compare(record[k],v,label+' '+k))
    return worst



def selection_causality_checks(protocol,archive):
    """Actual selected-expert and static-fit inputs survive future rate edits."""
    from ecb_risk import forecast_candidates, fz_score
    from severity_risk import replay_severity
    dates=archive['dates'];rates=archive['rates']
    parent=json.loads((ROOT/protocol['bank']['parent_protocol_file']).read_text())
    parent['horizons_observed_intervals']=protocol['new_assets']['horizons']
    cut=int(np.searchsorted(dates,'2020-01-01'))-1
    rng=np.random.default_rng(2026092609)
    altered=rates.copy();altered[cut+1:]*=np.exp(rng.normal(0,.3,altered[cut+1:].shape))
    checked=0;static_inputs=0
    for label,x in [('future_suffix_mutation',altered),('suffix_truncation',rates[:cut+1])]:
        _,candidates=forecast_candidates(x,parent)
        for ci,currency in enumerate(protocol['new_assets']['currencies']):
            for h in protocol['new_assets']['horizons']:
                key=f'{currency}_{h}';origins,q0,e0=candidates[ci,h]
                m=origins+h<len(x);y=np.full(len(origins),np.nan)
                y[m]=100*np.log(x[origins[m]+h,ci]/x[origins[m],ci])
                es=[replay_severity(q0[:,5],y,h,half,protocol['bank']['initial_ratio'],protocol['bank']['ratio_cap'])['es']
                    for half in protocol['bank']['severity_half_lives']]
                q=np.column_stack([q0,q0[:,5],q0[:,5]]);e=np.column_stack([e0]+es)
                fit=m&(dates[origins]>='2010-01-01')&(origins+h<=cut)
                original_fit=archive[key+'_static_fit_mask']
                require(np.array_equal(origins[fit],archive[key+'_origins'][original_fit]),'selected-expert cutoff origins')
                for value,original in [(q[fit],archive[key+'_expert_var'][original_fit]),
                                       (e[fit],archive[key+'_expert_es'][original_fit]),
                                       (y[fit],archive[key+'_realized'][original_fit])]:
                    require(np.array_equal(value,original),'future changed static fitting inputs')
                scores=fz_score(q[fit],e[fit],y[fit,None]).mean(axis=0)
                require(np.array_equal(scores,archive[key+'_development_expert_scores']),'future changed development scores')
                require(np.argmax(archive[key+'_selected_expert_weights'])==np.argmin(scores),'future changed selected expert')
                checked+=1;static_inputs+=3
    selection=json.loads((ROOT/protocol['primary_selection_file']).read_text())
    order=protocol['selection']['candidate_tie_order']
    means={name:float(np.mean([r['models'][name]['mean_fz0'] for r in selection['contracts']])) for name in order}
    for name in order:compare(means[name],selection['macro'][name]['mean_contract_fz0'],'old-asset selection mean')
    winner=min(order,key=lambda name:(means[name],order.index(name)))
    expected={'online_c0.1':'adagrad_c0p1','online_c0.3':'adagrad_c0p3','online_c1.0':'adagrad_c1',
              'static_transformed':'transformed_fit','uniform_transformed':'transformed_uniform'}[winner]
    require(expected==protocol['primary_model'],'pre-test primary tie-ordered selection')
    return dict(selected_individual_rechecks=checked,static_fit_input_arrays_bitwise_unchanged=static_inputs,
                cutoff=str(dates[cut]),variants=['future_suffix_mutation','suffix_truncation'],seed=2026092609,
                primary_selection_reconstructed_from_eight_saved_development_scores=True)

def verify_archive():
    """Run only once the separately saved protocol seal exists."""
    from verify_ecb_risk import reference_states
    from verify_severity_risk import severity_reference
    started=time.perf_counter()
    protocol_path=ROOT/'results/aggregate_risk_protocol.json'
    protocol=json.loads(protocol_path.read_text())
    seal=(ROOT/'results/aggregate_risk_protocol.sha256').read_text().split()[0]
    require(digest(protocol_path)==seal==FROZEN_PROTOCOL_HASH,'frozen protocol seal mismatch')
    for name,expected in protocol['implementation_sha256'].items():
        require(digest(ROOT/'reproduction'/name)==expected,'pre-freeze implementation changed: '+name)
    results_path=ROOT/'results/aggregate_risk_results.json'
    result=json.loads(results_path.read_text())
    require(result['protocol_sha256']==seal,'result protocol mismatch')
    require(digest(ROOT/protocol['primary_selection_file'])==protocol['primary_selection_sha256'],
            'pre-test primary selection changed')
    pred_path=ROOT/'results/aggregate_risk_predictions.npz'
    require(digest(pred_path)==result['predictions_sha256'],'prediction archive digest')
    for name,expected in result['source_sha256'].items():
        require(digest(ROOT/'reproduction'/name)==expected,'producer source changed: '+name)
    source=ROOT/protocol['source_file']
    require(digest(source)==protocol['source_csv_sha256'],'raw source changed')
    rows=sorted(csv.DictReader(io.StringIO(source.read_text())),key=lambda r:r['Date'])
    currencies=protocol['new_assets']['currencies'];horizons=protocol['new_assets']['horizons']
    dates=np.array([row['Date'] for row in rows])
    rates=np.array([[np.longdouble(row[c]) for c in currencies] for row in rows])
    require(np.isfinite(rates).all() and np.all(rates>0),'positive complete independently parsed rates')
    require(len(set(dates))==len(dates) and np.all(dates[:-1]<dates[1:]),'unique ordered source dates')
    parent_path=ROOT/protocol['bank']['parent_protocol_file']
    require(digest(parent_path)==protocol['bank']['parent_protocol_sha256'],'parent protocol digest')
    parent=json.loads(parent_path.read_text())
    archive=np.load(pred_path,allow_pickle=False)
    require(np.array_equal(archive['dates'],dates),'archived date mismatch')
    require(np.array_equal(archive['rates'],rates.astype(float)),'archived rate mismatch')
    states=reference_states(rates,parent['variance_initial_observations'],parent['variance_halflives_observed_intervals'])
    errors=dict(variance=compare(archive['variance_states'],states,'variance states'),base_var=0.,base_es=0.,
                realized=0.,severity=0.,model_var=0.,model_es=0.,scores=0.,weights=0.,gradients=0.,
                accumulators=0.,jensen=0.,metrics=0.,selection=0.)
    counts=dict(base_pairs=0,expert_pairs=0,model_pairs=0,metrics=0,jensen_rows=0,online_updates=0,
                fit_start_objectives=0,fit_dual_witness_rows=0,selected_individuals=0,regret_comparators=0,pending_targets=0)
    require(result['model_order']==archive['models'].tolist(),'model order')
    names=result['model_order'];experts=result['expert_order'];K=len(experts)
    uniform=np.full(K,np.longdouble(1)/K)
    common_dates=None;fit_records=[];regrets=[];contract_records=[]
    spec=protocol['new_assets'];cs=protocol['aggregation']['eta_scales']
    for item in result['contracts']:
        currency,h=item['currency'],item['horizon'];ci=currencies.index(currency);key=f'{currency}_{h}'
        get=lambda name:archive[key+'_'+name]
        origins,qbase,ebase,yref,matured=reference_all_forecasts(rates,states,ci,h,parent)
        require(np.array_equal(get('origins'),origins),'origin sequence '+key)
        require(np.array_equal(get('matured'),matured),'maturity sequence '+key)
        y=get('realized');q=get('expert_var');e=get('expert_es')
        errors['base_var']=max(errors['base_var'],compare(q[:,:6],qbase,key+' independent base Q'))
        errors['base_es']=max(errors['base_es'],compare(e[:,:6],ebase,key+' independent base E'))
        errors['realized']=max(errors['realized'],compare(y,yref,key+' realized target'))
        compare(q[:,6:],np.repeat(q[:,5,None],2,axis=1),key+' severity unchanged Q')
        counts['base_pairs']+=qbase.size;counts['expert_pairs']+=q.size
        for j,half in enumerate(protocol['bank']['severity_half_lives']):
            # Actual issued binary64 expert q is the input to this independent recursion.
            sr=severity_reference(q[:,5],y,h,half,protocol['bank']['initial_ratio'],protocol['bank']['ratio_cap'])
            errors['severity']=max(errors['severity'],compare(e[:,6+j],sr['es'],key+' severity E'))
            for field in ['issued_raw_ratio','issued_ratio','preupdate_ratio','postupdate_ratio']:
                errors['severity']=max(errors['severity'],compare(get('severity_'+field)[:,j],sr[field],key+' severity '+field))
            require(np.array_equal(get('severity_cap_flags')[:,j],sr['cap_flag']),key+' severity cap flags')
        lo,hi=spec['development']
        fit=np.zeros(len(origins),bool)
        fit[matured]=((dates[origins[matured]]>=lo)&(dates[origins[matured]]<=hi)&
                      (dates[origins[matured]+h]>=lo)&(dates[origins[matured]+h]<=hi))
        require(np.array_equal(fit,get('static_fit_mask')),key+' fit chronology')
        receipt=int((origins[fit]+h).max())
        require(item['static_available_from_origin_index']==receipt,'fit receipt bound')
        require(np.array_equal(get('static_available_mask'),origins>=receipt),'static availability')
        develop=ref_score(q[fit],e[fit],y[fit,None]).mean(axis=0)
        errors['selection']=max(errors['selection'],compare(get('development_expert_scores'),develop,key+' development scores'))
        chosen=int(np.argmin(develop));require(chosen==item['selected_expert_index'],'selected expert index')
        require(experts[chosen]==item['selected_expert'],'selected expert name')
        require(np.array_equal(get('selected_expert_weights'),np.eye(K)[chosen]),'selected one-hot weights')
        counts['selected_individuals']+=1
        for geometry in ['arithmetic','transformed']:
            fitted=item['static_fits'][geometry]
            info=check_fit(fitted,q[fit],e[fit],y[fit]);info.update(currency=currency,horizon=h,geometry=geometry)
            fit_records.append(info);counts['fit_start_objectives']+=info['starts']
            counts['fit_dual_witness_rows']+=info.get('dual_witness_rows',0)
            compare(get('static_'+geometry+'_weights'),fitted['weights'],'saved fit weights')
        expected_pairs=[(q[:,j],e[:,j]) for j in range(K)]+[(q[:,chosen],e[:,chosen])]
        wa=np.asarray(item['static_fits']['arithmetic']['weights'],np.longdouble)
        wt=np.asarray(item['static_fits']['transformed']['weights'],np.longdouble)
        expected_pairs += [(np.asarray(q,np.longdouble)@wa,np.asarray(e,np.longdouble)@wa),
                          ref_pool(q,e,wt),(np.asarray(q,np.longdouble)@uniform,np.asarray(e,np.longdouble)@uniform),
                          ref_pool(q,e,uniform)]
        available=dates[origins]>=protocol['aggregation']['online_start_date']
        require(np.array_equal(get('online_available_mask'),available),'online start availability')
        start=int(np.flatnonzero(available)[0]);online_matured=matured&available
        require(np.array_equal(get('online_matured'),np.repeat(online_matured[:,None],len(cs),axis=1)),'online matured mask')
        for cindex,c in enumerate(cs):
            trace=ref_online(q[start:],e[start:],origins[start:],y[start:],h,c)
            referencew=np.vstack([np.tile(uniform,(start,1)),trace['weights']])
            errors['weights']=max(errors['weights'],compare(get('online_issued_weights')[:,cindex],referencew,key+' online weights'))
            rq,re=ref_pool(q,e,referencew);expected_pairs.append((rq,re))
            require(np.isnan(get('online_gradient')[~online_matured,cindex]).all(),'invalid feedback rows have gradients')
            require(np.isnan(get('online_score')[~online_matured,cindex]).all(),'invalid feedback rows have score')
            m=np.flatnonzero(online_matured)
            wissued=np.asarray(get('online_issued_weights')[:,cindex],np.longdouble)
            gradient=np.array([ref_gradient(q[j],e[j],wissued[j],y[j]) for j in m])
            centered=gradient-gradient.mean(axis=1,keepdims=True)
            errors['gradients']=max(errors['gradients'],compare(get('online_gradient')[m,cindex],gradient,key+' original-issued gradient'),
                                    compare(get('online_centered_gradient')[m,cindex],centered,key+' centered gradient'))
            errors['weights']=max(errors['weights'],compare(get('online_preupdate_weights')[m,cindex],wissued[m],key+' update-before-issue lane alignment'))
            norm=np.sum(centered**2,axis=1)
            errors['accumulators']=max(errors['accumulators'],compare(get('online_gradient_norm_squared')[m,cindex],norm,'gradient norm'))
            finals=[];finalweights=[]
            for lane in range(h):
                take=np.flatnonzero(origins[m]%h==lane);rowsm=m[take]
                cumul=np.cumsum(norm[take]);prior=np.r_[np.longdouble(0),cumul[:-1]]
                errors['accumulators']=max(errors['accumulators'],compare(get('online_accumulator_before')[rowsm,cindex],prior,'accumulator before'),
                                          compare(get('online_accumulator_after')[rowsm,cindex],cumul,'accumulator after'))
                steps=np.divide(c,np.sqrt(cumul),out=np.zeros_like(cumul),where=cumul>0)
                compare(get('online_step')[rowsm,cindex],steps,'causal adaptive steps')
                posts=np.array([ref_projection(wissued[j]-step*g) for j,step,g in zip(rowsm,steps,centered[take])])
                errors['weights']=max(errors['weights'],compare(get('online_postupdate_weights')[rowsm,cindex],posts,'projected update'))
                finals.append(cumul[-1]);finalweights.append(posts[-1])
            errors['accumulators']=max(errors['accumulators'],compare(get('online_final_accumulators')[:,cindex],finals,'final accumulators'))
            errors['weights']=max(errors['weights'],compare(get('online_final_weights')[:,cindex],finalweights,'final lane weights'))
            score=ref_score(rq[online_matured],re[online_matured],y[online_matured])
            errors['scores']=max(errors['scores'],compare(get('online_score')[online_matured,cindex],score,'online scores'))
            bound=(1/c+c)*sum(np.sqrt(finals));worstregret=-math.inf
            for u in list(np.eye(K))+[uniform,wt]:
                uq,ue=ref_pool(q[online_matured],e[online_matured],u)
                regret=float(score.sum()-ref_score(uq,ue,y[online_matured]).sum())
                require(regret<=bound+1e-7,'observed-path regret exceeds bound')
                worstregret=max(worstregret,regret);counts['regret_comparators']+=1
            regrets.append(dict(currency=currency,horizon=h,scale=c,completed_targets=int(online_matured.sum()),
                                bound=float(bound),largest_checked_regret=worstregret,
                                scope='fixed comparators on observed expert path; no generalization guarantee'))
            counts['online_updates']+=int(online_matured.sum())
        mq,me=[np.stack([pair[j] for pair in expected_pairs],axis=1) for j in [0,1]]
        errors['model_var']=max(errors['model_var'],compare(get('model_var'),mq,'all model Q'))
        errors['model_es']=max(errors['model_es'],compare(get('model_es'),me,'all model E'))
        scores=np.full(mq.shape,np.nan,dtype=np.longdouble);scores[matured]=ref_score(mq[matured],me[matured],y[matured,None])
        errors['scores']=max(errors['scores'],compare(get('model_fz0'),scores,'all archived model scores'))
        counts['model_pairs']+=mq.size
        # Recompute each component from absolute-value Jensen formula, distinct from producer hinges.
        weights=[wt,uniform]+[get('online_issued_weights')[:,j] for j in range(len(cs))]
        for j,w in enumerate(weights):
            wm=w if np.asarray(w).ndim==1 else w[matured]
            lg,hg=ref_gap(q[matured],e[matured],wm,y[matured])
            for field,target in [('jensen_log_component',lg),('jensen_hinge_component',hg),('jensen_gap',lg+hg)]:
                errors['jensen']=max(errors['jensen'],compare(get(field)[matured,j],target,key+' '+field))
            require(lg.min()>-1e-12 and hg.min()>-1e-12,'negative Jensen components')
            counts['jensen_rows']+=int(matured.sum())
        common=matured&(dates[origins]>=spec['test_origin_start'])&(origins<=len(dates)-1-max(horizons))
        extra=matured&(origins>len(dates)-1-max(horizons)) if h==1 else np.zeros(len(origins),bool)
        masks=dict(development=fit,common_test=common,extra_h1=extra,
                   test_all_matured=matured&(dates[origins]>=spec['test_origin_start']))
        for period,(lo,hi) in spec['secondary_periods'].items():
            m=np.zeros(len(origins),bool)
            m[matured]=((dates[origins[matured]]>=lo)&(dates[origins[matured]]<=hi)&
                        (dates[origins[matured]+h]>=lo)&(dates[origins[matured]+h]<=hi))
            masks[period]=m
        for period,mask in masks.items():
            require(np.array_equal(get('mask_'+period),mask),'period mask '+period)
            oo=origins[mask]
            record=dict(n=int(mask.sum()),first_origin=str(dates[oo[0]]) if len(oo) else None,
                        last_origin=str(dates[oo[-1]]) if len(oo) else None,last_target=str(dates[oo[-1]+h]) if len(oo) else None)
            require(record==item['periods'][period],'period boundaries '+period)
            for j,model in enumerate(names):
                if not mask.any():continue
                errors['metrics']=max(errors['metrics'],check_metrics(item['models'][model][period],mq[mask,j],me[mask,j],y[mask],key+' '+model+' '+period))
                counts['metrics']+=1
        if common_dates is None:common_dates=dates[origins[common]]
        else:require(np.array_equal(common_dates,dates[origins[common]]),'unmatched primary origin dates')
        require(np.all(get('static_available_mask')[common]) and np.all(available[common]),'primary comparison uses unavailable forecasts')
        counts['pending_targets']+=int((~matured).sum())
        contract_records.append(dict(currency=currency,horizon=h,common_origins=int(common.sum()),
                                     first_common_origin=str(common_dates[0]),last_common_origin=str(common_dates[-1])))
        print('independently verified',key,flush=True)
    require(counts['model_pairs']==result['archived_candidate_pairs'],'total archive pair count')
    output=dict(status='passed',protocol_sha256=seal,predictions_sha256=digest(pred_path),
        archive_counts=counts,max_absolute_differences=errors,contracts=contract_records,
        static_fit_checks=fit_records,pathwise_regret_checks=regrets,
        generic_checks=generic_checks(),selection_causality_checks=selection_causality_checks(protocol,archive),tolerances=dict(atol=ATOL,rtol=RTOL),
        arithmetic_scope='longdouble and independent algorithm cross-checks; no interval enclosure or automatic proof',
        source_sha256={name:digest(ROOT/'reproduction'/name) for name in ['verify_aggregate_risk.py','verify_ecb_risk.py','verify_severity_risk.py']},
        execution_seconds=time.perf_counter()-started)
    return output


def verify_bootstrap():
    summary_path=ROOT/'results/aggregate_risk_summary.json'
    boot_path=ROOT/'results/aggregate_bootstrap.npz'
    p=json.loads((ROOT/'results/aggregate_risk_protocol.json').read_text())
    summary=json.loads(summary_path.read_text());s=summary['dependent_bootstrap']
    boot=np.load(boot_path,allow_pickle=False)
    archive=np.load(ROOT/'results/aggregate_risk_predictions.npz',allow_pickle=False)
    results=json.loads((ROOT/'results/aggregate_risk_results.json').read_text())
    names=archive['models'].tolist();primary=names.index(p['primary_model'])
    comparators=boot['comparators'].tolist();indices=[names.index(name) for name in comparators]
    cubes=[];origins0=None
    for currency in p['new_assets']['currencies']:
        for h in p['new_assets']['horizons']:
            key=f'{currency}_{h}';mask=archive[key+'_common_test_mask']
            origin=archive[key+'_origins'][mask]
            if origins0 is None:origins0=origin
            else:require(np.array_equal(origin,origins0),'bootstrap origins unaligned')
            cubes.append(ref_score(archive[key+'_model_var'][mask],archive[key+'_model_es'][mask],archive[key+'_realized'][mask,None]))
    cube=np.stack(cubes,axis=1)
    compare(boot['common_all_scores'],cube,'bootstrap source scores')
    diffs=cube[:,:,primary,None]-cube[:,:,indices]
    errors=[compare(boot['paired_differences'],diffs,'paired difference cube')]
    date=diffs.mean(axis=1);observed=date.mean(axis=0);n=len(date)
    errors.append(compare(boot['date_comparator_differences'],date,'shared-date mean differences'))
    errors.append(compare(boot['contract_comparator_differences'],diffs.mean(axis=0),'contract mean differences'))
    require(np.array_equal(boot['common_origins'],origins0),'bootstrap retained origins')
    require(summary['common_dates']==n and summary['primary_contract_cases']==n*len(cubes),'primary counts')
    # Prefix sums over a doubled circular series avoid the producer's concatenated index gather.
    prefix=np.vstack([np.zeros((1,date.shape[1]),dtype=np.longdouble),np.cumsum(np.tile(date,(2,1)),axis=0)])
    checked=[];interval_pass=[]
    for length in s['block_lengths']:
        starts=boot[f'block_starts_{length}']
        rng=np.random.Generator(np.random.PCG64(np.random.SeedSequence([s['seed'],length])))
        expected=rng.integers(0,n,size=(s['replicates'],math.ceil(n/length)),dtype=np.int32)
        require(np.array_equal(starts,expected),'frozen block-start RNG reproduction')
        full=prefix[starts+length]-prefix[starts]
        tail=n-(starts.shape[1]-1)*length
        partial=prefix[starts[:,-1]+tail]-prefix[starts[:,-1]]
        means=(full[:,:-1].sum(axis=1)+partial)/n
        errors.append(compare(boot[f'bootstrap_means_{length}'],means,'independent cumulative block means'))
        ordered=np.sort(means,axis=0)
        bounds=[]
        for probability in [Fraction(1,40),Fraction(19,20),Fraction(39,40)]:
            position=probability*(len(means)-1);lower=position.numerator//position.denominator
            fraction=position-lower
            if not fraction:val=ordered[lower]
            else:val=ordered[lower]+np.longdouble(fraction.numerator)/fraction.denominator*(ordered[lower+1]-ordered[lower])
            bounds.append(val)
        bounds=np.array(bounds)
        for j,name in enumerate(comparators):
            rows=[r for r in s['intervals'] if r['block_length']==length and r['comparator']==name]
            require(len(rows)==1,'unique comparator interval');row=rows[0]
            for field,value in [('observed_difference',observed[j]),('two_sided95_lower',bounds[0,j]),
                                ('one_sided95_upper',bounds[1,j]),('two_sided95_upper',bounds[2,j]),
                                ('bootstrap_mean',means[:,j].mean()),
                                ('bootstrap_sd',np.sqrt(np.sum((means[:,j]-means[:,j].mean())**2)/(len(means)-1)))]:
                errors.append(compare(row[field],value,'bootstrap '+field))
            passed=bool(bounds[1,j]<0)
            require(row['strictly_negative_upper']==passed,'individual interval gate')
            interval_pass.append(passed)
        checked.append(dict(length=length,replicates=len(means),comparators=len(comparators),last_block_retained_dates=tail))
    require(s['conjunctive_gate_passed']==all(interval_pass),'joint headline gate')
    for item in summary['primary_comparisons']:
        j=comparators.index(item['comparator']);means=diffs[:,:,j].mean(axis=0)
        errors.append(compare(item['mean_difference'],means.mean(),'summary primary difference'))
        require(item['contracts_better']==int((means< -1e-12).sum()),'contract wins')
        require(item['contracts_worse']==int((means> 1e-12).sum()),'contract losses')
        require(item['contracts_tied']==int((np.abs(means)<=1e-12).sum()),'contract ties')
    return dict(status='passed',summary_sha256=digest(summary_path),bootstrap_sha256=digest(boot_path),
        common_dates=n,contracts=len(cubes),block_replays=checked,
        max_absolute_difference=max(errors),conjunctive_gate_passed=all(interval_pass),
        scope='Independent deterministic replay of archived bootstrap; does not validate stationarity or future coverage')


def main():
    output=verify_archive()
    output['bootstrap_verification']=verify_bootstrap()
    target=ROOT/'results/aggregate_risk_verification.json'
    target.write_text(json.dumps(output,indent=2,allow_nan=False)+'\n')
    print(json.dumps(dict(status=output['status'],counts=output['archive_counts'],
                         max_absolute_differences=output['max_absolute_differences'],
                         bootstrap=output['bootstrap_verification']),indent=2),flush=True)


if __name__=='__main__': main()
