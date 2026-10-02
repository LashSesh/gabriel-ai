#!/usr/bin/env python3
"""Independently verify durable graph-observer captures and reproduce their table.

No timing collector/harness is imported. This reader reconstructs fixture bytes,
source/graph identities, matrix-exponential references and within-triple medians.
An explicitly supplied original executable can also semantically replay the one
retained SQLite database; otherwise that replay is marked not executed here.
"""
from pathlib import Path
import argparse
import hashlib
import json
import math
import statistics
import sqlite3
import struct
import sys
import numpy as np
import scipy
from scipy.linalg import expm
from report_engine_observer_results import (require,read,digest,reconstruct,
    stable_unit,norm_squared,expected_action)

ROOT=Path(__file__).resolve().parents[1]
VARIANTS=['spectral_full','auto_full','auto_region']
PAIRS=[('spectral_full','auto_full'),('spectral_full','auto_region'),('auto_full','auto_region')]


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False)


def identity(value): return digest(canonical(value).encode('ascii'))

def bits(value): return struct.pack('>d',value).hex()


def number(value):
    require(type(value) is str and len(value)==16 and all(c in '0123456789abcdef' for c in value),'Invalid binary64 wire value')
    result=struct.unpack('>d',bytes.fromhex(value))[0]
    require(math.isfinite(result),'Nonfinite binary64 wire value')
    return result


def fixture(case,count,protocol):
    data=reconstruct(case);source=data['source'];n=case['n'];targets=list(range(0,n,2))
    norm=norm_squared(source)
    threshold=sum((float(source[i].real)*float(source[i].real)+float(source[i].imag)*float(source[i].imag))/norm for i in targets)
    query={'source':[{'entity':i,'re_bits':bits(float(z.real)),'im_bits':bits(float(z.imag))} for i,z in enumerate(source)],
           'targets':targets,'times_bits':[bits(protocol['query_times'][i%len(protocol['query_times'])]+(i//len(protocol['query_times']))/protocol['query_offsets_denominator']) for i in range(count)],
           'threshold_bits':bits(threshold),'deadband_bits':bits(protocol['deadband'])}
    result={'case':case,'query_count':count,'batches':data['batches'],'query':query}
    result['fingerprint']=identity(result)
    return result,data


def check_capture(executed,protocol):
    before=read(executed/'source_guard_before.json');after=read(executed/'source_guard_after.json')
    require(before==after,'Durable measured source guard changed')
    for rel,sha in before.items():
        require((ROOT/rel).is_file() and digest((ROOT/rel).read_bytes())==sha,'Durable current source mismatch: '+rel)
    require(read(executed/'protocol.json')==protocol,'Durable protocol changed')
    records=read(executed/'commands.json')
    expected=[f'process_{i}.command.json' for i in range(protocol['fresh_processes'])]
    require([row['file'] for row in records]==expected,'Incomplete durable command index')
    require({p.name for p in executed.glob('*.command.json')}==set(expected),'Unexpected durable individual command inventory')
    for row in records:
        raw=(executed/row['file']).read_bytes();command=read(executed/row['file'])
        require(digest(raw)==row['sha256'] and command==row['record'],'Durable command record differs')
        require(command['returncode']==0,'Durable worker failed')
        for stream in ['stdout','stderr']:
            require(digest((executed/command[stream]).read_bytes())==command[stream+'_sha256'],'Durable captured stream mismatch')
    integrity=read(executed/'integrity.json')
    require(integrity['sources_unchanged'] is True and integrity['executable_unchanged'] is True,'Durable incomplete source/executable guard')
    for key in ['individual_command_count','indexed_command_count','successful_workers','expected_workers']:
        require(integrity[key]==protocol['fresh_processes'],'Durable capture count mismatch')
    return before,{'source_files':len(before),'capture_commands':len(records),'capture_streams':2*len(records),
                  'aggregate_command_index_complete':True,'current_and_measured_sources_match':True}


def inspect_residual_database(path,row,executed):
    raw=path.read_bytes()
    require(digest(raw)!=row['database_sha256'],'Unexpected unretained final database remains')
    connection=sqlite3.connect('file:'+str(path.resolve())+'?mode=ro',uri=True)
    try:
        require(connection.execute('PRAGMA integrity_check').fetchall()==[('ok',)],
                'Unexpected residual database is structurally corrupt')
        stored=connection.execute('SELECT sequence,command_text FROM journal ORDER BY sequence').fetchall()
        head,count=connection.execute('SELECT head,event_count FROM meta WHERE singleton=1').fetchone()
        require(0<count<len(row['commands']) and len(stored)==count,'Residual database is not a strict task prefix')
        for i,(sequence,text) in enumerate(stored):
            require(sequence==i+1 and text==canonical(row['commands'][i]),'Residual database command prefix differs')
        require(head==row['commands'][count]['expected_head'],'Residual head differs from captured next command')
    finally:
        connection.close()
    require(path.read_bytes()==raw,'Read-only residue inspection altered bytes')
    return {'file':str(path.relative_to(executed)),'actual_bytes':len(raw),'actual_sha256':digest(raw),
        'recorded_final_bytes':row['database_bytes'],'recorded_final_sha256':row['database_sha256'],
        'stored_prefix_events':count,'recorded_final_events':row['owner_events'],
        'structurally_valid_and_matches_captured_command_prefix':True,
        'accepted_as_recorded_final_database':False,'cause':'Undetermined'}


def verify(executed,protocol,executable=None):
    sources,evidence=check_capture(executed,protocol)
    environment=read(executed/'environment.json')
    binary_checked=False
    if executable is not None:
        require(executable.is_file() and executable.stat().st_size==environment['executable_bytes']
                and digest(executable.read_bytes())==environment['executable_sha256'],'Original CLI executable mismatch')
        binary_checked=True
    workers=[read(executed/f'process_{i}'/'worker.json') for i in range(protocol['fresh_processes'])]
    require(len({w['pid'] for w in workers})==len(workers),'Durable processes were not fresh')
    inputs=[];references={};oracle_max=0.;cross_max=0.;retained=[];residues=[];task_count=0;queries=0
    for case in protocol['cases']:
        for count in protocol['query_counts']:
            item,data=fixture(case,count,protocol);inputs.append(item)
            if case['id'] not in references:
                unit=stable_unit(data['source']);norm=norm_squared(unit)
                refs=[]
                for j in range(max(protocol['query_counts'])):
                    time=protocol['query_times'][j%len(protocol['query_times'])]+(j//len(protocol['query_times']))/protocol['query_offsets_denominator']
                    state=expm(-1j*time*data['matrix'])@unit
                    refs.append(float(sum(abs(state[i])**2/norm for i in data['target_indices'])))
                references[case['id']]=refs
    for pi,worker in enumerate(workers):
        directory=executed/f'process_{pi}'
        require(worker['schema']=='gabriel.graph-observer-owner.worker.v1' and worker['process_index']==pi,'Durable worker identity')
        require(worker['source_guard_before']==worker['source_guard_after']==sources,'Durable per-worker source mismatch')
        require(worker['executable_sha256']==environment['executable_sha256'],'Durable executable mismatch')
        require(worker['protocol_sha256']==digest((ROOT/'results/graph_observer_owner_protocol.json').read_bytes()),'Durable protocol hash mismatch')
        require(read(directory/'inputs.json')==inputs,'Durable frozen fixture reconstruction differs')
        records=worker['records']
        require(worker['task_count']==len(records)==72,'Durable worker task count')
        require({p.name for p in directory.glob('task_*.json')}=={f'task_{i:03d}.json' for i in range(len(records))},'Durable primary task inventory')
        for i,record in enumerate(records):
            require(read(directory/f'task_{i:03d}.json')==record,'Durable task primary record differs')
        index=0;worker_cross=0.
        for ci,case in enumerate(protocol['cases']):
            for qi,count in enumerate(protocol['query_counts']):
                item,data=fixture(case,count,protocol)
                for trial in range(protocol['triples_per_process']):
                    offset=(pi+ci+qi+trial)%3;order=VARIANTS[offset:]+VARIANTS[:offset]
                    if (pi+trial)%2: order.reverse()
                    triple={}
                    for position,variant in enumerate(order):
                        row=records[index];index+=1;task_count+=1
                        require(row['process_index']==pi and row['trial']==trial and row['variant']==variant
                            and row['order_position']==position and row['variant_order']==order
                            and row['case_id']==case['id'] and row['query_count']==count
                            and row['input_fingerprint']==item['fingerprint'],'Durable task identity/order mismatch')
                        require(type(row['elapsed_ns']) is int and row['elapsed_ns']>0,'Invalid durable total time')
                        require(set(row['phase_ns'])=={'adapter_and_create','bind','append_all','query','close'}
                            and all(type(x) is int and x>0 for x in row['phase_ns'].values())
                            and sum(row['phase_ns'].values())==row['elapsed_ns'],'Durable phase partition mismatch')
                        require(row['elapsed_seconds']==row['elapsed_ns']/1e9,'Durable time-unit mismatch')
                        commands=row['commands'];receipt=row['query_receipt']
                        require(identity(commands)==row['commands_sha256'] and identity(receipt)==row['query_receipt_sha256'],'Durable command/receipt digest mismatch')
                        require(len(commands)==len(item['batches'])+2,'Durable command count mismatch')
                        for j,command in enumerate(commands):
                            require(command['id']==f'task-{j+1}' and command['contract']=='graph' and command['at']==j,'Durable command identity/clock')
                            require(type(command['expected_head']) is str and len(command['expected_head'])==64,'Invalid durable expected head')
                        require(commands[0]['op']=='bind' and commands[0]['payload']=={'adapter':'native-graph-observer/v1','config':{'backend':variant,'max_nodes':64,'max_batches':128,'max_queries':256}},'Durable bind contract mismatch')
                        for command,batch in zip(commands[1:-1],item['batches']):
                            require(command['op']=='append_batch' and command['payload']=={'entities':batch},'Durable ingestion command mismatch')
                        require(commands[-1]['op']=='query' and commands[-1]['payload']==item['query'],'Durable query request mismatch')
                        require(receipt['sequence']==row['owner_events']==len(commands)
                            and receipt['head']==row['owner_head'] and receipt['command_id']==commands[-1]['id']
                            and receipt['contract']=='graph' and receipt['result']['operation']=='query','Durable query receipt mismatch')
                        issue=receipt['result']['issue'];issue_body={k:v for k,v in issue.items() if k!='digest'}
                        require(identity(issue_body)==issue['digest'],'Durable issued-readout digest mismatch')
                        require(issue['request']==item['query'] and issue['owner_receipt_at']==len(commands)-1
                            and issue['batch_count']==len(item['batches']),'Durable issue request provenance mismatch')
                        response=issue['native_result'];snapshot=response['snapshot']
                        require(response['schema']=='gabriel-engine-observer/v1' and response['backend']==variant,'Durable native response contract')
                        expected_engine={'ticks':data['tick'],'commits':0,'vertices':case['n'],'edges':data['directed_edges'],
                            'observations':sum(len(b) for b in item['batches']),'faulted':False}
                        require(response['engine']==expected_engine,'Durable engine metadata mismatch')
                        require(snapshot['identity']==data['identity'] and snapshot['tick']==data['tick']
                            and snapshot['vertices']==[{'entity':i,'vertex_id':str(vid)} for i,vid in enumerate(data['vertices'])], 'Durable snapshot identity/labels mismatch')
                        expected_backend='spectral' if variant=='spectral_full' else case['expected_auto']
                        require(snapshot['walk_backend']==expected_backend,'Durable walk backend mismatch')
                        require(snapshot['model']=='exp(-itL);L=D-A;(W+W^T)/2;inactive-included;selfloops-ignored','Durable graph model mismatch')
                        require(len(response['query_results'])==1,'Durable native query count')
                        answer=response['query_results'][0]
                        expected_region='complete_graph_region' if variant=='auto_region' and case['family']=='clique' else 'state_readout'
                        require(answer['region_backend']==expected_region and len(answer['values'])==count,'Durable region/count mismatch')
                        masses=[];threshold=number(item['query']['threshold_bits']);deadband=number(item['query']['deadband_bits'])
                        for q,value in enumerate(answer['values']):
                            require(value['time_bits']==item['query']['times_bits'][q],'Durable time bits mismatch')
                            mass=number(value['mass_bits']);ref=references[case['id']][q]
                            error=abs(mass-ref);oracle_max=max(oracle_max,error)
                            require(error<=2e-9,'Durable SciPy reference disagreement')
                            action=expected_action(mass,threshold,deadband).replace('abstain','ambiguous')
                            require(value['decision']==action==expected_action(ref,threshold,deadband).replace('abstain','ambiguous'),'Durable policy/oracle decision mismatch')
                            masses.append(mass);queries+=1
                        triple[variant]=(masses,[v['decision'] for v in answer['values']])
                        db=directory/row['database_filename']
                        if row['database_retained']:
                            require(pi==ci==qi==trial==0 and variant=='spectral_full','Unexpected retained DB')
                            require(db.stat().st_size==row['database_bytes'] and digest(db.read_bytes())==row['database_sha256'],'Retained database bytes mismatch')
                            require(row['untimed_replay_audit']['status']=='passed','Original retained DB audit failed')
                            retained.append((db,row))
                        else:
                            if db.exists():
                                residues.append(inspect_residual_database(db,row,executed))
                    for masses,actions in triple.values():
                        require(actions==triple['spectral_full'][1],'Durable variant decision disagreement')
                        error=max(abs(a-b) for a,b in zip(masses,triple['spectral_full'][0]))
                        require(error<=protocol['mass_absolute_tolerance'],'Durable mass variant disagreement')
                        worker_cross=max(worker_cross,error)
        require(worker['maximum_mass_difference']==worker_cross,'Durable worker maximum differs')
        cross_max=max(cross_max,worker_cross)
    require(task_count==protocol['expected_timed_tasks']==360 and len(retained)==1,'Durable total/retained count mismatch')
    rows=[]
    for case in protocol['cases']:
        for count in protocol['query_counts']:
            processes=[]
            for worker in workers:
                selected=[r for r in worker['records'] if r['case_id']==case['id'] and r['query_count']==count]
                ratios={a+'_over_'+b:[] for a,b in PAIRS};times={v:[] for v in VARIANTS}
                for trial in range(protocol['triples_per_process']):
                    triple={r['variant']:r for r in selected if r['trial']==trial}
                    require(set(triple)==set(VARIANTS),'Durable summary missing triple')
                    for variant in VARIANTS: times[variant].append(triple[variant]['elapsed_ns'])
                    for a,b in PAIRS: ratios[a+'_over_'+b].append(triple[a]['elapsed_ns']/triple[b]['elapsed_ns'])
                processes.append({'process_index':worker['process_index'],'paired_ratios':ratios,
                    'median_paired_ratios':{k:statistics.median(v) for k,v in ratios.items()},
                    'median_ns':{k:statistics.median(v) for k,v in times.items()}})
            summary={}
            for a,b in PAIRS:
                key=a+'_over_'+b;values=[p['median_paired_ratios'][key] for p in processes]
                summary[key]={'median':statistics.median(values),'minimum':min(values),'maximum':max(values)}
            rows.append({'case':case,'query_count':count,'processes':processes,'paired_ratio_summary':summary,
                'median_process_ns':{v:statistics.median(p['median_ns'][v] for p in processes) for v in VARIANTS}})
    archived=read(executed/'summary.json')
    expected={'schema':'gabriel.graph-observer-owner.summary.v1','cases':rows,'fresh_processes':len(workers),
              'total_tasks':task_count,'maximum_mass_difference':cross_max}
    require(archived==expected,'Durable independently aggregated summary differs')
    replay=None
    if executable is not None:
        sys.path.insert(0,str(ROOT))
        from gabriel_runtime.engine import Store
        from gabriel_runtime.graph_observer import ADAPTER,GraphObserverAdapter
        db,row=retained[0]
        before=digest(db.read_bytes())
        with Store.open(db,{ADAPTER:GraphObserverAdapter(executable,environment['executable_sha256'])},
                        expected_head=row['owner_head'],expected_events=row['owner_events']) as owner:
            replay=owner.audit(expected_head=row['owner_head'],expected_events=row['owner_events'])
        require(digest(db.read_bytes())==before,'Independent replay changed retained database bytes')
    evidence.update({'schema':'gabriel.graph-observer-owner.independent-checks.v1','fresh_processes':len(workers),
        'complete_timed_tasks':task_count,'all_timed_scalar_outputs_checked':queries,'independent_scipy_reference_states':len(references)*max(protocol['query_counts']),
        'maximum_scipy_mass_error':oracle_max,'maximum_variant_mass_difference':cross_max,'scipy_absolute_tolerance':2e-9,
        'every_archived_summary_recomputed_exactly':True,'retained_databases_hash_verified':len(retained),
        'unexpected_unretained_database_residues':residues,'unexpected_residue_count':len(residues),
        'residues_excluded_from_final_database_evidence':True,
        'original_executable_reverified':binary_checked,'retained_database_semantic_replay_executed':replay is not None,
        'independent_replay_result':replay,'numpy_version':np.__version__,'scipy_version':scipy.__version__,
        'no_new_timings_generated':True})
    return rows,evidence


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executed',required=True,type=Path)
    parser.add_argument('--executable',type=Path)
    parser.add_argument('--output-dir',type=Path,default=ROOT/'results')
    args=parser.parse_args()
    protocol=read(ROOT/'results/graph_observer_owner_protocol.json')
    require(protocol['fresh_processes']==5 and protocol['triples_per_process']==3 and protocol['query_counts']==[1,256] and protocol['query_offsets_denominator']==4096,'Unexpected durable experiment design')
    rows,evidence=verify(args.executed,protocol,args.executable)
    args.output_dir.mkdir(parents=True,exist_ok=True)
    (args.output_dir/'graph_observer_owner_checks.json').write_text(json.dumps(evidence,indent=2)+'\n')
    (args.output_dir/'graph_observer_owner_summary.json').write_text(json.dumps({'evidence':evidence,'cases':rows},indent=2)+'\n')
    lines=[r'\begin{table}[H]\centering\small',
        r'\caption{Complete durable graph-observation tasks, from adapter creation through SQLite owner close. Median ratios and observed ranges of five worker medians, each from three paired triples. Every append and query starts a native process and replays the accumulated history. This includes the actual process, identity-check and durable-transaction costs.}',
        r'\label{tab:graphobserverowner}',r'\begin{tabular}{lrrrr}\toprule',
        r'Graph & $q$ & Total/full & Total/region [range] & Region (ms)\\\midrule']
    for row in rows:
        case=row['case'];pairs=row['paired_ratio_summary'];d=pairs['spectral_full_over_auto_region']
        name={'clique':'Clique','path':'Path','near_clique':'Near-clique'}[case['family']]+' '+str(case['n'])
        lines.append(r'%s & %d & %.2f & $%.2f\,[%.2f,\,%.2f]$ & %.1f\\'%(name,row['query_count'],
            pairs['spectral_full_over_auto_full']['median'],d['median'],d['minimum'],d['maximum'],row['median_process_ns']['auto_region']/1e6))
    lines += [r'\bottomrule\end{tabular}',r'\end{table}']
    (args.output_dir/'graph_observer_owner_tables.tex').write_text('\n'.join(lines)+'\n')
    print(json.dumps(evidence,indent=2))


if __name__=='__main__':main()
