# G1 matched evaluation report

Protocol `b9f824a464c554d9` (frozen 2026-10-02T18:25:46.239110+00:00), provider `openai_compat` model `gpt-4.1-mini`, backend `linux_namespace`, 9 tasks in 3 families, 72 runs.

| system | runs | verified | p_success | CI95 (families) | declared | false completions | cond. FC | mean requests | mean tokens | mean wall s | recovery |
|---|---|---|---|---|---|---|---|---|---|---|---|
| provider_only | 18 | 12 | 0.67 | [0.33, 1.00] | 18 | 6 | 0.33 (n=18) | 1.00 | 719 | 2.5 | 0 |
| simple_loop | 18 | 16 | 0.89 | [0.83, 1.00] | 16 | 0 | 0.00 (n=16) | 2.17 | 2329 | 9.1 | 0 |
| gabriel | 18 | 13 | 0.72 | [0.50, 1.00] | 13 | 0 | 0.00 (n=13) | 3.22 | 3359 | 12.9 | 6 |
| gabriel_no_repair | 18 | 10 | 0.56 | [0.33, 0.83] | 10 | 0 | 0.00 (n=10) | 2.00 | 1827 | 7.8 | 0 |

## Paired differences (gabriel minus baseline, verified success per task)

- gabriel_minus_provider_only: mean +0.06, CI95 by family [+0.00, +0.17], by task [+0.00, +0.17]; per task: co-chunk +0.0, co-dedupe +0.0, co-slugify +0.5, nl-leapyear +0.0, nl-median +0.0, nl-roman +0.0, tp-csvfields +0.0, tp-kvparse +0.0, tp-querystring +0.0
- gabriel_minus_simple_loop: mean -0.17, CI95 by family [-0.33, +0.00], by task [-0.44, +0.06]; per task: co-chunk -0.5, co-dedupe +0.0, co-slugify -0.5, nl-leapyear +0.0, nl-median -1.0, nl-roman +0.5, tp-csvfields +0.0, tp-kvparse +0.0, tp-querystring +0.0
- gabriel_minus_gabriel_no_repair: mean +0.17, CI95 by family [+0.17, +0.17], by task [+0.00, +0.33]; per task: co-chunk +0.0, co-dedupe +0.0, co-slugify +0.5, nl-leapyear +0.0, nl-median +0.0, nl-roman +0.5, tp-csvfields +0.0, tp-kvparse +0.0, tp-querystring +0.5

## Retained failures and false completions

- co-chunk / gabriel / rep 0: declared=False verified=False; run state failed; oracle exit 1, visible exit 1, out of scope []; provider ['completed', 'completed', 'completed', 'completed', 'completed', 'completed']
- co-chunk / gabriel / rep 1: declared=False verified=False; run state failed; oracle exit 1, visible exit 1, out of scope []; provider ['completed', 'completed', 'completed', 'completed', 'completed', 'invalid_output']
- co-chunk / gabriel_no_repair / rep 0: declared=False verified=False; run state failed; oracle exit 1, visible exit 1, out of scope []; provider ['completed', 'completed']
- co-chunk / gabriel_no_repair / rep 1: declared=False verified=False; run state failed; oracle exit 1, visible exit 1, out of scope []; provider ['completed', 'completed']
- co-chunk / provider_only / rep 0: declared=True verified=False; patch applied; declared done without verification; oracle exit 1, visible exit 1, out of scope []; provider ['completed']
- co-chunk / provider_only / rep 1: declared=True verified=False; patch applied; declared done without verification; oracle exit 1, visible exit 1, out of scope []; provider ['completed']
- co-chunk / simple_loop / rep 0: declared=False verified=False; budget exhausted without passing checks; oracle exit 1, visible exit 1, out of scope []; provider ['completed', 'completed', 'completed', 'completed', 'completed', 'completed']
- co-slugify / gabriel / rep 0: declared=False verified=False; run state failed; oracle exit 1, visible exit 1, out of scope []; provider ['completed', 'completed', 'completed', 'completed', 'completed', 'completed']
- co-slugify / gabriel_no_repair / rep 0: declared=False verified=False; run state failed; oracle exit 1, visible exit 1, out of scope []; provider ['completed', 'completed']
- co-slugify / gabriel_no_repair / rep 1: declared=False verified=False; run state failed; oracle exit 1, visible exit 1, out of scope []; provider ['completed', 'completed']
- co-slugify / provider_only / rep 0: declared=True verified=False; patch applied; declared done without verification; oracle exit 1, visible exit 1, out of scope []; provider ['completed']
- co-slugify / provider_only / rep 1: declared=True verified=False; patch applied; declared done without verification; oracle exit 1, visible exit 1, out of scope []; provider ['completed']
- nl-median / gabriel / rep 0: declared=False verified=False; run state failed; oracle exit 0, visible exit 1, out of scope []; provider ['completed', 'completed', 'completed', 'completed', 'completed', 'completed']
- nl-median / gabriel / rep 1: declared=False verified=False; run state failed; oracle exit 0, visible exit 1, out of scope []; provider ['completed', 'completed', 'completed', 'completed', 'completed', 'completed']
- nl-median / gabriel_no_repair / rep 0: declared=False verified=False; run state failed; oracle exit 0, visible exit 1, out of scope []; provider ['completed', 'completed']
- nl-median / gabriel_no_repair / rep 1: declared=False verified=False; run state failed; oracle exit 0, visible exit 1, out of scope []; provider ['completed', 'completed']
- nl-median / provider_only / rep 0: declared=True verified=False; patch applied; declared done without verification; oracle exit 0, visible exit 1, out of scope []; provider ['completed']
- nl-median / provider_only / rep 1: declared=True verified=False; patch applied; declared done without verification; oracle exit 0, visible exit 1, out of scope []; provider ['completed']
- nl-roman / gabriel_no_repair / rep 1: declared=False verified=False; run state failed; oracle exit 1, visible exit 1, out of scope []; provider ['completed', 'completed']
- nl-roman / simple_loop / rep 0: declared=False verified=False; budget exhausted without passing checks; oracle exit 1, visible exit 1, out of scope []; provider ['completed', 'completed', 'completed', 'completed', 'completed', 'completed']
- tp-querystring / gabriel_no_repair / rep 0: declared=False verified=False; run state failed; oracle exit 1, visible exit 1, out of scope []; provider ['completed', 'completed']

Scoped comparison on one synthetic task distribution with one provider; a difference here is not a general superiority claim. Costs include every attempt, including failed and timed-out runs.
