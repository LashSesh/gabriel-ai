> Final disposition (26 September 2026): this file preserves the earlier design review. The delivered implementation uses `synchronous=EXTRA` (not the proposed FULL), checks finite derived scores, and rejects late new issue commands in its declared-receipt profile by requiring issue time equal to owner time and earlier than target completion. Retrospective imports remain explicitly historical. These findings were resolved and exercised in `reproduction/check_runtime.py`; the statements below describing missing implementation or proposed checks refer to the earlier review stage.

# Formal review of the proposed Gabriel owner runtime

Reviewed: `tmp/gabriel_os/runtime_spec.md`, read-only; relevant unchanged legacy implementations `finite_observation.py`, `maturity_ledger.py`, `sequential_contract.py`, and scoring/controller functions in `replay_adaptive_maturity.py`. At the start of this review the new `gabriel_runtime` package had not yet appeared. Implementation conformance therefore needs the separate code/tests review once available.

## Recommended mathematical scope

The paper can state short propositions about deterministic transition composition and transactional ownership. These are useful conditional guarantees of the implemented interface, not new general distributed-systems or learning theorems. An empirical robustness experiment can then show that the implementation satisfies the conditions in selected adversarial cases. It should not assert absolute failure freedom, independently authenticated event times, or increased predictive accuracy.

Let contract `c` bind an immutable adapter identity `a_c`, configuration `g_c`, and initial local state `s_c,0 = Init(a_c,g_c)`. Its deterministic local transition is

`T_c(s, op, payload, at) = (s', result)`.

The adapter sees only the supplied local state, operation, payload and explicit owner timestamp. It does not observe global sequence/head, another contract's state, wall-clock time, mutable module globals, randomness or external I/O. Canonicalization must preserve the specified exact types and values. Configuration normalization must be fixed and deterministic. Registry bindings must remain fixed for the considered execution.

The owner adds admission rules, global order, command identity, expected head, shared resource accounting and durable storage. These mechanisms are outside `T_c` and can reject a proposed schedule. This distinction is essential in every equivalence statement below.

## Proposition 1: local projection under accepted interleavings

**Statement.** Consider two successfully initialized owner executions with the same bound contracts/configurations/adapter transition functions. Suppose both complete command sequences are accepted by their respective owners, and for each contract `c` their projection onto *new logical commits* gives the same ordered local sequence `(op_i,payload_i,at_i)`, including the same binding operation. Then after every equal-length local prefix, the canonical local state and adapter result sequence for `c` are identical. Their adapter views are identical if the view function is also a deterministic function solely of the local state.

**Proof.** The equal bind gives equal initial local states. At the next local transition both executions pass the same prior local state and the same `(op,payload,at)` to the same deterministic function. They therefore yield equal next state and result. Other-contract transitions do not mutate this local state or transition function. Induction over each contract's projected sequence gives the result. The deterministic view corollary follows by function application.

**Essential restrictions.**

- This is not arbitrary global commutativity. Global monotone `at`, stale-head rejection and shared budgets may make one merge inadmissible. The proposition is conditional on both streams being accepted.
- In particular, times 1 then 2 cannot simply be swapped into globally decreasing owner time. Equivalent merges may differ only where all admission constraints still hold.
- Global command records need not be byte-identical across merges: their `expected_head` fields must normally differ. Global sequence numbers, journal heads, receipt envelopes and budget bytes may therefore differ. Do **not** include them in the equivalence conclusion.
- Adapter output must not contain global metadata unless that metadata is deliberately excluded from the observation being compared. The result is equality of local domain semantics, not equality of the entire owner database.
- Preserve exact local timestamps, not merely payload order: finite sessions use owner cutoff to expose current evidence. Changing these timestamps changes the domain execution.
- Identical accepted-command retries are not new logical commits. New command IDs whose adapter operation is a domain-level no-op *are* new owner commits; retain them in the local sequence.
- This property establishes noninterference between admitted local transitions. It supplies neither scheduling fairness nor a guarantee that one contract cannot exhaust shared capacity before another contract binds.

## Proposition 2: command idempotence and ambiguous acknowledgement

**Statement.** Assume successful creation of a store whose database enforces unique command identity; each new command is processed inside one serialized transaction that reads the authoritative current frontier/state; canonical command identity is compared by bytes; the transaction atomically persists command, adapter state/result, receipt, journal frontier and charges; and clients receive the receipt only after successful commit. For any already committed command ID, submitting the identical canonical command returns the originally stored receipt without another state transition or charge. A different canonical command under the same ID is rejected without logical change. A retry remains valid even if its original expected head and timestamp are now historical.

**Proof.** A transaction first resolves an existing ID and compares its full canonical representation. For equality it reads the uniquely stored receipt and executes no transition or accounting mutation; otherwise it rejects. Concurrent transactions cannot both create the same logical command because the unique identity and serialization constraints exclude two accepted inserts. For a new ID all logical writes commit atomically. Thus at most one new logical transition is committed for that canonical command identity, independent of how many exact retries occur.

**Crash/recovery corollary (conditional).** Under the advertised SQLite transaction/recovery semantics and effective VFS/fsync/storage assumptions, a process termination before commit leaves the pretransaction state after recovery; a successful commit followed by termination before acknowledgement leaves the committed state and receipt. The caller may be unable to know which happened, but exact retry either commits once or retrieves the prior receipt.

**What is not established.**

- Not “exactly once execution”: reducers can execute before a rolled-back transaction, during retry, and during audit. Their external effects are prohibited for this reason.
- Not “exactly once ingestion” for equivalent payloads under fresh IDs. Those are new commands and may incur new charges. Domain adapters have separate idempotence rules.
- Not a theorem about physical power loss or every storage device. `synchronous=FULL` requests a documented durability policy; actual guarantees depend on SQLite, the VFS, filesystem and device honoring the operations.
- Not recovery from arbitrary file truncation, malicious database edits, unsupported SQLite modes, unsafe simultaneous file replacement, or a partially completed creation protocol.
- A returned SQLite `COMMIT` error or connection failure can have an ambiguous outcome. The caller should reopen and retry the same command; it must not assume no commit and invent a fresh identity.
- Opening multiple Store handles is safe only if every new submit reads authoritative data *inside* `BEGIN IMMEDIATE`; no stale in-memory state may drive dispatch.

## Proposition 3: semantic replay and its completeness boundary

**Statement.** Given an export/header and a finite record sequence, fix trusted deterministic adapter implementations and initial configuration. Suppose replay reconstructs initialization, validates every command against the preceding frontier and temporal/capacity rules, recomputes each transition and result, and compares canonical prestate/poststate/results/receipts and final stored state/accounting. Successful replay establishes that the supplied records and final materialized state constitute a valid execution of those implementations on that command prefix.

**Proof.** Initialization is checked. At every step the next expected record is uniquely determined by the previously verified state/frontier and supplied command. Exact comparison validates that step. Induction validates the supplied prefix and final comparison validates the stored materialization of that prefix.

**Completeness limitation.** Replay alone cannot distinguish a legitimate shorter run from deletion of a valid suffix followed by replacement of the corresponding materialized state/frontier. Nor can it detect a completely rewritten but semantically valid history solely from hashes that were recomputed by the same file controller. Rejected attempts and queued/unreceived events are outside an accepted-command log unless separately recorded. Successful replay does not show that every physical observation or attempted command was logged.

**External anchor.** A separately retained trusted `(header identity, committed sequence count, head)` identifies the expected committed frontier. Comparing replay with this anchor detects missing suffixes or alteration relative to that known frontier, conditional on hash collision resistance and the anchor remaining trusted. It does not by itself authenticate sensors or establish that unreceived events existed. Do not claim suffix completeness if no such anchor is supplied or checked.

## Legacy adapter semantics that constrain claims

### Maturity is conditional on declared clock and receipt data

`maturity_ledger.py:214–255` selects by event cutoff, receipt cutoff and accepted-operation prefix. `IssuedForecast` requires issue before target completion and at least one required endpoint at `target_end` (`35–67`). `EventRevision` requires completed event before declared receipt (`sequential_contract.py:65–71`). Consequently a score from a selected endpoint cannot first mature before target completion **under those declarations**. This is receipt-causal replay, not authenticated knowledge of real-world publication.

Owner `at`, domain `received_at`, forecast `issued_at`, event times and query cutoffs need documented relationships. Do not silently overwrite supplied `received_at` with owner `at`: that changes legacy semantics. Conversely, require any declared receipt used by the adapter to be no later than owner operation time. Query cutoffs must not silently extend past the available ledger prefix. Equal timestamps require the operation prefix to identify the intended historical state.

Corrections replace a score at its original first-maturity position and replay subsequent controller state (`maturity_ledger.py:115–127`). Therefore “each target updates exactly once” is misleading unless carefully defined. The current replay contains one active score per target. It may recompute the entire reduction when a correction arrives. Previously issued predictions stay immutable; the current controller state may change.

### Current scorer requires a numeric boundary guard

The specification requires finite positive endpoint inputs, but this does not guarantee a finite computed score. `replay_adaptive_maturity.py:23–31` computes `100*np.log(rate1/rate0)`, whose intermediate ratio can overflow/underflow.

An executed read-only probe using positive finite rates `1e-300` and `1e300` returned:

```json
{"hit": true, "realized_log_loss_hex": "inf"}
```

and NumPy emitted `overflow encountered in scalar divide`. The inverse extreme gives a zero ratio and negative infinity. Preserve the unchanged legacy scoring function for equivalence, but reject its nonfinite derived output atomically in the adapter, with a documented unsupported numeric domain. Do not silently replace the formula with a more stable formula while claiming exact unchanged numerical behavior. Even if a hex string is syntactically canonical JSON, `"inf"` is not an acceptable finite score representation.

Require unique canonical float encodings, e.g. `x == float.fromhex(x).hex()` after finite checks, if mathematical value aliases must not create distinct forecast identities. Decide/document negative zero; Python's canonical float hex distinguishes it. This is identity policy, not a numerical proof.

### Finite session is an exact finite model, not a probability certification

`finite_observation.py:220–250` validates passive evidence, source identity, event/receipt availability and advances its cutoff. A repeated source/value observation can return false while advancing cutoff. The wrapper must preserve that behavior when submitted under a new outer command ID. `result()` explicitly calls an empty compatible set `conflict` (`252–256`); do not convert it into vacuous target agreement.

The minimax solver may return infinity for a conflict or an indistinguishable target (`108–117`). The exact JSON envelope excludes floats; represent this by an explicit status/null field, not by silently converting a proof-relevant quantity to a finite number. Bounds on command bytes do not adequately bound minimax computation: the adapter needs a modest bound on catalogue size/query count or an explicitly documented finite but potentially exponential workload.

## Fingerprints: necessary but conditional

The registry fingerprint should bind adapter implementation, used legacy modules, scoring function and relevant numeric dependency versions. Merely hashing `adapters.py` does not identify the imported `maturity_ledger`, `finite_observation`, scorer, canonicalization or transitive imports. A versioned distribution/source manifest is the simplest complete declaration. Audit/open should compare this fixed declaration.

However, source hashes are still a local identity assumption. They do not prove that loaded bytecode corresponds to the files currently hashed, that a module was not monkey-patched after initialization, or that two platforms' numeric libraries round all transcendental functions identically. State the scope as trusted local deterministic implementations within the recorded environment; existing exact integer portions have a stronger reproducibility scope than binary64 log scoring. Do not call self-reported fingerprints code authentication or a sandbox for arbitrary plugins.

`Store` should freeze a canonical fingerprint snapshot at initialization/open. If it stores mutable registry objects, deterministic/stateless adapter behavior remains a trusted precondition unless later calls revalidate identities and prohibit mutable external state. Passing cloned state/payload arguments prevents ordinary input mutation but does not make an arbitrary adapter pure.

## Cost, rejection and audit accounting

- Define `events` as unique **outer logical commits**, including successful domain no-ops and query operations if they are submitted commands. An identical command-ID retry is excluded.
- Define `bytes` precisely as the sum of committed canonical command byte lengths. This excludes SQLite overhead, receipts, state size, replay workload and rejected attempts. It is not a bound on storage size or total CPU work.
- A reducer may run and fail before logical rollback. No committed charge does not mean no consumed computational resource. Denial-of-service resistance, per-attempt metering and rejection logging are not proved by commit-only budgets.
- Global capacity produces cross-contract admission coupling. Projection equivalence of accepted local transitions does not imply fair access to capacity.
- Rejection can remain absent from the accepted-command journal, but the paper must say so. Do not claim a complete attempt audit while storing only committed commands.
- Audit should not execute committed query commands against the *final* state; it must reproduce their original local prefix state and explicit cutoffs.
- Commands passed as Python dicts and exported JSON text must use the same strict validator. Python equality must never substitute for canonical identity at command, config, receipt or stored-state comparisons where `True`/`1` matter.

## Concrete tests that are most informative

1. Two admissible interleavings with identical local operations/timestamps, compare adapter states/results; also show the global heads differ and do not compare them as an equivalence requirement.
2. Shared-capacity and globally backdated interleavings rejected, demonstrating the proposition's scope rather than declaring an isolation defect.
3. Same canonical ID retry after several later commits returns original receipt and charge; same ID with a nested boolean/integer substitution rejects.
4. Two independent Store handles attempt commits against one head: one commits, the stale one rejects; subsequent retry against current state is correct.
5. Process termination before COMMIT and after COMMIT/before acknowledgement, reopened with identical retry; this is a process-crash test, not a power-loss test.
6. Rehash an altered result, leave its command unchanged: semantic replay fails. Supply a coherent shorter prefix: audit succeeds without anchor, external expected anchor comparison fails. This distinguishes internal consistency from completeness.
7. Nonfinite derived risk score causes complete rollback even though all endpoints are finite.
8. Correction changes current controller replay but not stored issued forecasts; operation-prefix queries recover the pre-correction state.
9. Registry/source fingerprint mismatch rejected on open, while documentation explicitly limits the authentication claim.

## Review status

This review provides proof statements and implementation requirements. It did not execute the new runtime because the package was not present during the initial review. The only newly executed probe in this document is the finite-input/nonfinite-score counterexample. The architectural base-profile bool/int retry counterexample is recorded separately in `architecture_audit.md`. No legacy numerical algorithm or repository source was edited.

## Subsequent first implementation inspection

After drafting the review, the new package appeared and all current lines of `canonical.py`, `engine.py` and `adapters.py` were read. The first implementation supports the proposed narrow propositions: exact canonical comparison, authoritative reads inside BEGIN IMMEDIATE, transactional state/result/receipt/accounting, semantic replay against original prefix states, external expected head/count checks, cloned input/state arguments, bounded adapter histories, finite-catalogue caps, canonical finite binary64 inputs, and a nonfinite *computed* score guard are implemented. These are code-inspection findings, not a claim that this reviewer ran the full runtime test suite.

The implementation chooses `PRAGMA synchronous=EXTRA` (engine lines 102–105 and audit lines 324–327), stronger than the plan's `FULL`. The final manuscript/contract should reflect the actual mode while retaining the storage/VFS limitation. The adapter now explicitly rejects the nonfinite-score counterexample (`adapters.py:227–235`). It also encodes infinite finite-model cost by `cost_status='infinite'` and `worst_case_cost=None` (`151–160`), and limits catalogues to 32 rows/12 queries (`120–121`).

### Confirmed remaining semantic boundary: retrospective forecast ingestion

`MaturityRiskAdapter.apply` checks only that declared `issued_at <= owner receipt_at` (`338–342`) in addition to the legacy `issued_at < target_end` condition. It **does not require the owner to durably ingest a new forecast before its target ends**. This can be a legitimate historical replay/import policy, but it is not a live issuance barrier.

A read-only direct-adapter probe was executed using `availability_mode='declared_observed_receipts'`: forecast origin/issued_at 0, target_end 10, owner operation time 100. It returned `accepted=True` with the forecast pending. Thus a user can supply a declared earlier issue long after completion; the wrapper does not authenticate that declaration or show the supplied prediction was computed without future information. The paper should call this hosting of supplied immutable issue records under declared metadata. If a live-issuance claim is desired, it needs an explicit policy/mode requiring owner commit time before target completion, with its own tests; importing prior issues must remain visibly different.

The adapter accepts external forecast predictions and an initial controller checkpoint. It does not generate each next forecast from that controller or verify the checkpoint's entire earlier training history. Direct-module equivalence and correct score replay remain meaningful; claims of an end-to-end live learner need a separate connection.

### Runtime and dependency identity scope

Current adapter fingerprints bind adapter source and the selected transitive legacy modules (`adapters.py:93–99,203–207`), plus NumPy version for risk. The core `engine.py` and `canonical.py` are identified by declared runtime format, not file hashes in that fingerprint. If the manuscript claims the journal binds **all** implementation sources, add a runtime source identity or narrow the claim. Python/platform/libm/NumPy build differences and already-loaded code versus files remain trusted-environment assumptions. The hash declaration is not remote attestation.

The code-inspection addendum and one retrospective-issue probe do not replace the independent runtime verification assigned separately. Source line numbers can shift during ongoing implementation; function names are the stable pointers.
