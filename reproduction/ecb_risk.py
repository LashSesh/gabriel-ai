"""Causal current-vintage FX risk adapter with one- and two-scale fading state.

Historical simulation and volatility filtering are established methods. This
module uses event-count horizons; it does not infer transactions or price returns
from executable quotes. All forecast arithmetic is binary64, not interval proof.
"""
from pathlib import Path
from fractions import Fraction
import csv, hashlib, json, math
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
PROTOCOL_HASH='04f39c50fb6d7eab9d59bad70548fa23dc15cc964816e37db7cad8baf73bde93'

def load_protocol():
    raw=(ROOT/'results/ecb_risk_protocol.json').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=PROTOCOL_HASH:
        raise ValueError('ECB protocol changed')
    return json.loads(raw)

def load_rates(protocol):
    raw=(ROOT/'data/ecb_eurofxref-hist_20260926.csv').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=protocol['source_csv_sha256']:
        raise ValueError('source data changed')
    records=sorted(csv.DictReader(raw.decode('utf-8').splitlines()),key=lambda r:r['Date'])
    dates=np.array([r['Date'] for r in records],dtype='U10')
    rates=np.array([[float(r[c]) for c in protocol['currencies']] for r in records])
    if len(set(dates))!=len(dates) or np.any(rates<=0) or not np.isfinite(rates).all():
        raise ValueError('duplicate dates, nonpositive rates or missing observations')
    return dates,rates

def fading_variances(rates,initial=60,halflives=(20,120)):
    x=np.asarray(rates,dtype=float)
    if x.ndim!=2 or len(x)<=initial or np.any(x<=0) or not np.isfinite(x).all():
        raise ValueError('positive finite rate matrix required')
    losses=np.full_like(x,np.nan)
    losses[1:]=100*np.log(x[1:]/x[:-1])
    q=np.full((len(x),len(halflives),x.shape[1]),np.nan)
    q[initial]=np.mean(losses[1:initial+1]**2,axis=0)[None,:]
    decay=2.**(-1/np.asarray(halflives,dtype=float))
    for t in range(initial+1,len(x)):
        q[t]=decay[:,None]*q[t-1]+(1-decay[:,None])*losses[t]**2
    return losses,q

def tail(scenarios,alpha='39/40'):
    """Finite uniform distribution, including fractional probability at quantile."""
    x=np.asarray(scenarios,float)
    if x.ndim!=2 or not x.shape[1] or not np.isfinite(x).all():
        raise ValueError('finite scenario rows required')
    a=Fraction(alpha);n=x.shape[1]
    if not 0<=a<1:raise ValueError('invalid confidence')
    k=max(0,math.ceil(a*n)-1)
    quantile=np.partition(x,k,axis=1)[:,k]
    es=quantile+np.maximum(x-quantile[:,None],0).mean(axis=1)/float(1-a)
    return quantile,es

def forecast_candidates(rates,protocol):
    """Return forecasts on every eligible prefix; no future endpoint is needed.

    Keys (currency index,horizon); each matrix columns raw HS then five FHS
    weights. Selection and scoring are deliberately outside this function.
    """
    x=np.asarray(rates,float);_,states=fading_variances(
        x,protocol['variance_initial_observations'],
        protocol['variance_halflives_observed_intervals'])
    wsize=protocol['window'];initial=protocol['variance_initial_observations']
    weights=list(map(lambda z:float(Fraction(z)),protocol['fast_weights']))
    output={}
    for c in range(x.shape[1]):
        for h in protocol['horizons_observed_intervals']:
            first=initial+h+wsize-1
            if len(x)<=first:continue
            ends=np.arange(first,len(x),dtype=int)
            y=np.full(len(x),np.nan);y[h:]=100*np.log(x[h:,c]/x[:-h,c])
            # The first window ends at `first`; every scenario ends <= forecast origin.
            block=np.lib.stride_tricks.sliding_window_view(y,wsize)[ends-wsize+1]
            qs=[];ess=[]
            q,e=tail(block,protocol['alpha']);qs.append(q);ess.append(e)
            for w in weights:
                var=w*states[:,0,c]+(1-w)*states[:,1,c]
                if np.any(var[initial:]<=0):raise ValueError('positive variance required')
                z=np.full(len(x),np.nan)
                z[initial+h:]=y[initial+h:]/np.sqrt(h*var[initial:-h])
                zblock=np.lib.stride_tricks.sliding_window_view(z,wsize)[ends-wsize+1]
                q,e=tail(zblock,protocol['alpha'])
                scale=np.sqrt(h*var[ends]);qs.append(q*scale);ess.append(e*scale)
            output[c,h]=(ends,np.stack(qs,axis=1),np.stack(ess,axis=1))
    return states,output

def fz_score(q,e,y,alpha='39/40'):
    q,e,y=np.broadcast_arrays(np.asarray(q,float),np.asarray(e,float),np.asarray(y,float))
    if not np.isfinite([q,e,y]).all() or np.any(e<=0) or np.any(q>e+1e-12):
        raise ValueError('FZ0 requires finite y,q,e, positive e and q<=e')
    return np.log(e)+(q+np.maximum(y-q,0)/float(1-Fraction(alpha)))/e-1

def metrics(q,e,y,alpha='39/40'):
    score=fz_score(q,e,y,alpha)
    hit=y>q
    residual=q+np.maximum(y-q,0)/float(1-Fraction(alpha))-e
    return dict(n=len(y),mean_fz0=float(score.mean()),exceedances=int(hit.sum()),
                exceedance_fraction=float(hit.mean()),
                mean_es_identification_residual=float(residual.mean()),
                mean_var=float(q.mean()),mean_es=float(e.mean()))
