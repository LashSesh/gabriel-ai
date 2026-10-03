# Protocol 9 declaration: a second provider on the association tier

Written before any run of the association tier with a provider other than gpt-4.1-mini. The
frozen files are `pilot9.frozen.json` (feasibility pilot) and `protocol9.frozen.json`; the
executed runs `pilot9-run/` and `run9/`.

## Question
Every claim of ADR-20, ADR-21 and ADR-22 rests on one provider, gpt-4.1-mini. Do the three
mechanisms hold for a second provider of a different model family, gpt-5-mini (a reasoning
model, served through the same OpenAI-compatible endpoint, no sampling temperature, the same
budgets), and does the readout promoted under protocol 8, trained on gpt-4.1-mini's retained
decisions and not retrained, transfer to it?

## Mechanisms under test, as specified
- ADR-20: the associative view carries a source linked to the task only by verified co-citation
  into a budgeted prompt and changes the verified outcome.
- ADR-21: carried sources say in the prompt why they are there; the model then uses them where
  the goal asks and not where it forbids.
- ADR-22: the shipped readout (`readout-channels-v2-f164ed8e44e7`, weights fixed) stops a
  hopeless repair at its first decision and abstains where its channels are missing; the
  document pack's declared channels are committed facts, provider-independent by construction.

## Corpus
The association tier as frozen for protocol 8 (digest `5f761d33…`): all seventeen evaluated
tasks (`da-`, `dc-`, `du-` of the five topics, `dn-` of two), every history run first in the same
workspace through the scripted provider. Nothing in the corpus was built or changed with
gpt-5-mini in view. The held-out families of protocol 8 (library and garden: needed, cold and
unneeded) stay named as held out for the readout, which never saw them in training.

## Pilot (feasibility of the provider configuration only)
Six runs (da-fee, dc-fee, du-fee; arms `gabriel_associative` and `gabriel_policy`; one
repetition) to see that gpt-5-mini answers the document prompts within the matched output
budget (4000 completion tokens, reasoning included) and the request limits. The pilot may
change nothing but a provider setting that makes requests complete (timeout, output budget,
declared beside the result); the corpus, the arms, the rules below and the readout are frozen
here and not touched after the pilot. The pilot's runs are retained and not counted.

## Arms
`gabriel_reference_plan` (provenance view, rule-based), `gabriel_associative` (labeled
associative view, rule-based: the production configuration under the rule),
`gabriel_associative_unlabeled` (ADR-20 presentation, rule-based) and `gabriel_policy` (the
production configuration with the promoted readout pinned). Two repetitions, `linux_namespace`,
budgets of protocols 5 to 8; 136 runs.

## Pre-declared rules
- R1 (ADR-20): on `association-needed` and `association-needed-held-out`, verified success of
  `gabriel_associative` exceeds `gabriel_reference_plan` by at least 0.5 (paired per task).
- R2 (ADR-21): on `association-unneeded` and `association-unneeded-held-out` (ten runs),
  verified success of `gabriel_associative` is not worse than `gabriel_reference_plan` by more
  than one run, and false completions are not more frequent; the number of first attempts that
  state the forbidden figure is reported for the labeled and the unlabeled arm.
- R3 (ADR-22): on the held-out families of protocol 8, `gabriel_policy` reaches at least the
  verified success of `gabriel_associative`, with fewer mean model tokens and no false
  completion; and on every cold task (seen and held out) the readout stops the repair at its
  first decision. Refusals (layout mismatch) and abstentions are counted and reported.
- `association-none`: the Gabriel arms are equal.
- Provider statuses other than `completed` (truncated, invalid output, refusal) are counted per
  arm and reported; a unit that ends on them stays in the denominator.
- Consequence, declared now: a rule that holds extends the respective ADR's claim to a second
  provider in the docs, as a replication under the same protocol discipline; a rule that fails
  is recorded as a provider dependence of that mechanism, the defaults promoted under protocols
  7 and 8 stay as they are (they were promoted on their own evidence), and the known issues name
  the dependence.

## What this protocol cannot establish
Generality across providers: two providers of one vendor through one API. A transfer of the
readout is a test of its weights on a different distribution of decisions; it cannot say what a
readout trained on gpt-5-mini's decisions would have learned.
