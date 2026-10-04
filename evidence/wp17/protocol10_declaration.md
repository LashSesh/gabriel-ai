# Protocol 10 declaration: the channel route on a second pack (ADR-24)

Written before any run of the numerical decision families with a real provider. The frozen
files are `pilot10.frozen.json` (feasibility pilot), `protocol10a-train.frozen.json` and
`protocol10b-eval.frozen.json`; the executed runs `pilot10-run/`, `run10a-train/` and
`run10b-eval/`; the training output `policies10/`; the promotion record `promotion10/promotion.json`.

## Question
ADR-22 established G3 in the blueprint's scoped sense on one pack (document) and one
constructed distribution: a readout over the generic channels and the pack's declared channels
met a held-out criterion and ships as that pack's default. The route is pack-independent by
design (a pack declares channels, the layout composes, a readout binds to the layout), but that
has not been executed on a second pack, and a second pack fails for reasons of its own. Does the
route carry? Concretely: can the numerical pack declare channels from committed facts of its
own verification; does a readout trained on retained decisions of numerical runs stop hopeless
repairs on held-out numerical topics without losing a verified success; does the memory's rule
admit it; and is the document pack's promoted readout refused on the numerical layout rather
than silently applied?

## Mechanism under test, as specified (ADR-24)
- The reference-contract verifier commits, beside its reason, `failure_class` (one of `none`,
  `verdict`, `output_binding`, `contract`, `units`, `rows`, `deviation`, `structure`),
  `input_problems` (how many contract problems the observed input dataset of the judged job
  carried) and `worker_reason` (what the worker said when it refused); the worker's reason also
  reaches the next prompt's diagnostics.
- The numerical pack declares `numerical-progress-v1`: `input_problems`, `verdict_refused`,
  `contract_mismatch`, `units_mismatch`, `rows_mismatch`, `deviation_excess`, `output_unbound`,
  read from the retained evidence of the latest reference-contract verification; a verification
  that has not run leaves them missing, so a bound readout abstains.
- The record's layout is `progress-channels-v1.numerical-progress-v1`; a readout is bound to
  the layout it was trained on and refuses any other (the document pack's readout on a numerical
  run included). Decision point, actions, retention, labels, logistic training,
  leave-one-family-out validation and the promotion rule are those of ADR-15, unchanged. The
  arm `gabriel_policy` on a numerical task is the reference plan with the protocol's frozen
  readout pinned.

## Corpus (tier `numerical`, digest frozen with the protocols)
The nine tasks of protocol 5 (families `units`, `resample`, `graph`; under protocol 5 every
numerical unit of every arm verified at its first attempt, so they are the no-decision control)
plus, declared for this protocol:

- `numerical-prerequisite` (seen: np-null, np-stamp, np-pair) and
  `numerical-prerequisite-held-out` (np-text, np-rankine): the observed input dataset carries a
  declared contract problem (a reading that is not a number, a time stamp that is not an
  integer, a malformed row, a unit outside the catalogue), the declared worker refuses every
  job on it, and no repair can succeed; the correct deliverable exists (the transformation of
  the valid rows) but needs the input cleaned, which lies outside the admitted scope. Every
  repair is hopeless; the right system behaviour is a documented stop.
- `numerical-undeclared` (seen: nd-fahrenheit, nd-centimetres, nd-millis) and
  `numerical-undeclared-held-out` (nd-kelvin, nd-millimetres): the target unit is declared in
  `data/conventions.json`, which the pack observes as a dataset of unknown kind and never shows
  the model; a first attempt that guesses the obvious unit of the dimension fails on the units
  and the diagnostic names the declared unit, so the repair that follows it succeeds.

Every task has executed positive and negative controls (`gabriel eval corpus-check --tier
numerical`). Held out means: never executed with any provider before protocol 10b, never used
to construct, select or validate a readout, disjoint from the training families.

## Pilot (feasibility of the decision classes on the seen topics only)
Six runs (the six seen decision tasks; arm `gabriel_reference_plan`, rule-based; one
repetition; gpt-4.1-mini, `linux_namespace`) to see that both classes appear under the
provider: the prerequisite runs fail with refused verdicts at every attempt, the undeclared
first attempts fail on the units at a measurable rate and the following repair succeeds. The
pilot may lead to an amendment of the seen families' texts only, if it exposes a construction
defect, recorded here before protocol 10a; the held-out families are not touched. The pilot's
runs are retained and not counted.

## Amendment after the pilot (recorded before protocol 10a was frozen)
Pilot run (`pilot10-run/`, digest `af3857f7…`, six runs): the prerequisite family behaved as
constructed (np-null, np-stamp, np-pair: three requests each, every verdict refused with the
dataset's problem in the worker's reason, no verified run). The undeclared family did not:
gpt-4.1-mini does not guess a unit of the dimension, it passes the field reference itself as
the target unit (`reporting.units`, then `data/conventions.json:reporting.units`), the worker
refuses it as a unit outside the catalogue, and that diagnostic cannot name the declared unit;
only nd-fahrenheit, whose first attempt named a catalogue unit (`degC`, no conversion), reached
the units diagnostic and recovered (two requests). nd-centimetres reached it only at its last
repair, nd-millis never. The family's construction rule ("the first attempt fails on the units
and the diagnostic names the declared unit") therefore did not hold under the provider.

Amendment: the goal of every undeclared task names the two admissible units of the series'
dimension, the obvious one first, and leaves which applies to the conventions file the pack
never shows (`... the conventions admit K or degF for temperatures ...`). The negative control
`obvious_guess` is unchanged. The amendment is a construction rule of the family and applies to
the seen and the held-out tasks alike; the held-out tasks remain never executed and never used
to select or validate a readout. A second pilot (`pilot10b.frozen.json`, `pilot10b-run/`,
three runs: the seen undeclared tasks) checks the amended rule under the provider before
protocol 10a is frozen; it is retained and not counted.

Second pilot (`pilot10b-run/`, three runs): every unit verified; nd-fahrenheit after one
repair (first attempt K, the units diagnostic named degF), nd-centimetres and nd-millis at the
first attempt (the model chose the declared unit directly). The amended rule holds under the
provider: a first attempt on this family either verifies or fails on the units and recovers;
the rate of first-attempt failures is lower than assumed and is left to protocol 10a to
measure. No further change; protocol 10a is frozen after this record.

## Protocol 10a (training)
The six seen decision tasks; arm `gabriel_reference_plan` (the production configuration of
the numerical pack under the rule-based policy: every decision is `repair`); three repetitions;
18 runs; gpt-4.1-mini, `linux_namespace`. Every retained router decision of every unit is one
training sample, labeled 1 when the unit's final tree passed the independent verification and 0
otherwise (the label rule of ADR-15). Two readouts are fitted (`channels`, `recurrent`) with
leave-one-family-out validation against the rule (always repair); the candidate is the readout
with the lower validation loss. If fewer than four samples or only one label class exist, no
readout is trained and the protocol ends there with that record.

## Protocol 10b (evaluation)
All nineteen tasks of the numerical tier (the nine control tasks and the ten decision tasks);
arms `gabriel_reference_plan` (baseline, rule-based) and `gabriel_policy` (treatment: the same
configuration with the frozen candidate pinned); two repetitions; 76 runs; the candidate frozen
in the protocol file. The readout cannot gain rights, budget or checks; it can only stop a
repair earlier than the rule.

## Pre-declared criterion and decision rules
- On the held-out families together (`numerical-prerequisite-held-out`,
  `numerical-undeclared-held-out`): the treatment's verified success is at least the
  baseline's, its mean model tokens are lower, and it makes no false completion (the criterion
  of protocols 4b and 8, unchanged). A stop on a run the baseline verified counts against it
  through the first clause.
- Decision loss: on the held-out decisions, the readout's log-loss is below the rule's.
- Promotion: `scripts/policy_route.py promote` records the outcome labels of every evaluation
  unit in a promotion workspace and asks the memory service's rule; the training families must
  be disjoint from the held-out families (they are by construction) and the treatment's
  effective support on the held-out source must exceed its refutations.
- Control families (`units`, `resample`, `graph`): the two arms are equal; refusals (layout
  mismatch) and abstentions of the readout are counted and reported.
- Consequence, declared now: if the criterion holds and the memory promotes the candidate, the
  promoted readout becomes the numerical pack's default routing policy for new tasks that pin
  none (the document pack's readout stays what it is; the software pack stays on the rule); if
  either fails, the rule-based policy stays the numerical pack's default and the result is
  recorded as such.

## What this protocol cannot establish
That a learned policy raises verified success: the readout can only stop earlier. The hopeless
class here rests on one committed fact (the input's contract problems), so what the readout can
learn is again one legible fact; the claim is bounded to one provider, two packs and two
constructed distributions. A transfer of the document readout is not tested, because the route
refuses it by construction; what this protocol tests is whether the route, not the weights,
carries across packs.
