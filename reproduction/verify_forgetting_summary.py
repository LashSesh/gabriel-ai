"""Independent reduction, paired intervals, and candidate gate reconstruction."""
from pathlib import Path
import json,math
from scipy.special import betainc
from scipy.optimize import brentq
ROOT=Path(__file__).resolve().parents[1]

def main():
 records=[];dev=[]
 for tag in ['','_refinement','_ablation']:
  records+=json.loads((ROOT/'results'/f'forgetting{tag}_synthetic.json').read_text())['records'];dev+=json.loads((ROOT/'results'/f'forgetting{tag}_development.json').read_text())['records']
 lookup={(r['case'],r['latency'],r['model'],r['replicate']):r['periods']['all']['conditional_excess_fz0'] for r in records};summary=json.loads((ROOT/'results/forgetting_summary.json').read_text());p=json.loads((ROOT/'results/forgetting_design_v2.json').read_text());final=json.loads((ROOT/'results/forgetting_final_selection.json').read_text());critical=brentq(lambda x:1-.5*betainc(31/2,.5,31/(31+x*x))-.975,1,4,xtol=1e-14)
 count=0;maxdiff=0.;eligibility=[]
 def verify_interval(values,got):
  nonlocal count,maxdiff
  m=math.fsum(values)/32;variance=math.fsum((v-m)**2 for v in values)/31;half=critical*math.sqrt(variance/32)
  for k,v in [('mean',m),('lower',m-half),('upper',m+half)]:maxdiff=max(maxdiff,abs(v-got[k]));assert abs(v-got[k])<1e-10
  count+=1
 for row in summary['rows']:
  name=row['name'];devmean=math.fsum(r['mean_fz0'] for r in dev if r['model']==name)/8;assert abs(devmean-row['development_mean'])<1e-12
  changes={}
  for mode in ['changing','stationary']:
   keys=[(case,h) for case in p['synthetic']['cases'] for h in [1,5] if case.startswith('stationary')==(mode=='stationary')]
   vals=[math.fsum(lookup[case,h,name,rep]-lookup[case,h,'cumulative',rep] for case,h in keys)/len(keys) for rep in range(32)];verify_interval(vals,row[mode+'_difference']);changes[mode]=math.fsum(vals)/32
  worst=max(math.fsum(lookup[case,h,name,rep]-lookup[case,h,'cumulative',rep] for rep in range(32))/32 for case in ['stationary_low','stationary_high'] for h in [1,5]);assert abs(worst-row['maximum_stationary_case_latency_penalty'])<1e-12
  if name in final['candidates']:
   base=next(x for x in summary['rows'] if x['name']=='cumulative')['development_mean'];eligible=name!='cumulative' and devmean<base and changes['changing']<0 and worst<=.02
   assert eligible==row['eligible']==final['candidates'][name]['eligible']
   if eligible:eligibility.append(name)
 for row in summary['matched_controls']:
  keys=[(c,h) for c in p['synthetic']['cases'] if not c.startswith('stationary') for h in [1,5]]
  vals=[math.fsum(lookup[c,h,row['model'],r]-lookup[c,h,row['reference'],r] for c,h in keys)/len(keys) for r in range(32)];verify_interval(vals,row['changing_difference'])
 for row in summary['per_case']:
  vals=[lookup[row['case'],row['latency'],row['model'],r]-lookup[row['case'],row['latency'],'cumulative',r] for r in range(32)];verify_interval(vals,row['difference'])
 assert not eligibility and final['primary_model']=='cumulative'
 out=dict(status='passed',paired_intervals=count,critical_value_df31=critical,max_interval_difference=maxdiff,eligible_candidates=eligibility,primary_model=final['primary_model'],market_outcomes_accessed=False)
 (ROOT/'results/forgetting_summary_verification.json').write_text(json.dumps(out,indent=2)+'\n');print(out)
if __name__=='__main__':main()
