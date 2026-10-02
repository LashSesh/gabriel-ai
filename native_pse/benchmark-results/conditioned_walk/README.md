# Conditioned state-vector benchmark

This is a synthetic, same-output comparison of the new conditioned-walk API.
It compares `BackendChoice::Auto` with `BackendChoice::Spectral`, using the
same weighted Laplacian, normalized complex initial state and query times.
Both return the entire vector `exp(-i t L) psi(0)`. Both cache the initial
state preparation. It does not time the historical all-pairs threshold scan,
and it does not establish a whole-engine or application-level speedup.

## Reproduction

Run the relevant kernel correctness tests first. With Rust 1.95.0, Python
3.10+ and the Cargo dependencies available locally, run from this directory:

```sh
python3 reproduce.py --output /absolute/path/to/a/new/result-directory
```

Use a new output directory and run no competing builds or CPU-intensive work
during measurement. The runner builds offline, with a frozen Cargo lockfile
and no LTO. If the lockfile is missing, its generation is recorded before
the source snapshot. The complete project dependencies may need downloading
before running this offline experiment. The benchmark sources alone are a
protocol, not evidence of execution; executed results must include a
successful `integrity.json` and the original process outputs.

## Workload and timing boundaries

`protocol.json`, embedded in the executable, is authoritative. Eleven cases
cover binary-exact uniformly weighted cliques of order 7, 13, 32, 64 and 128,
a weight-1 clique, and five strict-dispatch controls. The nonbinary weight
1.7 case uses neighbour-ordered degree accumulation; its rounded diagonal
does not satisfy the strict complete-graph gate and must use Spectral.
The other controls are paths and cliques with one doubled edge weight.

The input state is deterministic, complex and normalized; no random seed or
external data is needed. Each batch cycles through 16 specified times,
including zero and negative times. Thus 1/16 of the exact workload consists
of zero-time queries. Times, weights, dimensions and repetition counts are
fixed before measurement. Every returned real and imaginary component for
every distinct query time is checked and saved before query measurement.
The component bound is `5e-10 + 5e-10 * max(abs(a), abs(b))`; squared norm
must stay within `5e-10` of the initial squared norm. These are numerical
checks, not interval-certified roundoff bounds. Independent kernel tests
provide the separate oracle; this benchmark compares the two backends.

Measurements are kept separate:

1. Graph construction and initial-state generation, each recorded once.
2. Plan construction, including validation, dispatch, dense construction and
   any eigendecomposition, measured in five warmed pairs.
3. State preparation, including cached overlaps or mean, measured in five
   warmed pairs. Destruction of prepared states is excluded.
4. Repeated prepared-state queries, measured in five paired batches. These
   include allocation, return-value checking, complete-vector `black_box`,
   one changing component's checksum contribution and vector destruction.
   Correctness validation, warmup, setup, preparation, JSON encoding and
   process startup are excluded. Plan destruction is outside setup timing.

Seven fresh OS processes each contain both variants. Pair order reverses
with process, case and batch parity. Full-vector validation outputs and
every timing sample are retained. Output checksums prevent using an
unobserved result; the complete-vector optimization barrier prevents
eliminating unconsumed components. Summary ratios are paired Spectral/Auto
ratios: median across five pairs in each process, then median and observed
range across seven processes. The observed range is not a confidence
interval. Setup costs and preparation costs must be reported separately
when interpreting an advantage from reusing a plan.

## Evidence files

The runner records protocol/source snapshots, source SHA-256 before/after,
Cargo and rustc version output, environment, executable SHA-256, each exact
command with stdout/stderr, complete per-process JSON, checked summary and
final integrity status. Build output under `target/` is disposable; the
preserved executable, lockfile, source tree and evidence provide the build
and execution identities. Changes to source files during the experiment
invalidate the final integrity check. No statistical significance, quantum
hardware advantage, cross-machine performance or trading result is inferred.
