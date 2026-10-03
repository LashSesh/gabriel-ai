# ADR-18: The native PSE graph engine as a contained analytical worker

**Status:** accepted. **Affects:** `adapters/native_graph.py`, `adapters/window_certificate.py`
(vendored), `domains/numerical/pack.py`, `domains/numerical/schemas/numerical-snapshot.schema.json`,
`evaluation/fixtures/graph_walk.py`, `evaluation/corpus_domains.py` (graph tier),
`evaluation/comparators_domains.py`, `interfaces/cli.py`, `scripts/pse_measure.py`.

## Context
The blueprint's "native PSE and analytical worker contracts" admit the inherited Rust engine
(`native_pse/`) only as an analytical worker behind the DomainPack ports: specific bounded
operations, a fresh contained worker per job, complete bindings (input bytes, operation,
parameters, executable digests, worker build, numerical environment), the verdicts
`reachable`, `excluded`, `unknown` and `out_of_scope`, the inherited heuristic features
quarantined, no crystal-learning claim, and cold start, identity validation, query time and
total latency measured separately. The inherited review (`native_pse/GABRIEL_REVIEW.md`) had
fixed what the engine does and does not do: a deterministic conditioned graph walk
`exp(-itL)` on the symmetrized co-observation graph, exact closed-window certificates on
uniform cliques (python-flint/Arb), and a bounded S7 small-graph signature whose zero-padded
form collides across vertex counts. Until this ADR the worker was unbuilt and every manifest
listed it as not executed.

## Decision
- **Build and identity.** The Cargo examples `engine_observer` and `engine_snapshot` are built
  from the locked sources (`cargo build --locked --release`, cargo/rustc 1.97.0;
  `evidence/pse/build_identity.json` records the executable digests, the `Cargo.lock` digest
  and the digest of the bound source set). The fresh build reproduces every retained answer of
  the inherited functional journals bit for bit on all three walk backends (masses, decisions,
  snapshot identities; `evidence/pse/equivalence_fresh_vs_shipped.json`,
  `evidence/pse/functional_fresh_build/`). The executable bytes differ from the shipped
  binary (another toolchain); both digests are recorded and a job binds the digest it ran with.
- **Three declared operations, no free parameters.** `graph.snapshot` (input kind
  `observation_batches`): the conditioned snapshot of an ordered batch history (identity,
  vertices, walk backend, engine statistics). `graph.region_mass` (`graph_query`): the
  normalized source-conditioned walk read out as regional mass at declared times with the
  declared threshold and deadband rule (`above`, `below`, `ambiguous`); a mass is a model
  readout, not a probability. `graph.window_reachability` (`graph_window_query`): the exact
  certificate of `exists t in [start, end]: mass(t) > threshold` over the represented binary64
  Laplacian. The query is declared data (binary64 values as 16-digit bit strings); a proposal
  with parameters is rejected before execution. Caps: 64 nodes, 128 batches, 256 times, 32
  windows, 1 MiB input, 4 MiB wire, 30 s per native process.
- **Same worker protocol as the standard-library adapter.** The numerical pack installs
  `adapters/native_graph.py` as `.gabriel_worker/native_worker.py`, the two executables as
  `.gabriel_worker/bin/*` (mode 755, digests in `job.json`) and runs `python3` on it inside the
  containment backend; the worker checks each executable's SHA-256 before and after every
  process, feeds compact canonical JSON on stdin, requires compact canonical JSON back and
  removes everything but the output. Inside the Linux namespace jail the executables run from
  the worktree mount (bound without `noexec`), with no network and no host filesystem.
- **Complete bindings.** `worker_build` is the digest of the worker file plus the digests of
  both executables, so a job cannot be bound while an executable is missing, and a changed or
  missing executable at execution time is `STALE_EVIDENCE`. The cache key binds the input
  bytes, operation, parameters, the profile `native-pse-graph-v1`, the worker build and the
  numerical environment; the inherited padded signature is never a key. A hit on the complete
  key re-issues the retained result together with the retained witness of the run that
  produced it (the hit path previously omitted the witness slot and was rejected by the
  reducer; fixed here and covered by a test).
- **Validation independent of the engine.** Every response is re-checked: field sets, schema
  and backend echo, `commits == 0` and `faulted == false` under the reviewed profile (decay 0,
  crystal commits disabled), the model string, mass in `[0, 1]`, the decision rule recomputed
  from threshold and deadband, the time identities, and for the exact export the snapshot
  identity recomputed from the exported vertices, degrees and adjacency, the FNV sensor vertex
  identifiers, symmetric non-negative adjacency and the batch history (ticks, observations,
  entity set). A violation is `invalid_input`, never a success.
- **Stage two in a dedicated host process.** For `graph.window_reachability` the contained
  worker exports the exact Laplacian; the pack then runs
  `python -m gabriel_agent.adapters.native_graph certify` as a separate host process
  (python-flint/Arb; the Arb context is never shared with unrelated work) over the validated
  snapshot and merges the certificates into the output. The job verdict follows the statuses:
  `computed` only when every window is `reachable` or `excluded`; any `out_of_scope` (the
  represented matrix is not a uniform clique) or `unknown` (precision ladder 128/256/512 bits
  exhausted) makes the job `out_of_scope` or `unknown`, retains the certificates in the
  diagnostics and leaves no output file. An unavailable arithmetic is `unknown`. The reference
  contract accepts `computed` only.
- **References independent of the engine.** `evaluation/fixtures/graph_walk.py` reconstructs
  the represented model from the declared construction rule (every pair co-observed in a batch
  is an edge of symmetrized weight 1/2 whatever the number of co-observations; degree is the sum
  of incident weights; vertices in first-observation order), evaluates the walk by a
  standard-library Jacobi spectral decomposition and, in tests, by scipy's matrix exponential,
  recomputes the snapshot identity from the reconstruction, and derives window statuses from
  the closed-form harmonic model of a uniform clique with a declared margin. On the fixture the
  three implementations agree to 5.6e-17 (test bound 1e-12), the reconstructed identities equal
  the engine's on seven histories, and the certificate statuses equal the closed form.
- **Cross-implementation signature check.** The standard-library canonical adjacency behind
  `graph.small_signature` and the engine's exhaustively verified S7 orbit index
  (`native_pse/crates/pse-metatron/data/s7_classes.bin`) induce the same isomorphism classes:
  exhaustively for every graph on up to five vertices (1, 2, 4, 11 and 34 classes) and on
  sampled graphs with isomorphic copies for six and seven vertices. The native word carries no
  vertex count, so the padded collision of the inherited index is reproduced and remains
  reported for comparison only.
- **Corpus tier `graph`.** Six tasks in three families (`graph-snapshot`, `graph-mass`,
  `graph-window`) with executed positive and negative controls and content-based verification
  (`gabriel eval corpus-check --tier graph`, `evidence/pse/graph_tier_check.json`). The tier is
  separate from the numerical tier, so the digests of protocol 5 and pilot 2 are unchanged
  (asserted by a test). The matched simple-loop comparator executes native operations through
  the same worker file in process, with the same dedicated certificate process.

## Measurements (`evidence/pse/measurements.json`; medians of 7; shared cloud container, magnitudes only)

| Quantity | trusted_local | linux_namespace |
|----------|---------------|-----------------|
| Native process, fixture query (4 entities, 5 times) | 1.7 ms | 1.9 ms (inside the jail) |
| Cold start: first native process after the executables were installed | 1.9 to 2.4 ms | |
| Identity validation (two SHA-256 passes over both executables, 2.6 MiB, before and after) | 2.5 ms | 3.3 ms |
| Query at the caps: 64 nodes, 256 times, auto backend / spectral_full; 128 batches | 4.0 ms / 7.9 ms; 4.3 ms | |
| Exact certificate: dedicated host process / arithmetic alone | 84 ms / 0.7 ms | 85 ms / 0.7 ms |
| Stage one: the fresh worker process in the backend (python start, identity, native process) | 86 ms | 234 ms |
| Worker-internal time (identity validation, native process, validation, output) | 6.3 ms | 6.5 ms |
| Job elapsed on the owner clock (snapshot, region mass; window with stage two) | 95 ms; 186 ms | 242 ms; 335 ms |
| Total task latency through the owner (observe, scripted propose, run, read-back, verify, review) | 0.67 to 0.78 s | 0.87 to 0.94 s |
| The same task again: hit on the complete job key | 0.56 s | 0.55 to 0.62 s |

The native computation itself costs one to eight milliseconds at the declared caps; process
starts (the worker interpreter, the jail, the certificate process) and the owner's pipeline
dominate the latency, and a cache hit saves the worker start only.

## What this establishes and what it does not
- The engine does what the review said it does, deterministically and reproducibly, and it is
  now an essential component in the only sense the blueprint allows: a first-class contained
  analytical worker with the same contracts, bindings, verdicts and verification as the
  standard-library adapter, selectable by the model among declared operations and judged by
  references it does not control.
- It establishes no learning, memory, crystal, resonance or reasoning claim: the reviewed
  profile forbids crystal commits and decay, and the response validation rejects any commit.
  The Betti, proof-of-resonance, marginal-gate and morphogenic features stay quarantined and
  unused. The exact certificate profile covers uniform cliques only; other histories are
  declared `out_of_scope`. The inherited Windows golden-fixture mismatch (23 of 78 engine-state
  hashes) is untouched and still unresolved.
- The graph tier is not part of any frozen advantage protocol and was not run against a
  provider: the operations are deterministic computations a model cannot perform itself, so
  such a run would measure orchestration only. The worker runs under the backend's `python3`
  (3.11 on this host) while the job binds the host's interpreter (3.12); both are retained, as
  for the standard-library worker.
- Dependencies: the executables are built from source per host (cargo); without them native
  operations are refused at proposal time with no substitute worker. python-flint is needed
  for stage two only; without it certificate jobs are `unknown`. numpy and scipy serve the
  test-side second reference only.
