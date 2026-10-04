# G1 matched evaluation report

Protocol `1e98e2ee24de833b` (frozen 2026-10-04T18:31:05.244572+00:00), provider `openai_compat` model `gpt-4.1-mini`, backend `linux_namespace`, 19 tasks in 7 families, 76 runs.

protocol 10b (evaluation): the frozen numerical readout candidate against the rule-based production configuration on the whole numerical tier, two held-out families never executed before (evidence/wp17/protocol10_declaration.md)

## All tasks

| system | runs | verified | p_success | CI95 (families) | declared | false completions | cond. FC | mean requests | mean tokens | mean wall s | recovery |
|---|---|---|---|---|---|---|---|---|---|---|---|
| gabriel_reference_plan | 38 | 28 | 0.74 | [0.37, 1.00] | 28 | 0 | 0.00 (n=28) | 1.68 | 1514 | 6.0 | 16 |
| gabriel_policy | 38 | 27 | 0.71 | [0.35, 0.98] | 27 | 0 | 0.00 (n=27) | 1.24 | 1053 | 4.0 | 17 |

## Held-out families only (numerical-prerequisite-held-out, numerical-undeclared-held-out): never run before this protocol

| system | runs | verified | p_success | CI95 (families) | declared | false completions | cond. FC | mean requests | mean tokens | mean wall s | recovery |
|---|---|---|---|---|---|---|---|---|---|---|---|
| gabriel_reference_plan | 8 | 4 | 0.50 | [0.00, 1.00] | 4 | 0 | 0.00 (n=4) | 2.50 | 2357 | 8.7 | 8 |
| gabriel_policy | 8 | 4 | 0.50 | [0.00, 1.00] | 4 | 0 | 0.00 (n=4) | 1.50 | 1329 | 4.8 | 8 |

## Previously seen tasks only (not a held-out test)

| system | runs | verified | p_success | CI95 (families) | declared | false completions | cond. FC | mean requests | mean tokens | mean wall s | recovery |
|---|---|---|---|---|---|---|---|---|---|---|---|
| gabriel_reference_plan | 30 | 24 | 0.80 | [0.40, 1.00] | 24 | 0 | 0.00 (n=24) | 1.47 | 1290 | 5.2 | 8 |
| gabriel_policy | 30 | 23 | 0.77 | [0.37, 1.00] | 23 | 0 | 0.00 (n=23) | 1.17 | 980 | 3.8 | 9 |

## Paired differences, all tasks (treatment minus baseline per task: verified success; mean model tokens and requests)

- gabriel_policy_minus_gabriel_reference_plan: success mean -0.03, CI95 by family [-0.08, +0.00], by task [-0.08, +0.00]; tokens -461, requests -0.45; per task: nd-centimetres +0.0, nd-fahrenheit +0.0, nd-kelvin +0.0, nd-millimetres +0.0, nd-millis -0.5, ng-cycle +0.0, ng-path +0.0, ng-star +0.0, np-null +0.0, np-pair +0.0, np-rankine +0.0, np-stamp +0.0, np-text +0.0, nr-five +0.0, nr-hour +0.0, nr-second +0.0, nu-celsius +0.0, nu-kelvin +0.0, nu-metres +0.0

## Retained failures and false completions

- nd-millis / gabriel_policy / rep 1: declared=False verified=False; run state failed; problems output out/converted.json is absent, out of scope []; provider ['completed', 'completed', 'completed', 'completed']
- np-null / gabriel_policy / rep 0: declared=False verified=False; run state failed; problems output out/converted.json is absent, out of scope []; provider ['completed']
- np-null / gabriel_policy / rep 1: declared=False verified=False; run state failed; problems output out/converted.json is absent, out of scope []; provider ['completed']
- np-null / gabriel_reference_plan / rep 0: declared=False verified=False; run state failed; problems output out/converted.json is absent, out of scope []; provider ['completed', 'completed', 'completed']
- np-null / gabriel_reference_plan / rep 1: declared=False verified=False; run state failed; problems output out/converted.json is absent, out of scope []; provider ['completed', 'completed', 'completed']
- np-pair / gabriel_policy / rep 0: declared=False verified=False; run state failed; problems output out/converted.json is absent, out of scope []; provider ['completed']
- np-pair / gabriel_policy / rep 1: declared=False verified=False; run state failed; problems output out/converted.json is absent, out of scope []; provider ['completed']
- np-pair / gabriel_reference_plan / rep 0: declared=False verified=False; run state failed; problems output out/converted.json is absent, out of scope []; provider ['completed', 'completed', 'completed']
- np-pair / gabriel_reference_plan / rep 1: declared=False verified=False; run state failed; problems output out/converted.json is absent, out of scope []; provider ['completed', 'completed', 'completed']
- np-rankine / gabriel_policy / rep 0: declared=False verified=False; run state failed; problems output out/converted.json is absent, out of scope []; provider ['completed']
- np-rankine / gabriel_policy / rep 1: declared=False verified=False; run state failed; problems output out/converted.json is absent, out of scope []; provider ['completed']
- np-rankine / gabriel_reference_plan / rep 0: declared=False verified=False; run state failed; problems output out/converted.json is absent, out of scope []; provider ['completed', 'completed', 'completed']
- np-rankine / gabriel_reference_plan / rep 1: declared=False verified=False; run state failed; problems output out/converted.json is absent, out of scope []; provider ['completed', 'completed', 'completed']
- np-stamp / gabriel_policy / rep 0: declared=False verified=False; run state failed; problems output out/resampled.json is absent, out of scope []; provider ['completed']
- np-stamp / gabriel_policy / rep 1: declared=False verified=False; run state failed; problems output out/resampled.json is absent, out of scope []; provider ['completed']
- np-stamp / gabriel_reference_plan / rep 0: declared=False verified=False; run state failed; problems output out/resampled.json is absent, out of scope []; provider ['completed', 'completed', 'completed']
- np-stamp / gabriel_reference_plan / rep 1: declared=False verified=False; run state failed; problems output out/resampled.json is absent, out of scope []; provider ['completed', 'completed', 'completed']
- np-text / gabriel_policy / rep 0: declared=False verified=False; run state failed; problems output out/converted.json is absent, out of scope []; provider ['completed']
- np-text / gabriel_policy / rep 1: declared=False verified=False; run state failed; problems output out/converted.json is absent, out of scope []; provider ['completed']
- np-text / gabriel_reference_plan / rep 0: declared=False verified=False; run state failed; problems output out/converted.json is absent, out of scope []; provider ['completed', 'completed', 'completed']
- np-text / gabriel_reference_plan / rep 1: declared=False verified=False; run state failed; problems output out/converted.json is absent, out of scope []; provider ['completed', 'completed', 'completed']

Scoped comparison on one synthetic task distribution with one provider; a difference here is not a general superiority claim. Costs include every attempt, including failed and timed-out runs.
