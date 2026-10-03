# ADR-22: Domain-declared progress channels and G3 on the association distribution

**Status:** accepted. **Affects:** `domains/base.py` (`progress_channels` port),
`domains/document/pack.py` (`document-progress-v1`; `retrieved_source_ids` in the citation
report; `expected_source_retrieved` per claim), `policy/features.py` (pack channels appended,
composed `channel_schema_id`), `policy/router.py` (readouts bound to a layout), `agent/runner.py`
(pack channels at the decision point), `evaluation/comparators_domains.py` (arm `gabriel_policy`
for document tasks), `evaluation/harness.py` (paired treatment), `evaluation/corpus_domains.py`
(families `association-needed-cold`, `-cold-held-out`, `association-unneeded-held-out`),
`scripts/policy_route.py` (`--systems`, layout-bound readouts), `evidence/wp15/protocol8_declaration.md`.

## Context
The G3 route (ADR-15) built the policy machinery and could not evaluate it: on the hard tier no
first patch failed verification, so no labeled decision existed (`docs/RELEASE_G3.md`). The
association tier of ADR-20 and ADR-21 is the first distribution on which first attempts fail at
a measurable rate with both outcomes: hopeless repairs when the required source is not in the
prompt, recoverable ones when the model stated a forbidden figure or left a carried one out.
The generic progress channels of ADR-15 cannot tell these apart: both fail the same mandatory
check with the same budget fractions. What tells them apart is a committed fact the document
pack already has: whether the expected source of an unmet claim was among the retrieved items.

## Decision
- **A domain pack may declare progress channels.** `DomainPack.progress_channels(projection,
  store)` returns `{"schema_id", "names", "values"}` or None. The document pack declares
  `document-progress-v1`: `required_missing`, `required_uncited`, `forbidden_present`,
  `expected_source_absent`, `citations_unbound`, `carried_sources`, read from the retained
  evidence of the latest `claims` and `citations` checks (the review report now records
  `retrieved_source_ids`, the claims verifier `expected_source_retrieved` per claim) and from
  the observed snapshot's retrieval manifest. Every value is a committed fact; a value the
  evidence does not carry is missing, with its indicator, never guessed.
- **The generic channels append the pack's.** The record's `channel_schema_id` is the generic
  schema alone (`progress-channels-v1`) or the generic schema followed by the pack's
  (`progress-channels-v1.document-progress-v1`); the vector layout is every value, then every
  missing indicator. A readout record names the layout it was trained on and `decide` refuses
  any other layout with a stale-evidence error rather than scoring it; the rule-based policy
  needs no layout.
- **The route is otherwise ADR-15.** Decision point, actions, retention, labels (1 when the
  run's final tree passed the independent verification), logistic training with
  leave-one-family-out validation, the memory's promotion rule and the per-task pin are
  unchanged. `scripts/policy_route.py train --systems` names the arms whose decisions are
  samples and binds the readouts to the samples' layout; the recurrent configuration takes the
  layout's dimension.
- **Harness.** The arm `gabriel_policy` exists for document tasks: the production configuration
  (associative view, reference plan) with the protocol's frozen readout pinned. The paired
  treatment of a protocol is the readout arm when it carries one.
- **Corpus.** `association-needed-cold` (3 seen, 2 held out): the needed task without history,
  so no view carries the hidden source and every repair is hopeless; `association-unneeded-held-out`
  (2). The invariants of ADR-20 apply unchanged.
- **Protocol 8** (`evidence/wp15/protocol8_declaration.md`, frozen before any run): 8a trains
  on the retained decisions of the production configuration and the unlabeled control on the
  three training topics (three repetitions); 8b evaluates the frozen candidate against the
  rule-based production configuration on all fifteen `da-`/`dc-`/`du-` tasks with the two held-out
  topics in three held-out families, under the criterion of protocol 4b (verified success not
  lower, fewer tokens, no false completion on the held-out families) plus decision loss below
  the rule's, promotion by the memory's rule, and the declared consequence that a promoted
  readout becomes the document pack's default routing policy.
- **A layout-bound readout abstains where the pack's channels are missing.** A verification
  that produced none of the pack's channels (another check failed before the claims check ran)
  is outside what the readout was trained on; `decide` then returns the rule's action with the
  reason retained ("readout abstains: pack channel(s) ... missing"). No decision of protocol 8
  had a missing pack channel (0 of 48 training and 0 of 76 evaluation decisions), so the rule
  changes nothing about the evaluated behaviour; it bounds the promoted readout to its
  evidence.
- **The promoted readout ships with the pack.** `domains/document/policies/readout-channels-v2.json`
  is the evaluated candidate (policy digest `f164ed8e…`), beside its provenance record (training
  run, protocol digests, samples, validation, criterion, promotion decision).
  `DocumentPack.default_policy` returns it; a document task whose spec names no policy pins it
  (digest-bound, among its base inputs), an explicit policy still wins, and every other pack
  keeps the rule-based policy. The harness pins the rule-based policy explicitly on every
  Gabriel arm but `gabriel_policy`, so the arms of protocols 5 to 8 keep their declared meaning.

## Results (`evidence/wp15/run8a-train/`, `policies8/`, `run8b-eval/`, `promotion8/`)
- **Training (8a, 54 runs, digest `02a19b82…`).** Every history run succeeded. The production
  configuration verified 9 of 9 needed and 9 of 9 unneeded tasks and none of the 9 cold ones
  (three requests each); the unlabeled control verified 7 of 9 unneeded at 2.22 requests. The
  retained decisions gave 48 samples with 8 positives, all in the layout
  `progress-channels-v1.document-progress-v1`. Leave-one-family-out validation: the channel
  readout's mean log-loss 1.45 against the rule's 3.14 (cold family held out and the readout
  trained on 12 samples without a hopeless case: loss 1.42, accuracy 0.08, against the rule's
  6.91; unneeded held out: 1.12 against 2.51; needed: one sample); the recurrent readout 1.77;
  the channel readout selected. Resubstitution loss 0.18 at accuracy 0.94. Its largest weights:
  `expected_source_absent` -2.34, `repair_fraction` -1.21, `forbidden_present` +1.05.
- **Evaluation (8b, 90 runs, digest `5563390a…`, candidate `readout-channels-v2-f164ed8e44e7`).**

  | arm | all tasks (30) | held-out families (12) | needed-cold-held-out | needed-held-out | unneeded-held-out |
  |---|---|---|---|---|---|
  | gabriel_associative (rule) | 20/30, 1.80 requests, 5346 tokens | 8/12, 1.83, 5425 | 0/4, 3.00 | 4/4, 1.50 | 4/4, 1.00 |
  | gabriel_policy (readout) | 19/30, 1.03, 2946 | 8/12, 1.00, 2836 | 0/4, 1.00, 4 stops | 4/4, 1.00 | 4/4, 1.00 |
  | gabriel_reference_plan | 10/30, 2.40, 7230 | 4/12, 2.50, 7530 | 0/4, 3.50 | 0/4, 3.00 | 4/4, 1.00 |

  - Held-out criterion **met**: verified success equal (8 of 12 each), 2836 against 5425 mean
    tokens, no false completion. On the held-out cold topics the readout stopped every hopeless
    repair at its first decision (p = 0.044); on the held-out needed and unneeded topics no
    decision point fired and the arms are identical.
  - Decision loss on the held-out decisions: readout 0.045 against the rule's 6.91 (4 decisions,
    all stops of hopeless runs, all labeled 0; a one-sided comparison, since no recoverable
    first failure occurred on the held-out topics).
  - Promotion: `promoted`, held-out effective support 8 against 4 refutations, the training
    families disjoint from the held-out families; candidate `readout-channels-v2-f164ed8e44e7`.
  - The cost, measured on a seen task: on da-fee (repetition 1) the readout stopped a
    recoverable repair (p = 0.309: required statement missing, expected source present, one such
    positive sample in training), so the seen needed family verified 5 of 6 against 6 of 6; the
    paired difference over all tasks is -0.03 success, -2401 tokens, -0.77 requests.
- **Consequence applied:** the readout is the document pack's default routing policy (above).

## What this establishes and what it does not
A readout trained on retained decisions of the system's own runs, over declared and committed
facts, met a criterion declared before the run on topics disjoint from its training, was
admitted by the memory's promotion rule, and ships pinned with its provenance. That is the
blueprint's G3 in its scoped sense: a versioned routing policy that improves a declared held-out
criterion (cost at equal verified success) with the regression gates intact. What the readout
learned is small and legible: it stops when the unmet claim expects a source the retrieval did
not carry; it cannot raise verified success, and it stopped one recoverable repair on a seen
task. One provider, one pack, one constructed distribution, 48 training decisions with 8
positives; the held-out decisions were of one class. No learning claim beyond the fitted
logistic readout follows, and the engine's quarantined paths stay quarantined.

## Transfer (protocol 9, `evidence/wp15/run9/`)
The promoted readout, weights fixed, pinned on gpt-5-mini runs it had never seen a decision of:
on the held-out families it equalled the rule-based production configuration (8 of 12) at 4018
against 8766 mean tokens, no false completion; it stopped all 10 cold repairs at the first
decision (p = 0.044), abstained and was refused 0 times, and stopped no recoverable repair. The
pack's declared channels are committed facts, so the fact the readout learned transfers with
them; what a readout trained on gpt-5-mini's own decisions would learn was not tested. Scope:
two providers of one vendor (`docs/EVALUATION_PROTOCOL.md`, protocol 9).
