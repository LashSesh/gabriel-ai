# Optional PSE graph-analysis component

Read this document first for the scope of the Gabriel copy. The other supplied
README, architecture, API and benchmark documents describe the inherited
repository and remain source evidence; their historical or scientific claims
are not automatically endorsed by this review.

This is a narrowly accelerated copy of the supplied PSE standalone repository.
It is an optional graph-analysis component, separate from Gabriel's durable
transaction owner and financial forecasting adapters. It is not required to
run the Python Gabriel runtime.

The upstream mathematical model is preserved. “Crystal”, “resonance”, “Granger”,
“proof” and similar inherited names denote this model's data structures and
heuristic features; they are not general scientific correctness guarantees.

## Execution change

`pse-metatron/src/small_signature.rs` computes the engine's complete signature
for simple undirected graphs of at most seven vertices by exact integer S7
permutations. It preserves the legacy row-major canonical matrix ordering and
hash, and retains the original spectral and Platonic computations on the same
input. The dense reference API remains available unchanged. The engine's
global attachment path uses this shortcut and returns before cache initialization
for ineligible regions.

The signature retains the inherited 64-bit FNV padded-adjacency identity. In
particular it omits original vertex count from the hash, so edgeless graphs
with distinct sizes collide. Do not use hash equality as a graph-isomorphism
proof or as an authorization to reuse a Gabriel transition result. Other model
limits are recorded in the separate source review.

## Reproduction

Use the included Cargo.lock and the specified Rust toolchain. External crates
are resolved by Cargo; the package contains all local workspace crates.

```sh
cargo test --release --locked -p pse-metatron small_signature
cargo test --workspace --release --locked -- --skip full_state_matches_original_golden_fixture
```

The second command explicitly excludes comparison against the supplied
Windows-generated golden fixture. The unchanged upstream's current Linux
execution differs in 23 of 78 recorded engine-state hashes and one crystal
hash. The cause is unresolved: the supplied historical hashes do not expose
the underlying values or establish whether platform arithmetic, ordering or
another difference caused the mismatch. The fixture is retained unchanged.
Current-platform original-versus-fork comparisons test the optimization
separately. Do not interpret the exclusion as a passing full test suite or
as evidence that the historical mismatch has been explained.

The focused tests cover all 1099 labelled simple graphs through five vertices
against an independently indexed permutation action, 48 seeded graphs at six
and seven vertices, nine complete dense-reference signature comparisons,
invalid inputs and the inherited padding collision. Commands are reproducible
checks, not a universal proof for floating-point libraries or all hardware.

The original files directly in `benchmark-results/` are inherited evidence
from the supplied archive. New same-host paired measurements and execution
logs are in `benchmark-results/gabriel/`; begin with its README.md. Separate
verification results also reside in the enclosing project's results/audit
material. No inherited number becomes a newly reproduced result merely by
shipping this folder.

## Scientific and operational scope

The review does not certify the complete PSE model. Among the inherited limits,
the navigator's Betti formula is incorrect for filled simplices; the PoR state
machine is not advanced by the main engine; eight marginal quantiles do not
calibrate the conjunction's pass probability; morphogenic IDs can collide;
and full crystal metadata are not all covered by the crystal ID. The multiscale
component still contains elapsed-time branches. The signature equivalence
argument therefore does not prove complete-engine equivalence for all inputs
and execution schedules. Successful current-platform engine comparisons are
finite executed checks, not an unconditional mathematical replay guarantee.

The new focused test run passed five tests. The current Linux workspace run
with the explicit historical-fixture exclusion passed 438 tests, with one
inherited doctest ignored. A preceding build encountered a linker error in
an unchanged component; the subsequent command completed without a scientific
source change. Both logs are retained in the enclosing audit folder. No
cross-platform frozen-fixture success or scientific peer review is claimed.

The detailed review with source locations and exact reading coverage is
`../audit/pse_core_review.md`; new test metadata are in
`../results/native_pse_refinement_checks.json`.

## Addendum: determinism and the specified readout (Gabriel ADR-19)

The Windows golden-fixture mismatch named above is now explained and no longer blocks the test
suite. A per-component trace (`examples/golden_trace.rs`) shows that the 23 differing digests
start at tick 7 and are confined to quantities computed through transcendental functions (the
data helix, the carrier phase ladder and the gate metrics q, k and g, each by one unit in the
last place), that a build using the host's glibc differs from a build using the pure-Rust `libm`
crate in 32 of 78 digests, and that moving `sin` by one unit in the last place changes 73 of the
78 digests and six crystal digests. C libraries round these functions differently in the last
bit; the whole-state digest is maximally sensitive to it. Every transcendental call of the engine
now goes through `crates/pse-fmath` (pure-Rust `libm` by default; the `platform-libm` feature
reproduces the host C library byte for byte), `tests/fixtures/pure_libm.json` is the
platform-independent golden fixture (its 16 seeded graph histories equal the Windows fixture's),
and the Windows fixture is retained unchanged behind an ignored test. Cross-platform identity of
the new arithmetic holds by construction and has not been executed on a second platform.

Two additive engine changes serve the readout: `Observation.amplitude_hint` (a declared
data-helix amplitude instead of the payload's byte entropy; `None` keeps the old behaviour) and
`GlobalState.last_metrics` (the metric set of the last step, always readable). The bridge
`examples/engine_readout.rs` runs the engine with decay and crystal commits disabled on a
half-turn carrier grid and reports the embedding, data helix, active carrier, gate metrics and
gate verdict per step; `src/gabriel_agent/evaluation/fixtures/graph_readout.py` states the
specification and implements it independently. Under that profile r, p and n are constants and
k equals lambda_c times q, so three of the eight inherited gate quantities vary (d, q, j). The
crystal, consensus, cascade, falsification and morphogenic paths remain quarantined for the
reasons given above; "detections" in Gabriel are schedule-admitted gate crossings of the
specified readout, not crystals.
