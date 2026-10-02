"""Synchronous, sparse, locally plastic Gabriel cell reference model.
All updates use the OLD activity and traces; no online supervised core training.
"""
from dataclasses import dataclass
import numpy as np

@dataclass(frozen=True)
class Config:
    n: int = 48
    degree: int = 6
    backbone_degree: int = 2
    input_dim: int = 2
    g0: float = .4
    gains: tuple = (.07, .07)
    betas: tuple = (.03, .2)
    thresholds: tuple = (.08, .08)
    leaks: tuple = (.15, .4, .8)
    input_scale: float = .8
    bias_scale: float = .15


def soft_threshold(c, threshold):
    return np.sign(c) * np.maximum(np.abs(c) - threshold, 0.)


class Gabriel:
    def __init__(self, seed=0, config=Config(), mode='adaptive'):
        self.config, self.mode = config, mode
        p = config
        if not (0 < p.degree < p.n):
            raise ValueError('degree must be in [1,n-1]')
        if len(p.gains) != len(p.betas) or len(p.gains) != len(p.thresholds):
            raise ValueError('trace parameter lengths differ')
        if any(not 0 < b <= 1 for b in p.betas) or any(not 0 < a <= 1 for a in p.leaks):
            raise ValueError('rates must be in (0,1]')
        if p.g0 < 0 or any(g < 0 for g in p.gains) or any(not 0 <= z < 1 for z in p.thresholds):
            raise ValueError('invalid gain or threshold')
        if mode not in ('adaptive','fixed','budget','trace_only'):
            raise ValueError(mode)
        rng = np.random.default_rng(seed)
        self.parents = np.stack([rng.choice(np.delete(np.arange(p.n),i),p.degree,replace=False) for i in range(p.n)])
        base = rng.normal(size=(p.n,p.degree))
        if not (0 < p.backbone_degree <= p.degree):
            raise ValueError('invalid backbone degree')
        if mode != 'budget':
            base[:,p.backbone_degree:] = 0.
        base /= np.abs(base).sum(axis=1,keepdims=True)
        budget = p.g0 + sum(g*(1-z) for g,z in zip(p.gains,p.thresholds))
        self.base = base * (budget if mode == 'budget' else p.g0)
        self.U = rng.uniform(-p.input_scale,p.input_scale,(p.n,p.input_dim))
        self.bias = rng.uniform(-p.bias_scale,p.bias_scale,p.n)
        self.alpha = np.resize(np.array(p.leaks),p.n)
        self.beta = np.array(p.betas)[:,None,None]
        self.lam = np.array(p.thresholds)[:,None,None]
        self.gains = np.array(p.gains)[:,None,None]
        self.reset()

    def reset(self):
        self.x = np.zeros(self.config.n)
        self.c = np.zeros((len(self.config.betas),self.config.n,self.config.degree))

    def weights(self):
        if self.mode != 'adaptive': return self.base.copy()
        return self.base + (self.gains*soft_threshold(self.c,self.lam)).sum(axis=0)/self.config.degree

    def step(self,u):
        u = np.asarray(u,dtype=float)
        if u.shape != (self.config.input_dim,) or not np.isfinite(u).all():
            raise ValueError('input has wrong shape or is nonfinite')
        oldx = self.x
        drive = np.sum(self.weights()*oldx[self.parents],axis=1)+self.U@u+self.bias
        newx = (1-self.alpha)*oldx+self.alpha*np.tanh(drive)
        if self.mode in ('adaptive','trace_only'):
            correlation = oldx[:,None]*oldx[self.parents]
            self.c = (1-self.beta)*self.c+self.beta*correlation[None,:,:]
        self.x = newx
        return self.x.copy()

    def features(self,u,joint=False):
        parts = [np.asarray(u),self.x]
        if joint: parts.append(self.c.mean(axis=2).reshape(-1))
        return np.concatenate(parts)

    def certificate(self):
        p=self.config
        gains=np.array(p.gains) if self.mode=='adaptive' else np.zeros(len(p.gains))
        q=float(np.max(np.abs(self.base).sum(axis=1))+np.sum(gains*(1-np.array(p.thresholds))))
        # Common trace scale r produces a valid weighted max norm for all leak rates.
        if self.mode in ('fixed','budget'):
            return dict(valid=bool(q<1),scope='activity only; traces unused',q=q,load=q,kappa=float(np.max(1-self.alpha+self.alpha*q)))
        if q+2*gains.sum() < 1:
            r=.5*(2+(1-q)/gains.sum()) if gains.sum()>0 else 3.
            kx=float(np.max(1-self.alpha+self.alpha*(q+r*gains.sum())))
            kc=float(np.max(1-np.array(p.betas)+2*np.array(p.betas)/r))
            return dict(valid=True,scope='activity and traces',q=q,load=q+2*float(gains.sum()),trace_scale=r,kappa=max(kx,kc))
        return dict(valid=False,scope='activity and traces',q=q,load=q+2*float(gains.sum()))

    def distance(self,other,r):
        return max(float(np.max(np.abs(self.x-other.x))),float(np.max(np.abs(self.c-other.c)))/r)

    def step_cell(self,i,u):
        """One local update, current neighbor values, no communication delay.
        A fair schedule is required for the sweep-wise convergence theorem.
        """
        p=self.config;u=np.asarray(u,dtype=float)
        if u.shape!=(p.input_dim,) or not np.isfinite(u).all():raise ValueError('invalid input')
        old=self.x[i];neighbors=self.x[self.parents[i]].copy()
        w=self.base[i].copy()
        if self.mode=='adaptive':
            w+=(self.gains[:,0,0,None]*soft_threshold(self.c[:,i,:],self.lam[:,0,0,None])).sum(axis=0)/p.degree
        nx=(1-self.alpha[i])*old+self.alpha[i]*np.tanh(w@neighbors+self.U[i]@u+self.bias[i])
        if self.mode in ('adaptive','trace_only'):
            self.c[:,i,:]=(1-self.beta[:,0,:])*self.c[:,i,:]+self.beta[:,0,:]*(old*neighbors)[None,:]
        self.x[i]=nx
        return float(nx)
