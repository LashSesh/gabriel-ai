# G1 matched evaluation report

Protocol `8cc9e12fd75f1f90` (frozen 2026-10-02T22:22:19.429442+00:00), provider `openai_compat` model `gpt-4.1-mini`, backend `linux_namespace`, 18 tasks in 6 families, 144 runs.

Protocol 5 (ADR-16): advantage gate on the document and numerical tiers with the declared memory ablations. Frozen after two pilots on the revision, revoked, units and resample families (evidence/wp14/pilot_declaration.md, pilot1-run, pilot2-run); the conflict and graph families were never run before this protocol. The corpus was amended once between the pilots (status statements removed from the source texts) and is pinned here.

## All tasks

| system | runs | verified | p_success | CI95 (families) | declared | false completions | cond. FC | mean requests | mean tokens | mean wall s | recovery |
|---|---|---|---|---|---|---|---|---|---|---|---|
| provider_only | 36 | 30 | 0.83 | [0.50, 1.00] | 35 | 5 | 0.14 (n=35) | 1.00 | 698 | 1.9 | 0 |
| simple_loop | 36 | 36 | 1.00 | [1.00, 1.00] | 36 | 0 | 0.00 (n=36) | 1.31 | 1027 | 2.6 | 0 |
| gabriel_reference_plan | 36 | 35 | 0.97 | [0.92, 1.00] | 35 | 0 | 0.00 (n=35) | 1.25 | 1025 | 4.0 | 5 |
| gabriel_plain_sources | 18 | 17 | 0.94 | [0.83, 1.00] | 17 | 0 | 0.00 (n=17) | 1.83 | 1840 | 6.3 | 10 |
| gabriel_all_revisions | 18 | 16 | 0.89 | [0.67, 1.00] | 16 | 0 | 0.00 (n=16) | 1.83 | 1987 | 6.0 | 6 |

## Held-out families only (conflict, graph): never run before this protocol

| system | runs | verified | p_success | CI95 (families) | declared | false completions | cond. FC | mean requests | mean tokens | mean wall s | recovery |
|---|---|---|---|---|---|---|---|---|---|---|---|
| provider_only | 12 | 6 | 0.50 | [0.00, 1.00] | 11 | 5 | 0.45 (n=11) | 1.00 | 698 | 2.0 | 0 |
| simple_loop | 12 | 12 | 1.00 | [1.00, 1.00] | 12 | 0 | 0.00 (n=12) | 1.67 | 1429 | 3.7 | 0 |
| gabriel_reference_plan | 12 | 11 | 0.92 | [0.83, 1.00] | 11 | 0 | 0.00 (n=11) | 1.75 | 1722 | 6.4 | 5 |
| gabriel_plain_sources | 6 | 5 | 0.83 | [0.83, 0.83] | 5 | 0 | 0.00 (n=5) | 2.67 | 2753 | 9.4 | 6 |
| gabriel_all_revisions | 6 | 4 | 0.67 | [0.67, 0.67] | 4 | 0 | 0.00 (n=4) | 3.50 | 4260 | 11.9 | 6 |

## Previously seen tasks only (not a held-out test)

| system | runs | verified | p_success | CI95 (families) | declared | false completions | cond. FC | mean requests | mean tokens | mean wall s | recovery |
|---|---|---|---|---|---|---|---|---|---|---|---|
| provider_only | 24 | 24 | 1.00 | [1.00, 1.00] | 24 | 0 | 0.00 (n=24) | 1.00 | 698 | 1.8 | 0 |
| simple_loop | 24 | 24 | 1.00 | [1.00, 1.00] | 24 | 0 | 0.00 (n=24) | 1.12 | 826 | 2.0 | 0 |
| gabriel_reference_plan | 24 | 24 | 1.00 | [1.00, 1.00] | 24 | 0 | 0.00 (n=24) | 1.00 | 676 | 2.8 | 0 |
| gabriel_plain_sources | 12 | 12 | 1.00 | [1.00, 1.00] | 12 | 0 | 0.00 (n=12) | 1.42 | 1384 | 4.8 | 4 |
| gabriel_all_revisions | 12 | 12 | 1.00 | [1.00, 1.00] | 12 | 0 | 0.00 (n=12) | 1.00 | 850 | 3.1 | 0 |

## Paired differences, all tasks (treatment minus baseline per task: verified success; mean model tokens and requests)

- gabriel_reference_plan_minus_provider_only: success mean +0.14, CI95 by family [+0.00, +0.42], by task [+0.00, +0.31]; tokens +327, requests +0.25; per task: dc-hours +0.5, dc-limit +1.0, dc-quorum +1.0, dr-fee +0.0, dr-notice +0.0, dr-sla +0.0, dv-delivery +0.0, dv-retention +0.0, dv-travel +0.0, ng-cycle +0.0, ng-path +0.0, ng-star +0.0, nr-five +0.0, nr-hour +0.0, nr-second +0.0, nu-celsius +0.0, nu-kelvin +0.0, nu-metres +0.0
- gabriel_reference_plan_minus_simple_loop: success mean -0.03, CI95 by family [-0.08, +0.00], by task [-0.08, +0.00]; tokens -2, requests -0.06; per task: dc-hours -0.5, dc-limit +0.0, dc-quorum +0.0, dr-fee +0.0, dr-notice +0.0, dr-sla +0.0, dv-delivery +0.0, dv-retention +0.0, dv-travel +0.0, ng-cycle +0.0, ng-path +0.0, ng-star +0.0, nr-five +0.0, nr-hour +0.0, nr-second +0.0, nu-celsius +0.0, nu-kelvin +0.0, nu-metres +0.0
- gabriel_reference_plan_minus_gabriel_plain_sources: success mean +0.00, CI95 by family [+0.00, +0.00], by task [-0.17, +0.17]; tokens -311, requests -0.33; per task: dc-hours -0.5, dc-limit +0.0, dc-quorum +0.5, dr-fee +0.0, dr-notice +0.0, dr-sla +0.0, dv-delivery +0.0, dv-retention +0.0, dv-travel +0.0
- gabriel_reference_plan_minus_gabriel_all_revisions: success mean +0.06, CI95 by family [+0.00, +0.17], by task [+0.00, +0.17]; tokens -458, requests -0.33; per task: dc-hours +0.0, dc-limit +0.0, dc-quorum +0.5, dr-fee +0.0, dr-notice +0.0, dr-sla +0.0, dv-delivery +0.0, dv-retention +0.0, dv-travel +0.0

## Retained failures and false completions

- dc-hours / gabriel_all_revisions / rep 1: declared=False verified=False; run state failed; problems forbidden statement present in doc/hours.md: 10:00 to 16:00, out of scope []; provider ['completed', 'invalid_output', 'invalid_output', 'invalid_output', 'completed', 'invalid_output']
- dc-hours / gabriel_reference_plan / rep 0: declared=False verified=False; run state failed; problems forbidden statement present in doc/hours.md: 10:00 to 16:00, out of scope []; provider ['completed', 'completed', 'completed', 'invalid_output']
- dc-hours / provider_only / rep 0: declared=True verified=False; deliverable produced; declared done without verification; problems forbidden statement present in doc/hours.md: 10:00 to 16:00, out of scope []; provider ['completed']
- dc-hours / provider_only / rep 1: declared=False verified=False; provider status invalid_output; problems doc/hours.md carries no citation; required statement missing: 09:00 to 15:00 | 9:00 to 15:00 | 09:00-15:00 | 9:00-15:00 | 09:00 and 15:00 | 9:00 and 15:00; required statement not cited from resolution with '09:00 to 15:00', out of scope []; provider ['invalid_output']
- dc-limit / provider_only / rep 0: declared=True verified=False; deliverable produced; declared done without verification; problems forbidden statement present in doc/signature_limit.md: two thousand (2000) EUR, (2000) EUR, out of scope []; provider ['completed']
- dc-limit / provider_only / rep 1: declared=True verified=False; deliverable produced; declared done without verification; problems forbidden statement present in doc/signature_limit.md: two thousand (2000) EUR, (2000) EUR, out of scope []; provider ['completed']
- dc-quorum / gabriel_all_revisions / rep 1: declared=False verified=False; run state failed; problems forbidden statement present in doc/quorum.md: one half, half of the members, out of scope []; provider ['completed', 'completed', 'completed', 'completed']
- dc-quorum / gabriel_plain_sources / rep 0: declared=False verified=False; run state failed; problems forbidden statement present in doc/quorum.md: one half, half of the members, out of scope []; provider ['completed', 'completed', 'completed', 'completed']
- dc-quorum / provider_only / rep 0: declared=True verified=False; deliverable produced; declared done without verification; problems forbidden statement present in doc/quorum.md: one half, half of the members, out of scope []; provider ['completed']
- dc-quorum / provider_only / rep 1: declared=True verified=False; deliverable produced; declared done without verification; problems doc/quorum.md: quote 'The general assembly has a quorum when one third of the memb' is not a verbatim span of any available source; required statement not cited from amendment with 'one third of the members'; forbidden statement present in doc/quorum.md: one half, half of the members, out of scope []; provider ['completed']

Scoped comparison on one synthetic task distribution with one provider; a difference here is not a general superiority claim. Costs include every attempt, including failed and timed-out runs.
