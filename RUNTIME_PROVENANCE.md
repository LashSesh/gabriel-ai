# Runtime extraction and integration provenance

The operational runtime is a new compositional implementation hosting existing
Gabriel numerical/domain algorithms. The English manuscript is the scientific
description; this file records development provenance and audit scope.

## Supplied source

The user supplied `ophan_bridge-main.zip`, whose root README identifies the
GRFPS second-layer perception profile 0.30.0. Source archive SHA-256:

`653ea8ef5cb23532675fd6a4336c16ea6b7988a68e08fccd921164b5a82784bc`

The archive contains 3,945 files and 944,305,168 uncompressed bytes, largely saved
JSON/JSONL histories and generated HTML. All 280 Python files, including nested
source copies, were mechanically parsed (23,611 lines; no syntax errors). This
inventory is not a claim that every line, every generated history or all attached
publications were semantically reviewed. The focused architecture audit names
the files and contracts actually examined.

## What was extracted

| Source mechanism | New runtime realization | Boundary |
|---|---|---|
| Pure candidate reducer and publish-after-journal | Local adapter interface and atomic SQLite command/state/result/log transaction | Local trusted code; no distributed consensus or external effects |
| Exact schema and canonical records | Strict ASCII exact JSON; duplicate-key rejection; canonical-byte retry identity | Hexadecimal binary64 encoding preserves representation, not real-arithmetic accuracy |
| Scoped evidence and current-view invalidation | Immutable per-module contract and explicit domain semantic profiles | No universal equation of physical truth, finite-model decision and forecast validity |
| Replay of state transitions | Recompute every transition, state hash, result and receipt | Reuses declared reducers; not an independent proof of their mathematics |
| Version/source binding | Relevant source fingerprints and fixed adapter registry | No authentication of a device or honest execution environment |
| Bounded accepted history | Owner event/byte limits and per-adapter operation caps | No CPU, throughput or hard real-time guarantee |
| Historical prefix replay | Optional expected terminal head and event-count anchor | The retained anchor itself requires trust |

The current upstream bank chain has 18 classes. It was not copied into Gabriel.
XR geometry, instrument calibration, browser transport and the generated galleries
remain source-domain components. They do not provide a financial predictor.

Two upstream boundary examples informed concrete checks: the historical Boolean
kernel compares retry dictionaries using Python equality (`True == 1`), and a
valid complete journal prefix remains internally replayable after deleting a whole
suffix. The new implementation uses canonical identity and supports separately
retained completeness anchors. The latter is a scope limit of internal replay,
not a claim that hashing alone can authenticate history.

## Direct reuse from Gabriel

The adapters import these existing local sources without modifying them:

- `finite_observation.py`
- `decision_regions.py`
- `sequential_contract.py`
- `maturity_ledger.py`
- `ecb_risk.py`
- `replay_adaptive_maturity.py`

The new adapter adds strict ingress validation, finite derived-score checks and
distinct declared-receipt versus historical-import issuance rules. The risk
controller is an execution reference from the existing research, not a newly
selected or recommended predictor. Forecasts and initial checkpoints are supplied;
this runtime slice does not generate an entire market strategy.

## Executed validation and retained evidence

`results/runtime_checks.json` records the fresh integration tests, their synthetic
inputs, source hashes, exact comparison rules and explicit non-tested scope.
`results/runtime_history_replay.json` records the archived financial preservation
study. `results/runtime_cli_checks.json` records the actual CLI subprocess checks.
The runtime demo is retained in `results/runtime_demo.json`; it uses synthetic
inputs and is regenerated through the supplied CLI.

`results/ophan_upstream_audit.json` records the fresh original 0.30 release gate:
1,026 Python tests and 937 JavaScript checks, semantic replay of 3,450 retained
transitions, and a separately executed CLI restart with two owner and three
producer processes. Historical producer/HTTP reports were not reexecuted, and no
headset, physical instrument or visual browser evaluation occurred. The source
gate ran in an isolated copy; all 276 top-level original Python files remained
unchanged. Additional scoped probes are recorded separately.

The upstream archive is identified above and remains the user's supplied source;
it is not vendored into the cleaned runtime or required to execute it. Repeating
the upstream release gate requires that original archive. Every dependency source
needed for the delivered runtime demo and integration checks is included. Python,
SQLite and declared numerical packages remain environment dependencies. The
complete research project retains the historical benchmark data; the compact
runtime distribution omits those archives and the historical replay driver.

## Literature and status

Event/processing-time distinctions follow established stream-processing work;
SQLite supplies transaction machinery. The paper cites primary Dataflow research
and official SQLite documentation. This implementation claims concrete component
preservation and tested fault handling. It does not claim priority for event
sourcing, transaction logs, idempotency or modular adapters, or improved predictive
accuracy. The current two-adapter migration is explicit; other Gabriel modules
remain in the research project pending their own integration contracts.

## Generated-stream integration

The subsequent stream profile closes an input-to-generated-forecast loop in
`gabriel_runtime/stream.py`. Its sources are the unchanged `ecb_risk.py`,
`severity_risk.py` and `aggregate_risk.py` implementations and the preceding
transaction owner. The new adapter invokes the base generator and projection/
scoring routines, and specializes severity and cumulative feedback into a fold
against immutable issued records. The correction-aware fold is newly implemented;
its regular uncorrected execution is compared with the original batch routines.
The existing numerical sources, `engine.py`, `canonical.py` and `adapters.py`
remain unchanged. The CLI adds an explicitly selected `stream` registry while
retaining the original default profile and source bindings.

Every new source index triggers feedback maturation followed by attempted forecast
generation. Both expert banks and aggregate weights are generated from received
records; no externally supplied forecasts enter this profile. Model-positive
forecast unavailability is explicit, and the originally positive scoring domain
is retained. The eight-expert bank uses the existing base, two severity memories
and cumulative aggregate at scale 0.1. This is an integration profile, not a new
parameter selection or a claim that the previously failed superiority criterion
has been satisfied.

A corrected source value changes current feedback and future inference; it does
not regenerate the original issue tape. A newly derived, conditional score bound
retains the signed difference between the gradient's original evaluation state
and the current replay state. The argument specializes standard convexity and
projection machinery. The explicit two-expert stale-evaluation counterexample
shows why discarding that term is invalid. It is a constructed mathematical
sequence, not an asserted reachable market trajectory.

Observation indexes are distinct from event and receipt timestamps. The temporal
basis is `next_unreceived_observation`; after maturity the result also reports
`target_after_issue`. Delayed ingestion may concern an event already completed
outside the store. This scope was identified during independent final review and
made explicit in the code, tests and manuscript. It is not a guarantee of genuine
future-event forecasting or authenticated source vintages.

The read-only exposure proposal uses an exact rational comparison of the dyadic
number represented by binary64 ES. It maximizes integer units under a declared
per-proposal log-loss proxy budget. It does not provide portfolio reservation,
external execution, realized-loss control or a rounding certificate for estimated
risk.

Fresh execution records are `results/stream_checks.json`,
`results/stream_history_replay.json` and `results/stream_cli_checks.json`.
The historical study uses only the original four currency columns and initializes
at the first eligible source prefix. It does not reuse the 2010 learner checkpoint
or introduce another market-selection experiment. The full original corpus is
retained; its older complete training runs are not repeated for this change.
The small runtime package includes the synthetic test closure and now requires
NumPy and SciPy; it omits the historical raw archive and replay driver.


## Incremental execution of the preserved stream contract

`incremental.py` adds an explicitly selected alternative evaluator for the existing `stream-risk/v1` semantics. The original owner, canonicalizer, research adapters, `stream.py`, and eight hosted research modules are unchanged. CLI profile selection and the synthetic demo helper are extended; default legacy/reference outputs remain checked.

The new evaluator reuses verified variance prefixes and immutable-issued feedback contributions, computes only the current six tail rows, replays affected aggregate lanes and the globally ordered severity suffix, and preserves historical finite-domain guards. Its cache is private, bounded, disposable and absent from accepted source state. Numerical equivalence is conditional on the fixed machine operations/environment and supported by executed exact-byte comparisons, not a machine-checked Python proof.

Executed independent checks are in `results/incremental_checks.json`; separate command-line checks and the generated example are in `incremental_cli_checks.json` and `incremental_demo.json`. The synthetic efficiency study retains `incremental_benchmark_protocol.json`, `incremental_benchmark_inputs.json`, `incremental_benchmark.json` and the executable driver. It compares both full trajectories and repeated terminal cases, including correction-then-append bundles so deferred variance repair is measured. A pre-timing protocol revision added those bundles and selected an early issued endpoint; no measured outcome informed it. No new market data, predictive parameter selection or reserved currency evaluation occurred.

The study demonstrates less repeated numerical work and measured speed gains in bounded synthetic histories. It also exposes persistent full-history array construction, canonical materialization and journal costs. Wall-clock repetitions include slower individual incremental cases; paired medians and full raw samples are retained rather than asserting uniform or production-wide speedup. The standard memoization/change-propagation idea is attributed; correction locality and the specific reference-equivalence argument are derived in the manuscript. See the separate review notes in `audit/` for access and verification scope.


## Equivalent owner materialization and the supplied PSE archive

The supplied `pse-standalone.zip` (SHA-256 `30d4a6aeab6c6509c0cc31fcf5b4be4fd3f95aec745127aa848c8ce37b7299ca`) is preserved at `audit/pse-standalone.zip`. It is a synchronous Rust graph-analysis pipeline, not an implementation of the durable Gabriel owner. Original archive metadata, scoped source reviews, actual build outcomes and counterexamples are retained separately. The earlier unpublished `_pse_forensics/` originals and comparison binaries referenced in its documents were not supplied or inspected.

Its useful execution principle is applied to Gabriel in `fast_owner.py`: remove repeated materialization while preserving an explicit reference. Checked structural copies preserve exact types, values, nested dictionary iteration order and mutable isolation for value-based adapters. Locally validated state text is reused for state hashing and storage. The original owner, exact codec, adapters, stream implementation, incremental implementation and eight research dependencies remain unchanged. There is no cross-call owner-state cache, weakened durability, grouped commit or skipped semantic audit. Registry profile and owner selection are independent; both owners deliberately use the same journal protocol and fingerprints. The new owner source is identified in release manifests and executed reports rather than falsely claimed to be bound by the unchanged original header.

This equivalence is conditional on stable data inputs, adequate resources and adapters that depend on values and container order. An executed Python scalar-identity counterexample documents the excluded introspection behavior. Independent checks compare complete stored rows and canonical receipts, exercise malformed data and process failures, and open each owner's store with the other. The new benchmark uses the already incremental numerical adapter on both sides, with its own retained synthetic seed and no new market evaluation. Its ratios cannot be multiplied with the previous experiment's ratios as an unmeasured combined speed claim.

The optional `native_pse/` fork retains its MIT license, all original mathematical routines and historical fixture. Its small-region signature path uses exact packed permutations and avoids discarded scan work. At that measured revision it was an auxiliary graph-analysis source without a Python-owner consumer. The later graph-observer integration below adds an explicit consumer while leaving the financial reducers unchanged. The finite signature proof and same-environment comparisons do not repair inherited heuristic or numerical claims. In particular, retained wall-clock branches prevent an unrestricted whole-engine determinism claim. The original cross-environment fixture disagreement remains visible, with cause unresolved. Begin with `native_pse/GABRIEL_REVIEW.md`, not an assumption that historical logs are new executions.

## Expected-byte replay and recovered finite indexing

The last unsaved execution environment was lost. The source baseline was
recovered from the saved archive with SHA-256
`2b4bfce4fa94482c9a86d2242157066c730f73be17f8978dbfe6cd20a05a9c4b`.
The new replay implementation, tests and benchmark are reconstructed and rerun.
The original reference numerical sources, FastStore and canonical format remain
unchanged. `audit/pre_replay_sources.zip` retains edited baseline documentation
and CLI files. Earlier unarchived timing summaries are not substituted for raw
measurements in this release.

`replay_owner.py` overrides only `_audit`. The CLI adds `--owner replay`; reference
remains default. Raw executed checks are `results/replay_owner_checks.json` and
`results/replay_owner_cli_checks.json`. Fresh benchmark inputs, protocol and
individual observations are under `results/replay_benchmark*`.

The finite graph table is freshly generated and exhaustively verified by two
standalone C++17 programs with distinct edge/matrix action implementations.
Fault tests and byte-identical regeneration are retained. The optional Rust
consumer and a new 256-entry-per-thread complete-signature cache are now built
and tested with Rust 1.95.0. Packed remains the default. Input validation precedes
reuse; labelled input plus n supplies exact identity for +0/1 matrices, and any
negative zero bypasses the cache. At that measured revision, original numerical/subgraph source files and
all ten Python runtime files remained byte-identical to the preceding archive.
Its exact measured source files are preserved in audit/native_indexed_measured_sources.zip.

The no-LTO workspace verification passes 449 tests with one documentation test
ignored and the preserved historical fixture explicitly filtered. Unfiltered
execution still fails that fixture. ThinLTO link attempts failed locally with
undefined symbols; the current release profile and all three new benchmark
builds disable LTO. Root-cause diagnosis and Rust1.89 support are not claimed.

The default comparison wrapper actually builds three binaries, checks complete
signature goldens and selected-state/complete-crystal engine goldens, and runs
16000 warm engine ticks,80 first macrosteps and114688 complete-signature calls.
Source and binary hashes, all parsed individual measurement records, retained
stdout/stderr and commands are under benchmark-results/indexed_engine/executed.
New matched comparisons are kept separate from the historical dense-to-packed
study. Cache hits accelerate only a bounded part of the native engine; collision
and first-call controls retain unfavorable results. Neither financial scores
nor Python owner performance are remeasured or claimed improved in this phase.


## Guarded spectral execution refinement, 26 September 2026

Two optional features add within-call CTQW mode-phase reuse and within-step
C16/C18 spectrum reuse. Defaults remain unchanged. The source audit is
`audit/phase_source_changes.json`; the original CTQW body is unchanged, while its
new noninlining attribute is shared by all current benchmark variants. The
previous measured native revision is retained separately so historical source
hashes are not falsely attributed to the current tree. All ten Python runtime
source files remain byte-identical to the preceding delivered archive.

An initial strict special-float test exposed a NaN sign mismatch. The failed
log is retained. A conservative finite-domain guard now delegates exceptional
and overflow-risk inputs to the reference; strict tests were not relaxed.
Final all-feature verification passes 461 tests with one ignored documentation
test and one filtered historical fixture. A final unfiltered run still fails
that fixture. CTQW tests cover 1,500 returned-result parameter cases and four
malformed-rank panic cases; topology/core reuse tests cover the retained spectrum,
complete serialized crystals, selected state, errors and size thresholds.

The executed `phase_engine` wrapper builds four matched no-LTO variants and
checks exact configuration and 19,658,993-byte serialized golden equality before
30 timed processes. There are 3,600 timed episodes and 43,560 measured commits.
The independent reporter recomputes all 30 paired summaries, reconstructs actual
induced graphs from public input and state, and checks every cache counter delta.
It verifies all 44 original individual command records and 88 captured streams
against redundant original bytes and recorded hashes. The aggregate command
index is an intact 43-entry prefix, not a complete index. Its cause is unknown;
all original individual records exist. The derived full index is explicitly
labelled and the original incomplete aggregate is preserved. No measurement was
invented, rerun to replace an unfavorable value, or reconstructed from a summary.

The timing study uses forced commits, complete-region fast-path extraction and
suppressed morphology, on sparse paths and monotone acquisitions at n=3/5/7/8/16.
It is not a default-workload or external application benchmark. No CPU affinity,
frequency locking or memory measurement was used. The binary64 preservation
statement requires repeatable scalar functions; the portable Rust API does not
supply a universal NaN or sin/cos bit guarantee. Existing wall-clock branches,
spectral/clustering model defects and historical fixture failure remain open.

## Conditioned-state API phase

At the conditioned-state API revision, the native module was an explicit additive API; ten Python runtime sources and all existing topology bodies remained byte-identical to the preceding release, except the documented module export. Default Cargo features did not change. `audit/conditioned_source_preservation.json` and `audit/conditioned_runtime_preservation.json` retain the checks. D6 helper ordering/invalid-axis behavior is deliberately corrected; it is unused by current signature consumers.

Measured source identity, protocol, raw states,11 command records and 22 streams are under `native_pse/benchmark-results/conditioned_walk/executed/`. The incomplete 10-record aggregate remains original. `results/native_conditioned_commands_derived.json` is explicitly reconstructed from the original individual records, with source hashes; no command metadata or timings are fabricated. The reason for the missing final aggregate entry is unknown.

`native_phase_measured_sources.zip` preserves the 77 files for the earlier phase-hoist/shared-spectrum experiment; the historical reporter now verifies those exact bytes if the current tree differs. Those historical conditioned timings have their own 76-source guards; the exact measured files are now preserved in `audit/native_conditioned_measured_sources.zip`, and their reporter verifies that archive when the current tree differs. The full native test suite and separately failing original fixture are captured under `conditioned_validation`. A first fixture-target attempt selected the wrong package and ran zero tests; it is not counted as a pass. The independent SciPy calculation and source review are further checks, not hardware experiments or certified rounding bounds.


## Engine observer and durable graph-profile integration

The public `Engine::conditioned_snapshot` method now constructs the observer from
the Engine's actual labelled persistent graph. It retains a snapshot identity,
explicit normalized complex source, target-region selection and stable vertex
mapping. Region queries have three matched implementations: full spectral state,
strict complete-graph state specialization, and complete-graph scalar region
readout with a full-state fallback. Source normalization is part of this observer
contract; the older low-level conditioned-walk contract remains separate.

The `gabriel_runtime/graph_observer.py` adapter connects that API to the original
`gabriel_runtime.engine.Store` through `native_pse/examples/engine_observer.rs`.
Its full batch history and issued query results participate in the existing
atomic transaction, immutable journal, retry and semantic replay contracts.
Every accepted append/query starts a fresh trusted native process, replays all
retained batches, and binds output to current source and executable hashes.
Source and executable hashes are consistency identifiers; separate captured
build commands establish the recorded build provenance. The original Python
owner and financial prediction/reducer routes remain unchanged. No speedup of
FastStore or the other owner variants is credited to this reference-owner run.

Native validation is captured under
`native_pse/benchmark-results/engine_observer_validation/`: 492 tests pass, one
documentation test is ignored and the preserved historical fixture is explicitly
filtered. Its separate selected execution fails. The fixture is not changed.
Independent results are `results/engine_observer_checks.json` and
`results/engine_observer_summary.json`. They verify 77 measured source files,
11 original command records, 22 streams and a complete aggregate command index.
Seven fresh benchmark processes execute 2,520 complete Engine tasks and 229,320
scalar queries. For complete graphs at 256 query times, total-task median ratios
against full spectral execution are 2.034–3.114. The 2,056 full-state and 408
diagnostic reference states, induced graphs, source/target identities, timed
scalar outputs and all summary ratios are independently recomputed. Observed
maximum SciPy differences are below 7.059e-13 per complex component and
3.302e-13 for region mass.

The complete durable workload is captured under
`native_pse/benchmark-results/graph_observer_owner/executed/`. Five fresh workers
execute 360 full adapter/create/bind/ingest/query/close tasks, producing 46,260
checked timed scalar outputs. Source guards cover 80 files; all five command
records and ten streams are present. Independent reporting recomputes 1,024
SciPy states and every archived summary. The complete 64-node, 256-query task
has a median paired full-spectral/direct-region ratio of 1.0577, with worker
medians from 1.0220 to 1.0728; other cases remain near one. This measured boundary
includes repeated Engine reconstruction, process startup, serialization, hash
checks and SQLite EXTRA commit. It demonstrates a working durable consumer and
a small scoped execution gain, not general forecast-quality superiority.

One intentionally retained final SQLite database matches its recorded byte hash
and passes anchored semantic replay using the original executable. Another 32
unexpected SQLite files are present where the benchmark intended temporary
files to be removed. They are structurally valid and match prefixes of captured
command histories, but differ from the recorded final byte hashes and event
counts. They are preserved as unexpected residues and excluded from completed
persisted-state evidence. Their cause is undetermined; the verification does not
reinterpret these prefixes as successful final checkpoints. The raw timing and
scalar-output streams remain independently checked. Exact per-file findings are
retained in `results/graph_observer_owner_checks.json`.

The original measured Linux x86-64 CLI is distributed as
`native_pse/benchmark-results/graph_observer_owner/executable/engine_observer_linux_x86_64.bin`
with SHA-256
`629b13f23fad4a4e8142eb7345e5bb2ca36dce508fb364758d76050d096300b1`.
Its production build command and output streams are retained alongside it.
After extraction, restore executable permission with `chmod +x` and verify its
hash before use. The path may change while identical bytes retain their semantic
fingerprint. Exact numeric replay requires the same numerical environment;
a rebuild or different math environment may legitimately fail the original
fingerprint or bitwise replay check. A fresh rebuild can generate new journals
and measurements, which must retain their own provenance. README.md provides
commands for demo, audit, functional checks, independent reporting and fresh
benchmark runs.

Historical measurements remain tied to their own source snapshots. In particular,
`audit/native_conditioned_measured_sources.zip` preserves all 76 files measured
by the preceding conditioned-state kernel study. Its 3.421–63.879 query ratios
are not measurements of the new Engine/durable workflows and are not multiplied
with their ratios. The phase/spectrum and indexed studies likewise retain their
original guards and archived measured sources.

## Targeted persistence verification


A targeted follow-up replays all 32 affected command sequences into new retained
stores. Both workspace batches initially reproduce every final receipt and
SQLite image byte-for-byte and pass immediate reopening. Later checks find
2/32 and 5/32 images at earlier valid prefixes, including a batch without
concurrent workspace operations. The same unchanged verification outside the
workspace passes all 32 after-batch and subsequent fresh-execution checks.
This is an observed storage-location contrast; the mechanism remains unresolved.
The checks generate no new performance claim. Unrestricted persistence reliability
in the benchmark environment is not established. All three runs are sealed in
`audit/engine_observer_residue_replay_{failed,isolated_failed,outside_passed}.zip`;
`audit/engine_observer_persistence_location_check.json` records their hashes,
comparison and final outside-workspace checks. The executable reproduction is
`reproduction/check_engine_observer_residue_replay.py --help`; choose a new output
directory and retain both success and failure results.

## Exact-input window certificate profile

The current additive production sources are `window_certificate.py`,
`graph_reachability.py`, and native `examples/engine_snapshot.rs`. All 69 existing
point-observer production fingerprints remain byte-identical to the input
archive. Final new source and arithmetic hashes are retained in
`audit/graph_reachability_functional_summary.json`; old and new journals remain
separate numerical contracts. Final-source semantic replay checks 3 new and 3
historical backend databases against external anchors.

The frozen protocol preceded all cohort execution. Initial semantic evaluation
is retained; the final cap repair and pre-timing baseline fairness amendment are
explicit in audit records. The final 852 certificates, 11,520 timed calls and
negative registered outcome are preserved without case exclusion. Root-level
independent algebra/complex-Arb verification and owner result binding are in
`results/window_reachability_verification.json` and
`results/reachability_owner_verification.json`. A shared trusted Arb dependency
remains; these checks do not constitute proof-assistant verification.

Live databases were generated only outside automatic workspace mirroring.
The 24 complete owner runs and closed bytes are sealed in
`audit/reachability_owner_closed.zip`; the separately archived executed collector
is byte-identical to its reproduction source. Byte/anchor rechecks passed.
The observed `fsync=volatile` overlay precludes a power-loss durability claim.
The earlier unexplained prefix failures remain part of the evidence. New 60-file
paced/burst controls and 3 synthetic detections narrow the environment boundary
but do not attribute those historical failures.

## Strict model batching and complete-owner comparison

This extension preserves all 72 original reachability production files and adds
`window_batch.py` and `batched_reachability.py` to its own 74-file source closure.
The original Store and native executable are unchanged. The full frozen protocol
is `results/epoch_owner_protocol.json`; inputs and pre-measurement source freeze
are in `results/epoch_owner_study`. The measured binary SHA-256 remains
`f47f01b1f14c53184ccd5abdf22e01865d750a7b513f7acd6ec1e1a6a833aa93`.

Three serial fresh workers executed 240 complete creation-to-closure tasks and
240 separately timed full semantic replays. The primary paired median was
1.0213144699872245, failing the broad >1.10/each-size criterion; the prespecified
32/64-node and 16/32-window subgroup reached 1.2661148583170005, passing its
separate workload-specific criterion. The archive retains every measurement,
closed database and independently stored anchor. Filesystem caches and CPU
frequencies were uncontrolled; no hardware-normalized guarantee is made.

Independent validation reconstructed all fixture rules, checked 3336 emitted
certificate objects against mathematically verified fixture answers, validated
all 240 stored journals and executed 240 additional fresh native semantic replays.
The archive digest and detailed counts are recorded in
`results/epoch_owner_study/independent_verification.json`.
`audit/strict_batch_owner_measurements.zip` contains the sealed raw experiment.
The inherited Arb/Python trusted base and volatile-filesystem restrictions remain.
No new prediction model or external-data study was executed in this extension.
