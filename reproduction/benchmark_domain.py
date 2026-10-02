"""Execute the frozen finite-model mechanism protocol, with complete outputs."""
from pathlib import Path
from dataclasses import asdict
from collections import Counter
from fractions import Fraction
import json
import hashlib
import time
import numpy as np
from flint import arb
from gabriel import Gabriel, Config
from validated_prefix import feature_balls, endpoints
from domain_adapters import transport_records, event_records, build_catalogue
from finite_observation import Planner, Catalogue, Observation, Session, digest

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT/'results'


def validated_labels(records):
    """A fixed diagnostic head; no fit, selection, or prediction-accuracy claim."""
    m = records[0]['inputs'].shape[1]
    g = Gabriel(0, Config(input_dim=m), mode='trace_only')
    w = g.U[:, 0] - g.U[:, 1]  # frozen binary64 coefficients, interpreted exactly
    rows = []
    for record in records:
        u = record['inputs']; scores = []
        for precision in (100, 160):
            f = feature_balls(u, [len(u)], precision)[0][0]
            s = sum((arb(float(a))*b for a,b in zip(w, f[1+m:1+m+48])), arb(0))
            scores.append(s)
        certificate = endpoints([arb(0), scores[0]])
        refined = endpoints([arb(0), scores[1]])
        if certificate['winner'] < 0 or certificate['winner'] != refined['winner']:
            raise RuntimeError('unresolved fixed readout: retain the failed case, do not prune it')
        if not scores[0].contains(scores[1]):
            raise RuntimeError('refined interval not contained')
        g.reset()
        for event in u: g.step(event)
        reference_score = float(w @ g.x)
        if int(reference_score > 0) != certificate['winner']:
            raise RuntimeError('float reference disagrees')
        rows.append(dict(id=record['id'], inputs=u.tolist(), winner=certificate['winner'],
                         reference_score=reference_score, arb100=certificate, arb160=refined))
    parameters = dict(config=asdict(g.config), parents=g.parents.tolist(),
                      base=g.base.tolist(), U=g.U.tolist(), bias=g.bias.tolist(),
                      alpha=g.alpha.tolist(), head=w.tolist(), initial_state='zero')
    return [r['winner'] for r in rows], dict(parameters=parameters, records=rows)


def execute_case(planner, realised_row, policy):
    session = Session(planner)
    path, cost = [], 0
    while session.result()['status'] == 'unresolved':
        q = planner.choice(session.state, policy)
        if q is None: break
        y = realised_row[q]
        cost += planner.c.costs[q]
        # A buffered record is complete by time 100; its retrieval occurs later.
        e = Observation(planner.c.identity, q, y, f'buffer-value-{q}', (0,100), 101+cost)
        session.ingest(e, 101+cost)
        path.append(dict(query=q, outcome=y, state=hex(session.state), cost=cost))
        if len(path) > len(planner.c.query_names): raise RuntimeError('repeated query')
    return dict(path=path, cost=cost, state=hex(session.state), **session.result())


def main():
    protocol_bytes = (RESULTS/'domain_protocol.json').read_bytes()
    protocol = json.loads(protocol_bytes)
    psha = hashlib.sha256(protocol_bytes).hexdigest()
    output = dict(protocol_sha256=psha, scope='exhaustive finite-model mechanism study',
                  point_certificates={}, studies=[], timings={})
    started = time.perf_counter()
    for domain, builder in [('conservative_transport',transport_records),('event_order',event_records)]:
        records, queries = builder()
        model_labels, points = validated_labels(records)
        output['point_certificates'][domain] = points
        input_digest = digest(dict(protocol=psha, points=points))
        for target, labels in [('domain_predicate',[r['label'] for r in records]),
                               ('frozen_gabriel_readout',model_labels)]:
            for nuisance in protocol['nuisance_values']:
                c, physical = build_catalogue(domain, records, queries, nuisance, labels)
                c = Catalogue(c.contract_id+';'+target+';'+input_digest, c.query_names,
                              c.costs, c.rows, c.labels, c.weights)
                small, mapping = c.quotient()
                planner = Planner(small)
                start = time.perf_counter(); worst = planner.value(planner.all)
                seconds = time.perf_counter()-start
                group_physical = [set() for _ in small.rows]
                for raw_id, qid in enumerate(mapping): group_physical[qid].add(physical[raw_id])
                study = dict(domain=domain, target=target, nuisance_values=nuisance,
                             raw_hypotheses=len(c.rows), compressed_hypotheses=len(small.rows),
                             physical_histories=len(records), label_counts=dict(Counter(c.labels)),
                             catalogue=asdict(c), catalogue_digest=c.identity,
                             compressed_digest=small.identity, raw_to_group=mapping,
                             minimax_worst=None if worst == float('inf') else worst,
                             bellman_states=planner.value.cache_info().currsize,
                             planner_seconds=seconds, policies={})
                for policy in protocol['policies']:
                    # Execute every raw case, including aliases. The planner receives
                    # only the outcome of its selected query, never the case index.
                    runs = []
                    for raw_id, realised in enumerate(c.rows):
                        r = execute_case(planner, realised, policy)
                        state = int(r['state'],16)
                        remaining_physical = set().union(*(group_physical[g] for g in planner.members(state)))
                        r.update(case=raw_id, remaining_physical=len(remaining_physical))
                        assert state & (1 << mapping[raw_id])
                        assert r['label'] is None or r['label'] == c.labels[raw_id]
                        runs.append(r)
                    costs = [r['cost'] for r in runs]
                    decided = [r for r in runs if r['status']=='decided']
                    study['policies'][policy] = dict(
                        mean_cost=str(Fraction(sum(costs),len(costs))), worst_cost=max(costs),
                        decided=len(decided), total=len(runs),
                        ambiguous_physical_at_decision=sum(r['remaining_physical']>1 for r in decided),
                        metadata_queries=sum(any(p['query']==len(queries) for p in r['path']) for r in runs),
                        runs=runs)
                assert worst == study['policies']['minimax']['worst_cost']
                output['studies'].append(study)
                print(domain, target, nuisance, 'H',len(c.rows),'quotient',len(small.rows),
                      'costs', {k:v['mean_cost'] for k,v in study['policies'].items()}, flush=True)
    output['timings']['total_seconds'] = time.perf_counter()-started
    (RESULTS/'domain_benchmark.json').write_text(json.dumps(output,indent=2)+'\n')
    print('wrote',RESULTS/'domain_benchmark.json',flush=True)


if __name__=='__main__': main()
