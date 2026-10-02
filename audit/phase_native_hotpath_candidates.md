# Native PSE hot-path review — 2026-09-26

Status: read-only source review. No builds, timing measurements, or numerical executions were performed by this reviewer. Recommendations identify redundant work; performance impact remains to be measured.

Project: `/workspace/scratch/657e86c899c9/recovered/project/Gabriel`.

## First candidate: reuse CTQW eigenmode phases within one propagation call

`native_pse/crates/pse-topology/src/lib.rs`, `ctqw_propagate`, lines 469–607. Called on every accepted crystal through `compute_topological_signature` (lines 774–837), itself called by `pse-core/src/lib.rs` near line 863.

The time-scan loops are step → source → destination → eigenmode. Inside the innermost loop:

```
let phase = -lam * t;
re += phase.cos() * u_mj * u_md;
im += phase.sin() * u_mj * u_md;
```

Both trigonometric values depend only on step and eigenmode, yet are recomputed for every still-unresolved source/destination pair. The final reporting pass repeats the same redundant work at `config.ctqw_time_max`.

Recommended change: one call-local pair of reusable `Vec<f64>` phase arrays of length `k`. Fill using exactly `phase = -spectral.eigenvalues[m] * t`, then `phase.cos()` and `phase.sin()`. Preserve all source/destination/eigenmode iteration orders, the left-associated products and accumulator updates, and all threshold comparisons. Fill separately for final reporting at literal `config.ctqw_time_max`.

Theoretical work reduction: at n=7, k=7, 100 time steps, unresolved non-diagonal entries require up to 29,400 sin/cos pairs, reducible to 700; final reporting from 343 pairs to 7. These are source-derived operation counts, not measured speedups. Allocation overhead is O(k). No cross-call cache, graph identity key, or synchronization is required. Whole macro-step speedup is bounded by the contribution of this stage.

Critical semantic constraints:

* Do not substitute `sin_cos()` without proving equality against separate sin/cos on the executable target.
* Do not precompute `u_mj * u_md`, factor sums, vectorize with reassociation, or impose source/destination symmetry: floating-point multiplication/accumulation order changes.
* The final sample must use `config.ctqw_time_max`, not reuse the phase arrays from the last scanned time: `steps * (time_max / steps)` need not equal `time_max` in floating-point.
* Preserve n=0 early return, k=0, zero scan steps, arbitrary threshold, ragged eigenvectors (existing zero fallback), and existing invalid `k > eigenvalues.len()` panic behavior.
* Avoid mathematical claims of exact CTQW from this optimization: the underlying truncation, diagonal-first threshold assumption, unit propagation distance and threshold scan remain inherited approximations.

Minimum meaningful validation:

1. Freeze the original function as an independent test/reference body and compare **all f64 fields by `to_bits()`**, including both matrices and mean propagation time. JSON comparison alone collapses signed zero and cannot carry non-finite output faithfully.
2. Cases: empty, singleton, zero rank, full/truncated spectra, ragged eigenvectors, disconnected/complete/path/star/weighted directed graphs, random finite spectra/vectors, eigenvalues with ±0, repeated eigenvalues and ill-scaled positive/negative finite entries; scan steps 0,1,3,7,100; non-dyadic end times; thresholds below zero, exactly zero, common values, above one and NaN. Explicit Inf/NaN spectra can establish executable-local bit equivalence without promising cross-platform NaN payload stability.
3. Derive threshold-adjacent cases from actual reference probabilities (`next_up`/`next_down` around a probability) so one-bit changes cannot hide behind the threshold.
4. Compare full engine selected state and every complete emitted crystal byte-for-byte before timing. Extend at least the existing n3/5/7/8 focused protocol with sparse/changing topology so results are not only repeat-complete-graph cache hits.
5. Freeze both build trees and release profiles, alternate process order, retain raw individual timings. Time the full engine and isolated CTQW with n3/5/7/8, plus n16/32 or another realistically larger case. Gate-rejected and >100-node topology cases form controls where this stage is not executed.

## Second candidate: assemble the dense Laplacian in one adjacency pass

`pse-topology/src/lib.rs`, `spectral_decompose_full`, lines 256–279.

Current `DMatrix::from_fn` scans every adjacency entry for every off-diagonal matrix element, producing O(n² e) assembly before eigendecomposition. Initialize zero matrix, copy degree values to the diagonal, then traverse adjacency in its existing order and subtract weight into the corresponding off-diagonal cell. This makes assembly O(n²+e), while preserving each individual cell's operation order.

Care: public `SparseLaplacian` can contain repeated, diagonal or out-of-bounds adjacency entries. The existing loop ignores diagonal entries and out-of-bounds entries; a replacement must do the same if the public behavior is retained. Preserve initial +0 and `-=` arithmetic. Compare dense matrix bits before eigenvalue tests, then all spectral fields and full engine output. This may be more important at larger n than n7, but depends on how much assembly contributes relative to eigensolve.

## Third candidate: share the identical spectral decomposition within a macro-step

`pse-core/src/lib.rs`, C16 near lines 860–879 and C18 near lines 882–904. The C16 call computes a default-config Laplacian and spectral decomposition; the immediately following C18 block independently recomputes both on the same unchanged graph with the same default spectral rank.

A call-local topology-analysis result exposing both the signature and its spectral decomposition would permit reuse in C18 without persistent cache invalidation. Preserve existing public `compute_topological_signature` as a wrapper. For n<=500 the two `spectral_decompose` calls receive equivalent ranks (`min(k,n)` inside the latter); n>500 currently skips both heavy branches. The initial Kuramoto state needed in C18 is **not** the 10-step evolved Kuramoto state used for C16 coherence; do not reuse the evolved state accidentally.

Risk: API/lifetime refactor spans topology and core, and exposing an internal analysis object must not change serialized crystal fields. Exact deterministic floating-point environment assumed. Smaller likely benefit for n7 than CTQW phase reuse, potentially larger at n>100 where CTQW is skipped.

## Fourth candidate: prepare Kuramoto graph data once for the 10-step block

`pse-topology/src/lib.rs`, `kuramoto_step`, lines 624–718, and its loop near 820–823. Every step rebuilds the same NodeIndex map, neighbors, weighted degree and natural frequencies from an immutable graph. Compute these once for the block and reuse them in an internal step helper. Preserve raw edge order, neighbor order, duplicate/reverse-edge accounting, embedding-value order and RK4 formulas. This reduces allocations and preprocessing; it does not reduce the dominant phase-difference sin count.

No cross-step mutable graph or mapping assumptions should be added to public `kuramoto_step`. Keep the existing public one-step wrapper constructing its own prepared data. Exact-state comparisons must include all phases, order parameter, mean phase and cluster coherences, not only the final scalar used by topology.

## Findings intentionally not folded into optimization

* `pse-graph::compute_spectral_gap` is an existing degree-spread proxy, unlike the eigensolver-backed spectral gap. It is cheap and semantically separate; replacing it is a model change.
* `multi_scale_tick` still has a wall-clock budget check near `pse-scale/src/lib.rs:935`; it is evaluated immediately after starting its timer and only gates n>100. This residual branch complicates universal whole-engine determinism claims for larger cases. A performance refactor should not silently reinterpret it.
* Existing historical fixture remains unresolved. No performance change should refresh expected data merely to hide this failure.

Recommendation: implement only candidate 1 first, with executable bit-exact differential tests and full-engine timing. The structural leverage is substantial and the state boundary is local. Add another candidate only if measurements show a concrete remaining bottleneck and there is enough time to give it equally independent validation.

## Authorized implementation follow-up

After the read-only review, root authorized candidate 1 plus the helper needed by a separately owned shared-spectrum core change. Implemented only in `pse-topology`:

* `Cargo.toml`: optional `phase-hoist` and `shared-spectrum` features; default empty.
* `src/lib.rs`: original CTQW body renamed to public reference; feature-dependent public alias; signature wrapper/common const-generic helper retaining the existing spectrum without clone when requested.
* `src/ctqw_hoisted.rs`: same output computation, with cos/sin arrays populated lazily at the first unresolved ordered pair of each step. Final literal `t_max` has separate phase evaluation. No all-pairs extra scan, symmetry copying, phase approximation, or cross-call state.
* `src/ctqw_equivalence_tests.rs`: 6 executable test functions. 1,491 returned-result parameter cases compare every f64 bit in both matrices and mean, also checking the dispatched API. Four invalid-rank cases verify both functions panic. Source hash check binds exact original function body.
* `src/shared_spectrum_tests.rs`: frozen original signature body as an independent refactor oracle; 21 n/rank combinations compare all signature and spectral fields bitwise, including n32/k2 partial decomposition and n501 fallback.

Reference CTQW body SHA256: `a0d94fdef6254c04e80704b7ae9fe3c3d7454b797cf05b86603adbcf7dde11a4`. A Python read-only comparison verified the renamed function body is byte-identical to `audit/native_indexed_measured_sources.zip`.

No Rust compilation, test execution, or timing was performed by this agent. Root owns actual execution. Do not describe these tests as passed until root execution succeeds.

The revised phase count formula (for n>0, rank k) is:

* Reference sin+cos pairs: `k * (sum_s Q_s + n*n)`.
* Hoisted sin+cos pairs: `k * (A + 1)`.

Here `Q_s` counts unresolved ordered pairs upon reaching step s, and `A` counts scan steps with at least one unresolved pair. Each pair of trigonometric operations means one separate sin and one separate cos. For n1, A=0 and both perform k phase pairs at final reporting; the optimized function still allocates two O(k) arrays. Therefore no uniform speedup claim follows.

## Exceptional-float failure and conservative correction

Root's first executed differential run found a genuine NaN sign-bit mismatch in the special-float test (payload 0x42), although the other new tests passed. The failed test was retained. Repeated NaN arithmetic is not interchangeable with sharing an intermediate at the compiled instruction-selection level, even when source multiplication order is unchanged.

The hoisted function now uses a conservative eligibility guard and falls back to the unchanged reference function otherwise. Only consumed values are examined. The sufficient conditions are:

* `usize::BITS <= 64`, rank `k <= 2^32`, eigenvalue storage sufficient, positive scan-step count, finite threshold;
* finite eigenvalues with magnitude at most `2^250`;
* finite consumed eigenvector entries with magnitude at most `2^128`;
* finite end time with magnitude at most `2^250`, and either exactly ±0 or magnitude at least `2^-250`.

Under round-to-nearest binary64 arithmetic and finite sin/cos outputs bounded in magnitude by 2, these conditions give active scan time magnitude at least `2^-315` when nonzero and at most `2|T|`; phase magnitude at most `2^501`; product magnitude below `2^259`; accumulated amplitudes below `2^293`; probability below `2^588`. Rank satisfies `k*2^-53 <= 2^-21`, so accumulation rounding stays well within those margins. Reciprocals stay below `2^315`. Scan times all have the same sign; a rounded same-sign addition increments the magnitude by at most twice the addend, bounding their sum below `2^380` even without assuming a small total number of additions.

The reference function now has `#[inline(never)]` outside its body so exceptional fallback and the test oracle use one compiled body. Its body hash remains unchanged, but the compilation attribute is an explicit change and is present in every same-tree benchmark build. This is executable-local preservation, not a portable guarantee about arbitrary Rust NaN payload selection.

Nine additional complete-result cases exercise signed NaN payloads in eigenvalues, eigenvectors and time, finite values that cause arithmetic overflow, and subnormal scan time. Total returned-result differential cases: 1,500. One additional test checks the conservative domain boundaries. Strict comparisons were not weakened. Root owns rerun results; this agent did not run compilation or tests.

Independent reviewer `/root/spectral_refinement_review` inspected the implemented guard and accepted the bounds with the stated arithmetic assumptions.

A subsequent read-only inspection of `benchmark-results/phase_engine/src/main.rs` and `reproduce.py` found no blocking issue in golden, graph-shape, signature-cap, cache-regime, source/binary/capture or paired-run checks. `cold_acquisition` means signature-cache cold after an untimed bootstrap, not a cold process or machine.
