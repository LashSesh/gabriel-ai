# Protocol 5 pilot declaration (written before any provider call)

Purpose of the pilot: estimate whether the document and numerical distribution discriminates
between the matched systems and the declared memory ablations, before the final protocol is
frozen. The pilot runs the `revision`, `revoked`, `units` and `resample` families once per
unit with gpt-4.1-mini in `linux_namespace`. The `conflict` and `graph` families are not run in
the pilot and are the held-out families of the final protocol.

Minimum relevant effect, declared now for the final protocol:

- Document families: the production arm `gabriel_reference_plan` (provenance view: effective
  revision, authorized and available sources) must reach at least the verified success of every
  other arm and either use at least 0.5 fewer mean model requests per task than the plain-view
  ablation `gabriel_plain_sources` on the `revision` and `revoked` families, or avoid at least
  one false completion that `provider_only` makes on those families.
- Numerical family: no success difference is expected between the systems; the comparison
  reports cost (requests, tokens, wall time) and the containment of the worker only.
- If no arm fails a first answer anywhere in the pilot, the distribution does not discriminate
  for this provider; the final protocol is still frozen and run, and the report says so.

Systems in the pilot and the final protocol: `provider_only`, `simple_loop`,
`gabriel_reference_plan`, `gabriel_plain_sources` (document only), `gabriel_all_revisions`
(document only). The model planner arm is not run (its cost is known from protocols 1 to 3).

What the pilot may change before the freeze: budgets, repetitions and the wording of the
declared criterion. What it may not change: the corpus (digest pinned), the systems, the
verification, the held-out families.

## Amendment after pilot 1 (recorded before pilot 2)

Pilot 1 (`pilot1.frozen.json`, `pilot1-run/`, 48 runs) ended with every arm at 1.00 verified
success on the first request, including the plain-view ablation on the `revoked` and
`revision` families. The retained prompts show why: the source texts stated their own status.
The withdrawn memo carried the line "(This memo was withdrawn by its author on 22 October
2026.)", the withdrawn quotation "This quotation was withdrawn before signature.", the leaked
draft was titled "Draft travel policy (not adopted)", and every second revision said "replaces
revision 1" or "supersedes revision 1". With that text in the content, the plain view carried
the same provenance as the memory service, so the ablation did not remove the mechanism: the
manipulation check failed, not the mechanism.

The rule above forbids changing the corpus after the pilot in order to keep the result from
being tuned. This amendment is recorded as an exception for the reason just given and is
limited to removing the status statements from the content of the `revoked` and `revision`
tasks (the access state and the revision number remain declared task metadata, which is where
they belong) and to renaming `sources/travel_draft.md` to `sources/travel_allowance_update.md`.
Goals, oracles, targets, controls, the `conflict`, `units`, `resample` and `graph` tasks and
the held-out families are unchanged. Pilot 1 is retained unchanged. A second pilot runs on the
amended corpus under the same declaration; the final protocol is frozen after it.
