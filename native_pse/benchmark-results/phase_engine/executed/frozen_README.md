# Controlled sparse whole-engine phase and spectrum benchmark

This independently executable Cargo package compares four same-source builds:

| Variant | Signature | CTQW phase loop | C16/C18 decomposition |
|---|---|---|---|
| indexed | finite exact graph index | reference | separate |
| hoisted | finite exact graph index | hoisted | separate |
| shared | finite exact graph index | hoisted | shared within tick |
| memoized | indexed plus optional exact-input cache | hoisted | shared within tick |

Each comparison changes one mechanism. Feature defaults elsewhere are not
changed by this package. Exact complete-crystal and selected-state golden
bytes must match before any timing is accepted. The selected state is the
same explicit field set as the previous focused benchmark; it is not every
field of `GlobalState`. This checks exact serialized bytes, not arbitrary
underlying floating-point bit patterns: JSON can collapse nonfinite values
to null. Dedicated kernel tests compare raw floating-point bits separately.

## Public input and scope

`freeze_inputs.py` deterministically writes all JSON payload bytes and the
measurement protocol. Inputs use only the public `macro_step` API. Singleton
batches create n vertices without edges. Pair batches then create one edge
each. No graph state is injected or changed directly.

Sizes are 3, 5, 7, 8 and 16. A repeated-path episode first creates a path, then
measures 12 pair batches that update an existing edge. A cold-acquisition
episode clears the thread-local signature cache after singleton bootstrap,
then measures min(16,n(n−1)/2) newly added distinct edges, path edges first.
The cache reset is an explicit experimental condition, outside the timer.
"Cold" refers only to the signature memoizer after bootstrap; the process,
code, allocator, graph index and hardware caches are not made cold.
The n=8 and n=16 measured portions never attach small-graph signatures;
their eligible bootstrap calls are excluded from the timer.

The configuration forces successful commits, suppresses splitting and
merging on these bounded inputs, and uses extraction convergence_tau=1 to
obtain the full vertex region through the low-variance fast path. Thus these
are controlled synthetic workloads, not measurements of default extraction
cost or representative external traffic. The JSON golden trace records actual
induced adjacency, region order, graph size, edge counts and complete crystal
values at every bootstrap and measured tick. Assertions require every tick
to commit and every measured cache hit/miss regime to match the intended case.

## Reproduction

Run the native correctness tests first. Then, with Rust 1.95.0 and Python 3.10+
on PATH, from any directory:

```
python native_pse/benchmark-results/phase_engine/reproduce.py --output /absolute/new/output
```

The output path must not exist. The wrapper builds all four executables with
one Cargo build job in one Cargo target, preserves each executable, records compiler/environment and
source/input/binary hashes, verifies exact goldens and actual graph traces,
then executes five alternating external process pairs for each comparison.
Each process runs one untimed warmup per case and 12 fresh-engine repetitions.
A fresh engine does not imply a cold thread-local cache; the policy above is
explicit and cache counters are recorded outside the measured interval.

Only the measured macro-step loop is timed. Process launch, configuration,
input construction, engine construction, public bootstrap, cache reset,
validation and output serialization are excluded. Results report committed
ticks/s and ns/tick. The ratio is the candidate/reference ratio of median
per-process ticks/s, then summarized by median/min/max across five pairs.
No population confidence interval or application-wide speedup is inferred.

Captured subprocess output is held as original bytes until the command has
completed, atomically written, immediately reread, and redundantly stored in
`captured_records.json`. Every capture and executable is rechecked before
results are accepted. Failed or empty required outputs halt the run; Python
optimization flags cannot disable these gates. Build output may legitimately
have empty stdout. `target/` contains regenerable build products and is not
required in the research source archive.
