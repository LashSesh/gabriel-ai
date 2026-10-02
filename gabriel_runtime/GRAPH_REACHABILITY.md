# Durable continuous-time regional reachability

`graph_reachability.py` is an opt-in profile of the unchanged SQLite `Store`.
It asks whether there exists a time in a supplied **closed interval** at which
normalized regional mass is **strictly greater** than a supplied threshold.
An exclusion means mass is at most the threshold throughout that interval.
Equality therefore does not establish reachability. There is no numerical
deadband in this contract.

The source components and native represented Laplacian entries are interpreted
as exact dyadic rationals encoded by finite binary64 bit strings. The source is
mathematically normalized. This is a new mathematical observation contract; it
does not promise byte equality with the older binary64 `mass_at` calculation.
The readout is a graph-model quantity, not a calibrated probability of an
external event, a financial prediction, or a crystal-commit claim.

## Execution and ownership

Register `GraphReachabilityAdapter(executable, expected_sha256)` under
`native-graph-reachability/v1`. Both executable path and lowercase SHA-256 are
explicit. Bind with configuration `{max_nodes, max_batches, max_windows}`;
the hard maxima are 64, 128, and 32 respectively. Lower limits are allowed.

The only graph operation is `observe`. Its exact payload fields are:

```text
{
  batches: [[entity, ...], ...],
  source: [{entity, re_bits, im_bits}, ...],
  targets: [entity, ...],
  windows: [{start_bits, end_bits}, ...],
  threshold_bits: sixteen lowercase hexadecimal digits
}
```

All bit strings encode finite binary64 values. Entity labels are integers from
0 through 63. Every source covers the entire resulting graph exactly once and
must be nonzero. Targets may be empty but cannot repeat. Thresholds lie in
[0,1]; window endpoints may be negative or equal and must be in ascending
order. A command has one to 32 windows, and the configured window capacity is
cumulative across the contract. Its new batches are appended in order to the
retained history. An empty new-batch list is allowed when history already exists.
All members are validated before native execution or certification.

One accepted `observe` produces one atomic Store event, even when it ingests
several batches and certifies several windows. The whole command rolls back on
invalid input or an execution failure. It does not publish intermediate append
receipts. Identical retries return the original receipt without another native
invocation. Expected-head checks, command IDs, owner receipt ordering, budgets,
SQLite DELETE/EXTRA, immutable issued records, and semantic replay are the
unchanged Store mechanisms. The default 65,536-byte Store command limit applies;
the adapter independently limits the payload to that size.

Every observation launches a fresh native process and replays the complete
retained batch history through public Engine ingestion. The Engine uses the same
sensor labels, observation bytes, zero phase hint, zero decay, and disabled
crystal commits as the older graph observer. The native process exports the
actual frozen snapshot; no raw graph mutation substitutes for ingestion.

The `gabriel-engine-snapshot/v1` request is `{schema, batches}`. Its response has
`{schema, engine, snapshot}`. The snapshot includes `identity`, `tick`, ordered
`vertices` as entity/u64-decimal-ID pairs, `degree_bits`, sorted directed
`adjacency` entries `{from,to,weight_bits}`, and a model marker. Edge endpoints
are dense indices in vertex order. Python reconstructs the snapshot digest from
the actual exported bits before certification. Directed weights represent the
symmetrized adjacency of the conditioned snapshot; the certificate matrix uses
their negatives off diagonal and the exported degrees on the diagonal.

## Certificates and limits

The certificate implementation uses the fixed precision sequence 128, 256, and
512 bits. Each window returns `reachable`, `excluded`, `unknown`, or
`out_of_scope`, together with the certifier's evidence. Exact uniform complete
graphs use their harmonic regional-mass formula. A valid graph outside the
supported analytic class returns `out_of_scope`; samples are never promoted to
a proof of absence. Precision exhaustion returns `unknown`.

Each immutable issue retains the full request, owner receipt time, complete
native export, certificates, batch count, and canonical issue digest. The
profile fingerprint binds the certificate schema, precision policy, model,
caps, production source bytes, executable bytes, Python version, python-flint
version, installed flint Python/extension bytes, and wheel-bundled arithmetic
libraries. Exact serialized dyadic certificate bounds support deterministic
Store replay in that bound environment. Portability across changed libraries,
platforms, or binaries is not promised.

Source and executable bytes are checked before and after every fresh invocation
and certification calculation. These checks cover trusted local code and are
integrity guards, not authentication or race-free protection against a hostile
filesystem. Native input/output are capped at 4 MiB; native execution has a
30-second timeout and uses bounded reads from temporary stdout/stderr files.
Certification work is bounded by window count and the fixed precision policy.

Arb's precision context is process-global. Use controlled single-process
contexts and a fresh interpreter with immutable production files; unrelated
code must not change flint context during a certificate call. The certifier's
own lock coordinates its own calls, not arbitrary external flint users. File
fingerprints identify bytes on disk, not a signature of already loaded Python
code or memory. The arithmetic fingerprint covers installed package and bundled
library files; it does not cover external system libraries. Output length is
checked after native exit, so temporary disk output can grow until exit or the
timeout. This trusted-code bridge is not a hostile-process resource sandbox.

The old graph-observer adapter, its executable, its source fingerprint closure,
old receipts and history, and default financial routes remain unchanged. New
files are additive; they do not revise the old journal contract.

## Build and checks

With the locked Rust dependencies and python-flint available:

```sh
CARGO_PROFILE_RELEASE_LTO=false CARGO_PROFILE_RELEASE_CODEGEN_UNITS=1 \
CARGO_BUILD_JOBS=1 cargo build --locked --offline --release \
  --manifest-path native_pse/Cargo.toml --example engine_snapshot
sha256sum native_pse/target/release/examples/engine_snapshot
python reproduction/check_graph_reachability.py \
  --executable /absolute/path/to/engine_snapshot --sha256 EXPECTED_SHA256 \
  --output /absolute/new-check-directory
```

The integration checker covers native malformed requests, exact snapshot
identity, bounded atomic commands, no native work for invalid members, retry,
rollback, stale heads, immutable issues, source/executable identity checks,
relocation, and cold semantic replay. It makes no timing or predictive claims.
