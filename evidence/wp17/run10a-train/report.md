# G1 matched evaluation report

Protocol `e3af389493401b16` (frozen 2026-10-04T18:29:03.270133+00:00), provider `openai_compat` model `gpt-4.1-mini`, backend `linux_namespace`, 6 tasks in 2 families, 18 runs.

protocol 10a (training): retained decisions of the numerical pack's production configuration on the seen decision topics (evidence/wp17/protocol10_declaration.md)

## All tasks

| system | runs | verified | p_success | CI95 (families) | declared | false completions | cond. FC | mean requests | mean tokens | mean wall s | recovery |
|---|---|---|---|---|---|---|---|---|---|---|---|
| gabriel_reference_plan | 18 | 9 | 0.50 | [0.00, 1.00] | 9 | 0 | 0.00 (n=9) | 2.11 | 1980 | 8.3 | 11 |

## Paired differences, all tasks (treatment minus baseline per task: verified success; mean model tokens and requests)


## Retained failures and false completions

- np-null / gabriel_reference_plan / rep 0: declared=False verified=False; run state failed; problems output out/converted.json is absent, out of scope []; provider ['completed', 'completed', 'completed']
- np-null / gabriel_reference_plan / rep 1: declared=False verified=False; run state failed; problems output out/converted.json is absent, out of scope []; provider ['completed', 'completed', 'completed']
- np-null / gabriel_reference_plan / rep 2: declared=False verified=False; run state failed; problems output out/converted.json is absent, out of scope []; provider ['completed', 'completed', 'completed']
- np-pair / gabriel_reference_plan / rep 0: declared=False verified=False; run state failed; problems output out/converted.json is absent, out of scope []; provider ['completed', 'completed', 'completed']
- np-pair / gabriel_reference_plan / rep 1: declared=False verified=False; run state failed; problems output out/converted.json is absent, out of scope []; provider ['completed', 'completed', 'completed']
- np-pair / gabriel_reference_plan / rep 2: declared=False verified=False; run state failed; problems output out/converted.json is absent, out of scope []; provider ['completed', 'completed', 'completed']
- np-stamp / gabriel_reference_plan / rep 0: declared=False verified=False; run state failed; problems output out/resampled.json is absent, out of scope []; provider ['completed', 'completed', 'completed']
- np-stamp / gabriel_reference_plan / rep 1: declared=False verified=False; run state failed; problems output out/resampled.json is absent, out of scope []; provider ['completed', 'completed', 'completed']
- np-stamp / gabriel_reference_plan / rep 2: declared=False verified=False; run state failed; problems output out/resampled.json is absent, out of scope []; provider ['completed', 'completed', 'completed']

Scoped comparison on one synthetic task distribution with one provider; a difference here is not a general superiority claim. Costs include every attempt, including failed and timed-out runs.
