# G1 matched evaluation report

Protocol `02da6897d5b81956` (frozen 2026-10-02T18:45:46.465074+00:00), provider `openai_compat` model `gpt-4.1-mini`, backend `linux_namespace`, 15 tasks in 5 families, 150 runs.

Third frozen protocol after the failure analysis of run 2 (protocol b9a6e0d0...): the first observation of every system did not retain the in-scope source files in the artifact store, so the shared worker prompt listed file digests only and every system patched blind in its first request (retained prompts under run2; e.g. nl-median lost the unseen mean() function, co-chunk was rewritten as a generator). software.observe now retains in-scope text sources (bounded) and the prompt marks any file whose content is not retained instead of omitting it silently. The twelve tasks of runs 1 and 2 were seen before this freeze; the encoding family (run-length encoding, rot13, hex codec) was written after run 2 and never run before.

## All tasks

| system | runs | verified | p_success | CI95 (families) | declared | false completions | cond. FC | mean requests | mean tokens | mean wall s | recovery |
|---|---|---|---|---|---|---|---|---|---|---|---|
| provider_only | 30 | 30 | 1.00 | [1.00, 1.00] | 30 | 0 | 0.00 (n=30) | 1.00 | 808 | 2.5 | 0 |
| simple_loop | 30 | 30 | 1.00 | [1.00, 1.00] | 30 | 0 | 0.00 (n=30) | 1.00 | 805 | 2.7 | 0 |
| gabriel | 30 | 30 | 1.00 | [1.00, 1.00] | 30 | 0 | 0.00 (n=30) | 2.00 | 1916 | 7.8 | 0 |
| gabriel_no_repair | 30 | 30 | 1.00 | [1.00, 1.00] | 30 | 0 | 0.00 (n=30) | 2.00 | 1922 | 8.8 | 0 |
| gabriel_reference_plan | 30 | 30 | 1.00 | [1.00, 1.00] | 30 | 0 | 0.00 (n=30) | 1.00 | 810 | 5.1 | 0 |

## Held-out families only (encoding): never run before this protocol

| system | runs | verified | p_success | CI95 (families) | declared | false completions | cond. FC | mean requests | mean tokens | mean wall s | recovery |
|---|---|---|---|---|---|---|---|---|---|---|---|
| provider_only | 6 | 6 | 1.00 | [1.00, 1.00] | 6 | 0 | 0.00 (n=6) | 1.00 | 820 | 2.7 | 0 |
| simple_loop | 6 | 6 | 1.00 | [1.00, 1.00] | 6 | 0 | 0.00 (n=6) | 1.00 | 818 | 2.7 | 0 |
| gabriel | 6 | 6 | 1.00 | [1.00, 1.00] | 6 | 0 | 0.00 (n=6) | 2.00 | 1910 | 7.8 | 0 |
| gabriel_no_repair | 6 | 6 | 1.00 | [1.00, 1.00] | 6 | 0 | 0.00 (n=6) | 2.00 | 1915 | 8.0 | 0 |
| gabriel_reference_plan | 6 | 6 | 1.00 | [1.00, 1.00] | 6 | 0 | 0.00 (n=6) | 1.00 | 823 | 4.8 | 0 |

## Previously seen tasks only (not a held-out test)

| system | runs | verified | p_success | CI95 (families) | declared | false completions | cond. FC | mean requests | mean tokens | mean wall s | recovery |
|---|---|---|---|---|---|---|---|---|---|---|---|
| provider_only | 24 | 24 | 1.00 | [1.00, 1.00] | 24 | 0 | 0.00 (n=24) | 1.00 | 805 | 2.4 | 0 |
| simple_loop | 24 | 24 | 1.00 | [1.00, 1.00] | 24 | 0 | 0.00 (n=24) | 1.00 | 801 | 2.7 | 0 |
| gabriel | 24 | 24 | 1.00 | [1.00, 1.00] | 24 | 0 | 0.00 (n=24) | 2.00 | 1918 | 7.8 | 0 |
| gabriel_no_repair | 24 | 24 | 1.00 | [1.00, 1.00] | 24 | 0 | 0.00 (n=24) | 2.00 | 1923 | 9.0 | 0 |
| gabriel_reference_plan | 24 | 24 | 1.00 | [1.00, 1.00] | 24 | 0 | 0.00 (n=24) | 1.00 | 807 | 5.2 | 0 |

## Paired differences, all tasks (gabriel minus baseline, verified success per task)

- gabriel_minus_provider_only: mean +0.00, CI95 by family [+0.00, +0.00], by task [+0.00, +0.00]; per task: co-chunk +0.0, co-dedupe +0.0, co-slugify +0.0, en-hex +0.0, en-rle +0.0, en-rot13 +0.0, nl-leapyear +0.0, nl-median +0.0, nl-roman +0.0, tp-csvfields +0.0, tp-kvparse +0.0, tp-querystring +0.0, vl-email +0.0, vl-isbn10 +0.0, vl-luhn +0.0
- gabriel_minus_simple_loop: mean +0.00, CI95 by family [+0.00, +0.00], by task [+0.00, +0.00]; per task: co-chunk +0.0, co-dedupe +0.0, co-slugify +0.0, en-hex +0.0, en-rle +0.0, en-rot13 +0.0, nl-leapyear +0.0, nl-median +0.0, nl-roman +0.0, tp-csvfields +0.0, tp-kvparse +0.0, tp-querystring +0.0, vl-email +0.0, vl-isbn10 +0.0, vl-luhn +0.0
- gabriel_minus_gabriel_no_repair: mean +0.00, CI95 by family [+0.00, +0.00], by task [+0.00, +0.00]; per task: co-chunk +0.0, co-dedupe +0.0, co-slugify +0.0, en-hex +0.0, en-rle +0.0, en-rot13 +0.0, nl-leapyear +0.0, nl-median +0.0, nl-roman +0.0, tp-csvfields +0.0, tp-kvparse +0.0, tp-querystring +0.0, vl-email +0.0, vl-isbn10 +0.0, vl-luhn +0.0
- gabriel_minus_gabriel_reference_plan: mean +0.00, CI95 by family [+0.00, +0.00], by task [+0.00, +0.00]; per task: co-chunk +0.0, co-dedupe +0.0, co-slugify +0.0, en-hex +0.0, en-rle +0.0, en-rot13 +0.0, nl-leapyear +0.0, nl-median +0.0, nl-roman +0.0, tp-csvfields +0.0, tp-kvparse +0.0, tp-querystring +0.0, vl-email +0.0, vl-isbn10 +0.0, vl-luhn +0.0

## Retained failures and false completions

none

Scoped comparison on one synthetic task distribution with one provider; a difference here is not a general superiority claim. Costs include every attempt, including failed and timed-out runs.
