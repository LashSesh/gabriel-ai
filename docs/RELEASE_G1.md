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
| Release gate | install, restore, identity manifest, known issues, license review | passed: install and restore (`scripts/smoke.sh`, `evidence/wp12/`); root license Apache-2.0 (`LICENSE`, declared in `pyproject.toml`, recorded in the manifest) |

## What the evaluation established (WP11)
Three frozen matched comparisons were executed with gpt-4.1-mini (72, 120 and 150 runs;
`docs/EVALUATION_PROTOCOL.md`, `evidence/wp11/`). Across all of them the verification machinery
removed false completions: the provider-only baseline declared success in every run and was
wrong in roughly a third of them, while Gabriel and the simple verification loop never declared
an unverified success. No protocol measured a higher verified success for Gabriel than for the
simple loop (paired means -0.17, -0.04 and 0.00), and none measured lower resource use at equal
success: the planner request doubles model cost unless the reference plan is admitted directly,
and the owner adds about 2.5 s of observation, journal and review per task. After the last fix
every system, including the provider-only baseline, solved all 15 tasks on its first request, so
the corpus is saturated for gpt-4.1-mini and a further protocol needs a harder frozen
distribution before an advantage can be shown or refuted.
Each run's failure analysis found a real defect that the next protocol fixed (repair prompts
without the retained test output; one planner request per plan version; observations that did
not retain the sources the worker edits), and the defective runs are retained unchanged. A
failed advantage gate does not erase the working G1 slice; it determines what stays optional.

## Backup and restore (AT18)
`gabriel backup` writes a coherent SQLite snapshot through the online backup API, every
referenced artifact (byte-verified) and the independent anchor. `gabriel restore` rebuilds the
layout elsewhere, re-verifies every object, checks the retained anchor and replays the journal.
Corrupted objects and a truncated journal suffix are refused (`tests/test_release.py`); a
corrupted checkpoint projection with a correct frontier is rejected by its binding
(`tests/test_owner.py::test_anchor_detects_truncated_suffix_and_checkpoint_binding`).

## License
The tree is licensed under the Apache License, Version 2.0 (`LICENSE`, chosen by the author).
`native_pse/LICENSE` (MIT, same author) keeps covering that subtree; both are permissive and
compatible. The bundled UEA time-series files under `data/` are external datasets distributed
under CC BY 4.0 with their own attribution (`data/ATTRIBUTION.md`); the root license does not
re-license them. Python and LaTeX dependencies are not bundled.

## Known issues
- A tool implementation change invalidates existing workspaces at open; no migration command.
- Single-user, single-host deployment; no network identity or tenant isolation.
- WP09 (memory), WP10 (numerical/native adapters) are not started; G2/G3 are not established.
