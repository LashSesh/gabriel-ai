# Gabriel runtime reference contract

This package hosts unchanged finite-observation and forecast-maturity algorithms through deterministic replay adapters. It adds an operational lifecycle, persistent transactions and reproducible dispatch. It does not change forecasts, certify physical data, or execute financial or XR actions.

## Owner interface

`Store.create(path, registry, limits=None)` creates a new store. `Store.open(path, registry, expected_head=None, expected_events=None)` reconstructs an existing store after checking its bound registry fingerprints. `default_registry()` supplies the two implemented adapters. `submit(command)` atomically commits a unique command and returns its retained receipt; `view(contract_id)` returns the current adapter projection; `audit(expected_head=None, expected_events=None)` semantically replays the log; `export()` returns exact JSON `{header, records}`. Optional expected head/count values are caller-supplied external anchors: they can detect a valid but unintended prefix or replacement run when kept separately from the mutable store. A store cannot establish its own completeness merely from its internally consistent log. `head` is the current committed frontier and `budget` contains accepted event and canonical-byte counts. Stores support `close()` and context managers.

Every command has exactly these fields:

```json
{"id":"unique-command","contract":"local-contract","op":"bind","at":0,"expected_head":"CURRENT_HEAD","payload":{"adapter":"finite-observation/v1","config":{}}}
```

The example `config` is a placeholder; complete configurations are specified below. `at` is a nonnegative owner operation time. New commands must be monotone in that time and carry the current `expected_head`. The first command for a contract uses `op="bind"` and payload exactly `{adapter, config}`. The binding is immutable. Commands use short nonempty ASCII identifiers and the versioned exact JSON format defined by `canonical.py`: null, Boolean, safe integer (absolute value at most `2**53-1`), ASCII text, list, or string-keyed object. Floats, duplicate keys, unsupported types and excessive nesting are rejected. Boolean and integer types are distinct. Binary64 domain values are represented explicitly as canonical `float.hex()` strings, not native JSON numbers.

The receipt has `{sequence, command_id, contract, result, head}`. Retrying the identical canonical command with the same ID returns exactly the original receipt, even after its frontier has become old. This does not re-execute the adapter or consume budget. Reusing its ID with changed bytes fails. A different ID invokes the domain operation again; the legacy operation can itself be an idempotent no-op while the unique owner command still consumes an event and its canonical bytes.

Default owner limits are 10,000 commands, 10,000,000 cumulative command bytes and 65,536 bytes per command. These are engineering accounting limits, not CPU, memory or hard real-time guarantees. The adapters impose smaller workload caps described below. Adapter calls are trusted local code, not sandboxed plugins.

SQLite uses rollback journal mode `DELETE`, `synchronous=EXTRA` (numeric value 3), and an immediate transaction. State, output, journal and accounting are committed together; responses are exposed after commit. Multiple handles serialize writes and read the current committed state before reduction. Crash behavior remains subject to SQLite/VFS/filesystem/storage semantics. The package does not claim proof against arbitrary power-loss/storage failure. It provides test-only crash hooks before commit and after commit before acknowledgment. No network service, worker scheduler, OS kernel, source authentication or effect executor is supplied.

Adapter fingerprints bind the relevant local Python source files, adapter code, shared `engine.py` and `canonical.py`, fixed rule identities and, for numerical risk scoring, the NumPy version. These hashes identify declared local implementation bytes; they do not authenticate a sensor or prove that a host executes those bytes honestly. Legacy modules are resolved exclusively from this project's `reproduction/` directory; a preloaded same-name module from another location causes rejection. No user-configured Python import or callback is executed.

## Finite observation adapter

Adapter identifier: `finite-observation/v1`.

Configuration has exactly:

```json
{"contract_id":"example-catalogue","query_names":["q0","q1"],"costs":[1,1],"rows":[["0","0"],["0","1"],["1","0"]],"labels":[0,1,1],"weights":[]}
```

There must be 1–32 rows, 1–12 unique query names, canonical ASCII outcome strings, positive integer costs, integer target labels, and positive integer multiplicities. Empty `weights` normalizes to one per row through the unchanged `Catalogue` constructor. Configuration rows, query names, costs, labels and weights are explicit JSON lists. Contract IDs have at most 512 characters, query/source IDs 128, and outcomes 256. The finite model is immutable for a bound contract.

The only domain operation is `observe`. Its payload has exactly:

```json
{"query":0,"outcome":"0","source_id":"sensor-record-0","event_interval":[0,0],"received_at":1,"status":"observed","kind":"passive","cutoff":1}
```

All clocks and query indices are exact nonnegative integers. The native completed event interval must end by `received_at`, which must not exceed `cutoff`, which must not exceed owner command `at`. The adapter supplies the catalogue digest internally. It invokes the unchanged `Session.ingest` with this observation and cutoff. Only actual passive evidence is allowed. A source identifier is bound to its query, value and event interval; conflicting reuse fails. Identical source content is a legacy no-op that may still advance the cutoff. Revisions of a finite immutable input require a new contract, not a silent rewrite.

The operation result is `{accepted, view}`. `accepted` is the unchanged native Boolean. `view` contains:

```text
semantic_profile: "finite-catalogue/v1"
catalogue_digest: original Catalogue.identity
result: original Session.result() object
compatible_mask: hexadecimal candidate-state mask
next_query: minimax query index or null
worst_case_cost: exact integer or null
cost_status: "finite" or "infinite"
evidence_count: number of unique accepted native observations
```

Native result statuses remain `decided`, `unresolved`, and `conflict`. In particular an empty compatible set is `conflict`, not a successful or ambiguous decision. A `decided` label is conditional agreement within the supplied model. It does not prove that the true external history belongs to the catalogue. Null worst-case cost together with `cost_status="infinite"` denotes impossible complete identification under the finite model.

State stores configuration and at most 256 submitted observation operations, including native no-ops that advance cutoff. The adapter reconstructs a fresh `Catalogue`, `Planner` and `Session` on each invocation. Minimax planning may be exponential in the finite model; the caps bound the reference problem size, not practical worst-case latency. This is not an optimized live-stream implementation.

## Maturity and risk adapter

Adapter identifier: `maturity-risk/v1`.

Configuration has exactly:

```json
{"scoring_rule_id":"binary64-upper-loss-hit-primary-v1","availability_mode":"historical_replay_without_vintages","initial_states":{"0":{"theta_units":0,"updates":0}}}
```

The scoring-rule ID is fixed to the displayed implementation. Availability mode is either `declared_observed_receipts` or `historical_replay_without_vintages`; neither authenticates timestamps. Bind 1–16 named learner lanes. Every initial state has exactly `theta_units` (integer in `[-800,800]`) and `updates` (nonnegative integer). Initial states can be supplied historical checkpoints; preceding learning history is then outside the replay claim.

The scorer and reducer are the actual `score_outcome` and `reduce_controller` functions in `replay_adaptive_maturity.py`. The scorer computes binary64 `100*log(right/left)` and compares it with the issued VaR. The adapter additionally rejects nonfinite computed loss, including division overflow/underflow despite individually finite positive endpoints. The reducer adds 39 after an exceedance or -1 otherwise, clips integer units to `[-800,800]`, and increments updates. This is the existing beta `1/40`, step `1/20`, unit `1/800` controller, not a freely configurable learning algorithm.

`issue` payload has exactly:

```json
{"forecast_id":"f0","origin":0,"target_end":2,"issued_at":0,"requirements":[{"source_id":"price","record_id":"p0","event_start":0,"event_end":0},{"source_id":"price","record_id":"p2","event_start":2,"event_end":2}],"prediction":{"var_hex":"0x1.0000000000000p+0","es_hex":"0x1.0000000000000p+1"},"lane_id":"0","provenance":{}}
```

Exactly two requirements name the origin endpoint and target endpoint in that order. Predictions contain exactly finite canonical `var_hex` and `es_hex`, with `0 < VaR <= ES`. `origin <= issued_at < target_end`. In `declared_observed_receipts` mode the issue must satisfy `issued_at ==` owner `at`; submitting a new live issue after its declared issue time fails. In `historical_replay_without_vintages` mode importing an older issue is permitted with `issued_at <=` owner `at`, and every view explicitly declares `issuance_basis="historical_declaration"`. The lane must be prebound. Provenance is an exact JSON object. The legacy immutable `IssuedForecast` retains its native identity. Requirements cannot be supplied in reverse order or as an arbitrary two-value difference model.

`outcome` payload has exactly:

```json
{"source_id":"price","record_id":"p2","revision":0,"event_interval":[2,2],"received_at":3,"vintage_id":"v0","payload":{"rate_hex":"0x1.9c00000000000p+6"}}
```

The rate must be finite, positive and in canonical `float.hex()` form. Endpoint events are point intervals. Event completion is no later than declared receipt, and receipt is no later than owner `at`. Revisions start at zero, advance consecutively and preserve the original source-record interval. Declared receipt order must remain compatible with the native ledger. New commands may ingest older event times, but cannot backdate new receipts within that ledger.

Owner `at` and declared domain receipt time are distinct: outcome ingestion may happen after the declared receipt. New live issues instead bind their issue time to the owner operation time. This remains a declared computational clock, not authenticated wall time. Historical imports make a weaker claim and remain labelled as such. The runtime does not certify historical issuance or source authenticity.

Both issue and outcome return `{accepted, view}`. Accepted native operations are stored once; admitted duplicate native issues/receipts do not increase the module-operation prefix or learner update count. They may still be distinct owner commands with their own charge. In live mode a duplicate issue under a new owner command ID is also subject to `issued_at == at`; use the original command ID and identical bytes for a later transport retry. The default view after either operation is the native snapshot at the ledger's current declared clock for both cutoffs.

`query` payload has exactly:

```json
{"event_cutoff":2,"receipt_cutoff":3,"operation_cutoff":null}
```

Cutoffs are exact nonnegative integers no later than owner `at`; the native ledger also requires receipt cutoff no later than its observed clock. `operation_cutoff` is null (all accepted **module** issue/receipt operations) or their explicit nonnegative prefix length. It is never the owner-wide sequence, which also counts other modules, queries and binds. Querying an empty ledger fails. Queries may select an older snapshot and do not create new outcomes or feedback; the query is retained as the adapter's current displayed selection.

Every maturity view, and the direct result of a query, has:

```text
semantic_profile: "maturity-risk/v1"
arithmetic: "binary64"
issuance_basis: "declared_owner_receipt" or "historical_declaration"
feedback: JSON-normalized asdict(original FeedbackSnapshot), or null initially
feedback_digest: original FeedbackSnapshot.identity, or null initially
controller_states: per-lane replay from the supplied initial checkpoints
module_operation_count: accepted native issue/receipt operations
```

Tuple-to-list conversion happens explicitly at the legacy dataclass boundary. Canonical byte identity remains the outer comparison rule. Scores are tagged binary64; exact integer controller accounting does not make the log-return arithmetic exact or establish conditional calibration. Predictions are never labelled empirically `Known`.

Pending targets require both completed endpoint events and available receipts. There is one active score per issued forecast. A correction substitutes that score at its original first-maturity position and causes current-state replay; it does not add another target, alter the original forecast, or mutate an older stored snapshot. The adapter never expires historical risk evidence because an unrelated observation transport or XR frame changes.

At most 256 accepted module operations are stored. Each call reconstructs the ledger; each snapshot reselects the evidence and replays current scores. Repeated inspection over a growing history can therefore incur quadratic work, with additional cost for repeated per-lane replay. This is a bounded reference owner, not a throughput claim. The exact query budget and the mathematical learning result are separate from this engineering limit.

## Claim boundaries

The integration target is direct-versus-hosted trace equivalence, preservation of contract isolation, transactional rejection, and deterministic recovery under the declared environment. Mathematical assumptions and numerical limitations of the hosted modules remain in force. The persistent journal is not a contractive dynamical state; adding persistence does not extend the recurrent-core contraction theorem. No advantage in predictive accuracy, general intelligence, physical perception, market performance, adversarial source authentication, or deployed financial infrastructure follows from successful runtime tests.
