# ADR-10: Hold records (`record_hold` / `HoldRecorded`)

**Status:** accepted for the first implementation. **Affects:** `gabriel.command/1` op enum,
`gabriel.event/1` kind enum, new payload schema `gabriel.hold/1`, reducer transitions.

## Context
The blueprint's run state table lists transitions from `planning`/`running` to `waiting_user`,
`blocked` and `failed` for "missing user decision, unavailable prerequisite, exhausted repair
policy". The thirteen operations of the proposed command contract contain no operation that
records such a decision: assessments can move a run to `failed` (repair policy exhausted) but a
missing credential, an unusable planner response, an unresolved external outcome or an exhausted
plan-version limit had no durable, validated transition. The domain-kernel section also asks for
hold records that "name a prerequisite and wakeup condition".

## Decision
Add one operation, `record_hold`, with event kind `HoldRecorded` and the closed payload
`gabriel.hold/1` (`reason_code`, `target_state` in `blocked|waiting_user|failed`, `reason_ref`,
`missing_prerequisite`, `wakeup_condition`). The reducer admits it only from `admitted`,
`planning` or `running`, refuses `failed` while attempts are in flight, and retains the hold in
the projection. `resume_run` from `blocked`/`waiting_user` restores `planning` (no plan) or
`running` (plan exists) after re-checking the grant. Pause remains a flag, not a state.

## Consequences
The enum extension is additive; every blueprint example still validates and the vendored
`tools/validate_spec.py` passes (negative control `execute_unrestricted` still rejects). Clients
that pin the original enum must add the new value. Holds are decisions by trusted runner code;
models cannot submit commands.
