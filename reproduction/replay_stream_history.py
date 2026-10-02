"""Replay archived raw FX observations through the executable stream adapter.

This is a bounded algorithm-integration comparison, not a new market-performance
experiment. Only the four already used currency columns are read. Each learner
starts uniformly at its first eligible raw-price prefix, not at the later 2010
checkpoint used in earlier market evaluations.
"""
from __future__ import annotations

from fractions import Fraction
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CURRENCIES = ('USD', 'GBP', 'JPY', 'CHF')
HORIZONS = (1, 5)
ISSUES = 32
ATOL = 2e-13
RTOL = 2e-12


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def unpack(value):
    if isinstance(value, list):
        return np.asarray([unpack(x) for x in value], dtype=float)
    return float.fromhex(value)


def main():
    started = time.monotonic()
    from gabriel_runtime import Store, canonical, digest
    from gabriel_runtime.stream import extended_registry
    # These are the unchanged batch implementations, not stream-adapter helpers.
    from ecb_risk import load_protocol, forecast_candidates
    from severity_risk import replay_severity
    from aggregate_risk import replay_adagrad, EXPERTS

    registry = extended_registry()
    fingerprints = {name: adapter.fingerprint() for name, adapter in registry.items()}
    protocol = load_protocol()
    require(tuple(protocol['currencies']) == CURRENCIES, 'unexpected archive currency mapping')
    archive_path = ROOT / 'results/adaptive_risk_predictions.npz'
    sources = {str(path.relative_to(ROOT)): sha(path) for path in [archive_path,
        ROOT / 'results/ecb_risk_protocol.json', Path(__file__),
        ROOT / 'reproduction/ecb_risk.py', ROOT / 'reproduction/severity_risk.py',
        ROOT / 'reproduction/aggregate_risk.py']}
    with np.load(archive_path, allow_pickle=False) as archive:
        dates, all_rates = archive['dates'].copy(), archive['rates'].copy()
    require(all_rates.shape == (len(dates), len(CURRENCIES)), 'archive must contain only four currency columns')
    max_count = 60 + max(HORIZONS) + 250 - 1 + ISSUES
    rates = all_rates[:max_count]
    del all_rates
    require(np.isfinite(rates).all() and np.all(rates > 0), 'invalid retained source prices')

    comparisons = {}
    counts = dict(raw_records=0, issued_forecasts=0, expert_bank_comparisons=0,
                  pooled_forecast_comparisons=0, issued_weight_comparisons=0,
                  issued_accumulator_comparisons=0, severity_state_comparisons=0,
                  exact_proposal_checks=0, feedback_records=0,
                  on_time_target_availability_checks=0,
                  feedback_state_field_comparisons=0, terminal_learner_comparisons=0,
                  terminal_reopened_views=0)

    def compare(found, expected, name):
        actual, wanted = np.asarray(found, float), np.asarray(expected, float)
        require(actual.shape == wanted.shape and np.isfinite(actual).all()
                and np.isfinite(wanted).all(), 'nonfinite/shape comparison: ' + name)
        delta = float(np.max(np.abs(actual - wanted)))
        record = comparisons.setdefault(name, dict(calls=0, scalar_values=0,
                                                   max_absolute_difference=0.0,
                                                   bitwise_equal_calls=0))
        record['calls'] += 1
        record['scalar_values'] += int(actual.size)
        record['max_absolute_difference'] = max(record['max_absolute_difference'], delta)
        record['bitwise_equal_calls'] += int(actual.tobytes() == wanted.tobytes())
        require(np.allclose(actual, wanted, atol=ATOL, rtol=RTOL),
                f'{name}: max absolute difference {delta:.17g}')

    contracts = []
    for column, currency in enumerate(CURRENCIES):
        for horizon in HORIZONS:
            first = 60 + horizon + 250 - 1
            count = first + ISSUES
            source = rates[:count, column:column + 1]
            spec = dict(protocol, currencies=[currency], horizons_observed_intervals=[horizon])
            _, candidates = forecast_candidates(source, spec)
            origins, base_q, base_e = candidates[0, horizon]
            require(np.array_equal(origins, np.arange(first, count)), 'batch first-eligible rule changed')
            losses = np.full(ISSUES, np.nan)
            mature = origins + horizon < count
            losses[mature] = 100 * np.log(source[origins[mature] + horizon, 0] / source[origins[mature], 0])
            severity = [replay_severity(base_q[:, 5], losses, horizon, half,
                                       initial=1.5, cap=20) for half in (125, 500)]
            q = np.column_stack([base_q, base_q[:, 5], base_q[:, 5]])
            e = np.column_stack([base_e] + [x['es'] for x in severity])
            aggregate = replay_adagrad(q, e, losses, horizon, .1, origins=origins)
            contracts.append(dict(id=f'stream-{currency}-h{horizon}', currency=currency,
                column=column, horizon=horizon, first=first, count=count,
                origins=origins, losses=losses, q=q, e=e, severity=severity,
                aggregate=aggregate, issues=[], config={'source_id': 'ECB-' + currency,
                    'horizon': horizon, 'risk_budget': '10', 'unit_exposure': '100',
                    'max_units': 100}))

    commands, final_views = [], {}
    with tempfile.TemporaryDirectory(prefix='gabriel_stream_history_') as temporary:
        database = Path(temporary) / 'stream.sqlite'
        with Store.create(database, registry) as store:
            for c in contracts:
                command = {'id': 'bind-' + c['id'], 'contract': c['id'], 'op': 'bind',
                           'at': 0, 'expected_head': store.head,
                           'payload': {'adapter': 'stream-risk/v1', 'config': c['config']}}
                store.submit(command)
                commands.append(command)
            for index in range(max_count):
                for c in contracts:
                    if index >= c['count']:
                        continue
                    command = {'id': f"record-{c['id']}-{index}", 'contract': c['id'],
                        'op': 'record', 'at': index, 'expected_head': store.head,
                        'payload': {'index': index, 'event_at': index, 'received_at': index,
                            'revision': 0, 'rate_hex': float(rates[index, c['column']]).hex()}}
                    receipt = store.submit(command)
                    commands.append(command)
                    result = receipt['result']
                    require(result['accepted'] is True, 'source record was not accepted')
                    counts['raw_records'] += 1
                    issued = result['issued']
                    if index < c['first']:
                        require(issued is None, 'stream emitted before prescribed warmup')
                        continue
                    require(issued is not None, 'eligible positive-bank forecast not emitted')
                    require(issued['prediction_basis'] == 'next_unreceived_observation',
                            'forecast availability basis is not explicit')
                    row = index - c['first']
                    require(issued['origin_index'] == index and issued['target_index'] == index + c['horizon'],
                            'issued target indices differ')
                    require(tuple(issued['expert_order']) == EXPERTS, 'expert ordering differs')
                    compare(unpack(issued['expert_var_hex']), c['q'][row], 'expert_var')
                    compare(unpack(issued['expert_es_hex']), c['e'][row], 'expert_es')
                    compare([unpack(issued['var_hex']), unpack(issued['es_hex'])],
                            [c['aggregate']['var'][row], c['aggregate']['es'][row]], 'pooled_var_es')
                    compare(unpack(issued['issued_weights_hex']), c['aggregate']['issued_weights'][row],
                            'issued_weights')
                    # With fixed h and on-time prices the previous update in
                    # this lane is precisely the issue h rows earlier.
                    accumulator = 0.0 if row < c['horizon'] else c['aggregate']['accumulator_after'][row - c['horizon']]
                    compare(unpack(issued['issued_accumulator_hex']), accumulator, 'issued_accumulator')
                    compare(unpack(issued['severity_raw_ratio_hex']),
                            [x['issued_raw_ratio'][row] for x in c['severity']], 'issued_severity_raw')
                    proposal = issued['proposal']
                    es = Fraction(float.fromhex(issued['es_hex']))
                    budget, exposure = Fraction(c['config']['risk_budget']), Fraction(c['config']['unit_exposure'])
                    per_unit = exposure * es / 100
                    expected_units = min(c['config']['max_units'], budget // per_unit)
                    require(proposal['units'] == expected_units, 'proposal integer optimum differs')
                    require(Fraction(proposal['es_exact']) == es, 'proposal does not bind issued binary64 ES')
                    require(Fraction(proposal['proxy_loss']) == expected_units * per_unit,
                            'proposal model-loss accounting differs')
                    require(Fraction(proposal['next_unit_proxy_loss']) == (expected_units + 1) * per_unit,
                            'next-unit loss accounting differs')
                    require(proposal['budget_satisfied'] is True and proposal['maximum_feasible'] is True,
                            'proposal feasibility declaration differs')
                    require(expected_units == c['config']['max_units'] or (expected_units + 1) * per_unit > budget,
                            'proposal is not maximal')
                    c['issues'].append(issued)
                    for name in ('issued_forecasts', 'expert_bank_comparisons', 'pooled_forecast_comparisons',
                                 'issued_weight_comparisons', 'issued_accumulator_comparisons',
                                 'severity_state_comparisons', 'exact_proposal_checks'):
                        counts[name] += 1

            for c in contracts:
                view = store.view(c['id'])
                final_views[c['id']] = view
                require(view['source_count'] == c['count'] and view['revision_count'] == c['count'],
                        'raw source accounting differs')
                require(view['issued_count'] == ISSUES and view['pending_count'] == c['horizon'],
                        'issued/pending count differs')
                require(view['prediction_basis'] == 'next_unreceived_observation',
                        'view availability basis is not explicit')
                learner = view['learner']
                compare(unpack(learner['lane_weights_hex']), c['aggregate']['final_weights'], 'final_lane_weights')
                compare(unpack(learner['lane_accumulators_hex']), c['aggregate']['final_accumulators'],
                        'final_lane_accumulators')
                compare(unpack(learner['severity_raw_ratio_hex']),
                        [x['issued_raw_ratio'][-1] for x in c['severity']], 'final_severity_raw')
                counts['terminal_learner_comparisons'] += 3
                feedback = learner['active_feedback']
                require(len(feedback) == ISSUES - c['horizon'], 'matured feedback count differs')
                for row, record in enumerate(feedback):
                    issued = c['issues'][row]
                    require(record['forecast_id'] == issued['forecast_id'], 'feedback order differs')
                    require(record['target_index'] == int(c['origins'][row] + c['horizon']),
                            'feedback target differs')
                    require(record['first_matured_at'] == record['target_index'] and
                            record['target_event_at'] == record['target_index'] and
                            record['target_after_issue'] is True and
                            record['lane'] == int(c['origins'][row] % c['horizon']),
                            'on-time target maturity/availability declaration differs')
                    counts['on_time_target_availability_checks'] += 1
                    compare(unpack(record['loss_hex']), c['losses'][row], 'feedback_loss')
                    for actual_name, reference_name in [
                            ('gradient_hex', 'gradient'), ('centered_gradient_hex', 'centered_gradient'),
                            ('gradient_norm_squared_hex', 'gradient_norm_squared'), ('step_hex', 'step'),
                            ('pre_weights_hex', 'preupdate_weights'), ('post_weights_hex', 'postupdate_weights'),
                            ('accumulator_before_hex', 'accumulator_before'), ('accumulator_after_hex', 'accumulator_after')]:
                        compare(unpack(record[actual_name]), c['aggregate'][reference_name][row],
                                'feedback_' + reference_name)
                        counts['feedback_state_field_comparisons'] += 1
                    compare(unpack(record['staleness_l2_hex']), 0.0, 'uncorrected_staleness')
                    counts['feedback_records'] += 1
            terminal_head, owner_budget = store.head, store.budget
            header = store.export()['header']

        # One terminal reopen performs the full semantic audit; there is no
        # growing-prefix Store.audit() inside the raw-record ingestion loop.
        with Store.open(database, registry, expected_head=terminal_head,
                        expected_events=owner_budget['events']) as reopened:
            for c in contracts:
                require(canonical(reopened.view(c['id'])) == canonical(final_views[c['id']]),
                        'terminal reopened view changed')
                counts['terminal_reopened_views'] += 1

    require(canonical({name: adapter.fingerprint() for name, adapter in registry.items()}) == canonical(fingerprints),
            'runtime fingerprints changed during execution')
    inputs = {'schema': 'gabriel.stream-history-inputs.v1', 'source_sha256': sources,
        'source_date_labels': [str(x) for x in dates[:max_count]], 'header': header,
        'commands': commands, 'expected_terminal_head': terminal_head,
        'expected_events': owner_budget['events'], 'expected_command_bytes': owner_budget['bytes']}
    input_path = ROOT / 'results/stream_history_inputs.json'
    input_path.write_text(json.dumps(inputs, indent=2) + '\n')
    result = {'schema': 'gabriel.stream-history-replay.v1', 'status': 'passed',
        'elapsed_seconds': time.monotonic() - started, 'source_sha256': sources,
        'runtime_fingerprints': fingerprints, 'numpy_version': np.__version__,
        'scope': 'Bounded raw-observation integration on previously used four-currency source data; no market accuracy evaluation, parameter selection, reserved currency access, or external effects.',
        'initialization': 'Severity ratios1.5; uniform eight-expert simplex and zero gradient energy per horizon lane at the first eligible source index. Earlier 2010 market-evaluation checkpoints are not imported.',
        'availability_mode': 'historical_current_vintage_replay_with_synthetic_index_receipts',
        'clock_scope': 'Source-index clocks preserve chronology. Actual historical publication receipts and revisions are unavailable.',
        'proposal_scope': 'Exact dyadic/rational budget comparison of a modeled linear log-loss proxy, not a trading instruction or actual-loss guarantee.',
        'reference_methods': ['ecb_risk.forecast_candidates', 'severity_risk.replay_severity', 'aggregate_risk.replay_adagrad'],
        'tolerances': {'absolute': ATOL, 'relative': RTOL, 'arithmetic': 'binary64, not directed rounding'},
        'selection': {'currencies': list(CURRENCIES), 'horizons': list(HORIZONS),
            'first_source_date': str(dates[0]), 'last_source_date': str(dates[max_count - 1]),
            'unique_source_currency_index_pairs': len(CURRENCIES) * max_count,
            'delivery_scope': 'The same source observations are delivered separately to the h1 and h5 contracts; raw_records counts contract deliveries, not independent observations.',
            'issued_origins_per_contract': ISSUES, 'rule': 'First32 eligible origins after fixed60-initialization/250-window warmup; no outcome-based choice.'},
        'checks': counts, 'numerical_comparisons': comparisons, 'owner_budget': owner_budget,
        'expected_terminal_head': terminal_head, 'terminal_semantic_reopen_passed': True,
        'inputs_file': str(input_path.relative_to(ROOT)), 'inputs_sha256': sha(input_path),
        'runs': [{'contract_id': c['id'], 'currency': c['currency'], 'horizon': c['horizon'],
            'config': c['config'], 'source_records': c['count'], 'first_issued_index': c['first'],
            'first_issued_date': str(dates[c['first']]), 'last_issued_date': str(dates[c['count'] - 1]),
            'issued_forecasts': len(c['issues']), 'matured_targets': ISSUES - c['horizon'],
            'final_view': final_views[c['id']], 'final_view_digest': digest(final_views[c['id']]),
            'issued': c['issues']} for c in contracts]}
    (ROOT / 'results/stream_history_replay.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'status': result['status'], 'checks': counts, 'owner_budget': owner_budget,
        'elapsed_seconds': result['elapsed_seconds'],
        'maximum_absolute_difference': max(x['max_absolute_difference'] for x in comparisons.values())}, indent=2))


if __name__ == '__main__':
    main()
