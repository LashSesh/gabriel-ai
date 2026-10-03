# Protocol 7 declaration: association provenance in the prompt (ADR-21)

Written before any run of the labeled associative view with a real provider; the frozen protocol
file is `protocol7.frozen.json`, the executed run is under `run7/`.

## Question
Protocol 6b (`run6b/`) showed that the associative view carries a source linked to the task only
by verified co-citation into a budgeted prompt and changes the verified outcome (10 of 10 needed
tasks against 0 of 10), and that the carried source gets used whether the task needs it or not:
in all six first attempts on `association-unneeded` the model stated the figure the task forbade,
the loop repaired four, and the declared harm bound (one run in six) was exceeded by one. Does
telling the carried source apart in the prompt, with the reason the manifest retains, bring the
unneeded family within the bound while the needed families keep their outcome?

## Mechanism under test, as specified
The retrieval manifest keeps every item's lexical score beside its structural score and, in the
association record, `links`: for every carried key (mass from the walk, not a seed) the seeds it
was cited together with and the claims and tasks of the verified runs that cited them together.
The document pack's view `associative` lists the lexically retrieved sources as before and then,
under a separate heading ("Sources associated by verified history ... use one only where the
goal needs it"), every carried source with its reason ("associated: cited together with charter
in verified run history-dh-fee"), and closes the rules with "State only what the goal asks for; a
source associated by history is available, not required." Nothing else changes: the same
retrieval, the same budget, the same items, the same checks. The declared ablation
`associative_unlabeled` is the same retrieval with the ADR-20 presentation (carried sources
listed like the others, no reason, no closing rule).

## Corpus
The `association` tier as frozen for protocol 6b (digest `d3517d87…`; construction invariants
executed): `association-needed` (3, seen), `association-needed-held-out` (2), `association-unneeded`
(3), `association-none` (2); every history run first in the same workspace through the scripted
provider. The held-out family has been executed twice before this protocol (run 6 under the
defective corpus, run 6b under the amended one); it is held out from corpus development, not
from execution, and is reported with that qualification.

## Arms
`gabriel_reference_plan` (provenance view; the matched comparator), `gabriel_associative`
(labeled, the mechanism under test) and `gabriel_associative_unlabeled` (the ADR-20 presentation;
the within-protocol control for the labeling). Same provider (gpt-4.1-mini, temperature 0),
budgets, backend (`linux_namespace`), reference plan, two repetitions. The unbudgeted baselines
are not repeated: their bounds on this tier are in `run6b/` (provider_only 0.70 with six false
completions, simple_loop 0.95).

## Pre-declared expectations and decision rules
- Needed: on `association-needed` and `association-needed-held-out`, verified success of
  `gabriel_associative` exceeds `gabriel_reference_plan` by at least 0.5 (paired per task, mean
  over repetitions), as in protocol 6. Expected: unchanged at +1.00, since the labeling does not
  change what is carried.
- Harm, the decision rule of this protocol: on `association-unneeded`, verified success of
  `gabriel_associative` is not worse than `gabriel_reference_plan` by more than one run in six,
  and false completions are not more frequent. Reported beside it, not decisive: the number of
  first attempts that state the forbidden figure (6 of 6 in run 6b for the unlabeled
  presentation) for both associative arms, and mean requests.
- `association-none`: the arms are equal.
- Consequence, declared now: if the needed rule and the harm rule both hold, the document pack's
  default retrieval view becomes `associative` (ADR-21); the harness keeps naming every arm's
  view explicitly, so earlier protocols stay reproducible. If the harm rule fails again, the view
  stays declared per task and the result is recorded as the mechanism's cost under this provider.
- A history run that does not succeed is a protocol defect, reported as such; the unit stays in
  the denominator.

## What this protocol cannot establish
A general retrieval advantage, or that the labeling works for another provider: it is one
provider's response to one presentation on one constructed distribution, with the matched
unlabeled control in the same run.
