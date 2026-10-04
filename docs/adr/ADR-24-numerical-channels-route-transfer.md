# ADR-24: Domain-declared channels of the numerical pack and the route across packs

**Status:** accepted. **Affects:** `domains/numerical/pack.py` (`ReferenceContractVerifier`
evidence: `failure_class`, `input_problems`, `worker_reason`; `numerical-progress-v1`;
`NumericalPack.progress_channels`, `default_policy`), `evaluation/corpus_domains.py` (families
`numerical-prerequisite`, `numerical-undeclared` and their held-out families),
`evaluation/comparators_domains.py` (arm `gabriel_policy` on numerical tasks),
`scripts/policy_route.py` (unchanged, run on a second pack), `evidence/wp17/`.

## Context
ADR-22 established G3 in the blueprint's scoped sense on one pack and one constructed
distribution. The route is pack-independent by design: a pack declares channels from committed
facts of its own verification, the layout composes the generic channels with the pack's, a
readout binds to the layout it was trained on. None of that had been executed on a second pack,
and a second pack fails for reasons of its own. The numerical pack had declared no channels, its
reference-contract verifier committed a reason text only, and under protocol 5 every numerical
unit of every arm had verified at its first attempt, so the tier produced no decision at all.
The question of this ADR is whether the route carries: whether the numerical pack can declare
channels, whether a readout trained on retained decisions of numerical runs stops hopeless
repairs on held-out numerical topics without losing a verified success, whether the memory's
rule admits it, and whether the document pack's promoted readout is refused on the numerical
layout rather than applied.

## Decision
- **The verifier commits the class of a failure.** `ReferenceContractVerifier` records, beside
  its reason, `failure_class` (`none`, `verdict`, `output_binding`, `contract`, `units`, `rows`,
  `deviation`, `structure`), `input_problems` (how many contract problems the observed input
  dataset of the judged job carried, read from the job's bound snapshot) and `worker_reason`
  (what the worker said when it refused, from its retained diagnostics). The worker's reason is
  appended to the verdict reason, so the next prompt's diagnostics name it.
- **The numerical pack declares `numerical-progress-v1`:** `input_problems`, `verdict_refused`,
  `contract_mismatch`, `units_mismatch`, `rows_mismatch`, `deviation_excess`, `output_unbound`,
  read from the retained evidence of the latest reference-contract verification (the check is
  found by its predicate kind, the latest by node order). Every value is a committed fact of the
  run; a verification that has not run leaves every channel missing, so a layout-bound readout
  abstains and the rule applies (ADR-22).
- **The layout is `progress-channels-v1.numerical-progress-v1`** (38 vector positions). A readout
  bound to the document layout is refused on a numerical run with a stale-evidence error and
  never scored; the decision point, actions, retention, labels, training, validation and
  promotion rule are those of ADR-15 and ADR-22, unchanged. `gabriel_policy` on a numerical task
  is the reference plan with the protocol's frozen readout pinned. `NumericalPack.default_policy`
  returns a shipped readout when one exists under `policies/`, else None (the rule).
- **Two decision families on the numerical tier** (`gabriel eval corpus-check --tier numerical`
  executes their controls): `numerical-prerequisite`, where the observed input dataset carries a
  declared contract problem (a reading that is not a number, a time stamp that is not an
  integer, a malformed row, a unit outside the catalogue), the declared worker refuses every job
  on it and no repair can succeed, while the correct deliverable (the transformation of the
  valid rows) exists and needs the input cleaned outside the admitted scope: a documented
  prerequisite; and `numerical-undeclared`, where the target unit is declared in a conventions
  file the pack observes as a dataset of unknown kind and never shows the model, so a first
  attempt that picks the other admissible unit fails on the units and the diagnostic names the
  declared one. Three seen and two held-out topics per family; the nine tasks of protocol 5 are
  the no-decision control. The numerical tier's digest moved with the families; every task
  protocol 5 ran keeps its frozen digest (`docs/EVALUATION_PROTOCOL.md`).
- **Protocol 10** (`evidence/wp17/protocol10_declaration.md`, frozen before any run): a pilot on
  the seen topics, 10a training on the retained decisions of the rule-based production
  configuration (six tasks, three repetitions), 10b evaluation of the frozen candidate against
  the rule on the whole tier with the two held-out families, the criterion of protocol 8 on the
  held-out families (verified success not lower, fewer tokens, no false completion), decision
  loss below the rule's, promotion by the memory's rule, equality on the control families, and
  the declared consequence that a promoted readout becomes the numerical pack's default.

## Pilot and amendment (`pilot10-run/`, `pilot10b-run/`)
The first pilot (six runs) confirmed the prerequisite family (three requests each, every
verdict refused with the dataset's problem in the worker's reason) and exposed a construction
defect of the undeclared family: gpt-4.1-mini passes the field reference itself as the target
unit (`reporting.units`), the worker refuses it as a unit outside the catalogue, and that
diagnostic cannot name the declared unit; only the unit whose first attempt named a catalogue
unit recovered. The recorded amendment names the two admissible units of the dimension in the
goal, the obvious one first, and leaves which applies to the conventions file; it applies to the
seen and the held-out tasks alike (a construction rule, not an execution), and the second pilot
(three runs) showed the amended rule holding: one first attempt failed on the units and
recovered, two verified directly.

## Training (10a, `run10a-train/`, `policies10/`, 18 runs, digest `e3af3894…`)
The prerequisite tasks failed in every repetition (three requests, two decisions each: 18
samples labeled 0); the undeclared tasks verified in every repetition, two of them after a
repair (nd-fahrenheit: 2 samples labeled 1). 20 samples, 2 positives, one layout. The
leave-one-family-out validation could not run: each of the two training families carries one
label class, so holding either out leaves a training set without both labels and both folds
were skipped; the script then selected the channel readout by its tie order over the recurrent
one, on resubstitution loss 0.037 at accuracy 1.0. The readout's largest weights name the fact:
`input_problems` -1.78, `verdict_refused` -1.78, `units_mismatch` +1.76; it stops where the
input carries a contract problem and repairs where the units differ. That it was never
validated on a family it had not seen is why protocol 10b, not this fit, decides.

## Results (10b, `run10b-eval/`, `promotion10/`, 76 runs, gpt-4.1-mini, `linux_namespace`)

| family | gabriel_reference_plan (rule) | gabriel_policy (readout) |
|---|---|---|
| units, resample, graph (18 runs each arm) | 18/18, 1.00 requests, 794 tokens | 18/18, 1.00, 795; no decision point fired |
| numerical-prerequisite, seen (6) | 0/6, 3.00, 2871 | 0/6, 1.00, 804; 6 stops at the first decision (p = 0.022) |
| numerical-prerequisite-held-out (4) | 0/4, 3.00, 2860 | 0/4, 1.00, 806; 4 stops at the first decision |
| numerical-undeclared, seen (6) | 6/6, 1.33, 1194 | 5/6, 1.83, 1711; 2 readout repairs (p = 0.823), one unit lost (below) |
| numerical-undeclared-held-out (4) | 4/4, 2.00, 1853 | 4/4, 2.00, 1851; 4 readout repairs (p = 0.823) |

- Held-out criterion **met**: on the two held-out families together the readout arm equals
  the rule (4 of 8 verified each) at 1329 against 2357 mean tokens and 1.50 against 2.50
  requests, with no false completion. Every hopeless held-out repair was stopped at its first
  decision, every recoverable held-out repair was taken and verified.
- Decision loss on the eight held-out decisions, this time of both classes (four stops of
  hopeless runs labeled 0, four repairs labeled 1): readout 0.109 against the rule's 3.45,
  accuracy 1.0 against 0.5.
- Promotion: **rejected** by the memory service's rule: the treatment's effective support on
  the held-out source is 4 against 4 refutations, and the rule requires support to exceed
  refutations. Half of the held-out evidence is a family that is hopeless by construction, so
  no routing policy could have met the rule on this composition; the rule measures the
  treatment's own held-out outcomes, not its advantage over the baseline, and was declared as
  the gate. Consequence, as declared: the numerical pack keeps the rule-based policy as its
  default; no readout ships with it.
- Control families: equal, no decision point fired, 0 refusals, 0 abstentions.
- The one lost unit (nd-millis, repetition 1): the model mistyped one hexadecimal character of
  the dataset's digest in four proposals in a row (temperature 0, the rule arm's repetition
  wrote it correctly), each proposal was rejected at normalization before any job ran, the
  readout abstained at every failed-node decision (no reference verification had run, so its
  channels were missing) and the rule repaired until the plan-version limit. No stop was
  involved; the paired difference over all 38 units is -0.026 verified success at -461 tokens
  and -0.45 requests.

## What this establishes and what it does not
The route carries across packs: a second pack declared channels from committed facts of its
own verification, the layout composed and bound, the document pack's readout was refused on it
by construction, a readout trained on twenty retained numerical decisions met the declared
held-out criterion on topics it had never seen, and for the first time the held-out decisions
carried both classes, so the decision loss is a two-sided comparison. What the readout learned
is again one legible fact (stop when the input the job used carries a contract problem, repair
when the units differ); it can only stop earlier, it was not validated across families before
the evaluation (two training families, one label class each), and the memory's promotion rule
declined it on a held-out composition that no policy could have passed. The numerical pack
therefore keeps the rule; the scoped G3 claim of ADR-22 stays what it was, now with the
mechanism executed on two packs under one provider and two constructed distributions. Not
established: a second provider on these families; a third pack; anything about a readout
raising verified success.
