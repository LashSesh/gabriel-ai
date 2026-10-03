# G1 matched evaluation report

Protocol `65f0fd0af67ddb57` (frozen 2026-10-03T16:55:34.157892+00:00), provider `openai_compat` model `gpt-5-mini`, backend `linux_namespace`, 3 tasks in 3 families, 6 runs.

Pilot 9: feasibility of the gpt-5-mini configuration on three document tasks; declared in evidence/wp15/protocol9_declaration.md; retained, not counted

## All tasks

| system | runs | verified | p_success | CI95 (families) | declared | false completions | cond. FC | mean requests | mean tokens | mean wall s | recovery |
|---|---|---|---|---|---|---|---|---|---|---|---|
| gabriel_associative | 3 | 2 | 0.67 | [0.00, 1.00] | 2 | 0 | 0.00 (n=2) | 1.67 | 6856 | 21.5 | 1 |
| gabriel_policy | 3 | 2 | 0.67 | [0.00, 1.00] | 2 | 0 | 0.00 (n=2) | 1.00 | 3842 | 12.4 | 1 |

## Paired differences, all tasks (treatment minus baseline per task: verified success; mean model tokens and requests)

- gabriel_policy_minus_gabriel_associative: success mean +0.00, CI95 by family [+0.00, +0.00], by task [+0.00, +0.00]; tokens -3014, requests -0.67; per task: da-fee +0.0, dc-fee +0.0, du-fee +0.0

## Retained failures and false completions

- dc-fee / gabriel_associative / rep 0: declared=False verified=False; run state failed; problems required statement missing: 120 EUR | 120; required statement not cited from annex with 'one hundred twenty (120) EUR', out of scope []; provider ['completed', 'completed', 'completed']
- dc-fee / gabriel_policy / rep 0: declared=False verified=False; run state failed; problems required statement missing: 120 EUR | 120; required statement not cited from annex with 'one hundred twenty (120) EUR', out of scope []; provider ['completed']

Scoped comparison on one synthetic task distribution with one provider; a difference here is not a general superiority claim. Costs include every attempt, including failed and timed-out runs.
