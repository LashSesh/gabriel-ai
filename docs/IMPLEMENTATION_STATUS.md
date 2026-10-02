# Gabriel AI implementation status (WP01–WP08)

Branch `claude/vigilant-gauss-03dalc`, built from the recovered baseline
`ed3da014e41999b4201b1654c8b2667ed907636b` with the Kosmocrates donor pinned at
`a320ad101bbf0fdcde85d4617366ddee435d40b8` (local checkout matched). Every claim below is
backed by a file under `evidence/` or by a test named in `evidence/test_results.txt`
(117 passed including the privileged containment self-test, 1 opt-in live test skipped in the
suite log and executed separately four times; Python 3.12.3, SQLite 3.45.1, Linux 6.18 x86_64, uid 0).

## Work packages

| WP | Delivered code | Executed evidence | Not executed / limitations |
|----|----------------|-------------------|----------------------------|
| WP01 Baseline packaging | `pyproject.toml` with core/provider/numerical/native/dev groups, `gabriel` entry point, `tests/`, `.github/workflows/ci.yml` | `evidence/wp01/baseline_manifest.json`: both commits pinned; inherited `reproduction/check_runtime.py` rerun in an isolated worktree at the baseline commit, exit 0, 3449 assertions in 98 categories, source hashes and counts identical to the blueprint evidence (`evidence/wp01/legacy_check_runtime.log`) | LFS payload not fetched; no native build; root license still unresolved (`missing_evidence_register`) |
| WP02 Contracts | `src/gabriel_agent/contracts/`: exact codec, strict local schema registry (17 blueprint schemas + 25 new closed schemas: goal-spec, compilation-report, context-manifest, proposal-envelope, check-evidence, read-back, hold, receipt, checkpoint, anchor, tool-descriptor, catalog, task-binding, provider-profile, workspace-config, run-witness, export-manifest, plan-proposal, command payloads; software domain schemas), cross-record rules | `tests/test_contracts.py` (AT02 representation controls, plan DAG/65-node/depth-13 bounds, amendment weakening, approval digest); `evidence/wp02/spec_validation.json`: vendored blueprint validator PASSED with the ADR-10 enum extension | Schemas define representation only |
| WP03 Owner and artifacts | `artifacts/store.py` (atomic install, fsck, orphan grace), `state/owner.py`, `state/reducer.py` (pure), recorded replay, anchors, checkpoints, SQLite backup | `tests/test_artifacts.py` (AT03 crash before/after rename, corruption fault), `tests/test_owner.py` (AT04 exact retry/ID reuse/stale/race with two writers, AT05 crash hooks in-process and `os._exit` child, replay with zero port calls, tampered event rejected, anchor detects truncated suffix, AT18 checkpoint binding rejects a changed projection) | Durability still depends on SQLite/VFS/storage; no power-loss test |
| WP04 Policy and budget | `policy/grants.py`, `policy/budget.py`, `policy/principals.py`, approvals in the owner | `tests/test_policy.py`, `tests/test_owner.py` (AT06 revocation before marker, approval digest mutation, in-flight effect becomes reconciliation obligation; AT07 reservation race, unknown usage conservative, retry cannot reset budget, overrun retained and admission suspended) | Single-host principal secrets; no network identity |
| WP05 Tool sandbox | `tools/fs.py` (dir-fd walk, `O_NOFOLLOW`, atomic writes), `tools/registry.py` (fingerprinted implementations, grant-filtered catalog), `workers/isolation.py` + `workers/jail_init.py` (linux_namespace: user/mount/pid/net/ipc/uts namespaces, tmpfs root, read-only binds, `pivot_root`, `setpriv` capability drop + `no_new_privs`, rlimits, SIGKILL of the PID namespace, full-stream output digests), `TrustedLocalBackend`, `workers/worktree.py`, `workers/supervisor.py` | `tests/test_workers.py`: symlink/absolute/parent escapes rejected, trusted_local capture/timeout/env scrub/descendant report, supervisor crash windows with idempotent and non-idempotent fake targets (AT12), lease expiry and late result (AT13); **`test_namespace_jail_isolation_selftest` PASSED** (cwd `/work`, host `/home` and `/root` invisible, effective capabilities 0, network blocked, `/usr` read-only, file written into the worktree, daemonized descendant killed with the PID namespace, timeout kills the namespace); `evidence/doctor_linux_namespace_selftest.json` (`untrusted_execution_supported: true`) | The self-test was executed on this host only (Linux 6.18, uid 0, util-linux unshare/setpriv); other hosts must run `gabriel doctor --selftest` themselves. `trusted_local` remains an explicitly separate non-contained mode. |
| WP06 Model gateway | `models/port.py`, `models/scripted.py`, `models/http_providers.py` (OpenAI-compatible, Anthropic; `env:` credentials only), `models/gateway.py` (retained prompt/response/usage, strict normalization, `model.generate` tool with conservative unknown usage) | `tests/test_models.py` (AT09 statuses: completed/truncated/invalid output/refusal/rate limit/timeout/transport failure; HTTP status mapping against local fake endpoints; credential reference restrictions); **four real OpenAI runs** recorded in `evidence/live/summary.json` with exact model revisions (`gpt-4.1-mini-2025-04-14`, `gpt-5-mini-2025-08-07`), known usage for every request and one retained `invalid_output` (an operation carried an unexpected field; rejected, never parsed, retried) | Anthropic provider implemented and tested against a local fake endpoint only (no credential available here) |
| WP07 Scheduler and kernel | `kernel/kernel.py` (port of the blueprint reference under `gabriel.kernel/1`, plus `complete()` and progress vector), `planning/scheduler.py`, plan validation in `contracts/rules.py`, outbox/lease/fencing/reconciliation in the reducer | `tests/test_kernel.py` (23 reference cases + 3; AT20/AT21 representation parts), `tests/test_scheduler.py` (AT10 tie-break, read-worker bound, single writer), `tests/test_owner.py` (plan bounds at the owner, bounded repair cycles) | Ranking heuristics are not used by the runner beyond the deterministic reference plan |
| WP08 Coding vertical slice | `domains/software/pack.py` (six ports), `agent/workspace.py`, `agent/runner.py`, `agent/export.py`, `interfaces/cli.py`, `evaluation/fixtures/parser_bug.py` | `tests/test_slice.py`: end-to-end repair with an independent oracle (scripted provider), interrupt after I/O and resume from the journal, false completion ("done" with failing oracle) and acceptance weakening (plan omitting the oracle, patch editing the oracle file) rejected, task without oracle refused unless acknowledged (AT19), termination between two file writes recorded/reconciled/re-observed (AT24), CLI smoke including pause/resume/export/audit/replay; **real-provider runs inside `linux_namespace`** (`evidence/live/`): every test check executed in the containment backend (`containment: true` in the retained evidence), independent oracle passed, recorded replay passed with zero port calls, export delivered | One synthetic task family; no matched comparison (AT17/WP11) |

## Acceptance case coverage (as executed in this session)

| Case | Status | Where |
|------|--------|-------|
| AT01 recovered baseline replay | executed | `evidence/wp01/` |
| AT02 closed schema and exact primitives | executed | `tests/test_contracts.py` |
| AT03 artifact integrity and installation crash | executed | `tests/test_artifacts.py` |
| AT04 retry and concurrent revision | executed | `tests/test_owner.py` |
| AT05 crash and recorded replay | executed (in-process hooks and a killed child process) | `tests/test_owner.py` |
| AT06 grant revocation and approval mutation | executed | `tests/test_owner.py`, `tests/test_policy.py` |
| AT07 concurrent budget and unknown usage | executed (sequential race at the ceiling; two-writer race in AT04) | `tests/test_owner.py` |
| AT08 hostile content and containment | executed: path/symlink escapes, env scrub, hostile README treated as data, namespace jail self-test (no host filesystem, no network, no capabilities, descendants cleaned) | `tests/test_workers.py`, `tests/test_slice.py`, `evidence/doctor_linux_namespace_selftest.json` |
| AT09 model response boundaries | executed with the scripted provider and fake HTTP endpoints | `tests/test_models.py` |
| AT10 plan and scheduler bounds | executed | `tests/test_contracts.py`, `tests/test_scheduler.py`, `tests/test_owner.py` |
| AT11 complete coding slice | executed: scripted provider (positive, resume, false-completion controls) and four real-provider runs, two of them inside the namespace backend with exact model revisions retained | `tests/test_slice.py`, `evidence/live/summary.json` |
| AT12 external effect ambiguity | executed with fake targets (crash before marker, after marker before I/O, after I/O before commit, after commit) | `tests/test_workers.py` |
| AT13 cancellation and late result | executed | `tests/test_owner.py`, `tests/test_workers.py` |
| AT18 release restore and export | partially executed: backup/restore anchor check and checkpoint corruption control; full release export bundle only for the slice | `tests/test_owner.py`, `tests/test_slice.py` |
| AT19 loss-preserving goal compilation | executed for the structured compiler (unknown kinds reject, missing oracle unresolved, weakening needs principal confirmation) | `tests/test_slice.py`, `tests/test_owner.py` |
| AT20 categorical completion | executed at kernel and owner level (no eligible candidate → no dispatch is the owner's admission rule) | `tests/test_kernel.py`, `tests/test_owner.py` |
| AT21 complete action/context identity | executed at kernel level and for candidate/patch identity (create/modify/delete distinct) | `tests/test_kernel.py` |
| AT22 proposed versus observed state | executed: only read-back advances the observed snapshot; stale evidence rejected | `tests/test_owner.py`, `tests/test_slice.py` |
| AT24 required coverage and contained partial effects | executed (required unsupported kinds reject at compilation, out-of-root/symlink writes reject, crash between two writes reconciled, containment self-test passed, truncation metadata retained) | `tests/test_slice.py`, `tests/test_workers.py` |
| AT14–AT17, AT23, AT25 | not in WP01–WP08 scope; not executed | — |

## Release assessment
G0 (reproducible local analytical tools): holds on this environment (WP01 rerun).
G1 (complete coding-agent workflow) is **established on this host** in the blueprint's sense: a
real provider, an isolated worktree, bounded tools inside the tested Linux-namespace backend,
independent tests, durable resume and artifact export worked together on the seeded task
(`evidence/live/summary.json`, `evidence/doctor_linux_namespace_selftest.json`,
`evidence/test_results.txt`). The claim is scoped: one host, one provider, one synthetic task
family. The G1 release route of the blueprint still needs WP11 (frozen matched comparison,
AT17) and WP12 (restore bundle, doctor, declared dependency/license manifest, AT18) before a
distributable release can be asserted.

## Known limitations and open items
- `trusted_local` mode has no containment: a daemonized descendant survives (the witness
  reports `descendants_cleaned: false`), the host environment is scrubbed but the filesystem
  and network are open. It exists only for trusted repositories and is opt-in.
- Scripted provider cursors live in process memory; after a restart the script replays from
  its first response per step key (deterministic, documented).
- The planner prompt embeds a reference plan; a real model may return it verbatim. Plan
  validation (unknown capability, unknown check, omitted mandatory check, cycle, limits) is
  enforced by the owner independently of the model.
- The capability catalog is fingerprinted from the loaded implementation source. Changing a tool
  module invalidates existing workspaces at open (`UNSUPPORTED: capability catalog differs`);
  an explicit migration command does not exist yet, so a new workspace is required.
- Invalid or truncated provider output is retained as a failed attempt and retried within the
  node's attempt limit with the diagnostic in the next prompt; the earlier gpt-5-mini run used
  a plan version instead (both bounded, both recorded).
- The ADR-10 hold operation and ADR-11 planner bootstrap intent extend the proposed contract;
  the vendored specification files are unchanged apart from the two additive enum values.
- The root license remains unresolved (`pyproject.toml` declares `LicenseRef-Unresolved`).
- WP09–WP12 (memory, numerical/native adapters, evaluation, release) are not started.
