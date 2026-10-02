"""Independent finite oracles, Bellman inequalities and replay of saved paths."""
from pathlib import Path
from collections import Counter
from copy import deepcopy
import hashlib
import json
import numpy as np
from orientation import BinaryObservation, parity
from robust_orientation import BoundedErrorObservation, check_certificate

ROOT = Path(__file__).resolve().parents[1]; OUT = ROOT / 'results'


def verify_bellman(data, target):
    # Reconstruct every split and Bellman minimum without calling Planner.
    candidates, remaining = data['candidates'], data['remaining']
    nodes = data['nodes']
    for skey, node in nodes.items():
        state = int(skey)
        members = [i for i in range(len(candidates)) if (state >> i) & 1]
        labels = {parity(target, candidates[i]) for i in members}
        assert labels
        if len(labels) == 1:
            assert node['label'] == next(iter(labels)) and node['value'] == 0
            assert node['choice'] is None and node['branches'] == []
            continue
        assert node['label'] is None
        expected = {}
        for q, j in enumerate(remaining):
            groups = [sum(1 << i for i in members if ((candidates[i] >> j) & 1) == y) for y in (0, 1)]
            if all(groups): expected[q] = groups
        actual = {r['query']: r['children'] for r in node['branches']}
        assert actual == expected
        values = {q: 1 + max(nodes[str(s)]['value'] for s in children) for q, children in expected.items()}
        assert all(s.bit_count() < state.bit_count() for children in expected.values() for s in children)
        assert node['value'] == min(values.values())
        assert node['choice'] == min(q for q, value in values.items() if value == min(values.values()))
    assert nodes[str(data['root'])]['value'] == 5
    return len(nodes)


def main():
    raw = (OUT / 'robust_orientation_protocol.json').read_bytes(); protocol = json.loads(raw)
    data = json.loads((OUT / 'robust_orientation_results.json').read_text())
    assert hashlib.sha256(raw).hexdigest() == data['summary']['protocol_sha256']
    model_data = data['model']
    model = BinaryObservation(model_data['n'], model_data['rows'], model_data['rhs'], model_data['target'])
    observer = BoundedErrorObservation(model, 1)

    # Build all flat assignments through vertex frames and one explicit seam,
    # independently of the generating script's binary nullspace catalogue.
    edges = sorted({tuple(sorted(e)) for i in range(6) for e in
                    [(1+i,1+(i+1)%6),(7+i,7+(i+1)%6),(1+i,7+i),(1+i,7+(i+1)%6)]})
    seam = sum(1 << edges.index(e) for e in [(1,6),(7,12),(6,7)])
    code = set()
    for frames in range(1 << 11):
        switched = sum((((frames >> (a-1)) ^ (frames >> (b-1))) & 1) << j
                       for j, (a,b) in enumerate(edges))
        code.update((switched, switched ^ seam))
    assert code == set(data['code']) and len(code) == 4096
    target = model.target
    opposite = [a for a in code if parity(target, a)]
    assert min(a.bit_count() for a in opposite) == 3
    assert set(data['minimum_patterns']) == {a for a in opposite if a.bit_count() == 3}
    # Twelve minimum patterns cover all coordinates: any fixed omission fails t=1.
    union = 0
    for a in data['minimum_patterns']: union |= a
    assert union == (1 << 24)-1
    # Six disjoint parity-changing seams imply at least 12 queries on a clean path.
    seams = []
    for i in range(6):
        pairs = [(1+i,1+(i+1)%6),(7+i,7+(i+1)%6),(1+i,7+(i+1)%6)]
        mask = sum(1 << edges.index(tuple(sorted(e))) for e in pairs)
        assert mask in code and parity(target, mask) == 1
        assert all(mask & other == 0 for other in seams)
        seams.append(mask)
    node_count = verify_bellman(data['bellman'], target)

    certificates = 0
    for records in data['representatives'].values():
        for name, record in records.items():
            obs = record['observations'] if name == 'full' else record['path']['observations']
            assert check_certificate(observer, obs, record['certificate']); certificates += 1
    for record in data['lexical_representatives'].values():
        assert check_certificate(observer, record['observations'], record['certificate']); certificates += 1
    for record in data['omissions']:
        assert check_certificate(observer, record['observations'], record['certificate']); certificates += 1
    robust2 = BoundedErrorObservation(model, 2)
    for record in data['stress']:
        obs = [(j,(record['error']>>j)&1) for j in range(24)]
        assert check_certificate(observer, obs, record['one_budget'])
        assert check_certificate(robust2, obs, record['two_budget']); certificates += 2

    # Independent catalogue agreement for each distinct (fault, prefix) encountered.
    # Translation by a latent flat assignment preserves mismatch distances and
    # flips all target labels by the same bit. Check that identity on every path.
    with np.load(OUT / 'robust_orientation_paths.npz') as compressed:
        archive = {key: compressed[key] for key in compressed.files}
    cache = {}; paths_verified = 0; prefixes_verified = set()
    def catalogue_decision(fault, mask):
        key = (int(fault), int(mask))
        if key not in cache:
            classes = {parity(target, a) for a in code if ((a ^ key[0]) & key[1]).bit_count() <= 1}
            cache[key] = classes
        return cache[key]
    for policy, metric in data['summary']['policies'].items():
        orders = archive[policy+'_path']; counts = archive[policy+'_count']
        masks = archive[policy+'_mask']; answers = archive[policy+'_answer']
        for k in range(len(counts)):
            a, e, y = map(int, (archive['latent'][k], archive['error'][k], archive['report'][k]))
            assert a in code and y == a ^ e and e.bit_count() <= 1
            n = int(counts[k]); order = list(map(int, orders[k, :n]))
            assert len(set(order)) == n and np.all(orders[k,n:] == -1)
            mask = sum(1 << j for j in order)
            assert mask == int(masks[k])
            values = catalogue_decision(e, mask)
            assert values == {int(answers[k]) ^ parity(target, a)} == {0}
            if policy.startswith('ring_'):
                prefix = 0
                for step,j in enumerate(order):
                    if step >= 12:
                        assert catalogue_decision(e, prefix) == {0,1}
                    prefix |= 1 << j
            if policy == 'lexical_robust_prefix' and n:
                assert catalogue_decision(e, mask ^ (1 << order[-1])) == {0,1}
            paths_verified += 1
        assert {str(k):v for k,v in Counter(map(int, counts)).items()} == metric['query_histogram']
        assert int(counts.sum()) == metric['count_sum']

    # General affine API oracle: enumerate all binary records, not error subsets.
    rng = np.random.default_rng(protocol['generic_oracle']['seed'])
    generic = 0; statuses = Counter(); mutations = 0
    for case in range(protocol['generic_oracle']['systems']):
        n = int(rng.integers(3,9)); rows = [int(x) for x in rng.integers(0,1<<n,int(rng.integers(0,n+2)))]
        anchor = int(rng.integers(0,1<<n)); rhs = [parity(r,anchor) for r in rows]
        if case % 10 == 0: rows += [0]; rhs += [1]  # inconsistent base models
        ell = int(rng.integers(0,1<<n)); base = BinaryObservation(n,rows,rhs,ell)
        possible = [a for a in range(1<<n) if all(parity(r,a)==b for r,b in zip(rows,rhs))]
        for trial in range(protocol['generic_oracle']['queries_per_system']):
            indices = list(map(int,rng.permutation(n)[:int(rng.integers(0,n+1))]))
            obs = [(j,int(rng.integers(2))) for j in indices]
            for budget in protocol['generic_oracle']['budgets']:
                rob = BoundedErrorObservation(base,budget)
                report = rob.observe(obs)
                labels = {parity(ell,a) for a in possible if sum(((a>>j)&1)!=y for j,y in obs)<=budget}
                expected = 'conflict' if not labels else 'known' if len(labels)==1 else 'ambiguous'
                assert report['status']==expected and check_certificate(rob,obs,report)
                if expected=='known': assert report['value']==next(iter(labels))
                statuses[expected]+=1;generic+=1
                altered = deepcopy(report); altered['identity']='different-model'
                assert not check_certificate(rob,obs,altered);mutations+=1
                if expected=='known':
                    altered=deepcopy(report);altered['value']^=1
                    assert not check_certificate(rob,obs,altered);mutations+=1
                if report.get('branches'):
                    altered=deepcopy(report);altered['branches'].pop()
                    assert not check_certificate(rob,obs,altered);mutations+=1
    guards=0
    for obs in [[(0,0),(0,0)],[(0,0),(0,1)],[(24,0)],[(0,2)],[(0,0.0)],[(0.0,0)]]:
        try: observer.observe(obs)
        except ValueError: guards+=1
        else: raise AssertionError('missing query guard')
    for budget in [-1,1.5,True]:
        try: BoundedErrorObservation(model,budget)
        except ValueError: guards+=1
        else: raise AssertionError('missing budget guard')
    try: BoundedErrorObservation(model,2,pattern_limit=1).observe([(0,0)])
    except ValueError: guards+=1
    else: raise AssertionError('missing work guard')
    result=dict(protocol_sha256=hashlib.sha256(raw).hexdigest(),independent_flat_assignments=len(code),
                saved_paths_checked=paths_verified,distinct_catalogue_prefixes=len(cache),
                binary_certificates_checked=certificates,bellman_nodes_checked=node_count,
                general_affine_cases=generic,general_statuses=dict(statuses),
                corrupted_certificates_rejected=mutations,invalid_requests_rejected=guards,
                optimal_continuation_depth=5,all_checks_passed=True)
    (OUT/'robust_orientation_verification.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))


if __name__=='__main__': main()
