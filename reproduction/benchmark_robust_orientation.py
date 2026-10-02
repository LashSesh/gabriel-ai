"""Exhaust the saved bounded-error orientation protocol and save all paths."""
from pathlib import Path
import json
import hashlib
import time
from collections import Counter
import numpy as np
from orientation import BinaryObservation, parity, support
from robust_orientation import (BoundedErrorObservation, AnnularErrorPolicy,
                                error_masks, check_certificate)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'results'


def main():
    start = time.perf_counter()
    raw = (OUT / 'robust_orientation_protocol.json').read_bytes()
    protocol = json.loads(raw)
    policy = AnnularErrorPolicy()
    base = BinaryObservation(24, policy.rows, [0] * 12, policy.inner)
    robust = BoundedErrorObservation(base, 1)
    allmask = (1 << 24) - 1
    opposite = [a for a in policy.code if parity(policy.inner, a)]
    minimum = min(a.bit_count() for a in opposite)
    short = [a for a in opposite if a.bit_count() == minimum]
    assert minimum == 3 and len(short) == 12
    assert len({j for a in short for j in support(a)}) == 24
    omissions = []
    for j in range(24):
        pair = next(a for a in short if (a >> j) & 1)
        observed = [k for k in range(24) if k != j]
        y = 1 << next(k for k in support(pair) if k != j)
        obs = [(k, (y >> k) & 1) for k in observed]
        result = robust.observe(obs)
        assert result['status'] == 'ambiguous' and check_certificate(robust, obs, result)
        omissions.append(dict(missing=j, opposite=pair, report=y, observations=obs, certificate=result))

    # Generic exact observer generates replayable orbit representatives.
    faults = list(error_masks(list(range(24)), 1))
    representatives = {}; lexical = {}
    for fault in faults:
        key = str(fault)
        representatives[key] = {}
        for name in ('minimax', 'ec2', 'fixed'):
            result = policy.execute(lambda j: (fault >> j) & 1, name)
            cert = robust.observe(result['observations'])
            assert cert['status'] == 'known' and cert['value'] == 0
            assert check_certificate(robust, result['observations'], cert)
            representatives[key][name] = dict(path=result, certificate=cert)
        obs = []
        for j in range(24):
            obs.append((j, (fault >> j) & 1))
            cert = robust.observe(obs)
            if cert['status'] == 'known': break
        assert cert['value'] == 0 and check_certificate(robust, obs, cert)
        lexical[key] = dict(observations=obs, certificate=cert)
        fullobs = [(j, (fault >> j) & 1) for j in range(24)]
        fullcert = robust.observe(fullobs)
        assert fullcert['status'] == 'known' and fullcert['value'] == 0
        assert check_certificate(robust, fullobs, fullcert)
        representatives[key]['full'] = dict(observations=fullobs, certificate=fullcert)

    # Execute the adaptive policy from report callbacks for EVERY latent/fault pair.
    size = len(policy.code) * len(faults)
    saved = dict(latent=np.repeat(np.array(policy.code, np.uint32), len(faults)),
                 error=np.tile(np.array(faults, np.uint32), len(policy.code)))
    saved['report'] = saved['latent'] ^ saved['error']
    saved['truth'] = np.array([parity(policy.inner, int(a)) for a in saved['latent']], np.uint8)
    metrics = {}
    for name in protocol['policies']:
        paths = np.full((size, 24), -1, np.int8)
        counts = np.empty(size, np.uint8); answers = np.empty(size, np.uint8)
        masks = np.empty(size, np.uint32)
        for k, (latent, error, report) in enumerate(zip(saved['latent'], saved['error'], saved['report'])):
            latent, error, report = int(latent), int(error), int(report)
            if name.startswith('ring_'):
                continuation = name[len('ring_'):]
                result = policy.execute(lambda j: (report >> j) & 1, continuation)
                assert result['status'] == 'known'
                order = [j for j, _ in result['observations']]
                answer = result['value']
            elif name == 'lexical_robust_prefix':
                # Linear translation preserves every robust prefix status; reuse
                # the 25 checked templates, rather than claiming new elimination.
                order = [j for j, _ in lexical[str(error)]['observations']]
                answer = lexical[str(error)]['certificate']['value'] ^ parity(policy.inner, latent)
            else:
                order = list(range(24))
                answer = representatives[str(error)]['full']['certificate']['value'] ^ parity(policy.inner, latent)
            assert len(order) == len(set(order)) and answer == saved['truth'][k]
            paths[k, :len(order)] = order; counts[k] = len(order); answers[k] = answer
            masks[k] = sum(1 << j for j in order)
        saved[name + '_path'] = paths; saved[name + '_count'] = counts
        saved[name + '_answer'] = answers; saved[name + '_mask'] = masks
        clean = saved['error'] == 0
        metrics[name] = dict(cases=size, wrong_known=int(np.count_nonzero(answers != saved['truth'])),
                             unresolved=0, minimum_queries=int(counts.min()),
                             maximum_queries=int(counts.max()), mean_queries=float(counts.mean()),
                             clean_queries=sorted(set(counts[clean].tolist())),
                             count_sum=int(counts.sum()), query_histogram=dict(Counter(map(int, counts))))
    np.savez_compressed(OUT / 'robust_orientation_paths.npz', **saved)

    # Deliberate budget stress: the t=1 interface need not be correct for two errors.
    stress = []; robust2 = BoundedErrorObservation(base, 2)
    for fault in error_masks(list(range(24)), 2):
        if fault.bit_count() != 2: continue
        obs = [(j, (fault >> j) & 1) for j in range(24)]
        one = robust.observe(obs); two = robust2.observe(obs)
        assert check_certificate(robust, obs, one) and check_certificate(robust2, obs, two)
        assert two['status'] != 'conflict'
        if two['status'] == 'known': assert two['value'] == 0
        routed = policy.execute(lambda j: (fault >> j) & 1)
        stress.append(dict(error=fault, one_budget=one, two_budget=two,
                           ring_policy_status=routed['status'], ring_policy_value=routed.get('value'),
                           queries=len(routed['observations'])))
    summary = dict(protocol_sha256=hashlib.sha256(raw).hexdigest(),
                   cases_per_policy=size, policies=metrics, target_distance=minimum,
                   minimum_logical_patterns=len(short), required_fixed_queries=24,
                   ring_prefix_queries=12, continuation_minimax=policy.planner.value(policy.planner.all),
                   bellman_nodes=len(policy.bellman_certificate()['nodes']),
                   stress_two_error_patterns=len(stress),
                   two_budget_status=dict(Counter(r['two_budget']['status'] for r in stress)),
                   one_budget_wrong_full=sum(r['one_budget']['status']=='known' and r['one_budget']['value']!=0 for r in stress),
                   one_budget_wrong_ring=sum(r['ring_policy_status']=='known' and r['ring_policy_value']!=0 for r in stress),
                   seconds=time.perf_counter()-start)
    result = dict(summary=summary, model=dict(n=24, rows=policy.rows, rhs=[0]*12, target=policy.inner),
                  code=policy.code, minimum_patterns=short, omissions=omissions,
                  bellman=policy.bellman_certificate(), representatives=representatives,
                  lexical_representatives=lexical, stress=stress)
    (OUT / 'robust_orientation_results.json').write_text(json.dumps(result, indent=2))
    (OUT / 'robust_orientation_summary.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
