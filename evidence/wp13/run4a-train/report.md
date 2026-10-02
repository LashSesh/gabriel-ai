# G1 matched evaluation report

Protocol `51e813eafa15bdc5` (frozen 2026-10-02T21:24:57.304003+00:00), provider `openai_compat` model `gpt-4.1-nano`, backend `linux_namespace`, 6 tasks in 2 families, 18 runs.

Protocol 4a (G3 route, training), third freeze. gpt-4.1-mini saturated the hard training families (run4a-train-mini-saturated: 18/18 first attempt, no repair decision). gpt-4.1-nano with the model planner mostly returned invalid plan JSON, so most runs ended before any repair decision (run4a-train-nano-model-planner). This protocol runs the rule-based Gabriel with the reference plan (no planner request, as the G3 arms do) and gpt-4.1-nano on the training families multi_file and trap, three repetitions, to collect router decisions at the failed-verification boundary labeled by the independent verification, and episodes for the frozen seed. The stateful family stays held out for protocol 4b.

## All tasks

| system | runs | verified | p_success | CI95 (families) | declared | false completions | cond. FC | mean requests | mean tokens | mean wall s | recovery |
|---|---|---|---|---|---|---|---|---|---|---|---|
| gabriel_reference_plan | 18 | 18 | 1.00 | [1.00, 1.00] | 18 | 0 | 0.00 (n=18) | 1.50 | 1411 | 5.6 | 3 |

## Paired differences, all tasks (gabriel minus baseline, verified success per task)


## Retained failures and false completions

none

Scoped comparison on one synthetic task distribution with one provider; a difference here is not a general superiority claim. Costs include every attempt, including failed and timed-out runs.
