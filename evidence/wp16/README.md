# ADR-23 witness: erosion of the association history

| File | Content |
|------|---------|
| `report.md` | The three tasks through one workspace in `linux_namespace` (history, associative summary, summary with the annex declared withdrawn): run states, access policy revisions, association statuses, what the prompt carried, the erosion summaries, both reproductions (service and CLI), the checks and the chain verification |
| `witness.json` | Every value of the report with the retrieval manifest digests, the association records (entities, seeds, masses, links, erosion), the exclusion reasons of the annex, the prompt facts, the revocation record, the owner replay and memory anchor, the `engine_observer` digest |
| `manifest-history.json`, `manifest-summary_associative.json`, `manifest-summary_annex_withdrawn.json` | The three retrieval manifests exactly as retained in the workspace's object store |

Produced by `scripts/association_erosion_witness.py --out evidence/wp16 --backend linux_namespace`
with the scripted provider (the fixture's correct deliverables): the mechanism under witness is
the memory's. The workspace under `work/` (repository, worktrees, objects, principal secret) is
not committed. The regression evidence is `tests/test_association.py` in `evidence/test_results.txt`.
