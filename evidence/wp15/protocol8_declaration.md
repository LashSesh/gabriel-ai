# Protocol 8 declaration: G3 on the association distribution (ADR-22)

Written before any run of the training or the evaluation protocol with a real provider; the
frozen files are `protocol8a-train.frozen.json` and `protocol8b-eval.frozen.json`, the executed
runs `run8a-train/` and `run8b-eval/`, the training output `policies8/`, the promotion record
`promotion8/promotion.json`.

## Question
Protocol 4 (`docs/RELEASE_G3.md`) could not train a readout: no first patch failed verification
in 54 training runs, so no labeled decision existed. Protocols 6b and 7 produced a distribution
on which first attempts fail at a measurable rate with both outcomes: hopeless repairs where the
required source is not in the prompt (the provenance view on the needed families: 0 of 10 after
three requests), and recoverable ones where the model stated a forbidden figure or left a
carried figure out (4 of 6 and 2 of 2 repaired). Does a readout trained on retained decisions of
such runs, over the generic progress channels and the document pack's declared channels, stop
hopeless repairs on held-out topics without losing a verified success, and does the memory's
promotion rule admit it on held-out evidence?

## Mechanism under test, as specified (ADR-22)
- A domain pack may declare progress channels (`DomainPack.progress_channels`): committed facts
  of the run's latest verification in the pack's own terms. The document pack declares
  `document-progress-v1`: `required_missing`, `required_uncited`, `forbidden_present`,
  `expected_source_absent` (the fraction of unmet required claims whose expected source was not
  among the retrieval manifest's items), `citations_unbound` and `carried_sources`, read from the
  retained evidence of the latest `claims` and `citations` checks and the retrieval manifest.
- The runner appends them to the generic channels at every decision point; the record's
  `channel_schema_id` names the layout (`progress-channels-v1.document-progress-v1`), a readout
  is bound to the layout it was trained on and refuses any other.
- The decision point, the actions (bounded repair or documented stop), the retention of every
  decision, the outcome labels, the logistic training, the leave-one-family-out validation and
  the promotion rule (held-out families disjoint from the training families, effective support
  over refutations) are those of ADR-15, unchanged.

## Corpus (tier `association`, digest frozen with the protocols)
The tier of protocols 6b and 7 plus, declared for this protocol: `association-needed-cold` (3,
seen) and `association-needed-cold-held-out` (2): the needed task without any history, so no
view can carry the hidden source under the budget and every repair is hopeless; and
`association-unneeded-held-out` (2). Training topics: fee, parking, archive. Held-out topics:
library, garden, in the families `association-needed-held-out`,
`association-needed-cold-held-out` and `association-unneeded-held-out`. The held-out topics'
needed tasks were executed under protocols 6, 6b and 7 (never with a readout); their cold and
unneeded tasks have never been executed. Held out means: disjoint from the training families,
never used to construct, select or validate a readout.

## Protocol 8a (training)
Tasks `da-`, `dc-`, `du-` of the three training topics (nine tasks); arms `gabriel_associative`
(the production configuration) and `gabriel_associative_unlabeled` (the ADR-20 presentation,
which produces recoverable first-attempt failures on the unneeded family); three repetitions;
rule-based policy (every decision is `repair`); gpt-4.1-mini, `linux_namespace`. Every retained
router decision of every unit is one training sample, labeled 1 when the unit's final tree
passed the independent verification and 0 otherwise (the label rule of ADR-15). Two readouts
are fitted (`channels`, `recurrent`) with leave-one-family-out validation against the rule
(always repair); the candidate is the readout with the lower validation loss. If fewer than four
samples or only one label class exist, no readout is trained and the protocol ends there.

## Protocol 8b (evaluation)
All fifteen `da-`, `dc-`, `du-` tasks of the five topics; arms `gabriel_associative` (baseline,
rule-based policy), `gabriel_policy` (treatment: the same configuration with the frozen
candidate pinned) and `gabriel_reference_plan` (the provenance view, reported as the reference
of the earlier protocols); two repetitions; the candidate frozen in the protocol file. The
readout cannot gain rights, budget or checks; it can only stop a repair earlier than the rule.

## Pre-declared criterion and decision rules
- On the held-out families together (`association-needed-held-out`,
  `association-needed-cold-held-out`, `association-unneeded-held-out`): the treatment's verified
  success is at least the baseline's, its mean model tokens are lower, and it makes no false
  completion (the criterion of protocol 4b, unchanged). A stop on a run the baseline verified
  counts against it through the first clause.
- Decision loss: on the held-out decisions, the readout's log-loss is below the rule's.
- Promotion: `scripts/policy_route.py promote` records the outcome labels of every evaluation
  unit in a promotion workspace and asks the memory service's rule; the training families must
  be disjoint from the held-out families (they are by construction) and the treatment's
  effective support on the held-out source must exceed its refutations.
- Consequence, declared now: if the criterion holds and the memory promotes the candidate, the
  promoted readout becomes the document pack's default routing policy for new tasks that pin
  none (the rule-based policy stays the default of every other pack); if either fails, the
  rule-based policy stays pinned and the result is recorded as such.
- A history run that does not succeed is a protocol defect, reported as such; the unit stays in
  the denominator.

## What this protocol cannot establish
That a learned policy raises verified success: the readout can only stop earlier. What it can
establish is bounded and stated: whether a readout over declared, retained facts generalizes
from seen topics to held-out ones in deciding when a repair is hopeless, at what decision loss,
and what that saves. One provider, one pack, one constructed distribution.
