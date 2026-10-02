"""Executed exact witness checks for finite and convex-hull robust CVaR.

The main verification is rational primal/dual equality. An optional SciPy LP is
only a floating diagnostic and is reported separately. No market data or
financial-performance experiment is involved.
"""
from copy import deepcopy
from fractions import Fraction as F
from itertools import product, combinations_with_replacement
from pathlib import Path
import hashlib
import json
import random

from portfolio_risk import (cvar, cvar_certificate, robust_cvar,
                            verify_cvar_certificate, verify_robust_cvar_certificate)

ROOT = Path(__file__).resolve().parents[1]


def jsonable(value):
    if isinstance(value, F):
        return str(value)
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [jsonable(v) for v in value]
    return value


def reject(function):
    try:
        function()
    except ValueError:
        return
    raise AssertionError('invalid input or invalid certificate accepted')


def independent_tail_value(losses, probabilities, alpha):
    """Sort actual atoms and fill upper probability mass 1-alpha directly."""
    remaining = 1-alpha
    weighted = F(0)
    for loss, probability in sorted(zip(losses, probabilities), reverse=True):
        taken = min(remaining, probability)
        weighted += loss*taken
        remaining -= taken
    assert remaining == 0
    return weighted/(1-alpha)


def lp_diagnostic(losses, models, alpha):
    """Independent risk-envelope LP, using float conversion only here.

    Maximize loss dot q subject to sum(q)=1, sum(lambda)=1,
    q_s <= sum_m lambda_m p_ms/(1-alpha), q>=0, lambda>=0.
    """
    from scipy.optimize import linprog
    n, m = len(losses), len(models)
    objective = [-float(x) for x in losses]+[0.0]*m
    inequalities = []
    for s in range(n):
        row = [0.0]*(n+m)
        row[s] = 1.0
        for j in range(m):
            row[n+j] = -float(models[j][s]/(1-alpha))
        inequalities.append(row)
    equality = [[1.0]*n+[0.0]*m, [0.0]*n+[1.0]*m]
    result = linprog(objective, A_ub=inequalities, b_ub=[0.0]*n,
                     A_eq=equality, b_eq=[1.0,1.0], bounds=(0,None), method='highs')
    assert result.success, result.message
    return -result.fun


def main():
    counts = dict(exact_single_distribution_cases=0, exact_hull_cases=0,
                  mixture_grid_lower_checks=0, invariance_checks=0,
                  invalid_input_rejections=0, tamper_rejections=0)
    loss_vectors = tuple(combinations_with_replacement((-2,0,3),3))
    models = tuple(tuple(F(x,3) for x in v) for v in product(range(4),repeat=3)
                   if sum(v)==3)
    alphas = (F(0),F(1,3),F(1,2),F(2,3),F(9,10))
    diagnostic_cases = []
    two_model_witnesses = 0
    for losses, alpha, probabilities in product(loss_vectors,alphas,models):
        certificate = cvar_certificate(losses,probabilities,alpha)
        assert certificate['value']==independent_tail_value(losses,probabilities,alpha)
        assert verify_cvar_certificate(certificate,losses=losses,probabilities=probabilities,alpha=alpha)
        counts['exact_single_distribution_cases'] += 1
    for losses, alpha, family in product(loss_vectors,alphas,combinations_with_replacement(models,2)):
        certificate = robust_cvar(losses,family,alpha)
        value = certificate['value']
        assert verify_robust_cvar_certificate(certificate,losses=losses,models=family,alpha=alpha)
        assert value >= max(independent_tail_value(losses,p,alpha) for p in family)
        assert value == independent_tail_value(losses,certificate['mixture_probabilities'],alpha)
        two_model_witnesses += sum(w>0 for w in certificate['mixture_weights'])==2
        for w in (F(0),F(1,4),F(1,2),F(3,4),F(1)):
            mixed = tuple(w*p+(1-w)*q for p,q in zip(*family))
            assert independent_tail_value(losses,mixed,alpha)<=value
            counts['mixture_grid_lower_checks'] += 1
        counts['exact_hull_cases'] += 1
        if counts['exact_hull_cases'] % 50 == 0:
            diagnostic_cases.append((losses,family,alpha,value))

    # A strict failure of the max-listed-CVaR surrogate. The worst distribution
    # is interior in the convex hull, with a threshold between loss knots.
    counterexample = robust_cvar((-100,0,100),((0,1,0),(F(99,100),0,F(1,100))),F(1,2))
    assert counterexample['listed_value']==0
    assert counterexample['value']==F(100,99)
    assert counterexample['eta']==F(-100,99)
    assert counterexample['mixture_weights']==(F(49,99),F(50,99))

    # More than two input models, asymmetric probability denominators, zero
    # mass extreme losses, tied atoms, alpha zero and a near-one exact alpha.
    rng=random.Random(20260925)
    for _ in range(160):
        n=rng.randrange(1,7); m=rng.randrange(1,6)
        losses=tuple(F(rng.randrange(-20,21),rng.randrange(1,5)) for _ in range(n))
        family=[]
        for _ in range(m):
            weights=[rng.randrange(6) for _ in range(n)]
            if not sum(weights):weights[0]=1
            family.append(tuple(F(w,sum(weights)) for w in weights))
        family=tuple(family)
        alpha=rng.choice((F(0),F(1,2),F(7,10),F(999,1000)))
        certificate=robust_cvar(losses,family,alpha)
        value=certificate['value']
        assert value==independent_tail_value(losses,certificate['mixture_probabilities'],alpha)
        counts['exact_hull_cases']+=1
        shift=F(-13,7);scale=F(3,2)
        assert robust_cvar(tuple(x+shift for x in losses),family,alpha)['value']==value+shift
        assert robust_cvar(tuple(scale*x for x in losses),family,alpha)['value']==scale*value
        assert robust_cvar((0,)*n,family,alpha)['value']==0
        order=list(range(n));rng.shuffle(order)
        assert robust_cvar(tuple(losses[i] for i in order),
                           tuple(tuple(p[i] for i in order) for p in family),alpha)['value']==value
        assert robust_cvar(losses,tuple(reversed(family)),alpha)['value']==value
        assert robust_cvar(losses,family+(family[0],),alpha)['value']==value
        counts['invariance_checks']+=6
        if len(diagnostic_cases)<95:
            diagnostic_cases.append((losses,family,alpha,value))

    atoms=[((5,),(1,),F(0)),((5,),(1,),F(999,1000)),
           ((-100,7,100),(0,1,0),F(1,2)),((0,10,10),(F(1,2),F(1,4),F(1,4)),F(3,4))]
    for losses,p,alpha in atoms:
        certificate=cvar_certificate(losses,p,alpha)
        assert certificate['value']==independent_tail_value(losses,p,alpha)
        counts['exact_single_distribution_cases']+=1

    invalid=[lambda:cvar((),(),F(1,2)),lambda:cvar((1,),(),F(1,2)),
             lambda:cvar((1,2),(1,1),F(1,2)),lambda:cvar((1,2),(-1,2),F(1,2)),
             lambda:cvar((1,),(1,),1),lambda:cvar((1,),(1,),-1),
             lambda:cvar((1.0,),(1,),F(1,2)),lambda:cvar((1,),(1.0,),F(1,2)),
             lambda:cvar((True,),(1,),F(1,2)),lambda:cvar((1,),(1,),0.5),
             lambda:robust_cvar((1,),(),F(1,2)),lambda:robust_cvar((1,),((0,),),F(1,2)),
             lambda:robust_cvar((1,),((True,),),F(1,2)),lambda:cvar((1,),(1,),True)]
    for function in invalid:
        reject(function);counts['invalid_input_rejections']+=1

    original=cvar_certificate((0,10,20),(F(1,3),)*3,F(1,2))
    mutations=[('value',original['value']+1),('eta',original['eta']+1),
               ('tail_weights',(F(1),F(0),F(0))),('excesses',(F(1),)*3),
               ('tail_capacities',(F(1),)*3),('probabilities',(F(1),F(0),F(0)))]
    for key,replacement in mutations:
        changed=deepcopy(original);changed[key]=replacement
        reject(lambda c=changed:verify_cvar_certificate(c));counts['tamper_rejections']+=1
    for key,replacement in [('value',counterexample['value']+1),('eta',F(0)),
                            ('mixture_weights',(F(1),F(0))),('active_models',(0,)),
                            ('model_objectives',(F(0),F(0))),
                            ('mixture_probabilities',(F(0),F(1),F(0))),
                            ('listed_value',F(1)),('listed_values',(F(1),F(-96)))]:
        changed=deepcopy(counterexample);changed[key]=replacement
        reject(lambda c=changed:verify_robust_cvar_certificate(c));counts['tamper_rejections']+=1
    changed=deepcopy(counterexample);changed['lower_certificate']['value']+=1
    reject(lambda:verify_robust_cvar_certificate(changed));counts['tamper_rejections']+=1
    reject(lambda:verify_cvar_certificate(original,losses=(1,10,20)))
    reject(lambda:verify_cvar_certificate(original,probabilities=(F(1),F(0),F(0))))
    reject(lambda:verify_cvar_certificate(original,alpha=F(1,3)))
    reject(lambda:verify_robust_cvar_certificate(counterexample,models=((1,0,0),)))
    counts['tamper_rejections']+=4

    lp=dict(status='not_available',cases=0,scope='floating diagnostic; not an exact proof')
    try:
        import scipy
    except ImportError:
        pass
    else:
        errors=[]
        for losses,family,alpha,value in diagnostic_cases:
            found=lp_diagnostic(losses,family,alpha)
            error=abs(found-float(value))
            assert error<=1e-7*max(1,abs(float(value)))
            errors.append(error)
        lp.update(status='pass',cases=len(errors),max_absolute_error=max(errors),scipy_version=scipy.__version__)
    output=dict(status='pass',scope='exact finite risk arithmetic and certificate verification',
                counts=counts,grid_two_model_witnesses=two_model_witnesses,
                random_seed=20260925,random_multi_model_cases=160,
                counterexample=counterexample,linear_program_diagnostic=lp,
                certificate_basis='exact feasible tail dual equals threshold primal; hull upper equals attained mixture lower',
                source_sha256={name:hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest()
                               for name in ('portfolio_risk.py','check_portfolio_risk.py')})
    target=ROOT/'results'/'portfolio_risk_checks.json'
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(jsonable(output),indent=2)+'\n')
    print(json.dumps(jsonable(output),indent=2))


if __name__=='__main__':
    main()
