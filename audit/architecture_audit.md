# Ophan Bridge architectural extraction audit

Source: `tmp/ophan_ingest/ophan_bridge-main`, supplied repository headed by GRFPS 0.30.0. This is an architectural/code audit, not a certification of every file. No source files were modified. Read-only imports used `PYTHONDONTWRITEBYTECODE=1`.

## Decision

The repository has a useful executable systems contribution: a deterministic, evidence-scoped reducer; explicit admission and retirement; append-before-publish journaling; replay that recomputes transitions; bounded acquisition; and projection that retains evidence/limitations. These are suitable for a domain-independent Gabriel control and evidence spine.

Copying the entire latest XR implementation would carry substantial accidental complexity. The actual MRO has **18 bank classes**: Reference3D → Pose3D → Report3D → XR3D → Flow3D → Stream3D → Feedback3D → Temporal3D → Capture3D → Producer3D → Acquisition3D → Revision3D → Carrier → Source → Noisy → Uncertain → Registered → Organ. This was inspected by importing `Reference3DBank` and reading `__mro__`. The classes combine old discrete 2D worlds, later 3D geometry, several revisions of data acquisition, and recent instrument contracts. New Gabriel should extract their invariants into explicit components, not replicate historical subclass layers.

Neither this repository nor its integration establishes improved risk prediction, market superiority, a general perception theory, or a deployed XR operating system. The strongest immediate gain is an executable boundary around existing Gabriel computations: what was issued, on what evidence and model version, when its outcome became usable, and exactly which state changed.

## Implemented invariants worth carrying forward

| Invariant | Actual implementation | Gabriel use and necessary qualification |
|---|---|---|
| Strict canonical event representation | `grfps_l2.py:27–64`: ASCII canonical JSON, sorted keys, integer range, no floats, duplicate-key rejection. `reference3d_segments.py:12–14,55–56` canonicalizes before reduction. | Canonical records and content identity. Floating forecast outputs need an explicit exact byte/hex encoding; serialization does not certify their numerical error. |
| Deterministic reducer before external publication | `session.py:129–132`; `organ_bank.py:65–67`: copy state, apply event, return candidate. `journal.py:108–121`: publish candidate only after write, flush, fsync. | Freeze issue records and delay learner update until an admissible, bound outcome event. Keep side effects outside the reducer. |
| Replay verifies semantics, not merely hash links | `grfps_l2.py:361–372`, `journal.py:38–69`, `bank_journal.py:12–25`, `reference3d_segments.py:15–34`: reconstruct initial state and reproduce every output/state. | Restart equivalence and auditability. Hashes are integrity evidence within the retained chain, not source authentication or evidence of physical truth. |
| Lifecycle and evidence scope are explicit | `session.py:182–210` binds request to target/frame epoch and rejects obsolete receipt effects; `reference3d_contract.py:80–89` binds source, current cursor/head/native report, registration receipt/certificate and report certificate. | Forecast issue ID, model version, source epoch, units, horizon, issue availability, maturity, and receipt must be bound. A correct value from the wrong run/horizon must not update the model. |
| Transport receipt is not semantic acceptance | `reference3d_runtime.py:39–56` bounded queue then owner commit; identical command identity can replay; `REFERENCE3D_CONTRACT.md:98` documents HTTP 202 correctly. | Distinguish queued, admitted, usable, scored, and learned outcomes. Repeated delivery must not learn twice. |
| Source, transport and reference continuity differ | `flow3d_bank.py:28–39,45–69,89–95`: new transport invalidates current report/temporal chain; same source registration can remain. `revision3d_bank.py:60–66`: reference reset retires calibration. | A network reconnection need not reset a learned predictor. A changed measurement/target contract may invalidate outstanding predictions. Do not conflate either with optimizer restart. |
| Multitemporal claims retain different clocks | `report3d_bank.py:37–44`: observed, callback, predicted-display and owner-received times remain distinct. `report3d_contract.py:40–43,64–108` qualifies only the stated clock relation. | For finance: target event/index, release/availability time, issue time, maturity and ingest time are distinct. Maturity alone cannot authorize access to unreleased labels. |
| Fit and controls remain disjoint | `report3d_contract.py:74–98` disjoint report refs, later controls, fit polygon, whole-enclosure check. `reference3d_contract.py:97–111` derives from binding channel, rounds controls inward, never refits to them. | Training/calibration/selection/transfer roles must be fixed and retained. A control failure cannot silently alter model settings and remain the same control evaluation. |
| Interval entailment and search incompleteness are distinct | `uncertain3d.py:145–173,192–211`: rational interval cover, explicit search limits, at least one fit witness, universal query for Known, two feasible opposite witnesses for Ambiguous, overlap alone Unknown. | Do not promote a numerical interval overlap to a real counterexample, or absence of a found counterexample to correctness. Preserve hypothesis/certification scope. |
| No inference across gaps | `temporal3d_bank.py:46–49,87–97`: barriers clear temporal anchor. `temporal3d_contract.py:78–99`: ordered endpoint intervals and scope match; equal endpoints do not exclude intervening change, opposite endpoints establish only a lower bound. | Missing outcomes, late data and unavailable regimes cannot count as successful predictions or prove continuity. Distinguish a completed horizon from a continuously observed path. |
| Resource reservations and negative results persist | `organ_bank.py:75–84`; `source_bank.py:129–162,190–192`; `reference3d_bank.py:18–41`: acquisition and compute reservations, accepted negative certificate/cost retention, no false refund. | Bounded issued/outcome queues and retained failed attempts. Logical budgets are not latency, throughput or arbitrary-restart CPU bounds. |
| Machine result and view stay distinct | `grfps_l2.py:303–322`; `session.py:244–284`; `operator_port.py:7–13`. Views name evidence and loss; stale delta preconditions fail. | UI should present a projection of committed state, with an issue/evidence reference. Display is not actuation or proof. |
| Provenance does not become physical validation | `reference3d_bank.py:42–47`; `pose3d_contract.py:73–79`; `reference3d_contract.py:90`: physical_validation remains Unknown, instrument/association verification false even for Known. | A risk prediction being well formed, reproducible, or statistically scored cannot be labeled empirically superior solely on those grounds. |

## Defects and extraction hazards

### 1. Confirmed base-profile retry type confusion

`grfps_l2.Kernel.step`, lines 330–332, uses Python dictionary equality for “exact duplicate”. Python considers `True == 1`, while this protocol explicitly distinguishes booleans and integers. Minimal read-only reproduction:

```python
from grfps_l2 import Kernel, canon
from test_kernel import genome
k = Kernel(genome())
e = {"id":"example", "kind":"tick", "at":1, "label":"tick"}
k.step(e)
r = dict(e, at=True)
assert e == r
assert canon(e) != canon(r)
k.step(r)                  # silently accepted as retry
assert len(k.records) == 1
```

Executed result: `retry_dict_equality=True`, `canonical_equality=False`, `retry_was_accepted=True`, one record. The retry bypasses the integer-clock validation that would reject `True` for a new event. It does not by itself show an unauthorized state change; it disproves the stated “exact duplicate” criterion in the base implementation. This is **not** evidence that all later command ports share the bug: current reference commands compare `command_ref`, and current segment replay compares canonical bytes. A cleaned Gabriel kernel must compare canonical bytes/content digests and validate exact field types before idempotence acceptance.

### 2. A single five-valued status is not a sufficient shared ontology

`grfps_l2.py:203–213` calls conflicting Boolean observations `Ambiguous`, even though their conjunction has no consistent Boolean value (`candidates=[]`). `uncertain3d.py:209–211` calls two concrete feasible opposite models `Ambiguous`, and a broad overapproximation `Unknown`. `organ_bank.py:54–57` mainly uses Known/Unknown/occluded. `operator_port.py:10` adds `Reported`, outside the original five-valued set. These are defensible local protocols, but not interchangeable global semantics.

A Gabriel kernel should separate axes:

1. structural validity and domain scope;
2. provenance and evidence references;
3. availability/maturity/lifecycle;
4. conditional model entailment, conflicting evidence, incomplete search, or probabilistic uncertainty;
5. empirical evaluation status.

Keep explicit reason/type fields. In particular, a forecast may be a valid issued prediction while the future outcome remains unavailable; it should not be mislabeled a Known physical fact. `Invalid` must not substitute for a valid negative result or for two inconsistent observations.

### 3. Canonical hashes are scoped integrity, not security/authentication

The registry/domain-separated hashes, retained raw bytes, and full replay are valuable. They do not authenticate source identity or protect against replacing and recomputing the whole chain. This limit is acknowledged in `README.md:64–68` and current project scope. A single writer owns the segment journal, but there is no cross-process lock or authenticated multiwriter consensus in `reference3d_segments.py:36–77`. `_write` checks descriptor/path inode and size and calls fsync; this is not a demonstrated crash-consistent database for arbitrary storage/power-loss conditions. Do not market it as tamper-proof or distributed consensus.

### 4. Deep historical inheritance and expensive snapshots

Most bank layers copy the entire predecessor contract, rewrite its profile, call super, restore their own contract, enrich snapshots, and hash again. Examples: `reference3d_bank.py:12–13,48–51`, `report3d_bank.py:11–15,71–79`, `flow3d_bank.py:15–18,96–110`. `organ_bank.py:65–67` copies the entire object per event; recent histories/certificates are included in subsequent snapshots. This is finite under current small bounds, but it is not a demonstrated scalable streaming implementation.

Many early mechanisms are overridden away (`source_bank.py:44–46` disables proposals/projections/compaction) yet their state/configuration remains inherited. Historical profiles should be preserved as provenance/regression fixtures outside the new runtime. Use composition with a small event dispatcher and explicit state components. Do not import an entire chain merely to reuse journaling.

### 5. Replay is strong self-consistency, not automatically independent mathematics

`reference3d_segments.py:31` reruns the production reducer. `revision3d_bank.py:49–50` recomputes certificates with the same production compiler; `source_bank.py:153–154` likewise repeats the same solver. These detect altered transitions/bindings and inconsistent stored results; they do not independently establish correctness of that solver. The separate reference verifier and test cases are relevant additional checks, but their full independence must be assessed by actually reading/executing them. Imported validation counts are not newly reproduced counts.

### 6. Domain-specific truths must stay in adapters

Quaternion boxes, rigid rotations, sensor error envelopes, reference/control instruments and WebXR lifecycle are useful XR adapters. They do not explain predictive financial regimes or supply a new risk model. Conversely, FZ0, VaR/ES feasibility, maturity lanes, expert-bank contracts and statistical evidence belong in Gabriel's risk adapter. A shared event/kernel does not make them the same uncertainty calculus.

### 7. Limits of current exact geometry

`uncertain3d.py:82–92` bounds supplied quaternion charts and search; `119–131` tries finitely many translations for a concrete fit; `145–173` can leave fit existence/control unresolved. Rational arithmetic protects the stated finite operations from rounding; it does not prove global model completeness or validity of physical error assumptions. The newer reference contract correctly preserves this limitation. Do not transplant “exact” as a blanket label to the existing floating-point Gabriel learner.

## Proposed cleaned integration boundary

This is an extraction recommendation, not a claim that the following has already been implemented:

**Immutable contract** → **typed event admission** → **pure state transition** → **durable journal** → **query/view projection**. Domain modules implement deterministic prediction/assessment/update hooks. Each accepted event binds contract hash, source and epoch, event/availability time, issue or evidence references and exact payload. Runtime I/O produces events but does not directly mutate learner state.

For Gabriel risk, the critical new state component is a forecast ledger:

- Issue freezes forecast, origin, horizon, maturity, units, expert/model references and state before the outcome.
- Outcome receipt names the issue and target, preserves its observed/published/received times, and is admitted only when the issue's horizon is complete and the label is available.
- Score compares the delivered outcome with the frozen issued prediction; it must not recompute the forecast using newer weights.
- Update consumes each admitted outcome once, with the specified lane/order policy; late/out-of-order outcomes need an explicit policy rather than implicit chronological reinterpretation.
- Restart restores exact committed state and unresolved issues; genuine source/model-contract changes invalidate only the objects whose assumptions changed.
- Synthetic, recorded, derived and empirically evaluated are distinct attributes. A held or rejected event produces a reason and does not silently become a training observation.

A meaningful superiority demonstration for this phase would therefore concern **runtime semantic robustness** (e.g., duplicate/delayed/reordered/restarted streams yield the same admissible model trajectory, while an intentionally naive baseline fails those defined conditions). It must not be called improved predictive accuracy. The previous forecasting benchmarks remain unchanged unless a new predictive mechanism is actually tested.

## Read and execution coverage

Read in full: `README.md`; `REFERENCE3D_CONTRACT.md`; `grfps_l2.py`; `journal.py`; `session.py`; `bank_journal.py`; `organ_bank.py`; `reference3d_bank.py`; `reference3d_contract.py`; `reference3d_runtime.py`; `reference3d_segments.py`; `temporal3d_bank.py`; `temporal3d_contract.py`; `pose3d_contract.py`; `report3d_bank.py`; `report3d_contract.py`; `flow3d_bank.py`; `carrier_bank.py`; `source_bank.py`; `revision3d_bank.py`; `uncertain3d.py`; `operator_port.py`; `test_reference3d.py`; `validate_reference3d_release.py`.

Partial/scoped reads: `noisy_bridge.py:1–100`; `test_session.py:1–100`; class/import/declaration locations in earlier bridge and bank modules. The full current `PROJECT_STATE.json` and `POSE3D_CONTRACT.md` were requested but a combined tool output was truncated; only visible portions and the independently read implementing code support conclusions. They are **not** counted as fully read. Historical README revisions, all demo HTML, full project monograph/PDF, all archived process traces and all test files were **not** read by this audit.

Actually executed here: one minimal base-profile canonical-idempotence counterexample and runtime MRO inspection. No full upstream suite, integration replay, visual UI test, benchmark or physical experiment was executed by this audit. `README.md:43` reports 1026 Python tests and 937 JavaScript checks; these remain source-reported counts until a separate new execution verifies them. It explicitly states synthetic instrument data, no physical device-session validation, and a limited historical replay scope (`README.md:54–68`).
