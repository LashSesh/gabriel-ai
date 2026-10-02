# G2 release report: general workspace agent (domain portability)

Scope: the blueprint's second product target, "coding, document evidence and at least one
numerical adapter use the same task and policy machinery". This report states what was
executed for WP09 and WP10 and what the G2 claim covers. It does not establish G3 (evaluated
adaptive policies) and does not revise the advantage-gate verdict of `docs/EVALUATION_PROTOCOL.md`.

## What changed in the core
- `domains/base.py` (ADR-13): the DomainPack contract the runner calls; no domain name is
  branched on in `agent/runner.py`, `agent/workspace.py`, the owner, the reducer, the scheduler
  or the supervisor. One `ToolRegistry` holds all packs, so a workspace pins one catalog digest
  for the three domains.
- `memory/service.py` (ADR-14): the evidence index with its own hash chain, versioned
  observations, as-of retrieval, scoped claims, outcome labels, policy promotion, compaction;
  included in backup and restore.
- Packs: `domains/document` (sources as memory observations, citation markers, citation-binding
  and required-claims verifiers) and `domains/numerical` (declared operations of
  `adapters/analytical.py` in a fresh contained worker per job, reference-contract verifier).

## Gate evidence
| gate | required evidence | status |
|---|---|---|
| Contract gate | owner/schema/policy failure cases | unchanged from G1; 138 tests pass (1 opt-in live test skipped) including the new memory and domain suites (`evidence/test_results.txt`) |
| Containment gate | backend-specific tests | unchanged; the numerical worker also runs inside the namespace jail (`test_numerical_worker_runs_inside_the_namespace_jail`) |
| G2 gate | same owner/policy path supports all three task families | **established on this host, scoped**: AT23 executed with a real provider in `linux_namespace` (`evidence/wp10/at23/report.md`); AT14, AT15, AT16, AT25 executed as tests |
| Advantage gate | frozen paired evaluation | unchanged: not passed (`docs/EVALUATION_PROTOCOL.md`) |
| Release gate | install, restore, manifest, license | restore now covers the memory index; Apache-2.0 root license |

## AT23 as executed
One workspace (`linux_namespace`, doctor self-test passed), provider gpt-4.1-mini for the valid
tasks, scripted providers for the controls, one catalog digest for every run, replay passed
with zero external calls, memory chain verified (`evidence/wp10/at23/summary.json`).

| domain | pack | state | requests | tokens | model revision | mandatory checks |
|---|---|---|---|---|---|---|
| software | software-repair 0.1.0 | succeeded | 2 | 1922 | gpt-4.1-mini-2025-04-14 | unit, oracle, scope, base-commit, checks-intact, no-secrets passed |
| document | document-amendment 0.1.0 | succeeded | 2 | 1681 | gpt-4.1-mini-2025-04-14 | citations, claims, scope, base-commit, checks-intact, no-secrets passed |
| numerical | numerical-transform 0.1.0 | succeeded | 2 | 1481 | gpt-4.1-mini-2025-04-14 | reference, scope, base-commit, checks-intact, no-secrets passed |

| control (scripted, no repair cycles) | state | failing mandatory check or rejection |
|---|---|---|
| software: wrong patch, then a plan dropping the oracle and a patch editing it | failed | oracle |
| document: fabricated observation id | failed | citations |
| document: right facts cited from the wrong source | failed | claims |
| document: amendment of a source file | failed | rejected at apply (outside the editable scope) |
| numerical: conversion to a unit of another dimension | failed | reference (retained verdict `out_of_scope`) |
| numerical: undeclared operation | failed | rejected at normalization (no job ran) |
| numerical: output path outside the scope | failed | rejected at normalization (no job ran) |

AT16 in the same run: the direct and the hosted (namespace-jailed) worker produced identical
output bytes for the same input and the same worker build; unsupported inputs returned
`out_of_scope` or `invalid_input`; two graphs that share the inherited padded signature have
different retained signatures and different cache keys.

The first real-provider run is retained under `evidence/wp10/at23-run1-oracle-phrase/`: the
document task failed its required-claims check although the amendment was correct and both
citations resolved, because the oracle demanded the literal phrase "30 days" and the model wrote
"thirty (30) days". The oracle format now accepts alternative phrasings of the same fact while
the cited source span stays fixed; the run was repeated.

## Scope of the claim
- Three fixture task families on one host: repository repair (seeded defect with a hidden
  oracle), source-grounded document amendment (two sources, two required claims) and numerical
  transformation (unit conversion with a reference contract). A real-world corpus for the
  document and numerical domains does not exist yet.
- The analytical adapter is the standard-library worker with three declared operations; the
  native PSE worker and the recurrent routing feature stay optional and unbuilt (WP10's optional
  part). The inherited padded graph signature is reproduced only as a collision control.
- Memory retrieval is lexical; there is no trained retrieval or routing policy, so G3 is not
  claimed. The promotion rule requires held-out evidence and is tested, not evaluated.
- Document extraction supports UTF-8 text only.

## Advantage gate on the document and numerical families (protocol 5, ADR-16)
Executed after this report's gate evidence, with frozen corpora, matched baselines, two pilots
and held-out families (`docs/EVALUATION_PROTOCOL.md`, `evidence/wp14/`): 144 runs with
gpt-4.1-mini in `linux_namespace`. The provider-only baseline false-completed five of six
`conflict` amendments; every verifying system, Gabriel included, removed those false
completions, the simple verification loop as reliably as the owner and at no higher cost. On
the `revision` family every arm, with or without the revision rule, chose the dated later
revision at the first request; on the `revoked` family the production view saved the plain
view's repairs (1.00 against 1.83 requests), but three of those four repairs were an
observation-id mix-up on a correct statement, not the withdrawn content being used. The
numerical tier did not discriminate at all (identical outcomes and tokens; Gabriel's worker
contained, the baselines' in process). Against the criterion declared before the run, the
advantage gate is **not passed** on these families either, and the declared memory ablations
fell below the minimum relevant effect. The G2 claim of this report is unchanged by that
result: the three domains run through one core; whether the core's memory mechanisms buy
anything measurable depends on the provider and the distribution, and for gpt-4.1-mini on these
tasks it is small.

## Known issues
- A tool implementation change invalidates existing workspaces at open (no migration).
- The numerical job cache lives in the workspace as a derived file; it is not part of backups.
- Single-user, single-host deployment; no network identity or tenant isolation.
