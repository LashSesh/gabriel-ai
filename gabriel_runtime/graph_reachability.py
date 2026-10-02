"""Opt-in durable interval reachability for exact represented graph models.

Fresh native full-history replay and byte checks remain mandatory. This profile
does not modify the binary64 observation or financial adapters.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
from pathlib import Path
import subprocess
import sys
import tempfile

from .canonical import canonical, digest, loads
from .graph_observer import (ROOT, bits, number, _fields, _integer, _entities,
                             _hash_file, _source_hashes)
from . import window_certificate

ADAPTER = 'native-graph-reachability/v1'
SCHEMA = 'gabriel-engine-snapshot/v1'
MODEL = 'exp(-itL);L=D-A;(W+W^T)/2;inactive-included;selfloops-ignored'
CAPS = {'max_nodes': 64, 'max_batches': 128, 'max_windows': 32}
PRECISIONS = (128, 256, 512)
MAX_WIRE_BYTES = 4 * 1024 * 1024
MAX_COMMAND_BYTES = 65536
TIMEOUT_SECONDS = 30


def _sensor_vertex_id(entity):
    value = 0xcbf29ce484222325
    for byte in ('sensor-' + str(entity)).encode('ascii'):
        value = ((value ^ byte) * 0x100000001b3) & ((1 << 64) - 1)
    return value


def _sources():
    hashes = _source_hashes()
    for relative in ('gabriel_runtime/graph_reachability.py',
                     'gabriel_runtime/window_certificate.py',
                     'native_pse/examples/engine_snapshot.rs'):
        hashes[relative] = _hash_file(ROOT / relative)
    return dict(sorted(hashes.items()))


def _arithmetic_identity():
    """Bind flint's installed Python/extension bytes and bundled shared libraries."""
    import flint
    root = Path(flint.__file__).resolve().parent
    paths = [p for p in root.rglob('*') if p.is_file() and
             (p.suffix in ('.py', '.so', '.pyd', '.dll', '.dylib') or '.so.' in p.name)]
    # Linux wheels keep FLINT/GMP/MPFR beside the package in python_flint.libs.
    for directory in root.parent.glob('*flint*.libs'):
        paths.extend(p for p in directory.rglob('*') if p.is_file())
    return {'python': sys.version, 'python_flint': importlib.metadata.version('python-flint'),
            'flint_version': str(getattr(flint, '__FLINT_VERSION__', 'unreported')),
            'files': {str(p.relative_to(root.parent)): _hash_file(p) for p in sorted(set(paths))}}


def laplacian_for_certificate(response):
    """Validate exported exact bits and construct the represented dense matrix."""
    _fields(response, 'schema engine snapshot')
    if response['schema'] != SCHEMA:
        raise ValueError('native snapshot schema mismatch')
    engine = response['engine']
    _fields(engine, 'ticks commits vertices edges observations faulted')
    for key in ('ticks', 'commits', 'vertices', 'edges', 'observations'):
        _integer(engine[key], 0, 2**53 - 1)
    if type(engine['faulted']) is not bool or engine['faulted'] or engine['commits'] != 0:
        raise ValueError('native snapshot unexpectedly faulted or committed')
    snapshot = response['snapshot']
    _fields(snapshot, 'identity tick vertices degree_bits adjacency model')
    if snapshot['model'] != MODEL:
        raise ValueError('native model mismatch')
    identity = snapshot['identity']
    if type(identity) is not str or len(identity) != 64 or any(c not in '0123456789abcdef' for c in identity):
        raise ValueError('invalid snapshot identity')
    _integer(snapshot['tick'], 1, CAPS['max_batches'])
    vertices = snapshot['vertices']
    if type(vertices) is not list or not 1 <= len(vertices) <= CAPS['max_nodes']:
        raise ValueError('native vertex count exceeds cap')
    labels, vertex_ids = [], []
    for vertex in vertices:
        _fields(vertex, 'entity vertex_id')
        labels.append(_integer(vertex['entity'], 0, 63))
        value = vertex['vertex_id']
        if type(value) is not str or not value or not value.isascii() or not value.isdecimal():
            raise ValueError('invalid native vertex identifier')
        if str(int(value)) != value or not 0 <= int(value) < 2**64:
            raise ValueError('noncanonical native vertex identifier')
        if int(value) != _sensor_vertex_id(vertex['entity']):
            raise ValueError('native entity label does not match sensor vertex identifier')
        vertex_ids.append(int(value))
    if len(set(labels)) != len(labels) or len(set(vertex_ids)) != len(vertex_ids):
        raise ValueError('duplicate native vertex')
    n = len(labels)
    if engine['vertices'] != n or engine['ticks'] != snapshot['tick']:
        raise ValueError('native snapshot statistics mismatch')
    degrees = snapshot['degree_bits']
    if type(degrees) is not list or len(degrees) != n:
        raise ValueError('native degree count mismatch')
    matrix = [[bits(0)] * n for _ in range(n)]
    for i, value in enumerate(degrees):
        if number(value) < 0:
            raise ValueError('negative native degree')
        matrix[i][i] = value
    adjacency = snapshot['adjacency']
    if type(adjacency) is not list or len(adjacency) > n*(n-1):
        raise ValueError('native adjacency exceeds cap')
    seen, previous = {}, None
    for edge in adjacency:
        _fields(edge, 'from to weight_bits')
        i, j = (_integer(edge[k], 0, n-1) for k in ('from', 'to'))
        if i == j or (i, j) in seen or (previous is not None and (i, j) <= previous):
            raise ValueError('invalid native adjacency order')
        weight = number(edge['weight_bits'])
        if weight < 0:
            raise ValueError('negative native weight')
        seen[i, j] = edge['weight_bits']
        previous = (i, j)
        matrix[i][j] = f'{int(edge["weight_bits"], 16) ^ (1 << 63):016x}'
    for (i, j), weight in seen.items():
        if (j, i) not in seen or number(seen[j, i]) != number(weight):
            raise ValueError('asymmetric native adjacency')
    # Reconstruct the Engine's snapshot digest independently of the CLI's label.
    encoded = bytearray(b'gabriel/conditioned-snapshot/v1;exp(-itL);L=D-A\0')
    encoded += snapshot['tick'].to_bytes(8, 'little') + n.to_bytes(8, 'little')
    for vertex_id, degree in zip(vertex_ids, degrees):
        encoded += vertex_id.to_bytes(8, 'little') + int(degree, 16).to_bytes(8, 'little')
    encoded += len(adjacency).to_bytes(8, 'little')
    for edge in adjacency:
        for value in (edge['from'], edge['to'], int(edge['weight_bits'], 16)):
            encoded += value.to_bytes(8, 'little')
    if hashlib.sha256(encoded).hexdigest() != identity:
        raise ValueError('native snapshot identity does not cover exported graph')
    return {'identity': identity, 'entities': labels, 'laplacian_bits': matrix}


class GraphReachabilityAdapter:
    def __init__(self, executable, expected_sha256):
        self.executable = Path(executable).resolve(strict=True)
        if not self.executable.is_file():
            raise ValueError('explicit executable must be a regular file')
        if (type(expected_sha256) is not str or len(expected_sha256) != 64
                or any(c not in '0123456789abcdef' for c in expected_sha256)):
            raise ValueError('explicit SHA-256 must be lowercase hexadecimal')
        self.expected_sha256 = expected_sha256
        self.sources = _sources()
        self.arithmetic = _arithmetic_identity()
        self._check_identity()

    def _check_identity(self):
        if _hash_file(self.executable) != self.expected_sha256:
            raise ValueError('native executable identity mismatch')
        if _sources() != self.sources or _arithmetic_identity() != self.arithmetic:
            raise ValueError('bound reachability source or arithmetic identity mismatch')

    def fingerprint(self):
        self._check_identity()
        return {'adapter': ADAPTER, 'snapshot_schema': SCHEMA,
                'executable_sha256': self.expected_sha256,
                'source_sha256': dict(self.sources), 'arithmetic': self.arithmetic,
                'hard_caps': dict(CAPS), 'precision_bits': list(PRECISIONS),
                'max_command_bytes': MAX_COMMAND_BYTES, 'max_wire_bytes': MAX_WIRE_BYTES,
                'timeout_seconds': TIMEOUT_SECONDS,
                'execution': 'fresh-native-process-full-batch-replay',
                'model': 'exact-raw-binary64-dyadic-source;exact-represented-laplacian;normalized-region-mass',
                'proposition': 'exists t in closed [start,end]: mass(t)>threshold',
                'certificate_schema': window_certificate.CERTIFICATE_SCHEMA}

    def initialize(self, config):
        _fields(config, 'max_nodes max_batches max_windows')
        for key, cap in CAPS.items():
            _integer(config[key], 1, cap)
        return {'config': loads(canonical(config)), 'batches': [], 'issues': [],
                'window_count': 0, 'last_snapshot': None}

    def _validate(self, state, payload):
        _fields(payload, 'batches source targets windows threshold_bits')
        if len(canonical(payload).encode('ascii')) > MAX_COMMAND_BYTES:
            raise ValueError('reachability payload byte cap exceeded')
        batches = payload['batches']
        if type(batches) is not list or len(state['batches']) + len(batches) > state['config']['max_batches']:
            raise ValueError('batch history exceeds cap')
        entities = set(entity for batch in state['batches'] for entity in batch)
        for batch in batches:
            entities |= _entities(batch, state['config']['max_nodes'], nonempty=True)
        if not entities or len(entities) > state['config']['max_nodes']:
            raise ValueError('total entity count outside bounds')
        source = payload['source']
        if type(source) is not list or len(source) != len(entities):
            raise ValueError('source must cover current entities exactly once')
        seen, nonzero = set(), False
        for entry in source:
            _fields(entry, 'entity re_bits im_bits')
            entity = _integer(entry['entity'], 0, 63)
            if entity not in entities or entity in seen:
                raise ValueError('duplicate or unknown source entity')
            seen.add(entity)
            re, im = number(entry['re_bits']), number(entry['im_bits'])
            nonzero = nonzero or re != 0 or im != 0
        if not nonzero:
            raise ValueError('zero source')
        if not _entities(payload['targets'], state['config']['max_nodes']) <= entities:
            raise ValueError('unknown target entity')
        threshold = number(payload['threshold_bits'])
        if not 0 <= threshold <= 1:
            raise ValueError('threshold outside [0,1]')
        windows = payload['windows']
        if type(windows) is not list or not 1 <= len(windows) <= state['config']['max_windows']:
            raise ValueError('window count outside bounds')
        if state['window_count'] + len(windows) > state['config']['max_windows']:
            raise ValueError('total window capacity exceeded')
        for window in windows:
            _fields(window, 'start_bits end_bits')
            if number(window['start_bits']) > number(window['end_bits']):
                raise ValueError('reversed closed window')

    def _invoke(self, batches):
        self._check_identity()
        wire = canonical({'schema': SCHEMA, 'batches': batches}).encode('ascii')
        if len(wire) > MAX_WIRE_BYTES:
            raise ValueError('native input byte cap exceeded')
        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            try:
                process = subprocess.run([str(self.executable)], input=wire,
                                         stdout=out, stderr=err, timeout=TIMEOUT_SECONDS,
                                         check=False, shell=False)
            except subprocess.TimeoutExpired as exc:
                raise ValueError('native snapshot timeout') from exc
            finally:
                self._check_identity()
            out.seek(0); raw = out.read(MAX_WIRE_BYTES + 1)
            err.seek(0); error = err.read(4096)
            if process.returncode:
                raise ValueError('native snapshot rejected request: ' + error.decode('ascii', errors='replace').strip())
        if len(raw) > MAX_WIRE_BYTES:
            raise ValueError('native output byte cap exceeded')
        try:
            response = loads(raw.decode('ascii').strip())
        except (UnicodeDecodeError, ValueError) as exc:
            raise ValueError('invalid native exact JSON response') from exc
        laplacian_for_certificate(response)
        stats = response['engine']
        entities = {entity for batch in batches for entity in batch}
        if (stats['ticks'] != len(batches) or stats['observations'] != sum(map(len, batches))
                or {v['entity'] for v in response['snapshot']['vertices']} != entities):
            raise ValueError('native history mismatch')
        return response

    def apply(self, state, operation, payload, receipt_at):
        _integer(receipt_at, 0, 2**53 - 1)
        if operation != 'observe':
            raise ValueError('reachability supports observe')
        payload = loads(canonical(payload))
        self._validate(state, payload)
        candidate = loads(canonical(state))
        candidate['batches'].extend(payload['batches'])
        native = self._invoke(candidate['batches'])
        snapshot = laplacian_for_certificate(native)
        self._check_identity()
        try:
            certificates = [window_certificate.certify_window(
                snapshot, payload['source'], payload['targets'],
                window['start_bits'], window['end_bits'], payload['threshold_bits'],
                precisions=PRECISIONS) for window in payload['windows']]
            # Exact JSON also refuses nonfinite values and unbounded JSON integers.
            certificates = loads(canonical(certificates))
        finally:
            self._check_identity()
        issue = {'request': payload, 'owner_receipt_at': receipt_at,
                 'batch_count': len(candidate['batches']), 'native_snapshot': native,
                 'certificates': certificates}
        issue['digest'] = digest(issue)
        candidate['issues'].append(issue)
        candidate['window_count'] += len(payload['windows'])
        candidate['last_snapshot'] = native['snapshot']
        return candidate, {'operation': operation, 'issue': issue}

    def view(self, state):
        return {'semantic_profile': ADAPTER, 'batch_count': len(state['batches']),
                'window_count': state['window_count'], 'issue_count': len(state['issues']),
                'last_snapshot': state['last_snapshot'],
                'last_issue': state['issues'][-1] if state['issues'] else None}
