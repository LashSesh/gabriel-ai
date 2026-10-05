# ADR-23: Erosion of the association history

**Status:** accepted. **Affects:** `memory/association.py` (`supported_claims` as of the
frontier from the chain; `cocitation_history` projected onto the retrieval's candidates with the
erosion summary; status `eroded`), `memory/service.py` (`_candidates`, `_manifest`,
`reproduce`; `_authorized` at an access policy revision), `contracts/schemas/retrieval-manifest.schema.json`
(`erosion`, status `eroded`), `interfaces/cli.py` (`gabriel memory reproduce`),
`evaluation/fixtures/document_association.py` (declared withdrawal), `scripts/association_erosion_witness.py`,
`evidence/wp16/`.

## Context
ADR-20 built the association history from every supported claim available at the frontier and
projected nothing: the engine's walk ran over the source keys of all supporting observations,
whether or not the retrieving principal could retrieve them. Four consequences, each verified in
the code and the tests as they stood before this ADR:

1. **The walk saw what the principal could not.** A revoked source and a source of another
   principal stayed in the graph as entities (the test asserted four entities: charter, annex,
   secret, foreign). The masses read out at the retrievable candidates were masses of a graph the
   principal could not see; the rule "the walk never adds a source" held, the rule "authorization
   is applied before any association is computed" held for the candidates only.
2. **The record disclosed them.** `entities` named every key of the history, so a retained
   manifest, which the principal's own run holds, named sources outside the principal's scope.
3. **A withdrawal did not erode.** A revocation changes the access policy; only a retraction
   reopens the claims that cited the source. The document pack declares withdrawals (`access:
   revoked`) and never retracts, so a source withdrawn after a verified run had cited it kept
   linking the sources it was cited with, for every later retrieval.
4. **The history was not reproducible.** It read the current claim table (status as of now)
   restricted to `seq <= frontier`; after a reassessment the same frontier yielded another
   history, so a retained manifest could not be recomputed from the chain.

One more fact shapes the rule: the document pack ingests every declared source per task (at the
time of this ADR the observation's scope carried the task id; since ADR-25 the scope carries the
principal and the source kind only, so a source that several tasks declare unchanged is one
observation), so a withdrawal names one observation of a source key, and the key leaves
retrieval because the revision rule selects that latest observation. Erosion therefore has to be
defined on keys as the retrieval sees them, not on observation ids.

## Decision
- **The walk runs over this retrieval's candidates and nothing else.** Step 1 of a retrieval
  (`_candidates`) now also returns, for every source key at the frontier, whether the retrieval
  admitted it or why not (`revoked`, `out_of_scope`, `kind_not_allowed`, `contested`,
  `unresolved_revision`). The association history is every supported claim at the frontier
  projected onto its retrievable keys; a claim contributes only while at least two of its keys
  remain (one key says nothing about co-citation). Entities, seeds, links, masses and the batch
  digest are computed over the projection; the record never names a key the retrieval could not
  admit. What was removed is retained in the record (`erosion`: policy revision, claims
  available, claims contributing, keys removed, reasons), and a history whose every claim eroded
  is reported as `eroded`, not as `no_history`; the retrieval then stays lexical and says why.
- **Claims are read as of the frontier from the chain.** `supported_claims` takes the latest
  claim record at or before the frontier for every claim id and keeps those with the assessment
  `supported`. A retraction or reassessment after the frontier changes later retrievals and
  never an earlier one.
- **The access policy revision is explicit.** Authorization takes the revision at which it is
  evaluated (`_authorized(observation, principal, policy_revision)`); a revocation recorded at a
  later revision does not apply. A retrieval is thereby a function of the chain at its frontier,
  the revocations at its access policy revision, the principal and the declared parameters, all
  of which its manifest already carried.
- **Every retained manifest reproduces.** `MemoryService.reproduce(manifest)` recomputes a
  manifest from the chain at its own frontier and revision, bypassing the cache, and compares
  items, exclusions and the association record field by field (`gabriel memory reproduce
  --manifest <sha256>`). A difference is a finding with the field's name; `reproduced` is the only
  passing status.
- **Retraction and revocation stay distinct.** A retraction says the deliverable's basis was
  wrong: it reopens the claim (ADR-14) and the claim drops from the history entirely. A
  withdrawal says a source may no longer be used: the claim's remaining keys were still cited
  together in a verified deliverable, so they keep linking each other while two or more remain.
  Both are erosion; neither is silent.
- **The document pack's declaration semantics are unchanged.** Each task declares the access of
  its sources. A withdrawal declared in one task persists for later tasks that do not re-declare
  the source (the key's effective observation stays the revoked one). At the time of this ADR a
  task that declared the source available again overrode the withdrawal, because every task
  ingested its own observation of the source; since ADR-25 an unchanged source is one observation
  across tasks, so the withdrawal holds until a task declares a new revision of the source (a new
  observation that the revision rule selects; new bytes or a new declaration at the same revision
  are a second observation of that revision, which makes the key contested and keeps it out).
  This is the pack's rule, recorded here, not a memory rule; see the limits below.
- **Protocols 6 to 9 are unaffected by construction.** The association tier declares no
  withdrawn source, one principal and document sources only, and every history claim cites two
  sources that stay retrievable, so the projection is the identity on those runs; the harness
  self-test with the scripted deliverables is unchanged.

## Witness (`evidence/wp16/`, `linux_namespace`, scripted provider)
Three document tasks through one workspace (`scripts/association_erosion_witness.py`); the
provider is the fixture's scripted correct deliverable, because the mechanism under witness is
the memory's, not a model's.

| step | state | access policy revision | association | annex in the prompt | erosion |
|---|---|---|---|---|---|
| history (cites charter and annex) | succeeded, claim supported | 0 | no history | lexically retrieved | - |
| summary, associative view | succeeded | 0 | computed | carried to rank 2 at 230 milli, with its reason | 1 of 1 claims, nothing removed |
| summary, annex declared withdrawn | failed (annex unavailable) | 1 | **eroded** | absent; excluded `revoked`; no association heading, no annex figure | 0 of 2 claims, removed `{revoked: 2}` |

Both retained manifests reproduce from the chain through the service and through the CLI
(`differences: []`); the earlier one at its own revision 0 while the memory stands at revision 1
(`computed -> computed`), the later one `eroded -> eroded`. The owner's journal replays and the
memory chain verifies with the one revocation record the run appended. The unit test adds the
chain-level case the pack cannot produce: after a retraction reopens the claim, the manifest
retained while it was supported still reproduces, a new retrieval at that manifest's frontier
erodes (`removed_by: {revoked: 3}`), and a retrieval at the current frontier has no history.

## What this establishes and what it does not
Established: entities are a subset of the retrieval's candidates by construction; a declared
withdrawal erodes the history through the owner; every retained retrieval manifest is a function
of the chain at its frontier and revision and recomputes bit for bit across a later revocation
and a later retraction. Not established: any effect on a model (no provider run; a model that
is not shown a withdrawn source cannot cite it, which the pack's citation binding enforces
regardless of this ADR); erosion by time (a claim contributes or not, there is no decay); a
key-level access rule (at the time of this ADR the pack re-admitted a withdrawn source as soon as
a later task declared it available, because each task ingested its own observation; since
ADR-25 an unchanged source is one observation across tasks and the withdrawal holds until a
task declares a new revision of the source, which the memory cannot tell from a restored one; a
key-level access rule would still be a new contract). Cost: an uncached retrieval with the
profile loads every claim record at or before its frontier from the store; claims are few per
workspace here and the manifest is cached per frontier and revision.
