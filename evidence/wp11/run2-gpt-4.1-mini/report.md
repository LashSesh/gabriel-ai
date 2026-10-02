# G1 matched evaluation report

Protocol `b9a6e0d096ca285c` (frozen 2026-10-02T18:34:09.215798+00:00), provider `openai_compat` model `gpt-4.1-mini`, backend `linux_namespace`, 12 tasks in 4 families, 120 runs.

Second frozen protocol after the failure analysis of run 1 (protocol b9f824a4...): the runner now includes retained test output in repair prompts, and gabriel_reference_plan admits the domain pack's reference plan without a planner request. The nine tasks of run 1 were seen before this freeze; the validation family was written after run 1 and never run before.

## All tasks

| system | runs | verified | p_success | CI95 (families) | declared | false completions | cond. FC | mean requests | mean tokens | mean wall s | recovery |
|---|---|---|---|---|---|---|---|---|---|---|---|
| provider_only | 24 | 17 | 0.71 | [0.46, 0.92] | 24 | 7 | 0.29 (n=24) | 1.00 | 748 | 2.7 | 0 |
| simple_loop | 24 | 22 | 0.92 | [0.75, 1.00] | 22 | 0 | 0.00 (n=22) | 1.79 | 1836 | 5.6 | 0 |
| gabriel | 24 | 21 | 0.88 | [0.75, 1.00] | 21 | 0 | 0.00 (n=21) | 2.75 | 2976 | 11.0 | 6 |
| gabriel_no_repair | 24 | 16 | 0.67 | [0.46, 0.83] | 16 | 0 | 0.00 (n=16) | 2.00 | 1861 | 8.3 | 0 |
| gabriel_reference_plan | 24 | 21 | 0.88 | [0.75, 1.00] | 21 | 0 | 0.00 (n=21) | 1.38 | 1271 | 6.2 | 6 |

## Held-out families only (validation): never run before this protocol

| system | runs | verified | p_success | CI95 (families) | declared | false completions | cond. FC | mean requests | mean tokens | mean wall s | recovery |
|---|---|---|---|---|---|---|---|---|---|---|---|
| provider_only | 6 | 5 | 0.83 | [0.83, 0.83] | 6 | 1 | 0.17 (n=6) | 1.00 | 830 | 3.0 | 0 |
| simple_loop | 6 | 6 | 1.00 | [1.00, 1.00] | 6 | 0 | 0.00 (n=6) | 1.33 | 1156 | 4.5 | 0 |
| gabriel | 6 | 6 | 1.00 | [1.00, 1.00] | 6 | 0 | 0.00 (n=6) | 2.00 | 1940 | 8.3 | 0 |
| gabriel_no_repair | 6 | 5 | 0.83 | [0.83, 0.83] | 5 | 0 | 0.00 (n=5) | 2.00 | 1966 | 8.4 | 0 |
| gabriel_reference_plan | 6 | 6 | 1.00 | [1.00, 1.00] | 6 | 0 | 0.00 (n=6) | 1.00 | 826 | 4.8 | 0 |

## Previously seen tasks only (not a held-out test)

| system | runs | verified | p_success | CI95 (families) | declared | false completions | cond. FC | mean requests | mean tokens | mean wall s | recovery |
|---|---|---|---|---|---|---|---|---|---|---|---|
| provider_only | 18 | 12 | 0.67 | [0.33, 1.00] | 18 | 6 | 0.33 (n=18) | 1.00 | 720 | 2.6 | 0 |
| simple_loop | 18 | 16 | 0.89 | [0.67, 1.00] | 16 | 0 | 0.00 (n=16) | 1.94 | 2062 | 6.0 | 0 |
| gabriel | 18 | 15 | 0.83 | [0.67, 1.00] | 15 | 0 | 0.00 (n=15) | 3.00 | 3321 | 11.9 | 6 |
| gabriel_no_repair | 18 | 11 | 0.61 | [0.33, 0.83] | 11 | 0 | 0.00 (n=11) | 2.00 | 1826 | 8.2 | 0 |
| gabriel_reference_plan | 18 | 15 | 0.83 | [0.67, 1.00] | 15 | 0 | 0.00 (n=15) | 1.50 | 1419 | 6.6 | 6 |

## Paired differences, all tasks (gabriel minus baseline, verified success per task)

- gabriel_minus_provider_only: mean +0.17, CI95 by family [+0.04, +0.29], by task [+0.00, +0.38]; per task: co-chunk +0.0, co-dedupe +0.0, co-slugify +1.0, nl-leapyear +0.0, nl-median +0.5, nl-roman +0.0, tp-csvfields +0.0, tp-kvparse +0.0, tp-querystring +0.0, vl-email +0.5, vl-isbn10 +0.0, vl-luhn +0.0
- gabriel_minus_simple_loop: mean -0.04, CI95 by family [-0.12, +0.00], by task [-0.12, +0.00]; per task: co-chunk +0.0, co-dedupe +0.0, co-slugify +0.0, nl-leapyear +0.0, nl-median -0.5, nl-roman +0.0, tp-csvfields +0.0, tp-kvparse +0.0, tp-querystring +0.0, vl-email +0.0, vl-isbn10 +0.0, vl-luhn +0.0
- gabriel_minus_gabriel_no_repair: mean +0.21, CI95 by family [+0.17, +0.29], by task [+0.04, +0.42]; per task: co-chunk +0.0, co-dedupe +0.0, co-slugify +1.0, nl-leapyear +0.0, nl-median +0.5, nl-roman +0.0, tp-csvfields +0.0, tp-kvparse +0.0, tp-querystring +0.5, vl-email +0.5, vl-isbn10 +0.0, vl-luhn +0.0
- gabriel_minus_gabriel_reference_plan: mean +0.00, CI95 by family [+0.00, +0.00], by task [+0.00, +0.00]; per task: co-chunk +0.0, co-dedupe +0.0, co-slugify +0.0, nl-leapyear +0.0, nl-median +0.0, nl-roman +0.0, tp-csvfields +0.0, tp-kvparse +0.0, tp-querystring +0.0, vl-email +0.0, vl-isbn10 +0.0, vl-luhn +0.0

## Retained failures and false completions

- co-chunk / gabriel / rep 0: declared=False verified=False; run state failed; oracle exit 1, visible exit 1, out of scope []; provider ['completed', 'completed', 'completed', 'completed', 'completed', 'completed']
- co-chunk / gabriel / rep 1: declared=False verified=False; run state failed; oracle exit 1, visible exit 1, out of scope []; provider ['completed', 'completed', 'completed', 'completed', 'completed', 'completed']
- co-chunk / gabriel_no_repair / rep 0: declared=False verified=False; run state failed; oracle exit 1, visible exit 1, out of scope []; provider ['completed', 'completed']
- co-chunk / gabriel_no_repair / rep 1: declared=False verified=False; run state failed; oracle exit 1, visible exit 1, out of scope []; provider ['completed', 'completed']
- co-chunk / gabriel_reference_plan / rep 0: declared=False verified=False; run state failed; oracle exit 1, visible exit 1, out of scope []; provider ['completed', 'completed', 'completed']
- co-chunk / gabriel_reference_plan / rep 1: declared=False verified=False; run state failed; oracle exit 1, visible exit 1, out of scope []; provider ['completed', 'completed', 'completed']
- co-chunk / provider_only / rep 0: declared=True verified=False; patch applied; declared done without verification; oracle exit 1, visible exit 1, out of scope []; provider ['completed']
- co-chunk / provider_only / rep 1: declared=True verified=False; patch applied; declared done without verification; oracle exit 1, visible exit 1, out of scope []; provider ['completed']
- co-chunk / simple_loop / rep 0: declared=False verified=False; budget exhausted without passing checks; oracle exit 1, visible exit 1, out of scope []; provider ['completed', 'completed', 'completed', 'completed', 'completed', 'completed']
- co-chunk / simple_loop / rep 1: declared=False verified=False; budget exhausted without passing checks; oracle exit 1, visible exit 1, out of scope []; provider ['completed', 'completed', 'completed', 'completed', 'completed', 'completed']
- co-slugify / gabriel_no_repair / rep 0: declared=False verified=False; run state failed; oracle exit 1, visible exit 1, out of scope []; provider ['completed', 'completed']
- co-slugify / gabriel_no_repair / rep 1: declared=False verified=False; run state failed; oracle exit 1, visible exit 1, out of scope []; provider ['completed', 'completed']
- co-slugify / provider_only / rep 0: declared=True verified=False; patch applied; declared done without verification; oracle exit 1, visible exit 1, out of scope []; provider ['completed']
- co-slugify / provider_only / rep 1: declared=True verified=False; patch applied; declared done without verification; oracle exit 1, visible exit 1, out of scope []; provider ['completed']
- nl-median / gabriel / rep 1: declared=False verified=False; run state failed; oracle exit 0, visible exit 1, out of scope []; provider ['completed', 'completed', 'completed', 'completed', 'completed', 'completed']
- nl-median / gabriel_no_repair / rep 0: declared=False verified=False; run state failed; oracle exit 0, visible exit 1, out of scope []; provider ['completed', 'completed']
- nl-median / gabriel_no_repair / rep 1: declared=False verified=False; run state failed; oracle exit 0, visible exit 1, out of scope []; provider ['completed', 'completed']
- nl-median / gabriel_reference_plan / rep 0: declared=False verified=False; run state failed; oracle exit 0, visible exit 1, out of scope []; provider ['completed', 'completed', 'completed']
- nl-median / provider_only / rep 0: declared=True verified=False; patch applied; declared done without verification; oracle exit 0, visible exit 1, out of scope []; provider ['completed']
- nl-median / provider_only / rep 1: declared=True verified=False; patch applied; declared done without verification; oracle exit 0, visible exit 1, out of scope []; provider ['completed']
- tp-querystring / gabriel_no_repair / rep 1: declared=False verified=False; run state failed; oracle exit 1, visible exit 1, out of scope []; provider ['completed', 'completed']
- vl-email / gabriel_no_repair / rep 1: declared=False verified=False; run state failed; oracle exit 0, visible exit 1, out of scope []; provider ['completed', 'completed']
- vl-email / provider_only / rep 1: declared=True verified=False; patch applied; declared done without verification; oracle exit 0, visible exit 1, out of scope []; provider ['completed']

Scoped comparison on one synthetic task distribution with one provider; a difference here is not a general superiority claim. Costs include every attempt, including failed and timed-out runs.
