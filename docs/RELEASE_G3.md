# G3 report: evaluated adaptive policies (routing feature experiment)

Scope: the blueprint's third level, "versioned memory/routing policies improve declared
held-out task criteria while preserving regression gates", approached through the routing
feature experiment the blueprint names first: bounded task-progress features from the
committed event stream, a small readout proposing among already authorized choices, a
rule-based router as the comparator, a conventional feature/readout baseline beside the
recurrent-feature variant, decision loss and end-to-end effect both reported. This report
states what was executed and the verdict; it does not revise G1/G2.

## What was built (ADR-15)
- Hard corpus tier (`evaluation/corpus_hard.py`): nine tasks in three families whose plausible
  wrong fix passes the visible tests and fails the oracle; the trap invariant is executed by
  `gabriel eval corpus-check --tier hard`.
- `policy/features.py`: versioned progress channels (`progress-channels-v1`) with clipping and
  missing indicators, retained as integer milli-units.
- `policy/recurrent.py`: the reference recurrent map (`recurrent.features/1`) from the
  blueprint's equations; deterministic from the known initial state, bounded, rejecting
  configuration mismatch, missing elements and nonfinite inputs.
- `policy/router.py`: `gabriel.router-policy/1` records (rule-based or logistic readout over
  channels or recurrent features), decision records with exact inputs, logistic training and
  decision loss.
- Runner integration: one decision point (failed verification: repair or documented stop),
  decisions retained in memory, outcome labels and episodes per terminal run, episodic
  retrieval into the worker prompt with recorded observation ids, policy pin per task with
  digest binding and rollback by pinning an earlier policy.
- Harness: `gabriel_policy` and `gabriel_episodes` arms, frozen policy and episode seed in the
  protocol, declared held-out criterion, `scripts/policy_route.py train|promote`.

## Executed protocols
Training runs (protocol 4a, hard tier, training families `multi_file` and `trap`, six tasks,
three repetitions, rule-based policy, `linux_namespace`):

| run | provider | planner | verified | recovery | router decisions |
|---|---|---|---|---|---|
| `run4a-train-mini-saturated` | gpt-4.1-mini-2025-04-14 | model | 18/18 | 0 | 0 |
| `run4a-train-nano-model-planner` | gpt-4.1-nano | model | 7/18 (11 runs ended on invalid plan JSON before any plan) | 1 | 0 |
| `run4a-train` | gpt-4.1-nano | reference | 18/18 (3 runs replanned after invalid worker JSON) | 3 | 0 at a verification boundary |

The hard tier's trap invariant holds for every task (the plausible wrong fix passes the
visible tests and fails the oracle, executed by `corpus-check`), but neither provider took the
trap: no first patch failed the independent verification in 54 training runs, so the
failed-verification boundary never occurred and `scripts/policy_route.py train` found no
labeled decision of either class. A readout cannot be trained from these outcomes; the
candidate is recorded as rejected for that reason, not evaluated on fabricated labels. The
training runs did yield 18 episodes (goal, final diff, verified outcome) that seed the
episodic-retrieval arm.

Evaluation run (protocol 4b, hard tier, all nine tasks, `stateful` held out, gpt-4.1-mini, two
repetitions, frozen episode seed from the training families):

| system | runs | verified | p_success | false completions | mean requests | mean tokens | mean wall s | recovery |
|---|---|---|---|---|---|---|---|---|
| provider_only | 18 | 18 | 1.00 | 0 | 1.00 | 825 | 2.1 | 0 |
| simple_loop | 18 | 18 | 1.00 | 0 | 1.00 | 824 | 2.6 | 0 |
| gabriel_reference_plan | 18 | 18 | 1.00 | 0 | 1.00 | 829 | 4.4 | 0 |
| gabriel_episodes | 18 | 18 | 1.00 | 0 | 1.00 | 1433 | 4.5 | 0 |

Held-out `stateful` family only (six runs per system; the family was never run before this
protocol, and its seed episodes come from other tasks):

| system | verified | p_success | false completions | mean requests | mean tokens | mean wall s |
|---|---|---|---|---|---|---|
| provider_only | 6/6 | 1.00 | 0 | 1.00 | 828 | 2.2 |
| simple_loop | 6/6 | 1.00 | 0 | 1.00 | 827 | 2.6 |
| gabriel_reference_plan | 6/6 | 1.00 | 0 | 1.00 | 829 | 4.8 |
| gabriel_episodes | 6/6 | 1.00 | 0 | 1.00 | 1395 | 4.5 |

Previously seen tasks (`multi_file`, `trap`; twelve runs per system, not a held-out test because
their seed episodes contain earlier solutions of the same tasks): every system 12/12, mean tokens
823 / 823 / 829 / 1452.

What the retained workspaces show (`evidence/wp13/run4b-eval/runs/*/`): every one of the 18
`gabriel_episodes` runs retrieved two episodes into the worker prompt, recorded in the context
manifest as `procedure` entries with purpose `episodic_retrieval` and their observation ids; for
the held-out `stateful` tasks the retrieved episodes were earlier solutions of `mf-config` and
`tr-percent`, never of the task at hand. No run of any system failed its independent
verification, so no repair boundary occurred and the rule-based decision point never fired. The
provider-only baseline made no false completion: gpt-4.1-mini produced the correct fix at its
first request in all 18 runs, so the trap that `corpus-check` proves to exist was never taken.
Every final diff is retained (`final_diffs/index.json`, 72 of 72 worktrees present).

Declared criterion for the episodic arm (frozen in the protocol): at least the verified success of
`gabriel_reference_plan` on the held-out family, fewer mean model tokens, no false completion.
Outcome: success equal (1.00 against 1.00), no false completion, but 1395 against 829 mean tokens
(68 % more). **Criterion not met.** `scripts/policy_route.py promote` recorded the decision in
`evidence/wp13/promotion/promotion.json`: candidate `null`, decision `rejected`, reason "no readout
can be trained: the training run produced 0 decision samples", treatment criterion `met: false`.

## Verdict
**G3 is not established.** The blueprint admits an adaptive policy only when held-out evidence
shows the declared criterion met with regression gates intact; neither candidate of this route
reached that bar.

- Readout router: no candidate exists. The decision point the readout was to serve (a failed
  verification) did not occur once in 54 training runs with two providers, so the training set
  holds no labeled decision of either class and `scripts/policy_route.py train` wrote
  `trained: false`. The decision loss of a readout against the rule is therefore measured only on
  the synthetic samples of `tests/test_policy_route.py`, which show that the trainer and the
  decision point work, not that a readout helps on tasks. The route did not fabricate labels,
  did not lower the threshold until something fired, and did not evaluate a readout in protocol 4b.
- Episodic retrieval: executed as declared and rejected on the declared criterion. On the
  held-out family it reached the same verified success as the rule-based reference with no
  false completion but 68 % more model tokens; the retrieved episodes were real, recorded with
  their observation ids, and visibly did not change what the provider produced.
- What the route does establish: the policy machinery works end to end under the owner's
  constraints (pinned, digest-bound, decisions and episodes retained, promotion recorded with
  its reason) and the hard tier's trap invariant holds for every task. What it does not
  establish is any effect of a learned policy on task outcomes, because the frozen hard
  distribution is at ceiling for gpt-4.1-mini: every system solved every task at its first
  request in 72 runs. The hard tier is harder for the oracle than the standard tier, not for
  the provider.

Consequence for production: the rule-based policy (`rule-based-v1`, no episodes) remains the
default pin; no readout or episodic policy is promoted; `gabriel_policy` stays an evaluation arm.
A next protocol needs a distribution on which first patches fail at a measurable rate (a pilot
before the freeze must show failed verifications, for example interface contracts hidden from the
visible tests, files beyond the prompt budget, or a weaker provider at the boundary) so that
labeled decisions exist and the decision loss can be measured on real outcomes.

## Regression gates
Executed on this host after the route was integrated, with the rule-based policy as the default
pin:

- `GABRIEL_CONTAINMENT_TESTS=1 .venv/bin/python -m pytest tests -vv -rs`: 142 passed, 1 skipped
  (the live-provider tests without `GABRIEL_LIVE_PROVIDER=1`); `evidence/test_results.txt`,
  `evidence/test_run.json`. Every G1 and G2 acceptance test (AT11 to AT25) passes unchanged beside
  the new `tests/test_policy_route.py`; the namespace containment self-test passes.
- `gabriel eval corpus-check --tier standard` and `--tier hard`: all 15 standard and 9 hard tasks
  sound, `trap_holds` true for all nine hard tasks (corpus digest `09c7eca3…`).
- The G1 smoke workflow (`scripts/smoke.sh`: clean install, doctor self-test, scripted task,
  export, audit, backup, restore, release manifest) rerun in `linux_namespace`; its outputs and
  the release manifest with the G3 gate text are recorded under `evidence/wp12/`.
- Runner behaviour on the G1/G2 paths is unchanged except for what the route adds at the
  boundaries: a decision record when a repair boundary occurs, and an outcome label plus an
  episode in the memory service at every terminal state. Replay and restore cover both.
