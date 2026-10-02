# Exact materialization for the durable owner

`FastStore`, from `gabriel_runtime.fast_owner`, is an explicit execution alternative to `gabriel_runtime.engine.Store`. It accepts the same commands, adapter registry, limits and SQLite format. It leaves adapter algorithms, numerical recurrences, forecasts, feedback and proposal rules unchanged.

```python
from gabriel_runtime.fast_owner import FastStore
from gabriel_runtime.incremental import incremental_registry

with FastStore.create("new-session.sqlite", incremental_registry()) as store:
    initial_head = store.head
```

Use `FastStore.open(path, registry)` to open an existing store. Full semantic replay runs on every open, exactly as for `Store.open`. A store can be alternately opened by either class when its registry fingerprint agrees. The execution class is deliberately absent from the journal header: it implements the existing owner protocol rather than defining a new semantic profile. This does not authorize changing a fingerprinted adapter or relaxing its source and numerical-environment checks. Release manifests identify the alternative's implementation source.

## What changes

The reference's isolation primitive is `loads(canonical(value))`. Besides parsing, that path validates and serializes twice because `loads` validates its result by calling `canonical`. `checked_clone` instead validates and recursively copies the exact supported object domain in one traversal. It reconstructs dictionaries in sorted-key order, as the reference JSON round trip does. This ordering matters even for an adapter that inspects Python dictionary insertion order. Lists retain order, mutable aliases are expanded into independent copies, and immutable scalar values can be shared safely.

Accepted values are exact built-in `None`, `bool`, bounded `int`, ASCII `str`, `list` and string-keyed `dict` instances. Integer limits and maximum depth match `canonical.py`. Unsupported subclasses, floats, non-ASCII strings, non-string keys, cycles and excessive nesting are rejected. Parsing bytes read from SQLite still uses the reference duplicate-key-rejecting parser and canonical-text comparison.

For a non-binding command, the canonical state text just validated from SQLite supplies the pre-state SHA-256 digest directly. The post-state is canonicalized once; those exact bytes supply both its digest and persisted state. Adapter-returned text or hashes never substitute for this validation. Neither optimization carries a state cache across calls.

## Preserved boundaries

Every accepted unique command retains its own `BEGIN IMMEDIATE` transaction and durable commit. The SQLite `DELETE` journal and `synchronous=EXTRA` setting remain mandatory. Command identity, exact retry behavior, expected-head comparison, owner-clock order, event and byte budgets, immutable binding, atomic rejection, record hashes and full semantic replay are preserved. Returned values and adapter inputs remain isolated by copying. The same before/after-commit process-failure hooks are supported.

No transaction batching, deferred acknowledgement, weaker synchronization, skipped verification, numerical approximation, compiler extension or native dependency is introduced. Actual physical power-loss durability still depends on the storage system and SQLite VFS. Hashes provide integrity identities, not signatures or authenticated provenance.

## Refinement argument and limits

Let `C(x)` denote the reference `loads(canonical(x))` operation on an accepted exact-domain object. A structural induction proves equality of `checked_clone(x)` and `C(x)`, including container iteration order: scalar cases are unchanged, lists apply the induction hypothesis in order, and dictionaries apply it in sorted-key order. Both operations expand aliases rather than sharing mutable children. The argument assumes finite, stable input values during a call; the owner is a sequential API, not a concurrent mutation protocol for arbitrary Python objects.

For identical initial stores and trusted deterministic adapters whose outputs depend only on the supplied JSON values and container order, induction over accepted commands then gives identical post-state text, results, state hashes, records, receipts and metadata. This assumption excludes observing Python object identity, interning, reference counts, wall time, allocation behavior or external side effects. Immutable scalar object identity can differ from a JSON round trip; an adapter that uses string identity rather than string value is a counterexample to an unrestricted Python-level equivalence claim. Replacing a digest of a validated object by SHA-256 of its already validated canonical representation is an algebraic identity. Rejected commands roll back the transaction; exact duplicate retries return their previously stored receipt. The induction concerns normally completed operations in the same numerical environment; resource exhaustion and external storage faults are outside the equivalence statement. This is a mathematical implementation argument supplemented by differential and failure tests, not a machine-checked verification of Python, SQLite or the operating system.

This owner optimization is domain-independent. It can accelerate the current financial profile without improving prediction accuracy. Full-state storage, full views, adapter-internal copies and journal replay still scale with retained history. The implementation is bounded by the configured reference limits and is not an unbounded streaming system or a general throughput guarantee. PSE's graph, similarity, gate and spectral routines are not substituted for the owner's semantic checks.
