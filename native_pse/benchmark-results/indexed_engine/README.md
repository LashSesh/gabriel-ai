# Controlled native signature integration benchmark

This standalone Cargo project compares three builds of the same native engine:
default packed, optional indexed lookup, and optional exact labelled-graph
signature memoization. `protocol.json` fixes every workload, order, repetition,
timing boundary, equality gate and summary statistic. `inputs.json` contains
the actual observation payload bytes and all microbenchmark graph words.
`freeze_inputs.py` regenerates those checked-in inputs without running a benchmark.

After the native correctness tests have passed, run:

```bash
python native_pse/benchmark-results/indexed_engine/reproduce.py \
  --output /absolute/path/to/new-results-directory
```

The default command performs the real locked release builds itself. Untimed
compilation shares `output/target/build` to reuse Cargo dependencies. Each
completed executable is immediately copied to `output/target/binaries/<variant>`
and byte-hash verified; all golden and timing commands use those preserved
copies, whose exact hashes are recorded. It requires
Rust 1.95.0, a linker, Python 3.10+, and the locked crates available to Cargo.
Do not run other builds or CPU-heavy work during its timing phase. No alternate
prebuilt-binary or reduced-repetition path is used. The explicit release
profile uses optimization 3, LTO disabled, one codegen unit, debug information
retained, unwind, and no overflow checks. All three variants use this same
profile. Disabling LTO is a local linking workaround after Rust 1.95.0 ThinLTO
link attempts failed with undefined symbols; this is not a diagnosis of the
link failures. Build commands use one Cargo job. The new paired ratios must
not be multiplied by earlier results produced with ThinLTO.

Before the first timing subprocess, the wrapper freezes source hashes, inputs,
protocol, full effective configuration, toolchain and environment; builds all
variants; and compares exact raw golden output bytes. Engine goldens contain
the same selected state fields as the prior focused harness and complete
per-tick crystals. They do not represent every internal GlobalState field.
Micro goldens contain every byte of each complete canonical signature for
the fixed graph, all 512 seeded inputs at each n, and collision inputs.
Failure stops timing.

The engine experiment uses 3/5/7/8 sources, eight ticks, 25 fresh engines per
process, and five alternating external pairs for indexed/packed and separately
memoized/indexed. Every tick must actually commit. The source workload forms
complete graphs; eight sources bypass bounded signatures. The micro experiment
uses one executable containing all functions and seven alternating pairs of
512 complete-signature calls on fixed complete graphs and seeded changing
graphs. The 512 changing inputs are not all distinct: n=3 has only eight
possible simple graphs. Exact distinct counts are recorded in `inputs.json`.
An additional n=5/7 collision workload alternates distinct graphs with different
edge counts assigned to one cache slot. Untimed diagnostics require all 512
second-pass calls to miss and evict, testing full labelled-key comparisons;
there is no within-size slot collision among the eight n=3 graphs.

First-macrostep results are separate fresh-process measurements. Only the first
`macro_step` is timed: process launch and input/config/state construction are
excluded. Process-global initialization inside that call is included. This
does not claim a cold operating-system page cache. Steady engine repetitions
have fresh state but warm process-global tables/caches; memoization persists
between fresh states in one process. Cumulative memoizer diagnostics are
sampled outside timing, while the implementation's counter increments remain
part of its measured cost.

Outputs retain command arguments, raw stdout/stderr, exact goldens, source and
binary hashes, full measurements, and paired median/range summaries. Wrapper
wall times include process launch and are explicitly marked as non-benchmark
metrics. Ratios describe these local synthetic workloads; they must not be
multiplied by historical benchmark ratios or presented as broader application
or model validation.
