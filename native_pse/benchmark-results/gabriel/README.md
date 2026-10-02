# Native PSE execution review

The supplied PSE builds with task-local Rust 1.95.0 on Linux. The unfiltered locked release workspace test fails at the historical golden fixture. With exactly that test explicitly filtered, 433 tests pass, one inherited test is ignored and one test is filtered. The optional small-signature fork adds five passing tests; its corresponding filtered suite reports 438 passing tests. No historical fixture was replaced.

The historical mismatch comprises 23 of 78 state hashes and one crystal hash, while all recorded tick/commit counts and all 128 separate binary-graph-history hashes agree. The root cause is not established: the supplied expected fixture stores hashes and cannot expose original numerical values. Both current same-host comparison suites agree, with focused evidence comparing the explicit selected state snapshots and complete returned crystal values directly (1,257,237 bytes). This is not an all-fields GlobalState snapshot; see `snapshot_scope.json`.

Both standalone focused wrappers explicitly use opt-level=3, ThinLTO, one codegen unit, debug=true, strip=none, overflow-checks=false and panic=unwind. Dependency package root profiles are not assumed to propagate. `focused_profile.json` and the common `focused_harness.rs` specify the actual execution. All builds and other agents’ heavy work stopped before timing. Three external pairs alternate reference/fork order; each invocation contains five fresh-state repetitions. No CPU affinity/frequency lock or confidence interval is provided.

| Synthetic commit batch | Reference obs/s | Fork obs/s | Median paired throughput ratio | Pair-ratio range |
|---|---:|---:|---:|---:|
| 3 | 8.255 | 25544.225 | 3094.555 | 2710.855–3445.321 |
| 5 | 13.826 | 17271.731 | 1222.682 | 1031.683–1285.010 |
| 7 | 19.388 | 10027.734 | 513.370 | 500.387–536.589 |
| 8 | 10070.867 | 9811.802 | 1.022 | 0.933–1.025 |

The table rate columns are medians of the three per-process median rates; the paired ratio is a different statistic. Each focused case has eight ticks and eight real commits. Every 3/5/7-source commit has a signature on the equally sized region. Every eight-source commit has no signature. The eight-source control shows no robust speed gain; across the unchanged stock workload suite median paired ratios range from 0.988 to 1.063. The very large gains eliminate the dense canonicalization work of the eligible inherited signature path. They are neither generic Rust speedups nor multipliers for Gabriel’s Python predictor or durable owner.

The original supplied harness remains byte-identical. Its historical original/extracted/optimized Windows outputs are supplied artifacts, not rerun historical comparisons. The new measured reference is the actual PSE version supplied in this upload. The archived upload is included with its unchanged SHA-256 in the portable reproduction wrapper.

## Reproduction

`python reproduce_native.py --output /path/to/new_directory` implements the same build profiles, exact supplied-reference extraction, identical focused source and paired measurement procedure. It needs standard Rust 1.95.0/Cargo, a linker and access to the locked registry dependencies on first build. The wrapper’s argument/help path was checked; the experiment itself was executed through the logged commands and task runner, not by rerunning this packaging wrapper. Raw files in `paired_stock/` and `paired_focused/` are the actual outputs. The delivered native source retains inherited scientific limitations and the historical fixture failure; the diagnostic crate under the main project `audit/pse_diagnostics` exposes two concrete inherited failures.

Build/test logs retain the original command failure and the explicitly filtered continuation. Linux fields named CPU time or RSS in the inherited harness are literal unsupported zeros and must not be interpreted as measured zero resource use.
