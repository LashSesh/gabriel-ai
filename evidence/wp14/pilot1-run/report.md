# G1 matched evaluation report

Protocol `d1094fdffa495690` (frozen 2026-10-02T22:18:03.214993+00:00), provider `openai_compat` model `gpt-4.1-mini`, backend `linux_namespace`, 12 tasks in 4 families, 48 runs.

Protocol 5 pilot (not the final protocol): revision, revoked, units and resample families once per unit; conflict and graph are never run before the final protocol. Declaration of the minimum relevant effect: evidence/wp14/pilot_declaration.md, written before this freeze.

## All tasks

| system | runs | verified | p_success | CI95 (families) | declared | false completions | cond. FC | mean requests | mean tokens | mean wall s | recovery |
|---|---|---|---|---|---|---|---|---|---|---|---|
| provider_only | 12 | 12 | 1.00 | [1.00, 1.00] | 12 | 0 | 0.00 (n=12) | 1.00 | 702 | 2.0 | 0 |
| simple_loop | 12 | 12 | 1.00 | [1.00, 1.00] | 12 | 0 | 0.00 (n=12) | 1.00 | 700 | 1.8 | 0 |
| gabriel_reference_plan | 12 | 12 | 1.00 | [1.00, 1.00] | 12 | 0 | 0.00 (n=12) | 1.00 | 678 | 3.0 | 0 |
| gabriel_plain_sources | 6 | 6 | 1.00 | [1.00, 1.00] | 6 | 0 | 0.00 (n=6) | 1.00 | 875 | 3.6 | 0 |
| gabriel_all_revisions | 6 | 6 | 1.00 | [1.00, 1.00] | 6 | 0 | 0.00 (n=6) | 1.00 | 841 | 3.4 | 0 |

## Paired differences, all tasks (treatment minus baseline per task: verified success; mean model tokens and requests)

- gabriel_reference_plan_minus_provider_only: success mean +0.00, CI95 by family [+0.00, +0.00], by task [+0.00, +0.00]; tokens -23, requests +0.00; per task: dr-fee +0.0, dr-notice +0.0, dr-sla +0.0, dv-delivery +0.0, dv-retention +0.0, dv-travel +0.0, nr-five +0.0, nr-hour +0.0, nr-second +0.0, nu-celsius +0.0, nu-kelvin +0.0, nu-metres +0.0
- gabriel_reference_plan_minus_simple_loop: success mean +0.00, CI95 by family [+0.00, +0.00], by task [+0.00, +0.00]; tokens -21, requests +0.00; per task: dr-fee +0.0, dr-notice +0.0, dr-sla +0.0, dv-delivery +0.0, dv-retention +0.0, dv-travel +0.0, nr-five +0.0, nr-hour +0.0, nr-second +0.0, nu-celsius +0.0, nu-kelvin +0.0, nu-metres +0.0
- gabriel_reference_plan_minus_gabriel_plain_sources: success mean +0.00, CI95 by family [+0.00, +0.00], by task [+0.00, +0.00]; tokens -44, requests +0.00; per task: dr-fee +0.0, dr-notice +0.0, dr-sla +0.0, dv-delivery +0.0, dv-retention +0.0, dv-travel +0.0
- gabriel_reference_plan_minus_gabriel_all_revisions: success mean +0.00, CI95 by family [+0.00, +0.00], by task [+0.00, +0.00]; tokens -10, requests +0.00; per task: dr-fee +0.0, dr-notice +0.0, dr-sla +0.0, dv-delivery +0.0, dv-retention +0.0, dv-travel +0.0

## Retained failures and false completions

none

Scoped comparison on one synthetic task distribution with one provider; a difference here is not a general superiority claim. Costs include every attempt, including failed and timed-out runs.
