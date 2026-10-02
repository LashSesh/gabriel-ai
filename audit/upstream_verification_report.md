# Independent execution and extraction audit of ophan_bridge-main

The repository is an executable synthetic-perception reference system, not merely a collection of architecture documents. This audit reads and executes the supplied 0.30 release contracts in an isolated copy. Existing stored validation outputs are not counted as a new run.

## Scope and method

- Reviewed the current release gate, canonical JSON and identity primitives, reference-recording derivation, current bank reducer and segment replay, and targeted failure/identity/schema tests before execution.
- The release command is `python validate_reference3d_release.py`. It discovers all `test_*.py`, runs all 31 JavaScript DOM-harness suites, replays reference, carrier and pose journals, and runs a new two-owner-process local reference CLI restart scenario.
- All subprocesses and HTTP interaction are local test facilities; the supplied source tree is kept unchanged by executing in `verification_repo`.
- JavaScript tests exercise a mocked DOM. They are not a visual browser review or a physical XR device test.

## Independently reproduced boundary cases

1. **Current evidence invalidation works for the probed transition.** A qualified `reference_assessment` becomes `Unknown` on the next native report. Its old certificate remains available as history. `physical_validation` remains `Unknown`; the system does not convert a synthetic enclosure into physical verification.
2. **Semantic replay needs an expected endpoint to establish completeness.** Removing the last *complete* event from a valid current-profile journal changes sequence 2 to sequence 1 and is accepted as a valid prefix. A trusted expected terminal count/head would reject this shortening. The chain by itself proves internal replay consistency, not completeness or authenticity. Removing bytes halfway through a record is rejected with `segment_line`.
3. **Historical profiles do not share all current lifecycle semantics.** In the old Boolean `grfps_l2.Kernel`, `Known` survives tracking loss and recovery until ordinary expiry. This is a historical model-navigation profile, not a basis for claiming current reference certificates survive a source/epoch reset. A cleaned extraction must choose one explicit lifecycle semantics.
4. **A legacy idempotence check conflates Boolean and integer values.** After accepting an event with `at=1`, resending the same event ID with `at=True` is accepted as an exact duplicate because Python mapping equality equates them. Canonical encodings differ. No new event is committed, so the demonstrated effect is a type-validation bypass in duplicate recognition, not state corruption. Canonical byte identity plus schema validation is the appropriate extraction requirement.

The probe source is `probe_upstream.py`; its fresh results are `upstream_independent_probes.json`. The first two issues describe necessary claim boundaries; the fourth is a concrete localized implementation defect in the historical kernel. None establishes a failure of predictive models or a market-performance claim.

## Architectural implications for Gabriel

Extract current source/epoch/context binding, typed canonical identity, explicit validity intervals, atomic reducers, retained negative evidence, resource accounting and replay. Keep domain and certainty semantics explicit: a conditional enclosure or correctly transported value does not establish predictive calibration, decision utility, source honesty or physical instrument accuracy. Add trusted terminal-manifest checking where a complete archive is required. Do not import the complete inheritance/history stack merely because its tests pass.

## Fresh release execution

The unmodified current release gate **passed**, exit code 0, in 411.639 seconds on Python 3.12.14 / Linux.

- **1,026 Python tests**: 0 failures, 0 errors, 0 skips.
- **937 JavaScript checks** across 31 mocked-DOM suites: passed.
- Current reference, historical carrier and pose evidence journals replayed and matched their recorded expectations. These are fresh semantic replays of saved inputs, not new runs of their historical producers or HTTP sessions.
- Fresh CLI scenario: 2 owner processes, 3 producer processes, 24 native synthetic frames and 199 transitions. Preserved certificates/budgets, invalidated active claims on resume, requalified only with fresh bindings, and rejected a Boolean-valued policy mutation without any journal write.
- No visual browser inspection or physical device/instrument run was executed.

`upstream_release_execution.json`, `upstream_release_validation.json` and `upstream_release_detail.log` retain this fresh run. The tests are repository-provided expectations; the five additional boundary probes above are a separate independent audit. `upstream_source_integrity.json` confirms the original 276 Python files remained byte-identical.
