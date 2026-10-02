"""Exact oracle and adversarial checks for target maturity and feedback replay."""
from pathlib import Path
from fractions import Fraction as F
from dataclasses import asdict, replace, FrozenInstanceError
import json, random
from sequential_contract import EventRevision, canonical, identity
from maturity_ledger import TargetRequirement, IssuedForecast, MaturityLedger

ROOT = Path(__file__).resolve().parents[1]


def scorer(prediction, observations):
    if len(observations) == 1:
        y = F(observations[0]['loss'])
    else:
        y = F(observations[1]['value']) - F(observations[0]['value'])
    return {'hit': y > F(prediction['q']), 'loss': str(y)}


def reducer(state, score):
    theta = F(state['theta']) + F(1, 10) * (int(score['hit']) - F(1, 4))
    return {'theta': str(min(F(1, 4), max(-F(1, 4), theta))), 'count': state['count'] + 1}


def forecast(name, origin, horizon, q='1/2', lane='default'):
    return IssuedForecast.create(name, origin, origin + horizon, origin,
        [TargetRequirement('loss', name, origin, origin + horizon)],
        {'q': q}, lane_id=lane, provenance={'contract': identity([name, origin, horizon])})


def outcome(f, receipt, value, revision=0):
    return EventRevision.create('loss', f.forecast_id, revision,
        (f.origin, f.target_end), receipt, 'declared-vintage-' + str(revision), {'loss': str(value)})


def independent_oracle(issued, receipts, event_cutoff, receipt_cutoff):
    """Brute-force histories; no production snapshot/replay/selection helpers."""
    rows = []
    pending = []
    for f in issued:
        if f.issued_at > receipt_cutoff:
            continue
        matched = []
        first_times = []
        for req in f.requirements:
            candidates = [r for r in receipts if r.source_id == req.source_id
                          and r.record_id == req.record_id and r.received_at <= receipt_cutoff
                          and r.event_end <= event_cutoff]
            if not candidates:
                break
            matched.append(max(candidates, key=lambda r: r.revision))
            first_times.append(min(r.received_at for r in candidates))
        if len(matched) != len(f.requirements) or f.target_end > event_cutoff:
            pending.append(f.forecast_id)
            continue
        observations = [json.loads(r.payload_json) for r in matched]
        y = F(observations[0]['loss']) if len(observations) == 1 else F(observations[1]['value']) - F(observations[0]['value'])
        q = F(json.loads(f.prediction_json)['q'])
        order = (max([f.issued_at] + first_times), f.target_end, f.issued_at, f.forecast_id)
        rows.append((order, f, y > q, y))
    rows.sort(key=lambda row: row[0])
    states = {}
    for lane in {f.lane_id for f in issued} | {None}:
        theta, count = F(0), 0
        for _, f, hit, _ in rows:
            if lane is not None and f.lane_id != lane:
                continue
            theta += F(1, 10) * (int(hit) - F(1, 4))
            theta = min(F(1, 4), max(-F(1, 4), theta))
            count += 1
        states[lane] = {'theta': str(theta), 'count': count}
    return rows, tuple(sorted(pending)), states


def run():
    count = {'randomized_histories': 0, 'snapshot_oracle_comparisons': 0,
             'lane_replay_comparisons': 0, 'past_snapshot_immutability_checks': 0,
             'duplicate_issue_checks': 0, 'duplicate_receipt_checks': 0,
             'invalid_input_rejections': 0, 'prefix_nonanticipation_checks': 0}
    rng = random.Random(761390)
    archived_example = None
    for trial in range(160):
        issued = [forecast('f%02d' % i, i, rng.choice([1, 2, 5]),
                          str(F(rng.randrange(-2, 4), 3)), 'lane-' + str(i % 3))
                  for i in range(18)]
        receipts = []
        for f in issued:
            delay = rng.randrange(5)
            t = f.target_end + delay
            receipts.append(outcome(f, t, F(rng.randrange(-3, 6), 4)))
            if rng.randrange(3):
                receipts.append(outcome(f, t + rng.randrange(1, 5), F(rng.randrange(-3, 6), 4), 1))
        # New receipts before issues on ties, as in a causal online learner.
        operations = [(f.issued_at, 1, f.forecast_id, f) for f in issued]
        operations += [(r.received_at, 0, r.record_id + str(r.revision), r) for r in receipts]
        operations.sort(key=lambda x: x[:3])
        ledger = MaturityLedger(scorer, 'exact-indicator-v1')
        retained = []
        seen_f, seen_r = [], []
        for t, kind, _, item in operations:
            if kind:
                assert ledger.issue(item)
                assert not ledger.issue(item)
                count['duplicate_issue_checks'] += 1
                seen_f.append(item)
            else:
                assert ledger.append(item)
                assert not ledger.append(item)
                count['duplicate_receipt_checks'] += 1
                seen_r.append(item)
            snapshot = ledger.snapshot(t, t)
            expected, pending, states = independent_oracle(seen_f, seen_r, t, t)
            assert snapshot.pending == pending
            assert [r.forecast_id for r in snapshot.active] == [r[1].forecast_id for r in expected]
            assert [json.loads(r.score_json) for r in snapshot.active] == [
                {'hit': hit, 'loss': str(y)} for _, _, hit, y in expected]
            assert len({r.forecast_id for r in snapshot.active}) == len(snapshot.active)
            for r in snapshot.active:
                assert r.target_end <= t
                assert all(x.received_at <= t and x.event_end <= t for x in r.evidence)
            count['snapshot_oracle_comparisons'] += 1
            for lane, state in states.items():
                assert snapshot.replay({'theta': '0', 'count': 0}, reducer, lane) == state
                count['lane_replay_comparisons'] += 1
            retained.append((snapshot, snapshot.identity))
        for old, digest in retained:
            assert old.identity == digest and identity(asdict(old)) == digest
            assert ledger.snapshot(old.event_cutoff, old.receipt_cutoff,
                                   old.operation_cutoff).identity == old.identity
            count['past_snapshot_immutability_checks'] += 1
        # Fresh replay of each complete timestamp prefix agrees with full history.
        replay = MaturityLedger(scorer, 'exact-indicator-v1')
        for k, (t, kind, _, item) in enumerate(operations):
            replay.issue(item) if kind else replay.append(item)
            if k == len(operations) - 1 or operations[k+1][0] != t:
                assert replay.snapshot(t, t).identity == ledger.snapshot(t, t, k + 1).identity
                count['prefix_nonanticipation_checks'] += 1
        count['randomized_histories'] += 1
        if trial == 0:
            archived_example = {'final_feedback_identity': snapshot.identity,
                                'forecasts': len(issued), 'received_revisions': len(receipts),
                                'active': len(snapshot.active), 'state': states[None]}

    # Explicit adversarial correction: the original score stays immutable and
    # the controller is replayed with replacement, not appended as target #3.
    ledger = MaturityLedger(scorer, 'exact-indicator-v1')
    f0, f1 = forecast('A', 0, 5), forecast('B', 1, 1)
    ledger.issue(f0); ledger.issue(f1)
    b = outcome(f1, 2, '1')
    ledger.append(b)
    early = ledger.snapshot(2, 2)
    assert early.pending == ('A',) and len(early.active) == 1
    ledger.append(outcome(f0, 7, '0'))
    before = ledger.snapshot(7, 7)
    assert [r.forecast_id for r in before.active] == ['B', 'A']
    ledger.append(outcome(f1, 9, '0', 1))
    after = ledger.snapshot(9, 9)
    assert after.changes_from(before) == (('B', 'revised'),)
    assert before.replay({'theta': '0', 'count': 0}, reducer) == {'theta': '1/20', 'count': 2}
    assert after.replay({'theta': '0', 'count': 0}, reducer) == {'theta': '-1/20', 'count': 2}
    assert len(after.active) == 2 and not ledger.append(b)
    correction_case = {'old_state': before.replay({'theta': '0', 'count': 0}, reducer),
                       'corrected_state': after.replay({'theta': '0', 'count': 0}, reducer),
                       'active_targets': 2, 'retained_receipts': 3,
                       'old_feedback_digest': before.identity, 'new_feedback_digest': after.identity,
                       'changes': after.changes_from(before)}

    # Two raw endpoints: complete event time is insufficient when one endpoint
    # arrives late; a later correction changes the same score's evidence version.
    two = MaturityLedger(scorer, 'exact-indicator-v1')
    f = IssuedForecast.create('endpoint-target', 0, 5, 0,
        [TargetRequirement('price', 'left', 0, 0), TargetRequirement('price', 'right', 5, 5)], {'q': '1'})
    two.issue(f)
    two.append(EventRevision.create('price', 'left', 0, (0, 0), 0, 'v0', {'value': '10'}))
    two.append(EventRevision.create('unrelated', 'x', 0, (5, 5), 5, 'v0', {'value': '500'}))
    assert two.snapshot(5, 5).pending == ('endpoint-target',)
    two.append(EventRevision.create('price', 'right', 0, (5, 5), 8, 'v0', {'value': '12'}))
    assert not two.snapshot(4, 8).active
    assert not two.snapshot(5, 7).active
    got = two.snapshot(5, 8)
    assert got.active[0].first_matured_at == 8
    two.append(EventRevision.create('price', 'left', 1, (0, 0), 10, 'v1', {'value': '11'}))
    corrected = two.snapshot(5, 10)
    assert corrected.active[0].first_matured_at == 8
    assert json.loads(got.active[0].score_json)['hit'] is True
    assert json.loads(corrected.active[0].score_json)['hit'] is False

    def reject(fn):
        try:
            fn()
        except (ValueError, FrozenInstanceError):
            count['invalid_input_rejections'] += 1
        else:
            raise AssertionError('expected invalid input rejection')
    reject(lambda: forecast('past', 2, 0))
    reject(lambda: IssuedForecast.create('late', 0, 5, 5, [TargetRequirement('x','y',0,5)], {'q':'1'}))
    reject(lambda: IssuedForecast.create('float', 0, 5, 0, [TargetRequirement('x','y',0,5)], {'q':0.5}))
    reject(lambda: IssuedForecast.create('no-endpoint',0,5,0,[TargetRequirement('x','y',0,4)], {'q':'1'}))
    reject(lambda: IssuedForecast.create('duplicate',0,5,0,[TargetRequirement('x','y',0,5)]*2,{'q':'1'}))
    reject(lambda: IssuedForecast.create('outside',0,5,0,[TargetRequirement('x','y',-1,5)],{'q':'1'}))
    reject(lambda: ledger.issue(replace(f0, prediction_json=canonical({'q':'2'}))))
    reject(lambda: ledger.issue(forecast('backdate',0,20)))
    reject(lambda: ledger.append(outcome(f0,6,'0',1)))
    reject(lambda: ledger.append(outcome(f0,10,'0',3)))
    reject(lambda: ledger.append(outcome(f0,7,'999',0)))
    reject(lambda: ledger.append(EventRevision.create('loss','A',1,(1,5),10,'v1',{'loss':'0'})))
    reject(lambda: ledger.snapshot(10,10))
    reject(lambda: setattr(f0,'origin',100))
    reject(lambda: before.changes_from(replace(after, scoring_rule_id='different-rule')))
    reject(lambda: MaturityLedger(None,'bad'))
    reject(lambda: MaturityLedger(scorer,''))
    reject(lambda: MaturityLedger(scorer,'ok').snapshot(0,0))
    reject(lambda: after.replay({'theta':'0','count':0},lambda state,score: {'float': 0.5}))

    # Clipping makes updates noncommutative. Appending a revised target to the
    # old state cannot substitute for correction replay.
    state = {'theta': '1/4', 'count': 0}
    first_then_second = reducer(reducer(state, {'hit': True}), {'hit': False})
    second_then_first = reducer(reducer(state, {'hit': False}), {'hit': True})
    assert first_then_second['theta'] != second_then_first['theta']
    result = {'schema':'gabriel.maturity-ledger-checks.v1', 'status':'pass',
              'seed':761390, 'arithmetic':'exact rational test scorer and reducer',
              'checks':count, 'correction_case':correction_case,
              'example':archived_example,
              'noncommutative_example':{'hit_then_miss':first_then_second,
                                       'miss_then_hit':second_then_first},
              'scope':'Declared clocks and pure deterministic scorer/reducer. No authenticated publication timestamps or calibration claim.'}
    (ROOT/'results/maturity_ledger_checks.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__ == '__main__':
    run()
