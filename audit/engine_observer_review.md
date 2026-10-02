# Independent review: conditioned engine observer

Status: source review and independent numerical/provenance checks completed. Native task acceleration is supported within the measured workload. Complete durable-owner acceleration is small or absent for most cases. The unexpected SQLite-prefix residues described below remain an unresolved artifact-management observation.

## Scope and boundary

The reviewed task is a public `Engine::step` ingestion followed by an immutable,
labelled graph snapshot, explicit complex source, fixed target region and scalar
readout with a declared deadband. Runtime cost comparisons apply to that composite
observation task. They do not establish faster legacy crystal commits, predictive
accuracy, market superiority, or a physical quantum implementation.

## Source inspection completed

- `ConditionedSnapshot::from_graph` uses the existing `compute_laplacian` producer:
  `(W+W^T)/2`, omitted self loops and inclusion of inactive vertices. It rejects
  negative/nonfinite raw weights before the producer's clipping could hide them.
- The native vertex iteration order is shared with the Laplacian constructor.
  Node labels and the reverse ID map are cross-validated before preparation.
- A snapshot owns its Laplacian and evolution plan. Its tick, node labels and
  represented Laplacian bits enter a domain-separated SHA-256 identity. This
  identity does not purport to hash the whole engine or observation provenance.
- A 512-vertex cap is checked before the dense plan allocation. Empty graphs,
  malformed graph maps, unknown/duplicate source labels and zero sources have
  explicit failure paths. Named dense sources must name every vertex once.
- Full readouts use an initial norm denominator and expose a norm ratio rather
  than renormalizing away numerical drift. Such a ratio is diagnostic, not an
  error certificate.
- The initial API additions do not alter `Engine::step`, calibration, legacy
  topology functions, default feature selection or the old conditioned kernel.

## Material issue found and corrected before measurement

For a subnormal original source, forming the mean before rescaling can lose the
entire mean. The counterexample from the independent mathematics reviewer is
`psi=(minimum positive subnormal,0)` on two vertices with unit symmetric edge
weight at time `pi/2`: the prior unscaled kernel's normalized full readout can
remain at its initial vertex while its norm ratio still equals one. A direct
readout assembled from scaled coefficients gives the correct transferred mass.
This is a genuine numerical counterexample; a norm-only check cannot detect it.
The observer now validates the original finite nonzero source, divides by its
maximum component magnitude, normalizes the scaled vector, and only then prepares
the existing walk kernel. Its explicit API returns normalized amplitudes. All
full and regional paths use that same normalized source. The lower-level
arbitrary-norm kernel is unchanged. A Rust regression test covers minimum
subnormal, minimum normal, unit and maximum-finite source magnitudes; its
execution passed in the retained native workspace log.

## Fixed-region readout and policy

The recognized clique has two subspaces. The implementation's cross coefficient
uses the sign appropriate to `exp(-itL)`: with `c=conj(mean)*sum(residual_i)` it
computes `m(0)+2 Re(c)(cos(nwt)-1)/N+2 Im(c)sin(nwt)/N`. The anchored form uses
`cos(theta)-1=-2 sin(theta/2)^2` to avoid the avoidable zero-time cancellation.
Target labels are validated and their indices sorted at preparation; empty and
full regions, stationary sources and a complex interference-sign case appear in
the tests. The direct path returns a scalar mass only; it does not pretend to
measure a full-state norm ratio. Generic graphs fall back to the full state.

Finite binary64 arithmetic and phase reduction remain approximate. There is no
uniform-in-time error enclosure. Values near a boundary can differ by rounding;
a deadband is a declared policy, not certified uncertainty or predictive confidence.
The benchmark's explicit source and target selection define a synthetic task.
Uniform sources, real zero-mean clique sources and source-excluded one-hot clique
vertices are degeneracy controls, not evidence of richer clique discrimination.

## Timing boundary correction

Inspection found that response vectors survive the total timer, contrary to an
initial protocol sentence about including their destruction. The protocol was
corrected before measurement: response construction and `black_box` are timed,
while later response serialization/destruction is excluded. Engine/snapshot/source
teardown remains in total latency. Every variant produces the same scalar task
outputs, which remain available for independent verification.

## Durable owner bridge inspection

The new adapter uses the unchanged SQLite owner with bounded history and query
counts. Float quantities cross the exact-JSON boundary as finite IEEE-754 bit
strings; native vertex IDs are strings, avoiding the owner's integer limit.
Commands use an explicit local executable, no shell, finite timeout and bounded
input/response reads. Anonymous files avoid unbounded in-memory stdout capture.
The executable is trusted code; hash guards are neither authentication nor a sandbox.

The absolute executable path was removed from semantic fingerprint identity;
the functional checks successfully replayed journals after moving identical binary
bytes. The explicit executable SHA and source hashes remain bound. Exact replay still depends on the same numerical execution environment:
source and executable hashes do not guarantee identical libm/eigensolver output
bits across operating systems or runtime changes. Nor do the hashes prove that a
binary was compiled from the adjacent source. These boundaries must be documented.

## Executed independent checks

The reviewer implemented and actually ran both independent readers. Neither imports
the timing harness or its aggregation function. The native reader reconstructs
engine graph ingestion, FNV vertex IDs, symmetric Laplacians, snapshot SHA-256,
caller sources, stable normalization, target sets and all time points. The durable
reader independently reconstructs the same inputs and verifies bit-encoded source,
time and mass values, command/receipt digests, individual task records and timing
summaries. Both readers check the exact aggregate against the separately recorded
collector aggregate.

- Native capture: 77 source files; 11 command records and 22 streams; seven fresh
  processes; 840 three-variant batches; 2,520 complete Engine tasks; all 229,320
  timed scalar outputs checked against retained functional outputs. Every batch
  with 256 queries uses 256 distinct times.
- SciPy: 2,056 primary full-state references plus 408 source-control references;
  maximum observed complex-component error `7.058216575058414e-13`; maximum region
  mass error `3.3018032752352156e-13`. The predeclared independent acceptance
  tolerance is `2e-9`; the measured error is not a formal rounding enclosure.
- Native Auto/Spectral maximum real-component difference is
  `1.7008616737257398e-13`; maximum scalar-variant difference
  `3.7192471324942744e-14`; maximum norm-ratio drift
  `1.7763568394002505e-15`. Reordered ingestion agrees by vertex identity within
  `2.169847337960556e-13` complex-component difference.
- Native workspace log hashes and summaries were independently checked: 492
  passed tests, one ignored doctest and one explicitly filtered historical
  fixture. The historical fixture was separately executed and failed with exit
  101. The lower-level conditioned kernel and topology source also match the
  retained pre-integration measured-source archive byte for byte.
- Durable capture: 80 source files; five command records and ten streams; five
  fresh workers; 360 full create-to-close tasks. All 46,260 timed scalar answers
  were checked against 1,024 independently recomputed SciPy state references.
  Scalar and cross-variant error maxima match the native experiment's values.
- Every archived native and durable timing summary was independently recomputed
  exactly. Observed process ranges are not confidence intervals or tests of
  significance.
- The retained first SQLite database matches its originally recorded size and
  SHA-256. The reviewer independently reopened it using the exact packaged CLI
  binary, checked the external head/event anchor and reran semantic replay. It
  passed with three events; the database bytes remained unchanged afterward.

## Comparative result and scope

For 256 distinct scalar queries on Engine-produced cliques, complete native task
latency improves by median factors 2.034, 2.726, 3.114 and 2.588 for 7, 13, 32 and
64 vertices. One-query task factors are only 1.060–1.192. Generic path and
near-clique controls show approximately unit ratios. The largest query-only ratio,
50.98 for 64 vertices, is not a whole-task speedup.

The complete SQLite workflow largely absorbs the kernel gain. The 64-vertex,
256-query case has median factor 1.0577 with observed worker range
[1.0220,1.0728]. The 13-vertex,256-query case has median 0.9885 with range
[0.9743,0.9952], a small slowdown. Most other cases remain near one. These results
support an integrated native task optimization and identify process, identity-check,
history-replay and durable-storage overhead as remaining costs. They do not support
predictive superiority, a financial-platform comparison or a universal architecture
advantage.

## Unexpected unretained SQLite prefixes

The first durable-reader execution correctly stopped because 32 databases marked
`database_retained=false` still existed even though the measured collector source
calls `unlink()` after recording each closed final database hash. Their present
sizes and hashes do not match the recorded final databases. No numerical record,
command capture or timing aggregate was modified to address this observation.

A separate read-only inspection found all 32 present databases structurally valid
and equal to strict prefixes of their corresponding captured task command lists.
Each stored prefix head equals the next captured command's `expected_head`; none
contains the final query. The intended retained database is unaffected and matches
its final recorded hash exactly. The cause of the extra prefix artifacts is
undetermined; no filesystem, synchronization or other causal mechanism has been
established.

The independent durable reader now records each residue's present and final
recorded hashes, sizes and prefix-event counts, and explicitly excludes these files
from final-database evidence. It still verifies all complete primary command/receipt
and timing records. The raw residue files remain unchanged. The complete manifest
is in `results/graph_observer_owner_checks.json`. The result is therefore not a
claim that all 360 final database files remain available or were individually
reopened; only the deliberately retained database was independently replayed.

## Reproduction

Executed successfully, with `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1`:

```sh
python reproduction/report_engine_observer_results.py
python reproduction/report_graph_observer_owner_results.py \
  --executed native_pse/benchmark-results/graph_observer_owner/executed \
  --executable native_pse/benchmark-results/graph_observer_owner/executable/engine_observer_linux_x86_64.bin
```

The first failed residue-inventory check and the subsequent qualified verification
logs are preserved in `audit/engine_observer_independent/`. The separate
`audit/engine_observer_sqlite_residues.json` records filesystem timestamps and
source-path inspection: all residue modification/status times precede the first
independent reporter. The first failed reader had not reached any `Store.open`,
and the qualified reader inspected residues only with SQLite `mode=ro`. One
residue status-change time follows its own worker completion by about 0.47 seconds;
this observation does not establish a cause. No new performance
measurement was generated by either independent reader.

## Targeted persistence follow-up: a stronger unresolved limitation

The earlier residue qualification was followed by a concrete replay experiment.
`reproduction/check_engine_observer_residue_replay.py` replays exactly the 32
captured tasks affected by the original prefix residues. It uses the existing
Store and the original hash-verified native CLI, with no runtime changes and no
benchmark collector import. Each task uses a fresh database, compares its final
receipt byte-for-byte with the original capture, compares its closed final database
hash with the original recorded final hash, and reopens it for an externally
anchored semantic audit. All resulting databases are retained. A second pass
checks every final database after the other tasks finish.

Three actual runs give the following outcome:

| Output location and execution condition | Immediate exact final receipt/database matches | Final databases unchanged after all tasks |
|---|---:|---:|
| Workspace, ordinary concurrent workspace activity | 32/32 | 30/32 |
| Workspace, all other workspace commands suspended during the run | 32/32 | 27/32 |
| `/tmp`, all other workspace commands suspended during the run | 32/32 | 32/32 |

In both workspace runs, affected databases passed immediate close/reopen audit
and initially had the exact original final hash. Later inspection found valid
earlier command prefixes instead: two files in the first run and five in the
isolated repeat. Thus this is a persisted-state integrity failure in the observed
workspace runs, not merely the unexpected survival of deleted temporary files.
The isolated repeat establishes that concurrent root/agent workspace commands are
not necessary for the failure. Every original capture, original residue, runtime
source and executable remained byte-identical during the verification runs.

The unchanged verifier and inputs passed when only the database output location
was moved outside the workspace to `/tmp`. A fresh separate tool execution then
rechecked all 32 outside-workspace final database hashes and anchors; another
later tool execution checked the same 32 hashes again successfully. These results
establish an observed location-dependent contrast. They do **not** establish the
root cause, a repaired workspace persistence mechanism, or a universal durability
guarantee. The native numerical results and recorded latency measurements are
unchanged. Production-grade persistence under the affected storage conditions
remains unverified.

Source inspection found explicit connection closure in `Store.close` and
`Store.__exit__`, closure on `Store.open` failure, no delayed asynchronous Store
writer, and no SQLite access in the native graph subprocess. The verifier's
separate SQLite inspection opens `mode=ro` and performs no data modification;
its connection context manager can leave read handles for garbage collection,
but no source-level path writing an earlier database prefix was identified.
This source review is not a causal diagnosis of the underlying storage behavior.

All three outcomes, including failures, are preserved in sealed archives with
per-file SHA-256 manifests, original verification scripts, logs, receipts,
database bytes, and post-run integrity records:

- `audit/engine_observer_residue_replay_failed.zip`
- `audit/engine_observer_residue_replay_isolated_failed.zip`
- `audit/engine_observer_residue_replay_outside_passed.zip`

Each archive was closed, copied atomically, hash-checked, and independently
reopened in a fresh tool execution for CRC and every payload-hash check.
`audit/engine_observer_persistence_location_check.json` records the comparison;
`audit/engine_observer_persistence_seals_verified.json` records the later archive
and outside-database checks. The original numerical/timing captures and original
prefix files were not changed. These replay verifications generated no new
performance claim.
