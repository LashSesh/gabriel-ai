"""Check immutable preparation and full-certificate equivalence; no timing claims.

The independent mathematical checks remain in check_window_certificate.py and
verify_window_reachability.py.  This check targets the new optimization boundary:
source equivalence, original full certificates, validation, aliasing and threads.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import copy
from fractions import Fraction
import hashlib
import inspect
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gabriel_runtime import window_batch as batch
from gabriel_runtime import window_certificate as reference
from gabriel_runtime.graph_reachability import laplacian_for_certificate

COUNTS = Counter()
COMPARISONS = []
METRICS = {}


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')


def require(condition, name):
    if not condition:
        raise AssertionError(name)
    COUNTS[name] += 1


def raises(call):
    try:
        call()
    except Exception as exc:
        return type(exc).__name__, str(exc)
    raise AssertionError('expected a rejection')


def equal(name, expected, observed):
    a, b = wire(expected), wire(observed)
    require(a == b, 'full_certificate_bytes_identical')
    require(json.dumps(expected) == json.dumps(observed), 'insertion_order_and_default_json_identical')
    require(expected['resources'] == observed['resources'], 'all_resource_counters_identical')
    COMPARISONS.append({'name': name, 'sha256': hashlib.sha256(a).hexdigest(),
                        'status': observed['status'],
                        'method': observed.get('evidence', {}).get('method')})


def bits(value):
    return struct.pack('>d', value).hex()


def sample():
    return ({'entities': [0, 1],
             'laplacian_bits': [[bits(1.), bits(-1.)], [bits(-1.), bits(1.)]]},
            [{'entity': 0, 're_bits': bits(1.), 'im_bits': bits(0.)},
             {'entity': 1, 're_bits': bits(0.), 'im_bits': bits(0.)}], [1])


def syntax_equivalence():
    """The entire decision algorithm and validation are the unchanged v1 AST."""
    old = ast.parse(inspect.getsource(reference.certify_window)).body[0]
    new = ast.parse(inspect.getsource(batch.certify_prepared)).body[0]
    old_index = next(i for i, node in enumerate(old.body)
                     if isinstance(node, ast.Try) and 'prepare_model' in ast.unparse(node))
    new_index = next(i for i, node in enumerate(new.body)
                     if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
                     and ast.unparse(node.value.func) == '_require_prepared')
    dump = lambda nodes: [ast.dump(node, include_attributes=False) for node in nodes]
    require(dump(old.body[:old_index]) == dump(new.body[:new_index]),
            'query_validation_and_resource_initialization_ast_identical')
    require(dump(old.body[old_index + 2:]) == dump(new.body[new_index + 4:]),
            'full_decision_body_ast_identical')
    require(batch.implementation_identity()['reference_matches'], 'frozen_reference_source_hash')


def saved_cases():
    old = json.loads((ROOT / 'results/window_certificate_checks.json').read_text())
    for case in old['certificates']:
        snapshot, source, targets = case['snapshot'], case['source'], case['targets']
        query = case['certificate']['query']
        args = tuple(Fraction(query[k]) for k in ('start', 'end', 'threshold'))
        precisions = tuple(case['certificate']['resources']['precision_ladder'])
        prepared = batch.prepare_window_model(snapshot, source, targets)
        fresh = reference.certify_window(snapshot, source, targets, *args, precisions=precisions)
        observed = batch.certify_prepared(prepared, *args, precisions=precisions)
        equal('prior-adversarial-' + case['name'], fresh, observed)
        require(wire(fresh) == wire(case['certificate']), 'prior_saved_certificate_reproduced')

    study = json.loads((ROOT / 'results/window_reachability_study/inputs.json').read_text())
    snapshots = {key: laplacian_for_certificate(item['response']) for key, item in study['snapshots'].items()}
    groups = {}
    for case in study['cases']:
        snapshot = case.get('snapshot', snapshots.get(case['snapshot_key']))
        source, targets = case['source'], case['targets']
        key = wire({'snapshot': snapshot, 'source': source, 'targets': targets})
        prepared = groups.setdefault(key, None)
        if prepared is None:
            groups[key] = prepared = batch.prepare_window_model(snapshot, source, targets)
        args = tuple(case[k] for k in ('start_bits', 'end_bits', 'threshold_bits'))
        expected = reference.certify_window(snapshot, source, targets, *args)
        observed = batch.certify_prepared(prepared, *args)
        equal(case['case_id'], expected, observed)
    METRICS['distinct_prepared_study_models'] = len(groups)


def validation_and_isolation():
    snapshot, source, targets = sample()
    prepared = batch.prepare_window_model(snapshot, source, targets)
    args = (Fraction(0), Fraction(3), Fraction(9, 10))
    expected = reference.certify_window(snapshot, source, targets, *args)
    pristine_binding = prepared.input_sha256
    for method in (lambda: setattr(prepared, '_input_sha256', 'forged'),
                   lambda: delattr(prepared, '_model'),
                   lambda: setattr(prepared._model, 'a', Fraction(10)),
                   lambda: batch.PreparedWindowModel()):
        raises(method)
        COUNTS['public_mutation_or_direct_construction_rejected'] += 1
    # Every externally held mutable input can change without rewriting history.
    snapshot['entities'].reverse()
    snapshot['laplacian_bits'][0][1] = bits(0.)
    source[0]['re_bits'] = bits(0.)
    targets[:] = [0, 1]
    require(prepared.input_sha256 == pristine_binding, 'caller_mutation_preserves_binding')
    equal('input-alias-isolation', expected, batch.certify_prepared(prepared, *args))
    payload = prepared.model_payload()
    payload['entities'].clear()
    payload['a'] = '123'
    first = batch.certify_prepared(prepared, *args)
    first['model']['targets'].clear()
    first['resources']['attempted_precisions'].append(999)
    first['evidence']['mass']['lower'] = '42'
    equal('output-alias-isolation', expected, batch.certify_prepared(prepared, *args))

    snapshot, source, targets = sample()
    bad_queries = [((2, 1, 0), {}), ((0, 1, -1), {}), ((0, 1, 2), {}),
                   ((0., 1, 0), {}), ((True, 1, 0), {}),
                   (('7ff0000000000000', 1, 0), {}),
                   (({'numerator': '2', 'denominator': '4'}, 1, 0), {}),
                   ((Fraction(1 << 8193), 1, 0), {}),
                   ((0, 1, 0), {'precisions': ()}),
                   ((0, 1, 0), {'precisions': (128, 128)}),
                   ((0, 1, 0), {'precisions': (512, 128)}),
                   ((0, 1, 0), {'precisions': (1024,)}),
                   ((0, 1, 0), {'precisions': (True,)}),
                   ((0, 1, 0), {'precisions': (128.0,)})]
    for query, kwargs in bad_queries:
        require(raises(lambda: reference.certify_window(snapshot, source, targets, *query, **kwargs)) ==
                raises(lambda: batch.certify_prepared(prepared, *query, **kwargs)),
                'query_validation_type_and_message_identical')
    for precisions in ((32,), (64, 128), [128, 256, 512]):
        equal('alternate-precision-ladder',
              reference.certify_window(snapshot, source, targets, *args, precisions=precisions),
              batch.certify_prepared(prepared, *args, precisions=precisions))

    malformed = [({}, source, targets), (snapshot, source[:-1], targets),
                 (snapshot, source, [1, 1]), (snapshot, source, [False]),
                 (snapshot, [dict(source[0]), dict(source[0])], targets)]
    zero = copy.deepcopy(source)
    for term in zero:
        term['re_bits'] = term['im_bits'] = bits(0.)
    malformed.append((snapshot, zero, targets))
    for s, q, r in malformed:
        require(raises(lambda: reference.prepare_model(s, q, r)) ==
                raises(lambda: batch.prepare_window_model(s, q, r)),
                'model_validation_type_and_message_identical')
    for impostor in (None, {}, reference.prepare_model(snapshot, source, targets),
                     object.__new__(batch.PreparedWindowModel)):
        require(raises(lambda: batch.certify_prepared(impostor, *args))[0] == 'ValueError',
                'forged_prepared_object_rejected')

    outside = copy.deepcopy(snapshot)
    outside['laplacian_bits'][0][1] = bits(-0.5)
    op = batch.prepare_window_model(outside, source, targets)
    require(op.out_of_scope and op.model_payload() is None, 'valid_unsupported_preparation')
    equal('unsupported-graph', reference.certify_window(outside, source, targets, *args),
          batch.certify_prepared(op, *args))
    require(op.input_sha256 != prepared.input_sha256, 'unsupported_graph_has_distinct_binding')
    require(raises(lambda: reference.certify_window(outside, source, targets, 2, 1, 0)) ==
            raises(lambda: batch.certify_prepared(op, 2, 1, 0)), 'unsupported_query_validation_precedence')

    windows = [{'start_bits': args[0], 'end_bits': args[1]},
               {'start_bits': 0, 'end_bits': Fraction(1, 4)},
               {'start_bits': args[0], 'end_bits': args[1]}]
    expected_list = [reference.certify_window(snapshot, source, targets, w['start_bits'], w['end_bits'], args[2])
                     for w in windows]
    observed = batch.certify_windows(snapshot, source, targets, windows, args[2])
    require(wire(observed) == wire(expected_list), 'batch_order_duplicates_and_certificates_preserved')
    require(observed[0] is not observed[2] and observed[0]['model'] is not observed[2]['model'],
            'duplicate_windows_have_independent_output_objects')
    one = {'start_bits': 0, 'end_bits': 0, 'threshold_bits': 1}
    require(len(batch.certify_prepared_many(prepared, [one] * 256)) == 256, 'batch_inclusive_cap')
    for queries in ([], [one] * 257, [{**one, 'extra': 1}], [{'start_bits': 0}], [None], iter([one])):
        require(raises(lambda: batch.certify_prepared_many(prepared, queries))[0] == 'ValueError',
                'batch_shape_or_cap_rejected')
    for windows_bad in ([], [windows[0]] * 257, [{'start_bits': 0}], [None]):
        require(raises(lambda: batch.certify_windows(snapshot, source, targets, windows_bad, 0))[0] == 'ValueError',
                'shared_threshold_batch_shape_or_cap_rejected')
    broken = [one, {**one, 'start_bits': 1, 'end_bits': 0}]
    require(raises(lambda: batch.certify_prepared_many(prepared, broken))[0] == 'ValueError',
            'late_invalid_query_returns_no_partial_batch')
    # The same model is safe under the existing shared Arb lock.  Threaded API
    # agreement is a correctness check, not a throughput experiment.
    with ThreadPoolExecutor(max_workers=4) as pool:
        threaded = list(pool.map(lambda _: batch.certify_prepared(prepared, *args), range(24)))
    require(all(wire(item) == wire(expected) for item in threaded), 'shared_model_threaded_equivalence')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT / 'results/epoch_batch/functional_checks.json')
    args = parser.parse_args()
    syntax_equivalence()
    saved_cases()
    validation_and_isolation()
    report = {'schema': 'gabriel-window-batch-checks/v1', 'passed': True,
              'scope': 'Full-certificate equivalence and preparation isolation; no timing or independent new mathematical proof.',
              'implementation': batch.implementation_identity(),
              'checker_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'check_count': sum(COUNTS.values()), 'checks': dict(sorted(COUNTS.items())),
              'metrics': METRICS,
              'comparisons': COMPARISONS,
              'comparison_digest': hashlib.sha256(wire(COMPARISONS)).hexdigest()}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, sort_keys=True, indent=2) + '\n')
    print(json.dumps({'passed': True, 'checks': report['check_count'],
                      'full_certificate_comparisons': len(COMPARISONS), 'output': str(args.output)}))


if __name__ == '__main__':
    main()
