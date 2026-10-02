"""Bounded native graph observations owned by the existing SQLite Store.

The selected local executable is trusted code. Hash guards bind a replay to
specific source and executable bytes; they are not authentication or a sandbox.
Every state transition reconstructs the native Engine in a fresh process.
Binary64 wire quantities use sixteen lowercase IEEE-754 bit digits.
"""
from __future__ import annotations

import argparse
import hashlib
import math
from pathlib import Path
import struct
import subprocess
import tempfile

from .canonical import canonical, digest, loads
from .engine import Store

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 'gabriel-engine-observer/v1'
ADAPTER = 'native-graph-observer/v1'
BACKENDS = ('spectral_full', 'auto_full', 'auto_region')
CAPS = {'max_nodes': 64, 'max_batches': 128, 'max_queries': 256}
MAX_WIRE_BYTES = 4 * 1024 * 1024
TIMEOUT_SECONDS = 30


def bits(value):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError('nonfinite binary64 quantity')
    return struct.pack('>d', value).hex()


def number(value):
    if (type(value) is not str or len(value) != 16
            or any(c not in '0123456789abcdef' for c in value)):
        raise ValueError('binary64 requires sixteen lowercase hexadecimal bit digits')
    result = struct.unpack('>d', bytes.fromhex(value))[0]
    if not math.isfinite(result):
        raise ValueError('nonfinite binary64 quantity')
    return result


def _fields(value, fields):
    if type(value) is not dict or set(value) != set(fields.split()):
        raise ValueError('fields must be exactly: ' + fields)


def _integer(value, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError('integer outside declared bounds')
    return value


def _entities(value, maximum=64, nonempty=False):
    if type(value) is not list or not int(nonempty) <= len(value) <= maximum:
        raise ValueError('entity list outside declared bounds')
    for entity in value:
        _integer(entity, 0, CAPS['max_nodes'] - 1)
    if len(set(value)) != len(value):
        raise ValueError('duplicate entity')
    return set(value)


def _hash_file(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _source_hashes():
    paths = [ROOT / 'gabriel_runtime' / name for name in
             ('graph_observer.py', 'engine.py', 'canonical.py', '__init__.py')]
    native = ROOT / 'native_pse'
    paths += [native / 'Cargo.toml', native / 'Cargo.lock',
              native / 'examples/engine_observer.rs']
    paths += list((native / 'src').rglob('*.rs'))
    paths += list((native / 'crates').glob('*/Cargo.toml'))
    paths += list((native / 'crates').glob('*/src/**/*.rs'))
    paths += list((native / 'crates').glob('*/data/*.bin'))
    return {str(path.relative_to(ROOT)): _hash_file(path) for path in sorted(set(paths))}


class GraphObserverAdapter:
    """Domain-neutral graph query profile, separate from financial adapters."""

    def __init__(self, executable, expected_sha256):
        self.executable = Path(executable).resolve(strict=True)
        if not self.executable.is_file():
            raise ValueError('explicit executable must be a regular file')
        if (type(expected_sha256) is not str or len(expected_sha256) != 64
                or any(c not in '0123456789abcdef' for c in expected_sha256)):
            raise ValueError('explicit SHA-256 must be lowercase hexadecimal')
        self.expected_sha256 = expected_sha256
        self.sources = _source_hashes()
        self._check_identity()

    def _check_identity(self):
        if _hash_file(self.executable) != self.expected_sha256:
            raise ValueError('native executable identity mismatch')
        if _source_hashes() != self.sources:
            raise ValueError('bound graph observer source identity mismatch')

    def fingerprint(self):
        self._check_identity()
        return {'adapter': ADAPTER, 'schema': SCHEMA,
                'executable_sha256': self.expected_sha256,
                'source_sha256': dict(self.sources), 'hard_caps': dict(CAPS),
                'timeout_seconds': TIMEOUT_SECONDS, 'max_wire_bytes': MAX_WIRE_BYTES,
                'execution': 'fresh-native-process-full-batch-replay',
                'binary64_encoding': 'ieee754-f64-lowercase-16-hex-bits'}

    def initialize(self, config):
        _fields(config, 'backend max_nodes max_batches max_queries')
        if config['backend'] not in BACKENDS:
            raise ValueError('unknown graph backend')
        for key, cap in CAPS.items():
            _integer(config[key], 1, cap)
        return {'config': loads(canonical(config)), 'batches': [], 'issues': [],
                'query_count': 0, 'last_snapshot': None}

    def _query(self, payload, state):
        _fields(payload, 'source targets times_bits threshold_bits deadband_bits')
        entities = set(entity for batch in state['batches'] for entity in batch)
        if not entities:
            raise ValueError('at least one observation batch is required')
        if type(payload['source']) is not list or len(payload['source']) != len(entities):
            raise ValueError('source must cover every current entity exactly once')
        seen = set()
        nonzero = False
        for entry in payload['source']:
            _fields(entry, 'entity re_bits im_bits')
            entity = _integer(entry['entity'], 0, CAPS['max_nodes'] - 1)
            if entity in seen or entity not in entities:
                raise ValueError('duplicate or unknown source entity')
            seen.add(entity)
            re, im = number(entry['re_bits']), number(entry['im_bits'])
            nonzero = nonzero or re != 0.0 or im != 0.0
        if not nonzero:
            raise ValueError('zero source is not a normalized observation')
        targets = _entities(payload['targets'], state['config']['max_nodes'])
        if not targets <= entities:
            raise ValueError('unknown target entity')
        times = payload['times_bits']
        if type(times) is not list or not 1 <= len(times) <= CAPS['max_queries']:
            raise ValueError('one to 256 query times required')
        for value in times:
            number(value)
        threshold, deadband = number(payload['threshold_bits']), number(payload['deadband_bits'])
        if not 0 <= threshold <= 1 or not 0 <= deadband <= 1:
            raise ValueError('threshold and decision deadband must be in [0,1]')
        if state['query_count'] + len(times) > state['config']['max_queries']:
            raise ValueError('total query capacity exceeded')

    def _invoke(self, state, queries):
        self._check_identity()
        job = {'schema': SCHEMA, 'backend': state['config']['backend'],
               'batches': state['batches'], 'queries': queries}
        wire = canonical(job).encode('ascii')
        if len(wire) > MAX_WIRE_BYTES:
            raise ValueError('native input byte cap exceeded')
        # Output goes to anonymous local files so an accidental excessive output
        # cannot force an unbounded in-memory capture. Trusted code is bounded.
        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            try:
                process = subprocess.run([str(self.executable)], input=wire,
                                         stdout=out, stderr=err, timeout=TIMEOUT_SECONDS,
                                         check=False, shell=False)
            except subprocess.TimeoutExpired as exc:
                raise ValueError('native graph observer timeout') from exc
            self._check_identity()
            out.seek(0); response_bytes = out.read(MAX_WIRE_BYTES + 1)
            err.seek(0); error_bytes = err.read(4096)
            if process.returncode:
                raise ValueError('native graph observer rejected request: ' +
                                 error_bytes.decode('ascii', errors='replace').strip())
        if len(response_bytes) > MAX_WIRE_BYTES:
            raise ValueError('native output byte cap exceeded')
        try:
            response = loads(response_bytes.decode('ascii').strip())
        except (UnicodeDecodeError, ValueError) as exc:
            raise ValueError('invalid native exact JSON response') from exc
        _fields(response, 'schema backend engine snapshot query_results')
        if response['schema'] != SCHEMA or response['backend'] != job['backend']:
            raise ValueError('native response contract mismatch')
        if type(response['query_results']) is not list or len(response['query_results']) != len(queries):
            raise ValueError('native response query count mismatch')
        for query, result in zip(queries, response['query_results']):
            _fields(result, 'region_backend values')
            if result['region_backend'] not in ('state_readout', 'complete_graph_region'):
                raise ValueError('unknown native region backend')
            if type(result['values']) is not list or len(result['values']) != len(query['times_bits']):
                raise ValueError('native response time count mismatch')
            threshold = number(query['threshold_bits'])
            deadband = number(query['deadband_bits'])
            for time_bits, item in zip(query['times_bits'], result['values']):
                _fields(item, 'time_bits mass_bits decision')
                if item['time_bits'] != time_bits:
                    raise ValueError('native time identity mismatch')
                mass = number(item['mass_bits'])
                decision = ('above' if mass > threshold + deadband else
                            'below' if mass < threshold - deadband else 'ambiguous')
                if item['decision'] != decision:
                    raise ValueError('native decision does not match declared rule')
        return response

    def apply(self, state, operation, payload, receipt_at):
        _integer(receipt_at, 0, 2**53 - 1)
        candidate = loads(canonical(state))
        payload = loads(canonical(payload))
        if operation == 'append_batch':
            _fields(payload, 'entities')
            _entities(payload['entities'], state['config']['max_nodes'], nonempty=True)
            existing = set(entity for batch in state['batches'] for entity in batch)
            if len(existing | set(payload['entities'])) > state['config']['max_nodes']:
                raise ValueError('total entity capacity exceeded')
            if len(state['batches']) >= state['config']['max_batches']:
                raise ValueError('batch history capacity exceeded')
            candidate['batches'].append(payload['entities'])
            response = self._invoke(candidate, [])
            candidate['last_snapshot'] = response['snapshot']
            result = {'operation': operation, 'batch_count': len(candidate['batches']),
                      'engine': response['engine'], 'snapshot': response['snapshot']}
        elif operation == 'query':
            self._query(payload, state)
            response = self._invoke(candidate, [payload])
            issue = {'request': payload, 'owner_receipt_at': receipt_at,
                     'batch_count': len(candidate['batches']), 'native_result': response}
            issue['digest'] = digest(issue)
            candidate['issues'].append(issue)
            candidate['query_count'] += len(payload['times_bits'])
            candidate['last_snapshot'] = response['snapshot']
            result = {'operation': operation, 'issue': issue}
        else:
            raise ValueError('graph observer supports append_batch and query')
        return candidate, result

    def view(self, state):
        return {'semantic_profile': ADAPTER, 'backend': state['config']['backend'],
                'batch_count': len(state['batches']), 'query_count': state['query_count'],
                'issue_count': len(state['issues']), 'last_snapshot': state['last_snapshot'],
                'last_issue': state['issues'][-1] if state['issues'] else None}


def demo_query(n=13, count=16):
    """Synthetic fixture; source values are normalized by the native observer."""
    source = [{'entity': i, 're_bits': bits(((17*i+3) % 29)-14),
               'im_bits': bits(((11*i+5) % 23)-11)} for i in range(n)]
    norm = sum(number(s['re_bits'])**2 + number(s['im_bits'])**2 for s in source)
    threshold = sum(number(s['re_bits'])**2 + number(s['im_bits'])**2
                    for s in source if s['entity'] % 2 == 0) / norm
    return {'source': source, 'targets': list(range(0, n, 2)),
            'times_bits': [bits((i % 16 + 1)/32) for i in range(count)],
            'threshold_bits': bits(threshold), 'deadband_bits': bits(1e-7)}


def run_demo(directory, executable, sha256, backend='auto_region'):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    adapter = GraphObserverAdapter(executable, sha256)
    commands = []
    with Store.create(directory / 'owner.sqlite', {ADAPTER: adapter}) as owner:
        def submit(op, payload):
            command = {'id': 'graph-' + str(len(commands)+1), 'contract': 'graph',
                       'op': op, 'at': len(commands), 'expected_head': owner.head,
                       'payload': payload}
            result = owner.submit(command)
            commands.append(command)
            return result
        submit('bind', {'adapter': ADAPTER, 'config': {'backend': backend, **CAPS}})
        submit('append_batch', {'entities': list(range(13))})
        receipt = submit('query', demo_query())
        anchor = {'head': owner.head, 'events': owner.budget['events']}
        audit = owner.audit(expected_head=anchor['head'], expected_events=anchor['events'])
        journal = owner.export()
    for name, value in [('commands', commands), ('anchor', anchor), ('journal', journal),
                        ('summary', {'kind': 'synthetic', 'audit': audit,
                                     'query_receipt': receipt})]:
        (directory / (name + '.json')).write_text(canonical(value)+'\n', encoding='ascii')
    return {'status': 'passed', 'directory': str(directory), 'anchor': anchor}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['demo', 'audit'])
    parser.add_argument('path')
    parser.add_argument('--executable', required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--backend', choices=BACKENDS, default='auto_region')
    args = parser.parse_args()
    if args.operation == 'demo':
        result = run_demo(args.path, args.executable, args.sha256, args.backend)
    else:
        directory = Path(args.path)
        anchor = loads((directory / 'anchor.json').read_text('ascii'))
        with Store.open(directory / 'owner.sqlite',
                        {ADAPTER: GraphObserverAdapter(args.executable, args.sha256)},
                        expected_head=anchor['head'], expected_events=anchor['events']) as owner:
            result = owner.audit(expected_head=anchor['head'], expected_events=anchor['events'])
    print(canonical(result))


if __name__ == '__main__':
    main()
