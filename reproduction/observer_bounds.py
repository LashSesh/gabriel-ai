"""Bounds for frozen Gabriel trace observers, with interval reverse derivatives.

All statements concern a fixed model on a Cartesian input box. Arithmetic is
float64, not an outward-rounded proof kernel. Plastic feedback is not supported.
The original non-intercept feature order is input, activity, row-mean traces.
"""
import hashlib
import numpy as np
from scalable_observation import pairs, class_verdict


def product_bounds(al, au, bl, bu):
    v=np.array([al*bl,al*bu,au*bl,au*bu])
    return v.min(axis=0),v.max(axis=0)


def affine_bounds(lo,hi,w):
    """Rows are samples and w is input-by-output."""
    pos=np.maximum(w,0.);neg=np.minimum(w,0.)
    return lo@pos+hi@neg,hi@pos+lo@neg


class ObserverBounds:
    def __init__(self,graph,coefficients,steps):
        if graph.mode!='trace_only':raise ValueError('frozen trace observer required')
        if not graph.certificate()['valid']:raise ValueError('uncertified core')
        p=graph.config;self.n=p.n;self.m=p.input_dim;self.steps=int(steps)
        self.parents=graph.parents.copy();self.alpha=graph.alpha.copy()
        self.beta=graph.beta[:,0,0].copy();self.U=graph.U.copy();self.bias=graph.bias.copy()
        self.B=np.zeros((p.n,p.n));self.B[np.arange(p.n)[:,None],self.parents]=graph.base
        self.co=np.asarray(coefficients,float).copy()
        if self.co.ndim!=2 or self.co.shape[1]!=1+p.input_dim+p.n+len(self.beta)*p.n or not np.isfinite(self.co).all():raise ValueError('invalid readout')
        if self.steps<1:raise ValueError('empty window')
        self.K=len(self.co)
        if self.K<2:raise ValueError('at least two classes required')
        self.pp=pairs(self.K)
        self.head=np.array([self.co[a]-self.co[b] for a,b in self.pp]);self.P=len(self.head)
        self.hu=self.head[:,1:1+self.m];self.hx=self.head[:,1+self.m:1+self.m+self.n]
        self.hc=self.head[:,1+self.m+self.n:].reshape(self.P,len(self.beta),self.n)
        self.bp=np.maximum(self.B,0);self.bn=np.minimum(self.B,0)
        self.up=np.maximum(self.U,0);self.un=np.minimum(self.U,0)
        # Unroll the linear traces, then combine opposite orientations of each
        # equal-time product before taking an enclosure or its derivative.
        fade=self.beta[None,:]*(1-self.beta[None,:])**np.arange(self.steps-1,-1,-1)[:,None]
        row=np.einsum('tr,pri->tpi',fade,self.hc)/p.degree
        self.M=np.zeros((self.steps,self.P,self.n,self.n))
        for i in range(self.n):
            for j in self.parents[i]:
                self.M[:,:,i,j]+=row[:,:,i];self.M[:,:,j,i]+=row[:,:,i]
        self.mp=np.maximum(self.M,0);self.mn=np.minimum(self.M,0)
        self.ea,self.eb=np.nonzero(np.triu(np.any(self.M!=0,axis=(0,1)),1))
        self.ec=self.M[:,:,self.ea,self.eb]
        self.ecp=np.maximum(self.ec,0);self.ecn=np.minimum(self.ec,0)
        h=hashlib.sha256()
        for arr in [self.parents,self.alpha,self.beta,self.U,self.bias,self.B,self.co,np.array([self.steps])]:
            h.update(str(arr.shape).encode());h.update(arr.dtype.str.encode());h.update(arr.tobytes())
        self.model_hash=h.hexdigest()

    def validate_box(self,lower,upper):
        lo=np.asarray(lower,float);hi=np.asarray(upper,float)
        if lo.ndim==2:lo=lo[None];hi=hi[None]
        if lo.shape!=hi.shape or lo.ndim!=3 or lo.shape[1:]!=(self.steps,self.m):raise ValueError('input box shape')
        if not np.isfinite(lo).all() or not np.isfinite(hi).all() or np.any(lo>hi):raise ValueError('invalid or empty box')
        if np.any(lo < -1.) or np.any(hi > 1.):raise ValueError('outside normalized input contract')
        return lo,hi

    def point(self,u):
        u=np.asarray(u,float)
        if u.ndim==2:u=u[None]
        self.validate_box(u,u)
        x=np.zeros((len(u),self.n));c=np.zeros((len(u),len(self.beta),self.n,self.parents.shape[1]))
        for t in range(self.steps):
            c=(1-self.beta)[None,:,None,None]*c+self.beta[None,:,None,None]*(x[:,:,None]*x[:,self.parents])[:,None]
            x=(1-self.alpha)*x+self.alpha*np.tanh(x@self.B.T+u[:,t]@self.U.T+self.bias)
        f=np.concatenate([np.ones((len(u),1)),u[:,-1],x,c.mean(-1).reshape(len(u),-1)],axis=1)
        return f@self.co.T

    def analyze(self,lower,upper,derivatives=False):
        lo,hi=self.validate_box(lower,upper);batch=len(lo);mid=(lo+hi)/2;rad=(hi-lo)/2
        xl=np.zeros((self.steps+1,batch,self.n));xu=xl.copy();xm=xl.copy()
        dl=np.empty((self.steps,batch,self.n));du=dl.copy()
        shape=(batch,len(self.beta),self.n,self.parents.shape[1]);cl=np.zeros(shape);cu=cl.copy();cm=cl.copy()
        beta=self.beta[None,:,None,None]
        for t in range(self.steps):
            low=xl[t]@self.bp.T+xu[t]@self.bn.T+lo[:,t]@self.up.T+hi[:,t]@self.un.T+self.bias
            high=xu[t]@self.bp.T+xl[t]@self.bn.T+hi[:,t]@self.up.T+lo[:,t]@self.un.T+self.bias
            nearest=np.maximum(0.,np.maximum(low,-high));furthest=np.maximum(abs(low),abs(high))
            # tanh' = sech^2; nearest is zero when the interval crosses zero.
            du[t]=1-np.tanh(nearest)**2;dl[t]=1-np.tanh(furthest)**2
            pl,pu=product_bounds(xl[t,:, :,None],xu[t,:, :,None],xl[t][:,self.parents],xu[t][:,self.parents])
            cl=(1-beta)*cl+beta*pl[:,None];cu=(1-beta)*cu+beta*pu[:,None]
            cm=(1-beta)*cm+beta*(xm[t,:,:,None]*xm[t][:,self.parents])[:,None]
            xl[t+1]=(1-self.alpha)*xl[t]+self.alpha*np.tanh(low)
            xu[t+1]=(1-self.alpha)*xu[t]+self.alpha*np.tanh(high)
            xm[t+1]=(1-self.alpha)*xm[t]+self.alpha*np.tanh(xm[t]@self.B.T+mid[:,t]@self.U.T+self.bias)
        fl=np.concatenate([np.ones((batch,1)),lo[:,-1],xl[-1],cl.mean(-1).reshape(batch,-1)],axis=1)
        fu=np.concatenate([np.ones((batch,1)),hi[:,-1],xu[-1],cu.mean(-1).reshape(batch,-1)],axis=1)
        fm=np.concatenate([np.ones((batch,1)),mid[:,-1],xm[-1],cm.mean(-1).reshape(batch,-1)],axis=1)
        basic=np.stack(affine_bounds(fl,fu,self.head.T),axis=-1);center=fm@self.head.T
        # Recombine trace channels and reciprocal products before intervalization.
        ql,qu=product_bounds(xl[:-1,:,self.ea],xu[:-1,:,self.ea],xl[:-1,:,self.eb],xu[:-1,:,self.eb])
        # ql/qu shape is (time,batch,edge).
        pl=self.head[:,0]+lo[:,-1]@np.maximum(self.hu,0).T+hi[:,-1]@np.minimum(self.hu,0).T+xl[-1]@np.maximum(self.hx,0).T+xu[-1]@np.minimum(self.hx,0).T
        pu=self.head[:,0]+hi[:,-1]@np.maximum(self.hu,0).T+lo[:,-1]@np.minimum(self.hu,0).T+xu[-1]@np.maximum(self.hx,0).T+xl[-1]@np.minimum(self.hx,0).T
        pl+=np.einsum('tpe,tbe->bp',self.ecp,ql)+np.einsum('tpe,tbe->bp',self.ecn,qu)
        pu+=np.einsum('tpe,tbe->bp',self.ecp,qu)+np.einsum('tpe,tbe->bp',self.ecn,ql)
        compiled=np.stack([pl,pu],axis=-1)
        # Interval reverse mode on the exact trajectory score. The direct term
        # at x_t is M_t*x_t; the recurrent derivative carries future contributions.
        al=np.broadcast_to(self.hx[:,None,:],(self.P,batch,self.n)).copy();au=al.copy()
        gl=np.empty((self.steps,self.P,batch,self.m));gu=gl.copy()
        for t in range(self.steps-1,-1,-1):
            vl,vu=product_bounds(al,au,dl[t][None],du[t][None]);vl*=self.alpha;vu*=self.alpha
            gl[t]=vl@self.up+vu@self.un;gu[t]=vu@self.up+vl@self.un
            if t==self.steps-1:gl[t]+=self.hu[:,None];gu[t]+=self.hu[:,None]
            direct_l=xl[t][None]@self.mp[t].transpose(0,2,1)+xu[t][None]@self.mn[t].transpose(0,2,1)
            direct_u=xu[t][None]@self.mp[t].transpose(0,2,1)+xl[t][None]@self.mn[t].transpose(0,2,1)
            al_new=(1-self.alpha)*al+vl@self.bp+vu@self.bn+direct_l
            au=(1-self.alpha)*au+vu@self.bp+vl@self.bn+direct_u;al=al_new
        gain=np.maximum(abs(gl),abs(gu)).transpose(2,1,0,3)
        contributions=gain*rad[:,None];radius=contributions.sum(axis=(2,3))
        mv=np.stack([center-radius,center+radius],axis=-1)
        structured=np.stack([np.maximum(basic[...,0],compiled[...,0]),np.minimum(basic[...,1],compiled[...,1])],axis=-1)
        hybrid=np.stack([np.maximum(structured[...,0],mv[...,0]),np.minimum(structured[...,1],mv[...,1])],axis=-1)
        # Empty intersections beyond rounding tolerance are errors, not verdicts.
        if np.any(hybrid[...,0]>hybrid[...,1]+1e-9):raise ArithmeticError('inconsistent enclosures')
        answer=dict(bounds=np.stack([basic,structured,hybrid],axis=1),center=center,contributions=contributions,model_hash=self.model_hash)
        if derivatives:answer.update(gradient_lower=gl.transpose(2,1,0,3),gradient_upper=gu.transpose(2,1,0,3),state_lower=xl.transpose(1,0,2),state_upper=xu.transpose(1,0,2),midpoint_state=xm.transpose(1,0,2))
        return answer

    def query(self,analysis,lower,upper):
        """Minimize a frozen derivative upper bound on the next worst width.

        This does not optimize actual future enclosing widths or stopping cost.
        """
        lo,hi=self.validate_box(lower,upper);c=analysis['contributions'].reshape(len(lo),self.P,-1)
        score=np.max(c.sum(-1)[:,:,None]-c,axis=1);score=np.where((hi>lo).reshape(len(lo),-1),score,np.inf)
        out=np.argmin(score,axis=1);return np.where(np.isfinite(score.min(1)),out,-1)

    def verdicts(self,bounds,margin=1e-10):
        bounds=np.asarray(bounds);wins=np.tile(np.eye(self.K,dtype=bool),bounds.shape[:-2]+(1,1))
        for j,(a,b) in enumerate(self.pp):wins[...,a,b]=bounds[...,j,0]>margin;wins[...,b,a]=bounds[...,j,1]<-margin
        yes=wins.all(-1);return np.where(yes.sum(-1)==1,yes.argmax(-1),-1)

    def record(self,lower,upper,calibration_id):
        """Numerical evidence record; containment of actual inputs is assumed.

        The identifier binds an externally declared normalization/time contract.
        It is not evidence that a physical sensor was calibrated.
        """
        if not isinstance(calibration_id,str) or not calibration_id:raise ValueError('calibration identity required')
        lo,hi=self.validate_box(lower,upper)
        if len(lo)!=1:raise ValueError('one record at a time')
        a=self.analyze(lo,hi)
        return dict(schema='gabriel-observer-box-1',arithmetic='float64-not-directed-rounded',model_hash=self.model_hash,calibration_id=calibration_id,initialization='zero',clock='one synchronous update per supplied event',lower=lo[0].tolist(),upper=hi[0].tolist(),bounds=a['bounds'][0,2].tolist(),verdict=int(self.verdicts(a['bounds'])[0,2]),margin=1e-10)

    def verify_record(self,record,calibration_id):
        """Recompute the numerical claim, rejecting stale/tampered metadata."""
        try:
            reference=self.record(record['lower'],record['upper'],calibration_id)
            return record==reference
        except (KeyError,TypeError,ValueError,ArithmeticError):return False
