"""Reproduce the complete forgetting study in an isolated project directory.

Preserves frozen original selection records and protocols in the supplied project.
The generated replay has its own numerical outputs; zip container hashes and run
metadata need not match; main scalar summaries and the primary selection are compared.
"""
from pathlib import Path
import argparse,shutil,subprocess,sys,json,os
ROOT=Path(__file__).resolve().parents[1]

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--destination',type=Path,default=ROOT.parent/'Gabriel_Forgetting_Replay');args=parser.parse_args();dest=args.destination.resolve()
 if dest==ROOT or ROOT in dest.parents:raise ValueError('Use a separate destination outside the original project')
 dest.mkdir(parents=True,exist_ok=True)
 for name in ['reproduction','results','figures']:(dest/name).mkdir(exist_ok=True)
 for source in (ROOT/'reproduction').glob('*.py'):shutil.copy2(source,dest/'reproduction'/source.name)
 names=['adaptive_risk_predictions.npz','severity_risk_predictions.npz','forgetting_design.json','forgetting_design.sha256','forgetting_design_v2.json','forgetting_design_v2.sha256','forgetting_refinement_design.json','forgetting_refinement_design.sha256','forgetting_ablation_design.json','forgetting_ablation_design.sha256','forgetting_market_status.json']
 for name in names:shutil.copy2(ROOT/'results'/name,dest/'results'/name)
 env=dict(os.environ,OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1')
 scripts=['benchmark_forgetting_design.py','benchmark_forgetting_refinement.py','benchmark_forgetting_ablation.py','summarize_forgetting.py','verify_forgetting.py','verify_forgetting_summary.py']
 for script in scripts:
  with (dest/'results'/(script+'.log')).open('w') as log:subprocess.run([sys.executable,'reproduction/'+script],cwd=dest,env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
  print('PASS',script,flush=True)
 a=json.loads((ROOT/'results/forgetting_summary.json').read_text());b=json.loads((dest/'results/forgetting_summary.json').read_text());assert a['primary_model']==b['primary_model'];maxdiff=0.
 assert len(a['rows'])==len(b['rows'])
 for x,y in zip(a['rows'],b['rows']):
  assert x['name']==y['name'];maxdiff=max(maxdiff,abs(x['development_mean']-y['development_mean']),abs(x['changing_difference']['mean']-y['changing_difference']['mean']))
 assert maxdiff<1e-9
 (dest/'results/reproduction_comparison.json').write_text(json.dumps(dict(status='passed',maximum_summary_difference=maxdiff,selection_unchanged=True,original_project_preserved=True),indent=2)+'\n');print('COMPLETE',dest,'max difference',maxdiff)
if __name__=='__main__':main()
