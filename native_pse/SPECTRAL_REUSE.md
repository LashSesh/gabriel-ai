# Optional spectral execution refinements

Two independently selectable build features reduce repeated computation:

- `phase-hoist`: reuse mode-dependent sine and cosine values within a CTQW call. Ordered products, accumulations, threshold comparisons and the separate literal final time remain unchanged. A conservative finite-domain guard delegates exceptional, overflow-risk, zero-step and malformed-rank inputs to the original reference body.
- `shared-spectrum`: move the eigensystem computed in C16 to C18 during the same macrostep, when the graph and effective spectral rank are unchanged. C18 still initializes its own fresh Kuramoto state. There is no cross-step spectral cache.

The optional finite graph index and complete-signature memoizer remain separate mechanisms. Defaults remain reference phases, separate decompositions and packed signatures. For the indexed build with both spectral refinements:

```sh
cargo build --locked --release --jobs 1 --manifest-path native_pse/Cargo.toml --features indexed-signature,phase-hoist,shared-spectrum
```

Substitute `memoized-signature` for `indexed-signature` only when the exact-input cache is wanted. Its first-call/miss cost and hit dependence remain relevant.

## Preservation scope

The reference CTQW function body is byte-identical to the measured-source snapshot in `audit/native_indexed_measured_sources.zip` (body SHA256 `a0d94fdef6254c04e80704b7ae9fe3c3d7454b797cf05b86603adbcf7dde11a4`). Its new `inline(never)` attribute is outside that body and common to all four current benchmark builds. Consequently this is a matched current-build experiment, not a timing comparison against an unchanged historical executable.

Bit identity of reused arithmetic requires repeatable scalar arithmetic/trigonometric operations. Rust's portable standard-library contract does not promise universal sin/cos repeatability or NaN payload/sign identity. The implemented guard uses exact-power limits and reference fallback; see its source comments and the manuscript for the sufficient domain and assumptions. Nonfinite inputs are not silently normalized. The actual strict tests compare every binary64 output field, including signed-zero and NaN bits, for their pinned executable and inputs.

Spectrum reuse requires unchanged graph/node order and equal effective rank. It applies at the inherited n<=500 bound. CTQW itself retains its n<=100 execution bound. Existing time-budget branches in multiscale processing make unrestricted whole-engine equality across operating-system schedules a stronger claim than the tests establish. Neither feature repairs inherited eigensolver, clustering or topology-model limitations.

## Reproduction

The full workspace correctness command is:

```sh
cargo test --locked --release --jobs 1 --manifest-path native_pse/Cargo.toml --workspace --all-features -- --skip full_state_matches_original_golden_fixture
```

The named historical fixture is explicitly excluded because its preserved discrepancy is unresolved. The unfiltered failure and intermediate/final validation logs are retained in `benchmark-results/phase_validation/`; no fixture was refreshed to force a pass.

After functional verification, use a quiet environment and a new output directory:

```sh
python native_pse/benchmark-results/phase_engine/reproduce.py --output /absolute/new/output
```

The executed study uses Rust 1.95.0, locked dependencies, one build job, opt-level 3, no LTO, one code-generation unit, debug information and no stripping. It compares four builds with exact serialized golden gates before timing. Public singleton/pair observations construct all sparse and acquisition graphs. The extraction and morphology controls are explicitly synthetic; default-workload performance is not inferred. Cold acquisition means a cleared signature memoizer, not cold machine caches.

`python reproduction/report_native_phase_results.py` independently checks and summarizes the retained run in `benchmark-results/phase_engine/executed/`. This reporting command performs no new timing. Build products under `target/` are regenerable and excluded from the source distribution; source, compiler, executable hashes and all captured observations remain supplied.
