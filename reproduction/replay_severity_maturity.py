"""Receipt-causal replay of fixed issued quantiles and discounted tail severity.

The checkpoint imports the raw pooled accumulator immediately before the first
2026 receipt update and retains the h already-issued pending targets. The bridge
therefore reconstructs every retained 2026 issue and maturity update, including
cross-year boundary feedback, without recomputing past forecasts. All severity
arithmetic is ordinary binary64, checked with explicit tolerances.
"""
from pathlib import Path
from dataclasses import asdict
import hashlib, json, math
import numpy as np

from ecb_risk import load_protocol, load_rates
from severity_risk import load_protocol as load_severity_protocol
from sequential_contract import EventRevision, identity
from maturity_ledger import TargetRequirement, IssuedForecast, MaturityLedger
from severity_correction import correct_discounted_score, severity_readout

ROOT = Path(__file__).resolve().parents[1]
ATOL = 1e-11
RTOL = 1e-11


def score_severity(prediction, outcomes):
    if len(outcomes) != 2:
        raise ValueError('two immutable target endpoint records required')
    rates = [float.fromhex(x['rate_hex']) for x in outcomes]
    q = float.fromhex(prediction['var_hex'])
    if not all(np.isfinite(x) and x > 0 for x in rates + [q]):
        raise ValueError('positive finite rates and issued quantile required')
    y = float(100 * np.log(np.float64(rates[1]) / np.float64(rates[0])))
    r = 1.0 + max(y - q, 0.0) / ((1.0 / 40.0) * q)
    return {'realized_log_loss_hex': y.hex(), 'severity_R_hex': r.hex()}


def reducer(decay):
    def step(state, score):
        old = float.fromhex(state['raw_m_hex'])
        r = float.fromhex(score['severity_R_hex'])
        new = decay * old + (1.0 - decay) * r
        return {'raw_m_hex': new.hex(), 'updates': state['updates'] + 1}
    return step


def endpoint(currency, dates, rates, index, received_at=None, revision=0, rate_override=None):
    rate = float(rates[index]) if rate_override is None else float(rate_override)
    return EventRevision.create('ECB-' + currency, str(dates[index]), revision,
        (index, index), index if received_at is None else received_at,
        'current-ECB-snapshot-20260926' if revision == 0 else 'synthetic-correction',
        {'rate_hex': rate.hex(), 'currency': currency, 'synthetic': revision != 0})


def main():
    parent = load_protocol()
    dates, rates = load_rates(parent)
    protocol_path = ROOT / 'results/severity_risk_protocol.json'
    protocol = load_severity_protocol()
    assert protocol['beta'] == '1/40' and protocol['primary_half_life'] == 125
    assert protocol['half_lives_completed_observations'] == [125, 500]
    protocol_hash = hashlib.sha256(protocol_path.read_bytes()).hexdigest()
    archive_path = ROOT / 'results/severity_risk_predictions.npz'
    archive = np.load(archive_path, allow_pickle=False)
    assert np.array_equal(archive['dates'], dates) and np.array_equal(archive['rates'], rates)
    archive_hash = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    decay = float(archive['decays'][0])
    assert math.isclose(decay, 2 ** (-1 / 125), rel_tol=1e-15, abs_tol=0)
    step = reducer(decay)
    totals = dict(retained_2026_targets=0, boundary_context_targets=0, issued_records=0,
                  retained_issue_state_comparisons=0, retained_preupdate_comparisons=0,
                  retained_postupdate_comparisons=0, retained_R_comparisons=0,
                  boundary_preupdate_comparisons=0, boundary_postupdate_comparisons=0,
                  synthetic_correction_cases=0, old_snapshot_reconstruction_checks=0, same_position_score_substitutions=0,
                  fast_correction_full_replay_comparisons=0, fast_correction_cap_matches=0)
    errors = {k: 0.0 for k in ('issued_m','preupdate_m','postupdate_m','R','correction_replay','correction_linear_identity','score_substitution')}
    runs, corrections, score_substitutions = [], [], []

    def compare(got, wanted, category):
        got, wanted = float(got), float(wanted)
        if not np.isfinite([got,wanted]).all() or not math.isclose(got,wanted,abs_tol=ATOL,rel_tol=RTOL):
            raise AssertionError((category, got, wanted))
        errors[category] = max(errors[category], abs(got - wanted))

    for ci, currency in enumerate(protocol['market']['currencies']):
        for horizon in protocol['market']['horizons']:
            key = '%s_%d_' % (currency, horizon)
            origins = archive[key + 'origins']
            matured = archive[key + 'matured']
            selected = np.flatnonzero((dates[origins] >= '2026-01-01') & matured &
                (dates[np.minimum(origins+horizon,len(dates)-1)] <= '2026-09-25'))
            assert len(selected)
            retained_origins = {int(origins[row]): int(row) for row in selected}
            start, end = min(retained_origins), max(retained_origins) + horizon
            all_rows = {int(origin): i for i,origin in enumerate(origins)}
            boundary_origins = list(range(start-horizon,start))
            assert all(o in all_rows for o in boundary_origins)
            assert all(str(dates[o]) < '2026-01-01' for o in boundary_origins)
            source_rates = rates[:,ci]
            for stream, model in enumerate(('severity_125','joint_125')):
                first_boundary_row = all_rows[start-horizon]
                initial_m = float(archive[key+'candidate_preupdate_ratio'][first_boundary_row,stream,0])
                initial_state = {'raw_m_hex': initial_m.hex(), 'updates': 0}
                checkpoint = {'raw_m_hex': initial_m.hex(), 'effective_before_receipt_index': start,
                              'effective_before_receipt_date': str(dates[start]),
                              'imported_producer_row_origin': start-horizon,
                              'pending_origins': boundary_origins,
                              'source_archive_sha256': archive_hash}
                ledger = MaturityLedger(score_severity, 'binary64-issued-quantile-severity-v1',
                                        'historical_replay_without_vintages')
                issued_objects, updates = {}, []

                def issue(origin, is_boundary):
                    row = all_rows[origin]
                    fid = '%s-h%d-%s-o%d' % (currency,horizon,model,origin)
                    requirements = [TargetRequirement('ECB-'+currency,str(dates[t]),t,t)
                                    for t in (origin,origin+horizon)]
                    prediction = {'var_hex': float(archive[key+'q_streams'][row,stream]).hex(),
                                  'es_hex': float(archive[key+'candidate_es'][row,stream,0]).hex(),
                                  'issued_raw_m_hex': float(archive[key+'candidate_issued_raw_ratio'][row,stream,0]).hex(),
                                  'boundary_context': is_boundary}
                    issued = IssuedForecast.create(fid,origin,origin+horizon,origin,requirements,prediction,
                        lane_id='pooled',provenance={'source_csv_sha256': parent['source_csv_sha256'],
                                                   'severity_protocol_sha256': protocol_hash,
                                                   'forecast_archive_sha256': archive_hash})
                    ledger.issue(issued)
                    issued_objects[fid] = issued
                    totals['issued_records'] += 1
                    return fid

                # These are already-issued pending forecasts at the effective
                # checkpoint; imported values are not regenerated from that state.
                for origin in boundary_origins:
                    ledger.append(endpoint(currency,dates,source_rates,origin))
                    issue(origin,True)
                previous = ledger.snapshot(start-1,start-1)
                assert not previous.active and len(previous.pending) == horizon
                totals['boundary_context_targets'] += horizon
                for index in range(start,end+1):
                    before = previous.replay(initial_state,step)
                    origin = index-horizon
                    row = all_rows[origin]
                    is_retained = origin in retained_origins
                    # Exactly one pending or retained target matures per receipt.
                    compare(float.fromhex(before['raw_m_hex']),
                            archive[key+'candidate_preupdate_ratio'][row,stream,0],'preupdate_m')
                    totals['retained_preupdate_comparisons' if is_retained else 'boundary_preupdate_comparisons'] += 1
                    ledger.append(endpoint(currency,dates,source_rates,index))
                    snap = ledger.snapshot(index,index)
                    fid = '%s-h%d-%s-o%d' % (currency,horizon,model,origin)
                    score = next(s for s in snap.active if s.forecast_id == fid)
                    observed_R = float.fromhex(json.loads(score.score_json)['severity_R_hex'])
                    compare(observed_R,archive[key+'R'][row,stream],'R')
                    if is_retained:
                        totals['retained_R_comparisons'] += 1
                        totals['retained_2026_targets'] += 1
                    after = snap.replay(initial_state,step)
                    compare(float.fromhex(after['raw_m_hex']),
                            archive[key+'candidate_postupdate_ratio'][row,stream,0],'postupdate_m')
                    totals['retained_postupdate_comparisons' if is_retained else 'boundary_postupdate_comparisons'] += 1
                    updates.append({'origin_index':origin,'target_end_index':index,
                                    'boundary_context':not is_retained,'R_hex':observed_R.hex(),
                                    'preupdate_raw_m_hex':before['raw_m_hex'],
                                    'postupdate_raw_m_hex':after['raw_m_hex'],
                                    'score_digest':score.identity})
                    if index in retained_origins:
                        row_at_issue = retained_origins[index]
                        compare(float.fromhex(after['raw_m_hex']),
                                archive[key+'candidate_issued_raw_ratio'][row_at_issue,stream,0],'issued_m')
                        totals['retained_issue_state_comparisons'] += 1
                        new_id = issue(index,False)
                        snap = ledger.snapshot(index,index)
                        assert new_id in snap.pending and new_id not in {r.forecast_id for r in snap.active}
                    previous = snap
                old_snapshot = previous
                assert not old_snapshot.pending and len(old_snapshot.active) == len(selected)+horizon
                old_state = old_snapshot.replay(initial_state,step)
                old_digest = old_snapshot.identity
                N = len(old_snapshot.active)
                initial_mass = decay ** N
                empirical_mass = -math.expm1(N*math.log(decay))
                assert math.isclose(initial_mass+empirical_mass,1.0,abs_tol=1e-14)
                runs.append({'currency':currency,'horizon':horizon,'model':model,
                             'retained_count':len(selected),'boundary_count':horizon,
                             'checkpoint':checkpoint,'updates':updates,'final_state':old_state,
                             'kernel_initial_mass':initial_mass,'kernel_real_update_mass':empirical_mass,
                             'feedback_digest':old_digest})

                # Isolate same-position score revision independently of raw
                # endpoints: an interior price can change two overlapping losses.
                R_values = [float.fromhex(update['R_hex']) for update in updates]
                old_m = float.fromhex(old_state['raw_m_hex'])
                for position in sorted({1,(N+1)//2,N}):
                    original_R = R_values[position-1]
                    weight = (1-decay)*decay**(N-position)
                    alternatives = [('increase',original_R+7.0),('decrease',1.0),
                                    ('force_cap',original_R+25.0/weight)]
                    for mode,new_R in alternatives:
                        quick = correct_discounted_score(old_m,decay,N,position,original_R,new_R)
                        direct = initial_m
                        for index,rr in enumerate(R_values,start=1):
                            direct = decay*direct+(1-decay)*(new_R if index == position else rr)
                        compare(quick,direct,'score_substitution')
                        quick_out, direct_out = severity_readout(quick),severity_readout(direct)
                        assert quick_out['lower_cap_active'] == direct_out['lower_cap_active']
                        assert quick_out['upper_cap_active'] == direct_out['upper_cap_active']
                        compare(quick_out['ratio'],direct_out['ratio'],'score_substitution')
                        if mode == 'force_cap':
                            assert quick_out['upper_cap_active'] and quick_out['ratio'] == 20.0
                        totals['same_position_score_substitutions'] += 1
                        totals['fast_correction_full_replay_comparisons'] += 1
                        totals['fast_correction_cap_matches'] += 1
                        score_substitutions.append({'currency':currency,'horizon':horizon,'model':model,
                            'position':position,'update_count':N,'mode':mode,
                            'old_R_hex':original_R.hex(),'new_R_hex':new_R.hex(),
                            'correction_raw_m_hex':quick.hex(),'full_replay_raw_m_hex':direct.hex(),
                            'ratio':quick_out['ratio'],'upper_cap_active':quick_out['upper_cap_active'],
                            'unchanged_kernel_weight':weight,
                            'full_replay_state_updates':N,'correction_power_evaluations':1})

                # Last endpoint participates in exactly one retained target.
                last_origin = end-horizon
                last_id = '%s-h%d-%s-o%d' % (currency,horizon,model,last_origin)
                old_record = next(s for s in old_snapshot.active if s.forecast_id == last_id)
                old_payload = json.loads(old_record.score_json)
                old_y = float.fromhex(old_payload['realized_log_loss_hex'])
                old_R = float.fromhex(old_payload['severity_R_hex'])
                q = float.fromhex(json.loads(issued_objects[last_id].prediction_json)['var_hex'])
                desired_loss = max(q,old_y)+max(q,1.0)
                corrected_rate = float(source_rates[last_origin])*float(np.exp(desired_loss/100))
                late_record = endpoint(currency,dates,source_rates,end,received_at=end+1,revision=1,
                                       rate_override=corrected_rate)
                ledger.append(late_record)
                assert not ledger.append(late_record)
                revised = ledger.snapshot(end,end+1)
                assert revised.changes_from(old_snapshot) == ((last_id,'revised'),)
                assert len(revised.active) == N
                new_record = next(s for s in revised.active if s.forecast_id == last_id)
                new_R = float.fromhex(json.loads(new_record.score_json)['severity_R_hex'])
                assert new_R > old_R and new_record.first_matured_at == old_record.first_matured_at
                new_state = revised.replay(initial_state,step)
                assert new_state['updates'] == old_state['updates'] == N
                manual = initial_m
                for update in updates:
                    rr = new_R if update['origin_index'] == last_origin else float.fromhex(update['R_hex'])
                    manual = decay*manual+(1-decay)*rr
                compare(float.fromhex(new_state['raw_m_hex']),manual,'correction_replay')
                predicted = float.fromhex(old_state['raw_m_hex'])+(1-decay)*(new_R-old_R)
                compare(float.fromhex(new_state['raw_m_hex']),predicted,'correction_linear_identity')
                assert new_state['raw_m_hex'] != old_state['raw_m_hex']
                assert identity(asdict(old_snapshot)) == old_digest
                assert ledger.snapshot(end,end,old_snapshot.operation_cutoff).identity == old_digest
                assert all(issued_objects[f.forecast_id].identity == f.identity for f in ledger.forecasts)
                totals['synthetic_correction_cases'] += 1
                totals['old_snapshot_reconstruction_checks'] += 1
                corrections.append({'currency':currency,'horizon':horizon,'model':model,
                                    'target':last_id,'old_R_hex':old_R.hex(),'new_R_hex':new_R.hex(),
                                    'synthetic_endpoint_rate_hex':corrected_rate.hex(),
                                    'old_state':old_state,'corrected_state':new_state,
                                    'active_count_before':N,'active_count_after':N,
                                    'kernel_weights_unchanged':True,'issued_forecasts_unchanged':True,
                                    'old_snapshot_unchanged':True,'old_feedback_digest':old_digest,
                                    'corrected_feedback_digest':revised.identity})
    result = {'schema':'gabriel.severity-maturity-replay.v1','status':'pass',
              'severity_protocol_sha256':protocol_hash,'forecast_archive_sha256':archive_hash,
              'source_csv_sha256':parent['source_csv_sha256'],
              'models':['severity_125','joint_125'],'half_life':125,'decay_hex':decay.hex(),
              'period':['2026-01-01','2026-09-25'],'endpoint_rule':'Both endpoints in period for retained targets; preceding pending targets are explicit boundary context.',
              'availability_mode':'historical_replay_without_vintages',
              'arithmetic':{'type':'ordinary binary64; no interval-rounding certificate','absolute_tolerance':ATOL,'relative_tolerance':RTOL},
              'checkpoint_scope':'Raw pooled producer state immediately before the first 2026 receipt plus h already-issued pending targets. Earlier history is imported, not independently regenerated.',
              'correction_scope':'Synthetic final-endpoint revisions alter one current feedback score each. Current-state replay preserves original issued forecasts and kernel weights; it does not refit historical forecasts or claim measured ECB revision events.',
              'count_semantics':'Counts sum forecast-target pairs over two quantile streams: 2960 retained pairs represent 1480 distinct currency-horizon targets; 48 boundary pairs represent 24 distinct boundary targets.',
              'checks':totals,'max_absolute_discrepancies':errors,'runs':runs,'synthetic_corrections':corrections,'synthetic_score_substitutions':score_substitutions,
              'correction_cost_scope':'One power evaluation and a fixed number of scalar arithmetic operations per stored-score substitution versus N recurrence updates for full replay. No wall-clock or bit-complexity comparison.'}
    (ROOT/'results/severity_maturity_replay.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'status':result['status'],'count_semantics':'Counts sum forecast-target pairs over two quantile streams: 2960 retained pairs represent 1480 distinct currency-horizon targets; 48 boundary pairs represent 24 distinct boundary targets.',
              'checks':totals,'max_absolute_discrepancies':errors},indent=2))


if __name__ == '__main__':
    main()
