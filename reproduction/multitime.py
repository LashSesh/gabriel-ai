"""Bounded degree-two fading signature for a held two-channel input.

The signature principle is established (Abi Jaber & Sotnikov, 2025/2026).
This is the explicit normalized two-channel realization used by this project.
Physical durations and semantic event counts are deliberately separate.
"""
import numpy as np


class OrderedMemory:
    def __init__(self, taus=(.5, 2., 8., 32.)):
        self.taus = np.asarray(taus, dtype=float)
        if self.taus.ndim != 1 or not len(self.taus) or not np.isfinite(self.taus).all() or np.any(self.taus <= 0):
            raise ValueError('time constants must be finite and positive')
        self.a = np.zeros((len(self.taus), 2))
        self.r = np.zeros(len(self.taus))
        self.symmetric = np.zeros(len(self.taus))

    def advance(self, u, duration):
        """Advance through a known held interval. Uses OLD a in the area update."""
        u = np.asarray(u, dtype=float)
        h = float(duration)
        if u.shape != (2,) or not np.isfinite(u).all() or np.any(np.abs(u) > 1):
            raise ValueError('held input must be a finite vector in [-1,1]^2')
        if not np.isfinite(h) or h < 0:
            raise ValueError('duration must be finite and nonnegative')
        loss = -np.expm1(-h / self.taus)
        decay = np.exp(-h / self.taus)
        wedge = self.a[:, 0] * u[1] - self.a[:, 1] * u[0]
        self.r = decay**2 * self.r + decay * loss * wedge
        self.symmetric = decay**2 * self.symmetric + (-np.expm1(-2*h/self.taus))*u[0]*u[1]
        self.a = decay[:, None] * self.a + loss[:, None] * u
        return self.features()

    def features(self):
        return np.r_[self.a.ravel(), self.r]

    def distance(self, other):
        return max(float(np.max(np.abs(self.a-other.a))),
                   .5*float(np.max(np.abs(self.r-other.r))))

    def transfer(self, u, duration, channel=0):
        """Affine 4x4 map on (a1,a2,r,1); matrix products preserve order."""
        u = np.asarray(u, dtype=float)
        h = float(duration)
        if u.shape != (2,) or not np.isfinite(u).all() or np.any(np.abs(u)>1) or not np.isfinite(h) or h<0:
            raise ValueError('invalid interval')
        e = np.exp(-h/self.taus[channel]); v=-np.expm1(-h/self.taus[channel])
        return np.array([[e,0,0,v*u[0]], [0,e,0,v*u[1]],
                         [e*v*u[1],-e*v*u[0],e*e,0], [0,0,0,1.]])


class EventMemory:
    """Integrate wall time continuously; update the graph ONLY at event_end.

Refining a held interval never creates a new semantic event. Event boundaries
must be supplied, not guessed from equal consecutive values.
"""
    def __init__(self, observer, taus=(.5, 2., 8., 32.), depth=12):
        self.observer = observer
        self.clock = OrderedMemory(taus)
        self.delays = np.zeros((depth+1, 2))
        self.event_count = 0

    def advance(self, u, duration, event_end=True):
        self.clock.advance(u, duration)
        if event_end:
            self.observer.step(u)
            self.delays[1:] = self.delays[:-1].copy()
            self.delays[0] = u
            self.event_count += 1

    def state(self):
        return np.r_[self.observer.x, self.observer.c.ravel(),
                     self.delays.ravel(), self.clock.features()]
