"""Numerical reference cases and explicit donor-claim counterexamples."""
from pathlib import Path
import json, itertools
import numpy as np
from scipy.linalg import expm
from phase_memory import PhaseMemory, PhaseEventMemory, parameters, kernel, features, compile_head
from gabriel import Gabriel, Config

ROOT=Path(__file__).resolve().parents[1]

def main():
    rng=np.random.default_rng(20260925)
    errs=dict(matrix_exponential=0.,subdivision=0.,contraction=0.,units_covariance=0.,kernel=0.,vertices=0.)
    for i in range(300):
        lam=10**rng.uniform(-2,2); om=rng.uniform(-20,20)*lam
        h=10**rng.uniform(-5,1)/lam; u=rng.uniform(-1,1)
        z=(rng.uniform(-1,1)+1j*rng.uniform(-1,1))/np.sqrt(2)
        a=PhaseMemory([lam],[om]); a.z[:]=z; a.advance([u],h)
        M=np.array([[-lam,-om,lam],[om,-lam,0.],[0.,0.,0.]])
        ref=expm(M*h)@np.array([z.real,z.imag,u])
        errs['matrix_exponential']=max(errs['matrix_exponential'],float(abs(a.z.item()-complex(*ref[:2]))))
        b=PhaseMemory([lam],[om]); b.z[:]=z
        for frac in [.125,.375,.5]: b.advance([u],h*frac)
        errs['subdivision']=max(errs['subdivision'],float(abs(a.z.item()-b.z.item())))
        c=PhaseMemory([lam],[om]); c.z[:]=-z; c.advance([u],h)
        errs['contraction']=max(errs['contraction'],float(abs(abs(a.z.item()-c.z.item())-2*abs(z)*np.exp(-lam*h))))
        scale=10**rng.uniform(-4,4); d=PhaseMemory([lam/scale],[om/scale]); d.z[:]=z; d.advance([u],h*scale)
        errs['units_covariance']=max(errs['units_covariance'],float(abs(a.z.item()-d.z.item())))
        assert abs(a.z.item()) <= 1+1e-12
    for phase in (False,True):
      for budget in (3,5,7,16):
        lam,omega=parameters(phase,budget); u=rng.uniform(-1,1,(12,2)); h=rng.uniform(.01,.2,12)
        mem=PhaseMemory(lam,omega,2)
        for v,dt in zip(u,h):mem.advance(v,dt)
        f=np.r_[1.,mem.z.real.ravel(),mem.z[omega!=0].imag.ravel()] if phase else np.r_[1.,mem.z.real.ravel()]
        ff=features(u[None],h,phase,budget)[0]
        errs['kernel']=max(errs['kernel'],float(np.max(abs(f-ff))))
        head=rng.normal(size=(len(f),3)); b,c=compile_head(head,h,2,phase,budget)
        assert np.max(abs(b+u.ravel()@c-f@head))<1e-12
    # Complete vertex audit for 8 independent unknowns, 20 random kernels/heads.
    vertices=np.array(list(itertools.product([-1.,1.],repeat=8)))
    for _ in range(20):
        h=rng.uniform(.01,.5,4); head=rng.normal(size=(33,2)); b,c=compile_head(head,h,2)
        vals=b+vertices@c; exact=np.array([b-abs(c).sum(0),b+abs(c).sum(0)])
        errs['vertices']=max(errs['vertices'],float(np.max(abs(exact-np.array([vals.min(0),vals.max(0)])))))
    # Two old graph-event contracts remain identical under clock subdivision.
    g=Gabriel(0,Config(input_dim=2),mode='trace_only'); gg=Gabriel(0,Config(input_dim=2),mode='trace_only')
    lam,om=parameters(); a=PhaseEventMemory(g,lam,om); b=PhaseEventMemory(gg,lam,om)
    for _ in range(40):
        u=rng.uniform(-1,1,2); h=rng.uniform(.01,.5)
        a.advance(u,h); b.advance(u,h/3,False); b.advance(u,2*h/3,True)
    assert a.event_count==b.event_count==40 and np.array_equal(g.x,gg.x) and np.array_equal(g.c,gg.c)
    assert np.max(abs(a.clock.z-b.clock.z))<1e-13
    # Five differentiable coordinates cannot exactly encode a locally free 6D state.
    A=-np.diag(np.arange(1.,7.)); B=np.ones(6); C=np.ones(6)
    controllable=np.column_stack([np.linalg.matrix_power(A,k)@B for k in range(6)])
    observable=np.vstack([C@np.linalg.matrix_power(A,k) for k in range(6)])
    assert np.linalg.matrix_rank(controllable)==np.linalg.matrix_rank(observable)==6
    # Explicit failures of blanket donor statements, not claims about all instances.
    counterexamples=dict(
        singleton_segment_action={"W_ab":1,"W_a_plus_W_b":0},
        pseudometric={"s":[0,0,0,0,0],"t":[0,0,0,1,0],"fields":"first three coordinates","distance":0},
        gradient_feedback={"potential":"||s||^2/2","step":0.1,"expansion":1.1,"angle":"constant along nonzero radial orbit"},
        expanding_radius={"exponent":1,"one_step_gain":float(np.e)},
        phase_only_alias={"angles":[0,float(2*np.pi)],"same_angle_modulo_2pi":True},
        shared_uncertainty={"coefficients":[1,-1],"shared_half_width":0,"independent_half_width":2},
        six_state_linear_system={"controllability_rank":6,"observability_rank":6},
        euler_rotation={"lambda":1,"omega":4,"h":.2,"one_step_modulus":float(abs(1+.2*(-1+4j))),"exact_modulus":float(np.exp(-.2))})
    assert all(v<2e-11 for v in errs.values()),errs
    out=dict(seed=20260925,random_continuous_cases=300,bank_variants=8,vertex_boxes=20,vertices_per_box=256,event_pairs=40,max_absolute_errors=errs,counterexamples=counterexamples,tolerances={"float_reference":2e-11,"event_clock":1e-13},status="executed; numeric checks supplement proofs, not a formal proof assistant")
    (ROOT/'results/phase_checks.json').write_text(json.dumps(out,indent=2));print(json.dumps(out,indent=2))

if __name__=='__main__':main()
