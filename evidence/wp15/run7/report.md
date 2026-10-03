# G1 matched evaluation report

Protocol `ce24ada60661ffd8` (frozen 2026-10-03T15:19:55.338652+00:00), provider `openai_compat` model `gpt-4.1-mini`, backend `linux_namespace`, 10 tasks in 4 families, 60 runs.

Protocol 7: association provenance in the prompt (ADR-21); declared in evidence/wp15/protocol7_declaration.md; history tasks run first in the same workspace for every Gabriel arm

## All tasks

| system | runs | verified | p_success | CI95 (families) | declared | false completions | cond. FC | mean requests | mean tokens | mean wall s | recovery |
|---|---|---|---|---|---|---|---|---|---|---|---|
| gabriel_reference_plan | 20 | 10 | 0.50 | [0.00, 1.00] | 10 | 0 | 0.00 (n=10) | 2.00 | 5582 | 9.3 | 10 |
| gabriel_associative | 20 | 20 | 1.00 | [1.00, 1.00] | 20 | 0 | 0.00 (n=20) | 1.20 | 3104 | 5.7 | 2 |
| gabriel_associative_unlabeled | 20 | 18 | 0.90 | [0.73, 1.00] | 18 | 0 | 0.00 (n=18) | 1.40 | 3661 | 6.8 | 6 |

## Held-out families only (association-needed-held-out): never run before this protocol

| system | runs | verified | p_success | CI95 (families) | declared | false completions | cond. FC | mean requests | mean tokens | mean wall s | recovery |
|---|---|---|---|---|---|---|---|---|---|---|---|
| gabriel_reference_plan | 4 | 0 | 0.00 | [0.00, 0.00] | 0 | 0 | n/a (0 declared) | 3.00 | 9147 | 13.1 | 4 |
| gabriel_associative | 4 | 4 | 1.00 | [1.00, 1.00] | 4 | 0 | 0.00 (n=4) | 1.00 | 2911 | 5.1 | 0 |
| gabriel_associative_unlabeled | 4 | 4 | 1.00 | [1.00, 1.00] | 4 | 0 | 0.00 (n=4) | 1.00 | 2838 | 5.5 | 0 |

## Previously seen tasks only (not a held-out test)

| system | runs | verified | p_success | CI95 (families) | declared | false completions | cond. FC | mean requests | mean tokens | mean wall s | recovery |
|---|---|---|---|---|---|---|---|---|---|---|---|
| gabriel_reference_plan | 16 | 10 | 0.62 | [0.00, 1.00] | 10 | 0 | 0.00 (n=10) | 1.75 | 4691 | 8.3 | 6 |
| gabriel_associative | 16 | 16 | 1.00 | [1.00, 1.00] | 16 | 0 | 0.00 (n=16) | 1.25 | 3153 | 5.8 | 2 |
| gabriel_associative_unlabeled | 16 | 14 | 0.88 | [0.67, 1.00] | 14 | 0 | 0.00 (n=14) | 1.50 | 3867 | 7.2 | 6 |

## Paired differences, all tasks (treatment minus baseline per task: verified success; mean model tokens and requests)

- gabriel_reference_plan_minus_gabriel_associative: success mean -0.50, CI95 by family [-1.00, +0.00], by task [-0.80, -0.20]; tokens +2478, requests +0.80; per task: da-archive -1.0, da-fee -1.0, da-garden -1.0, da-library -1.0, da-parking -1.0, dn-fee +0.0, dn-parking +0.0, du-archive +0.0, du-fee +0.0, du-parking +0.0
- gabriel_reference_plan_minus_gabriel_associative_unlabeled: success mean -0.40, CI95 by family [-1.00, +0.20], by task [-0.80, +0.00]; tokens +1921, requests +0.60; per task: da-archive -1.0, da-fee -1.0, da-garden -1.0, da-library -1.0, da-parking -1.0, dn-fee +0.0, dn-parking +0.0, du-archive +1.0, du-fee +0.0, du-parking +0.0

## Retained failures and false completions

- da-archive / gabriel_reference_plan / rep 0: declared=False verified=False; run state failed; problems required statement missing: eleven | 11 years | eleven years; required statement not cited from schedule with 'eleven calendar years', out of scope []; provider ['completed', 'completed', 'completed']
- da-archive / gabriel_reference_plan / rep 1: declared=False verified=False; run state failed; problems required statement missing: eleven | 11 years | eleven years; required statement not cited from schedule with 'eleven calendar years', out of scope []; provider ['completed', 'completed', 'completed']
- da-fee / gabriel_reference_plan / rep 0: declared=False verified=False; run state failed; problems required statement missing: 120 EUR | 120; required statement not cited from annex with 'one hundred twenty (120) EUR', out of scope []; provider ['completed', 'completed', 'completed']
- da-fee / gabriel_reference_plan / rep 1: declared=False verified=False; run state failed; problems required statement not cited from annex with 'one hundred twenty (120) EUR', out of scope []; provider ['completed', 'completed', 'completed']
- da-garden / gabriel_reference_plan / rep 0: declared=False verified=False; run state failed; problems required statement not cited from register with 'forty square metres', out of scope []; provider ['completed', 'completed', 'completed']
- da-garden / gabriel_reference_plan / rep 1: declared=False verified=False; run state failed; problems required statement not cited from register with 'forty square metres', out of scope []; provider ['completed', 'completed', 'completed']
- da-library / gabriel_reference_plan / rep 0: declared=False verified=False; run state failed; problems required statement not cited from table with 'twenty-one days', out of scope []; provider ['completed', 'completed', 'completed']
- da-library / gabriel_reference_plan / rep 1: declared=False verified=False; run state failed; problems doc/summary.md: quote 'Members may keep books for a period of twenty-one days.' is not a verbatim span of any available source; required statement not cited from table with 'twenty-one days', out of scope []; provider ['completed', 'completed', 'completed']
- da-parking / gabriel_reference_plan / rep 0: declared=False verified=False; run state failed; problems required statement missing: twelve through thirty | 12 through 30 | bays 12; required statement not cited from appendix with 'Bays twelve through thirty', out of scope []; provider ['completed', 'completed', 'completed']
- da-parking / gabriel_reference_plan / rep 1: declared=False verified=False; run state failed; problems required statement missing: twelve through thirty | 12 through 30 | bays 12; required statement not cited from appendix with 'Bays twelve through thirty', out of scope []; provider ['completed', 'completed', 'completed']
- du-archive / gabriel_associative_unlabeled / rep 0: declared=False verified=False; run state failed; problems forbidden statement present in doc/summary.md: eleven, out of scope []; provider ['completed', 'completed', 'completed']
- du-archive / gabriel_associative_unlabeled / rep 1: declared=False verified=False; run state failed; problems forbidden statement present in doc/summary.md: eleven, out of scope []; provider ['completed', 'completed', 'completed']

Scoped comparison on one synthetic task distribution with one provider; a difference here is not a general superiority claim. Costs include every attempt, including failed and timed-out runs.
