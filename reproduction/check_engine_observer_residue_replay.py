#!/usr/bin/env python3
"""Replay the 32 affected captured tasks into separately retained final databases.

This is targeted persistence/replay verification, not a timing experiment. The
original task captures, unexpected prefix files and recorded measurements are
read-only. Every new final database is kept and rechecked after all replays.
No benchmark collector or aggregation implementation is imported.
"""
from pathlib import Path
import argparse
import hashlib
import json
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from gabriel_runtime.canonical import canonical,loads
from gabriel_runtime.engine import Store
from gabriel_runtime.graph_observer import ADAPTER,GraphObserverAdapter,_source_hashes


def require(ok,message):
    if not ok:raise RuntimeError(message)


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def read(path):
    def pairs(items):
        value={}
        for key,item in items:
            require(key not in value,'Duplicate JSON key')
            value[key]=item
        return value
    return json.loads(Path(path).read_text(),object_pairs_hook=pairs,
        parse_constant=lambda v: (_ for _ in ()).throw(ValueError(v)))


def write(path,value):
    data=(json.dumps(value,indent=2,sort_keys=True,allow_nan=False)+'\n').encode('ascii')
    temporary=Path(str(path)+'.pending')
    with temporary.open('xb') as stream:stream.write(data)
    temporary.replace(path)
    require(path.read_bytes()==data,'Verification record write/readback mismatch')


def inspect_final(path,row):
    result={'bytes':path.stat().st_size,'sha256':sha(path)}
    with sqlite3.connect('file:'+str(path.resolve())+'?mode=ro',uri=True) as db:
        require(db.execute('PRAGMA integrity_check').fetchall()==[('ok',)],'Final SQLite structural integrity failed')
        head,count=db.execute('SELECT head,event_count FROM meta WHERE singleton=1').fetchone()
        commands=db.execute('SELECT sequence,command_text FROM journal ORDER BY sequence').fetchall()
        require(count==row['owner_events']==len(row['commands']) and head==row['owner_head'],
                'Final SQLite anchor differs from original captured task')
        require(len(commands)==count,'Final SQLite journal count differs')
        for i,(sequence,text) in enumerate(commands):
            require(sequence==i+1 and text==canonical(row['commands'][i]),'Final SQLite command differs')
    result.update(events=count,head=head,structural_integrity=True,
                  original_final_hash_matches=result['sha256']==row['database_sha256'],
                  original_final_size_matches=result['bytes']==row['database_bytes'])
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executed',required=True,type=Path)
    parser.add_argument('--residue-manifest',required=True,type=Path)
    parser.add_argument('--executable',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    executed=args.executed.resolve();output=args.output.resolve();executable=args.executable.resolve(strict=True)
    output.mkdir(parents=True,exist_ok=False)
    residue_manifest=read(args.residue_manifest)
    residues=residue_manifest['unexpected_unretained_database_residues']
    require(len(residues)==32,'Targeted verification requires the recorded 32 affected tasks')
    environment=read(executed/'environment.json');binary_sha=environment['executable_sha256']
    require(sha(executable)==binary_sha,'Original bundled CLI executable differs')
    sources_before=_source_hashes()
    original_hashes={str(args.residue_manifest.resolve()):sha(args.residue_manifest)}
    cases=[]
    for residue in residues:
        original_db=executed/residue['file']
        require(sha(original_db)==residue['actual_sha256'],'Original residue changed before verification')
        original_hashes[str(original_db)]=sha(original_db)
        directory=original_db.parent
        matches=[]
        for path in sorted(directory.glob('task_*.json')):
            row=read(path)
            if row['database_filename']==original_db.name:matches.append((path,row))
        require(len(matches)==1,'Residue does not identify exactly one original task')
        original_path,row=matches[0]
        require(row['database_retained'] is False and row['database_sha256']==residue['recorded_final_sha256'],
                'Original task final identity differs from residue manifest')
        original_hashes[str(original_path)]=sha(original_path)
        cases.append((residue,original_path,row))
    write(output/'inputs.json',{'source_hashes_before':sources_before,'executable_sha256':binary_sha,
        'executable_bytes':executable.stat().st_size,'original_readonly_files':original_hashes,
        'reader_sha256':sha(Path(__file__)),'command':sys.argv,
        'case_count':len(cases),'kind':'targeted replay verification; no performance measurement'})
    records=[];failure=None
    try:
        adapter=GraphObserverAdapter(executable,binary_sha)
        for index,(residue,original_path,row) in enumerate(cases):
            subdirectory=output/original_path.parent.name;subdirectory.mkdir(exist_ok=True)
            database=subdirectory/row['database_filename']
            record={'index':index,'original_task_file':str(original_path.relative_to(executed)),
                    'original_task_sha256':sha(original_path),'original_residue':residue['file'],
                    'new_database_file':str(database.relative_to(output)),
                    'original_final_sha256':row['database_sha256'],'original_final_bytes':row['database_bytes'],
                    'expected_head':row['owner_head'],'expected_events':row['owner_events']}
            with Store.create(database,{ADAPTER:adapter}) as owner:
                receipts=[]
                for command in row['commands']:
                    receipt=owner.submit(loads(canonical(command)))
                    receipts.append(receipt)
                require(canonical(receipts[-1])==canonical(row['query_receipt']),
                        'Final replay receipt differs byte-for-byte from original capture')
                require(owner.head==row['owner_head'] and owner.budget['events']==row['owner_events'],
                        'Replay owner anchor differs from original capture')
                record['final_receipt_canonical_sha256']=hashlib.sha256(canonical(receipts[-1]).encode('ascii')).hexdigest()
                record['every_captured_command_accepted']=True
                record['final_receipt_matches_byte_for_byte']=True
            record['after_close']=inspect_final(database,row)
            with Store.open(database,{ADAPTER:adapter},expected_head=row['owner_head'],
                            expected_events=row['owner_events']) as reopened:
                # Store.open has already executed a full anchored semantic audit.
                record['reopened_audit']=reopened.audit(expected_head=row['owner_head'],
                                                      expected_events=row['owner_events'])
            record['after_reopen']=inspect_final(database,row)
            require(record['after_reopen']==record['after_close'],'Reopening/auditing changed final database bytes')
            record['status']='passed'
            records.append(record)
            write(output/f'replay_{index:02d}.json',record)
            print(f'Verified retained replay {index+1}/{len(cases)}: {original_path.parent.name}/{row["database_filename"]}',flush=True)
        # Required second pass: all files must still be complete after every task.
        post_run_errors=[]
        for record,(_,_,row) in zip(records,cases):
            try:
                record['after_all_tasks']=inspect_final(output/record['new_database_file'],row)
                require(record['after_all_tasks']==record['after_close'],'Final database changed after later tasks')
                record['after_all_tasks_status']='passed'
            except Exception as exc:
                path=output/record['new_database_file']
                record['after_all_tasks_status']='failed'
                record['after_all_tasks_failure']={'error':repr(exc),'bytes':path.stat().st_size,'sha256':sha(path)}
                post_run_errors.append(record['new_database_file'])
            write(output/f'replay_{record["index"]:02d}.json',record)
        require(not post_run_errors,'Final after-all integrity failed: '+repr(post_run_errors))
        require(_source_hashes()==sources_before,'Runtime source changed during replay verification')
        require(sha(executable)==binary_sha,'Native executable changed during replay verification')
        for path,expected in original_hashes.items():
            require(sha(path)==expected,'Original evidence changed during read-only verification: '+path)
    except Exception as exc:
        failure=repr(exc)
        raise
    finally:
        sources_after=_source_hashes()
        result={'schema':'gabriel.engine-observer.residue-replay.v1',
            'status':'passed' if failure is None and len(records)==len(cases) else 'failed',
            'failure':failure,'kind':'targeted replay verification; no new timing claim',
            'source_hashes_before':sources_before,'source_hashes_after':sources_after,
            'runtime_sources_unchanged':sources_before==sources_after,
            'executable_sha256':binary_sha,'executable_unchanged':sha(executable)==binary_sha,
            'original_readonly_files_unchanged':all(sha(Path(p))==h for p,h in original_hashes.items()),
            'requested_replays':len(cases),'completed_replays':len(records),
            'all_final_receipts_match_original_bytes':all(r.get('final_receipt_matches_byte_for_byte') for r in records),
            'all_new_final_database_hashes_match_recorded_original_finals':all(r['after_close']['original_final_hash_matches'] for r in records),
            'all_new_final_databases_rechecked_after_all_tasks':all('after_all_tasks_status' in r for r in records),
            'all_new_final_databases_preserve_final_after_all_tasks':all(r.get('after_all_tasks_status')=='passed' for r in records),
            'original_residue_cause_explained':False,
            'records':records}
        write(output/'results.json',result)
    print(json.dumps({k:result[k] for k in ['status','requested_replays','completed_replays',
          'all_final_receipts_match_original_bytes','all_new_final_database_hashes_match_recorded_original_finals',
          'all_new_final_databases_rechecked_after_all_tasks','original_readonly_files_unchanged']}),flush=True)


if __name__=='__main__':main()
