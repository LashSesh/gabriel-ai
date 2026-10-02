"""Independent ODE reference, algebraic controls and source counterexamples."""
import json, copy
from pathlib import Path
import numpy as np
from scipy.integrate import solve_ivp
from gabriel import Gabriel
from multitime import OrderedMemory, EventMemory

ROOT=Path(__file__).resolve().parents[1]

def main():
    rng=np.random.default_rng(91407)
    semigroup=0.; excess=-np.inf; max_state=0.; matrix_error=0.
    for _ in range(2000):
        a=OrderedMemory(); a.a=rng.uniform(-1,1,a.a.shape); a.r=rng.uniform(-1,1,a.r.shape)
        b=copy.deepcopy(a); c=copy.deepcopy(a)
        c.a=rng.uniform(-1,1,c.a.shape);c.r=rng.uniform(-1,1,c.r.shape)
        d=a.distance(c);u=rng.uniform(-1,1,2);h=float(10**rng.uniform(-7,2))
        state=np.r_[a.a[0],a.r[0],1.];mat=a.transfer(u,h)
        a.advance(u,h);c.advance(u,h)
        f=float(rng.uniform());b.advance(u,h*f);b.advance(u,h*(1-f))
        semigroup=max(semigroup,np.max(np.abs(a.features()-b.features())))
        matrix_error=max(matrix_error,np.max(np.abs(mat@state-np.r_[a.a[0],a.r[0],1.])))
        excess=max(excess,a.distance(c)-np.exp(-h/32)*d)
        max_state=max(max_state,np.max(np.abs(a.features())))
    ode_error=0.
    for _ in range(40):
        tau=float(10**rng.uniform(-.5,1));h=float(rng.uniform(.01,3));u=rng.uniform(-1,1,2)
        start=rng.uniform(-1,1,3);m=OrderedMemory((tau,));m.a[0]=start[:2];m.r[0]=start[2]
        def rhs(t,z): return [(u[0]-z[0])/tau,(u[1]-z[1])/tau,(-2*z[2]+z[0]*u[1]-z[1]*u[0])/tau]
        ref=solve_ivp(rhs,(0,h),start,method='DOP853',rtol=1e-12,atol=1e-14)
        assert ref.success
        m.advance(u,h);ode_error=max(ode_error,np.max(np.abs(m.features()-ref.y[:,-1])))
    # Same first-level endpoint, opposite second-level information.
    ab=OrderedMemory((1.,));ba=OrderedMemory((1.,));h=np.log(2.)
    ab.advance([.8,0],h);ab.advance([0,.4],h)
    ba.advance([0,.8],h);ba.advance([.4,0],h)
    assert np.allclose(ab.a,ba.a,atol=1e-15) and np.allclose([ab.r[0],ba.r[0]],[.04,-.04])
    # Whole architecture: only the original event boundary advances the graph/delays.
    a=EventMemory(Gabriel(88,mode='trace_only'));b=EventMemory(Gabriel(88,mode='trace_only'))
    wrong=EventMemory(Gabriel(88,mode='trace_only'));partition=0.
    for _ in range(100):
        u=rng.uniform(-1,1,2);h=float(rng.uniform(.05,2));k=int(rng.integers(2,8))
        a.advance(u,h)
        for j in range(k):
            b.advance(u,h/k,event_end=(j==k-1));wrong.advance(u,h/k)
        partition=max(partition,np.max(np.abs(a.state()-b.state())))
    wrong_error=float(np.max(np.abs(a.state()-wrong.state())))
    # Conjugate ALL typed node data, not just the unweighted graph.
    m=Gabriel(91);m.x=rng.uniform(-1,1,m.x.shape);m.c=rng.uniform(-1,1,m.c.shape)
    perm=rng.permutation(48);inv=np.argsort(perm);p=copy.deepcopy(m)
    p.parents=inv[m.parents[perm]]
    for name in ['base','U','bias','alpha','x']:setattr(p,name,getattr(m,name)[perm].copy())
    p.c=m.c[:,perm,:].copy();equivariance=0.
    for _ in range(100):
        u=rng.uniform(-1,1,2);m.step(u);p.step(u)
        equivariance=max(equivariance,np.max(np.abs(p.x-m.x[perm])),np.max(np.abs(p.c-m.c[:,perm,:])))
    # Grid I.15: monotone Boolean-coordinate swap has a two-cycle, even with identity closure.
    points=[np.array([i,j]) for i in [0,1] for j in [0,1]]
    swap=lambda z:z[::-1]
    assert all(np.all(swap(x)<=swap(y)) for x in points for y in points if np.all(x<=y))
    z=np.array([0,1]);cycle=[z.tolist()]
    for _ in range(2):z=swap(z);cycle.append(z.tolist())
    assert cycle[0]==cycle[2] and cycle[0]!=cycle[1]
    # PSP spectral traces contain no extra information beyond the full spectrum.
    star=np.zeros((5,5));star[0,1:]=1;star[1:,0]=1
    square=np.zeros((5,5))
    for i in range(4):square[i,(i+1)%4]=square[(i+1)%4,i]=1
    spectra_error=float(np.max(np.abs(np.linalg.eigvalsh(star)-np.linalg.eigvalsh(square))))
    assert all(np.trace(np.linalg.matrix_power(star,k))==np.trace(np.linalg.matrix_power(square,k)) for k in range(1,17))
    # Grid I.17: su(2) is dimension three without Heisenberg relations.
    sx=np.array([[0,1],[1,0]],complex)*1j;sy=np.array([[0,-1j],[1j,0]],complex)*1j
    comm=sx@sy-sy@sx;nested=sx@comm-comm@sx
    q=np.array([1.,1.]);A=np.diag([.2,.8]);hidden=np.array([1.,-1.])
    assert q@hidden==0 and abs(q@A@hidden)>.5
    assert semigroup<3e-14 and matrix_error<3e-14 and excess<3e-14 and max_state<=1+3e-14
    assert ode_error<3e-11 and partition<3e-14 and equivariance<3e-14 and wrong_error>1e-3
    result=dict(seed=91407,random_trials=2000,semigroup_max_error=float(semigroup),
        affine_map_max_error=float(matrix_error),contraction_max_excess=float(excess),
        maximum_absolute_state=float(max_state),ode_reference_trials=40,ode_max_error=float(ode_error),
        event_partition_max_error=float(partition),wrong_extra_events_state_difference=wrong_error,
        events_correct=a.event_count,events_incorrect=wrong.event_count,
        identical_first_level=ab.a.tolist(),opposite_order_coordinates=[float(ab.r[0]),float(ba.r[0])],
        node_equivariance_max_error=float(equivariance),monotone_nonterminating_cycle=cycle,
        cospectral_error=spectra_error,spectral_moments_checked=16,
        nonheisenberg_three_dimensional_nested_commutator_norm=float(np.linalg.norm(nested)),
        projection_hidden_next_output=float(q@A@hidden),tolerance=3e-14,ode_tolerance=3e-11)
    (ROOT/'results/multitime_checks.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
