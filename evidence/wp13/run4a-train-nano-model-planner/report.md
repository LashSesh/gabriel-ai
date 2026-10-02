# G1 matched evaluation report

Protocol `21838d1897632ed7` (frozen 2026-10-02T21:23:23.995232+00:00), provider `openai_compat` model `gpt-4.1-nano`, backend `linux_namespace`, 6 tasks in 2 families, 18 runs.

Protocol 4a (G3 route, training) with a weaker provider: gpt-4.1-mini solved every hard training task on its first attempt under protocol 4a-mini (18/18, no repair round, no router decision), so no readout could be trained from it; that run is retained under run4a-train-mini-saturated. This protocol runs the rule-based Gabriel with gpt-4.1-nano on the training families multi_file and trap, three repetitions, to collect router decisions at the failed-verification boundary labeled by the independent verification, and episodes for the frozen seed. The stateful family stays held out for protocol 4b.

## All tasks

| system | runs | verified | p_success | CI95 (families) | declared | false completions | cond. FC | mean requests | mean tokens | mean wall s | recovery |
|---|---|---|---|---|---|---|---|---|---|---|---|
| gabriel | 18 | 7 | 0.39 | [0.22, 0.56] | 7 | 0 | 0.00 (n=7) | 2.17 | 2339 | 8.3 | 1 |

## Paired differences, all tasks (gabriel minus baseline, verified success per task)


## Retained failures and false completions

- mf-config / gabriel / rep 0: declared=False verified=False; run state blocked; oracle exit 1, visible exit 0, out of scope []; provider ['invalid_output', 'invalid_output']
- mf-config / gabriel / rep 1: declared=False verified=False; run state blocked; oracle exit 1, visible exit 0, out of scope []; provider ['invalid_output', 'invalid_output']
- mf-config / gabriel / rep 2: declared=False verified=False; run state blocked; oracle exit 1, visible exit 0, out of scope []; provider ['invalid_output', 'invalid_output']
- mf-money / gabriel / rep 1: declared=False verified=False; run state blocked; oracle exit 1, visible exit 0, out of scope []; provider ['invalid_output', 'invalid_output']
- mf-money / gabriel / rep 2: declared=False verified=False; run state blocked; oracle exit 1, visible exit 0, out of scope []; provider ['invalid_output', 'invalid_output']
- mf-paths / gabriel / rep 0: declared=False verified=False; run state blocked; oracle exit 1, visible exit 0, out of scope []; provider ['invalid_output', 'invalid_output']
- mf-paths / gabriel / rep 1: declared=False verified=False; run state blocked; oracle exit 1, visible exit 0, out of scope []; provider ['invalid_output', 'invalid_output']
- tr-interval / gabriel / rep 0: declared=False verified=False; run state blocked; oracle exit 1, visible exit 0, out of scope []; provider ['invalid_output', 'invalid_output']
- tr-interval / gabriel / rep 1: declared=False verified=False; run state blocked; oracle exit 1, visible exit 0, out of scope []; provider ['invalid_output', 'invalid_output']
- tr-interval / gabriel / rep 2: declared=False verified=False; run state blocked; oracle exit 1, visible exit 0, out of scope []; provider ['invalid_output', 'invalid_output']
- tr-version / gabriel / rep 2: declared=False verified=False; run state blocked; oracle exit 1, visible exit 0, out of scope []; provider ['invalid_output', 'invalid_output']

Scoped comparison on one synthetic task distribution with one provider; a difference here is not a general superiority claim. Costs include every attempt, including failed and timed-out runs.
