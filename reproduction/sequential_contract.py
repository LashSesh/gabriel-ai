"""Exact certificate renewal and immutable bitemporal model contracts.

These are conditional finite-model contracts. Receipt fields are declared
metadata, not authenticated publication times. In a historical replay without
vintages, the availability mode must state that receipt times are assumptions.
Certificate binding is distinct from verification of the certificate's content.

The risk bound uses established CVaR monotonicity/cash translation and total
variation sensitivity. The renewal inequalities concern fixed action meanings,
common score units and a verified bound on every new score. They do not make a
static risk objective dynamically consistent or execute an action.
"""
from dataclasses import dataclass, asdict
from fractions import Fraction as F
from functools import cached_property
import hashlib
import json

from decision_regions import exact_rational


def _plain(value):
    if type(value) is F:
        return str(value)
    if value is None or type(value) in (str,int,bool):
        return value
    if type(value) in (tuple,list):
        return [_plain(v) for v in value]
    if type(value) is dict and all(type(k) is str for k in value):
        return {k:_plain(v) for k,v in value.items()}
    raise ValueError('canonical payload requires exact JSON values; floats are rejected')


def canonical(value):
    return json.dumps(_plain(value),sort_keys=True,separators=(',',':'),allow_nan=False)


def identity(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def _text(value,name):
    if type(value) is not str or not value:
        raise ValueError(name+' must be a nonempty string')
    return value


def _clock(value,name):
    if type(value) is not int:
        raise ValueError(name+' must be an integer on the declared common clock')
    return value


@dataclass(frozen=True)
class EventRevision:
    source_id: str
    record_id: str
    revision: int
    event_start: int
    event_end: int
    received_at: int
    vintage_id: str
    payload_json: str

    def __post_init__(self):
        for key in ('source_id','record_id','vintage_id'):
            _text(getattr(self,key),key)
        for key in ('revision','event_start','event_end','received_at'):
            _clock(getattr(self,key),key)
        if self.revision<0 or not self.event_start<=self.event_end<=self.received_at:
            raise ValueError('revision and completed-event/receipt ordering are invalid')
        try:
            payload=json.loads(self.payload_json)
        except (TypeError,json.JSONDecodeError) as exc:
            raise ValueError('invalid canonical payload') from exc
        if canonical(payload)!=self.payload_json:
            raise ValueError('payload is not canonical exact JSON')

    @classmethod
    def create(cls,source_id,record_id,revision,event_interval,received_at,vintage_id,payload):
        start,end=event_interval
        return cls(source_id,record_id,revision,start,end,received_at,vintage_id,canonical(payload))


@dataclass(frozen=True)
class Snapshot:
    event_cutoff: int
    receipt_cutoff: int
    revisions: tuple
    availability_mode: str

    def __post_init__(self):
        _clock(self.event_cutoff,'event_cutoff');_clock(self.receipt_cutoff,'receipt_cutoff')
        if self.availability_mode not in ('declared_observed_receipts','historical_replay_without_vintages'):
            raise ValueError('unknown availability mode')
        object.__setattr__(self,'revisions',tuple(self.revisions))
        keys=[]
        for record in self.revisions:
            if not isinstance(record,EventRevision):raise ValueError('EventRevision required')
            if record.event_end>self.event_cutoff or record.received_at>self.receipt_cutoff:
                raise ValueError('snapshot contains unavailable evidence')
            keys.append((record.source_id,record.record_id))
        if len(keys)!=len(set(keys)) or keys!=sorted(keys):
            raise ValueError('snapshot needs one sorted revision per source record')

    @cached_property
    def identity(self):
        return identity(asdict(self))


class BitemporalLedger:
    """Append receipt-ordered revisions; preserve every previous revision.

    Events may arrive out of event order. Revision numbers for one source record
    start at zero and increase by one; receipt backdating and event-id reuse for
    a different interval are rejected. No old snapshot object is mutated.
    """
    def __init__(self,availability_mode='declared_observed_receipts'):
        if availability_mode not in ('declared_observed_receipts','historical_replay_without_vintages'):
            raise ValueError('unknown availability mode')
        self.availability_mode=availability_mode
        self._revisions=[]
        self._latest={}

    @property
    def revisions(self):
        return tuple(self._revisions)

    def append(self,record):
        if not isinstance(record,EventRevision):raise ValueError('EventRevision required')
        key=(record.source_id,record.record_id)
        previous=self._latest.get(key)
        if previous==record:return False
        if self._revisions and record.received_at<self._revisions[-1].received_at:
            raise ValueError('cannot append a backdated receipt')
        if previous is None:
            if record.revision!=0:raise ValueError('first revision must be zero')
        elif (record.revision!=previous.revision+1 or
              (record.event_start,record.event_end)!=(previous.event_start,previous.event_end)):
            raise ValueError('revision lineage or event interval mismatch')
        self._revisions.append(record);self._latest[key]=record
        return True

    def snapshot(self,event_cutoff,receipt_cutoff):
        _clock(event_cutoff,'event_cutoff');_clock(receipt_cutoff,'receipt_cutoff')
        selected={}
        for record in self._revisions:
            if record.event_end<=event_cutoff and record.received_at<=receipt_cutoff:
                selected[(record.source_id,record.record_id)]=record
        return Snapshot(event_cutoff,receipt_cutoff,tuple(selected[k] for k in sorted(selected)),
                        self.availability_mode)


@dataclass(frozen=True)
class ModelContract:
    model_digest: str
    snapshot_digest: str
    data_vintage_id: str
    target_id: str
    event_cutoff: int
    receipt_cutoff: int
    availability_mode: str

    def __post_init__(self):
        for key in ('model_digest','snapshot_digest','data_vintage_id','target_id'):
            _text(getattr(self,key),key)
        _clock(self.event_cutoff,'event_cutoff');_clock(self.receipt_cutoff,'receipt_cutoff')
        if self.availability_mode not in ('declared_observed_receipts','historical_replay_without_vintages'):
            raise ValueError('unknown availability mode')

    @classmethod
    def from_snapshot(cls,model_digest,snapshot,data_vintage_id,target_id):
        if not isinstance(snapshot,Snapshot):raise ValueError('Snapshot required')
        return cls(model_digest,snapshot.identity,data_vintage_id,target_id,
                   snapshot.event_cutoff,snapshot.receipt_cutoff,snapshot.availability_mode)

    @cached_property
    def identity(self):
        return identity(asdict(self))


@dataclass(frozen=True)
class BoundCertificate:
    """Immutable binding wrapper, not a substitute for a content verifier."""
    contract_digest: str
    action: int
    evidence_json: str
    parent_certificate: str = ''

    def __post_init__(self):
        _text(self.contract_digest,'contract_digest')
        if type(self.action) is not int or self.action<0:raise ValueError('nonnegative action index required')
        try:payload=json.loads(self.evidence_json)
        except (TypeError,json.JSONDecodeError) as exc:raise ValueError('invalid evidence JSON') from exc
        if canonical(payload)!=self.evidence_json:raise ValueError('noncanonical evidence JSON')
        if type(self.parent_certificate) is not str:raise ValueError('parent identity must be a string')

    @classmethod
    def bind(cls,contract,action,evidence):
        return cls(contract.identity,action,canonical(evidence))

    @cached_property
    def identity(self):
        return identity(asdict(self))


def verify_binding(certificate,contract):
    if not isinstance(certificate,BoundCertificate) or not isinstance(contract,ModelContract):
        raise ValueError('typed certificate and contract required')
    if certificate.contract_digest!=contract.identity:
        raise ValueError('certificate belongs to another model, snapshot, vintage or target')
    return True


def _probabilities(values):
    ps=tuple(exact_rational(p) for p in values)
    if not ps or any(p<0 for p in ps) or sum(ps)!=1:
        raise ValueError('nonempty probability vector must be nonnegative and sum to one')
    return ps


def total_variation(p,q):
    p,q=_probabilities(p),_probabilities(q)
    if len(p)!=len(q):raise ValueError('probability supports must be aligned')
    return sum((abs(x-y) for x,y in zip(p,q)),F(0))/2


def cvar_revision_bound(old_losses,new_losses,old_models,new_models,alpha):
    """Exact finite-support bound using matched vertices of two model hulls.

    Vertex pairing supplies an upper bound on Hausdorff TV, not necessarily its
    smallest value. Loss indices, scenario meanings and action units must be
    aligned by the caller, e.g. on a union support with zero mass where absent.
    All model families must have the same positive vertex count.
    """
    xs=tuple(exact_rational(x) for x in old_losses)
    ys=tuple(exact_rational(y) for y in new_losses)
    a=exact_rational(alpha)
    if not xs or len(xs)!=len(ys) or not 0<=a<1:raise ValueError('invalid loss support or alpha')
    ps=tuple(_probabilities(p) for p in old_models)
    qs=tuple(_probabilities(q) for q in new_models)
    if not ps or len(ps)!=len(qs) or any(len(p)!=len(xs) for p in ps+qs):
        raise ValueError('aligned nonempty model families are required')
    distances=tuple(total_variation(p,q) for p,q in zip(ps,qs))
    tv=max(distances)
    loss_change=max(abs(x-y) for x,y in zip(xs,ys))
    loss_range=max(xs)-min(xs)
    distribution_change=loss_range*min(F(1),tv/(1-a))
    return dict(schema='gabriel.cvar-revision-bound.v1',old_losses=xs,new_losses=ys,
                old_models=ps,new_models=qs,alpha=a,matched_vertex_tv=distances,
                hausdorff_tv_upper=tv,loss_sup_change=loss_change,old_loss_range=loss_range,
                distribution_change_upper=distribution_change,
                delta=loss_change+distribution_change,
                scope='aligned common finite support; model hulls paired by vertex')


def verify_cvar_revision_bound(certificate):
    try:
        computed=cvar_revision_bound(certificate['old_losses'],certificate['new_losses'],
                                    certificate['old_models'],certificate['new_models'],certificate['alpha'])
    except (KeyError,TypeError) as exc:raise ValueError('malformed CVaR revision certificate') from exc
    if canonical(computed)!=canonical(certificate):raise ValueError('invalid CVaR revision bound')
    return True


def renewal_certificate(old_scores,old_operational,new_operational,action,delta,
                        old_limit,new_limit,old_epsilon,new_epsilon,
                        old_contract_digest,new_contract_digest,change='symmetric'):
    """Conservatively renew one acceptable action under verified score changes.

    'symmetric': |J'-J|<=delta; 'increase': 0<=J'-J<=delta;
    'decrease': -delta<=J'-J<=0, all actionwise on the same finite action list.
    A conservative possible-new-feasible set must be contained in the old set.
    The action needs a true new operational flag and a safe new score upper bound.
    Failure means recompute, not that the old or new action is incorrect.
    """
    scores=tuple(exact_rational(x) for x in old_scores)
    old_flags,new_flags=tuple(old_operational),tuple(new_operational)
    d,k0,k1,e0,e1=map(exact_rational,(delta,old_limit,new_limit,old_epsilon,new_epsilon))
    if (not scores or len(old_flags)!=len(scores) or len(new_flags)!=len(scores) or
        any(type(x) is not bool for x in old_flags+new_flags) or
        type(action) is not int or not 0<=action<len(scores) or min(d,e0,e1)<0):
        raise ValueError('invalid action, flags, tolerance or bound')
    _text(old_contract_digest,'old_contract_digest');_text(new_contract_digest,'new_contract_digest')
    if old_contract_digest==new_contract_digest:raise ValueError('renewal requires a new contract identity')
    if change not in ('symmetric','increase','decrease'):raise ValueError('unknown change bound')
    lower=F(0) if change=='increase' else -d
    upper=F(0) if change=='decrease' else d
    old_feasible=tuple(i for i,s in enumerate(scores) if old_flags[i] and s<=k0)
    if action not in old_feasible:raise ValueError('old action was not feasible')
    regret=scores[action]-min(scores[i] for i in old_feasible)
    if regret>e0:raise ValueError('old action was not acceptable')
    potential=tuple(i for i,s in enumerate(scores) if new_flags[i] and s+lower<=k1)
    subset=set(potential)<=set(old_feasible)
    regret_upper=regret+(2*d if change=='symmetric' else d)
    score_upper=scores[action]+upper
    checks=dict(retained_action_operational=new_flags[action],
                possible_new_feasible_subset_old=subset,
                absolute_bound=score_upper<=k1,relative_bound=regret_upper<=e1)
    return dict(schema='gabriel.action-renewal.v1',old_scores=scores,
                old_operational=old_flags,new_operational=new_flags,action=action,delta=d,
                old_limit=k0,new_limit=k1,old_epsilon=e0,new_epsilon=e1,change=change,
                old_contract_digest=old_contract_digest,new_contract_digest=new_contract_digest,
                old_feasible=old_feasible,possible_new_feasible=potential,
                old_regret=regret,new_regret_upper=regret_upper,new_score_upper=score_upper,
                checks=checks,status='renewed' if all(checks.values()) else 'recompute',
                assumption='the declared score-change bound holds actionwise in the named contracts')


def verify_renewal_certificate(certificate):
    fields=('old_scores','old_operational','new_operational','action','delta','old_limit','new_limit',
            'old_epsilon','new_epsilon','old_contract_digest','new_contract_digest','change')
    try:computed=renewal_certificate(**{key:certificate[key] for key in fields})
    except (KeyError,TypeError) as exc:raise ValueError('malformed action renewal certificate') from exc
    if canonical(computed)!=canonical(certificate):raise ValueError('invalid action renewal certificate')
    return True


def renew_bound_certificate(previous,old_contract,new_contract,renewal):
    """Create a new immutable binding; never rewrite the previous certificate.

    This checks the renewal inequalities and bindings, not the empirical truth
    of the delta bound or the original decision evidence. Those need their own
    validators (e.g. cvar_revision_bound and the finite decision verifier).
    """
    verify_binding(previous,old_contract);verify_renewal_certificate(renewal)
    if (renewal['status']!='renewed' or renewal['action']!=previous.action or
        renewal['old_contract_digest']!=old_contract.identity or
        renewal['new_contract_digest']!=new_contract.identity):
        raise ValueError('renewal does not justify this action and these contracts')
    if old_contract.target_id!=new_contract.target_id:
        raise ValueError('target/action meanings changed; fresh derivation required')
    if (new_contract.event_cutoff<old_contract.event_cutoff or
        new_contract.receipt_cutoff<old_contract.receipt_cutoff):
        raise ValueError('cannot renew a later certificate into an earlier as-of contract')
    return BoundCertificate(new_contract.identity,previous.action,canonical(renewal),previous.identity)
