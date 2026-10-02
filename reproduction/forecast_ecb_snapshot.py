"""Bind eight fixed multiscale ECB risk forecasts to an immutable as-of snapshot.

Example from the project root:
    python reproduction/forecast_ecb_snapshot.py --date 2025-12-23

The original CSV is a downloaded, potentially revised vintage. Daily event and
receipt ordinals are replay assumptions, not authenticated release timestamps.
Forecasts use binary64 arithmetic; model-contract binding is not an arithmetic
certificate, an action recommendation or a trading simulation.
"""
from dataclasses import asdict
from datetime import date
from decimal import Decimal,InvalidOperation
from pathlib import Path
import argparse
import csv
import hashlib
import json
import math

import numpy as np

from ecb_risk import load_protocol,forecast_candidates
from sequential_contract import BitemporalLedger,EventRevision,ModelContract,canonical,identity

ROOT=Path(__file__).resolve().parents[1]
DEFAULT_DATE='2025-12-23'


def source_rows(protocol):
    """Read and check the supplied file against its fixed protocol hash."""
    raw=(ROOT/'data/ecb_eurofxref-hist_20260926.csv').read_bytes()
    digest=hashlib.sha256(raw).hexdigest()
    if digest!=protocol['source_csv_sha256']:
        raise ValueError('ECB source vintage does not match the fixed protocol')
    rows=tuple(dict(row) for row in csv.DictReader(raw.decode('utf-8').splitlines()))
    return rows,digest


def binary64(value):
    v=float(value)
    if not math.isfinite(v):raise ValueError('forecast payload contains a nonfinite value')
    return dict(decimal=repr(v),binary64_hex=v.hex())


def build_snapshot(protocol,rows,origin_date,source_vintage_digest):
    """Compute one origin using its prefix and bind all eight primary forecasts.

    This low-level function receives a declared source identity. Production use
    must call source_rows first. Counterfactual causality tests may hold that
    identity fixed while perturbing inaccessible suffix values; doing so is a
    test convention, not authentication of a modified data file.
    """
    try:origin=date.fromisoformat(origin_date)
    except (TypeError,ValueError) as exc:raise ValueError('origin must be an ISO calendar date') from exc
    if origin.isoformat()!=origin_date:raise ValueError('canonical ISO date required')
    if type(source_vintage_digest) is not str or len(source_vintage_digest)!=64:
        raise ValueError('a declared SHA256 source vintage is required')
    currencies=tuple(protocol['currencies'])
    horizons=tuple(protocol['horizons_observed_intervals'])
    if currencies!=('USD','GBP','JPY','CHF') or horizons!=(1,5):
        raise ValueError('this driver implements the fixed four-currency, two-horizon protocol')
    if protocol['primary_weight']!='1/2':raise ValueError('fixed primary weight must be one half')
    selected=[]
    for row in rows:
        try:day=date.fromisoformat(row['Date'])
        except (KeyError,TypeError,ValueError) as exc:raise ValueError('invalid source event date') from exc
        if day<=origin:selected.append((day,row))
    selected.sort(key=lambda item:item[0])
    if not selected or selected[-1][0]!=origin:
        raise ValueError('origin must be an observed ECB reference-rate date')
    if len({day for day,_ in selected})!=len(selected):raise ValueError('duplicate prefix dates')
    ledger=BitemporalLedger('historical_replay_without_vintages')
    rates=[]
    vintage='ecb-csv-sha256:'+source_vintage_digest
    for day,row in selected:
        payload={}
        numeric=[]
        for currency in currencies:
            try:
                raw=row[currency].strip()
                value=Decimal(raw)
            except (KeyError,AttributeError,InvalidOperation) as exc:
                raise ValueError('missing or invalid prefix rate') from exc
            if not value.is_finite() or value<=0:raise ValueError('positive finite prefix rate required')
            payload[currency]=raw
            numeric.append(float(value))
        ordinal=day.toordinal()
        ledger.append(EventRevision.create('ECB euro reference rates',day.isoformat(),0,
                                           (ordinal,ordinal),ordinal,vintage,payload))
        rates.append(numeric)
    cutoff=origin.toordinal()
    snapshot=ledger.snapshot(cutoff,cutoff)
    states,forecasts=forecast_candidates(np.asarray(rates,dtype=float),protocol)
    column=1+protocol['fast_weights'].index(protocol['primary_weight'])
    parameters=dict(method='fixed_multiscale_filtered_historical_simulation',
                    protocol_digest=identity(protocol),source_vintage_digest=source_vintage_digest,
                    fast_weight=protocol['primary_weight'],alpha=protocol['alpha'],window=protocol['window'],
                    variance_initial_observations=protocol['variance_initial_observations'],
                    variance_halflives_observed_intervals=protocol['variance_halflives_observed_intervals'],
                    units=protocol['units'])
    model_digest=identity(parameters)
    records=[]
    for c,currency in enumerate(currencies):
      for h in horizons:
        if (c,h) not in forecasts:raise ValueError('insufficient prefix for all requested horizons')
        ends,quantiles,shortfalls=forecasts[c,h]
        if not len(ends) or int(ends[-1])!=len(selected)-1:
            raise ValueError('forecast origin is not supported by the prefix')
        target_id=f'ecb-upper-log-loss;origin={origin_date};currency={currency};h={h};alpha={protocol["alpha"]}'
        contract=ModelContract.from_snapshot(model_digest,snapshot,vintage,target_id)
        records.append(dict(currency=currency,horizon_observed_intervals=h,target_id=target_id,
                            contract=asdict(contract),contract_digest=contract.identity,
                            var=binary64(quantiles[-1,column]),es=binary64(shortfalls[-1,column]),
                            variance_fast=binary64(states[-1,0,c]),variance_slow=binary64(states[-1,1,c])))
    result=dict(schema='gabriel.ecb-forecast-snapshot.v1',origin_date=origin_date,
                first_prefix_event=selected[0][0].isoformat(),prefix_record_count=len(selected),
                event_cutoff=cutoff,receipt_cutoff=cutoff,snapshot_digest=snapshot.identity,
                source_vintage_digest=source_vintage_digest,model_parameters=parameters,
                forecasts=records,availability_mode='historical_replay_without_vintages',
                scope='binary64 forecasts bound to a model snapshot; not action or arithmetic certificates',
                receipt_convention='same-day ordinal receipts assumed for chronological replay; no historical release vintages')
    result['document_digest']=identity(result)
    return result


def verify_snapshot(document,*,protocol=None,rows=None,source_vintage_digest=None):
    """Recompute the fixed prefix forecasts and all model bindings.

    Default verification checks the supplied CSV against its protocol hash.
    This is reproducibility verification of binary64 results, not a rounding proof.
    """
    if protocol is None:protocol=load_protocol()
    if rows is None:
        rows,actual=source_rows(protocol)
        if source_vintage_digest is not None and source_vintage_digest!=actual:
            raise ValueError('declared source vintage differs from the verified input file')
        source_vintage_digest=actual
    if source_vintage_digest is None:raise ValueError('explicit rows require their declared source vintage')
    try:expected=build_snapshot(protocol,rows,document['origin_date'],source_vintage_digest)
    except (KeyError,TypeError) as exc:raise ValueError('malformed forecast snapshot') from exc
    if canonical(document)!=canonical(expected):
        raise ValueError('forecast, target, cutoff, vintage or model binding does not reproduce')
    return True


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--date',default=DEFAULT_DATE,help='observed ECB date, YYYY-MM-DD')
    parser.add_argument('--output',type=Path,default=ROOT/'results/ecb_snapshot.json')
    args=parser.parse_args()
    protocol=load_protocol();rows,digest=source_rows(protocol)
    result=build_snapshot(protocol,rows,args.date,digest)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps(dict(status='written',origin=args.date,contracts=len(result['forecasts']),
                          prefix_records=result['prefix_record_count'],snapshot=result['snapshot_digest'],
                          output=str(args.output)),indent=2))


if __name__=='__main__':main()
