"""Verify real-input forecast integration with immutable model snapshots."""
from copy import deepcopy
from pathlib import Path
from decimal import Decimal
import hashlib
import json

import numpy as np

from ecb_risk import load_protocol
from forecast_ecb_snapshot import (DEFAULT_DATE,source_rows,build_snapshot,verify_snapshot,binary64)
from sequential_contract import canonical,identity

ROOT=Path(__file__).resolve().parents[1]


def reject(function):
    try:function()
    except ValueError:return
    raise AssertionError('altered or unavailable snapshot accepted')


def main():
    protocol=load_protocol();rows,digest=source_rows(protocol)
    result=build_snapshot(protocol,rows,DEFAULT_DATE,digest)
    assert verify_snapshot(result,protocol=protocol,rows=rows,source_vintage_digest=digest)
    counts=dict(contracts=len(result['forecasts']),archived_forecast_values=0,archived_state_values=0,
                altered_document_rejections=0,prefix_causality_comparisons=0,invalid_origin_rejections=0)
    column=1+protocol['fast_weights'].index('1/2')
    with np.load(ROOT/'results/ecb_risk_predictions.npz',allow_pickle=False) as archive:
        t=int(np.flatnonzero(archive['dates']==DEFAULT_DATE)[0])
        for record in result['forecasts']:
            currency=record['currency'];h=record['horizon_observed_intervals'];stem=f'{currency}_{h}'
            j=int(np.flatnonzero(archive[stem+'_origins']==t)[0])
            assert record['var']==binary64(archive[stem+'_candidate_var'][j,column])
            assert record['es']==binary64(archive[stem+'_candidate_es'][j,column])
            counts['archived_forecast_values']+=2
            c=protocol['currencies'].index(currency)
            assert record['variance_fast']==binary64(archive['variances'][t,0,c])
            assert record['variance_slow']==binary64(archive['variances'][t,1,c])
            counts['archived_state_values']+=2
    assert len({r['contract_digest'] for r in result['forecasts']})==8
    assert len({r['contract']['snapshot_digest'] for r in result['forecasts']})==1
    assert all(r['contract']['availability_mode']=='historical_replay_without_vintages' for r in result['forecasts'])
    # The declared vintage is deliberately held fixed in these counterfactual
    # low-level tests to isolate dependence on inaccessible suffix VALUES.
    changed_rows=deepcopy(rows)
    for row in changed_rows:
        if row['Date']>DEFAULT_DATE:
            for currency in protocol['currencies']:
                row[currency]=str(Decimal(row[currency])*Decimal('1.731'))
    changed=build_snapshot(protocol,changed_rows,DEFAULT_DATE,digest)
    assert canonical(changed)==canonical(result);counts['prefix_causality_comparisons']+=1
    prefix=tuple(row for row in rows if row['Date']<=DEFAULT_DATE)
    truncated=build_snapshot(protocol,prefix,DEFAULT_DATE,digest)
    assert canonical(truncated)==canonical(result);counts['prefix_causality_comparisons']+=1
    # An actual source-vintage change intentionally changes the binding even if
    # prefix prices and consequently numerical forecasts are identical.
    other=build_snapshot(protocol,rows,DEFAULT_DATE,'0'*64)
    assert other['snapshot_digest']!=result['snapshot_digest']
    assert all(x['var']==y['var'] and x['es']==y['es'] for x,y in zip(other['forecasts'],result['forecasts']))
    mutations=[]
    changed=deepcopy(result);changed['forecasts'][0]['horizon_observed_intervals']=5;mutations.append(changed)
    changed=deepcopy(result);changed['forecasts'][0]['target_id']='foreign-target';mutations.append(changed)
    changed=deepcopy(result);changed['forecasts'][0]['contract']['receipt_cutoff']+=1;mutations.append(changed)
    changed=deepcopy(result);changed['forecasts'][0]['contract']['event_cutoff']+=1;mutations.append(changed)
    changed=deepcopy(result);changed['forecasts'][0]['contract']['data_vintage_id']='foreign-vintage';mutations.append(changed)
    changed=deepcopy(result);changed['forecasts'][0]['var']['decimal']='123.0';mutations.append(changed)
    changed=deepcopy(result);changed['forecasts'][0]['es']['binary64_hex']='0x1.0p+0';mutations.append(changed)
    changed=deepcopy(result);changed['forecasts'][0]['contract_digest']='forged';mutations.append(changed)
    for changed in mutations:
        # Rehashing altered content must not evade fresh computation/binding.
        changed['document_digest']=identity({k:v for k,v in changed.items() if k!='document_digest'})
        reject(lambda doc=changed:verify_snapshot(doc,protocol=protocol,rows=rows,source_vintage_digest=digest))
        counts['altered_document_rejections']+=1
    for invalid in ('2025-12-27','1999-01-05','not-a-date'):
        reject(lambda day=invalid:build_snapshot(protocol,rows,day,digest))
        counts['invalid_origin_rejections']+=1
    saved=ROOT/'results/ecb_snapshot.json'
    if saved.exists():
        assert canonical(json.loads(saved.read_text()))==canonical(result)
    else:
        saved.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    output=dict(status='pass',origin=DEFAULT_DATE,counts=counts,
                prefix_record_count=result['prefix_record_count'],snapshot_digest=result['snapshot_digest'],
                source_vintage_digest=digest,forecast_arithmetic='binary64; exact replay equality, no rounding proof',
                receipt_assumption=result['receipt_convention'],
                causality_test='post-origin values perturbed and suffix removed with declared vintage held fixed solely for isolation',
                source_sha256={name:hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest()
                               for name in ('forecast_ecb_snapshot.py','check_ecb_snapshot.py')})
    (ROOT/'results/ecb_snapshot_checks.json').write_text(json.dumps(output,indent=2)+'\n')
    print(json.dumps(output,indent=2))


if __name__=='__main__':main()
