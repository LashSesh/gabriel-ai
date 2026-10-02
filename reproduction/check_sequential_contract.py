"""Execute exact renewal, revision-order and risk-sensitivity checks.

No historical publication timestamps are inferred from an event date. The ledger
examples are constructed events. Risk tests use exact finite probability models.
"""
from dataclasses import FrozenInstanceError, replace
from fractions import Fraction as F
from itertools import product
from pathlib import Path
import hashlib
import json
import random

from portfolio_risk import robust_cvar,cvar
from sequential_contract import (EventRevision,BitemporalLedger,ModelContract,BoundCertificate,
                                verify_binding,renew_bound_certificate,renewal_certificate,
                                verify_renewal_certificate,cvar_revision_bound,
                                verify_cvar_revision_bound,total_variation,canonical)

ROOT=Path(__file__).resolve().parents[1]


def reject(function,errors=(ValueError,)):
    try:function()
    except errors:return
    raise AssertionError('invalid record, bound or binding was accepted')


def acceptable(scores,flags,action,limit,epsilon):
    feasible=[i for i,j in enumerate(scores) if flags[i] and j<=limit]
    return action in feasible and scores[action]-min(scores[i] for i in feasible)<=epsilon


def main():
    counts=dict(renewal_contracts=0,renewed_contracts=0,exact_new_score_checks=0,
                risk_bound_cases=0,sharp_distribution_cases=0,tamper_rejections=0,
                event_contract_rejections=0)
    # Enumerate independently realizable score updates; a passed certificate
    # must remain correct for every enumerated realization allowed by its bound.
    for old in product((-1,0,1),repeat=2):
      for delta,change,limit,flags,action,epsilon in product((0,1),('symmetric','increase','decrease'),
                (0,2),product((False,True),repeat=2),range(2),(0,1,2)):
        if not acceptable(old,(True,True),action,limit,1):continue
        proof=renewal_certificate(old,(True,True),flags,action,delta,limit,limit,1,epsilon,
                                  'old','new',change)
        assert verify_renewal_certificate(proof)
        counts['renewal_contracts']+=1
        if proof['status']!='renewed':continue
        counts['renewed_contracts']+=1
        changes={'symmetric':(-delta,0,delta),'increase':(0,delta),'decrease':(-delta,0)}[change]
        for increments in product(set(changes),repeat=2):
            new=tuple(F(j+d) for j,d in zip(old,increments))
            assert acceptable(new,flags,action,limit,epsilon)
            counts['exact_new_score_checks']+=1

    # The coefficient 2 cannot be replaced by 1 for arbitrary two-sided changes.
    symmetric=renewal_certificate((0,0),(True,True),(True,True),0,1,10,10,0,1,'old','new')
    assert symmetric['status']=='recompute' and symmetric['new_regret_upper']==2
    assert not acceptable((1,-1),(True,True),0,10,1)
    sufficient=renewal_certificate((0,0),(True,True),(True,True),0,1,10,10,0,2,'old','new')
    assert sufficient['status']=='renewed'
    monotone=renewal_certificate((0,0),(True,True),(True,True),0,1,10,10,0,1,'old','new','increase')
    assert monotone['status']=='renewed' and acceptable((1,0),(True,True),0,10,1)
    # A newly feasible competitor defeats renewal even with delta=0.
    expansion=renewal_certificate((0,-10),(True,False),(True,True),0,0,20,20,0,0,'old','new')
    assert expansion['status']=='recompute'
    assert not expansion['checks']['possible_new_feasible_subset_old']
    lost_flag=renewal_certificate((0,0),(True,True),(False,True),0,0,10,10,0,0,'old','new')
    assert lost_flag['status']=='recompute' and not lost_flag['checks']['retained_action_operational']

    rng=random.Random(20260926)
    for _ in range(180):
        n=rng.randrange(1,6);m=rng.randrange(1,4)
        old=tuple(F(rng.randrange(-10,11),rng.randrange(1,4)) for _ in range(n))
        new=tuple(x+F(rng.randrange(-2,3),2) for x in old)
        families=[]
        for family in range(2):
            rows=[]
            for _ in range(m):
                weights=[rng.randrange(5) for _ in range(n)]
                if not sum(weights):weights[0]=1
                rows.append(tuple(F(w,sum(weights)) for w in weights))
            families.append(tuple(rows))
        alpha=rng.choice((F(0),F(1,2),F(3,4),F(9,10)))
        bound=cvar_revision_bound(old,new,*families,alpha)
        assert verify_cvar_revision_bound(bound)
        difference=abs(robust_cvar(old,families[0],alpha)['value']-
                       robust_cvar(new,families[1],alpha)['value'])
        assert difference<=bound['delta']
        counts['risk_bound_cases']+=1
    for alpha,epsilon in product((F(0),F(1,2),F(9,10)),(F(0),F(1,20),F(1,5),F(1))):
        p=(1,0);q=(1-epsilon,epsilon)
        bound=cvar_revision_bound((0,7),(0,7),(p,),(q,),alpha)
        difference=cvar((0,7),q,alpha)-cvar((0,7),p,alpha)
        assert difference==bound['delta']==7*min(F(1),epsilon/(1-alpha))
        counts['sharp_distribution_cases']+=1
    # Expanding the risk model can reverse relative optimality despite each
    # individual robust score being nondecreasing.
    old_models=((1,0),);new_models=((1,0),(0,1))
    before=tuple(robust_cvar(x,old_models,0)['value'] for x in ((0,3),(1,1)))
    after=tuple(robust_cvar(x,new_models,0)['value'] for x in ((0,3),(1,1)))
    assert before==(0,1) and after==(3,1)
    assert acceptable(before,(True,True),0,4,0) and not acceptable(after,(True,True),0,4,0)
    # Static and nested CVaR are different objectives on the same small tree.
    static=(cvar((0,4,0,0),(F(1,4),)*4,F(1,2)),cvar((3,3,0,0),(F(1,4),)*4,F(1,2)))
    nested=(cvar((4,0),(F(1,2),)*2,F(1,2)),cvar((3,0),(F(1,2),)*2,F(1,2)))
    assert static==(2,3) and nested==(4,3)

    ledger=BitemporalLedger()
    newer=EventRevision.create('source','new-event',0,(3,3),4,'v1',{'value':'7/2'})
    older=EventRevision.create('source','old-event',0,(1,1),5,'v1',{'value':2})
    assert ledger.append(newer) and ledger.append(older) # event ordering differs from receipts
    snapshot_old=ledger.snapshot(3,5)
    old_identity=snapshot_old.identity
    assert len(snapshot_old.revisions)==2
    correction=EventRevision.create('source','old-event',1,(1,1),8,'v2',{'value':9})
    assert ledger.append(correction) and not ledger.append(correction)
    assert snapshot_old.identity==old_identity
    assert ledger.snapshot(3,5).identity==old_identity
    snapshot_new=ledger.snapshot(3,8)
    assert snapshot_new.identity!=old_identity and snapshot_new.revisions[1].payload_json=='{"value":9}'
    assert len(ledger.snapshot(2,8).revisions)==1
    assert not ledger.snapshot(3,3).revisions
    old_contract=ModelContract.from_snapshot('model-1',snapshot_old,'v1','same-action-target')
    new_contract=ModelContract.from_snapshot('model-2',snapshot_new,'v2','same-action-target')
    old_certificate=BoundCertificate.bind(old_contract,0,{'score':'0','risk_limit':'10'})
    old_certificate_identity=old_certificate.identity
    assert verify_binding(old_certificate,old_contract)
    reject(lambda:verify_binding(old_certificate,new_contract));counts['event_contract_rejections']+=1
    for changed in (replace(old_contract,data_vintage_id='v2'),replace(old_contract,model_digest='foreign'),
                    replace(old_contract,target_id='another-horizon')):
        reject(lambda c=changed:verify_binding(old_certificate,c));counts['event_contract_rejections']+=1
    proof=renewal_certificate((0,0),(True,True),(True,True),0,1,10,10,0,2,
                              old_contract.identity,new_contract.identity)
    renewed=renew_bound_certificate(old_certificate,old_contract,new_contract,proof)
    assert renewed.identity!=old_certificate_identity and renewed.parent_certificate==old_certificate_identity
    assert verify_binding(renewed,new_contract) and old_certificate.identity==old_certificate_identity
    earlier=replace(new_contract,receipt_cutoff=4)
    backward_proof=renewal_certificate((0,0),(True,True),(True,True),0,1,10,10,0,2,
                                       old_contract.identity,earlier.identity)
    reject(lambda:renew_bound_certificate(old_certificate,old_contract,earlier,backward_proof))
    counts['event_contract_rejections']+=1
    reject(lambda:verify_binding(renewed,old_contract));counts['event_contract_rejections']+=1
    reject(lambda:setattr(old_certificate,'contract_digest',new_contract.identity),(FrozenInstanceError,))
    counts['event_contract_rejections']+=1
    replay=BitemporalLedger('historical_replay_without_vintages');replay.append(newer)
    replay_contract=ModelContract.from_snapshot('model-1',replay.snapshot(3,4),'v1','same-action-target')
    assert replay_contract.availability_mode=='historical_replay_without_vintages'
    for function in (lambda:ledger.append(EventRevision.create('source','x',0,(1,1),6,'v1',{})),
                     lambda:ledger.append(EventRevision.create('source','old-event',3,(1,1),9,'v3',{})),
                     lambda:ledger.append(EventRevision.create('source','old-event',2,(2,2),9,'v3',{})),
                     lambda:EventRevision.create('s','future',0,(10,10),9,'v',{}),
                     lambda:EventRevision.create('s','float',0,(1,1),2,'v',{'x':0.1})):
        reject(function);counts['event_contract_rejections']+=1

    for field,value in (('delta',proof['delta']+1),('status','recompute'),('action',1),
                        ('new_contract_digest','foreign'),('new_regret_upper',F(0))):
        changed=dict(proof);changed[field]=value
        # Changed identities require the outer binding check; the inequality
        # checker alone intentionally accepts arbitrary nonempty named models.
        function=(lambda c=changed:renew_bound_certificate(old_certificate,old_contract,new_contract,c))
        reject(function);counts['tamper_rejections']+=1
    changed=dict(bound);changed['delta']+=1
    reject(lambda:verify_cvar_revision_bound(changed));counts['tamper_rejections']+=1
    for function in (lambda:total_variation((1,),(F(1,2),F(1,2))),
                     lambda:cvar_revision_bound((0,1),(0,1),((1,0),),((1,0),),1),
                     lambda:renewal_certificate((0,),(True,),(True,),0,0,1,1,0,0,'same','same')):
        reject(function);counts['tamper_rejections']+=1
    output=dict(status='pass',counts=counts,random_seed=20260926,
                scope='exact finite-model sensitivity/renewal; constructed bitemporal records',
                symmetric_sharpness=dict(old_scores=(0,0),new_scores=(1,-1),delta=1,new_regret=2),
                monotone_sharpness=dict(old_scores=(0,0),new_scores=(1,0),delta=1,new_regret=1),
                model_expansion=dict(old_scores=before,new_scores=after),
                static_versus_nested=dict(static=static,nested=nested),
                late_revision=dict(old_snapshot=old_identity,new_snapshot=snapshot_new.identity,
                                   old_certificate=old_certificate_identity,new_certificate=renewed.identity),
                limitations=['Score-change bounds are post-revision certificates unless bounded future changes are separately assumed.',
                             'Receipt and source fields do not authenticate publication times.',
                             'A failed renewal gate means recompute, not reject the action.',
                             'A binding wrapper does not verify original decision evidence or economic model adequacy.'],
                source_sha256={name:hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest()
                               for name in ('sequential_contract.py','check_sequential_contract.py')})
    (ROOT/'results'/'sequential_contract_checks.json').write_text(json.dumps(json.loads(canonical(output)),indent=2)+'\n')
    print(json.dumps(json.loads(canonical(output)),indent=2))


if __name__=='__main__':main()
