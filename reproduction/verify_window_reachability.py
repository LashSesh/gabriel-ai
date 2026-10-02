"""Independent serialized-certificate verifier; no producer module imports.

Derives the harmonic coefficients from three exact quadrature states. Point
enclosures use complex projector evolution rather than the scalar cosine
producer. Arb remains a shared trusted arithmetic dependency. This is not a
proof-assistant checker. Run with python-flint installed.
"""
from __future__ import annotations
import argparse
import copy
from collections import Counter
from fractions import Fraction as F
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import struct
from flint import arb, acb, acb_mat, ctx, fmpq

ROOT = Path(__file__).resolve().parents[1]
COUNTS = Counter()

def canonical(x):
    return json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False)

def digest(x):
    return hashlib.sha256(canonical(x).encode('ascii')).hexdigest()

def check(x, label):
    if not x:
        raise AssertionError(label)
    COUNTS[label] += 1

def wire(x):
    if isinstance(x,dict):
        return F(int(x['numerator']),int(x['denominator']))
    # Independently use Python's exact as_integer_ratio of the decoded bits.
    return F(*struct.unpack('>d',bytes.fromhex(x))[0].as_integer_ratio())

def qa(x):
    x=F(x)
    return arb(fmpq(x.numerator,x.denominator))

def dyadic(x):
    check(x.is_exact(),'exact_arb_endpoint')
    m,e=map(int,x.man_exp())
    return F(m<<e) if e>=0 else F(m,1<<-e)

def ball(x):
    check(x.is_finite(),'finite_reference_ball')
    return dyadic(x.lower()),dyadic(x.upper())

def bound(x):
    return F(x['lower']),F(x['upper'])

def contains(outer,inner,label):
    lo,hi=bound(outer)
    check(lo<=inner[0]<=inner[1]<=hi,label)

def model(snapshot,source,targets):
    entities=snapshot['entities']; n=len(entities)
    check(1<=n<=64 and len(set(entities))==n and all(type(e) is int and e>=0 for e in entities),'valid_entities')
    check(len(snapshot['laplacian_bits'])==n and all(len(row)==n for row in snapshot['laplacian_bits']),'matrix_shape')
    check(len(source)==n and len({x['entity'] for x in source})==n,'unique_source_records')
    check(len(set(targets))==len(targets) and set(targets)<=set(entities),'valid_target_set')
    lap=tuple(tuple(wire(x) for x in row) for row in snapshot['laplacian_bits'])
    d,w=lap[0][0],(-lap[0][1] if n>1 else F(0))
    check(d>=0 and w>=0 and all(lap[i][j]==(d if i==j else -w)
          for i in range(n) for j in range(n)),'exact_represented_clique')
    src={x['entity']:(wire(x['re_bits']),wire(x['im_bits'])) for x in source}
    check(len(src)==n and set(src)==set(entities),'source_coverage')
    q=tuple(src[e] for e in entities)
    norm=sum((r*r+i*i for r,i in q),F(0))
    check(norm>0,'nonzero_exact_norm')
    mr=sum((v[0] for v in q),F(0))/n
    mi=sum((v[1] for v in q),F(0))/n
    indices=tuple(j for j,e in enumerate(entities) if e in targets)
    r0=sum((q[j][0]**2+q[j][1]**2 for j in indices),F(0))/norm
    rpi=sum(((2*mr-q[j][0])**2+(2*mi-q[j][1])**2 for j in indices),F(0))/norm
    rh=sum(((mr+q[j][1]-mi)**2+(mi-q[j][0]+mr)**2 for j in indices),F(0))/norm
    a,b=(r0+rpi)/2,(r0-rpi)/2
    c=rh-a
    binding=dict(entities=entities,laplacian_bits=snapshot['laplacian_bits'],
                 source=[next(t for t in source if t['entity']==e) for e in entities],
                 targets=[e for e in entities if e in targets])
    return dict(a=a,b=b,c=c,omega=n*w,n=n,w=w,d=d,norm=norm,q=q,
                indices=indices,mr=mr,mi=mi,lap=lap,input_sha256=digest(binding))

@lru_cache(maxsize=40000)
def complex_mass(q,indices,omega,t,precision=1024):
    n=len(q); norm=sum((r*r+i*i for r,i in q),F(0))
    mr=sum((v[0] for v in q),F(0))/n
    mi=sum((v[1] for v in q),F(0))/n
    with ctx.workprec(precision):
        z=acb(0,qa(-omega*t)).exp()
        mean=acb(qa(mr),qa(mi))
        total=arb(0)
        for j in indices:
            r,i=q[j]
            v=mean+z*acb(qa(r-mr),qa(i-mi))
            total+=v.real*v.real+v.imag*v.imag
        lo,hi=ball(total/qa(norm))
        return max(F(0),lo),min(F(1),hi)

def mass(m,t):
    if m['omega']==0 or t==0:
        x=sum((m['q'][j][0]**2+m['q'][j][1]**2 for j in m['indices']),F(0))/m['norm']
        return x,x
    if m['b']==m['c']==0:
        return m['a'],m['a']
    # 4096 bits give a separate reference also for huge binary64 phases.
    precision=4096 if abs(m['omega']*t)>2**200 else 1024
    return complex_mass(m['q'],m['indices'],m['omega'],t,precision)

def check_mass(m,t,enclosure):
    contains(enclosure,mass(m,t),'independent_complex_mass_contained')

def check_geometry(m,a,z,g):
    with ctx.workprec(4096):
        phi=arb.atan2(qa(m['c']),qa(m['b']))
        p=2*arb.pi()
        left=ball((qa(m['omega']*a)-phi)/p)
        right=ball((qa(m['omega']*z)-phi)/p)
        contains(g['phase'],ball(phi),'phase_enclosure_valid')
        contains(g['start_quotient'],left,'start_phase_quotient_valid')
        contains(g['end_quotient'],right,'end_phase_quotient_valid')
    ceil=lambda v:-((-v.numerator)//v.denominator)
    floor=lambda v:v.numerator//v.denominator
    check(int(g['possible_first_index'])==ceil(F(g['start_quotient']['lower'])),'first_index_bound')
    check(int(g['possible_last_index'])==floor(F(g['end_quotient']['upper'])),'last_index_bound')
    return ceil(left[0]),floor(right[1])

def verify_analytic(snapshot,case,r):
    m=model(snapshot,case['source'],case['targets'])
    a,z,h=(wire(case[k]) for k in ('start_bits','end_bits','threshold_bits'))
    check(a<=z and 0<=h<=1,'valid_analytic_query')
    check(r['query']==dict(start=str(a),end=str(z),threshold=str(h)),'analytic_query_binding')
    p=r['model']
    for key in ('a','b','c','omega'):
        check(F(p[key])==m[key],'independent_quadrature_coefficients')
    check(p['input_sha256']==m['input_sha256'],'analytic_input_binding')
    check(F(p['norm_squared'])==m['norm'],'exact_norm_binding')
    check(F(p['delta'])==m['d']-(m['n']-1)*m['w'],'represented_delta_binding')
    check(F(p['rho'])==m['d']+m['w'],'represented_rho_binding')
    D=m['b']**2+m['c']**2
    check(F(p['amplitude_squared'])==D,'amplitude_binding')
    ev=r['evidence']; kind=ev['method']; status=r['status']
    res=r['resources']
    check(0<=res['point_evaluations']<=res['max_point_evaluations'] and
          0<=res['phase_evaluations']<=res['max_phase_evaluations'] and
          0<=res['max_precision_bits']<=res['precision_cap_bits']<=512,'analytic_resource_caps')
    if status=='unknown':
        check(kind=='precision_cap','unknown_has_no_decision')
        return
    if kind=='stationary_exact':
        check(m['omega']==0 or D==0,'stationary_condition')
        v=m['a']+m['b'] if m['omega']==0 else m['a']
        check(F(ev['value'])==v and bound(ev['mass'])==(v,v),'stationary_evidence')
        check(status==('reachable' if v>h else 'excluded'),'stationary_decision')
    elif kind=='global_amplitude_exact':
        check(status=='excluded' and h>=m['a'] and (h-m['a'])**2>=D,'global_exclusion')
        check(F(ev['offset'])==m['a'] and F(ev['radicand'])==D and F(ev['supremum_upper'])==h,'global_evidence')
    elif kind=='rational_point':
        t=F(ev['time'])
        check(status=='reachable' and a<=t<=z,'witness_inside_window')
        check_mass(m,t,ev['mass'])
        check(F(ev['mass']['lower'])>h,'strict_witness')
    elif kind in ('endpoint_maximum','singleton_point'):
        check(status=='excluded','endpoint_exclusion_status')
        expected=[a] if a==z else [a,z]
        check([F(e['time']) for e in ev['endpoints']]==expected,'endpoint_coverage')
        for e in ev['endpoints']:
            check_mass(m,F(e['time']),e['mass'])
            check(F(e['mass']['upper'])<=h,'endpoint_below_threshold')
        check(F(ev['supremum_upper'])==max(F(e['mass']['upper']) for e in ev['endpoints']),'endpoint_supremum')
        if kind=='singleton_point':
            check(a==z,'singleton_window')
        else:
            first,last=check_geometry(m,a,z,ev['phase_geometry'])
            check(first>last,'no_interior_maximum')
    elif kind=='critical_point':
        check(status=='reachable','critical_witness_status')
        k=int(ev['phase_index']); lo,hi=bound(ev['time_enclosure'])
        check(a<=lo<=hi<=z,'critical_time_inside_window')
        with ctx.workprec(4096):
            t=ball((arb.atan2(qa(m['c']),qa(m['b']))+2*arb.pi()*k)/qa(m['omega']))
        contains(ev['time_enclosure'],t,'critical_root_contained')
        check_geometry(m,a,z,ev['phase_geometry'])
        check(F(ev['value']['offset'])==m['a'] and F(ev['value']['radicand'])==D,'critical_peak_value')
        l,u=bound(ev['mass']); check(l>h,'critical_strict_margin')
        check((l<=m['a'] or (l-m['a'])**2<=D) and u>=m['a'] and (u-m['a'])**2>=D,'critical_peak_bounds')
    else:
        raise AssertionError('unrecognized analytic proof method '+kind)

def verify_baseline(snapshot,case,r):
    m=model(snapshot,case['source'],case['targets'])
    a,z,h=(wire(case[k]) for k in ('start_bits','end_bits','threshold_bits'))
    check(a<=z and 0<=h<=1,'valid_baseline_query')
    check(r['input']==dict(start=str(a),end=str(z),threshold=str(h)),'baseline_query_binding')
    check(r['model_identity']==m['input_sha256'],'baseline_input_binding')
    check(all(F(r['coefficients'][k])==m[k] for k in ('a','b','c','omega')),'baseline_coefficients')
    if r['bounds'] is not None:
        R,K1,K2=(F(r['bounds'][k]) for k in ('radius_upper','K1','K2'))
        check(R>=0 and R*R>=m['b']**2+m['c']**2 and K1==abs(m['omega'])*R and K2==m['omega']**2*R,'derivative_bounds')
    else:
        check(not r['intervals'],'no_cover_without_bounds')
    check(r['point_evaluations']==len(r['points'])<=r['caps']['max_evaluations']==256,'baseline_point_cap')
    points={}
    for p in r['points']:
        t=F(p['time']); check(a<=t<=z,'sample_inside_window')
        check_mass(m,t,p); points[t]=bound(p)
    kind=(r['certificate'] or {}).get('kind'); status=r['status']
    if kind=='stationary':
        check(m['omega']==0 or (m['b']==m['c']==0),'baseline_stationary_condition')
        v=m['a']+m['b'] if m['omega']==0 else m['a']
        check(F(r['certificate']['mass'])==v and status==('reachable' if v>h else 'excluded'),'baseline_stationary_decision')
    elif kind=='global_amplitude':
        check(status=='excluded' and h>=m['a'] and (h-m['a'])**2>=m['b']**2+m['c']**2,'baseline_global_exclusion')
    elif status=='reachable':
        check(kind=='point','baseline_point_witness_kind')
        t=F(r['witness']['time']); check(a<=t<=z,'baseline_witness_time')
        check_mass(m,t,r['witness']); check(F(r['witness']['lower'])>h,'baseline_strict_witness')
    elif status=='excluded' and kind=='point':
        check(a==z and a in points and points[a][1]<=h,'baseline_singleton')
    elif kind=='interval_cover' or r['intervals']:
        cursor=a
        for cell in r['intervals']:
            l,u=F(cell['start']),F(cell['end'])
            check(l==cursor and l<u and l in points and u in points,'gapless_interval_cover')
            v,w=points[l][1],points[u][1]; length=u-l
            upper=min(v+K1*length,w+K1*length,(v+w+K1*length)/2,
                      max(v,w)+K2*length**2/8,m['a']+R,F(1))
            check(F(cell['upper'])==upper,'certified_interval_upper')
            if status=='excluded':
                check(upper<=h,'whole_interval_exclusion')
            cursor=u
        check(cursor==z,'complete_closed_window_cover')
        if status=='excluded':
            check(kind=='interval_cover','baseline_cover_kind')
    else:
        check(status=='unknown','unknown_baseline_only')

def snapshot_check(data):
    s=data['response']['snapshot']; n=len(s['vertices'])
    raw=bytearray(b'gabriel/conditioned-snapshot/v1;exp(-itL);L=D-A\0')
    raw+=s['tick'].to_bytes(8,'little')+n.to_bytes(8,'little')
    labels=[]
    mat=[['0000000000000000']*n for _ in range(n)]
    for i,(v,d) in enumerate(zip(s['vertices'],s['degree_bits'])):
        fnv=14695981039346656037
        for c in f"sensor-{v['entity']}".encode():
            fnv=((fnv^c)*1099511628211)%(1<<64)
        check(fnv==int(v['vertex_id']),'native_entity_mapping')
        raw+=fnv.to_bytes(8,'little')+int(d,16).to_bytes(8,'little')
        labels.append(v['entity']);mat[i][i]=d
    raw+=len(s['adjacency']).to_bytes(8,'little')
    for e in s['adjacency']:
        for x in (e['from'],e['to'],int(e['weight_bits'],16)):
            raw+=x.to_bytes(8,'little')
        mat[e['from']][e['to']]=f"{int(e['weight_bits'],16)^(1<<63):016x}"
    check(hashlib.sha256(raw).hexdigest()==s['identity'],'native_snapshot_digest')
    check(data['certificate_snapshot']==dict(identity=s['identity'],entities=labels,laplacian_bits=mat),'native_matrix_binding')

def matrix_reference(m,t):
    with ctx.workprec(512):
        full=acb_mat([[acb(0,qa(-v*t)) for v in row] for row in m['lap']]).exp()
        q=acb_mat([[acb(qa(r),qa(i))] for r,i in m['q']])
        y=full*q
        total=sum((y[j,0].real**2+y[j,0].imag**2 for j in m['indices']),arb(0))/qa(m['norm'])
        lo,hi=ball(total)
        other=mass(m,t)
        check(lo<=other[1] and other[0]<=hi,'full_acb_matrix_reference_overlap')
        check(hi-lo<F(1,1<<300),'full_matrix_reference_width')

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--inputs',type=Path,required=True)
    ap.add_argument('--evaluation',type=Path,required=True); ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args(); inp=json.loads(args.inputs.read_text()); ev=json.loads(args.evaluation.read_text())
    expected=inp.pop('cohort_digest'); check(digest(inp)==expected,'cohort_digest');inp['cohort_digest']=expected
    check(ev['cohort_digest']==expected and ev['protocol_sha256']==inp['protocol_sha256'],'evaluation_binding')
    for path,sha in ev['source_sha256'].items():
        check(hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==sha,'evaluated_source_current')
    for s in inp['snapshots'].values(): snapshot_check(s)
    cases={c['case_id']:c for c in inp['cases']}; seen=set(); decisions={}; counts=Counter()
    for record in ev['outputs']:
        cid,method=record['case_id'],record['method']; check((cid,method) not in seen,'unique_result')
        seen.add((cid,method)); case=cases[cid]; snapshot=inp['snapshots'][case['snapshot_key']]['certificate_snapshot']
        check(method in ('analytic','adaptive','uniform'),'declared_method')
        check(record['cohort']==case['cohort'],'cohort_label_binding')
        if method=='analytic': verify_analytic(snapshot,case,record['result'])
        else:
            check(record['result']['method']==method,'baseline_method_binding')
            verify_baseline(snapshot,case,record['result'])
        status=record['result']['status']; counts[(record['cohort'],method,status)]+=1
        if status in ('reachable','excluded'):
            check(cid not in decisions or decisions[cid]==status,'decisive_methods_agree'); decisions[cid]=status
    check(seen=={(cid,m) for cid in cases for m in ('analytic','adaptive','uniform')},'complete_method_coverage')
    refs=[]
    for n in ('7','13'):
        for seed in (20260927,20260928):
            c=next(c for c in inp['cases'] if c['case_id'].startswith(f'primary-n{n}-s{seed}-r0-'))
            m=model(inp['snapshots'][n]['certificate_snapshot'],c['source'],c['targets'])
            for t in (F(0),F(1,3)/m['omega'],F(7,3)/m['omega']):
                matrix_reference(m,t);refs.append(dict(nodes=int(n),seed=seed,time=str(t)))
    rejected=[]
    # Mutate independent payloads, requiring the verifier to reject each.
    def mutation(label,record,mutate):
        r=copy.deepcopy(record); mutate(r['result']);c=cases[r['case_id']]
        s=inp['snapshots'][c['snapshot_key']]['certificate_snapshot']
        try:
            (verify_analytic if r['method']=='analytic' else verify_baseline)(s,c,r['result'])
        except (AssertionError,ValueError,KeyError): rejected.append(label)
        else: raise AssertionError('undetected mutation '+label)
    records=ev['outputs']
    ar=next(r for r in records if r['method']=='analytic' and r['result']['evidence']['method']=='rational_point')
    ex=next(r for r in records if r['method']=='analytic' and r['result']['evidence']['method']=='endpoint_maximum')
    bc=next(r for r in records if r['method']=='adaptive' and r['result']['certificate']=={'kind':'interval_cover'})
    mutation('wrong source binding',ar,lambda r:r['model'].__setitem__('input_sha256','0'*64))
    mutation('wrong coefficient',ar,lambda r:r['model'].__setitem__('c',str(F(r['model']['c'])+1)))
    mutation('wrong query',ar,lambda r:r['query'].__setitem__('threshold','1'))
    mutation('invalid point mass',ar,lambda r:r['evidence'].__setitem__('mass',dict(lower='2',upper='3')))
    mutation('wrong phase index',ex,lambda r:r['evidence']['phase_geometry'].__setitem__('possible_first_index','999999'))
    mutation('cover gap',bc,lambda r:r['intervals'][0].__setitem__('start',str(F(r['intervals'][0]['start'])+F(1,10000))))
    mutation('false interval upper',bc,lambda r:r['intervals'][0].__setitem__('upper','-1'))
    mutation('invalid derivative bound',bc,lambda r:r['bounds'].__setitem__('K2','0'))
    ge=next(r for r in records if r['method']=='analytic' and r['result']['evidence']['method']=='global_amplitude_exact')
    mutation('false global upper',ge,lambda r:r['evidence'].__setitem__('supremum_upper','-1'))
    extra=[]
    for path,key in ((ROOT/'results/window_certificate_checks.json','certificates'),
                     (ROOT/'audit/window_extreme_cap_supplement.json','cases')):
        for record in json.loads(path.read_text())[key]:
            r=record['certificate']
            if r['status']=='out_of_scope':
                mat=[[wire(x) for x in row] for row in record['snapshot']['laplacian_bits']]
                d,w=mat[0][0],-mat[0][1]
                check(any(mat[i][j]!=(d if i==j else -w) for i in range(len(mat)) for j in range(len(mat))),
                      'out_of_scope_structure_control')
            else:
                def rational_wire(value):
                    value=F(value)
                    return dict(numerator=str(value.numerator),denominator=str(value.denominator))
                c=dict(source=record['source'],targets=record['targets'],
                       start_bits=rational_wire(r['query']['start']),end_bits=rational_wire(r['query']['end']),
                       threshold_bits=rational_wire(r['query']['threshold']))
                verify_analytic(record['snapshot'],c,r)
            extra.append(dict(name=record['name'],status=r['status'],source=str(path.relative_to(ROOT))))
    output=dict(schema='gabriel.window-independent-verification.v1',passed=True,
                inputs_sha256=hashlib.sha256(args.inputs.read_bytes()).hexdigest(),
                evaluation_sha256=hashlib.sha256(args.evaluation.read_bytes()).hexdigest(),
                verifier_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                certificates=len(seen),decisive_certificates=sum(v for (c,m,s),v in counts.items() if s in ('reachable','excluded')),
                unknown_certificates=sum(v for (c,m,s),v in counts.items() if s=='unknown'),
                counts=[dict(cohort=c,method=m,status=s,count=v) for (c,m,s),v in sorted(counts.items())],
                assertions=dict(COUNTS),complex_reference_cache=complex_mass.cache_info()._asdict(),
                matrix_references=refs,detected_mutations=rejected,
                supplementary_certificates=extra,
                trust_boundary='Independent algebra and aggregation, shared Python integer and Arb/acb arithmetic; not machine-checked formal proof.')
    args.output.write_text(json.dumps(output,indent=2)+'\n')
    print(json.dumps({k:output[k] for k in ('passed','certificates','decisive_certificates','unknown_certificates')}))

if __name__=='__main__': main()
