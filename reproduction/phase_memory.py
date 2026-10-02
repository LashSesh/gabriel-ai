"""Optional elapsed-time diagonal memory with damped rotation.

Complex modes are established linear state-space machinery. This module specifies
the held-input and bounded-input contracts used in the Gabriel extension.
All numerical functions here use float64, not directed rounding.
"""
import numpy as np


def parameters(phase=True, budget=16):
    if budget in (3, 5, 7) and phase:
        # One real mode, followed by one, two or three complex pairs.
        lam = np.r_[1., np.array([4., 1., 16.])[:(budget-1)//2]]
        omega = np.r_[0., 4*lam[1:]]
    elif phase and budget == 16:
        taus = np.repeat([1/16, 1/4, 1., 4.], 2)
        lam = 1/taus
        omega = np.tile([1., 4.], 4)*lam
    elif not phase and budget in (3, 5, 7, 16):
        lam = 1/np.geomspace(1/16, 4., budget)
        omega = np.zeros(budget)
    else: raise ValueError('budget must be 3, 5, 7 or 16')
    return lam, omega


class PhaseMemory:
    def __init__(self, lam, omega, channels=1):
        self.lam = np.asarray(lam, float).copy()
        self.omega = np.asarray(omega, float).copy()
        if (self.lam.ndim != 1 or not self.lam.size or
            self.omega.shape != self.lam.shape or
            not np.isfinite(self.lam).all() or not np.isfinite(self.omega).all() or
            np.any(self.lam <= 0) or not isinstance(channels, int) or channels < 1):
            raise ValueError('positive finite damping, finite frequencies, positive channel count required')
        self.z = np.zeros((len(self.lam), channels), complex)

    def advance(self, u, duration):
        u = np.asarray(u, float); h = float(duration)
        if (u.shape != (self.z.shape[1],) or not np.isfinite(u).all() or
            np.any(abs(u) > 1) or not np.isfinite(h) or h < 0):
            raise ValueError('bounded held input and nonnegative finite duration required')
        p = -self.lam + 1j*self.omega
        q = np.exp(p*h)
        b = self.lam*np.expm1(p*h)/p
        self.z = q[:, None]*self.z+b[:, None]*u
        return self.z.copy()

    def features(self):
        return np.r_[self.z.real.ravel(), self.z.imag.ravel()]


class PhaseEventMemory:
    """Parallel branch. A computational time subdivision is not a graph event."""
    def __init__(self, observer, lam, omega):
        self.observer = observer
        self.clock = PhaseMemory(lam, omega, observer.config.input_dim)
        self.event_count = 0

    def advance(self, u, duration, event_end=True):
        self.clock.advance(u, duration)
        if event_end:
            self.observer.step(u)
            self.event_count += 1


def kernel(durations, lam, omega):
    h = np.asarray(durations, float); lam = np.asarray(lam, float)
    # Constructor and zero step validate all parameter and duration contracts.
    obj = PhaseMemory(lam, omega)
    if h.ndim != 1 or not len(h) or not np.isfinite(h).all() or np.any(h < 0):
        raise ValueError('invalid durations')
    p = -lam+1j*obj.omega
    future = np.cumsum(h[::-1])[::-1]-h
    return np.exp(future[:, None]*p)*(lam*np.expm1(h[:, None]*p)/p)


def features(x, durations, phase=True, budget=16):
    x = np.asarray(x, float)
    if x.ndim != 3 or not np.isfinite(x).all() or np.any(abs(x)>1):
        raise ValueError('expected finite (records, events, channels) input in [-1,1]')
    lam, omega = parameters(phase, budget)
    k = kernel(durations, lam, omega)
    if len(k) != x.shape[1]: raise ValueError('duration length mismatch')
    z = np.einsum('tr,ntm->nrm', k, x)
    f = z.real.reshape(len(x), -1)
    if phase: f = np.c_[f, z[:, omega != 0].imag.reshape(len(x), -1)]
    return np.c_[np.ones(len(x)), f]


def compile_head(head, durations, channels, phase=True, budget=16):
    """Score = intercept + sum_{t,m} coefficient[t,m,:] * u[t,m]."""
    lam, omega = parameters(phase, budget); k = kernel(durations, lam, omega)
    R = len(lam); K = head.shape[1]
    a = head[1:1+R*channels].reshape(R, channels, K)
    c = np.einsum('tr,rmk->tmk', k.real, a)
    if phase:
        b = head[1+R*channels:].reshape(sum(omega != 0), channels, K)
        c += np.einsum('tr,rmk->tmk', k[:, omega != 0].imag, b)
    return head[0].copy(), c.reshape(-1, K)


def box_scores(intercept, coefficients, lo, hi):
    lo, hi = np.asarray(lo), np.asarray(hi)
    if lo.shape != hi.shape or np.any(lo > hi): raise ValueError('invalid box')
    mid = (lo+hi)/2; rad = (hi-lo)/2
    return intercept+mid@coefficients, rad@abs(coefficients)


def acquire(truth, missing, intercept, coefficients, policy):
    """Fixed policies on a buffered record; all reported margins use pair differences."""
    truth = np.asarray(truth); missing = np.asarray(missing, bool)
    if truth.ndim != 1 or missing.shape != truth.shape: raise ValueError('shape')
    K = len(intercept); ij = [(a,b) for a in range(K) for b in range(a+1,K)]
    dif = np.array([coefficients[:, a]-coefficients[:, b] for a,b in ij]).T
    dc = np.array([intercept[a]-intercept[b] for a,b in ij])
    ids = np.flatnonzero(missing)
    if policy == 'coefficient':
        importance = np.max(abs(dif), axis=1)
        order = ids[np.lexsort((ids, -importance[ids]))]
    elif policy == 'recent': order = ids[::-1]
    else: raise ValueError('unknown policy')
    mid = np.where(missing, 0., truth); radius = missing.astype(float)
    centers = dc+mid@dif; widths = radius@abs(dif)
    for j in range(len(order)+1):
        low = centers-widths
        for a in range(K):
            ok = all((low[k] if a==b else -centers[k]-widths[k]) > 1e-10
                     for k,(b,c) in enumerate(ij) if a in (b,c))
            if ok: return dict(winner=a, queries=order[:j].copy(), strict=True)
        if j == len(order):
            # Full observation resolves deterministic ties; validation must check them separately.
            return dict(winner=int(np.argmax(intercept+truth@coefficients)), queries=order.copy(), strict=False)
        q = order[j]; centers += truth[q]*dif[q]; widths -= abs(dif[q])
        widths = np.maximum(widths, 0.)
