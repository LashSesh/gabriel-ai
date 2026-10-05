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
The witness run of 600 tasks is in progress at the time of this commit; the commit that
records `evidence/ops/longrun/` replaces this paragraph with its growth table, probe statuses,
operation durations and checks.

## What this establishes and what it does not
Established: under 600 tasks in one workspace every operation of ADR-17 and the release
discipline ran and verified; the batch and entity caps are declared windows in the retained
record, not failures; the observation table grows with distinct sources; a backup taken after a
migration restores and replays every epoch; worktrees are reclaimed on request and the retired
run's export refuses; the first and last associative manifests recompute from the chain after
compactions, collections, a migration and a reopen. Not established: operation with a real
provider (the witness uses the scripted providers so that growth, not the model, is measured);
operation over months or across hosts; any bound on the journal (append-only by contract: a
replay, a migration and a restore cost time linear in the events, measured here, not bounded);
a bound on the telemetry file (`metrics` without `--run` reads it once per run); a restored
workspace's credential (never backed up; the operator writes it). Retirement is an operator's
decision: a retired run cannot be exported again, which is why nothing retires automatically.

## Consequences
A workspace can be operated through hundreds of tasks with the costs that grow stated and
measured, and the two cliffs that would have ended an associative workspace (the batch cap) or a
migrated one (the backup) are gone. ADR-20's capacity rule and ADR-23's limits are amended in
place; no evaluation protocol is affected (every protocol ran in a fresh workspace per unit).
