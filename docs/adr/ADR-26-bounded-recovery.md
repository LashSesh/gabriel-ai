# ADR-26: Bounded recovery

**Status:** accepted. **Affects:** `state/owner.py` (`replay(from_checkpoint, record_checkpoint)`,
verified state checkpoints, `checkpoints()`, `verify_checkpoint`, the validated-artifact cache of
the replay), `contracts/schemas/checkpoint.schema.json` (`gabriel.checkpoint/2`),
`contracts/schemas/checkpoint-state.schema.json`, `agent/backup.py` (`restore(full=)`),
`agent/gc.py` (a collection re-verifies from the latest checkpoint and records the next),
`agent/workspace.py` (the replay after a migration records the epoch's first checkpoint; the
startup validation lists checkpoints; `metrics` reads the telemetry once), `telemetry.py`
(rotation, `span_files`, `spans_by_run`), `interfaces/cli.py` (`checkpoint`, `audit
--from-checkpoint --checkpoint`, `restore --full`), `scripts/longrun_witness.py`,
`evidence/ops/longrun/`.

## Context
ADR-25 measured what grows linearly with the journal in a long-running workspace: at 612 runs
and 19 836 events a recorded replay from genesis took 93 s, a restore 139 s, a migration 94 s,
`gc --apply` 104 s and `metrics` 92 s. The journal is append-only by contract (ADR-12, ADR-17),
so none of these can be bounded by removing events. Reading where the time went, on the retained
witness workspace, gave three facts:

1. **The replay's cost is validation, not hashing or reduction.** Of 5.2 ms per event, 73 % is
   JSON-schema validation at five call sites, and 36 % alone is validating the run's task
   binding again for every event (the same bytes, 32 times per run); the reducer takes 18 %
   (half of it the pure reducer's copy of the projection, half the run schema), the projection
   digest 7.5 %, the object reads 4 %, the SQL under 1 %. Verifying both hash chains over every
   event, with nothing reduced, takes 0.16 s for the whole journal.
2. **The checkpoint the owner had was unverified and stateless.** `Owner.checkpoint` wrote the
   digest of the stored run projections without replaying them, retained no state, and no
   production path called it; `verify_checkpoint` compared a caller-supplied projection.
3. **`gc --apply` was a replay; `metrics` read the telemetry file once per run.** The dry run of
   a collection costs 3 s (roots, closure, scan); the remaining 100 s were the replay after the
   collection. `metrics` parsed the 14 MB spans file 613 times.

## Decision
- **A replay validates an artifact once.** Within one replay the owner memoizes a validated
  artifact by its digest (the task binding and the compilation report of `_derived_inputs`).
  The bytes behind a digest never change, so the result is the same object the per-event
  validation produced; the replay's checks are unchanged, only repeated work is gone.
- **Verified state checkpoints (`gabriel.checkpoint/2`).** A checkpoint is recorded only at the
  end of a recorded replay that reached its sequence (from genesis or from an earlier verified
  checkpoint) with every check passed. It retains the state that replay reproduced: one
  content-addressed object per run projection (the object's sha256 is the run's projection
  digest), a `gabriel.checkpoint-state/1` object listing them, and a manifest row binding the
  sequence, the heads of both chains, the digest of the per-run digests, the identities the state
  was produced with (reducer, schema registry, codec) and the catalog digest of its epoch, with
  `verified_from` (genesis or the checkpoint it started from), `events_reduced` and a reason.
  The collector and the backup already keep what checkpoint manifests name, so the state
  objects are roots. An unchanged run's object is the one the previous checkpoint named, so a
  checkpoint costs the projections that changed since the last one plus one state object.
- **Replay from the latest verified checkpoint.** `replay(from_checkpoint=True)` picks the
  latest checkpoint whose identities and epoch read the same as the running code's and whose
  binding still matches the journal (every unusable one is reported with its reason), verifies
  both hash chains over every event from genesis, loads the checkpoint's state (the store's byte
  check verifies every object), reduces only the events after the checkpoint, and runs the final
  checks over every run (the untouched runs by digest). A tampered event before the checkpoint
  is a hash mismatch; a changed state object or a forged binding is a storage fault; nothing is
  silently worked around. `replay()` from genesis stays the audit: it reduces everything and,
  at the sequence of every checkpoint it passes, compares the state it reached with the state
  the checkpoint binds (`checkpoints_verified`), so a checkpoint verified by induction is also
  verified by the next audit.
- **Where the bounded recovery is used.** `restore` replays from the checkpoint the backup
  carries (`--full` asks for the audit; the report says which); `gc --apply` re-verifies from
  the latest checkpoint and records the state it reached as the next one, so every collection
  bounds the next recovery; the replay after a migration is the audit under the new code and
  records a checkpoint on the epoch boundary (bound to the catalog of the events it covers, the
  old epoch's; the events after it belong to the new one); `gabriel checkpoint` records one on
  request;
  `gabriel audit` is the audit from genesis unless `--from-checkpoint`. Migration keeps its two
  full replays: its equivalence check is exactly the question whether the running code
  reproduces every event.
- **Telemetry rotates; metrics read it once.** The live spans file is rotated beyond 8 MiB into
  parts beside it; readers see every part in order; `metrics` reads the parts once and groups
  the spans by run, so its cost no longer multiplies the file by the number of runs.
- **The witness measures the recovery.** At every hundred-task boundary the witness replays from
  the latest verified checkpoint before the collection records the next one; at the half and at
  the end it restores the backup both from its checkpoint and from genesis; at the end the audit
  from genesis verifies every checkpoint. The report's recovery table shows the bounded replays
  beside the growing audit.

## Results (`evidence/ops/longrun/`)
The witness run of 600 tasks on this code is in progress at the time of this commit; the commit
that records `evidence/ops/longrun/` replaces this paragraph with its recovery table.

## What this establishes and what it does not
Established: the recovery of a workspace (restore, the re-verification after a collection, a
routine audit) costs the chains over every event plus the reduction of the events since the
last verified checkpoint, not the reduction of the whole journal; every checkpoint is verified
by the replay that records it and again by every later audit from genesis; a tampered prefix,
a changed state object or a forged binding is a fault; the full replay is cheaper than before
without a change in what it checks; `metrics` is linear in the spans. Not established: a bound
on the audit itself (the replay from genesis stays linear in the events and is the only
verification that does not trust a checkpoint); a bound on the migration (two full replays and
a backup, by design); a bound on the backup or the dry run of a collection (both parse every
event's retained inputs and every object in the closure, measured at seconds, not bounded);
pruning of checkpoints (every one is retained; the state objects of old checkpoints stay roots);
operation with a real provider or across hosts.

## Consequences
Recovery time is bounded by the checkpoint cadence an operator chooses (the witness takes one
per hundred tasks through its collections), the audit remains available and verifies the
checkpoints it passes, and the two paths agree by construction. ADR-17's operations keep their
contracts; ADR-25's known issue that replay, restore and `metrics` grow linearly is amended.
