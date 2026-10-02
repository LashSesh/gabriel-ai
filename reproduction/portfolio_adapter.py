"""Synthetic current-book adapter; future stress states are never queries.

Units, costs, hypothetical stresses and ambiguity set are frozen in the protocol.
The optional interventions here are evaluated actions, not executed trades.
"""
from fractions import Fraction as F
from itertools import product, combinations
from pathlib import Path
import hashlib,json
from decision_regions import RegionCatalogue
from portfolio_risk import robust_cvar,cvar

ROOT=Path(__file__).resolve().parents[1]
PROTOCOL=ROOT/'results/portfolio_protocol.json'
EXPECTED_PROTOCOL='b1a36f8f5d6d09b09a7807e9eb4435d077aa415681d66d4265a05f1df7fbf247'

def load_protocol():
    raw=PROTOCOL.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=EXPECTED_PROTOCOL:
        raise ValueError('portfolio protocol identity changed')
    return json.loads(raw),EXPECTED_PROTOCOL


def rational_json(value):
    if isinstance(value,F):return str(value)
    if isinstance(value,dict):return {str(k):rational_json(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [rational_json(v) for v in value]
    return value


def book_records(protocol):
    fields=tuple(protocol['fact_values'])
    records=[]
    for values in product(*(protocol['fact_values'][key] for key in fields)):
        fact=dict(zip(fields,values))
        row=tuple(str(fact[name]) if name!='position_registry' else
                  ','.join(str(fact[k]) for k in ('equity','duration','credit'))
                  for name in protocol['query_names'])
        semantic=tuple(fact[k] for k in fields if k!='metadata_tag')
        records.append(dict(facts=fact,row=row,semantic=semantic))
    return records


def loss_vector(protocol,fact,action,horizon):
    terms=protocol['action_terms'][action];frac=F(terms['position_fraction'])
    e,d,c=(F(fact[k])*frac for k in ('equity','duration','credit'))
    hedge=min(e,F(fact['existing_hedge']+terms['additional_hedge']))
    fee=F(terms['fee_base']+terms['fee_liquidity']*fact['liquidity_multiplier'])
    values=[]
    for scenario in protocol['scenarios']:
        se,sd,sc,sl=map(F,scenario[horizon])
        values.append(e*se+d*sd+c*sc-hedge*max(se,F(0))+
                      fact['liquidity_multiplier']*sl*(e+d+c)+fee)
    return tuple(values)


def cash_feasible(protocol,fact,action):
    t=protocol['action_terms'][action]
    return fact['cash']>=t['cash_base']+t['cash_liquidity']*fact['liquidity_multiplier']


def evaluate_books(protocol,records):
    alpha=F(protocol['alpha'])
    models=tuple(tuple(map(F,m['probabilities'])) for m in protocol['probability_models'])
    cache={};risks=[];flags=[];witnesses=[]
    for record in records:
        fact=record['facts'];scores=[];rowcerts=[]
        for action in protocol['action_names']:
            horizoncerts=[]
            for horizon in protocol['horizons']:
                losses=loss_vector(protocol,fact,action,horizon)
                if losses not in cache:
                    cert=robust_cvar(losses,models,alpha)
                    cert['max_listed_model_value']=max(cvar(losses,p,alpha) for p in models)
                    cache[losses]=cert
                horizoncerts.append(cache[losses])
            scores.append(max(cert['value'] for cert in horizoncerts))
            rowcerts.append(horizoncerts)
        risks.append(tuple(scores));flags.append(tuple(cash_feasible(protocol,fact,a) for a in protocol['action_names']))
        witnesses.append(rowcerts)
    return tuple(risks),tuple(flags),witnesses,len(cache)


def catalogue(protocol,digest,records,risks,flags,epsilon,risk_limit):
    return RegionCatalogue(contract_id='portfolio-static-snapshot;'+digest,
           query_names=protocol['query_names'],costs=protocol['query_costs'],
           rows=tuple(r['row'] for r in records),action_names=protocol['action_names'],
           risks=risks,feasible=flags,epsilon=epsilon,risk_limit=risk_limit)


def minimum_full_book_set(rows,semantic,costs):
    """Independent exhaustive fixed-set oracle for exact CURRENT-book recovery."""
    m=len(costs);best=None
    for mask in range(1<<m):
        ids=tuple(j for j in range(m) if mask>>j&1)
        groups={};valid=True
        for row,book in zip(rows,semantic):
            key=tuple(row[j] for j in ids)
            if key in groups and groups[key]!=book:valid=False;break
            groups[key]=book
        if valid:
            candidate=(sum(costs[j] for j in ids),len(ids),ids)
            if best is None or candidate<best:best=candidate
    if best is None:raise ValueError('current books not fully observable')
    return best


def inspection_catalogue(epsilon='1',risk_limit='12'):
    """Second synthetic adapter: present machine inspection and action losses.

    a,b are recorded defects, crew determines repair availability, tag is irrelevant.
    This is a static finite decision model, not a reliability prediction.
    """
    rows=[];risks=[];flags=[];semantic=[]
    for a,b,crew,tag in product((0,1),repeat=4):
        rows.append(tuple(map(str,(tag,a,b,crew))))
        risks.append((F(1+7*a+5*b),F(4+3*b),F(7+a)))
        flags.append((True,bool(crew),True));semantic.append((a,b,crew))
    return RegionCatalogue('industrial-inspection-static-v1',
           ('metadata_tag','wear_record','vibration_record','crew_record'),(1,2,2,1),
           tuple(rows),('continue','repair','controlled_stop'),tuple(risks),
           epsilon=epsilon,risk_limit=risk_limit,feasible=tuple(flags)),semantic
