# Gabriel AI implementation status (WP01–WP08, WP11, WP12)

Branch `claude/vigilant-gauss-03dalc`, built from the recovered baseline
`ed3da014e41999b4201b1654c8b2667ed907636b` with the Kosmocrates donor pinned at
`a320ad101bbf0fdcde85d4617366ddee435d40b8` (local checkout matched). Every claim below is
backed by a file under `evidence/` or by a test named in `evidence/test_results.txt`
(126 passed including the privileged containment self-test, 1 opt-in live test skipped in the
suite log and executed separately; Python 3.12.3, SQLite 3.45.1, Linux 6.18 x86_64, uid 0).
`scripts/evidence_manifest.py` regenerates `evidence/test_run.json` and
`evidence/work_packages.json` from that log.

## Work packages

| WP | Delivered code | Executed evidence | Not executed / limitations |
|----|----------------|-------------------|----------------------------|
| WP01 Baseline packaging | `pyproject.toml` with core/provider/numerical/native/dev groups, `gabriel` entry point, `tests/`, `.github/workflows/ci.yml` | `evidence/wp01/baseline_manifest.json`: both commits pinned; inherited `reproduction/check_runtime.py` rerun in an isolated worktree at the baseline commit, exit 0, 3449 assertions in 98 categories, source hashes and counts identical to the blueprint evidence (`evidence/wp01/legacy_check_runtime.log`) | LFS payload not fetched; no native build (`missing_evidence_register`); root license Apache-2.0 since the WP12 release review |
| WP02 Contracts | `src/gabriel_agent/contracts/`: exact codec, strict local schema registry (17 blueprint schemas + 25 new closed schemas: goal-spec, compilation-report, context-manifest, proposal-envelope, check-evidence, read-back, hold, receipt, checkpoint, anchor, tool-descriptor, catalog, task-binding, provider-profile, workspace-config, run-witness, export-manifest, plan-proposal, command payloads; software domain schemas), cross-record rules | `tests/test_contracts.py` (AT02 representation controls, plan DAG/65-node/depth-13 bounds, amendment weakening, approval digest); `evidence/wp02/spec_validation.json`: vendored blueprint validator PASSED with the ADR-10 enum extension | Schemas define representation only |
| WP03 Owner and artifacts | `artifacts/store.py` (atomic install, fsck, orphan grace), `state/owner.py`, `state/reducer.py` (pure), recorded replay, anchors, checkpoints, SQLite backup | `tests/test_artifacts.py` (AT03 crash before/after rename, corruption fault), `tests/test_owner.py` (AT04 exact retry/ID reuse/stale/race with two writers, AT05 crash hooks in-process and `os._exit` child, replay with zero port calls, tampered event rejected, anchor detects truncated suffix, AT18 checkpoint binding rejects a changed projection) | Durability still depends on SQLite/VFS/storage; no power-loss test |
| WP04 Policy and budget | `policy/grants.py`, `policy/budget.py`, `policy/principals.py`, approvals in the owner | `tests/test_policy.py`, `tests/test_owner.py` (AT06 revocation before marker, approval digest mutation, in-flight effect becomes reconciliation obligation; AT07 reservation race, unknown usage conservative, retry cannot reset budget, overrun retained and admission suspended) | Single-host principal secrets; no network identity |
| WP05 Tool sandbox | `tools/fs.py` (dir-fd walk, `O_NOFOLLOW`, atomic writes), `tools/registry.py` (fingerprinted implementations, grant-filtered catalog), `workers/isolation.py` + `workers/jail_init.py` (linux_namespace: user/mount/pid/net/ipc/uts namespaces, tmpfs root, read-only binds, `pivot_root`, `setpriv` capability drop + `no_new_privs`, rlimits, SIGKILL of the PID namespace, full-stream output digests), `TrustedLocalBackend`, `workers/worktree.py`, `workers/supervisor.py` | `tests/test_workers.py`: symlink/absolute/parent escapes rejected, trusted_local capture/timeout/env scrub/descendant report, supervisor crash windows with idempotent and non-idempotent fake targets (AT12), lease expiry and late result (AT13); **`test_namespace_jail_isolation_selftest` PASSED** (cwd `/work`, host `/home` and `/root` invisible, effective capabilities 0, network blocked, `/usr` read-only, file written into the worktree, daemonized descendant killed with the PID namespace, timeout kills the namespace); `evidence/doctor_linux_namespace_selftest.json` (`untrusted_execution_supported: true`); every check of the 342 evaluation runs executed inside the backend | The self-test was executed on this host only (Linux 6.18, uid 0, util-linux unshare/setpriv); other hosts must run `gabriel doctor --selftest` themselves. `trusted_local` remains an explicitly separate non-contained mode. |
| WP06 Model gateway | `models/port.py`, `models/scripted.py`, `models/http_providers.py` (OpenAI-compatible, Anthropic; `env:` credentials only), `models/gateway.py` (retained prompt/response/usage, strict normalization, `model.generate` tool with conservative unknown usage) | `tests/test_models.py` (AT09 statuses: completed/truncated/invalid output/refusal/rate limit/timeout/transport failure; HTTP status mapping against local fake endpoints; credential reference restrictions); **four real OpenAI runs** recorded in `evidence/live/summary.json` with exact model revisions (`gpt-4.1-mini-2025-04-14`, `gpt-5-mini-2025-08-07`), known usage for every request and one retained `invalid_output`; several hundred further retained real-provider requests under `evidence/wp11/` | Anthropic provider implemented and tested against a local fake endpoint only (no credential available here) |
| WP07 Scheduler and kernel | `kernel/kernel.py` (port of the blueprint reference under `gabriel.kernel/1`, plus `complete()` and progress vector), `planning/scheduler.py`, plan validation in `contracts/rules.py`, outbox/lease/fencing/reconciliation in the reducer | `tests/test_kernel.py` (23 reference cases + 3; AT20/AT21 representation parts), `tests/test_scheduler.py` (AT10 tie-break, read-worker bound, single writer), `tests/test_owner.py` (plan bounds at the owner, bounded repair cycles) | Ranking heuristics are not used by the runner beyond the deterministic reference plan |
| WP08 Coding vertical slice | `domains/software/pack.py` (six ports; observations retain in-scope sources since the run-2 analysis), `agent/workspace.py`, `agent/runner.py`, `agent/export.py`, `interfaces/cli.py`, `evaluation/fixtures/parser_bug.py` | `tests/test_slice.py`: end-to-end repair with an independent oracle (scripted provider), interrupt after I/O and resume from the journal, false completion ("done" with failing oracle) and acceptance weakening (plan omitting the oracle, patch editing the oracle file) rejected, task without oracle refused unless acknowledged (AT19), termination between two file writes recorded/reconciled/re-observed (AT24), CLI smoke including pause/resume/export/audit/replay; **real-provider runs inside `linux_namespace`** (`evidence/live/`, `evidence/wp11/`): every test check executed in the containment backend, independent oracle passed, recorded replay passed with zero port calls, export delivered | Seeded synthetic tasks only; no real-world repository |
| WP11 Evaluation | `evaluation/corpus.py` (15 tasks, 5 families, executed soundness invariants, digest), `evaluation/comparators.py` (provider_only, simple_loop, gabriel, gabriel_no_repair, gabriel_reference_plan under one task contract; system-independent verification), `evaluation/harness.py` (freeze, digest check, parallel run, report with explicit denominators, paired differences, family-clustered bootstrap, held-out split), `gabriel eval` CLI, `scripts/eval_final_diffs.py` | `tests/test_evaluation.py`; **three frozen protocols executed with gpt-4.1-mini (72 + 120 + 150 runs)**, every provider request and response retained, every final diff retained (`evidence/wp11/`, `docs/EVALUATION_PROTOCOL.md`). Run 1: Gabriel 0.72 verified success versus simple loop 0.89 (Gabriel defect: repair prompt without test output). Run 2: 0.88 versus 0.92 (shared defect: observations did not retain the sources). Run 3, after both fixes: every system 1.00 on all 15 tasks including the held-out `encoding` family, zero false completions, paired differences exactly 0, so the corpus is saturated for this provider. The provider-only baseline's false completions in runs 1 and 2 (6/18, 7/24) were removed by both verification loops. **Advantage gate not passed** | One provider, one synthetic task distribution, two repetitions per unit at temperature 0; family intervals are descriptive. AT23/AT25 need WP09/WP10 |
| WP12 Release (G1) | `agent/backup.py` (SQLite online backup, byte-verified objects, anchor; restore re-verifies objects, anchor and replay), `agent/release.py` (release manifest: source commit, package/schema/reducer/catalog identities, dependency lock, platform, doctor, evidence digests, gate status), `scripts/smoke.sh`, `scripts/evidence_manifest.py` | `tests/test_release.py` (AT18: restore + replay + export match; corrupted object and truncated journal refused; CLI backup/restore/manifest); `evidence/wp12/`: smoke workflow executed on this host in `linux_namespace` (clean venv install, doctor self-test, task, export, audit, backup, restore, manifest), `docs/RELEASE_G1.md`; root license Apache-2.0 (`LICENSE`, declared in `pyproject.toml`, reported as resolved by the manifest) | No workspace migration after a catalog change; single host |

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
| AT09 model response boundaries | executed with the scripted provider and fake HTTP endpoints; real `invalid_output` retained | `tests/test_models.py`, `evidence/live/` |
| AT10 plan and scheduler bounds | executed | `tests/test_contracts.py`, `tests/test_scheduler.py`, `tests/test_owner.py` |
| AT11 complete coding slice | executed: scripted provider (positive, resume, false-completion controls), four real-provider runs, and 342 evaluation runs inside the namespace backend | `tests/test_slice.py`, `evidence/live/summary.json`, `evidence/wp11/` |
| AT12 external effect ambiguity | executed with fake targets (crash before marker, after marker before I/O, after I/O before commit, after commit) | `tests/test_workers.py` |
| AT13 cancellation and late result | executed | `tests/test_owner.py`, `tests/test_workers.py` |
| AT17 matched evaluation | executed under three frozen protocols with held-out families, matched comparators, explicit denominators, paired differences and bootstrap intervals; the advantage claim is **not established** (see `docs/EVALUATION_PROTOCOL.md`) | `evidence/wp11/` |
| AT18 release restore and export | executed: backup/restore with object, anchor and replay verification, corruption and truncation controls, release manifest, smoke workflow with restore | `tests/test_release.py`, `evidence/wp12/` |
| AT19 loss-preserving goal compilation | executed for the structured compiler (unknown kinds reject, missing oracle unresolved, weakening needs principal confirmation) | `tests/test_slice.py`, `tests/test_owner.py` |
| AT20 categorical completion | executed at kernel and owner level (no eligible candidate → no dispatch is the owner's admission rule) | `tests/test_kernel.py`, `tests/test_owner.py` |
| AT21 complete action/context identity | executed at kernel level and for candidate/patch identity (create/modify/delete distinct) | `tests/test_kernel.py` |
| AT22 proposed versus observed state | executed: only read-back advances the observed snapshot; stale evidence rejected | `tests/test_owner.py`, `tests/test_slice.py` |
| AT24 required coverage and contained partial effects | executed (required unsupported kinds reject at compilation, out-of-root/symlink writes reject, crash between two writes reconciled, containment self-test passed, truncation metadata retained) | `tests/test_slice.py`, `tests/test_workers.py` |
| AT14–AT16, AT23, AT25 | not in scope of the delivered packages (WP09/WP10 not started); not executed | — |

## Release assessment
G0 (reproducible local analytical tools): holds on this environment (WP01 rerun).
G1 (complete coding-agent workflow) is **established on this host** in the blueprint's sense: a
real provider, an isolated worktree, bounded tools inside the tested Linux-namespace backend,
independent tests, durable resume and artifact export worked together on seeded tasks
(`evidence/live/summary.json`, `evidence/wp11/`, `evidence/doctor_linux_namespace_selftest.json`,
`evidence/test_results.txt`), and the release route (restore bundle, doctor, identity manifest,
smoke workflow) was executed (`evidence/wp12/`). The claim is scoped: one host, one provider,
synthetic tasks. The **advantage gate is not passed**: under three frozen protocols Gabriel's
verified success never exceeded the simple verification loop's (paired means -0.17, -0.04,
0.00) and its cost was higher (one planner request per plan version; about 2.5 s of
observation, journal and review per task at equal model cost for the reference-plan variant).
After the last defect fix every system solves the whole corpus on its first request, so the
distribution no longer discriminates; the next protocol needs a harder frozen distribution. The
root license is Apache-2.0 (`LICENSE`), so the release gate's license review is closed
(`docs/RELEASE_G1.md`).

## Known limitations and open items
- `trusted_local` mode has no containment: a daemonized descendant survives (the witness
  reports `descendants_cleaned: false`), the host environment is scrubbed but the filesystem
  and network are open. It exists only for trusted repositories and is opt-in.
- Scripted provider cursors live in process memory; after a restart the script replays from
  its first response per step key (deterministic, documented).
- The planner prompt embeds a reference plan; a real model reproduces it in practice (103 of
  the 104 planner responses retained in runs 1 and 2 have the reference plan's node, dependency
  and check structure), which is why `gabriel_reference_plan` exists. Plan validation (unknown capability, unknown check, omitted
  mandatory check, cycle, limits) is enforced by the owner independently of the model.
- The capability catalog is fingerprinted from the loaded implementation source. Changing a tool
  module invalidates existing workspaces at open (`UNSUPPORTED: capability catalog differs`);
  an explicit migration command does not exist yet, so a new workspace is required. The run-2 fix
  to `software.observe` is such a change: workspaces created before it must be recreated.
- Invalid or truncated provider output is retained as a failed attempt and retried within the
  node's attempt limit with the diagnostic in the next prompt.
- The ADR-10 hold operation and ADR-11 planner bootstrap intent extend the proposed contract;
  the vendored specification files are unchanged apart from the two additive enum values.
- WP09 (memory) and WP10 (numerical/native adapters) are not started; G2/G3 are not established.
