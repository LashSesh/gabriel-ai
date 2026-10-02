# ADR-16: Advantage gate on the document and numerical families with declared memory ablations

**Status:** accepted (evaluation design, protocol 5). **Affects:** `evaluation/corpus_domains.py`,
`evaluation/comparators_domains.py`, `evaluation/harness.py`, `domains/document/pack.py`,
`memory/service.py`, `models/scripted.py`.

## Context
The blueprint names three task families for the advantage comparison after G1 and asks for
ablations of one mechanism at a time: provenance-aware retrieval, revision-aware memory,
recurrent routing and native analytical workers. Protocols 1 to 4 compared the systems on the
repository-repair family only; the document and numerical packs were established for G2 with
one fixture task each and no matched baseline. The memory mechanisms the blueprint builds on
(effective revision, availability and authorization before scoring) therefore had no measured
end-to-end effect.

## Decision
- **Corpora with executed controls.** `corpus_domains.py` adds a `document` tier (families
  `revision`: the same document in two declared revisions; `revoked`: a withdrawn document that
  still sits in the repository; `conflict`: two available sources with a declared precedence)
  and a `numerical` tier (`units`, `resample`, `graph`) whose reference values are computed by
  code independent of the analytical adapter. Every task carries a correct deliverable that
  passes and wrong deliverables (stale value, revoked source, uncited statement, wrong numbers,
  wrong units, wrong path, edited source) that fail the module's verification;
  `gabriel eval corpus-check --tier document|numerical` executes them.
- **System-independent, content-based verification.** Citations are resolved by content: a
  quote must be a verbatim span of an available declared source; a required claim must be
  present and cited from the expected source revision with its decisive text; forbidden
  statements (the stale or withdrawn figure) must be absent; nothing outside the scope may
  change. Numerical outputs are compared with the reference within the declared tolerance.
  No observation id of any system is interpreted.
- **Declared ablations instead of hidden switches.** A document task declares its
  `retrieval_view` in its source declaration (base input, digest bound): `provenance` (the
  production default: effective revision, authorized and available at the frontier),
  `all_revisions` (every eligible revision; revocation and authorization still apply; a new
  explicit `version_policy` of the memory service) or `plain` (every declared file, whatever
  its revision or access; not a memory retrieval). A source may be declared `revoked`: it is
  ingested for audit and revoked before any retrieval, so the production view excludes it and
  the citation binding rejects it. Revisions of one document share a declared `object_id`.
- **Matched comparators.** `provider_only` and `simple_loop` see the plain view (what a minimal
  agent with the same corpus has); the simple loop runs the independent checks itself and
  iterates. `gabriel_reference_plan` is the production arm; `gabriel_plain_sources` and
  `gabriel_all_revisions` remove one mechanism each. Numerical baselines execute the declared
  operation through the same adapter in process; Gabriel runs it in the contained worker.
- **Protocol discipline.** A pilot with a declared minimum relevant effect precedes the freeze;
  the final protocol holds out the `conflict` and `graph` families; paired differences report
  verified success and model cost per task for every declared pair.

## Consequences
The advantage gate can be assessed on all three families with the same denominators. The
scripted provider gained `{{obs:<source>@<revision>}}`, `{{obs:file:<path>}}` and
`{{sha:<path>}}` placeholders so that repair rounds and plain-view prompts can be scripted
deterministically. A corpus digest is now pinned per tier, so adding a tier does not invalidate
protocols frozen on other tiers (protocols 1 to 4 keep their legacy digest). What a result
means is bounded as before: one provider, synthetic tasks, one host.
