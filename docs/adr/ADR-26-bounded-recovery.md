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
  both hash chains and the retained epoch digest over every event from genesis, loads the
  checkpoint's state and reads every projection object it names (the store's byte check
  verifies each one), reduces only the events after the checkpoint, and runs the final checks
  over every run (the untouched runs by digest against the runs table). A tampered event before
  the checkpoint is a hash mismatch; a missing or changed state object, a state that does not
  match its manifest or a binding that does not match the chains is a storage fault; nothing is
  silently worked around. `replay()` from genesis stays the audit: it reduces everything and,
  at the sequence of every checkpoint it passes (a checkpoint of the empty journal included),
  compares the chains and the state it reached with what the checkpoint binds and reads every
  state object (`checkpoints_verified`), so a checkpoint verified by induction is also verified
  by the next audit.
- **What the bounded replay trusts, stated plainly.** Everything a replay from a checkpoint
  verifies is internal to the workspace: the chains, the checkpoint's binding to them, the
  state objects' bytes and the suffix it reduces. It therefore trusts the checkpoint's retained
  state as a verified fact. Someone with write access to the workspace who forges a checkpoint
  together with a consistent state object, projection objects and runs rows at the honest chain
  heads is not caught by the bounded replay, because nothing it reads derives that state from
  the events; the audit from genesis does, and is the only verification that does. The prefix's
  payload bytes and command rows are likewise not re-read by the bounded replay (the artifact
  presence check and `doctor --deep`'s byte check cover the objects; the audit reads them). That
  is the same trust the owner already places in its own tables between audits, and the reason
  the audit stays available on every path (`gabriel audit`, `restore --full`, the migration) and
  should run on a cadence the operator chooses. An externally retained checkpoint manifest (the
  output of `gabriel checkpoint`) can be checked against a workspace with `verify_checkpoint`,
  as an exported anchor is checked by `restore`.
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
The same witness as ADR-25 (600 scheduled tasks and 12 probes, 612 runs, 19 836 events at the
end) ran on this code (commit `e600ca7`) in 17.8 minutes with every check passed, the ADR-25
checks included. The recovery table, read back from the retained operations:

| after task | journal events | replay from the latest checkpoint | audit from genesis |
|---|---|---|---|
| 102 | 3 157 | no checkpoint yet: 3 157 reduced, 9.6 s | |
| 205 | 6 334 | 3 177 reduced, 11.1 s | |
| 308 | 9 524 | 3 190 reduced, 10.5 s; restore 19.5 s (0 reduced) | restore 45.4 s, 3 checkpoints verified |
| 410 | 12 681 | 3 157 reduced, 10.7 s (from the migration's checkpoint) | |
| 512 | 16 136 | 3 455 reduced, 12.5 s | |
| 612 | 19 836 | 3 700 reduced, 13.4 s; restore 38.1 s (0 reduced) | restore 99.3 s, 7 checkpoints verified; replay 58.6 s, 7 checkpoints verified |

The replay from the latest checkpoint stayed between 9.6 and 13.4 s while the journal grew
sixfold, because each one reduced the roughly 3 200 to 3 700 events since the previous
collection (3.0 to 3.6 ms per reduced event, the chains over every event and the final check
over every run on top); the audit from genesis took 58.6 s for 19 836 events, 3.0 ms per event
against 4.7 ms before this ADR, the difference being the artifact validated once per digest,
with nothing removed from what it checks. `gc --apply` took 9.8 to 16.6 s (16 to 104 s before)
and 5.6 s after the retirement, `metrics` 3.2 s (91.7 s before), the migration 62 s (94 s
before; still two full replays and a backup). A restore from the backup's checkpoint reduced
nothing and took 19.5 s at 9 524 events and 38.1 s at 19 836, against 45.4 s and 99.3 s from
genesis, and the audit of each restored copy verified the checkpoint its default restore had
trusted, which the audit derives from the events alone (the witness's check
`full_restore_verified_the_checkpoint_the_quick_restore_trusted`); what remains in the restore
is the copy of every object into the restored store (42 510 objects, each written and synced),
which is linear in the objects, not in the events. Eight checkpoints were retained (six by
collections, one by the migration on its boundary, one by the collection after the retirement);
the audit at the end verified the seven that existed then. Per-task time did not grow (document
721 and 696 ms, numerical 686 and 654 ms, software 1 607 and 1 531 ms for the first and last
ten). The telemetry file rotated into two parts. The store holds 42 510 objects and 66.9 MB
against 41 875 and 46.1 MB in the ADR-25 run: the retained projections of the checkpoints are
the difference, about 21 MB for 612 runs, since a run's final projection is stored once and
every later checkpoint names the same object. Two earlier runs of the same witness on this
code's predecessors (commits `d10b41d` and `f9eebdf`, not retained) gave the same picture:
1 052 s and 1 049 s in all, bounded replays of 9.0 to 14.2 s and 9.8 to 12.1 s, audits of 60.6 s
and 59.3 s, restores from the checkpoint of 22.2 and 42.4 s and 18.5 and 43.1 s.

## What this establishes and what it does not
Established: the recovery of a workspace (restore, the re-verification after a collection, a
routine audit) costs the chains over every event plus the reduction of the events since the
last verified checkpoint, not the reduction of the whole journal; every checkpoint is verified
by the replay that records it and again by every later audit from genesis; a tampered prefix
event, a missing or changed state object or a binding that does not match the chains is a
fault; the full replay is cheaper than before without a change in what it checks; `metrics` is
linear in the spans. Not established, by construction: that a replay from a checkpoint detects
a state forged consistently with its checkpoint by someone with write access to the workspace
(only the audit from genesis derives the state from the events), or a prefix payload whose
bytes changed (presence is checked; `doctor --deep` and the audit check bytes). Not established: a bound
on the audit itself (the replay from genesis stays linear in the events and is the only
verification that does not trust a checkpoint); a bound on the migration (two full replays and
a backup, by design); a bound on the restore's object copy or on the backup and the dry run of
a collection (linear in the objects: every object is written and synced into the restored
store, every retained input and every object in the closure is parsed; measured at seconds to
tens of seconds, not bounded); pruning of checkpoints (every one is retained; the state objects
of old checkpoints stay roots, about 33 KB per run once); operation with a real provider or
across hosts.

## Consequences
Recovery time is bounded by the checkpoint cadence an operator chooses (the witness takes one
per hundred tasks through its collections), the audit remains available and verifies the
checkpoints it passes, and the two paths agree by construction. ADR-17's operations keep their
contracts; ADR-25's known issue that replay, restore and `metrics` grow linearly is amended.
