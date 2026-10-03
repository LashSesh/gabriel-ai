# G1 matched evaluation report

Protocol `5563390ac05e9a88` (frozen 2026-10-03T15:49:14.314214+00:00), provider `openai_compat` model `gpt-4.1-mini`, backend `linux_namespace`, 15 tasks in 6 families, 90 runs.

Protocol 8b (evaluation): the readout trained under protocol 8a (channels, evidence/wp15/policies8) pinned on the production configuration against the rule-based production configuration and the provenance reference; declared in evidence/wp15/protocol8_declaration.md

## All tasks

| system | runs | verified | p_success | CI95 (families) | declared | false completions | cond. FC | mean requests | mean tokens | mean wall s | recovery |
|---|---|---|---|---|---|---|---|---|---|---|---|
| gabriel_associative | 30 | 20 | 0.67 | [0.29, 1.00] | 20 | 0 | 0.00 (n=20) | 1.80 | 5346 | 8.6 | 14 |
| gabriel_policy | 30 | 19 | 0.63 | [0.27, 0.97] | 19 | 0 | 0.00 (n=19) | 1.03 | 2946 | 5.4 | 11 |
| gabriel_reference_plan | 30 | 10 | 0.33 | [0.00, 0.71] | 10 | 0 | 0.00 (n=10) | 2.40 | 7230 | 10.9 | 20 |

## Held-out families only (association-needed-cold-held-out, association-needed-held-out, association-unneeded-held-out): never run before this protocol

| system | runs | verified | p_success | CI95 (families) | declared | false completions | cond. FC | mean requests | mean tokens | mean wall s | recovery |
|---|---|---|---|---|---|---|---|---|---|---|---|
| gabriel_associative | 12 | 8 | 0.67 | [0.00, 1.00] | 8 | 0 | 0.00 (n=8) | 1.83 | 5425 | 8.4 | 6 |
| gabriel_policy | 12 | 8 | 0.67 | [0.00, 1.00] | 8 | 0 | 0.00 (n=8) | 1.00 | 2836 | 5.4 | 4 |
| gabriel_reference_plan | 12 | 4 | 0.33 | [0.00, 1.00] | 4 | 0 | 0.00 (n=4) | 2.50 | 7530 | 11.0 | 8 |

## Previously seen tasks only (not a held-out test)

| system | runs | verified | p_success | CI95 (families) | declared | false completions | cond. FC | mean requests | mean tokens | mean wall s | recovery |
|---|---|---|---|---|---|---|---|---|---|---|---|
| gabriel_associative | 18 | 12 | 0.67 | [0.00, 1.00] | 12 | 0 | 0.00 (n=12) | 1.78 | 5294 | 8.8 | 8 |
| gabriel_policy | 18 | 11 | 0.61 | [0.00, 1.00] | 11 | 0 | 0.00 (n=11) | 1.06 | 3018 | 5.4 | 7 |
| gabriel_reference_plan | 18 | 6 | 0.33 | [0.00, 1.00] | 6 | 0 | 0.00 (n=6) | 2.33 | 7030 | 10.8 | 12 |

## Paired differences, all tasks (treatment minus baseline per task: verified success; mean model tokens and requests)

- gabriel_policy_minus_gabriel_associative: success mean -0.03, CI95 by family [-0.09, +0.00], by task [-0.10, +0.00]; tokens -2401, requests -0.77; per task: da-archive +0.0, da-fee -0.5, da-garden +0.0, da-library +0.0, da-parking +0.0, dc-archive +0.0, dc-fee +0.0, dc-garden +0.0, dc-library +0.0, dc-parking +0.0, du-archive +0.0, du-fee +0.0, du-garden +0.0, du-library +0.0, du-parking +0.0
- gabriel_policy_minus_gabriel_reference_plan: success mean +0.30, CI95 by family [+0.00, +0.63], by task [+0.10, +0.53]; tokens -4284, requests -1.37; per task: da-archive +1.0, da-fee +0.5, da-garden +1.0, da-library +1.0, da-parking +1.0, dc-archive +0.0, dc-fee +0.0, dc-garden +0.0, dc-library +0.0, dc-parking +0.0, du-archive +0.0, du-fee +0.0, du-garden +0.0, du-library +0.0, du-parking +0.0

## Retained failures and false completions

- da-archive / gabriel_reference_plan / rep 0: declared=False verified=False; run state failed; problems required statement missing: eleven | 11 years | eleven years; required statement not cited from schedule with 'eleven calendar years', out of scope []; provider ['completed', 'completed', 'completed']
- da-archive / gabriel_reference_plan / rep 1: declared=False verified=False; run state failed; problems required statement missing: eleven | 11 years | eleven years; required statement not cited from schedule with 'eleven calendar years', out of scope []; provider ['completed', 'completed', 'completed']
- da-fee / gabriel_policy / rep 1: declared=False verified=False; run state failed; problems required statement missing: 120 EUR | 120; required statement not cited from annex with 'one hundred twenty (120) EUR', out of scope []; provider ['invalid_output', 'completed']
- da-fee / gabriel_reference_plan / rep 0: declared=False verified=False; run state failed; problems required statement missing: 120 EUR | 120; required statement not cited from annex with 'one hundred twenty (120) EUR', out of scope []; provider ['completed', 'completed', 'completed']
- da-fee / gabriel_reference_plan / rep 1: declared=False verified=False; run state failed; problems required statement missing: 120 EUR | 120; required statement not cited from annex with 'one hundred twenty (120) EUR', out of scope []; provider ['completed', 'completed', 'completed']
- da-garden / gabriel_reference_plan / rep 0: declared=False verified=False; run state failed; problems doc/summary.md: quote 'Each plot is forty square metres in size.' is not a verbatim span of any available source; required statement not cited from register with 'forty square metres', out of scope []; provider ['completed', 'completed', 'completed']
- da-garden / gabriel_reference_plan / rep 1: declared=False verified=False; run state failed; problems required statement not cited from register with 'forty square metres', out of scope []; provider ['completed', 'completed', 'completed']
- da-library / gabriel_reference_plan / rep 0: declared=False verified=False; run state failed; problems required statement not cited from table with 'twenty-one days', out of scope []; provider ['completed', 'completed', 'completed']
- da-library / gabriel_reference_plan / rep 1: declared=False verified=False; run state failed; problems required statement missing: twenty-one days | 21 days; required statement not cited from table with 'twenty-one days', out of scope []; provider ['completed', 'completed', 'completed']
- da-parking / gabriel_reference_plan / rep 0: declared=False verified=False; run state failed; problems required statement missing: twelve through thirty | 12 through 30 | bays 12; required statement not cited from appendix with 'Bays twelve through thirty', out of scope []; provider ['completed', 'completed', 'completed']
- da-parking / gabriel_reference_plan / rep 1: declared=False verified=False; run state failed; problems required statement missing: twelve through thirty | 12 through 30 | bays 12; required statement not cited from appendix with 'Bays twelve through thirty', out of scope []; provider ['completed', 'completed', 'completed']
- dc-archive / gabriel_associative / rep 0: declared=False verified=False; run state failed; problems required statement missing: eleven | 11 years | eleven years; required statement not cited from schedule with 'eleven calendar years', out of scope []; provider ['completed', 'completed', 'completed']
- dc-archive / gabriel_associative / rep 1: declared=False verified=False; run state failed; problems required statement missing: eleven | 11 years | eleven years; required statement not cited from schedule with 'eleven calendar years', out of scope []; provider ['completed', 'completed', 'completed']
- dc-archive / gabriel_policy / rep 0: declared=False verified=False; run state failed; problems required statement missing: eleven | 11 years | eleven years; required statement not cited from schedule with 'eleven calendar years', out of scope []; provider ['completed']
- dc-archive / gabriel_policy / rep 1: declared=False verified=False; run state failed; problems required statement missing: eleven | 11 years | eleven years; required statement not cited from schedule with 'eleven calendar years', out of scope []; provider ['completed']
- dc-archive / gabriel_reference_plan / rep 0: declared=False verified=False; run state failed; problems required statement missing: eleven | 11 years | eleven years; required statement not cited from schedule with 'eleven calendar years', out of scope []; provider ['completed', 'completed', 'completed']
- dc-archive / gabriel_reference_plan / rep 1: declared=False verified=False; run state failed; problems required statement missing: eleven | 11 years | eleven years; required statement not cited from schedule with 'eleven calendar years', out of scope []; provider ['completed', 'completed', 'completed']
- dc-fee / gabriel_associative / rep 0: declared=False verified=False; run state failed; problems required statement missing: 120 EUR | 120; required statement not cited from annex with 'one hundred twenty (120) EUR', out of scope []; provider ['completed', 'completed', 'completed']
- dc-fee / gabriel_associative / rep 1: declared=False verified=False; run state failed; problems required statement missing: 120 EUR | 120; required statement not cited from annex with 'one hundred twenty (120) EUR', out of scope []; provider ['completed', 'completed', 'completed']
- dc-fee / gabriel_policy / rep 0: declared=False verified=False; run state failed; problems required statement missing: 120 EUR | 120; required statement not cited from annex with 'one hundred twenty (120) EUR', out of scope []; provider ['completed']
- dc-fee / gabriel_policy / rep 1: declared=False verified=False; run state failed; problems required statement missing: 120 EUR | 120; required statement not cited from annex with 'one hundred twenty (120) EUR', out of scope []; provider ['completed']
- dc-fee / gabriel_reference_plan / rep 0: declared=False verified=False; run state failed; problems required statement missing: 120 EUR | 120; required statement not cited from annex with 'one hundred twenty (120) EUR', out of scope []; provider ['completed', 'completed', 'completed']
- dc-fee / gabriel_reference_plan / rep 1: declared=False verified=False; run state failed; problems required statement missing: 120 EUR | 120; required statement not cited from annex with 'one hundred twenty (120) EUR', out of scope []; provider ['completed', 'completed', 'completed']
- dc-garden / gabriel_associative / rep 0: declared=False verified=False; run state failed; problems doc/summary.md: quote 'Each plot is forty square metres in size.' is not a verbatim span of any available source; required statement not cited from register with 'forty square metres', out of scope []; provider ['completed', 'completed', 'completed']
- dc-garden / gabriel_associative / rep 1: declared=False verified=False; run state failed; problems required statement not cited from register with 'forty square metres', out of scope []; provider ['completed', 'completed', 'completed']
- dc-garden / gabriel_policy / rep 0: declared=False verified=False; run state failed; problems required statement missing: forty square metres | 40 square metres | 40 m; required statement not cited from register with 'forty square metres', out of scope []; provider ['completed']
- dc-garden / gabriel_policy / rep 1: declared=False verified=False; run state failed; problems required statement missing: forty square metres | 40 square metres | 40 m; required statement not cited from register with 'forty square metres', out of scope []; provider ['completed']
- dc-garden / gabriel_reference_plan / rep 0: declared=False verified=False; run state failed; problems doc/summary.md: quote 'Each plot is forty square metres in size.' is not a verbatim span of any available source; required statement not cited from register with 'forty square metres', out of scope []; provider ['completed', 'completed', 'completed']
- dc-garden / gabriel_reference_plan / rep 1: declared=False verified=False; run state failed; problems required statement missing: forty square metres | 40 square metres | 40 m; required statement not cited from register with 'forty square metres', out of scope []; provider ['completed', 'completed', 'completed']
- dc-library / gabriel_associative / rep 0: declared=False verified=False; run state failed; problems required statement not cited from table with 'twenty-one days', out of scope []; provider ['completed', 'completed', 'completed']
- dc-library / gabriel_associative / rep 1: declared=False verified=False; run state failed; problems required statement missing: twenty-one days | 21 days; required statement not cited from table with 'twenty-one days', out of scope []; provider ['completed', 'completed', 'completed']
- dc-library / gabriel_policy / rep 0: declared=False verified=False; run state failed; problems required statement missing: twenty-one days | 21 days; required statement not cited from table with 'twenty-one days', out of scope []; provider ['completed']
- dc-library / gabriel_policy / rep 1: declared=False verified=False; run state failed; problems required statement missing: twenty-one days | 21 days; required statement not cited from table with 'twenty-one days', out of scope []; provider ['completed']
- dc-library / gabriel_reference_plan / rep 0: declared=False verified=False; run state failed; problems required statement not cited from table with 'twenty-one days', out of scope []; provider ['completed', 'completed', 'completed']
- dc-library / gabriel_reference_plan / rep 1: declared=False verified=False; run state failed; problems required statement missing: twenty-one days | 21 days; required statement not cited from table with 'twenty-one days', out of scope []; provider ['completed', 'invalid_output', 'completed', 'completed', 'completed']
- dc-parking / gabriel_associative / rep 0: declared=False verified=False; run state failed; problems required statement not cited from appendix with 'Bays twelve through thirty', out of scope []; provider ['completed', 'completed', 'completed']
- dc-parking / gabriel_associative / rep 1: declared=False verified=False; run state failed; problems required statement missing: twelve through thirty | 12 through 30 | bays 12; required statement not cited from appendix with 'Bays twelve through thirty', out of scope []; provider ['completed', 'completed', 'completed']
- dc-parking / gabriel_policy / rep 0: declared=False verified=False; run state failed; problems required statement missing: twelve through thirty | 12 through 30 | bays 12; required statement not cited from appendix with 'Bays twelve through thirty', out of scope []; provider ['completed']
- dc-parking / gabriel_policy / rep 1: declared=False verified=False; run state failed; problems required statement missing: twelve through thirty | 12 through 30 | bays 12; required statement not cited from appendix with 'Bays twelve through thirty', out of scope []; provider ['completed']
- dc-parking / gabriel_reference_plan / rep 0: declared=False verified=False; run state failed; problems required statement missing: twelve through thirty | 12 through 30 | bays 12; required statement not cited from appendix with 'Bays twelve through thirty', out of scope []; provider ['completed', 'completed', 'completed']
- dc-parking / gabriel_reference_plan / rep 1: declared=False verified=False; run state failed; problems required statement missing: twelve through thirty | 12 through 30 | bays 12; required statement not cited from appendix with 'Bays twelve through thirty', out of scope []; provider ['completed', 'completed', 'completed']

Scoped comparison on one synthetic task distribution with one provider; a difference here is not a general superiority claim. Costs include every attempt, including failed and timed-out runs.
