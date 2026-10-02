# ADR-15: Readout router over authorized choices, pinned per task

**Status:** accepted (experimental policy, G3 route). **Affects:** `agent/runner.py`, `agent/workspace.py`, `policy/`.

## Context
The blueprint's routing feature experiment asks for bounded task-progress features extracted
from the committed event stream, a small readout that proposes among already authorized choices,
comparison with a rule-based router and a conventional feature/readout baseline, and reporting
of both the decision loss and the end-to-end task effect. A candidate policy is a
content-addressed artifact; production tasks pin one version, promotion affects new runs only,
and rollback selects an earlier policy.

## Decision
- `policy/features.py` defines the versioned channel schema `progress-channels-v1`: remaining
  budget fractions, elapsed fraction, recent failure fraction, unmet mandatory obligations,
  repair and plan-version usage, tool latency, provider failure fraction, unresolved effects
  and goal length, clipped to [0, 1] with explicit missing indicators and retained as integer
  milli-units.
- `policy/recurrent.py` is the reference recurrent map written from the blueprint's equations
  (`recurrent.features/1`): configuration digest, seed, ordered channel vectors, bounded
  state; configuration mismatch, missing elements and nonfinite inputs reject. It is the
  optional feature source of a readout, never a decision maker on its own.
- `policy/router.py` defines the `gabriel.router-policy/1` record (rule-based or logistic
  readout over channels or recurrent features, threshold, episode retrieval setting) and the
  training/decision-loss functions over explicit task outcomes.
- The runner consults the pinned policy at the repair boundaries: after the owner opened a
  repair cycle on a failed verification, and before a replan after a node exhausted its
  attempts (`failed_node`). `repair` continues with the pack's reference plan, `stop` records a
  hold (`router_stop`, target state `failed`) with the decision's reason. A policy declares
  which boundaries it covers (`decision_point`); elsewhere the rule applies.
  Every decision is retained as a `gabriel.router-decision/1` observation with the exact
  channels; every terminal run records an outcome label and an episode in the memory service.
- A task pins its policy through a `gabriel.policy-pin/1` record among its base inputs (digest
  bound); without a pin the rule-based policy applies. Episodic retrieval enters the worker
  prompt as `procedure` entries whose observation ids are recorded in the model request.

## Consequences
The owner validates every selected action as before: the readout cannot widen rights, budgets
or checks, and it can only stop earlier than the rule. Whether that is an improvement is an
empirical question answered per frozen protocol with a declared criterion; G3 is claimed only
on held-out evidence with regression gates intact.

## Outcome (protocol 4, `docs/RELEASE_G3.md`)
No readout was trained: the failed-verification boundary did not occur in 54 training runs on
the hard tier, so no labeled decision exists; the episodic-retrieval ablation failed its declared
held-out criterion (equal verified success at more tokens). The rule-based policy without
episodes stays the default pin; this ADR's mechanisms remain in place as evaluation
infrastructure, not as an adopted production policy.
