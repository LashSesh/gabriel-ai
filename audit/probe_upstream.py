from pathlib import Path
import sys,json,tempfile,hashlib,time,copy
ROOT=Path(__file__).resolve().parent
REPO=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else ROOT/'verification_repo'
sys.path.insert(0,str(REPO))
from grfps_l2 import Kernel,canon
from test_kernel import genome,obs
from test_reference3d import bank,ready,accept,send
from reference3d_segments import SegmentJournal,replay
out={'fresh_execution':True,'notes':'Independent probes by audit agent; characterize boundaries, not claim complete adversarial security.'}
t=time.monotonic()
# Kernel idempotence relies on Python equality, which conflates bool and int.
k=Kernel(genome());event=obs(1,at=1);k.step(event);mut=copy.deepcopy(event);mut['at']=True
try:
    k.step(mut)
    outcome='accepted_as_duplicate'
except Exception as e:outcome=type(e).__name__+':'+str(e)
out['legacy_duplicate_boolean_alias']={'outcome':outcome,'canonical_bytes_differ':canon(event)!=canon(mut),'python_mapping_equality':event==mut,'records_after':len(k.records),'location':'grfps_l2.py Kernel.step inputs[eid] == event'}
# Tracking loss/recovery of the historical Boolean profile is not epoch-bound evidence retirement.
k=Kernel(genome());k.step(obs(1));k.step(obs(2,source='sensor_b'))
statuses=[k.snapshot()['percepts']['gateway']['epistemic']]
for i,v in enumerate([False,True]):
    k.step(dict(id='tracking'+str(i),kind='tracking',at=i+1,valid=v,label='probe'))
    statuses.append(k.snapshot()['percepts']['gateway']['epistemic'])
out['legacy_tracking_profile']={'gateway_status_before_during_after':statuses,'source_refs_after':k.snapshot()['percepts']['gateway']['source_refs'],'scope':'Historical Boolean model; current reference profile is tested separately.'}
# Current profile does invalidate on a fresh report; history remains independently accessible.
m=accept(ready());q=m.queries()['reference_assessment'];old=copy.deepcopy(m.reference_recordings[0]['certificate']);n=send(m)
out['current_new_report_invalidation']={'before':q['status'],'after':n.queries()['reference_assessment']['status'],'history_certificate_preserved':old==n.reference_recordings[0]['certificate'],'physical_validation':q['physical_validation']}
# A complete internally valid prefix is not authenticated to an externally expected terminal head.
with tempfile.TemporaryDirectory(prefix='gabriel_upstream_prefix_',dir=ROOT) as td:
    d=Path(td)/'journal';j=SegmentJournal(d,bank().contract)
    j.commit(dict(kind='tick',at=1));j.commit(dict(kind='tick',at=2));j.close()
    full=replay(d);f=d/'segment-000000.jsonl';raw=f.read_bytes();rows=raw.splitlines(keepends=True);f.write_bytes(b''.join(rows[:-1]));prefix=replay(d)
    out['complete_suffix_deletion']={'full_sequence':full['machine'].seq,'prefix_sequence':prefix['machine'].seq,'prefix_accepted':True,'full_head':full['head'],'prefix_head':prefix['head'],'heads_differ':full['head']!=prefix['head'],'scope':'Hash-linked semantic replay verifies supplied prefix; trusted terminal head/count is needed to detect complete suffix loss.'}
# A torn record is instead detected rather than silently repaired in current profile.
with tempfile.TemporaryDirectory(prefix='gabriel_upstream_torn_',dir=ROOT) as td:
    d=Path(td)/'journal';j=SegmentJournal(d,bank().contract);j.commit(dict(kind='tick',at=1));j.close();f=d/'segment-000000.jsonl';f.write_bytes(f.read_bytes()+b'{"partial":')
    try: replay(d);out['torn_record']={'rejected':False}
    except Exception as e: out['torn_record']={'rejected':True,'exception':type(e).__name__,'reason':str(e)}
out['elapsed_seconds']=time.monotonic()-t
(ROOT/'upstream_independent_probes.json').write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps(out,indent=2))
