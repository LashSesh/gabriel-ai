"""Sign transport, invariant Gabriel traces and exact binary observation.

All combinatorial arithmetic is exact over GF(2). Floating dynamics use binary64.
An edge sign is a FIXED declared transport; plastic amplitude is a separate value.
The reference anchor is metadata and never a vertex in an operational route.
"""
from collections import deque
from copy import deepcopy
from dataclasses import dataclass
import itertools
import numpy as np
from gabriel import Config, Gabriel, soft_threshold


def profile_graph(ring_size=6, include_anchor=False):
    if not isinstance(ring_size, int) or ring_size < 4:
        raise ValueError('ring_size must be an integer >= 4')
    m=ring_size; edges=set()
    for i in range(m):
        a,b=1+i,1+(i+1)%m; c,d=1+m+i,1+m+(i+1)%m
        edges.update(tuple(sorted(e)) for e in [(a,b),(c,d),(a,c),(a,d)])
        if include_anchor: edges.add((0,a))
    vertices=tuple(range(0 if include_anchor else 1,2*m+1))
    edges=tuple(sorted(edges)); es=set(edges)
    faces=tuple(t for t in itertools.combinations(vertices,3)
                if all(e in es for e in itertools.combinations(t,2)))
    return vertices,edges,faces


def parity(mask, value):
    return (int(mask)&int(value)).bit_count()&1


def mask_of(indices):
    mask=0
    for i in indices:
        if not isinstance(i, (int,np.integer)) or i<0: raise ValueError('bad index')
        mask ^= 1<<int(i)
    return mask


def support(mask):
    return [i for i in range(int(mask).bit_length()) if (mask>>i)&1]


def face_rows(edges,faces):
    idx={e:i for i,e in enumerate(edges)}
    return tuple(mask_of(idx[e] for e in itertools.combinations(t,2)) for t in faces)


def cycle_mask(edges,cycle):
    idx={e:i for i,e in enumerate(edges)}
    return mask_of(idx[tuple(sorted((a,b)))] for a,b in zip(cycle,cycle[1:]+cycle[:1]))


def elimination(rows,rhs=None):
    """Pivot -> (row, rhs, XOR witness in original rows); contradiction witness."""
    if rhs is None: rhs=[0]*len(rows)
    if len(rows)!=len(rhs): raise ValueError('shape mismatch')
    basis={}
    for j,(a,b) in enumerate(zip(rows,rhs)):
        if not isinstance(a,(int,np.integer)) or a<0 or b not in (0,1):
            raise ValueError('invalid GF(2) row')
        a=int(a); b=int(b); w=1<<j
        while a:
            p=a.bit_length()-1
            if p not in basis: basis[p]=(a,b,w); break
            aa,bb,ww=basis[p]; a^=aa; b^=bb; w^=ww
        else:
            if b: return basis,w
    return basis,None


def rank(rows): return len(elimination(rows)[0])


def reduce_target(target,basis):
    a=int(target); y=w=0
    for p in sorted(basis,reverse=True):
        if (a>>p)&1:
            aa,bb,ww=basis[p];a^=aa;y^=bb;w^=ww
    return a,y,w


def particular(basis):
    value=0
    for p in sorted(basis):
        row,rhs,_=basis[p]
        if parity(row,value)!=rhs:value^=1<<p
    return value


def span_masks(rows):
    values=[0]
    for row in rows:values += [v^int(row) for v in values]
    return values


def nullspace(rows,n):
    basis,conflict=elimination(rows)
    if conflict is not None:raise ValueError('inconsistent homogeneous equations')
    ans=[]
    for free in range(n):
        if free in basis:continue
        x=1<<free
        for p in sorted(basis):
            if parity(basis[p][0],x):x^=1<<p
        ans.append(x)
    return ans


class BinaryObservation:
    """An affine admissible set Ax=b, exact scalar queries, one parity target."""
    def __init__(self,n,rows,rhs,target):
        if not isinstance(n,int) or n<1:raise ValueError('invalid variable count')
        rows=tuple(rows)
        if any(not isinstance(r,(int,np.integer)) for r in rows) or not isinstance(target,(int,np.integer)):
            raise ValueError('integer bit masks required')
        self.n=n;self.rows=tuple(int(r) for r in rows);self.rhs=tuple(rhs);self.target=int(target)
        if any(r<0 or r>=1<<n for r in self.rows) or not 0<=self.target<1<<n:
            raise ValueError('row outside variable range')
        self.basis,self.conflict=elimination(self.rows,self.rhs)

    def observe(self,observations):
        """List retains duplicates so conflicting repeated evidence is detected."""
        observations=list(observations)
        for i,y in observations:
            if not isinstance(i,(int,np.integer)) or not 0<=i<self.n or y not in (0,1):
                raise ValueError('invalid observation')
        rows=list(self.rows)+[1<<int(i) for i,y in observations]
        rhs=list(self.rhs)+[int(y) for i,y in observations]
        basis,conflict=elimination(rows,rhs)
        if conflict is not None:return dict(status='conflict',combination=conflict)
        residual,value,witness=reduce_target(self.target,basis)
        if residual==0:return dict(status='known',value=value,combination=witness)
        completions=[]
        for y in (0,1):
            bb,cc=elimination(rows+[self.target],rhs+[y])
            assert cc is None
            completions.append(particular(bb))
        return dict(status='ambiguous',completions=completions)

    def optimal_queries(self,costs,available=None,max_rank=24):
        """Exact coset search, exponential in rank(A); no generic fast claim."""
        costs=tuple(costs)
        if len(costs)!=self.n or any(not isinstance(c,(int,np.integer)) or c<=0 for c in costs):
            raise ValueError('positive integer costs required')
        if self.conflict is not None:return dict(status='conflict')
        if available is None:allowed=(1<<self.n)-1
        else:
            available=tuple(available)
            if any(not isinstance(i,int) or not 0<=i<self.n for i in available):raise ValueError('bad available index')
            allowed=sum(1<<i for i in set(available))
        basis=list(self.basis.values())
        if len(basis)>max_rank:raise ValueError('exact coset search rank guard')
        row=combo=0;constant=0;previous=0;best=None
        for index in range(1<<len(basis)):
            gray=index^(index>>1)
            if index:
                j=(gray^previous).bit_length()-1
                a,b,w=basis[j];row^=a;constant^=b;combo^=w
            previous=gray;mask=self.target^row
            if mask&~allowed:continue
            queries=support(mask);key=(sum(costs[j] for j in queries),len(queries),tuple(queries))
            if best is None or key<best[0]:
                best=(key,dict(status='known_plan',queries=queries,cost=key[0],
                               mask=mask,row_combination=combo,constant=constant))
        if best is None:return dict(status='unobservable',coset_size=1<<len(basis))
        return dict(best[1],coset_size=1<<len(basis))


def sign_bits(edges,negative_sector=False,ring_size=6):
    seam={(1,ring_size),(ring_size+1,2*ring_size),(ring_size,ring_size+1)}
    return mask_of(i for i,e in enumerate(edges) if negative_sector and e in seam)


def switching_mask(vertices,edges,node_bits):
    positions={v:i for i,v in enumerate(vertices)}
    return mask_of(k for k,(a,b) in enumerate(edges)
                   if ((node_bits>>positions[a])^(node_bits>>positions[b]))&1)


def lifted_path(vertices,edges,bits,start,goal):
    """Shortest path between (node,sheet_bit); None means unreachable."""
    if start[0] not in vertices or goal[0] not in vertices or start[1] not in (0,1) or goal[1] not in (0,1):
        raise ValueError('invalid node or sheet; reference anchor is not routable')
    if not 0<=int(bits)<1<<len(edges):raise ValueError('invalid sign vector')
    adj={v:[] for v in vertices}
    for k,(a,b) in enumerate(edges):adj[a].append((b,(bits>>k)&1));adj[b].append((a,(bits>>k)&1))
    todo=deque([start]);parent={start:None}
    while todo:
        x=todo.popleft()
        if x==goal:
            route=[]
            while x is not None:route.append(x);x=parent[x]
            return route[::-1]
        for b,s in adj[x[0]]:
            y=(b,x[1]^s)
            if y not in parent:parent[y]=x;todo.append(y)
    return None


def decode_address(code,operational=False):
    if not isinstance(code,int) or isinstance(code,bool) or not 0<=code<=15:raise ValueError('invalid four-bit word')
    if code>=13:raise ValueError('guard code')
    if operational and code==0:raise ValueError('reference anchor')
    return code


@dataclass
class OrientedGabriel:
    """Same recurrence in d_ij=sigma_ij*c_ij coordinates; invariant trace pooling."""
    original: Gabriel
    sigma: np.ndarray

    def __post_init__(self):
        self.original=deepcopy(self.original);g=self.original
        self.sigma=np.asarray(self.sigma,dtype=float).copy()
        if self.sigma.shape!=g.parents.shape or not np.isin(self.sigma,[-1,1]).all():raise ValueError('invalid transport')
        self.amplitude=g.base*self.sigma
        self.x=g.x.copy();self.d=g.c*self.sigma[None,:,:]

    def step(self,u):
        g=self.original;p=g.config;u=np.asarray(u,float)
        if u.shape!=(p.input_dim,) or not np.isfinite(u).all():raise ValueError('invalid input')
        amplitude=self.amplitude.copy()
        if g.mode=='adaptive':amplitude+=(g.gains*soft_threshold(self.d,g.lam)).sum(0)/p.degree
        old=self.x; transported=self.sigma*old[g.parents]
        new=(1-g.alpha)*old+g.alpha*np.tanh((amplitude*transported).sum(1)+g.U@u+g.bias)
        if g.mode in ('adaptive','trace_only'):
            self.d=(1-g.beta)*self.d+g.beta*(old[:,None]*transported)[None,:,:]
        self.x=new
        return self.x.copy()

    def trace_features(self):return self.d.mean(2).reshape(-1)

    def change_frames(self,signs):
        g=self.original;s=np.asarray(signs,float)
        if s.shape!=self.x.shape or not np.isin(s,[-1,1]).all():raise ValueError('invalid frames')
        result=deepcopy(self)
        result.x=s*self.x;result.sigma=self.sigma*s[:,None]*s[g.parents]
        result.original.U=g.U*s[:,None];result.original.bias=g.bias*s
        # Retain a consistent reference representation as well as active variables.
        result.original.base=result.sigma*result.amplitude
        result.original.x=result.x.copy();result.original.c=result.sigma[None,:,:]*result.d
        return result


def make_profile_core(seed,bits,mode='adaptive'):
    vertices,edges,_=profile_graph();index={v:i for i,v in enumerate(vertices)}
    p=Config(n=12,degree=4,backbone_degree=4)
    g=Gabriel(seed=seed,config=p,mode=mode)
    parents=[sorted(index[b if a==v else a] for a,b in edges if a==v or b==v) for v in vertices]
    g.parents=np.array(parents)
    lookup={e:1-2*((bits>>k)&1) for k,e in enumerate(edges)}
    sigma=np.array([[lookup[tuple(sorted((v,vertices[j])))] for j in g.parents[i]] for i,v in enumerate(vertices)],float)
    g.base=sigma*p.g0/p.degree
    return g,sigma


def double_cover(core,sigma):
    """Explicit 24-cell reference; paired sheets have opposite activity/drive."""
    g=core;p=g.config;n=p.n
    config=Config(n=2*n,degree=p.degree,backbone_degree=p.degree,input_dim=p.input_dim,
                  g0=p.g0,gains=p.gains,betas=p.betas,thresholds=p.thresholds,
                  leaks=p.leaks,input_scale=p.input_scale,bias_scale=p.bias_scale)
    h=Gabriel(0,config,g.mode)
    h.parents=np.vstack([2*g.parents[i]+(s^(sigma[i]<0).astype(int)) for i in range(n) for s in (0,1)])
    h.base=np.repeat(g.base*sigma,2,axis=0)
    h.U=np.repeat(g.U,2,axis=0)*np.tile([1,-1],n)[:,None]
    h.bias=np.repeat(g.bias,2)*np.tile([1,-1],n);h.alpha=np.repeat(g.alpha,2)
    h.x=np.repeat(g.x,2)*np.tile([1,-1],n)
    h.c=np.repeat(g.c*sigma[None,:,:],2,axis=1)
    return h
