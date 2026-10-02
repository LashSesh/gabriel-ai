# Phase-engine harness review

Scope: read-only reinspection of the frozen phase-engine harness, wrapper,
feature wiring and cache contract. No native build, simulation or timing was
performed for this review. The reviewer also authored the initial harness;
this is a second-pass audit, not an independent-author validation.

## Finding

No blocking defect found for the declared measured intervals and **serialized
output equivalence** claim. Four qualifications below must remain explicit.

1. **Timer boundary.** `once` constructs the engine and executes all public
   bootstrap macro-steps before the timer. Cold acquisition then clears the
   signature cache, and cache statistics are sampled before the timer. The
   measured loop includes complete `macro_step` calls, result unwrapping,
   `black_box` and dropping each returned value. The elapsed interval ends
   before cache-statistics reads, shape assertions, JSON construction and
   serialization. It therefore measures complete committed macro-steps in
   the specified episode segment, not process startup, bootstrap, persistence,
   or the whole life cycle of the fresh engine.

2. **Matched features.** `indexed-engine` enables only the finite graph index.
   `hoisted-engine` adds core/topology `phase-hoist`; `shared-engine` adds
   core/topology `shared-spectrum`; `memoized-engine` adds the existing exact
   signature cache. Core forwards both new features to topology, and the
   public `macro_step` chooses spectrum reuse when the sharing feature is
   compiled. Separate Cargo invocations preserve each executable immediately,
   and their recorded hashes are checked after measurement. Each of the
   three pairwise comparisons changes exactly one declared mechanism.

3. **Cache regime.** A repeated-path bootstrap ends by computing the exact
   path signature for fixed n, so the measured unchanged-topology calls can
   hit even on the first measured tick. Cold acquisition resets entries and
   counters only after the public singleton bootstrap; distinct successive
   edge additions produce distinct full labelled keys. Rust assertions require
   12 measured hits and zero misses for eligible repeated paths; all measured
   cold acquisitions must be misses; n>7 must make no signature-cache calls.
   The golden traces independently expose actual region order and adjacency
   bits, and the wrapper verifies their distinctness. A fresh engine alone
   never means a fresh thread cache. Likewise, **cold acquisition means a
   cleared signature memoizer, not cold code, allocator, graph-index pages,
   process, filesystem or hardware caches**. Cache-reset cost is excluded.

4. **Golden scope and NaN limitation.** The four golden subprocesses compare
   the entire emitted JSON byte sequence, containing every serialized crystal
   field plus the explicitly selected prior state fields on all 233 public
   input steps. This is a strong serialized-behavior check. It is not a
   complete `GlobalState` comparison and does not independently establish
   arbitrary binary64 bit identity: serde_json's Value serializer converts
   nonfinite floats to null. Distinct NaN payloads (or distinct nonfinite
   values) could therefore collapse to the same JSON. The harness does not
   explicitly certify finiteness of every state field. Report **complete
   serialized crystal and selected-state bytes agree**, and attribute the
   separate CTQW bit comparisons to their dedicated tests. Do not upgrade the
   engine golden result into an all-state bitwise or all-input proof.

## Acceptance and data integrity

- Required subprocess stdout must be nonempty; build stdout is allowed to be
  empty. Nonzero exits, timeouts and command-launch errors stop the wrapper.
- Captured byte buffers are written only after subprocess completion, using a
  temporary file and replacement; every write is immediately reread.
- Original stdout and stderr are also stored losslessly as base64 in
  `captured_records.json`, including on a wrapper failure via `finally`.
- Every capture is reread and checked before results acceptance. Source/input
  hashes are checked before builds, immediately before timing and afterward.
- Python correctness gates use explicit exceptions, not optimizable asserts.
- Five alternating paired process ratios are reported with median/min/max.
  Twelve inner repetitions improve within-process sampling but do not create
  twelve independent hardware environments. The protocol makes no confidence
  interval, representative-traffic or application-wide speedup claim.

## Remaining execution gate

All four builds, graph assertions, exact goldens and timed executions still
need to pass under root's central run. This review does not claim they have
already passed.
