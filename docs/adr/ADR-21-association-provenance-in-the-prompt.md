# ADR-21: Association provenance in the prompt

**Status:** accepted. **Affects:** `memory/association.py` (`cocitation_history`, `links`),
`memory/service.py` (`lexical_milli` per item), `contracts/schemas/retrieval-manifest.schema.json`,
`domains/document/pack.py` (the associative view's prompt; ablation view `associative_unlabeled`),
the document pack's schemas, `evaluation/comparators_domains.py` (arm
`gabriel_associative_unlabeled`), `evidence/wp15/protocol7_declaration.md`.

## Context
Protocol 6b (ADR-20) established that the engine's walk over verified co-citations carries a
source that shares no word with the goal into a budgeted prompt and changes the verified
outcome (10 of 10 needed tasks against 0 of 10 for the provenance view). It also measured the
cost: in all six first attempts on the unneeded family the model stated the figure the task
forbade, the verification loop repaired four, and the declared harm bound of one run in six
was exceeded by one. The carried source entered the prompt exactly like a lexically retrieved
one; nothing told the model that it had not been retrieved for the goal's words. The structural
score cannot tell a needed carried source from an unneeded one (the history is the same for
both), so the distinction has to be made where the source is used, and the system has what it
takes to make it: the manifest knows why every item is there.

## Decision
- **The manifest keeps the reason.** Every item retains its lexical score beside the structural
  one (`lexical_milli`). The association record carries `links`: for every carried key (mass
  from the walk and not a seed itself) the seeds it was cited together with, and the claim ids
  and task ids of the verified runs whose claims cite them together (`cocitation_history`
  returns the batches with their provenance; the batch digest is unchanged). A key reached only
  through other keys is marked `direct: false` with the claims that cite it at all.
- **The associative view tells carried sources apart.** The prompt lists the lexically retrieved
  sources as before and then, under its own heading ("Sources associated by verified history:
  not retrieved for the goal's words, each was cited together with a source above in an earlier
  verified run; use one only where the goal needs it"), every carried source with its reason
  ("associated: cited together with charter in verified run history-dh-fee"), and closes the
  rules with "State only what the goal asks for; a source associated by history is available,
  not required." Which items are carried is read from the manifest's `links`, never recomputed
  in the prompt builder. The byte budget is applied in rank order as before; only the
  presentation is grouped.
- **The ablation `associative_unlabeled`** is the same retrieval with the ADR-20 presentation,
  so the labeling can be measured against the carrying within one protocol.
- **Protocol 7** (`evidence/wp15/protocol7_declaration.md`, frozen before the run) compares the
  labeled view with the provenance view and the unlabeled control on the tier of protocol 6b,
  two repetitions, gpt-4.1-mini, `linux_namespace`: the needed rule of protocol 6 (at least
  +0.5), the harm rule as the decision rule (not worse than the provenance view by more than
  one run in six on the unneeded family, no more false completions), equality on the no-history
  family, and the consequence declared in advance: if the rules hold, the associative view
  becomes the document pack's default; if the harm rule fails again, it stays declared per task.

## Results (`evidence/wp15/run7/`, 60 runs, protocol digest `ce24ada6…`, corpus digest `d3517d87…`)

| family | gabriel_reference_plan | gabriel_associative (labeled) | gabriel_associative_unlabeled |
|---|---|---|---|
| needed, seen (6) | 0/6, 3.00 requests, 9190 tokens | 6/6, 1.67 requests, 5016 tokens | 6/6, 1.00, 2845 |
| needed, held out (4) | 0/4, 3.00, 9147 | 4/4, 1.00, 2911 | 4/4, 1.00, 2837 |
| unneeded (6) | 6/6, 1.00, 2794 | 6/6, 1.00, 2861 | 4/6, 2.33, 6945 |
| none (4) | 4/4, 1.00, 787 | 4/4, 1.00, 794 | 4/4, 1.00, 783 |

- Needed rule **met** (+1.00 on every task, held-out included); the visible source reached every
  budgeted prompt and the hidden source every associative prompt (`retrieval_analysis.json`).
- Harm rule **met**: on the unneeded family the labeled view equals the provenance view (6 of 6
  at one request); no first attempt stated the forbidden figure, against 6 of 6 for the
  unlabeled control, which reproduced run 6b exactly (4 of 6, two repair budgets exhausted on
  du-archive). False completions: none in any arm.
- `association-none`: equal.
- The labeling has a cost of its own, reported because it was measured: on da-fee (both
  repetitions) the labeled model's first attempt stated the charter's rule and left the annex
  figure out, the claims check named the missing statement, and the repair added it with the
  citation (three requests instead of one); the other four needed tasks succeeded at one
  request. Over all twenty tasks the labeled view is the cheapest arm (1.20 requests, 3104
  tokens against 1.40 and 3661 unlabeled, 2.00 and 5582 provenance) and the only one that
  verified every task.
- Consequence, as declared: **the associative view is the document pack's default** since this
  ADR (`DEFAULT_VIEW`). The harness names every arm's view explicitly, so protocols 5 to 7 stay
  reproducible; without history or executables the default ranks exactly like the provenance
  view and the manifest records why (`no_history`, `unavailable`).

## What this establishes and what it does not
The reason a source is in the prompt is now part of the retrieval's retained record and of what
the model sees, and under this provider that changed the use of carried sources from "always"
to "where the goal asks". It is one provider's response to one presentation on one constructed
distribution, with the matched unlabeled control in the same run; it is not a general claim
about labels, and the da-fee cost shows the presentation can also make the model too cautious.
The walk, the claims and the manifest are unchanged from ADR-20; no learning claim follows.

## Replication (protocol 9, `evidence/wp15/run9/`)
Under gpt-5-mini the labeled view equalled the provenance view on the unneeded families (10 of
10 at one request) and no first attempt stated the forbidden figure; the unlabeled control
stated it in 4 of 10 first attempts and needed a repair in 6, which gpt-5-mini then repaired
every time (where gpt-4.1-mini had lost 2 of 6). The presentation's effect on the first attempt
holds for both providers; its effect on the verified outcome depends on how well the provider
repairs. Scope: two providers of one vendor (`docs/EVALUATION_PROTOCOL.md`, protocol 9).
