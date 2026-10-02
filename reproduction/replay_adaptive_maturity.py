"""Replay issued 2026 risk forecasts through receipt-causal target maturity.

The exact controller checkpoint is imported from the saved producer before the
first evaluated target in each lane. Earlier learning history is not rebuilt by
this driver. Issued forecasts stay fixed when a synthetic final-endpoint
correction is used to exercise revision-aware state replay.
"""
from pathlib import Path
from fractions import Fraction as F
from dataclasses import asdict
import hashlib, json
import numpy as np

from ecb_risk import load_protocol, load_rates
from sequential_contract import EventRevision, identity
from maturity_ledger import TargetRequirement, IssuedForecast, MaturityLedger

ROOT = Path(__file__).resolve().parents[1]
PRIMARY = 2
DENOMINATOR = 800


def score_outcome(prediction, outcomes):
    if len(outcomes) != 2:
        raise ValueError('both immutable target endpoints required')
    rates = [float.fromhex(x['rate_hex']) for x in outcomes]
    if any(not np.isfinite(x) or x <= 0 for x in rates):
        raise ValueError('positive finite endpoint rates required')
    realized = 100 * np.log(np.float64(rates[1]) / np.float64(rates[0]))
    q = float.fromhex(prediction['var_hex'])
    return {'hit': bool(realized > q), 'realized_log_loss_hex': float(realized).hex()}


def reduce_controller(state, score):
    units = state['theta_units'] + (39 if score['hit'] else -1)
    return {'theta_units': max(-800, min(800, units)), 'updates': state['updates'] + 1}


def endpoint(currency, dates, rates, index, received_at=None, revision=0,
             rate_override=None):
    rate = float(rates[index]) if rate_override is None else float(rate_override)
    return EventRevision.create('ECB-' + currency, str(dates[index]), revision,
        (index, index), index if received_at is None else received_at,
        'current-ECB-snapshot-20260926' if revision == 0 else 'synthetic-correction',
        {'rate_hex': rate.hex(), 'currency': currency,
         'synthetic': revision != 0})


def main():
    protocol = load_protocol()
    dates, rates = load_rates(protocol)
    adaptive_protocol_path = ROOT / 'results/adaptive_risk_protocol.json'
    adaptive_protocol = json.loads(adaptive_protocol_path.read_text())
    assert adaptive_protocol['primary_eta'] == '1/20'
    assert adaptive_protocol['beta'] == '1/40'
    assert adaptive_protocol['theta_bounds'] == ['-1', '1']
    assert adaptive_protocol['source_csv_sha256'] == protocol['source_csv_sha256']
    archive_path = ROOT / 'results/adaptive_risk_predictions.npz'
    archive = np.load(archive_path, allow_pickle=False)
    assert np.array_equal(archive['dates'], dates)
    assert np.array_equal(archive['rates'], rates)
    assert int(archive['eta_denominators'][PRIMARY]) == DENOMINATOR
    assert str(archive['eta_grid'][PRIMARY]) == '1/20'
    protocol_hash = hashlib.sha256(adaptive_protocol_path.read_bytes()).hexdigest()
    run_results, correction_results = [], []
    totals = {'issued_forecasts': 0, 'matured_targets': 0, 'exact_hit_comparisons': 0,
              'exact_preupdate_state_comparisons': 0, 'exact_postupdate_state_comparisons': 0,
              'exact_issue_state_comparisons': 0, 'pending_after_issue_checks': 0,
              'synthetic_correction_cases': 0, 'duplicate_receipt_rejections_or_noops': 0,
              'old_snapshot_reconstruction_checks': 0}
    for currency_index, currency in enumerate(protocol['currencies']):
        for horizon in protocol['horizons_observed_intervals']:
            key = '%s_%d_' % (currency, horizon)
            origins = archive[key + 'origins']
            selected = np.flatnonzero((dates[origins] >= '2026-01-01') &
                                     archive[key + 'matured'] &
                                     (dates[np.minimum(origins + horizon, len(dates)-1)] <= '2026-09-25'))
            assert len(selected) and np.all(dates[origins[selected] + horizon] >= '2026-01-01')
            row_by_origin = {int(origins[k]): int(k) for k in selected}
            start, end = min(row_by_origin), max(row_by_origin) + horizon
            lane_checkpoints = {}
            for origin, row in row_by_origin.items():
                lane = str(origin % horizon)
                lane_checkpoints.setdefault(lane, {'theta_units': int(archive[key + 'lane_issued_units'][row, PRIMARY]),
                                                   'updates': 0})
            source_rates = rates[:, currency_index]
            ledger = MaturityLedger(score_outcome, 'binary64-upper-loss-hit-primary-v1',
                                    'historical_replay_without_vintages')
            issued_objects, saved_rows, updates = {}, {}, []
            snapshot = None
            for index in range(start, end + 1):
                record = endpoint(currency, dates, source_rates, index)
                ledger.append(record)
                snapshot = ledger.snapshot(index, index)
                mature_origin = index - horizon
                if mature_origin in row_by_origin:
                    row = row_by_origin[mature_origin]
                    forecast_id = '%s-h%d-o%d' % (currency, horizon, mature_origin)
                    lane = str(mature_origin % horizon)
                    mature = next(r for r in snapshot.active if r.forecast_id == forecast_id)
                    payload = json.loads(mature.score_json)
                    archived_hit = int(archive[key + 'lane_matured_hit'][row, PRIMARY])
                    assert int(payload['hit']) == archived_hit
                    totals['exact_hit_comparisons'] += 1
                    active_before = [r for r in snapshot.active if r.lane_id == lane and r.forecast_id != forecast_id]
                    manual_before = dict(lane_checkpoints[lane])
                    for score in active_before:
                        manual_before = reduce_controller(manual_before, json.loads(score.score_json))
                    assert manual_before['theta_units'] == int(archive[key + 'lane_preupdate_units'][row, PRIMARY])
                    totals['exact_preupdate_state_comparisons'] += 1
                    replayed = snapshot.replay(lane_checkpoints[lane], reduce_controller, lane)
                    assert replayed['theta_units'] == int(archive[key + 'lane_postupdate_units'][row, PRIMARY])
                    totals['exact_postupdate_state_comparisons'] += 1
                    totals['matured_targets'] += 1
                    updates.append({'origin_index': mature_origin, 'target_end_index': index,
                                    'lane': lane, 'hit': archived_hit,
                                    'preupdate_units': manual_before['theta_units'],
                                    'postupdate_units': replayed['theta_units'],
                                    'feedback_score_digest': mature.identity})
                if index in row_by_origin:
                    row = row_by_origin[index]
                    lane = str(index % horizon)
                    replayed = snapshot.replay(lane_checkpoints[lane], reduce_controller, lane)
                    issued_units = int(archive[key + 'lane_issued_units'][row, PRIMARY])
                    assert replayed['theta_units'] == issued_units
                    totals['exact_issue_state_comparisons'] += 1
                    forecast_id = '%s-h%d-o%d' % (currency, horizon, index)
                    requirements = [TargetRequirement('ECB-' + currency, str(dates[t]), t, t)
                                    for t in (index, index + horizon)]
                    prediction = {'var_hex': float(archive[key + 'lane_var'][row, PRIMARY]).hex(),
                                  'es_hex': float(archive[key + 'lane_es'][row, PRIMARY]).hex(),
                                  'theta_units': issued_units, 'theta_unit_denominator': DENOMINATOR}
                    issued = IssuedForecast.create(forecast_id, index, index + horizon, index,
                        requirements, prediction, lane_id=lane,
                        provenance={'adaptive_protocol_sha256': protocol_hash,
                                    'source_csv_sha256': protocol['source_csv_sha256'],
                                    'availability_mode': 'historical_replay_without_vintages',
                                    'checkpoint': lane_checkpoints[lane]})
                    ledger.issue(issued)
                    snapshot = ledger.snapshot(index, index)
                    assert forecast_id in snapshot.pending
                    assert forecast_id not in {r.forecast_id for r in snapshot.active}
                    totals['pending_after_issue_checks'] += 1
                    totals['issued_forecasts'] += 1
                    issued_objects[forecast_id] = issued
                    saved_rows[forecast_id] = row
            assert snapshot is not None and not snapshot.pending
            assert len(snapshot.active) == len(selected)
            final_states = {lane: snapshot.replay(state, reduce_controller, lane)
                            for lane, state in lane_checkpoints.items()}
            run_results.append({'currency': currency, 'horizon': horizon,
                                'first_origin': str(dates[start]), 'last_endpoint': str(dates[end]),
                                'count': len(selected), 'lane_checkpoints': lane_checkpoints,
                                'final_lane_states': final_states, 'feedback_digest': snapshot.identity,
                                'updates': updates})

            # Each final endpoint is used by exactly one retained target: there
            # is no retained forecast originating there with a later endpoint.
            old_snapshot, old_digest = snapshot, snapshot.identity
            forecast_id = '%s-h%d-o%d' % (currency, horizon, end-horizon)
            old_score = next(r for r in snapshot.active if r.forecast_id == forecast_id)
            old_hit = json.loads(old_score.score_json)['hit']
            issued = issued_objects[forecast_id]
            q = float.fromhex(json.loads(issued.prediction_json)['var_hex'])
            desired_loss = q - 1.0 if old_hit else q + 1.0
            corrected_rate = float(source_rates[end-horizon]) * float(np.exp(desired_loss / 100))
            corrected_receipt = endpoint(currency, dates, source_rates, end,
                received_at=end+1, revision=1, rate_override=corrected_rate)
            ledger.append(corrected_receipt)
            assert not ledger.append(corrected_receipt)
            totals['duplicate_receipt_rejections_or_noops'] += 1
            corrected = ledger.snapshot(end, end+1)
            changes = corrected.changes_from(old_snapshot)
            assert changes == ((forecast_id, 'revised'),)
            new_score = next(r for r in corrected.active if r.forecast_id == forecast_id)
            assert json.loads(new_score.score_json)['hit'] != old_hit
            assert old_score.first_matured_at == new_score.first_matured_at
            assert len(corrected.active) == len(old_snapshot.active)
            assert identity(asdict(old_snapshot)) == old_digest
            assert ledger.snapshot(end, end, old_snapshot.operation_cutoff).identity == old_digest
            assert all(issued_objects[f.forecast_id].identity == f.identity for f in ledger.forecasts)
            totals['old_snapshot_reconstruction_checks'] += 1
            corrected_states = {lane: corrected.replay(state, reduce_controller, lane)
                                for lane, state in lane_checkpoints.items()}
            # Independent integer replay of archived hits with just the final
            # retained target's outcome replaced. No production score reducer.
            manual_states = {lane: dict(state) for lane, state in lane_checkpoints.items()}
            for row in selected:
                origin = int(origins[row]); lane = str(origin % horizon)
                hit = int(archive[key + 'lane_matured_hit'][row, PRIMARY])
                if origin == end-horizon:
                    hit = int(not old_hit)
                val = manual_states[lane]['theta_units'] + (39 if hit else -1)
                manual_states[lane]['theta_units'] = min(800, max(-800, val))
                manual_states[lane]['updates'] += 1
            assert corrected_states == manual_states
            assert corrected_states != final_states
            assert sum(v['updates'] for v in corrected_states.values()) == len(selected)
            totals['synthetic_correction_cases'] += 1
            correction_results.append({'currency': currency, 'horizon': horizon,
                                       'synthetic_endpoint_rate_hex': corrected_rate.hex(),
                                       'changed_forecast': forecast_id, 'old_hit': old_hit,
                                       'new_hit': not old_hit, 'active_targets_before': len(old_snapshot.active),
                                       'active_targets_after': len(corrected.active),
                                       'old_lane_states': final_states, 'corrected_lane_states': corrected_states,
                                       'old_feedback_digest': old_digest, 'corrected_feedback_digest': corrected.identity,
                                       'old_snapshot_unchanged': True, 'issued_forecasts_unchanged': True})
    result = {'schema': 'gabriel.adaptive-maturity-replay.v1', 'status': 'pass',
              'adaptive_protocol_sha256': protocol_hash,
              'source_csv_sha256': protocol['source_csv_sha256'],
              'forecast_archive_sha256': hashlib.sha256(archive_path.read_bytes()).hexdigest(),
              'period': ['2026-01-01', '2026-09-25'],
              'endpoint_rule': 'origin and target endpoint both inside period',
              'controller': {'eta': '1/20', 'beta': '1/40', 'unit': '1/800', 'bounds_units': [-800,800]},
              'availability_mode': 'historical_replay_without_vintages',
              'checkpoint_scope': 'Import saved exact state at first retained forecast per lane; earlier learning history is not rebuilt here.',
              'correction_scope': 'Eight synthetic final-endpoint corrections in separate replay copies. Recompute current learner state while preserving all originally issued forecasts; no historical refitting or measured vintage claim.',
              'checks': totals, 'runs': run_results, 'synthetic_corrections': correction_results}
    (ROOT / 'results/adaptive_maturity_replay.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({'status': result['status'], 'checks': totals}, indent=2))


if __name__ == '__main__':
    main()
