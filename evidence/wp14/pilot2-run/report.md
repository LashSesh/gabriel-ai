# G1 matched evaluation report

Protocol `48c1a88773d0c846` (frozen 2026-10-02T22:21:00.989284+00:00), provider `openai_compat` model `gpt-4.1-mini`, backend `linux_namespace`, 6 tasks in 2 families, 30 runs.

Protocol 5 pilot 2 on the amended document corpus (status statements removed from the source texts; see evidence/wp14/pilot_declaration.md, amendment after pilot 1). Document families only: the numerical tasks are unchanged since pilot 1. Same declaration of the minimum relevant effect.

## All tasks

| system | runs | verified | p_success | CI95 (families) | declared | false completions | cond. FC | mean requests | mean tokens | mean wall s | recovery |
|---|---|---|---|---|---|---|---|---|---|---|---|
| provider_only | 6 | 5 | 0.83 | [0.67, 1.00] | 6 | 1 | 0.17 (n=6) | 1.00 | 865 | 2.2 | 0 |
| simple_loop | 6 | 6 | 1.00 | [1.00, 1.00] | 6 | 0 | 0.00 (n=6) | 1.17 | 1044 | 2.5 | 0 |
| gabriel_reference_plan | 6 | 6 | 1.00 | [1.00, 1.00] | 6 | 0 | 0.00 (n=6) | 1.00 | 824 | 3.0 | 0 |
| gabriel_plain_sources | 6 | 6 | 1.00 | [1.00, 1.00] | 6 | 0 | 0.00 (n=6) | 1.33 | 1286 | 4.0 | 1 |
| gabriel_all_revisions | 6 | 6 | 1.00 | [1.00, 1.00] | 6 | 0 | 0.00 (n=6) | 1.00 | 846 | 3.1 | 0 |

## Paired differences, all tasks (treatment minus baseline per task: verified success; mean model tokens and requests)

- gabriel_reference_plan_minus_provider_only: success mean +0.17, CI95 by family [+0.00, +0.33], by task [+0.00, +0.50]; tokens -41, requests +0.00; per task: dr-fee +0.0, dr-notice +0.0, dr-sla +0.0, dv-delivery +0.0, dv-retention +0.0, dv-travel +1.0
- gabriel_reference_plan_minus_simple_loop: success mean +0.00, CI95 by family [+0.00, +0.00], by task [+0.00, +0.00]; tokens -220, requests -0.17; per task: dr-fee +0.0, dr-notice +0.0, dr-sla +0.0, dv-delivery +0.0, dv-retention +0.0, dv-travel +0.0
- gabriel_reference_plan_minus_gabriel_plain_sources: success mean +0.00, CI95 by family [+0.00, +0.00], by task [+0.00, +0.00]; tokens -462, requests -0.33; per task: dr-fee +0.0, dr-notice +0.0, dr-sla +0.0, dv-delivery +0.0, dv-retention +0.0, dv-travel +0.0
- gabriel_reference_plan_minus_gabriel_all_revisions: success mean +0.00, CI95 by family [+0.00, +0.00], by task [+0.00, +0.00]; tokens -22, requests +0.00; per task: dr-fee +0.0, dr-notice +0.0, dr-sla +0.0, dv-delivery +0.0, dv-retention +0.0, dv-travel +0.0

## Retained failures and false completions

- dv-travel / provider_only / rep 0: declared=True verified=False; deliverable produced; declared done without verification; problems doc/travel_summary.md: quote 'The daily allowance for domestic travel is sixty (60) EUR.' is found only in a revoked source; required statement missing: 40 EUR | forty (40) EUR | (40) EUR | EUR 40 | forty EUR; required statement not cited from travel with 'forty (40) EUR', out of scope []; provider ['completed']

Scoped comparison on one synthetic task distribution with one provider; a difference here is not a general superiority claim. Costs include every attempt, including failed and timed-out runs.
