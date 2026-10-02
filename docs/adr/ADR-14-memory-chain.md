# ADR-14: Memory chain beside the journal

**Status:** accepted. **Affects:** workspace layout (`memory.sqlite`), backup/restore, document pack.

## Context
The blueprint separates three stores: the owner's event journal (exact episodic history), an
artifact/evidence index (searchable source fragments with provenance) and derived task
summaries. Observations, claims, outcome labels and policy candidates are workspace-level
records with their own availability order; the run-scoped command set of the owner is closed
and should not absorb them.

## Decision
`memory/service.py` keeps an append-only index in `memory.sqlite` with its own hash chain
(`gabriel.memory/1:` prefix over kind, sequence, record digest, owner sequence and previous
head). Every record is a canonical artifact in the shared object store, validated against the
closed schemas `observation`, `claim`, `claim-assessment`, `outcome-label`,
`access-revocation`, `policy-candidate` and `compaction-manifest`. The availability frontier of
a decision is the pair (owner sequence, memory sequence); a model request retains the selected
observation ids and the retrieval manifest records the frontier and the access policy revision.
Retrieval authorizes and filters by frontier before scoring; its cache is keyed by the same
authorization and frontier, so a revocation can never be served from it. Backup copies the
index through SQLite's online backup together with every artifact it references and its
anchor; restore recomputes the chain and verifies every byte.

## Consequences
The journal stays the only authority for run state; the memory chain is an additional
integrity commitment over evidence provenance. A missing referenced blob is a storage fault in
`verify`, `compact` and `restore`, never a successful compacted record. Summaries and cache
rows are derived and are the only rows compaction removes.
