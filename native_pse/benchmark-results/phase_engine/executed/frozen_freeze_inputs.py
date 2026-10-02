#!/usr/bin/env python3
"""Deterministically regenerate synthetic public-input phase-engine fixtures."""
import json
from pathlib import Path
HERE=Path(__file__).resolve().parent

def raw(entity,tick):
    return json.dumps({'entity':entity,'tick':tick,'phase':(tick%11)*0.02,'value':((tick*17+entity*31)%101)/101},separators=(',',':'),sort_keys=True)

def fixture(n,workload):
    bootstrap=[]; measured=[]; tick=0
    def step(entities,vertices,edges):
        nonlocal tick
        tick+=1
        return {'batch':[raw(e,tick) for e in entities],'vertices':vertices,'edges':edges}
    for entity in range(n): bootstrap.append(step([entity],entity+1,0))
    path=[(i,i+1) for i in range(n-1)]
    pairs=path+[(i,j) for i in range(n) for j in range(i+1,n) if (i,j) not in path]
    if workload=='repeated_path':
        for index,edge in enumerate(path): bootstrap.append(step(edge,n,index+1))
        for _ in range(12): measured.append(step((0,1),n,n-1))
    else:
        for index,edge in enumerate(pairs[:16]): measured.append(step(edge,n,index+1))
    return {'entities':n,'workload':workload,'bootstrap':bootstrap,'measured':measured}

cases=[fixture(n,w) for n in [3,5,7,8,16] for w in ['repeated_path','cold_acquisition']]
inputs={'schema':1,'cases':cases}
(HERE/'inputs.json').write_text(json.dumps(inputs,indent=2)+'\n')
comparisons=[]
for ref,candidate in [('indexed','hoisted'),('hoisted','shared'),('shared','memoized')]:
    comparisons.append({'name':candidate+'_vs_'+ref,'variants':[ref,candidate],
                        'orders':[[ref,candidate] if i%2==0 else [candidate,ref] for i in range(5)]})
protocol={'schema':1,'toolchain':'1.95.0','build_jobs':1,
 'scope':'Synthetic in-memory complete native macro_step; explicit controlled sparse and acquisition fixtures, no durable owner or real workload performance claim',
 'variants':['indexed','hoisted','shared','memoized'],
 'features':{v:[v+'-engine'] for v in ['indexed','hoisted','shared','memoized']},
 'profile':{'opt-level':3,'lto':False,'codegen-units':1,'debug':True,'strip':'none','overflow-checks':False,'panic':'unwind'},
 'comparisons':comparisons,
 'engine':{'entities':[3,5,7,8,16],'workloads':['repeated_path','cold_acquisition'],
    'inner_repetitions':12,'external_pairs':5,'warmup_episodes_per_case':1,
    'repeated_path_ticks':12,'cold_acquisition_ticks':'min(16,n(n-1)/2)',
    'timer':'Measured macro_steps only; config, input/state construction, singleton/path bootstrap, cache clear, assertions, serialization and process launch excluded',
    'cache':'repeated_path retains cache after path bootstrap; cold_acquisition resets current-thread memoizer after singleton bootstrap for every episode',
    'configuration':'force-commit thresholds plus extraction convergence_tau=1, adaptation split_threshold=3, merge_distance=0',
    'golden':'Complete serialized SemanticCrystal values plus prior selected-state fields at EVERY bootstrap and measured tick, exact four-way bytes before timing',
    'shape':'actual full graph vertex and edge counts; full crystal regions; presence/absence and n,m of signature; every tick commits',
    'actual_keys':'Golden trace independently records crystal region order and induced adjacency bits, not inferred from requested workload name'},
 'primary_metric':'ticks_per_s = measured committed ticks / measured elapsed interval; paired ratio of per-process median ticks/s',
 'measurements_are_synthetic':True,
 'statistics':'Five paired process ratios with alternating order; median,min,max only, no population-level confidence claim'}
(HERE/'protocol.json').write_text(json.dumps(protocol,indent=2)+'\n')
