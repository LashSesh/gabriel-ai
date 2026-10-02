# ADR-11: Planner requests as bootstrap intents while no plan is admitted

**Status:** accepted. **Affects:** reducer `issue_intent`/`mark_dispatch`/`accept_result` in state `planning`.

## Context
The execution loop reads "if no admitted plan exists, request and validate a candidate plan".
A plan request is a model call: it discloses context, costs tokens and must be reserved,
marked before I/O and retained like every other attempt. `issue_intent` requires a plan node,
so the very first model call had no admissible node.

## Decision
In state `planning` the owner admits an intent whose `step_id` is the reserved identifier
`plan-request` and whose capability is a registered model tool. It uses a synthetic node with
the task binding's planner reservation (default 8000 tokens, one request) and
`target_idempotent_retry`. At most two planner requests are admitted per plan version. The
result is retained like any attempt; it never changes plan state. Plan admission remains the
separate, validated `accept_plan` command. All other authorization, budget, lease and marker
rules apply unchanged.

## Consequences
Planner calls are accounted and recoverable (an interrupted planner call is recorded unknown,
reconciled as a failed provider call and retried under the same limit). The reserved step id
cannot be used as an ordinary plan node id.
