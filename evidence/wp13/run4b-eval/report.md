# G1 matched evaluation report

Protocol `0acb56abf9ce0372` (frozen 2026-10-02T21:28:26.669359+00:00), provider `openai_compat` model `gpt-4.1-mini`, backend `linux_namespace`, 9 tasks in 3 families, 72 runs.

Protocol 4b (G3 route, evaluation) on the hard tier with gpt-4.1-mini: baselines, the reference-plan Gabriel and the episodic-retrieval ablation seeded with the 18 episodes of run4a-train-mini-saturated (training families only). The stateful family was never run before this protocol. A first freeze of this protocol carried an empty seed because the seed builder read unit paths of a moved run; it was discarded before any result was read and the builder was corrected.

## All tasks

| system | runs | verified | p_success | CI95 (families) | declared | false completions | cond. FC | mean requests | mean tokens | mean wall s | recovery |
|---|---|---|---|---|---|---|---|---|---|---|---|
| provider_only | 18 | 18 | 1.00 | [1.00, 1.00] | 18 | 0 | 0.00 (n=18) | 1.00 | 825 | 2.1 | 0 |
| simple_loop | 18 | 18 | 1.00 | [1.00, 1.00] | 18 | 0 | 0.00 (n=18) | 1.00 | 824 | 2.6 | 0 |
| gabriel_reference_plan | 18 | 18 | 1.00 | [1.00, 1.00] | 18 | 0 | 0.00 (n=18) | 1.00 | 829 | 4.4 | 0 |
| gabriel_episodes | 18 | 18 | 1.00 | [1.00, 1.00] | 18 | 0 | 0.00 (n=18) | 1.00 | 1433 | 4.5 | 0 |

## Held-out families only (stateful): never run before this protocol

| system | runs | verified | p_success | CI95 (families) | declared | false completions | cond. FC | mean requests | mean tokens | mean wall s | recovery |
|---|---|---|---|---|---|---|---|---|---|---|---|
| provider_only | 6 | 6 | 1.00 | [1.00, 1.00] | 6 | 0 | 0.00 (n=6) | 1.00 | 828 | 2.2 | 0 |
| simple_loop | 6 | 6 | 1.00 | [1.00, 1.00] | 6 | 0 | 0.00 (n=6) | 1.00 | 827 | 2.6 | 0 |
| gabriel_reference_plan | 6 | 6 | 1.00 | [1.00, 1.00] | 6 | 0 | 0.00 (n=6) | 1.00 | 829 | 4.8 | 0 |
| gabriel_episodes | 6 | 6 | 1.00 | [1.00, 1.00] | 6 | 0 | 0.00 (n=6) | 1.00 | 1395 | 4.5 | 0 |

## Previously seen tasks only (not a held-out test)

| system | runs | verified | p_success | CI95 (families) | declared | false completions | cond. FC | mean requests | mean tokens | mean wall s | recovery |
|---|---|---|---|---|---|---|---|---|---|---|---|
| provider_only | 12 | 12 | 1.00 | [1.00, 1.00] | 12 | 0 | 0.00 (n=12) | 1.00 | 823 | 2.0 | 0 |
| simple_loop | 12 | 12 | 1.00 | [1.00, 1.00] | 12 | 0 | 0.00 (n=12) | 1.00 | 823 | 2.6 | 0 |
| gabriel_reference_plan | 12 | 12 | 1.00 | [1.00, 1.00] | 12 | 0 | 0.00 (n=12) | 1.00 | 829 | 4.3 | 0 |
| gabriel_episodes | 12 | 12 | 1.00 | [1.00, 1.00] | 12 | 0 | 0.00 (n=12) | 1.00 | 1452 | 4.5 | 0 |

## Paired differences, all tasks (gabriel minus baseline, verified success per task)


## Retained failures and false completions

none

Scoped comparison on one synthetic task distribution with one provider; a difference here is not a general superiority claim. Costs include every attempt, including failed and timed-out runs.
