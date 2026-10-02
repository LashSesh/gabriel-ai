# Strict batched reachability

`native-graph-reachability-strict-batch/v1` reuses one validated exact model
across the time windows of an atomic `observe` command. It has the same closed
window proposition, precision ladder, per-window work caps, 64-node limit,
128-batch history limit, and 32-window lifetime capacity as
`native-graph-reachability/v1`.

The optimization removes repeated represented-matrix decoding, exact clique
recognition, source normalization, regional coefficient construction, and model
serialization. Each window still runs the original numerical decision logic
and returns its complete original certificate, including evidence and resource
counters. Window order and repeated windows are preserved. A model is discarded
after the command; there is no cross-command model or certificate cache.

Both profiles use the existing `Store` without modification. Every observation
reconstructs the native Engine from its full batch history in a fresh process.
The original source, arithmetic-library, and executable content-hash checks
remain at their original boundaries. The new profile adds
`batched_reachability.py` and `window_batch.py` to its source closure, checked at
every original source-check site. The preparation helper additionally checks
the frozen scalar certificate source. No checks become modification-time-only
checks, and no assumed immutable epoch suppresses a content sweep.

For a fresh construction, Store creation, binding, and one successful
observation, the full identity guard is called eight times: construction;
creation fingerprint; binding fingerprint; observation fingerprint; before and
after native execution; before and after certification. Initial construction
also captures the source and arithmetic identities. The post-certification
guard runs in `finally`, before the inherited Store can write and commit the
accepted transition. These are integrity identifiers for trusted local code,
not authentication or protection against arbitrary code execution in the same
Python process.

## Use

```python
from gabriel_runtime.batched_reachability import make_profile

StoreClass, name, adapter = make_profile(
    "strict_batch", executable_path, executable_sha256
)
with StoreClass.create(database_path, {name: adapter}) as owner:
    # Submit the existing bind/observe command schema using adapter name `name`.
    ...
```

`legacy_scalar` selects the unchanged original adapter and Store for matched
comparisons. The two profiles produce identical semantic observation issues
for identical inputs and receipt times. Their registry fingerprints, bind
results, and journal heads differ intentionally. Open a journal with its exact
original registry; no cross-profile journal migration is implemented.

## Verification and scope

`reproduction/check_window_batch.py` checks certificate equivalence, copied
decision-body correspondence, invalid inputs, and prepared-model isolation.
`reproduction/check_batched_reachability.py` checks the complete native/Store
path, guard-site trace, one preparation per command, rollback, full-history
replay, idempotent retry, source closure, and complete certificate equality.
It performs no performance measurements. Its mutation controls change a copied
executable or bound expected identities; they do not alter shared dependencies.
`reproduction/check_batch_protocol_guards.py` separately executes conflicting
command-ID, stale-head, wrong external-anchor, and valid-prefix rollback
controls. It checks that rejection preserves database bytes and that the final
journal remains usable under its independently retained head and event count.
A valid prefix passes unanchored semantic replay; final external anchors detect
the synthetic rollback.

This remains the exact represented uniform-clique model. Unsupported valid
graphs return `out_of_scope`; a shared preparation does not extend the
mathematical scope. Speed depends on windows per command and the fraction of
complete cost occupied by preparation. Complete native execution, content
hashing, serialization, and SQLite costs remain. No forecast-quality or
general-system superiority claim follows from reuse alone.

Keep mutable SQLite databases outside automatically mirrored directories.
Publish only closed snapshots with external head/event anchors as described in
the existing runtime documentation. The batching profile introduces no new
storage durability claim.
