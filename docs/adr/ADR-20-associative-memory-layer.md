# ADR-20: The associative memory layer

**Status:** accepted. **Affects:** `memory/association.py` (new), `memory/service.py` (retrieval
with a declared association profile), `contracts/schemas/retrieval-manifest.schema.json`,
`domains/base.py` (`claims_after_success`), `domains/document/pack.py` (view `associative`,
claims from verified runs), `agent/runner.py` (claims recorded after a succeeded run),
`evaluation/corpus_domains.py` (tier `association` with history tasks),
`evaluation/comparators_domains.py` (arm `gabriel_associative`, history runs),
`evaluation/harness.py`, `evaluation/fixtures/document_association.py`.

## Context
ADR-18 and ADR-19 made the native engine a deterministic, specified, independently referenced
worker. Nothing in the system used it for what the system does: retrieving what a task needs
from what the system has established. Retrieval in the memory service (ADR-14) ranks the
authorized, eligible observations lexically and truncates by budget; a source whose words share
nothing with the goal is retrievable only while the budget is slack. The document pack had no
notion of what earlier verified runs cited together: claims existed in the memory's contract
but nothing wrote them. The question of this ADR is whether the engine's walk over the history
of verified co-citations can carry such a source into a budgeted retrieval, under the existing
authorization, revision and frontier rules, and whether that is worth anything under a frozen
protocol.

## Decision
- **Verified runs establish claims.** A domain pack may declare what a succeeded run
  establishes (`claims_after_success`): the document pack returns, for every target whose
  citations all resolved at the run's frontier, the target's content as a proposition supported
  by the cited observations, read from the retained citation report of the last review. The
  runner records those as claims with the assessment `supported` by `document.citations_bound`
  after the run's independent checks passed. A failed run establishes nothing. The log names
  every claim.
- **Association history is the co-citation graph of supported claims.** For a retrieval at a
  frontier, the source keys of the supporting observations of every supported claim available
  at that frontier form one observation batch each, in chain order. The engine's co-observation
  graph of those batches (ADR-18) is the association structure; a source cited together with
  others in several verified runs is linked to them with the engine's declared rule.
- **A declared association profile re-ranks; it never adds.** `MemoryService.retrieve` takes
  an optional profile (`co-citation-walk-v1`: walk time 1, automatic backend, at most eight
  seeds, the 64-entity cap, the combination `max`). Authorization, the revision rule, revocation,
  kind filtering and the frontier are applied first and unchanged; only the authorized,
  eligible candidates are scored. The lexically matching candidates seed the walk (uniform
  amplitude), the engine (`engine_observer`, bound by digest and validated as in ADR-18) reads
  out the regional mass at every candidate at the declared time, and a candidate's score is the
  larger of its lexical score and its mass in milli. The budget then applies as before.
- **Everything is retained.** The manifest carries, per item, the structural score and, at the
  top level, the association record: profile, status (`computed`, `no_history`, `no_seeds`,
  `no_seeds_in_history`, `capacity_exceeded`, `unavailable`), executable digest, digest of the
  batches, entities, seeds, snapshot identity and masses. The cache key covers the profile.
  Beyond the entity cap the walk is restricted to the batches that touch a seed, and beyond that
  it is declared unavailable in the record; the retrieval then stays lexical, and says so.
- **The document pack's view `associative`** is the provenance view with the profile; the
  default view is unchanged. The baseline views of ADR-16 are unchanged.
- **The reference.** The structural score equals the standard-library spectral walk of
  `evaluation/fixtures/graph_walk.py` over the co-citation graph (test bound 1e-9 of a milli).
- **Corpus tier `association`.** Five topics, each with a history task (role `history`, never
  an evaluation unit) whose goal reaches a visible and a hidden source lexically and whose
  correct deliverable cites both; evaluated tasks whose hidden source shares no token with the
  goal and competes with 36 scored distractors under the pack's budget of 32 items
  (`association-needed`, 3 seen, `association-needed-held-out`, 2 held out); tasks with the
  same history that need the visible source only and must not state the hidden figure
  (`association-unneeded`, 3); tasks without history or budget pressure (`association-none`,
  2). The precondition is executed at corpus construction under the memory service's own
  scorer (`_assert_hidden`, `_assert_ranking`): for every evaluated goal the visible source
  outranks every distractor strictly, every distractor outranks the hidden source strictly, and
  the needed goal shares no token with the hidden source; a test executes the same through the
  service under the pack's budget for every topic. The harness runs a task's history first in
  the same workspace with its correct deliverable through the scripted provider, for every
  Gabriel arm alike, so the history is produced by the system's own verified runs, not injected.
  `scripts/eval_retrieval_analysis.py` retains, per Gabriel unit of a run, what the retrieval
  carried (ranks, scores, association status, seeds, presence in the prompt).
- **Protocol 6** (`evidence/wp15/protocol6_declaration.md`, frozen before the run) compares
  `gabriel_associative` with its matched comparator `gabriel_reference_plan` (provenance view),
  with `provider_only` and `simple_loop` (every file in the prompt, no budget) as bounds, two
  repetitions, gpt-4.1-mini, `linux_namespace`, a declared minimum relevant effect of 0.5 on the
  needed families including the held-out one, and harm rules on the unneeded family.

## Results (`evidence/wp15/`, `docs/EVALUATION_PROTOCOL.md`)
- **Run 6** (80 runs, corpus digest `17ab990d…`) was lost to a corpus defect and is retained
  unchanged: the distractors named the visible source's subject and tied with it under the
  scorer in four of five topics, the tie-break by observation id dropped the visible source
  itself below the budget in 25 of the 32 budgeted Gabriel runs, and the walk had no seed in 13
  of 16. Where the precondition held (da-fee, one repetition of da-archive) the mechanism did
  what it specifies (3 of 3 against 0 of 3). The declaration records the amendment before any
  further run: distractors that name no source and an executed construction invariant under the
  service's own scorer (`_assert_ranking`).
- **Run 6b** (80 runs, corpus digest `d3517d87…`, same arms, budgets, provider, repetitions
  and decision rules): the visible source reached every budgeted prompt and the walk was seeded
  in every associative run (`run6b/retrieval_analysis.json`).
  - Primary expectation **met, held-out family included**: on `association-needed` and
    `association-needed-held-out` the associative view verified 10 of 10 at one request each
    (2860 mean tokens); the provenance view verified 0 of 10 after three requests each (9129
    tokens), never having the hidden source in its prompt. Paired difference +1.00 on every
    needed task against the declared minimum of 0.5. The retained manifests show the carrier:
    the visible source seeded at 770 milli, the hidden source carried at 230 milli to the second
    rank, the distractors at 54 to 64 milli lexical.
  - Harm rule **not met** on `association-unneeded`: the associative view verified 4 of 6 at
    2.33 requests (6944 tokens) against 6 of 6 at 1.00 request (2786 tokens) for the provenance
    view, two runs worse where the declared bound was one. In all six first attempts the model
    stated the figure the task forbade (the hidden source was in the prompt, the claims check
    recorded `forbidden_present`); the verification loop repaired four at one extra request and
    exhausted its two repairs on `du-archive` twice. False completions: none in either arm (the
    provider-only baseline stated the figure in all six and declared done each time; the simple
    loop lost one of six after six requests).
  - `association-none`: the two arms equal (4 of 4, one request, 784 against 797 tokens), as
    declared.
  - The unbudgeted baselines verified every needed task (they see every file) and are reported,
    not compared.

## What this establishes and what it does not
- The mechanism is specified, deterministic, bound and retained; it cannot leak: the walk runs
  over the authorized candidate set only, after every filter, and a revoked, foreign or
  post-frontier source is never scored or carried.
- Under the frozen protocol it carries a source that only verified co-citation links to the task
  into a budgeted prompt and changes the verified outcome, on seen and held-out topics alike.
  It is a mechanism test with negative controls, scoped to the precondition it constructs,
  under one provider; not a general retrieval advantage, and it does not touch the advantage
  gate of ADR-16. The held-out family was executed once under the defective corpus (where its
  visible source never reached a prompt) before the amended run; the amendment is tier-wide.
- The cost is measured, not assumed: what the walk carries, the model uses, whether the task
  needs it or not. The associative view therefore stays a declared per-task view, not the
  default, and the harm rule's failure is recorded as such. Which sources a goal should not see
  is a question the goal must answer (a forbidden-statement check exists; a retrieval exclusion
  does not), not the walk.
- The lexical seeds are the top-scored candidates with ties broken by observation id, which
  differs per workspace (ADR-14's scorer, unchanged by this ADR); the corpus invariant excludes
  ties for the tier, the general property remains.
- No learning claim follows: the association history is a declared, inspectable structure of
  what verified runs cited together, and the walk is a specified function of it. The crystal,
  consensus and morphogenic paths of the engine remain quarantined (ADR-19).

## Replication (protocol 9, `evidence/wp15/run9/`)
With gpt-5-mini (a reasoning model of another family, same endpoint, same budgets, 136 runs,
declared before any run) the associative view verified 10 of 10 needed tasks at one request
against 0 of 10 for the provenance view, the hidden source in every associative prompt and no
provenance prompt, as under gpt-4.1-mini. The mechanism's claim holds for two providers of one
vendor; the scope is otherwise unchanged (`docs/EVALUATION_PROTOCOL.md`, protocol 9).
