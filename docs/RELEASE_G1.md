# G1 release report

Scope: the first product target of the blueprint, a complete coding-agent workflow on one host.
This report separates G1 evidence from the extension gates (G2 domain portability, G3 adaptive
policies), which are not established. A synthetic specification check is never counted as
product acceptance.

## Identity
- Source: branch `claude/vigilant-gauss-03dalc` of `LashSesh/gabriel-ai`, built from the recovered
  baseline `ed3da014e41999b4201b1654c8b2667ed907636b`; donor `LashSesh/kosmocrates` pinned at
  `a320ad101bbf0fdcde85d4617366ddee435d40b8`.
- Release manifest: `gabriel release-manifest` binds source commit, package source identity,
  schema registry digest, reducer identity, catalog digest, dependency lock, platform, doctor
  report and the digests of the acceptance evidence (`evidence/wp12/release_manifest_smoke.json`
  is the manifest produced by the smoke workflow).
- Supported platform/backend: Linux with user namespaces and util-linux `unshare`/`setpriv`
  (`linux_namespace`). Verified on Linux 6.18 x86_64 with Python 3.12.3. `trusted_local` is an
  explicitly separate non-contained mode.

## Release gates and their evidence
| gate | required evidence | status |
|---|---|---|
| Contract gate | owner/schema/policy failure cases | passed: `tests/test_contracts.py`, `test_owner.py`, `test_policy.py`, `test_artifacts.py` (`evidence/test_results.txt`) |
| Containment gate | backend-specific escape/cancellation/resource tests | passed on the release host: `test_namespace_jail_isolation_selftest`, `gabriel doctor --selftest` (`evidence/doctor_linux_namespace_selftest.json`) |
| G1 gate | real-provider coding task, independent oracle, recorded restart, export | passed: four real-provider runs (`evidence/live/summary.json`), restart/resume and false-completion controls (`tests/test_slice.py`), export in every run |
| Advantage gate | frozen paired evaluation with uncertainty and cost accounting | executed, **not passed as an advantage claim**: see `docs/EVALUATION_PROTOCOL.md` and `evidence/wp11/` |
| Release gate | install, restore, identity manifest, known issues, license review | install and restore passed (`scripts/smoke.sh`, `evidence/wp12/`); license review **open** (no root license) |

## What the evaluation established (WP11)
The frozen matched comparison (`evidence/wp11/run-gpt-4.1-mini/report.md`) shows that the
verification machinery removes false completions: the provider-only baseline declared success
in every run and was wrong in a third of them; Gabriel and the simple verification loop declared
no false completion. It also shows that, on this task distribution and provider, Gabriel's
verified success did not exceed the simple loop's; the failure analysis found a Gabriel defect
(repair prompts lacked the retained test output) and a budget asymmetry (one planner request per
plan version). A second frozen protocol (`evidence/wp11/protocol2.frozen.json`) evaluates the
corrected runner and a reference-plan variant, reporting previously seen tasks and a new
held-out family separately. A failed advantage gate does not erase the working G1 slice; it
determines what stays optional.

## Backup and restore (AT18)
`gabriel backup` writes a coherent SQLite snapshot through the online backup API, every
referenced artifact (byte-verified) and the independent anchor. `gabriel restore` rebuilds the
layout elsewhere, re-verifies every object, checks the retained anchor and replays the journal.
Corrupted objects and a truncated journal suffix are refused (`tests/test_release.py`); a
corrupted checkpoint projection with a correct frontier is rejected by its binding
(`tests/test_owner.py::test_anchor_detects_truncated_suffix_and_checkpoint_binding`).

## Known issues
- Root license unresolved: the recovered tree only carries a license under `native_pse/`.
  Redistribution needs an explicit root license; local use and review are unaffected.
- A tool implementation change invalidates existing workspaces at open; no migration command.
- Single-user, single-host deployment; no network identity or tenant isolation.
- WP09 (memory), WP10 (numerical/native adapters) are not started; G2/G3 are not established.
