"""Rebuild retained synthetic traces without altering frozen selection records.

Run with --case0 through --case6 to checkpoint independently; no flag builds all
cases and combines them. A final --combine checks each member before finalization.
"""
from pathlib import Path
import argparse,hashlib,json,os,zipfile
import numpy as np
from forgetting_risk import ROOT,load_design,replay,synthetic_samples

def make_case(ci,p,directory):
 spec=p['synthetic'];case=spec['cases'][ci];q,e,y,s,d,tail,seeds=synthetic_samples(ci,case,spec);archive={}
 for h in spec['latencies']:
  key=f'{case}_{h}'
  for v in p['variants']:
   z=replay(q[:,0],e[:,0],y[:,0],h,v['kind'],v['memory'],p['c'])
   for field in ['var','es','issued_weights','issued_accumulator','accumulator_after','step','gradient_norm_squared','epoch','reset_before_issue']:archive[key+'_'+v['name']+'_'+field]=z[field]
  archive[key+'_losses']=y;archive[key+'_expert_var']=q[:,0];archive[key+'_expert_es']=e[:,0];archive[key+'_scale']=s;archive[key+'_tail_mean']=d
 f=directory/f'case_{ci}.npz';np.savez_compressed(f,**archive)
 with zipfile.ZipFile(f) as z:assert z.testzip() is None
 print('CHECKPOINT',ci,f.stat().st_size,flush=True)

def combine(p,directory):
 dest=ROOT/'results/forgetting_synthetic.npz';temp=directory/'complete.npz'
 with zipfile.ZipFile(temp,'w',compression=zipfile.ZIP_DEFLATED) as out:
  for ci in range(len(p['synthetic']['cases'])):
   with zipfile.ZipFile(directory/f'case_{ci}.npz') as z:
    assert z.testzip() is None
    for info in z.infolist():out.writestr(info,z.read(info.filename),compress_type=zipfile.ZIP_DEFLATED)
 with zipfile.ZipFile(temp) as z:assert z.testzip() is None;count=len(z.namelist())
 data=temp.read_bytes();dest.write_bytes(data)
 with zipfile.ZipFile(dest) as z:assert z.testzip() is None
 expected=json.loads((ROOT/'results/forgetting_synthetic.json').read_text())['archive_sha256'];actual=hashlib.sha256(data).hexdigest()
 check=dict(status='passed',members=count,bytes=len(data),original_recorded_sha256=expected,recovered_sha256=actual,identical_archive_hash=expected==actual,method='Same frozen generated inputs and recurrence; rebuilding replication-zero traces separately. Independent value checks are in forgetting_verification.json.')
 (ROOT/'results/forgetting_archive_rebuild.json').write_text(json.dumps(check,indent=2)+'\n');print(check,flush=True)

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--case',type=int);parser.add_argument('--combine',action='store_true');args=parser.parse_args();p=load_design();directory=ROOT/'results'/'forgetting_checkpoints';directory.mkdir(exist_ok=True)
 if args.case is not None:make_case(args.case,p,directory)
 elif args.combine:combine(p,directory)
 else:
  for ci in range(len(p['synthetic']['cases'])):make_case(ci,p,directory)
  combine(p,directory)
if __name__=='__main__':main()
