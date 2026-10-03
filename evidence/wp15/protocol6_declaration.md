# Protocol 6 declaration: the associative memory layer (ADR-20)

Written before any run of the association tier with a real provider; the frozen protocol file
is `protocol6.frozen.json`, the executed run is under `run6/`.

## Question
Does the associative view (the provenance view re-ranked by the native engine's walk over the
co-citation graph of claims that earlier verified runs established) change verified outcomes on
tasks whose required source a budgeted lexical retrieval cannot carry, and does it do harm where
it is not needed?

## Mechanism under test, as specified
A verified document run records a supported claim citing the observations of its deliverable.
A later retrieval with the associative profile seeds the engine's walk on the lexically matching
sources and ranks every retrievable candidate by the larger of its lexical score and its walk
mass at the declared time; authorization, the revision rule, revocation and the frontier apply
before the walk, which can only re-rank and never add a source. The reference implementation
of the walk is the standard-library spectral decomposition of `evaluation/fixtures/graph_walk.py`.

## Corpus (tier `association`, digest frozen with the protocol)
- `association-needed` (3 tasks, seen) and `association-needed-held-out` (2 tasks, held out):
  the required source shares no token with the goal and competes with 36 scored distractors
  under the pack's budget of 32 retrieved items; a history task cites it together with the
  visible source in a verified run.
- `association-unneeded` (3 tasks): the same history, but the task needs the visible source
  only and the hidden figure must not be stated (forbidden statement).
- `association-none` (2 tasks): no history, two sources, no budget pressure: both views reach
  both sources.
- Every history task runs first in the same workspace with its correct deliverable through the
  scripted provider, for every Gabriel arm alike; the baselines do not use the memory.

## Arms
`provider_only` and `simple_loop` (plain view: every declared file in the prompt, no budget),
`gabriel_reference_plan` (provenance view; the matched comparator) and `gabriel_associative`
(associative view). Same provider, budgets, backend (`linux_namespace`), reference plan and two
repetitions at temperature 0.

## Pre-declared expectations and decision rules
- Primary: on `association-needed` and `association-needed-held-out`, verified success of
  `gabriel_associative` exceeds `gabriel_reference_plan` by at least 0.5 (absolute, paired per
  task, mean over repetitions). The minimum relevant effect is 0.5 because the mechanism either
  carries the hidden source or it does not; smaller differences are noise of the provider.
- Harm: on `association-unneeded`, false completions and verified success of
  `gabriel_associative` are not worse than `gabriel_reference_plan` by more than one run in
  six; on `association-none`, the two arms are equal.
- The held-out family decides: the mechanism claim is made only if the primary expectation
  holds on `association-needed-held-out` as well.
- `provider_only` and `simple_loop` see every file without a budget; their results bound what
  an unbudgeted prompt achieves and are reported, not compared for the mechanism claim.
- Any failure of a history run is a protocol defect, reported as such; the unit stays in the
  denominator.

## What this protocol cannot establish
A general retrieval advantage. The corpus is constructed so that the mechanism's precondition
holds (a hidden source linked only by verified co-citation); the result is a mechanism test with
negative controls, scoped to that precondition, under one provider.

## Amendment after run 6 (written before any run of the amended corpus)
Run 6 (`protocol6.frozen.json`, corpus digest `17ab990d…`, 80 runs, retained unchanged under
`run6/` with every final diff) found a construction defect of the tier, not a property of the
mechanism. The distractors read "The <subject> states that the committee meets on the first
Tuesday of the month", naming the visible source's subject word. Under the memory service's
scorer (token overlap per paragraph with the whole goal) they tied with the visible source in
three of five topics (parking, library, garden: 4 shared tokens each) and in the archive topic
(5 each); only the fee topic's charter outranked them (7 against 5). Ties are broken by
observation id, which differs per workspace, so the visible source itself fell below the budget
of 32 items in 25 of the 32 budgeted Gabriel runs (`run6/retrieval_analysis.json`): neither arm
had the visible source in the prompt, the walk had no seed (`no_seeds_in_history` in 13 of the
16 budgeted associative runs), and both
arms failed alike on `association-unneeded` (0 of 6 each) and on every needed task but da-fee
and one repetition of da-archive. Where the precondition held, the mechanism behaved as
specified: da-fee 2 of 2 verified against 0 of 2 for the provenance arm (charter seeded at 770
milli, annex carried at 230 milli to the second rank), da-archive repetition 1 likewise. The
distractors also lured the model into citing them as the visible source's statements where
the visible source was absent. Against the pre-declared rules, run 6 is **not met** (needed
+0.50 at the limit, held-out +0.00, the held-out family decides).

The amendment, made once and recorded here before any further run:
- The distractor text names no source ("Minutes of the committee meeting held on the first
  Tuesday: quorum reached, no resolutions."); it still shares the goal's function words, so it
  outranks the hidden source and fills the budget.
- An executed construction invariant (`corpus_domains._assert_ranking`): for every evaluated and
  unneeded goal, under the service's own scorer, the visible source scores strictly above every
  distractor, every distractor scores above zero, and the hidden source scores strictly below
  every distractor (for the needed goal it shares no token at all, as before). A test executes
  the precondition for every topic through the service under the pack's budget
  (`tests/test_association.py`).
- Sources, asks, oracles, histories, families, arms, budgets, repetitions, provider and the
  decision rules are unchanged. The amended tier is frozen as `protocol6b.frozen.json` with its
  own corpus digest; the executed run is `run6b/`.
- Held-out status: the `association-needed-held-out` family (library, garden) was executed once
  under the defective corpus, where its visible source never reached a prompt; the amendment is a
  tier-wide rule, not a change to those topics. It is reported as held out from corpus
  development, with that qualification.
