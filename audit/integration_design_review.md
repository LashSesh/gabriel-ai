# Integration design review: Gabriel and the supplied Ophan runtime

Scope: read-only review of the named Gabriel modules and selected runtime files from `ophan_bridge-main`. This is not a claim that all 30 historical Ophan profiles or all embedded artifacts have been read or retested. No source or Gabriel implementation was modified. The checks below are proposed unless explicitly identified as source inspection.

## Strongest supported integration

The missing shared structure is an **executable owner runtime for deterministic, model-bound modules**. Gabriel already has mathematical state transitions, selective observation, immutable bitemporal snapshots, target maturity, and exact feedback accounting. It lacks one durable operational surface that hosts those branches, routes typed events, preserves their meanings, commits changes before publication, and reconstructs them after interruption. The Ophan repository contains concrete mechanisms for this operational layer. Its contribution should be extracted at this level, not by carrying across a Boolean or XR model and renaming it Gabriel.

The first integrated vertical slice should host two unchanged Gabriel implementations:

1. `finite_observation.Session` for selective observation and target agreement;
2. `maturity_ledger.MaturityLedger` for issued risk forecasts, completed target evidence, revisions, and feedback replay.

This connects the observation and risk branches without changing their mathematical results or predictive behavior. Hosting should demonstrate software properties—meaning-preserving execution, immutable provenance, interruption/replay, transactional rejection—not forecast improvement. The strongest new scientific statement is conditional trace equivalence between direct module execution and the hosted execution, supported by an induction argument and adversarial executable tests. It is a systems contribution, not a new learning theorem.

## Concrete source mechanisms worth retaining

| Source | Mechanism inspected | Adaptation |
|---|---|---|
| `grfps_l2.py:27,55` | restricted canonical JSON and duplicate-key rejection | Own versioned canonical schema, fixed exact wire types, no NaN/infinity, explicit binary64 hex if required |
| `grfps_l2.py:79` | configuration validation and typed operator dependencies | Small registry binding adapter ID, config, accepted commands, output schema, implementation identity |
| `session.py:70,129` | deterministic `reduce(event)` returning a candidate; time enters explicitly | One owner sequence; event/receipt clocks remain declared data; no hidden wall-clock sampling inside adapter |
| `map_runtime.py:22–40` | candidate computation, append/flush/fsync, state publication only afterwards | Durable commit-before-publish; failed writer becomes unusable until explicit recovery |
| `map_runtime.py:42–58` | reconstruct transitions and compare their semantics, not only their hashes | Replay re-executes every adapter command and compares output/poststate, rejecting rehashed tampering |
| `bank_journal.py:12–28` | streaming replay with optional projection collection | Do not retain every rendered historical state in memory by default |
| `source_identity.py:5–18` | declaration identity distinct from raw-trace identity | Distinguish source description, evidence bytes, and implementation IDs; hashes do not authenticate physical truth |
| `operator_port.py` | observation projection explicitly excludes external effects | Claims/predictions are read-only outputs; adding execution later requires its own implementation and tests |

Do not retain the fixed three-gene Boolean pipeline, latest-value TTL classification, XR frame registration, pose units, angular organs, or all historical demo galleries in the shared core. Those are domain/profile-specific. In particular, expiry of an XR pose is not expiry of a completed risk outcome. Frame epochs must not erase mature feedback or silently rewrite forecast issues.

## Exact host interface

A small implementable interface is sufficient:

```python
class Adapter:
    def contract(self) -> dict: ...
    def snapshot(self) -> dict: ...
    def reduce(self, command: dict) -> tuple['Adapter', dict]: ...

class Runtime:
    def commit(self, envelope: dict) -> dict: ...
    def snapshot(self) -> dict: ...
    @classmethod
    def reopen(cls, journal_path, registry): ...
```

`reduce` must not mutate its receiver or perform external I/O. A thin candidate copy of the legacy module is acceptable for the first bounded implementation. A reconstruction-based copy is slower but avoids unexpected sharing of caches. If deep copying `Planner`, remember that its `lru_cache` wrappers contain bound methods: catalogue immutability makes those method caches logically harmless, but generic deep-copy isolation should not be presumed for arbitrary adapters.

A frozen manifest should bind:

```text
schema, runtime_profile, registry_digest,
module_id -> {adapter_id, adapter_version, config_digest, implementation_digest},
canonicalization, max_events, max_event_bytes, max_journal_bytes
```

An outer command envelope should have a strict schema such as:

```text
schema, command_id, module_id, contract_digest,
operation_time, command
```

The outer operation sequence is distinct from domain event time, receipt time, forecast origin, and target endpoint. Do not reinterpret one integer field as all of them. Equal operation timestamps are ordered by the accepted sequence. Maintain explicitly whether a query/snapshot command advances the outer sequence while leaving the module's accepted-operation prefix unchanged.

An accepted transition can bind:

```text
sequence, parent_digest, envelope,
prestate_digest, poststate_digest, output,
transition_digest
```

The journal header contains enough manifest/configuration data to reconstruct fresh modules. Untrusted journal records must not select arbitrary imports, code, or callbacks; the registry is fixed by the executable. A configuration hash alone is insufficient to identify a scoring implementation. If binding source hashes, bind the transitive module implementation set or a versioned distribution manifest.

For duplicate `command_id`, an identical canonical envelope returns the original committed response without re-execution or extra accepted transition. Conflicting reuse is rejected. This outer idempotency is deliberately distinct from module-level idempotency: direct `finite_observation.Session.ingest` can accept a repeated source observation as a no-op while advancing its cutoff.

Schema/contract validation and adapter reduction occur before durable mutation. A reduction failure publishes no candidate state. A failed/partial journal write publishes no candidate state and stops further writes in the current owner. Reopen must reject an incomplete line by default, or use an explicit separately tested recovery policy; never silently ignore corrupt tails while claiming complete replay.

Ordinary hash chaining detects alterations relative to a trusted head. It does not resist full rewriting by an attacker controlling the file and the supposed trusted head. Directory fsync, operating-system/filesystem guarantees, concurrent writers, locking, and power-loss recovery are separate scope questions. A single-owner process profile can state these constraints directly.

## Adapter 1: finite selective observation

Existing imports/signatures:

```python
from finite_observation import Catalogue, Planner, Session, Observation

c = Catalogue(contract_id, query_names, costs, rows, labels, weights=())
p = Planner(c)
s = Session(p)
accepted = s.ingest(
    Observation(c.identity, query, outcome, source_id,
                event_interval, received_at,
                status='observed', kind='passive'), cutoff)
result = s.result()
next_query = p.choice(s.state, policy)
worst_cost = p.value(s.state)
```

`Catalogue` uses canonical outcome strings, positive integer costs and weights, and integer target labels. `Session` has `state` bitmask, `seen`, evidence `ledger`, and `cutoff`. A supplied observation must match the catalogue identity, be an actual passive observation, complete by its receipt, and be available at cutoff. Repeated source IDs with conflicting query/outcome/interval are rejected.

The hosted snapshot should include the exact legacy `result()`, state as hexadecimal text, cutoff, next query, finite worst cost or an explicit infinity token, and a digest of the ordered evidence ledger. The projection should retain native status:

| Legacy status | Safe common projection |
|---|---|
| `decided` | `Known` **conditional on the declared finite catalogue**, with exact target label and supporting state |
| `unresolved` with multiple target labels | `Ambiguous` within the model; preserve all compatible target values |
| `conflict` (empty set) | `Invalid` **relative to this model/evidence contract**, with explicit reason `no_compatible_history` |

`Unknown` should denote absent/unbound evidence or no operational evaluation, not be used to erase a known model conflict. An out-of-model true history can still agree with a modeled observation and produce a wrong external target: the runtime does not fix model coverage.

Natural existing data: `domain_adapters.transport_records()` and `event_records()`, then `build_catalogue(...)`. Both exercise the same planner without external downloads. Preserve nuisance-coordinate removal as its own existing operation, not a new runtime discovery.

## Adapter 2: forecast maturity and risk feedback

Existing imports/signatures:

```python
from sequential_contract import EventRevision
from maturity_ledger import TargetRequirement, IssuedForecast, MaturityLedger
from replay_adaptive_maturity import score_outcome, reduce_controller

m = MaturityLedger(score_outcome, scoring_rule_id, availability_mode)
f = IssuedForecast.create(forecast_id, origin, target_end, issued_at,
                          requirements, prediction, lane_id, provenance)
m.issue(f)
m.append(EventRevision.create(source_id, record_id, revision,
                             event_interval, received_at, vintage_id, payload))
b = m.snapshot(event_cutoff, receipt_cutoff, operation_cutoff=None)
state = b.replay(initial_state, reduce_controller, lane_id)
```

`replay_adaptive_maturity.score_outcome` consumes two endpoint dictionaries with positive finite `rate_hex` values and a retained prediction with `var_hex`. It computes binary64 `100*log(right/left)` and an exceedance Boolean. This is numerical scoring, not exact physical arithmetic. `reduce_controller` computes `theta_units += 39 if hit else -1`, clips to `[-800,800]`, and increments `updates`; that controller accounting is exact integer arithmetic. It corresponds to the already frozen primary `eta=1/20`, beta `1/40` and denominator 800. Do not silently generalize this reducer to configurable steps without implementing the matching arithmetic.

Wire payloads retain rational/hexadecimal strings; exact `canonical()` rejects native floats. Each forecast issue remains immutable. Targets require all endpoint receipts and the completed target. Corrections replace the active score at its first-maturity order rather than adding another target. Historical issue outputs and earlier snapshots remain unchanged.

Hosted snapshot can carry `FeedbackSnapshot.identity`, the exact ordered active-score identities, pending forecast IDs, accepted module-operation prefix, and per-lane replayed controller states. After no operations there is no valid legacy `snapshot`; use an explicit empty state, not a fabricated mature snapshot.

One subtle issue: a runtime-wide sequence counts commands across modules, but `MaturityLedger.operation_cutoff` counts only accepted issue/receipt operations inside that module. Store both. Never pass the runtime sequence as the legacy cutoff. Snapshot/read commands should neither become fictitious mature observations nor advance the legacy prefix.

The initial executable demonstration may use synthetic source endpoints and saved predictions. A stronger direct-parity test should stream a bounded prefix from the delivered `adaptive_risk_predictions.npz` with historical availability explicitly marked `historical_replay_without_vintages`. No new-market evaluation is needed or implied.

## A precise semantic-preservation claim

Let `D_i` be the direct state of module i under its accepted command subsequence and let `H_i` be the corresponding hosted state. Assume identical initial configuration, identical deterministic module implementation and serialization, an adapter whose command translation invokes the same legacy operation, and publication only after a successful complete journal append. If `P_i(H_i)=D_i` initially and the adapter commutes with each accepted legacy transition, then `P_i(H_i)=D_i` after every accepted command; a rejected command preserves the previous equality. Proof: induction on owner commands, with the untargeted modules unchanged. Semantic journal replay reproduces the same sequence under the same assumptions.

This is a conditional implementation invariant. Testing commutation for many traces is evidence about the supplied adapters, not a proof covering arbitrary adapters. Write-success is subject to the declared filesystem semantics. Prefix non-anticipation follows because future unaccepted events are not supplied to the reducer, but only if the adapter itself has no hidden reads or random state.

The recurrent-core contraction theorem does not automatically apply to this runtime: a historical log deliberately retains differences indefinitely. The runtime does not need to be contractive to preserve the behavior of a contractive hosted cell module. Do not market persistence as a new attractor theorem.

## Falsifiable validation plan

The following are meaningful checks of a new integration, not mirrors of one serialization function:

1. **Direct versus hosted finite observation:** use both existing domain catalogues; for every modeled history and multiple policies, call legacy `Session.ingest` independently while sending the same command to the host. Compare result, compatible set, next query, and total query cost at every step. Include unresolved, decided, and empty-compatible-set cases.
2. **Direct versus hosted maturity:** independently instantiate the legacy ledger and feed matched issues/receipts including delayed endpoint, equal-time operation ordering, corrections and multiple lanes. Compare each feedback identity, active-score order, pending set, and replayed exact controller state. Use initial checkpoints explicitly when testing saved historical forecasts.
3. **Interleaving isolation:** interleave events for both hosted modules; compare each projection with its direct subsequence. A mutation to observation history must not change risk state and vice versa.
4. **Prefix replay/restart:** at multiple cut points, close and reopen from disk; continue the same suffix and compare full final state/output sequence with an uninterrupted reference. Avoid claiming a checkpoint accelerator unless it is implemented and similarly checked.
5. **No anticipated maturity:** omit or delay the target endpoint; the target remains pending even after wall-clock/event target time passes. Revision of one endpoint replaces exactly one score at its original position.
6. **Rejection atomicity:** wrong model contract, backdated receipt, reused command ID with changed payload, unsupported action, wrong scalar type and exhausted budgets must preserve prior owner and module states. The observed rejection itself can have an external diagnostic record, but must not become a fictional successful transition.
7. **Commit failure:** inject an append exception/partial write. Verify no candidate publication, poisoned writer, and rejection on incomplete replay. Test a complete unacknowledged record on reopen as a separate crash window.
8. **Tampering beyond hash checks:** alter a stored output or poststate and recompute every subsequent hash. Re-execution still must reject semantic disagreement. Altering the entire header plus all valid events can describe another valid run; compare a trusted expected manifest/head for that distinct threat.
9. **Strict parser:** duplicate object keys, NaN, infinity, native floats in exact wire payloads, huge input beyond documented cap, and bool used as integer must be rejected before mutation.
10. **Bridge scope and arithmetic:** hex encode/decode roundtrip for finite binary64 values; no status projection upgrades numerical equality into a rounding certificate or model-conditional decision into physical truth.

Record test counts as actual implemented/executed counts only. Keep equality tests exact where the hosted adapter calls unchanged legacy modules; use no broad tolerance to hide altered risk forecasts. Mathematical formulas, training data, and fitted weights remain untouched by this phase.

## Packaging and manuscript placement

Keep the full Gabriel manuscript and all prior results. Add one methods section specifying the owner/adapter contract, one integration-results section with executed parity/replay evidence, and a small scope paragraph. The title need not claim a complete perception OS or general financial competitor.

Ship a single integrated Python package or a clearly bounded runtime subdirectory with a command-line `demo`, `replay`, `inspect`, and `verify` path; include actual journal/config/example outputs and tests. Existing research scripts remain accessible. Do not bundle the complete Ophan repository and its nested historical releases into the already large Gabriel artifact merely to claim assimilation. Document exactly which mechanisms were extracted and which XR-specific profiles remain unused. The source archive can be cited by local SHA-256 in the separate development report without becoming a required execution dependency.

The expected useful outcome is a coherent executable system boundary around two existing substantive Gabriel capabilities. Increased reliability of application/replay is a concrete gain; prediction accuracy and learned decision functions remain unchanged by design.
