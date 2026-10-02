"""Immutable exact-model preparation reused across independent window queries.

The scalar decision body is copied verbatim from the frozen single-window
implementation, except for its preparation block.  The source-equivalence check
in reproduction/check_window_batch.py verifies that relationship using the AST.
All returned certificate dictionaries, including resource counters, retain the
v1 format and are byte-identical under the same JSON serializer.  This module
adds no numerical shortcut, cross-window evidence cache, or global monkeypatch.

Prepared objects are local capabilities, not serialized proofs or a security
boundary against arbitrary Python code in the same interpreter.  Their model,
source binding and serialized payload are immutable under the public API.
"""
from __future__ import annotations

from fractions import Fraction
import hashlib
import json
from pathlib import Path

from . import window_certificate as _reference
from .window_certificate import (
    CERTIFICATE_SCHEMA, MODEL_PROFILE, DEFAULT_PRECISIONS,
    MAX_RATIONAL_BITS, MAX_OUTPUT_INTEGER_BITS, OutOfScope,
    exact_number, prepare_model, point_enclosure,
    _precision, _bounds_payload, _phase_geometry, _maximum_rational_bounds,
)


BATCH_SCHEMA = 'gabriel-prepared-window-batch/v1'
MAX_BATCH_WINDOWS = 256
REFERENCE_SOURCE_SHA256 = 'b344b7282c8c28262236e680d68fe58bfda67ecc45073c3b8d38f0b11214925c'
_FACTORY_TOKEN = object()


class PreparedWindowModel:
    """Immutable local result of prepare_window_model; not directly constructible."""
    __slots__ = ('_model', '_model_json', '_reason', '_input_sha256', '_seal')

    def __new__(cls, token=None, *args, **kwargs):
        if cls is not PreparedWindowModel or token is not _FACTORY_TOKEN:
            raise TypeError('use prepare_window_model to construct a prepared model')
        return super().__new__(cls)

    def __init__(self, token, model, payload, reason, binding):
        object.__setattr__(self, '_model', model)
        object.__setattr__(self, '_model_json', payload)
        object.__setattr__(self, '_reason', reason)
        object.__setattr__(self, '_input_sha256', binding)
        object.__setattr__(self, '_seal', token)

    def __setattr__(self, name, value):
        raise AttributeError('prepared window models are immutable')

    def __delattr__(self, name):
        raise AttributeError('prepared window models are immutable')

    @property
    def input_sha256(self):
        return self._input_sha256

    @property
    def out_of_scope(self):
        return self._reason is not None

    def model_payload(self):
        """Return an independent mutable payload, or None for out-of-scope input."""
        return None if self._model_json is None else json.loads(self._model_json)


def _require_prepared(prepared):
    if type(prepared) is not PreparedWindowModel or getattr(prepared, '_seal', None) is not _FACTORY_TOKEN:
        raise ValueError('expected a factory-created prepared window model')


def _binding(snapshot, source, targets):
    # Called only after original validation has established valid input types,
    # finite entries, unique entities, source coverage and target membership.
    entities = snapshot['entities']
    by_entity = {term['entity']: term for term in source}
    target_set = set(targets)
    binding = {'entities': list(entities),
               'laplacian_bits': [list(row) for row in snapshot['laplacian_bits']],
               'source': [dict(by_entity[e]) for e in entities],
               'targets': [e for e in entities if e in target_set]}
    wire = json.dumps(binding, sort_keys=True, separators=(',', ':'), ensure_ascii=True)
    return hashlib.sha256(wire.encode('ascii')).hexdigest()


def implementation_identity():
    reference = hashlib.sha256(Path(_reference.__file__).read_bytes()).hexdigest()
    return {'schema': BATCH_SCHEMA,
            'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'reference_source_sha256': reference,
            'expected_reference_source_sha256': REFERENCE_SOURCE_SHA256,
            'reference_matches': reference == REFERENCE_SOURCE_SHA256,
            'max_batch_windows': MAX_BATCH_WINDOWS,
            'certificate_schema': CERTIFICATE_SCHEMA}


def prepare_window_model(snapshot, source, targets):
    """Validate and detach a represented model once, binding exact source bits.

    This preparation API validates model input eagerly.  Thus, for a request
    whose model and query are both invalid, its first error can differ from
    certify_window's query-first order.  Every such request is still rejected.
    Query validation in certify_prepared is otherwise identical to v1, including
    when the prepared graph is valid but outside the supported clique class.
    Optional metadata has exactly the original non-mathematical status.
    """
    current = hashlib.sha256(Path(_reference.__file__).read_bytes()).hexdigest()
    if current != REFERENCE_SOURCE_SHA256:
        raise RuntimeError('frozen certificate reference source has changed')
    try:
        model = prepare_model(snapshot, source, targets)
    except OutOfScope as exc:
        return PreparedWindowModel(_FACTORY_TOKEN, None, None, str(exc),
                                   _binding(snapshot, source, targets))
    payload = json.dumps(model.model_payload(), separators=(',', ':'), ensure_ascii=True)
    return PreparedWindowModel(_FACTORY_TOKEN, model, payload, None, model.input_sha256)


def certify_prepared(prepared, start_bits, end_bits, threshold_bits,
                   *, precisions=DEFAULT_PRECISIONS):
    """Certify ``exists t in [start,end]: regional_mass(t) > threshold``.

    Returns reachable, excluded, unknown, or out_of_scope.  Every certified
    decision carries rational evidence.  Exhausting the fixed precision ladder
    produces unknown; exact equality is never decided by a tolerance.
    """
    start, end, threshold = map(exact_number, (start_bits, end_bits, threshold_bits))
    if start > end:
        raise ValueError('window start must not exceed its end')
    if not 0 <= threshold <= 1:
        raise ValueError('threshold must lie in [0,1]')
    if type(precisions) not in (tuple, list) or not 1 <= len(precisions) <= 8:
        raise ValueError('precision ladder must contain 1..8 entries')
    ladder = tuple(_precision(p) for p in precisions)
    if list(ladder) != sorted(set(ladder)):
        raise ValueError('precision ladder must be strictly increasing')
    resources = {'precision_cap_bits': ladder[-1], 'precision_ladder': list(ladder),
                 'attempted_precisions': [], 'point_evaluations': 0,
                 'phase_evaluations': 0, 'max_precision_bits': 0,
                 'max_output_integer_bits': MAX_OUTPUT_INTEGER_BITS,
                 'max_point_evaluations': 3 * len(ladder),
                 'max_phase_evaluations': len(ladder)}
    result = {'schema': CERTIFICATE_SCHEMA, 'model_profile': MODEL_PROFILE,
              'query': {'start': str(start), 'end': str(end), 'threshold': str(threshold)},
              'resources': resources}
    _require_prepared(prepared)
    if prepared._reason is not None:
        return {**result, 'status': 'out_of_scope', 'reason': prepared._reason}
    model = prepared._model
    result['model'] = json.loads(prepared._model_json)

    def finish(status, evidence):
        return {**result, 'status': status, 'evidence': evidence}

    if model.stationary:
        value = model.stationary_value
        return finish('reachable' if value > threshold else 'excluded',
                      {'method': 'stationary_exact', 'value': str(value),
                       'time': str(start), 'mass': _bounds_payload(value, value)})
    if model.global_upper_leq(threshold):
        return finish('excluded', {'method': 'global_amplitude_exact',
                                  'supremum_upper': str(threshold),
                                  'offset': str(model.a), 'radicand': str(model.amplitude_squared)})
    last = None
    for precision in ladder:
        resources['attempted_precisions'].append(precision)
        resources['max_precision_bits'] = precision
        endpoints = []
        try:
            for t in ((start,) if start == end else (start, end)):
                resources['point_evaluations'] += 1
                mass = point_enclosure(model, t, precision)
                endpoints.append({'time': str(t), 'mass': mass})
                if Fraction(mass['lower']) > threshold:
                    return finish('reachable', {'method': 'rational_point', 'precision_bits': precision,
                                                'time': str(t), 'mass': mass})
            if start == end:
                if Fraction(endpoints[0]['mass']['upper']) <= threshold:
                    return finish('excluded', {'method': 'singleton_point', 'precision_bits': precision,
                                               'endpoints': endpoints,
                                               'supremum_upper': endpoints[0]['mass']['upper']})
                last = {'reason': 'singleton_threshold_overlap', 'endpoints': endpoints}
                continue
            resources['phase_evaluations'] += 1
            geometry, index, critical = _phase_geometry(model, start, end, precision)
            possible_first = int(geometry['possible_first_index'])
            possible_last = int(geometry['possible_last_index'])
            if possible_first > possible_last and all(Fraction(x['mass']['upper']) <= threshold for x in endpoints):
                return finish('excluded', {'method': 'endpoint_maximum', 'precision_bits': precision,
                                           'endpoints': endpoints, 'phase_geometry': geometry,
                                           'supremum_upper': str(max(Fraction(x['mass']['upper']) for x in endpoints))})
            if critical is not None:
                lo, hi = critical
                # First try a simple rational point witness.  Its check does
                # not depend on the phase-location reasoning that proposed it.
                candidate = (lo + hi) / 2
                if (start <= candidate <= end and
                        max(abs(candidate.numerator).bit_length(), candidate.denominator.bit_length()) <= MAX_RATIONAL_BITS):
                    resources['point_evaluations'] += 1
                    mass = point_enclosure(model, candidate, precision)
                    if Fraction(mass['lower']) > threshold:
                        return finish('reachable', {'method': 'rational_point', 'precision_bits': precision,
                                                    'time': str(candidate), 'mass': mass})
                if start <= lo <= hi <= end:
                    lower, upper = _maximum_rational_bounds(model, threshold)
                    assert lower > threshold
                    return finish('reachable', {'method': 'critical_point', 'precision_bits': precision,
                                                'phase_index': str(index),
                                                'time_enclosure': _bounds_payload(lo, hi),
                                                'mass': _bounds_payload(lower, upper),
                                                'value': {'offset': str(model.a), 'radicand': str(model.amplitude_squared)},
                                                'phase_geometry': geometry})
            last = {'reason': 'phase_or_threshold_overlap', 'endpoints': endpoints,
                    'phase_geometry': geometry}
        except ArithmeticError as exc:
            last = {'reason': 'interval_resource_or_enclosure_limit', 'detail': str(exc)}
    return finish('unknown', {'method': 'precision_cap', **(last or {}),
                              'reason': (last or {}).get('reason', 'precision_cap_exhausted')})


def certify_prepared_many(prepared, queries, *, precisions=DEFAULT_PRECISIONS):
    """Return an ordered list of independent v1 certificates for 1..256 queries.

    A query has exactly start_bits, end_bits and threshold_bits.  The method
    raises on any invalid query and returns no partial batch.  It has no external
    side effects.  It preserves repeated windows and caller order; no deduplication
    or cross-query precision/result caching alters numerical work counters.
    """
    _require_prepared(prepared)
    if type(queries) not in (list, tuple) or not 1 <= len(queries) <= MAX_BATCH_WINDOWS:
        raise ValueError('window batch must contain 1..256 queries')
    required = {'start_bits', 'end_bits', 'threshold_bits'}
    if any(type(query) is not dict or set(query) != required for query in queries):
        raise ValueError('batch query has invalid fields')
    return [certify_prepared(prepared, **query, precisions=precisions) for query in queries]


def certify_windows(snapshot, source, targets, windows, threshold_bits,
                    *, precisions=DEFAULT_PRECISIONS):
    """Prepare once, then certify ordered windows with one shared threshold."""
    if type(windows) not in (list, tuple) or not 1 <= len(windows) <= MAX_BATCH_WINDOWS:
        raise ValueError('window batch must contain 1..256 windows')
    if any(type(window) is not dict or set(window) != {'start_bits', 'end_bits'}
           for window in windows):
        raise ValueError('window has invalid fields')
    queries = [{**window, 'threshold_bits': threshold_bits} for window in windows]
    prepared = prepare_window_model(snapshot, source, targets)
    return certify_prepared_many(prepared, queries, precisions=precisions)
