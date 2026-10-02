# Durable source-conditioned graph observations

`graph_observer.py` registers a bounded native graph observer with the existing
`gabriel_runtime.engine.Store`. It uses the same SQLite transaction, expected-head,
immutable journal, retry and semantic replay mechanisms as the other adapters.
The financial adapters and their prediction rules are unchanged.

The profile evaluates a normalized source-conditioned continuous-time graph walk.
Its region mass is a **model readout**, not calibrated uncertainty, an empirical
probability of an external event, or proof of predictive superiority. A declared
threshold and nonnegative deadband produce `above`, `below` or `ambiguous`.
The deadband is a user-selected decision rule, not a rigorous rounding enclosure.

## Build and execution

From the project root, with Rust 1.95.0 and the locked dependencies available:

```sh
CARGO_PROFILE_RELEASE_LTO=false CARGO_PROFILE_RELEASE_CODEGEN_UNITS=1 \
CARGO_BUILD_JOBS=1 cargo build --locked --offline --release \
  --manifest-path native_pse/Cargo.toml --example engine_observer
sha256sum native_pse/target/release/examples/engine_observer
python -m gabriel_runtime.graph_observer demo /absolute/new-demo-directory \
  --executable /absolute/path/to/engine_observer --sha256 EXPECTED_SHA256
python -m gabriel_runtime.graph_observer audit /absolute/new-demo-directory \
  --executable /absolute/path/to/engine_observer --sha256 EXPECTED_SHA256
```

The executable path and its expected hash must be supplied explicitly. No command
string is interpreted by a shell. The profile invokes a fresh local process for
every accepted `append_batch` or `query` command and reconstructs its Engine from
the complete retained batch history. This deliberate reference implementation
pays process startup, JSON, hash checks and replay costs before every query batch.
It does not retain a native process or native graph plan between owner commands.

`--backend` selects `spectral_full`, `auto_full` or `auto_region` for a new demo.
All use the same Engine-produced graph, source normalization and scalar decision
contract. The latter can evaluate a complete-graph region using precomputed scalar
coefficients. Generic graphs fall back to a full state readout. Backend selection
is immutable after the contract has been bound.

## Exact wire and bounded state

The native CLI accepts compact sorted-key ASCII JSON on standard input, with one
optional final newline. It rejects duplicate keys, unknown fields, noncanonical
representations and input exceeding 4 MiB. Finite binary64 values are encoded as
exactly sixteen lowercase hexadecimal IEEE-754 bit digits. This encoding preserves
bits without suggesting exact real arithmetic. Vertex identifiers in responses
are decimal strings because their u64 domain exceeds the owner's JSON integer cap.

The request schema is:

```text
{schema, backend, batches, queries}
batches = [[entity, ...], ...]
queries = [{source, targets, times_bits, threshold_bits, deadband_bits}, ...]
source = [{entity, re_bits, im_bits}, ...]
```

The schema string is `gabriel-engine-observer/v1`; entity labels are integers in
`[0,63]`. Hard caps are 64 distinct entities, 128 retained batches and 256 query
time points. The Python binding configuration may lower these limits, and checks
query capacity cumulatively over all accepted queries. The native CLI independently
checks its hard caps per invocation. A batch must be nonempty and cannot contain
an entity twice. Every query source must cover all current entities exactly once;
unknown labels and duplicate targets are rejected. Empty target regions are valid.

Each entity is converted to the source ID `sensor-i`. Its Engine observation is
the UTF-8 serialization of sorted-key JSON containing `entity`, zero-based batch
`tick`, and `phase: 0.0`. The fixed adapter supplies phase hint zero, timestamp equal
to the batch index, and the payload's content digest. The Engine uses default
configuration with `persistence.lambda_decay = 0` and
`consensus.min_crystal_tick = u64::MAX`. Thus no crystal commit is claimed by this
profile. Batch index is the graph observation clock; owner receipt time is a
separate exact integer retained with each issued query.

An accepted query retains its request, owner receipt time, batch count, snapshot
identity, numerical readout and decision. Later graph batches do not rewrite
those issued observations. An invalid command rolls back the existing Owner's
transaction; native errors never partially publish a graph query.

## Identity and reproducibility

The adapter fingerprint binds its Python owner/canonicalizer, native sources,
Cargo manifests and lockfile, the selected executable's SHA-256, schema and caps.
It checks source and executable bytes again before and after each subprocess.
These are consistency guards over trusted local code, not authentication,
sandboxing, or proof that the binary was compiled from those source files.
Build-command provenance supplies a separate relationship between source and binary.

The executable's filesystem path is not part of the semantic fingerprint, so
identical bytes can be relocated on the same numerical execution environment.
Exact replay compares binary64 output bits. Different CPU, math libraries, toolchain
or rebuilt executable may legitimately fail that exact identity/replay contract.
The profile does not promise bitwise portability across numerical environments.
Before/after file hashes also do not establish race-free protection against an
adversary replacing files during execution.

A 30-second subprocess timeout and bounded input/output are enforced. Native stdout
and stderr use temporary files; response parsing rejects output above 4 MiB.
This is a trusted executable interface, not a resource sandbox for hostile code.

## Reproduction checks

```sh
python reproduction/check_graph_observer_owner.py \
  --executable /absolute/path/to/engine_observer --sha256 EXPECTED_SHA256 \
  --output /absolute/new-check-directory --skip-timings
```

The script checks three-backend agreement, exact semantic replay, immutable issued
records, identical retries, rollback, lower resource caps, changed executable/source
identity, same-byte executable relocation, and native direct malformed requests.
Its optional query-command timing includes `Store.submit`, fresh process startup,
Engine replay, identity checks, JSON and SQLite EXTRA commit, but excludes store
creation, binding and previous ingestion. Complete create-to-close workflow timing
is a separate experiment. Neither timing scope measures forecast accuracy or
whole-system superiority.
