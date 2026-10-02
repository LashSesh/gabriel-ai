"""Maturity-ordered tail severity sufficient statistics and controlled examples.

The raw EWMA accumulator is never projected. Only its emitted common ES/VaR
ratio is bounded. All real-valued arithmetic is binary64; the synthetic
frequency controller alone retains the preceding exact integer lattice.
"""
from pathlib import Path
import hashlib
import json
import math
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_HASH = 'bf2b7ff636eebede7ad1e168689d836a653ddde0077314f3916fbc8691c7cc91'
BETA = 1/40


def load_protocol():
    raw = (ROOT/'results/severity_risk_protocol.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != PROTOCOL_HASH:
        raise ValueError('severity protocol changed')
    return json.loads(raw)


def validate_stream(q, losses, latency):
    q, losses = np.asarray(q, float), np.asarray(losses, float)
    if (q.ndim != 1 or losses.shape != q.shape or not len(q) or
        not np.isfinite(q).all() or np.any(q <= 0)):
        raise ValueError('finite positive issued quantiles and matching loss vector required')
    if not isinstance(latency, (int, np.integer)) or isinstance(latency, bool) or latency <= 0:
        raise ValueError('positive integer feedback latency required')
    matured = np.arange(len(q)) + latency < len(q)
    if not np.isfinite(losses[matured]).all():
        raise ValueError('all matured losses must be finite')
    return q, losses, matured


def replay_severity(issued_q, losses, latency, half_life, initial=1.5, cap=20):
    """Return issuance-aligned forecasts and feedback, with NaN pending updates.

    Feedback for issuance j is ingested at j+latency before that day's forecast.
    Its immutable issued Q determines R. preupdate_ratio/postupdate_ratio refer
    to that later receipt; issued_raw_ratio is the state at original issuance.
    """
    q, y, matured = validate_stream(issued_q, losses, latency)
    if (not np.isfinite(half_life) or half_life <= 0 or not np.isfinite(initial) or
        initial < 1 or not np.isfinite(cap) or cap < 1):
        raise ValueError('positive half-life, initial>=1 and cap>=1 required')
    decay = 2.0**(-1.0/half_life)
    n = len(q)
    out = {name:np.full(n, np.nan) for name in
           ['es','issued_raw_ratio','issued_ratio','R','preupdate_ratio','postupdate_ratio']}
    out.update(matured=matured, cap_flag=np.zeros(n, bool), decay=decay)
    state = float(initial)
    for t in range(n):
        j = t-latency
        if j >= 0:
            response = 1.0 + max(float(y[j]-q[j]), 0.0)/(BETA*q[j])
            if not math.isfinite(response):
                raise ValueError('nonfinite severity response')
            out['R'][j] = response
            out['preupdate_ratio'][j] = state
            state = decay*state + (1.0-decay)*response
            if not math.isfinite(state):
                raise ValueError('nonfinite severity accumulator')
            out['postupdate_ratio'][j] = state
        emitted = min(cap, max(1.0, state))
        out['issued_raw_ratio'][t] = state
        out['issued_ratio'][t] = emitted
        out['cap_flag'][t] = state > cap
        out['es'][t] = q[t]*emitted
    if not np.isfinite(out['es']).all() or np.any(out['es'] < q):
        raise ValueError('severity output outside positive ordered scoring domain')
    return out


def replay_frequency(base_q, base_e, losses, latency):
    """Frozen eta=1/20, beta=1/40, horizon lanes; arbitrary issued losses.

    Here latency controls feedback arrival for individual synthetic targets. It
    does not aggregate those targets into a multi-step return.
    """
    q, y, matured = validate_stream(base_q, losses, latency)
    e = np.asarray(base_e, float)
    if e.shape != q.shape or not np.isfinite(e).all() or np.any(e < q):
        raise ValueError('finite base ES >= base VaR required')
    n = len(q)
    out = {name:np.zeros(n, np.int64) for name in
           ['issued_units','preupdate_units','postupdate_units','projection_units']}
    out.update(var=np.empty(n), es=np.empty(n), matured=matured,
               matured_hit=np.full(n,-1,np.int8), denominator=800)
    states = [0]*latency
    for t in range(n):
        j = t-latency
        if j >= 0:
            slot = j % latency
            hit = int(y[j] > out['var'][j])
            before = states[slot]
            trial = before + 40*hit-1
            after = max(-800, min(800, trial))
            out['matured_hit'][j] = hit
            out['preupdate_units'][j] = before
            out['postupdate_units'][j] = after
            out['projection_units'][j] = after-trial
            states[slot] = after
        state = states[t % latency]
        out['issued_units'][t] = state
        scale = math.exp(state/800)
        out['var'][t], out['es'][t] = scale*q[t], scale*e[t]
    return out


def synthetic_sample(case_index, replicate, protocol):
    """Generate the exact declared independent U then V arrays and mixture."""
    spec = protocol['synthetic']
    if not isinstance(case_index, int) or not 0 <= case_index < len(spec['cases']):
        raise ValueError('invalid synthetic case')
    if not isinstance(replicate, int) or not 0 <= replicate < spec['replicates']:
        raise ValueError('invalid synthetic replicate')
    case = spec['cases'][case_index]
    origins = np.arange(spec['origins'])
    seed = [spec['seed_components'][0],case_index,replicate]
    rng = np.random.Generator(np.random.PCG64(np.random.SeedSequence(seed)))
    u, v = rng.random(len(origins)), rng.random(len(origins))
    scale = 1.0 + .25*np.sin(2*np.pi*origins/800)
    if case['name'] == 'stationary_bounded':
        d = np.full(len(origins),.5)
    elif case['name'] == 'recurrent_shift':
        d = np.where((origins//1000)%2==0,.5,3.)
    else:
        d = np.where(origins<4000,.5,3.)
    hit = u >= 39/40
    if case['tail'] == 'bounded':
        tail = 1+2*d*v
    elif case['tail'] == 'exponential':
        tail = 1-d*np.log1p(-v)
    else:
        raise ValueError('unknown synthetic tail')
    y = scale*np.where(hit,tail,-1+2*v)
    return dict(origins=origins, losses=y, scale=scale, tail_mean=d,
                true_var=scale, true_es=scale*(1+d),
                base_var=case['q_factor']*scale,
                base_es=1.5*case['q_factor']*scale,
                generated_tail=hit, seed=seed, tail=case['tail'])


def conditional_positive_part(q, scale, tail_mean, tail):
    """Analytic E[(Y-Q)+] for the declared uniform-body mixture."""
    q, s, d = np.broadcast_arrays(np.asarray(q,float),np.asarray(scale,float),
                                   np.asarray(tail_mean,float))
    if (not np.isfinite(q).all() or not np.isfinite(s).all() or not np.isfinite(d).all()
        or np.any(s<=0) or np.any(d<=0)):
        raise ValueError('finite thresholds, positive scales and tail means required')
    a = q/s
    body = np.where(a<=-1,-a,np.maximum(1-a,0)**2/4)
    if tail == 'bounded':
        excess = np.where(a<=1,1+d-a,np.maximum(1+2*d-a,0)**2/(4*d))
    elif tail == 'exponential':
        excess = np.where(a<=1,1+d-a,d*np.exp(-np.maximum(a-1,0)/d))
    else:
        raise ValueError('unknown synthetic tail')
    return s*((1-BETA)*body+BETA*excess)


def analytic_score_diagnostics(q, e, scale, tail_mean, tail):
    q, e, s, d = np.broadcast_arrays(np.asarray(q,float),np.asarray(e,float),
                                     np.asarray(scale,float),np.asarray(tail_mean,float))
    if not np.isfinite(e).all() or np.any(e<=0) or np.any(q>e):
        raise ValueError('positive ordered forecasts required')
    psi = q+conditional_positive_part(q,s,d,tail)/BETA
    truth = s*(1+d)
    score = np.log(e)+psi/e-1
    quantile_cost = np.log(psi/truth)
    severity_cost = np.log(e/psi)+psi/e-1
    residual = score-np.log(truth)-quantile_cost-severity_cost
    return dict(expected_fz0=score,quantile_score_excess=quantile_cost,
                severity_score_excess=severity_cost,decomposition_residual=residual,
                psi=psi)
