"""Convex transformed VaR/ES aggregation and maturity-ordered simplex learning.

FZ0 is convex in (a,b)=(Q/E,1/E). A common simplex vector mixes
these transformed forecasts. Arithmetic mixing is supplied as a matched
nonconvex comparator. All numerical values and certificates are binary64;
the LP lower bound is not a directed-rounding proof.
"""
import math
import numpy as np
from scipy.optimize import minimize, linprog

BETA = 1/40
EXPERTS = ('raw_hs','fhs_w0','fhs_w025','fhs_w05','fhs_w075','fast_fhs',
           'fast_severity_125','fast_severity_500')


def validate_bank(q, e):
    q, e = np.asarray(q, float), np.asarray(e, float)
    if (q.ndim != 2 or q.shape != e.shape or min(q.shape) < 1 or
        not np.isfinite(q).all() or not np.isfinite(e).all() or
        np.any(q <= 0) or np.any(e < q) or np.any(e < 1/np.finfo(float).max)):
        raise ValueError('nonempty finite positive ordered expert matrices required')
    return q, e


def validate_weights(w, experts):
    w = np.asarray(w, float)
    if (w.shape != (experts,) or not np.isfinite(w).all() or
        np.any(w < 0) or abs(float(w.sum())-1) > 1e-10):
        raise ValueError('simplex weights required')
    return w


def project_simplex(v):
    """Euclidean projection onto the probability simplex by sorted threshold."""
    v = np.asarray(v, float)
    if v.ndim != 1 or not len(v) or not np.isfinite(v).all():
        raise ValueError('finite nonempty vector required')
    with np.errstate(over='ignore',invalid='ignore'):
        shifted=v-v.max()
    if not np.isfinite(shifted).all():raise ValueError('simplex input dynamic range overflow')
    ordered = np.sort(shifted)[::-1]
    with np.errstate(over='ignore'):
        cumulative = np.cumsum(ordered)-1
    active = np.flatnonzero(ordered-cumulative/np.arange(1,len(v)+1) > 0)
    threshold = cumulative[active[-1]]/(active[-1]+1)
    return np.maximum(shifted-threshold,0)


def transformed_mix(q,e,w):
    q,e = validate_bank(q,e)
    w = validate_weights(w,q.shape[1])
    b=(1/e)@w; a=(q/e)@w
    return a/b,1/b


def arithmetic_mix(q,e,w):
    q,e=validate_bank(q,e);w=validate_weights(w,q.shape[1])
    return q@w,e@w


def transformed_score_gradient(q,e,y,w,beta=BETA,rho=0):
    """Mean FZ0 plus rho/2 distance to uniform; zero hinge subgradient.

    Works on one or multiple rows. For original issued weights w the score
    is -log(Bw)+Aw+max(y*Bw-Aw,0)/beta-1.
    """
    q,e=validate_bank(q,e); w=validate_weights(w,q.shape[1])
    y=np.asarray(y,float)
    if y.shape != (len(q),) or not np.isfinite(y).all() or not 0<beta<1 or not np.isfinite(rho) or rho<0:
        raise ValueError('finite matching outcomes, beta in (0,1), rho >= 0 required')
    a=q/e;b=1/e;aw=a@w;bw=b@w;c=y[:,None]*b-a;cw=c@w
    score=-np.log(bw)+aw+np.maximum(cw,0)/beta-1
    grad=np.mean(-b/bw[:,None]+a+(cw>0)[:,None]*c/beta,axis=0)
    diff=w-1/len(w)
    return float(score.mean()+rho/2*(diff@diff)),grad+rho*diff


def arithmetic_score_gradient(q,e,y,w,beta=BETA,rho=0):
    q,e=validate_bank(q,e);w=validate_weights(w,q.shape[1]);y=np.asarray(y,float)
    if y.shape!=(len(q),) or not np.isfinite(y).all() or not 0<beta<1 or not np.isfinite(rho) or rho<0:
        raise ValueError('finite matching outcomes, beta in (0,1), rho >= 0 required')
    Q=q@w;E=e@w;positive=np.maximum(y-Q,0);hit=y>Q
    score=np.log(E)+(Q+positive/beta)/E-1
    dQ=(1-hit/beta)/E;dE=1/E-(Q+positive/beta)/E**2
    grad=np.mean(dQ[:,None]*q+dE[:,None]*e,axis=0)
    diff=w-1/len(w)
    return float(score.mean()+rho/2*(diff@diff)),grad+rho*diff


def convex_lower_certificate(q,e,y,w,beta=BETA,rho=.01):
    """Optimize a tangent/hinge dual lower bound on the whole simplex.

    Hinge duals lambda in [0,1] need not match the computed active set.
    Thus near-kink numerical issues cannot invalidate the real-arithmetic
    lower-bound derivation. The returned bound uses clipped feasible dual
    variables and recomputes its minimum directly, not the LP objective.
    """
    q,e=validate_bank(q,e);w=validate_weights(w,q.shape[1]);y=np.asarray(y,float)
    if y.shape!=(len(q),) or not np.isfinite(y).all() or not 0<beta<1 or not np.isfinite(rho) or rho<0:
        raise ValueError('finite matching outcomes, beta in (0,1), rho >= 0 required')
    a=q/e;b=1/e;c=y[:,None]*b-a;bw=b@w;aw=a@w;diff=w-1/len(w)
    f0=float(np.mean(-np.log(bw)+aw)-1+rho/2*(diff@diff))
    g0=np.mean(-b/bw[:,None]+a,axis=0)+rho*diff
    n=len(q);scale=1/(beta*n)
    matrix=np.column_stack([-scale*c.T,np.ones(len(w))])
    objective=np.r_[np.zeros(n),-1.0]
    solved=linprog(objective,A_ub=matrix,b_ub=g0,
                   bounds=[(0.,1.)]*n+[(None,None)],method='highs',
                   options={'dual_feasibility_tolerance':1e-9,
                            'primal_feasibility_tolerance':1e-9})
    lam=np.clip(solved.x[:n],0,1) if solved.success else (c@w>0).astype(float)
    dualgradient=g0+scale*(c.T@lam)
    lower=float(f0-g0@w+np.min(dualgradient))
    value,gradient=transformed_score_gradient(q,e,y,w,beta,rho)
    return dict(lower_bound=lower,objective=value,numerical_gap=float(value-lower),
                plain_subgradient_gap=float(w@gradient-np.min(gradient)),
                lp_success=bool(solved.success),lp_status=int(solved.status),
                lp_iterations=int(solved.nit),
                dual_min=float(lam.min()),dual_max=float(lam.max()),dual_lambda=lam.tolist(),
                rounding_status='binary64 evaluation; not an interval certificate')


def fit_static(q,e,y,geometry='transformed',rho=.01,beta=BETA,
               ftol=1e-12,maxiter=2000):
    """Fit all uniform/vertex starts; retain best feasible numerical objective.

    Arithmetic geometry has no global-optimality certificate. Transformed
    geometry reports a convex lower bound independently of SLSQP status.
    """
    q,e=validate_bank(q,e); y=np.asarray(y,float)
    if (y.shape!=(len(q),) or not np.isfinite(y).all() or not 0<beta<1 or
        not np.isfinite(rho) or rho<0 or not np.isfinite(ftol) or ftol<=0 or
        not isinstance(maxiter,(int,np.integer)) or isinstance(maxiter,bool) or maxiter<=0):
        raise ValueError('finite matching outcomes and valid optimization controls required')
    if geometry not in ('transformed','arithmetic'):raise ValueError('unknown geometry')
    fn=transformed_score_gradient if geometry=='transformed' else arithmetic_score_gradient
    k=q.shape[1];starts=[np.full(k,1/k)]+list(np.eye(k));records=[];candidates=[]
    # Prepared arrays avoid repeated full matrix validation inside the optimizer.
    a=q/e;b=1/e;c=y[:,None]*b-a;u=np.full(k,1/k)
    def objective(w):
        diff=w-u
        if geometry=='transformed':
            bw=b@w;aw=a@w;cw=c@w
            val=float(np.mean(-np.log(bw)+aw+np.maximum(cw,0)/beta-1))
            grad=np.mean(-b/bw[:,None]+a+(cw>0)[:,None]*c/beta,axis=0)
        else:
            Q=q@w;E=e@w;excess=np.maximum(y-Q,0)
            val=float(np.mean(np.log(E)+(Q+excess/beta)/E-1))
            grad=np.mean(((1-(y>Q)/beta)/E)[:,None]*q+
                (1/E-(Q+excess/beta)/E**2)[:,None]*e,axis=0)
        return val+rho/2*(diff@diff),grad+rho*diff
    for index,start in enumerate(starts):
        result=minimize(objective,start,method='SLSQP',jac=True,
            bounds=[(0.,1.)]*k,
            constraints={'type':'eq','fun':lambda w:float(w.sum()-1),
                         'jac':lambda w:np.ones_like(w)},
            options={'ftol':ftol,'maxiter':maxiter,'disp':False})
        weight=project_simplex(result.x)
        value,_=objective(weight)
        records.append(dict(start=index,success=bool(result.success),status=int(result.status),
            iterations=int(result.nit),objective=float(value),weights=weight.tolist(),
            message=str(result.message)))
        candidates.append((value,index,weight))
    value,index,weight=min(candidates,key=lambda item:(item[0],item[1]))
    certificate=convex_lower_certificate(q,e,y,weight,beta,rho) if geometry=='transformed' else None
    return dict(geometry=geometry,rho=rho,beta=beta,weights=weight.tolist(),
                objective=float(value),selected_start=index,starts=records,
                certificate=certificate,ftol=ftol,maxiter=maxiter)


def replay_adagrad(q,e,y,horizon,c,origins=None,beta=BETA):
    """Issue then mature in h lanes; updates precede today's issuance.

    Issuance j matures at index j+h. Its loss gradient uses the expert bank
    and simplex weights stored at j. With constant h and contiguous origins
    the corresponding lane has no intervening update. Pending gradients and
    update states are NaN, while their issued forecasts remain available.
    """
    q,e=validate_bank(q,e);y=np.asarray(y,float);n,k=q.shape
    if (not isinstance(horizon,(int,np.integer)) or isinstance(horizon,bool) or horizon<=0 or
        not np.isfinite(c) or c<=0 or not 0<beta<1 or y.shape!=(n,)):
        raise ValueError('positive integer horizon, positive scale and matching outcomes required')
    if origins is None: origins=np.arange(n)
    origins=np.asarray(origins)
    if origins.shape!=(n,) or origins.dtype.kind not in 'iu' or np.any(np.diff(origins)!=1):
        raise ValueError('contiguous integer origins required')
    matured=np.arange(n)+horizon<n
    if not np.isfinite(y[matured]).all():raise ValueError('finite matured outcomes required')
    fields=['issued_weights','preupdate_weights','postupdate_weights','gradient','centered_gradient']
    out={name:np.full((n,k),np.nan) for name in fields}
    for name in ['step','gradient_norm_squared','accumulator_before','accumulator_after','score']:
        out[name]=np.full(n,np.nan)
    out.update(var=np.empty(n),es=np.empty(n),matured=matured)
    states=np.full((horizon,k),1/k);acc=np.zeros(horizon)
    a=q/e;b=1/e
    for t in range(n):
        j=t-horizon
        if j>=0:
            slot=int(origins[j]%horizon);w=out['issued_weights'][j]
            aw=float(a[j]@w);bw=float(b[j]@w);cw=float(y[j]*bw-aw)
            gradient=-b[j]/bw+a[j]+(y[j]*b[j]-a[j])*(cw>0)/beta
            centered=gradient-gradient.mean();norm=float(centered@centered)
            before=float(acc[slot]);after=before+norm
            step=c/math.sqrt(after) if after>0 else 0.
            updated=project_simplex(states[slot]-step*centered)
            out['preupdate_weights'][j]=states[slot]
            out['postupdate_weights'][j]=updated
            out['gradient'][j]=gradient;out['centered_gradient'][j]=centered
            out['step'][j]=step;out['gradient_norm_squared'][j]=norm
            out['accumulator_before'][j]=before;out['accumulator_after'][j]=after
            out['score'][j]=-math.log(bw)+aw+max(cw,0)/beta-1
            states[slot]=updated;acc[slot]=after
        weight=states[int(origins[t]%horizon)].copy()
        out['issued_weights'][t]=weight
        mixed_b=float(b[t]@weight);mixed_a=float(a[t]@weight)
        out['var'][t]=mixed_a/mixed_b;out['es'][t]=1/mixed_b
    out['final_weights']=states;out['final_accumulators']=acc
    return out
