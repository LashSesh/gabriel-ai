"""Exact-model batching with the original per-boundary content-hash guards.

Only model preparation is shared across windows of one atomic observe command.
The Store, native full-history replay, guard placement, numerical evidence, and
query caps are inherited unchanged. No state is cached between commands.
"""
from __future__ import annotations

from pathlib import Path

from .canonical import canonical, digest, loads
from .engine import Store
from . import graph_reachability as reference
from . import window_batch
from .graph_observer import ROOT, _hash_file, _integer

ADAPTER = 'native-graph-reachability-strict-batch/v1'
PROFILE_NAMES = ('legacy_scalar', 'strict_batch')
EXTRA_SOURCES = ('gabriel_runtime/batched_reachability.py',
                 'gabriel_runtime/window_batch.py')


def _sources():
    hashes = reference._sources()
    for relative in EXTRA_SOURCES:
        hashes[relative] = _hash_file(ROOT / relative)
    return dict(sorted(hashes.items()))


class BatchedReachabilityAdapter(reference.GraphReachabilityAdapter):
    """The v1 operational contract with one exact preparation per observation."""

    def __init__(self, executable, expected_sha256):
        # Same construction and first guard as the scalar profile. The closure
        # additionally binds both new modules at every original check site.
        self.executable = Path(executable).resolve(strict=True)
        if not self.executable.is_file():
            raise ValueError('explicit executable must be a regular file')
        if (type(expected_sha256) is not str or len(expected_sha256) != 64
                or any(c not in '0123456789abcdef' for c in expected_sha256)):
            raise ValueError('explicit SHA-256 must be lowercase hexadecimal')
        self.expected_sha256 = expected_sha256
        self.sources = _sources()
        self.arithmetic = reference._arithmetic_identity()
        self._check_identity()

    def _check_identity(self):
        if _hash_file(self.executable) != self.expected_sha256:
            raise ValueError('native executable identity mismatch')
        if _sources() != self.sources or reference._arithmetic_identity() != self.arithmetic:
            raise ValueError('bound reachability source or arithmetic identity mismatch')

    def fingerprint(self):
        result = super().fingerprint()
        result['adapter'] = ADAPTER
        result['model_preparation'] = 'once-per-observe-command;no-cross-command-cache'
        result['integrity_checks'] = 'original-v1-check-sites;full-content-hashes'
        result['batch_schema'] = window_batch.BATCH_SCHEMA
        result['reference_certificate_source_sha256'] = window_batch.REFERENCE_SOURCE_SHA256
        return result

    def apply(self, state, operation, payload, receipt_at):
        _integer(receipt_at, 0, 2**53 - 1)
        if operation != 'observe':
            raise ValueError('reachability supports observe')
        payload = loads(canonical(payload))
        self._validate(state, payload)
        candidate = loads(canonical(state))
        candidate['batches'].extend(payload['batches'])
        native = self._invoke(candidate['batches'])
        snapshot = reference.laplacian_for_certificate(native)
        self._check_identity()
        try:
            certificates = window_batch.certify_windows(
                snapshot, payload['source'], payload['targets'],
                payload['windows'], payload['threshold_bits'],
                precisions=reference.PRECISIONS)
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
        result = super().view(state)
        result['semantic_profile'] = ADAPTER
        return result


def make_profile(name, executable, expected_sha256):
    """Construct an explicit comparison profile; both retain the original Store."""
    if name == 'legacy_scalar':
        return (Store, reference.ADAPTER,
                reference.GraphReachabilityAdapter(executable, expected_sha256))
    if name == 'strict_batch':
        return Store, ADAPTER, BatchedReachabilityAdapter(executable, expected_sha256)
    raise ValueError('unknown reachability profile')
