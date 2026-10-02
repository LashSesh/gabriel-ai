# PSE core review and bounded native acceleration

Review date: 26 September 2026. Archive source: `pse-standalone.zip`, SHA-256
`30d4a6aeab6c6509c0cc31fcf5b4be4fd3f95aec745127aa848c8ce37b7299ca`.
The extracted upstream tree was not modified. This report distinguishes static
source findings, analytical counterexamples and executed code tests.

## Assessment

PSE contains a real executable, modular, synchronous graph-analysis pipeline.
It is useful as an optional source of graph features and heuristic candidate
proposals, and its implementation contains a substantial avoidable cost in the
small-graph signature path. It is not a general transaction owner, a faster
implementation of Gabriel's forecasting reducers, or evidence that five state
coordinates are universally sufficient or optimal. Its stored “crystals” and
“proof” fields do not by themselves establish the truth of an inferred pattern.

The narrowly suitable integration is an optional graph-analysis component behind
Gabriel's existing authority boundary, with numerical output treated as data.
Its approximate memory matches must not authorize omission of exact state
transitions. Replacing Gabriel's store with this engine would discard important
transaction, retry, replay and bounded-history contracts. Gabriel's separate
store acceleration is therefore the main system-level improvement.

## Findings requiring limits or separate semantic corrections

1. **Migration metric typo; transition impact is narrower than the typo suggests.**
   `pse-core/src/lib.rs:421` uses `!num_carriers == 0`, a bitwise complement,
   rather than `num_carriers != 0`. For ordinary carrier counts it reports zero
   migration readiness. However, `pse-cascade::migration_admissible` recomputes
   its own readiness and does not read `MetricSet::l_migration`. Correcting this
   expression alone would not alter that transition's decision or accelerate it.

2. **Zero change is mapped to nonzero novelty.**
   In `compute_all_metrics`, the fallback for a finite candidate equal to zero
   is `0.75`. An unchanged, nonempty, nonzero embedding therefore reports
   `d=0.75/(0.75+mu_d)`, which is about 0.789 at defaults, rather than zero.
   The fallback covers both an absent baseline and a genuinely unchanged graph.
   This is an analytical counterexample from the branch condition, not a claim
   about a measured anomaly-detection error rate.

3. **Marginal quantiles do not calibrate a joint AND probability.**
   `adaptive.rs` sets eight separate empirical quantile thresholds. Its claim
   that the conjunction fires on `target_pass_rate` of ticks is unsupported.
   For independent continuous metrics with upper-tail probability p, the joint
   probability is p^8; dependence can make it zero or as large as p. Constant
   histories with an inclusive comparison can pass every subsequent equal
   sample. No stationarity or distributional guarantee is supplied. Adaptive
   calibration remains a deterministic heuristic, not a calibrated probability.

4. **Proof-of-rigor state machine is not an engine gate.**
   `GlobalState` creates `PoRFsm`; `macro_step` copies its trace but never calls
   its `step` or `reset`. The initial trace is therefore not evidence of the
   advertised Search/Lock/Verify/Commit progression. `operator_stack` is also
   emitted empty, and `structural_result` is set to true without a separate
   structural test at this location. These fields must not be represented as
   verified scientific proofs. The actual cascade does evaluate two operator
   orders, but their scalar agreement is not an independent external validation.

5. **Morphogenic operations do not implement their full stated semantics.**
   In `pse-constraint/src/lib.rs`, splits create IDs 2v+1 and 2v+2 using wrapping
   arithmetic, merges use u+v, and replication adds a constant. None checks for
   collisions with existing IDs. Splits/merges do not inherit/union the promised
   edges. `EdgeRetype` checks an edge and does not change it. A merge candidate
   list may reuse the same vertex in multiple pairs. Several examples test
   finiteness or no panic, which does not verify those advertised semantics.

6. **The intrinsic linear update has an elementary conditional stability bound.**
   With fixed attractor a, constraint centers c_j, activation weights e_j and
   damping gamma, each coordinate obeys
   `h_next = (1-dt*(1+gamma+sum e_j))*h + dt*(a+sum e_j*c_j)`.
   For L=1+gamma+sum e_j>0 its fixed point is
   `(a+sum e_j*c_j)/L`, and contraction requires `0<dt*L<2`.
   The fixed point is generally not the supplied attractor. Facade validation
   only requires positive dt and finite configuration values; it does not
   enforce this bound, nor does this fixed-parameter derivation establish
   stability under moving attractors, changing constraints or graph mutation.

7. **Constraint names often designate proxies.**
   The Granger operator is a bounded transform of a single eta coordinate; it
   is not a fitted temporal causal model or a Granger test. The correlation
   operator is a bounded squared norm. Region variance uses the p coordinate
   only, not all five coordinates. The `TimeWindow` passed to `inverse_weave`
   is ignored. Candidate IDs bucket a score by hundredths and deduplicate on
   that bucket, which intentionally collapses distinct numerical candidates.
   These operations can be defined as features, but their names do not supply
   causal, spectral or information-theoretic identification results.

8. **Surrogate scores do not establish a statistical p-value contract.**
   Falsification re-canonicalizes stored payloads through the same adapter,
   transforms one original batch into singleton batches on fresh engines,
   ignores inner execution errors, and compares maximum carrier coherence.
   It need not reconstruct original observation metadata or batch semantics.
   A stateful adapter is not reset between surrogate runs. The empirical
   fraction has no finite-sample randomization calibration in the code;
   exchangeability and a suitable null model are not established. The method
   named BlockBootstrap permutes blocks without replacement; PhaseRandomize
   returns an unimplemented error. These are concrete scope limits, not an
   assertion that surrogate testing is intrinsically unsuitable.

9. **Navigator Betti numbers are incorrect for filled simplices.**
   `pse-navigator/src/lib.rs:248` keeps graph cycle rank `E-V+b0` as b1 after
   adding faces, then infers b2 from Euler characteristic. A filled triangle
   has V=3,E=3,F=1 and the function returns [1,1,1], whereas the contractible
   triangle has [1,0,0]. Boundary-matrix ranks are needed. Consequently the
   topology guard and reported “landscape topology” are not valid homology
   certificates. Golden-angle exploration is a reproducible search heuristic;
   it does not establish optimum attainment. Its configured seed is stored
   but unused by `NavigatorSpiral::next_point`.

10. **The Metatron hash is not an isomorphism proof.**
    The canonical hash covers a zero-padded 13x13 adjacency matrix under S7.
    It omits original n. Edgeless graphs with different positive n therefore
    have identical hashes, despite not being isomorphic as original graphs.
    `PatternMemory::lookup_crystal` keys only on that hash. It also uses a
    64-bit FNV digest without exact collision resolution. Directed edges,
    multiplicity and weights are discarded by induced adjacency. Exact
    canonical forms at fixed n can classify the simple undirected projection;
    a hash-only lookup cannot establish the stronger claims in comments.
    The current `macro_step` shortcut actually uses the approximate signature
    lookup, not `lookup_crystal`, so this canonical-index defect has a more
    limited engine impact than a search of comments might suggest.

11. **Finite input and semantic invariants are only partially validated.**
    The facade rejects nonfinite configuration floats but accepts negative
    normalization/damping values and does not bound all denominators. Adapter
    outputs carry a digest check, but finite timestamps and phase hints are an
    adapter obligation. Normalization into [0,1] requires parameter signs not
    universally enforced. “Physical interference” is the chosen feature
    formula, not an experimentally grounded physical system. The balanced
    cuboctahedron phase construction does not prove unique optimality among
    phase sets; many symmetric sets also have zero phasor sum.

## Implemented equivalent acceleration

The optional fork is `native_pse/`. It retains the upstream license, manifests,
lockfile, fixtures and mathematical model. Only the engine's small-region
signature execution and its cache-initialization guard change.

The inherited path constructs an S7 dense-matrix cache, forms 5040 conjugates
three times for orbit/stabilizer/complement analysis, then discards many full
scan fields when returning a lightweight signature. The new path:

- rejects empty or greater-than-seven regions before initializing a cache;
- uses the existing exact packed edge permutations over all 5040 S7 elements;
- minimizes the **original row-major matrix order**, not the different integer
  ordering used by the catalog's `canonical_bits`;
- counts the stabilizer and obtains orbit size from orbit-stabilizer;
- retains exactly the original spectral and Platonic calculations on the
  original embedding, preserving their floating-point input and operation order;
- returns all fields of `MetatronTopologySignature`, including the inherited
  padded-hash limitation. No heuristic threshold or scientific meaning changes.

For binary symmetric zero-diagonal matrices, the first differing row-major
matrix entry between two candidates lies in the upper triangle: any earlier
lower-triangle difference would already appear at its transposed upper entry.
Thus an upper-triangle row-major key with most-significant first bit has exactly
the dense canonical ordering. The integer action enumerates the same orbit
(the inverse convention is immaterial over the whole group). Floating-point
matrix multiplication on this binary permutation case produces exact 0/1
entries. This is a hand argument for the finite branch, not a machine proof.

Executed focused tests passed: all 1099 simple labelled graphs on 1..5 vertices
and 48 seeded graphs on 6/7 vertices against an independent direct indexed
matrix action; nine complete signatures compared as canonical bytes against
the unchanged dense implementation; invalid inputs rejected; inherited hash
padding collision explicitly demonstrated. The log is
`small_signature_tests.log`. Whole-workspace and cross-build measurements are
recorded separately by the build review, not inferred from these local tests.

The later workspace command passed 438 tests with one ignored doctest and one
explicitly filtered historical golden comparison. The supplied Windows-generated
fixture does not match unchanged upstream execution on current Linux: 23 of
78 recorded engine-state hashes and one crystal hash differ. The cause is not
established; the historical hashes do not expose the underlying differences.
No attribution to platform arithmetic, rounding or another mechanism is made.

The multiscale component retains elapsed-time branches. Exact equivalence of
the bounded signature operation therefore does not prove complete-engine
equivalence for all inputs and execution schedules. Successful current-platform
original-versus-fork runs are finite checks with separately retained evidence.

## Exact review coverage

Read in full: PSE_ARCHITECTURE.md, PSE_API.md, PSE_EXTRACTION_REPORT.md; public
facade `src/lib.rs`; `pse-core/src/lib.rs`, `adaptive.rs`, `query.rs`,
`explore.rs`; `pse-extract/src/lib.rs`; `pse-constraint/src/lib.rs`;
Metatron `orbit.rs`, `embed.rs`, `signature.rs`, `bitgraph.rs`, `group.rs`,
`stabilizer.rs`, `spectrum.rs`, `ingest.rs`, `phase_layout.rs`, `lib.rs`.

Read all production code but not every test: `pse-cascade/src/lib.rs` (1..839),
`pse-types/src/lib.rs` (1..1090), `pse-navigator/src/lib.rs` (1..951),
`pse-core/src/falsify.rs` (1..290). Read the Metatron attachment production
code (1..110), scan definitions and complete `scan_with_cache` path, and exact
memory canonical-index definitions/insertion/lookup. `platonic.rs` production
calls and return fields were inspected for the optimization dependency.

Not fully reviewed by this reviewer: core `topology_ops.rs`, `crystal_adapter.rs`,
Metatron graph catalog/general-n implementation, geometry, properties, remaining
unit-test bodies and all archive data. The graph/memory/evidence/topology/scale
review and build execution are separate team outputs. No claim is made that
every line in the 15k-line assigned area received mathematical verification.
