# G1 matched evaluation report

Protocol `74bc6bbac7b518b0` (frozen 2026-10-03T13:39:42.263265+00:00), provider `openai_compat` model `gpt-4.1-mini`, backend `linux_namespace`, 10 tasks in 4 families, 80 runs.

Protocol 6b: the associative memory layer (ADR-20) on the amended association tier; amendment and reasons in evidence/wp15/protocol6_declaration.md; history tasks run first in the same workspace for every Gabriel arm

## All tasks

| system | runs | verified | p_success | CI95 (families) | declared | false completions | cond. FC | mean requests | mean tokens | mean wall s | recovery |
|---|---|---|---|---|---|---|---|---|---|---|---|
| provider_only | 20 | 14 | 0.70 | [0.18, 1.00] | 20 | 6 | 0.30 (n=20) | 1.00 | 2559 | 2.5 | 0 |
| simple_loop | 20 | 19 | 0.95 | [0.86, 1.00] | 19 | 0 | 0.00 (n=19) | 1.70 | 4794 | 3.9 | 0 |
| gabriel_reference_plan | 20 | 10 | 0.50 | [0.00, 1.00] | 10 | 0 | 0.00 (n=10) | 2.00 | 5572 | 8.1 | 10 |
| gabriel_associative | 20 | 18 | 0.90 | [0.73, 1.00] | 18 | 0 | 0.00 (n=18) | 1.40 | 3671 | 6.1 | 6 |

## Held-out families only (association-needed-held-out): never run before this protocol

| system | runs | verified | p_success | CI95 (families) | declared | false completions | cond. FC | mean requests | mean tokens | mean wall s | recovery |
|---|---|---|---|---|---|---|---|---|---|---|---|
| provider_only | 4 | 4 | 1.00 | [1.00, 1.00] | 4 | 0 | 0.00 (n=4) | 1.00 | 2977 | 2.2 | 0 |
| simple_loop | 4 | 4 | 1.00 | [1.00, 1.00] | 4 | 0 | 0.00 (n=4) | 1.00 | 3000 | 2.2 | 0 |
| gabriel_reference_plan | 4 | 0 | 0.00 | [0.00, 0.00] | 0 | 0 | n/a (0 declared) | 3.00 | 9190 | 12.0 | 4 |
| gabriel_associative | 4 | 4 | 1.00 | [1.00, 1.00] | 4 | 0 | 0.00 (n=4) | 1.00 | 2865 | 5.6 | 0 |

## Previously seen tasks only (not a held-out test)

| system | runs | verified | p_success | CI95 (families) | declared | false completions | cond. FC | mean requests | mean tokens | mean wall s | recovery |
|---|---|---|---|---|---|---|---|---|---|---|---|
| provider_only | 16 | 10 | 0.62 | [0.00, 1.00] | 16 | 6 | 0.38 (n=16) | 1.00 | 2455 | 2.6 | 0 |
| simple_loop | 16 | 15 | 0.94 | [0.83, 1.00] | 15 | 0 | 0.00 (n=15) | 1.88 | 5242 | 4.4 | 0 |
| gabriel_reference_plan | 16 | 10 | 0.62 | [0.00, 1.00] | 10 | 0 | 0.00 (n=10) | 1.75 | 4668 | 7.1 | 6 |
| gabriel_associative | 16 | 14 | 0.88 | [0.67, 1.00] | 14 | 0 | 0.00 (n=14) | 1.50 | 3873 | 6.3 | 6 |

## Paired differences, all tasks (treatment minus baseline per task: verified success; mean model tokens and requests)

- gabriel_reference_plan_minus_provider_only: success mean -0.20, CI95 by family [-1.00, +0.64], by task [-0.70, +0.40]; tokens +3013, requests +1.00; per task: da-archive -1.0, da-fee -1.0, da-garden -1.0, da-library -1.0, da-parking -1.0, dn-fee +0.0, dn-parking +0.0, du-archive +1.0, du-fee +1.0, du-parking +1.0
- gabriel_reference_plan_minus_simple_loop: success mean -0.45, CI95 by family [-1.00, +0.10], by task [-0.80, -0.10]; tokens +778, requests +0.30; per task: da-archive -1.0, da-fee -1.0, da-garden -1.0, da-library -1.0, da-parking -1.0, dn-fee +0.0, dn-parking +0.0, du-archive +0.5, du-fee +0.0, du-parking +0.0
- gabriel_reference_plan_minus_gabriel_associative: success mean -0.40, CI95 by family [-1.00, +0.20], by task [-0.80, +0.00]; tokens +1901, requests +0.60; per task: da-archive -1.0, da-fee -1.0, da-garden -1.0, da-library -1.0, da-parking -1.0, dn-fee +0.0, dn-parking +0.0, du-archive +1.0, du-fee +0.0, du-parking +0.0

## Retained failures and false completions

- da-archive / gabriel_reference_plan / rep 0: declared=False verified=False; run state failed; problems required statement missing: eleven | 11 years | eleven years; required statement not cited from schedule with 'eleven calendar years', out of scope []; provider ['completed', 'completed', 'completed']
- da-archive / gabriel_reference_plan / rep 1: declared=False verified=False; run state failed; problems required statement missing: eleven | 11 years | eleven years; required statement not cited from schedule with 'eleven calendar years', out of scope []; provider ['completed', 'completed', 'completed']
- da-fee / gabriel_reference_plan / rep 0: declared=False verified=False; run state failed; problems required statement missing: 120 EUR | 120; required statement not cited from annex with 'one hundred twenty (120) EUR', out of scope []; provider ['completed', 'completed', 'completed']
- da-fee / gabriel_reference_plan / rep 1: declared=False verified=False; run state failed; problems required statement missing: 120 EUR | 120; required statement not cited from annex with 'one hundred twenty (120) EUR', out of scope []; provider ['completed', 'completed', 'completed']
- da-garden / gabriel_reference_plan / rep 0: declared=False verified=False; run state failed; problems required statement not cited from register with 'forty square metres', out of scope []; provider ['completed', 'completed', 'completed']
- da-garden / gabriel_reference_plan / rep 1: declared=False verified=False; run state failed; problems doc/summary.md: quote 'Each plot is forty square metres in size.' is not a verbatim span of any available source; required statement not cited from register with 'forty square metres', out of scope []; provider ['completed', 'completed', 'completed']
- da-library / gabriel_reference_plan / rep 0: declared=False verified=False; run state failed; problems required statement not cited from table with 'twenty-one days', out of scope []; provider ['completed', 'completed', 'completed']
- da-library / gabriel_reference_plan / rep 1: declared=False verified=False; run state failed; problems required statement not cited from table with 'twenty-one days', out of scope []; provider ['completed', 'completed', 'completed']
- da-parking / gabriel_reference_plan / rep 0: declared=False verified=False; run state failed; problems required statement missing: twelve through thirty | 12 through 30 | bays 12; required statement not cited from appendix with 'Bays twelve through thirty', out of scope []; provider ['completed', 'completed', 'completed']
- da-parking / gabriel_reference_plan / rep 1: declared=False verified=False; run state failed; problems doc/summary.md: quote '## Parking\\n\\nVehicles of members are parked according to th' is not a verbatim span of any available source; required statement not cited from appendix with 'Bays twelve through thirty', out of scope []; provider ['completed', 'completed', 'completed']
- du-archive / gabriel_associative / rep 0: declared=False verified=False; run state failed; problems forbidden statement present in doc/summary.md: eleven, out of scope []; provider ['completed', 'completed', 'completed']
- du-archive / gabriel_associative / rep 1: declared=False verified=False; run state failed; problems forbidden statement present in doc/summary.md: eleven, out of scope []; provider ['completed', 'completed', 'completed']
- du-archive / provider_only / rep 0: declared=True verified=False; deliverable produced; declared done without verification; problems forbidden statement present in doc/summary.md: eleven, out of scope []; provider ['completed']
- du-archive / provider_only / rep 1: declared=True verified=False; deliverable produced; declared done without verification; problems forbidden statement present in doc/summary.md: eleven, out of scope []; provider ['completed']
- du-archive / simple_loop / rep 1: declared=False verified=False; budget exhausted without passing checks; problems forbidden statement present in doc/summary.md: eleven, out of scope []; provider ['completed', 'completed', 'completed', 'completed', 'completed', 'completed']
- du-fee / provider_only / rep 0: declared=True verified=False; deliverable produced; declared done without verification; problems forbidden statement present in doc/summary.md: 120, out of scope []; provider ['completed']
- du-fee / provider_only / rep 1: declared=True verified=False; deliverable produced; declared done without verification; problems forbidden statement present in doc/summary.md: 120, out of scope []; provider ['completed']
- du-parking / provider_only / rep 0: declared=True verified=False; deliverable produced; declared done without verification; problems forbidden statement present in doc/summary.md: twelve through thirty, out of scope []; provider ['completed']
- du-parking / provider_only / rep 1: declared=True verified=False; deliverable produced; declared done without verification; problems forbidden statement present in doc/summary.md: twelve through thirty, out of scope []; provider ['completed']

Scoped comparison on one synthetic task distribution with one provider; a difference here is not a general superiority claim. Costs include every attempt, including failed and timed-out runs.
