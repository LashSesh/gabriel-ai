"""Host a bounded, already evaluated historical risk slice without refitting.

Eight interleaved contracts share one SQLite owner. Each imports the first 16
matured 2026 forecasts from the existing four-currency archive and the exact
per-lane state at its first imported issue. Earlier learning, historical source
vintages and authenticated issue times are outside this replay claim.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gabriel_runtime import Store, canonical, digest
from gabriel_runtime.adapters import MaturityRiskAdapter

CURRENCIES = ('USD', 'GBP', 'JPY', 'CHF')
HORIZONS = (1, 5)
PER_CONTRACT = 16
PRIMARY = 2


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    started = time.monotonic()
    archive_path = ROOT / 'results/adaptive_risk_predictions.npz'
    protocol_path = ROOT / 'results/adaptive_risk_protocol.json'
    parent_path = ROOT / 'results/ecb_risk_protocol.json'
    protocol = json.loads(protocol_path.read_text())
    parent = json.loads(parent_path.read_text())
    require(tuple(protocol['currencies']) == CURRENCIES, 'unexpected currency order')
    require(tuple(protocol['horizons_observed_intervals']) == HORIZONS, 'unexpected horizons')
    require(protocol['primary_eta'] == '1/20' and protocol['beta'] == '1/40', 'controller changed')
    require(protocol['theta_bounds'] == ['-1', '1'], 'controller bounds changed')
    require(protocol['source_csv_sha256'] == parent['source_csv_sha256'], 'source provenance mismatch')
    require(protocol['parent_protocol_sha256'] == sha(parent_path), 'parent protocol changed')
    sources = {
        'results/adaptive_risk_predictions.npz': sha(archive_path),
        'results/adaptive_risk_protocol.json': sha(protocol_path),
        'results/ecb_risk_protocol.json': sha(parent_path),
        'reproduction/replay_runtime_history.py': sha(__file__),
    }
    checks = dict(issued_forecasts=0, matured_targets=0,
                  exact_prediction_pair_checks=0, exact_hit_comparisons=0,
                  exact_issue_state_comparisons=0, exact_preupdate_state_comparisons=0,
                  exact_postupdate_state_comparisons=0, pending_after_issue_checks=0,
                  final_controller_update_count_checks=0, reopened_view_checks=0,
                  saved_command_replay_view_checks=0)
    registry = {'maturity-risk/v1': MaturityRiskAdapter()}
    fingerprint = registry['maturity-risk/v1'].fingerprint()
    contracts = []
    with np.load(archive_path, allow_pickle=False) as archive:
        dates, rates = archive['dates'], archive['rates']
        require(rates.shape == (len(dates), len(CURRENCIES)), 'archive is not the four-currency source')
        require(str(archive['eta_grid'][PRIMARY]) == '1/20', 'wrong archived controller column')
        require(int(archive['eta_denominators'][PRIMARY]) == 800, 'wrong state unit denominator')
        for column, currency in enumerate(CURRENCIES):
            for horizon in HORIZONS:
                key = f'{currency}_{horizon}_'
                origins = archive[key + 'origins']
                matured = archive[key + 'matured']
                selected = np.flatnonzero((dates[origins] >= '2026-01-01') & matured &
                    (dates[np.minimum(origins + horizon, len(dates) - 1)] <= '2026-09-25'))[:PER_CONTRACT]
                require(len(selected) == PER_CONTRACT, 'insufficient already evaluated forecasts')
                selected_origins = origins[selected]
                require(np.all(np.diff(selected_origins) == 1), 'retained slice must be consecutive')
                rows = {int(origins[row]): int(row) for row in selected}
                checkpoints = {}
                for origin, row in rows.items():
                    checkpoints.setdefault(str(origin % horizon), {
                        'theta_units': int(archive[key + 'lane_issued_units'][row, PRIMARY]),
                        'updates': 0})
                contracts.append(dict(id=f'history-{currency}-h{horizon}', currency=currency,
                    horizon=horizon, column=column, key=key, rows=rows,
                    start=min(rows), end=max(rows) + horizon, checkpoints=checkpoints,
                    updates=[]))

        start, end = min(c['start'] for c in contracts), max(c['end'] for c in contracts)
        commands, views = [], {}
        with tempfile.TemporaryDirectory(prefix='gabriel_runtime_history_') as temporary:
            database = Path(temporary) / 'history.sqlite'
            with Store.create(database, registry) as store:
                def submit(contract, operation, at, payload):
                    command = {'id': f'history-{len(commands) + 1:04d}',
                               'contract': contract['id'], 'op': operation,
                               'at': at, 'expected_head': store.head, 'payload': payload}
                    receipt = store.submit(command)
                    commands.append(command)
                    result = receipt['result']
                    if operation == 'bind':
                        views[contract['id']] = result
                    else:
                        require(result['accepted'] is True, 'historical native operation was not accepted')
                        views[contract['id']] = result['view']
                    return views[contract['id']]

                for c in contracts:
                    submit(c, 'bind', start, {'adapter': 'maturity-risk/v1', 'config': {
                        'scoring_rule_id': 'binary64-upper-loss-hit-primary-v1',
                        'availability_mode': 'historical_replay_without_vintages',
                        'initial_states': c['checkpoints']}})

                # At each original observation index, completed endpoints arrive
                # before new issues. This is the order of the previous driver.
                for index in range(start, end + 1):
                    for c in contracts:
                        if not c['start'] <= index <= c['end']:
                            continue
                        before = views[c['id']]['controller_states']
                        view = submit(c, 'outcome', index, {
                            'source_id': 'ECB-' + c['currency'], 'record_id': str(dates[index]),
                            'revision': 0, 'event_interval': [index, index], 'received_at': index,
                            'vintage_id': 'current-ECB-snapshot-20260926',
                            'payload': {'rate_hex': float(rates[index, c['column']]).hex()}})
                        origin = index - c['horizon']
                        if origin in c['rows']:
                            row = c['rows'][origin]
                            lane = str(origin % c['horizon'])
                            forecast_id = f"{c['currency']}-h{c['horizon']}-o{origin}"
                            score = next(x for x in view['feedback']['active']
                                         if x['forecast_id'] == forecast_id)
                            payload = json.loads(score['score_json'])
                            archived_hit = int(archive[c['key'] + 'lane_matured_hit'][row, PRIMARY])
                            pre = int(archive[c['key'] + 'lane_preupdate_units'][row, PRIMARY])
                            post = int(archive[c['key'] + 'lane_postupdate_units'][row, PRIMARY])
                            require(int(payload['hit']) == archived_hit, 'archived hit changed')
                            require(before[lane]['theta_units'] == pre, 'archived preupdate state changed')
                            require(view['controller_states'][lane]['theta_units'] == post,
                                    'archived postupdate state changed')
                            # Independent integer update, outside the adapter.
                            require(post == min(800, max(-800, pre + (39 if archived_hit else -1))),
                                    'archived clipped update is inconsistent')
                            c['updates'].append({'origin_index': origin, 'target_end_index': index,
                                'lane': lane, 'hit': archived_hit, 'preupdate_units': pre,
                                'postupdate_units': post, 'realized_log_loss_hex': payload['realized_log_loss_hex']})
                            for name in ('matured_targets', 'exact_hit_comparisons',
                                         'exact_preupdate_state_comparisons', 'exact_postupdate_state_comparisons'):
                                checks[name] += 1

                    for c in contracts:
                        if index not in c['rows']:
                            continue
                        row = c['rows'][index]
                        lane = str(index % c['horizon'])
                        units = int(archive[c['key'] + 'lane_issued_units'][row, PRIMARY])
                        require(views[c['id']]['controller_states'][lane]['theta_units'] == units,
                                'archived state at issue changed')
                        checks['exact_issue_state_comparisons'] += 1
                        prediction = {name + '_hex': float(archive[c['key'] + 'lane_' + name][row, PRIMARY]).hex()
                                      for name in ('var', 'es')}
                        forecast_id = f"{c['currency']}-h{c['horizon']}-o{index}"
                        view = submit(c, 'issue', index, {
                            'forecast_id': forecast_id, 'origin': index, 'target_end': index + c['horizon'],
                            'issued_at': index, 'requirements': [
                                {'source_id': 'ECB-' + c['currency'], 'record_id': str(dates[t]),
                                 'event_start': t, 'event_end': t} for t in (index, index + c['horizon'])],
                            'prediction': prediction, 'lane_id': lane,
                            'provenance': {'adaptive_protocol_sha256': sources['results/adaptive_risk_protocol.json'],
                                'forecast_archive_sha256': sources['results/adaptive_risk_predictions.npz'],
                                'archive_row': row, 'primary_column': PRIMARY,
                                'source_csv_sha256': protocol['source_csv_sha256'],
                                'checkpoint': c['checkpoints'][lane],
                                'availability_mode': 'historical_replay_without_vintages'}})
                        require(forecast_id in view['feedback']['pending'], 'issued target already scored')
                        require(forecast_id not in {x['forecast_id'] for x in view['feedback']['active']},
                                'issued target already active')
                        checks['issued_forecasts'] += 1
                        checks['pending_after_issue_checks'] += 1

                final_views = {c['id']: store.view(c['id']) for c in contracts}
                for c in contracts:
                    view = final_views[c['id']]
                    require(view['issuance_basis'] == 'historical_declaration', 'historical scope label lost')
                    require(not view['feedback']['pending'], 'remaining pending selected forecasts')
                    require(len(view['feedback']['active']) == PER_CONTRACT, 'selected target count changed')
                    require(view['module_operation_count'] <= 256, 'reference history cap exceeded')
                    require(sum(x['updates'] for x in view['controller_states'].values()) == PER_CONTRACT,
                            'learner update count changed')
                    checks['final_controller_update_count_checks'] += 1
                export = store.export()
                for record in export['records']:
                    command = record['command']
                    if command['op'] != 'issue':
                        continue
                    c = next(c for c in contracts if c['id'] == command['contract'])
                    row = c['rows'][command['payload']['origin']]
                    expected = {name + '_hex': float(archive[c['key'] + 'lane_' + name][row, PRIMARY]).hex()
                                for name in ('var', 'es')}
                    require(canonical(command['payload']['prediction']) == canonical(expected),
                            'stored prediction differs from archived binary64 pair')
                    checks['exact_prediction_pair_checks'] += 1
                terminal_head, budget = store.head, store.budget
                audit = store.audit(expected_head=terminal_head, expected_events=budget['events'])

            with Store.open(database, registry, expected_head=terminal_head,
                            expected_events=budget['events']) as recovered:
                for c in contracts:
                    require(canonical(recovered.view(c['id'])) == canonical(final_views[c['id']]),
                            'reopened historical view differs')
                    checks['reopened_view_checks'] += 1

            # Rebuild a second store from the exact saved command envelopes,
            # including expected heads; no new forecast generator is invoked.
            with Store.create(Path(temporary) / 'command-replay.sqlite', registry) as rebuilt:
                for command in commands:
                    rebuilt.submit(command)
                require(rebuilt.head == terminal_head, 'command replay terminal head differs')
                require(rebuilt.budget == budget, 'command replay accounting differs')
                for c in contracts:
                    require(canonical(rebuilt.view(c['id'])) == canonical(final_views[c['id']]),
                            'saved command replay view differs')
                    checks['saved_command_replay_view_checks'] += 1

    require(canonical(registry['maturity-risk/v1'].fingerprint()) == canonical(fingerprint),
            'runtime implementation changed during history replay')
    inputs = {'schema': 'gabriel.runtime-history-inputs.v1', 'header': export['header'],
              'commands': commands, 'expected_terminal_head': terminal_head,
              'expected_events': budget['events'], 'expected_command_bytes': budget['bytes']}
    input_path = ROOT / 'results/runtime_history_replay_inputs.json'
    input_path.write_text(json.dumps(inputs, indent=2) + '\n')
    result = {'schema': 'gabriel.runtime-history-replay.v1', 'status': 'passed',
        'elapsed_seconds': time.monotonic() - started, 'numpy_version': np.__version__,
        'source_sha256': sources, 'runtime_fingerprint': fingerprint,
        'recorded_source_csv_sha256': protocol['source_csv_sha256'],
        'source_scope': 'Endpoint rates read from the existing archive containing only USD, GBP, JPY and CHF. The full source CSV and reserved currencies are not loaded.',
        'selection': {'currencies': list(CURRENCIES), 'horizons': list(HORIZONS),
            'forecasts_per_contract': PER_CONTRACT, 'rule': 'First 16 consecutive matured origins in the previously evaluated 2026 period, independent of outcomes.',
            'first_origin': str(dates[start]), 'last_endpoint': str(dates[end]),
            'order': 'At each original observation index, completed endpoint receipts precede new forecasts. Contracts interleave under one owner.'},
        'controller': {'eta': '1/20', 'beta': '1/40', 'unit': '1/800', 'bounds_units': [-800, 800]},
        'availability_mode': 'historical_replay_without_vintages',
        'checkpoint_scope': 'Import exact per-lane theta at first retained issue; update counts restart at zero for this slice. Earlier learning is not reconstructed.',
        'claim_scope': 'Operational preservation of already issued archived forecasts, hits and integer controller states. No forecast refit, new market comparison, new selection or historical-vintage/live-issuance validation.',
        'checks': checks, 'owner_budget': budget, 'owner_audit': audit,
        'inputs_file': str(input_path.relative_to(ROOT)), 'inputs_sha256': sha(input_path),
        'runs': [{'contract_id': c['id'], 'currency': c['currency'], 'horizon': c['horizon'],
            'origin_indices': list(c['rows']), 'initial_lane_states': c['checkpoints'],
            'final_lane_states': final_views[c['id']]['controller_states'],
            'module_operations': final_views[c['id']]['module_operation_count'],
            'feedback_digest': final_views[c['id']]['feedback_digest'],
            'view_digest': digest(final_views[c['id']]), 'updates': c['updates']} for c in contracts]}
    (ROOT / 'results/runtime_history_replay.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'status': result['status'], 'checks': checks, 'owner_budget': budget,
                      'elapsed_seconds': result['elapsed_seconds']}, indent=2))


if __name__ == '__main__':
    main()
