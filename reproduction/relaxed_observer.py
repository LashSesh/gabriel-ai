"""Affine backward relaxation and ambiguity witnesses for a fixed observer.

Keeps linear input dependencies to the last operation, unlike coordinate IBP.
This is a specialization of established linear-bound propagation. Float64
arithmetic alone is not a sound directed-rounding certificate implementation.
"""
import numpy as np
from observer_bounds import ObserverBounds


def tanh_parallel(lower,upper):
    """tanh(z) in slope*z + [offset-error, offset+error] on [lower,upper].

    Residual extrema occur at endpoints or at sech(z)^2=slope. Any chosen
    slope is admissible if these residual extrema are evaluated. The secant
    is a heuristic slope choice, not a claim of an optimized CROWN relaxation.
    """
    width=upper-lower;mid=(upper+lower)/2
    slope=np.divide(np.tanh(upper)-np.tanh(lower),width,out=1-np.tanh(mid)**2,where=width>1e-10)
    slope=np.clip(slope,0.,1.)
    critical=np.arccosh(1/np.sqrt(np.maximum(slope,np.finfo(float).tiny)))
    points=np.stack([lower,upper,np.clip(critical,lower,upper),np.clip(-critical,lower,upper)])
    residual=np.tanh(points)-slope[None]*points
    low=residual.min(0);high=residual.max(0)
    return slope,(low+high)/2,(high-low)/2


class RelaxedObserver(ObserverBounds):
    def relaxed(self,lower,upper,base=None):
        lo,hi=self.validate_box(lower,upper);batch=len(lo);mid=(lo+hi)/2;rad=(hi-lo)/2
        if base is None:base=self.analyze(lo,hi,True)
        xl=base['state_lower'].transpose(1,0,2);xu=base['state_upper'].transpose(1,0,2)
        cot=np.broadcast_to(self.hx[:,None,:],(self.P,batch,self.n)).copy()
        constant=np.broadcast_to(self.head[:,0,None],(self.P,batch)).copy()
        nonlinear=np.zeros((self.P,batch));quadratic=nonlinear.copy();lin=np.zeros((batch,self.P,self.steps,self.m))
        for t in range(self.steps-1,-1,-1):
            dl=xl[t]@self.bp.T+xu[t]@self.bn.T+lo[:,t]@self.up.T+hi[:,t]@self.un.T+self.bias
            du=xu[t]@self.bp.T+xl[t]@self.bn.T+hi[:,t]@self.up.T+lo[:,t]@self.un.T+self.bias
            slope,offset,error=tanh_parallel(dl,du)
            z=cot*self.alpha;v=z*slope[None]
            lin[:,:,t]=(v@self.U).transpose(1,0,2)
            if t==self.steps-1:lin[:,:,t]+=self.hu
            constant+=(v*self.bias+z*offset[None]).sum(-1)
            nonlinear+=(abs(z)*error[None]).sum(-1)
            xm=(xl[t]+xu[t])/2;xr=(xu[t]-xl[t])/2
            direct=xm[None]@self.M[t].transpose(0,2,1)
            constant-=.5*(direct*xm[None]).sum(-1)
            quadratic+=((xr[:,self.ea]*xr[:,self.eb])@abs(self.ec[t]).T).T
            cot=(1-self.alpha)*cot+v@self.B+direct
        center=constant.T+(lin*mid[:,None]).sum((2,3))
        contributions=abs(lin)*rad[:,None]
        radius=contributions.sum((2,3))+nonlinear.T+quadratic.T
        raw=np.stack([center-radius,center+radius],-1)
        old=base['bounds'][:,2]
        combined=np.stack([np.maximum(old[...,0],raw[...,0]),np.minimum(old[...,1],raw[...,1])],-1)
        if np.any(combined[...,0]>combined[...,1]+1e-8):raise ArithmeticError('inconsistent relaxation')
        return dict(bounds=combined,raw=raw,base=base,linear=lin,linear_contributions=contributions,nonlinear_error=nonlinear.T,quadratic_error=quadratic.T,affine_center=center,model_hash=self.model_hash)

    def decision_query(self,result,lower,upper):
        """Heuristic: largest bounded influence on the least proven rival pair.

        The provisional winner uses the midpoint only to select a query. No
        winner is reported from this point estimate without interval dominance.
        """
        lo,hi=self.validate_box(lower,upper);batch=len(lo);pred=self.point((lo+hi)/2).argmax(1)
        lb=np.full((batch,self.K),np.inf);pair_index=np.zeros((batch,self.K),int)
        for p,(a,b) in enumerate(self.pp):
            ia=pred==a;ib=pred==b;lb[ia,b]=result['bounds'][ia,p,0];lb[ib,a]=-result['bounds'][ib,p,1];pair_index[ia,b]=p;pair_index[ib,a]=p
        rival=lb.argmin(1);p=pair_index[np.arange(batch),rival]
        influence=result['base']['contributions'][np.arange(batch),p].reshape(batch,-1)
        influence=np.where((hi>lo).reshape(batch,-1),influence,-np.inf)
        q=np.argmax(influence,1);return np.where(np.isfinite(influence.max(1)),q,-1)

    def pair_gradient(self,u,pair,sign):
        """Exact point reverse derivative for one selected pair per batch row."""
        u=np.asarray(u,float);batch=len(u);self.validate_box(u,u)
        pair=np.asarray(pair,int);sign=np.asarray(sign,float)
        x=np.zeros((self.steps+1,batch,self.n));sl=np.zeros((self.steps,batch,self.n))
        for t in range(self.steps):
            th=np.tanh(x[t]@self.B.T+u[:,t]@self.U.T+self.bias);sl[t]=1-th*th
            x[t+1]=(1-self.alpha)*x[t]+self.alpha*th
        cot=self.hx[pair]*sign[:,None];grad=np.zeros_like(u)
        for t in range(self.steps-1,-1,-1):
            v=cot*self.alpha*sl[t];grad[:,t]=v@self.U
            if t==self.steps-1:grad[:,t]+=self.hu[pair]*sign[:,None]
            direct=np.einsum('bij,bj->bi',self.M[t,pair],x[t])*sign[:,None]
            cot=(1-self.alpha)*cot+v@self.B+direct
        scores=self.point(u);value=np.array([sign[i]*(scores[i,self.pp[pair[i]][0]]-scores[i,self.pp[pair[i]][1]]) for i in range(batch)])
        return value,grad,scores

    def find_witness(self,lower,upper,seed=260925,iterations=24,restarts=2):
        """Try to exhibit two compatible completions with different winners.

        Failure to find a witness proves nothing. Uses no true missing values
        and no labels; all starts and projected steps remain inside the box.
        """
        lo,hi=self.validate_box(lower,upper);n=len(lo);mid=(lo+hi)/2
        initial=self.point(mid);winner=initial.argmax(1);rivals=np.array([[k for k in range(self.K) if k!=w] for w in winner])
        case=np.repeat(np.arange(n),self.K-1);target=rivals.ravel();ref=winner[case]
        lookup={pq:i for i,pq in enumerate(self.pp)}
        pair=np.array([lookup[tuple(sorted((a,b)))] for a,b in zip(ref,target)]);sign=np.where(ref<target,1.,-1.)
        ll=lo[case];hh=hi[case];rng=np.random.default_rng(seed)
        best_value=np.full(len(case),np.inf);best_input=(ll+hh)/2
        for restart in range(restarts):
            u=(ll+hh)/2 if restart==0 else ll+(hh-ll)*rng.random(ll.shape)
            for step in range(iterations+1):
                value,grad,scores=self.pair_gradient(u,pair,sign)
                better=value<best_value;best_value[better]=value[better];best_input[better]=u[better]
                if step<iterations:
                    rate=.15*(1-step/iterations)+.02
                    u=np.clip(u-rate*(hh-ll)*np.sign(grad),ll,hh)
        best=best_value.reshape(n,self.K-1).argmin(1)+(self.K-1)*np.arange(n)
        u=best_input[best];scores=self.point(u);found=(scores.argmax(1)!=winner)&(best_value[best]<-1e-8)
        assert np.all(u>=lo) and np.all(u<=hi)
        return dict(found=found,first=mid,second=u,first_scores=initial,second_scores=scores,margin=best_value[best],winner=winner)
