"""Algebraic and numerical checks of partial-observation contracts."""
import json,copy,itertools
from fractions import Fraction as F
from pathlib import Path
import numpy as np
from partial_observation import VertexAudit,replay_features,interval_bounds,sign_verdict,TAUS

OUT=Path(__file__).resolve().parents[1]/'results'

def main():
    rng=np.random.default_rng(92024);interpolation=0.;refinement=0.;minimax_excess=-np.inf;range_excess=-np.inf
    for trial in range(100):
        u=rng.uniform(-1,1,(6,2));h=rng.uniform(.1,2,6);lo=u.copy();hi=u.copy()
        missing=rng.choice(12,6,replace=False);lo.ravel()[missing]=-1;hi.ravel()[missing]=1
        c=rng.normal(size=16);a=VertexAudit(lo,hi,h,c)
        random_inputs=np.broadcast_to(u,(30,6,2)).copy()
        random_inputs.reshape(30,-1)[:,missing]=rng.uniform(-1,1,(30,6))
        y=replay_features(random_inputs,h)@c
        range_excess=max(range_excess,float(a.bounds()[0]-y.min()),float(y.max()-a.bounds()[1]))
        scores=a.scores()
        for coord in a.unknown:
            for value in [-1,-.7,0,.3,1]:
                b=copy.deepcopy(a);b.acquire(coord,value)
                minimax_excess=max(minimax_excess,b.bounds()[1]-b.bounds()[0]-scores[coord])
        q=a.choose();a.acquire(q,float(u.ravel()[q]));b=VertexAudit(a.lower,a.upper,h,c)
        interpolation=max(interpolation,float(np.max(np.abs(a.values-b.values))))
        refinement=max(refinement,float(np.max(np.abs(replay_features(random_inputs,h)-replay_features(random_inputs,h,substeps=3)))))
        before=a.bounds();before_values=a.values.copy()
        assert a.acquire(q,float(u.ravel()[q])) is False
        assert a.bounds()==before and np.array_equal(a.values,before_values)
        try:a.acquire(q,float(u.ravel()[q])+.01)
        except ValueError:pass
        else:raise AssertionError('conflicting repeated record accepted')
    # Independent exact rational recursion on all vertices of a six-variable box.
    rational_error=0.; c=np.zeros(7);c[-1]=1
    lo=np.full((3,2),-1.);hi=-lo;h=np.full(3,np.log(2.))
    a=VertexAudit(lo,hi,h,c,taus=np.array([1.]))
    for idx,vertex in enumerate(itertools.product([-1,1],repeat=6)):
        av=[F(0),F(0)];rv=F(0)
        for j in range(3):
            v=vertex[2*j:2*j+2]
            rv=rv/F(4)+(av[0]*v[1]-av[1]*v[0])/F(4)
            av=[(av[k]+v[k])/F(2) for k in range(2)]
        rational_error=max(rational_error,abs(float(rv)-a.values.ravel()[idx]))
    # A single unknown held event cannot create order from zero initialization.
    c=np.zeros(7);c[-1]=1;lo=np.full((1,2),-1.);hi=-lo;h=np.array([np.log(2.)])
    whole=interval_bounds(lo,hi,h,c,taus=np.array([1.]))
    split=interval_bounds(np.repeat(lo,2,0),np.repeat(hi,2,0),np.repeat(h/2,2),c,taus=np.array([1.]))
    assert whole==(0.,0.) and split[0]<-.1 and split[1]>.1
    vertices=np.array(list(itertools.product([-1.,1.],repeat=2)))[:,None,:]
    assert np.max(np.abs(replay_features(vertices,h,taus=np.array([1.]),substeps=2)[:,-1]))<1e-15
    # QPM vacuity and rank counterexamples are computed, not just listed.
    empty_all_true=all(x>0 for x in []) and all(x<=0 for x in [])
    assert empty_all_true
    try:sign_verdict((1.,-1.))
    except ValueError:empty_rejected=True
    else:raise AssertionError('empty range accepted')
    points=np.array([-1.,1.]);constant_matrices=np.array([np.eye(2) for _ in points])
    assert np.all(np.linalg.matrix_rank(constant_matrices)==2) and np.array_equal(constant_matrices[0],constant_matrices[1])
    assert interpolation<1e-12 and refinement<1e-12 and minimax_excess<1e-12 and range_excess<1e-12 and rational_error<1e-14
    result=dict(random_trials=100,interior_completions=3000,interpolation_max_error=interpolation,
        refinement_max_error=refinement,worst_case_width_max_excess=float(minimax_excess),
        range_max_excess=float(range_excess),exact_rational_vertices=64,rational_reference_error=float(rational_error),
        naive_box_unsplit=whole,naive_box_subdivided=split,shared_variable_refinement_order=0.,
        duplicate_query_idempotent=True,conflicting_duplicate_rejected=True,empty_evidence_rejected=empty_rejected,
        qpm_empty_set_both_predicates_true=empty_all_true,full_rank_constant_measurement_identifies_nothing=True,tolerance=1e-12)
    (OUT/'partial_checks.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))

if __name__=='__main__':main()
