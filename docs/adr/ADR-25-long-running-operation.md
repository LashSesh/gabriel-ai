# ADR-25: Long-running operation

**Status:** accepted. **Affects:** `memory/association.py` (batch window), `memory/service.py`
(indexes at creation, record cache, compaction counts), `domains/document/pack.py` (one
observation per source across tasks), `agent/backup.py` (closure-complete backup),
`agent/workspace.py` (`retire_worktrees`, a retired run refuses export), `interfaces/cli.py`
(`gabriel retire`; `memory reproduce` refuses a missing manifest), `state/owner.py` (events
index at creation), `contracts/schemas/retrieval-manifest.schema.json` (`window`),
`contracts/schemas/compaction-manifest.schema.json` (counts), `scripts/longrun_witness.py`,
`evidence/ops/longrun/`.

## Context
Every operation of ADR-17 (migration, startup validation, telemetry, metrics, garbage
collection) and of the release discipline (backup, restore) had been witnessed on workspaces of
one task (41 events, 131 objects) or, as a refused migration, of twelve runs. Nothing had run a
workspace through hundreds of tasks, and the code was read for what grows with the tasks and
what bounds it. The reading found six places where growth turned into a failure or an unbounded
cost rather than a declared limit:

1. **The engine's batch cap was a cliff.** `engine_observer` admits at most 128 observation
   batches per job (ADR-18 `CAPS`). The co-citation history of ADR-20 has one batch per
   supported claim, so the 129th verified document run in a workspace made every later
   associative retrieval raise from inside `retrieve` and the document task fail. The entity
   cap (64) was handled by a declared restriction to seed-touching batches; the batch cap was
   not handled at all.
2. **Every task re-ingested its sources.** The document pack's observation scope carried the
   task id, so a source that fifty tasks declared unchanged was fifty observations of one key,
   fifty content and scope objects, and fifty rows the revision rule had to read past. The
   observation table grew with tasks, not with sources.
3. **A backup after a migration could not be restored.** The backup copied the objects the
   journal's artifact table and the memory chain named directly; the catalogs retained for
   earlier epochs and the migration records are referenced from the journal's own rows, not from
   that table, so a restore of a migrated workspace failed its replay with `ARTIFACT_MISSING`.
   The garbage collector already computed the right closure (`roots_of`, `referenced_closure`);
   the backup did not use it.
4. **Worktrees were never removed.** Every task adds a detached git worktree registered in the
   source repository and nothing in the product removed one; a long run leaves hundreds of
   checkouts on disk and in the repository's worktree registration.
5. **The memory index had no secondary indexes and no record cache.** Admission, the revision
   rule, revocations and labels were scanned per key per retrieval, and every retrieval loaded
   every claim record at or before its frontier from the store.
6. **The compaction manifest truncated silently.** Its inventory kept the first 4096 retained
   artifacts and the first 1024 anchors without saying how many there were, and `memory
   reproduce` on a manifest the collector had removed crashed with a Python traceback.

The journal is append-only by contract (ADR-12, ADR-17): no event is ever rewritten or removed,
so a replay, a migration (two replays) and a restore cost time linear in the events. That is
not a defect to fix here but a cost to measure and state.

## Decision
- **The engine's caps are a declared window.** When the history has more batches than the
  engine admits, or more entities than the profile allows, the walk runs over the batches that
  touch a seed, of those the latest in chain order up to the batch cap, and of those the latest
  whose entities fit the entity cap. Only a single batch wider than the entity cap is
  `capacity_exceeded`, and such a record names no seed and no entity, since nothing was walked.
  A fault of the engine itself (a timeout, a changed executable, a non-finite mass) surfaces as
  `WORKER_UNAVAILABLE` through the memory service, never as a bare Python error. The record retains `window: {max_batches, max_entities, available, used,
  rule}` on every record that reached the walk's bounds (`computed`, `unavailable` and
  `capacity_exceeded`; `rule` is `whole history` when nothing was cut), `batches_sha256` covers
  the walked batches and `memory reproduce` compares the window, so an ADR-23 reproduction
  recomputes the same window and the manifest says what the walk did not see. The engine's caps are unchanged; the memory stops asking it for more than it admits. The
  first witness run (retained in the history of this branch, not as evidence) showed why the
  entity cap needs the same treatment as the batch cap: with the window on batches alone, every
  probe after the hub's neighbourhood passed 64 entities was `capacity_exceeded`, so the
  associative view had switched off for the rest of the workspace's life.
- **An unchanged source is one observation across tasks.** The document pack's observation
  scope carries the principal and the source kind; which task used which observation is
  retained per run (the run's retrieval manifest names the task, the citation report the
  observations). The identity of an observation is everything it declares about the source
  except when it was received: key, revision, bytes, extraction, scope, event kind and interval,
  publication time, time basis and authentication. A task that declares the same source the
  same way adds no observation; one that declares it differently adds one, and two
  observations of one revision make the key contested as before. Consequence for ADR-23: a
  withdrawal declared by one task now holds for later tasks until a task declares a new revision
  (ADR-23's limits are amended accordingly), and it holds for every task's next citation
  verification, a task in flight included (tasks run one at a time in this single-user
  deployment, so no such task exists here).
- **The backup carries the referenced closure.** `backup` copies the transitive closure of the
  workspace's roots (the collector's `roots_of` and `referenced_closure`): the retained catalogs
  of every epoch, the migration records, the memory manifests and everything nested in JSON
  artifacts. A root that is missing is a storage fault as before; a reference nested inside a
  JSON artifact (user-supplied content included) that names no stored object is recorded in the
  manifest (`unresolved_nested_references`) and never fails the backup. The deep doctor checks
  the same roots, so a lost catalog of an earlier epoch is reported before a backup or a replay
  fails on it. A restore of a migrated
  workspace replays every epoch under the retained catalogs. The migration record's object is
  stored before the row that names it, so a crash between the two leaves an orphan, never a
  recorded migration the closure cannot find.
- **Worktrees are retired explicitly.** `Workspace.retire_worktrees` (CLI `gabriel retire`)
  removes the worktrees of terminal runs that have no unresolved effect awaiting reconciliation
  (a cancelled run's dispatched attempts become effects of unknown outcome, which the next
  runner start reconciles against the tree), prunes the
  source repositories' registrations, records the retirement in the run's notes and retains a
  report under `<workspace>/retirements/`; an unknown run id is refused. `task export` of a
  retired run refuses with `STORAGE_FAULT` instead of exporting an empty tree, and `task run`
  on it reports the terminal state. The journal, the retained patch and every object are
  untouched; retirement is an operator's step, never automatic.
- **Indexes at creation, a bounded record cache, and counts instead of silent truncation.**
  A new memory index and a new journal are created with the secondary indexes their queries use
  (observations by key and sequence, kind, revocations by observation, labels by source, claims
  by status; events by run and sequence). Existing files are not altered on open, so the
  retained evidence workspaces stay byte for byte what their manifests record. The service keeps
  the last 8192 loaded records in memory and hands out copies. The compaction manifest retains
  `retained_artifact_count` and `anchor_count` beside its bounded lists, and `memory reproduce`
  refuses a missing manifest with `UNKNOWN_OBJECT`.
- **A long-run witness.** `scripts/longrun_witness.py` drives one workspace through 600
  scripted tasks in `linux_namespace` (300 document tasks on a shared hub, half over a fixed
  set of twenty wards so the batch cap is reached, half over new wards so the entity cap is
  reached; 150 software repairs; 150 numerical transformations), an associative probe every 25
  document tasks, memory compaction and `gc --apply` every 100 tasks, a backup, restore and
  migration to a changed catalog at the half, a backup and restore under the new epoch at the
  end, replay, chain verification, the reproduction of the first and last probe's manifest,
  deep diagnostics, metrics, retirement and a final collection. It reads growth back from the
  workspace at every snapshot and derives its verdict from retained facts.

## Results (`evidence/ops/longrun/`)
The witness ran 600 scheduled tasks and 12 probes (612 runs) in 24.8 minutes in
`linux_namespace` with every check passed (`summary.json`, `series.json`, `report.md`).
Read back from the workspace at the end:

| quantity | value |
|---|---|
| journal | 19 836 events, 612 runs, 151.0 MB |
| memory chain | 2 337 entries; 171 document observations for 171 distinct document keys; 312 supported claims; 0 cache rows after each compaction |
| object store | 41 875 objects, 46.1 MB |
| worktrees | 612 (4.9 MB) before retirement, 0 after |
| telemetry | 14.2 MB, 35 400 spans |
| independent checks | 5 820 passed, 0 failed; every run `succeeded` |

The probes (one every 25 document tasks, seeded by the goal's lexical matches with the hub
among them): probes 1 to 5 walked the whole history (25 to 125 claims, 21 entities, 13 keys
carried); probe 6 reached the batch cap (150 claims available, 128 walked, still 21 entities,
13 carried); probe 7 walked 128 of 175 batches over 46 entities and carried 38; probes 8 to 12
(200 to 300 claims, 71 to 171 entities in the history) walked the latest 63 seeded batches
over 64 entities, `computed` with the window declared, and carried nothing. The first and the
last probe's manifests reproduced from the chain after five compactions, six collections, a
migration and a reopen. Retrieval time stayed between 23 and 154 ms; the engine answered in
3 to 15 ms.

The operations, with their durations as the workspace grew: `memory.compact` 117 ms at 753
retained artifacts to 590 ms at 4 116; `gc --apply` 16.0 s over 6 948 objects to 104.2 s over
41 875 (each pass removed the manifests of the compaction before it, 69 or 70 objects, then 35,
then 0, and re-verified replay and chain); backup 3.0 s for 20 594 objects (22.2 MB) and 6.5 s
for 41 875 (46.1 MB); restore 64.0 s at 9 524 replayed events and 138.9 s at 19 836, the second
one across the recorded migration; the migration itself 94.2 s (backup, equivalence replay and
replay after, 9 524 events each); the final replay 92.7 s for 19 836 events, 4.7 ms per event;
`memory.verify` 135 ms; the two reproductions 26 and 49 ms; the deep doctor 1.7 s; `metrics`
91.7 s (it reads the telemetry file once per run); retirement 14.0 s for 612 worktrees, 4.9 MB
freed; the collection after it 99.1 s with 0 orphans. Task wall time did not grow: the mean of
the first and last ten tasks was 694 and 644 ms for document tasks, 719 and 657 ms for
numerical tasks, 1 528 and 1 538 ms for software repairs.

What the carried keys show: carrying is the engine's readout, not the window's doing. On a
star neighbourhood (one hub co-cited once with each ward) every non-seed ward carries one to
three milli up to 46 entities and nothing at 64, whatever the co-citation density (measured
directly against the engine: 20 wards cited seven times each, 45 cited once, 63 cited once or
twice, 30 cited four times, 40 cited three times). A hub co-cited with more than about 45
distinct sources therefore carries none of them at the profile's time; the walk runs, says what
it saw, and ranks nothing above the lexical score. That is ADR-20's readout, unchanged here.

## What this establishes and what it does not
Established: under 612 runs in one workspace every operation of ADR-17 and the release
discipline ran and verified; the batch and entity caps are declared windows in the retained
record, not failures, and per-task time did not grow; the observation table grows with distinct
sources; a backup taken after a migration restores and replays every epoch; worktrees are
reclaimed on request and the retired run's export refuses; the first and last associative
manifests recompute from the chain after compactions, collections, a migration and a reopen.
Not established: operation with a real provider (the witness uses the scripted providers so
that growth, not the model, is measured); operation over months or across hosts; any bound on
the journal (append-only by contract: a replay, a migration and a restore cost time linear in
the events, 4.7 ms per event here, measured, not bounded); a bound on the telemetry file
(`metrics` without `--run` reads it once per run, 92 s at 612 runs); a restored workspace's
credential (never backed up; the operator writes it); that a windowed walk carries anything (a
hub with more than about 45 distinct co-cited sources carries none at the profile's time, which
is the engine's readout and not this ADR's to change). Retirement is an operator's decision: a
retired run cannot be exported again, which is why nothing retires automatically.

## Consequences
A workspace can be operated through hundreds of tasks with the costs that grow stated and
measured, and the two cliffs that would have ended an associative workspace (the batch cap) or a
migrated one (the backup) are gone. ADR-20's capacity rule and ADR-23's limits are amended in
place; no evaluation protocol is affected (every protocol ran in a fresh workspace per unit).
