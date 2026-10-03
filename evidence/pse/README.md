# Native PSE graph worker evidence (ADR-18)

| File | Content |
|------|---------|
| `build_identity.json` | The locked source build of `engine_observer` and `engine_snapshot` (cargo/rustc 1.97.0): executable digests, `Cargo.lock` digest, digest of the bound source set, the shipped binary's digest for comparison |
| `equivalence_fresh_vs_shipped.json` | The fresh build, the shipped binary and the retained functional journals give bit-identical masses, decisions and snapshot identities on all three walk backends |
| `functional_fresh_build/` | The inherited functional check (`reproduction/check_graph_observer_owner.py`) executed against the fresh build: `results.json` and the owner journals per backend |
| `measurements.json` | `scripts/pse_measure.py`: cold start, identity validation, native query time at the fixture and at the caps, the dedicated certificate process, and total task latency through the owner on `trusted_local` and `linux_namespace`, each separately, with raw samples |
| `graph_tier_check.json` | `gabriel eval corpus-check --tier graph`: the graph tasks (five families since ADR-19), every executed positive and negative control as expected |
| `determinism/summary.json` | The determinism study (ADR-19): the historical mismatch reproduced, localized and explained; the decision for the pure-Rust arithmetic; what is not established |
| `determinism/linux_trace_*.json` | Per-component state digests of the golden cases under the host C library, the pure-Rust libm and the one-ulp `sin` perturbation |
| `determinism/observer_pure_libm_vs_retained.json` | The observer under the pure-Rust arithmetic against the retained functional journals (bit-identical on the automatic backends, one ulp on `spectral_full`) |

The regression evidence is `tests/test_native_pse.py` in `evidence/test_results.txt`. The
executables themselves are not retained in the repository (`native_pse/target/` is ignored);
they are rebuilt from the locked sources and identified by the digests recorded here.
