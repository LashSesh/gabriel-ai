# G1 matched evaluation report

Protocol `02a19b822b59b13a` (frozen 2026-10-03T15:45:13.816103+00:00), provider `openai_compat` model `gpt-4.1-mini`, backend `linux_namespace`, 9 tasks in 3 families, 54 runs.

Protocol 8a (training): retained router decisions of the production configuration and the unlabeled control on the three training topics, rule-based policy; declared in evidence/wp15/protocol8_declaration.md

## All tasks

| system | runs | verified | p_success | CI95 (families) | declared | false completions | cond. FC | mean requests | mean tokens | mean wall s | recovery |
|---|---|---|---|---|---|---|---|---|---|---|---|
| gabriel_associative | 27 | 18 | 0.67 | [0.00, 1.00] | 18 | 0 | 0.00 (n=18) | 1.70 | 5056 | 8.0 | 10 |
| gabriel_associative_unlabeled | 27 | 16 | 0.59 | [0.00, 1.00] | 16 | 0 | 0.00 (n=16) | 2.15 | 6411 | 9.7 | 18 |

## Paired differences, all tasks (treatment minus baseline per task: verified success; mean model tokens and requests)


## Retained failures and false completions

- dc-archive / gabriel_associative / rep 0: declared=False verified=False; run state failed; problems required statement not cited from schedule with 'eleven calendar years', out of scope []; provider ['completed', 'completed', 'completed']
- dc-archive / gabriel_associative / rep 1: declared=False verified=False; run state failed; problems required statement missing: eleven | 11 years | eleven years; required statement not cited from schedule with 'eleven calendar years', out of scope []; provider ['completed', 'completed', 'completed']
- dc-archive / gabriel_associative / rep 2: declared=False verified=False; run state failed; problems required statement missing: eleven | 11 years | eleven years; required statement not cited from schedule with 'eleven calendar years', out of scope []; provider ['completed', 'completed', 'completed']
- dc-archive / gabriel_associative_unlabeled / rep 0: declared=False verified=False; run state failed; problems required statement missing: eleven | 11 years | eleven years; required statement not cited from schedule with 'eleven calendar years', out of scope []; provider ['completed', 'completed', 'completed']
- dc-archive / gabriel_associative_unlabeled / rep 1: declared=False verified=False; run state failed; problems required statement missing: eleven | 11 years | eleven years; required statement not cited from schedule with 'eleven calendar years', out of scope []; provider ['completed', 'completed', 'completed']
- dc-archive / gabriel_associative_unlabeled / rep 2: declared=False verified=False; run state failed; problems required statement missing: eleven | 11 years | eleven years; required statement not cited from schedule with 'eleven calendar years', out of scope []; provider ['completed', 'completed', 'completed']
- dc-fee / gabriel_associative / rep 0: declared=False verified=False; run state failed; problems required statement missing: 120 EUR | 120; required statement not cited from annex with 'one hundred twenty (120) EUR', out of scope []; provider ['completed', 'completed', 'completed']
- dc-fee / gabriel_associative / rep 1: declared=False verified=False; run state failed; problems required statement missing: 120 EUR | 120; required statement not cited from annex with 'one hundred twenty (120) EUR', out of scope []; provider ['completed', 'completed', 'completed']
- dc-fee / gabriel_associative / rep 2: declared=False verified=False; run state failed; problems required statement missing: 120 EUR | 120; required statement not cited from annex with 'one hundred twenty (120) EUR', out of scope []; provider ['completed', 'completed', 'completed']
- dc-fee / gabriel_associative_unlabeled / rep 0: declared=False verified=False; run state failed; problems required statement missing: 120 EUR | 120; required statement not cited from annex with 'one hundred twenty (120) EUR', out of scope []; provider ['completed', 'completed', 'completed']
- dc-fee / gabriel_associative_unlabeled / rep 1: declared=False verified=False; run state failed; problems required statement missing: 120 EUR | 120; required statement not cited from annex with 'one hundred twenty (120) EUR', out of scope []; provider ['completed', 'completed', 'completed']
- dc-fee / gabriel_associative_unlabeled / rep 2: declared=False verified=False; run state failed; problems required statement missing: 120 EUR | 120; required statement not cited from annex with 'one hundred twenty (120) EUR', out of scope []; provider ['completed', 'invalid_output', 'completed', 'completed']
- dc-parking / gabriel_associative / rep 0: declared=False verified=False; run state failed; problems required statement missing: twelve through thirty | 12 through 30 | bays 12; required statement not cited from appendix with 'Bays twelve through thirty', out of scope []; provider ['completed', 'completed', 'completed']
- dc-parking / gabriel_associative / rep 1: declared=False verified=False; run state failed; problems required statement missing: twelve through thirty | 12 through 30 | bays 12; required statement not cited from appendix with 'Bays twelve through thirty', out of scope []; provider ['completed', 'completed', 'completed']
- dc-parking / gabriel_associative / rep 2: declared=False verified=False; run state failed; problems required statement missing: twelve through thirty | 12 through 30 | bays 12; required statement not cited from appendix with 'Bays twelve through thirty', out of scope []; provider ['completed', 'completed', 'completed']
- dc-parking / gabriel_associative_unlabeled / rep 0: declared=False verified=False; run state failed; problems required statement missing: twelve through thirty | 12 through 30 | bays 12; required statement not cited from appendix with 'Bays twelve through thirty', out of scope []; provider ['completed', 'completed', 'completed']
- dc-parking / gabriel_associative_unlabeled / rep 1: declared=False verified=False; run state failed; problems required statement missing: twelve through thirty | 12 through 30 | bays 12; required statement not cited from appendix with 'Bays twelve through thirty', out of scope []; provider ['completed', 'invalid_output', 'completed', 'completed']
- dc-parking / gabriel_associative_unlabeled / rep 2: declared=False verified=False; run state failed; problems required statement missing: twelve through thirty | 12 through 30 | bays 12; required statement not cited from appendix with 'Bays twelve through thirty', out of scope []; provider ['completed', 'completed', 'completed']
- du-archive / gabriel_associative_unlabeled / rep 1: declared=False verified=False; run state failed; problems forbidden statement present in doc/summary.md: eleven, out of scope []; provider ['completed', 'completed', 'completed']
- du-archive / gabriel_associative_unlabeled / rep 2: declared=False verified=False; run state failed; problems forbidden statement present in doc/summary.md: eleven, out of scope []; provider ['completed', 'completed', 'completed']

Scoped comparison on one synthetic task distribution with one provider; a difference here is not a general superiority claim. Costs include every attempt, including failed and timed-out runs.
