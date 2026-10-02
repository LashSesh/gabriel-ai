# G1 matched evaluation protocol (WP11)

The frozen, machine-readable protocol is `evidence/wp11/protocol.frozen.json`; its digest is
checked before every run and the corpus digest is checked against the code. This page explains
the choices. The report of the executed run is `evidence/wp11/run-gpt-4.1-mini/report.md`.

## Question
Does Gabriel's owner/scheduler/verification machinery increase independently verified task
success or reduce resources at equal success, compared with a minimal agent under the same
provider, tools, budget and oracle? This is the blueprint's falsifiable target, not a claim about
general capability.

## Task distribution
Nine held-out repository-repair tasks in three families (`src/gabriel_agent/evaluation/corpus.py`):
text parsing (kvparse, csvfields, querystring), numeric logic (median, roman numerals, leap
years) and collections (dedupe, slugify, chunk). Each repository carries a seeded defect, visible
tests that pass on the defect, and an independent oracle that is never stored in the repository.
`gabriel eval corpus-check` executes the invariants (defect passes visible tests, fails the
oracle; reference fix passes both) and the corpus digest is part of the frozen protocol.
The reference fixes are never shown to any system.

## Systems (identical task contract, provider profile, backend and budget)
| system | loop | declared success |
|---|---|---|
| `provider_only` | one request, patch applied | an admissible patch was applied |
| `simple_loop` | request -> apply -> run visible tests + oracle -> feedback, up to the request budget | its own check runs exit 0 |
| `gabriel` | owner, planner request, observe, baseline, propose, apply, read-back, review, verify; up to 2 repair cycles | run state `succeeded` |
| `gabriel_no_repair` | as `gabriel` with `max_repairs=0`, `max_plan_versions=1` (ablation) | run state `succeeded` |

Budget per task for every system: 6 model requests, 120000 model tokens, 64 tool attempts,
10 minutes wall clock, 60000/4000 input/output tokens per request, temperature 0. Every
provider call goes through the same gateway, so raw requests and responses are retained for
every system. Time limits count as failures.

## Verification (system-independent)
After a system finishes, the harness opens its final worktree and checks: changed paths are
inside `allowed_paths`; the visible tests exit 0; the oracle, installed fresh from the corpus
text, exits 0. All three run in the Linux-namespace backend. `V_i = 1` only when all hold.

## Metrics
With `N` runs per system, `V_i` verified and `D_i` declared success:
`p_success = mean(V)`, `p_false_completion = mean(D(1-V))`, conditional false completion
`sum(D(1-V)) / sum(D)` with its own denominator, model requests, model tokens and wall time per
run (every attempt counted), recovery (Gabriel runs that used repair cycles or extra plan
versions), paired differences `gabriel - baseline` per task averaged over repetitions, and
percentile bootstrap intervals (2000 resamples, seed 20261002) resampling families with
replacement, with a task-level resampling as a secondary view. With three families the family
intervals are wide by construction; they are descriptive, not a powered test.

## Freezing and amendments
`gabriel eval freeze` digests the protocol body and records the harness code identity.
`gabriel eval run` refuses a changed protocol or corpus. A harness code change after freezing is
reported in the results as `harness_amended`. The first launch of this protocol failed in the
harness before any provider call (relative worktree paths); no evaluation data were observed,
the path handling was fixed, and the protocol was frozen again with the same digest.
