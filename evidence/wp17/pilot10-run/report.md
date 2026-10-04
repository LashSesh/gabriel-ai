# G1 matched evaluation report

Protocol `af3857f7a762c42d` (frozen 2026-10-04T18:26:32.082551+00:00), provider `openai_compat` model `gpt-4.1-mini`, backend `linux_namespace`, 6 tasks in 2 families, 6 runs.

protocol 10 pilot: feasibility of the decision classes on the seen topics only (evidence/wp17/protocol10_declaration.md); retained, not counted

## All tasks

| system | runs | verified | p_success | CI95 (families) | declared | false completions | cond. FC | mean requests | mean tokens | mean wall s | recovery |
|---|---|---|---|---|---|---|---|---|---|---|---|
| gabriel_reference_plan | 6 | 1 | 0.17 | [0.00, 0.33] | 1 | 0 | 0.00 (n=1) | 2.83 | 2754 | 10.8 | 6 |

## Paired differences, all tasks (treatment minus baseline per task: verified success; mean model tokens and requests)


## Retained failures and false completions

- nd-centimetres / gabriel_reference_plan / rep 0: declared=False verified=False; run state failed; problems output units 'km' differ from the reference 'cm'; maximum deviation 999990.0 exceeds tolerance 1e-06, out of scope []; provider ['completed', 'completed', 'completed']
- nd-millis / gabriel_reference_plan / rep 0: declared=False verified=False; run state failed; problems output out/converted.json is absent, out of scope []; provider ['completed', 'completed', 'completed']
- np-null / gabriel_reference_plan / rep 0: declared=False verified=False; run state failed; problems output out/converted.json is absent, out of scope []; provider ['completed', 'completed', 'completed']
- np-pair / gabriel_reference_plan / rep 0: declared=False verified=False; run state failed; problems output out/converted.json is absent, out of scope []; provider ['completed', 'completed', 'completed']
- np-stamp / gabriel_reference_plan / rep 0: declared=False verified=False; run state failed; problems output out/resampled.json is absent, out of scope []; provider ['completed', 'completed', 'completed']

Scoped comparison on one synthetic task distribution with one provider; a difference here is not a general superiority claim. Costs include every attempt, including failed and timed-out runs.
