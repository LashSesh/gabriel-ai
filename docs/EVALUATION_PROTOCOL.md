# G1 matched evaluation protocol (WP11)

Three frozen protocols were executed, each after a failure analysis of the previous run:

| protocol | digest | corpus | run directory | runs |
|---|---|---|---|---|
| 1 | `b9f824a4…` (`evidence/wp11/protocol.frozen.json`) | 9 tasks, 3 families | `evidence/wp11/run-gpt-4.1-mini` | 72 |
| 2 | `b9a6e0d0…` (`evidence/wp11/protocol2.frozen.json`) | 12 tasks, 4 families (`validation` held out) | `evidence/wp11/run2-gpt-4.1-mini` | 120 |
| 3 | `02da6897…` (`evidence/wp11/protocol3.frozen.json`) | 15 tasks, 5 families (`encoding` held out) | `evidence/wp11/run3-gpt-4.1-mini` | 150 |

Every protocol digest is checked before a run and the corpus digest is checked against the
code; every run directory holds `protocol.json`, `results.json`, `report.json`, `report.md`, one
`runs/<task>--<system>--<rep>/` directory per unit with `record.json` (declared outcome and the
system-independent verification), the retained provider requests and responses (`store/objects`
for the baselines, the workspace journal and object store for the Gabriel variants), and
`final_diffs/<unit>.diff` with the exact worktree content the verification judged
(`scripts/eval_final_diffs.py`; the materialized repositories and worktrees are git
repositories of their own and are not committed).

## Question
Does Gabriel's owner/scheduler/verification machinery increase independently verified task
success or reduce resources at equal success, compared with a minimal agent under the same
provider, tools, budget and oracle? This is the blueprint's falsifiable target, not a claim about
general capability.

## Task distribution
Fifteen repository-repair tasks in five families (`src/gabriel_agent/evaluation/corpus.py`):
text parsing (kvparse, csvfields, querystring), numeric logic (median, roman numerals, leap
years), collections (dedupe, slugify, chunk), validation (e-mail, ISBN-10, Luhn; written after
run 1) and encoding (run-length encoding, rot13, hex codec; written after run 2). Each
repository carries a seeded defect, visible tests that pass on the defect, and an independent
oracle that is never stored in the repository. `gabriel eval corpus-check` executes the
invariants (defect passes visible tests, fails the oracle; reference fix passes both) and the
corpus digest is part of the frozen protocol. The reference fixes are never shown to any system.

A family is "held out" for exactly one protocol: the one frozen right after it was written.
Tasks that were run under an earlier protocol are reported as "previously seen" afterwards,
because their failure analyses informed the fixes.

## Systems (identical task contract, provider profile, backend and budget)
| system | loop | declared success |
|---|---|---|
| `provider_only` | one request, patch applied | an admissible patch was applied |
| `simple_loop` | request -> apply -> run visible tests + oracle -> feedback, up to the request budget | its own check runs exit 0 |
| `gabriel` | owner, planner request, observe, baseline, propose, apply, read-back, review, verify; up to 2 repair cycles | run state `succeeded` |
| `gabriel_no_repair` | as `gabriel` with `max_repairs=0`, `max_plan_versions=1` (ablation) | run state `succeeded` |
| `gabriel_reference_plan` | as `gabriel`, but the domain pack's reference plan is admitted without a planner request (protocols 2 and 3) | run state `succeeded` |

All systems share the software pack's observation and prompt builder, the patch normalizer and
the containment backend; the baselines call them without the owner. Budget per task for every
system: 6 model requests, 120000 model tokens, 64 tool attempts, 10 minutes wall clock,
60000/4000 input/output tokens per request, temperature 0. Every provider call goes through the
same gateway, so raw requests and responses are retained for every system. Time limits count
as failures.

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
replacement, with a task-level resampling as a secondary view. With three to five families the
family intervals are wide by construction; they are descriptive, not a powered test.

## Run 1 (protocol 1, 72 runs, gpt-4.1-mini-2025-04-14)
| system | verified | p_success | false completions | mean requests | mean tokens |
|---|---|---|---|---|---|
| provider_only | 12/18 | 0.67 | 6 (0.33 of declared) | 1.00 | 719 |
| simple_loop | 16/18 | 0.89 | 0 | 2.17 | 2329 |
| gabriel | 13/18 | 0.72 | 0 | 3.22 | 3359 |
| gabriel_no_repair | 10/18 | 0.56 | 0 | 2.00 | 1827 |

Paired `gabriel - simple_loop`: mean -0.17, family CI95 [-0.33, +0.00]. Failure analysis
(retained prompts): the repair prompt included only the assessment record, not the retained
test output (the witness reference sits one level deeper in the evidence record than the
runner read), so the model repaired blind; and every plan version costs a planner request, so
Gabriel had three worker proposals where the simple loop had six. Both were fixed before
protocol 2 (`runner._failure_context`, `gabriel_reference_plan`).

## Run 2 (protocol 2, 120 runs, gpt-4.1-mini-2025-04-14)
| system | verified | p_success | false completions | mean requests | mean tokens | held-out `validation` |
|---|---|---|---|---|---|---|
| provider_only | 17/24 | 0.71 | 7 (0.29 of declared) | 1.00 | 748 | 5/6, 1 false completion |
| simple_loop | 22/24 | 0.92 | 0 | 1.79 | 1836 | 6/6 |
| gabriel | 21/24 | 0.88 | 0 | 2.75 | 2976 | 6/6 |
| gabriel_no_repair | 16/24 | 0.67 | 0 | 2.00 | 1861 | 5/6 |
| gabriel_reference_plan | 21/24 | 0.88 | 0 | 1.38 | 1271 | 6/6 (1.00 requests, 826 tokens) |

Paired `gabriel - simple_loop`: mean -0.04, family CI95 [-0.12, +0.00]; `gabriel -
gabriel_no_repair`: +0.21, [+0.17, +0.29]. The only task where Gabriel lost a run to the simple
loop was nl-median (rep 1); every system failed co-chunk in every run.

Failure analysis (retained prompts and `final_diffs/`): the first observation of every system
did not retain the in-scope source files in the artifact store. `build_prompt` reads source
content back from the store by the digest listed in the manifest and silently skipped a file it
could not fetch, so the first worker prompt of every system listed digests only, and the model
rewrote each file from its name and the goal. nl-median lost the unseen `mean()` function (the
visible test imports it; the repair rounds then showed the already-patched file, so `mean` could
not be recovered), and co-chunk was rewritten as a generator in every system, after which
gpt-4.1-mini at temperature 0 returned the identical content on every repair request although
its own rationale named the problem. This defect affected all systems equally (shared prompt
builder) and it is a Gabriel defect in the blueprint's sense of retained inputs: an observation
that does not retain what the proposal will edit. Fixed before protocol 3: `software.observe` now retains in-scope
text sources (bounded by 2 MiB per observation), and the prompt marks a file whose content is
not retained as `[CONTENT NOT RETAINED]` instead of omitting it
(`tests/test_evaluation.py::test_worker_prompt_contains_retained_sources`).

## Run 3 (protocol 3, 150 runs, gpt-4.1-mini-2025-04-14)
| system | verified | p_success | false completions | mean requests | mean tokens | mean wall s | held-out `encoding` |
|---|---|---|---|---|---|---|---|
| provider_only | 30/30 | 1.00 | 0 | 1.00 | 808 | 2.5 | 6/6 |
| simple_loop | 30/30 | 1.00 | 0 | 1.00 | 805 | 2.7 | 6/6 |
| gabriel | 30/30 | 1.00 | 0 | 2.00 | 1916 | 7.8 | 6/6 |
| gabriel_no_repair | 30/30 | 1.00 | 0 | 2.00 | 1922 | 8.8 | 6/6 |
| gabriel_reference_plan | 30/30 | 1.00 | 0 | 1.00 | 810 | 5.1 | 6/6 |

With the sources in the prompt, every system solved every task with its first request,
including co-chunk and nl-median, which no Gabriel variant had solved reliably before. All
paired differences are exactly zero, no repair cycle was used, and the provider-only baseline
made no false completion because no first patch was wrong. The corpus is therefore saturated
for this provider: it no longer discriminates between the systems. The remaining differences are
cost: the planner request doubles Gabriel's model requests and tokens without changing any
outcome (`gabriel` versus `gabriel_reference_plan`), and the owner's observation, journal,
read-back and review add about 2.5 s per task over the simple loop at identical model cost
(`gabriel_reference_plan` 810 tokens versus `simple_loop` 805).

## Assessment of the advantage gate
The gate is **not passed**. What the three protocols establish, with their retained evidence:

- Verification removes false completions when the first patch is wrong. In runs 1 and 2 the
  provider-only baseline was wrong in 6 of 18 and 7 of 24 declared successes; Gabriel and the
  simple loop were wrong in 0 of 50 and 0 of 59. In run 3 no first patch was wrong, so the
  control had nothing to catch.
- No protocol measured an increase of verified success over the simple verification loop
  (paired means -0.17, -0.04, 0.00), and none measured a reduction of resources at equal
  success: the owner costs one planner request per plan version (removed by
  `gabriel_reference_plan`) and the observation/journal/review time, and saves no tokens.
- The failures Gabriel suffered in runs 1 and 2 were its own defects, found through the retained
  prompts and diffs: a repair prompt without the test output, and an observation that did not
  retain the sources the worker edits. The second one handicapped every system equally because
  the baselines share the prompt builder; fixing it moved every system to 1.00.
- The task distribution is now at ceiling for gpt-4.1-mini. A further protocol needs a harder
  frozen distribution (multi-file defects, defects whose plausible first patch is wrong, files
  beyond the prompt budget, tasks where a wrong patch passes the visible tests so that the
  false-completion control is exercised) or a weaker provider, decided before the freeze. Until
  such a run shows an advantage, the blueprint's rule applies: the owner/scheduler machinery
  stays optional for the coding slice, and what G1 provides regardless is containment, retained
  evidence, recorded replay and restore.

## Protocol 4: the G3 route on the hard tier
After run 3 saturated the standard tier, a hard tier was written (`evaluation/corpus_hard.py`,
nine tasks in the families `multi_file`, `trap` and `stateful`): every task carries a
plausible wrong fix that passes the visible tests and fails the oracle, and
`gabriel eval corpus-check --tier hard` executes that trap invariant beside the soundness
invariants. The G3 route trains a readout router from explicit task outcomes on two training
families and evaluates it on the held-out third family with a declared criterion
(`docs/RELEASE_G3.md`, `evidence/wp13/`).

Protocol 4a (training; `multi_file` and `trap`, six tasks, three repetitions, rule-based policy,
`linux_namespace`) was executed three times with different providers and planners:
gpt-4.1-mini with the model planner (18/18 verified), gpt-4.1-nano with the model planner (7/18;
eleven runs ended on invalid plan JSON before any plan) and gpt-4.1-nano with the reference plan
(18/18). In none of the 54 runs did a first patch fail the independent verification, so the
failed-verification boundary never occurred, no labeled router decision exists and no readout
was trained (`evidence/wp13/policies/metrics.json`: `trained: false`). The 18 episodes of the
gpt-4.1-mini run seed the episodic-retrieval arm.

Protocol 4b (evaluation; all nine tasks, `stateful` held out, gpt-4.1-mini, two repetitions,
frozen episode seed, digest `0acb56ab…`):

| system | verified | p_success | false compl. | mean requests | mean tokens | held-out verified | held-out tokens |
|---|---|---|---|---|---|---|---|
| provider_only | 18/18 | 1.00 | 0 | 1.00 | 825 | 6/6 | 828 |
| simple_loop | 18/18 | 1.00 | 0 | 1.00 | 824 | 6/6 | 827 |
| gabriel_reference_plan | 18/18 | 1.00 | 0 | 1.00 | 829 | 6/6 | 829 |
| gabriel_episodes | 18/18 | 1.00 | 0 | 1.00 | 1433 | 6/6 | 1395 |

Every `gabriel_episodes` run carried two retrieved episodes with recorded observation ids; on
the held-out family they came from other tasks. The declared criterion for that arm (at least
the reference's verified success, fewer tokens, no false completion on the held-out family) is
not met: equal success at 68 % more tokens. The promotion procedure recorded `rejected` for the
readout (no candidate) and `met: false` for the episodic arm
(`evidence/wp13/promotion/promotion.json`). The hard tier's trap exists for every task
(`corpus-check` executes the plausible wrong fix against visible tests and oracle) but
gpt-4.1-mini never produced it: zero false completions in the provider-only baseline, zero
failed verifications in 72 runs. For this provider the hard tier is at ceiling like the standard
tier; G3 is not established (`docs/RELEASE_G3.md`).

## Freezing and amendments
`gabriel eval freeze` digests the protocol body and records the harness code identity.
`gabriel eval run` refuses a changed protocol or corpus. A harness code change after freezing is
reported in the results as `harness_amended`. The first launch of protocol 1 failed in the
harness before any provider call (relative worktree paths); no evaluation data were observed,
the path handling was fixed, and the protocol was frozen again with the same digest. Runs 1 and
2 are retained unchanged, including the defects their analyses found; nothing was re-run under
an old protocol after a fix.
