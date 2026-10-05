# ADR-25 / ADR-26 long-run witness (evidence/ops/longrun)

One workspace driven through 600 scheduled tasks plus 12 associative probe tasks (612 runs) in
`linux_namespace` with the scripted providers, so that growth and the operations under it are
measured, not the model. The files here are the ADR-26 run, produced by
`scripts/longrun_witness.py` at commit `e600ca7` of this branch (`summary.json` records
`produced_at_utc`, the platform and the `engine_observer` digest); it repeats every ADR-25
measurement and adds the recovery table. The ADR-25 run at commit `5e8c889` is retained in the
history of this directory (commit `a1ea5ce`) and its figures stand in ADR-25 and below. Status:
**passed** (every check in `summary.json["checks"]`).

```bash
scripts/longrun_witness.py --out evidence/ops/longrun --backend linux_namespace --tasks 600
```

## Schedule
- 300 document tasks on one shared hub source: the first 150 cycle over a fixed set of 20
  wards (the hub's neighbourhood stays at 21 entities while the claims pass the engine's batch
  cap of 128), the second 150 each name a new ward (the neighbourhood passes the entity cap of
  64). Every verified document run records one supported claim citing the hub and its ward,
  which is one co-citation batch of the association history.
- 150 software repairs (the seeded parser bug with its independent oracle) and 150 numerical
  transformations (the series fixture with the reference contract), interleaved.
- An associative probe after every 25 document tasks: a task on the hub under the associative
  view; its retained retrieval manifest records the association status, the window, the seeds,
  the entities and what was carried.
- After every 100 scheduled tasks: a replay from the latest verified checkpoint (ADR-26), then
  `memory.compact()` and `gc(apply=True, grace_seconds=0)`, which re-verifies from that
  checkpoint and records the next one, then a snapshot of the workspace.
- At task 300: backup, restore elsewhere from the backup's checkpoint and once more from
  genesis (both verified and replayed), then an explicit migration to a changed catalog (an
  extra read-only tool), whose replay records a checkpoint on the boundary, and a reopen under
  the new epoch.
- At the end: backup, restore from its checkpoint and from genesis, the audit from genesis
  (which verifies every checkpoint it passes), chain verification, the reproduction of the
  first and the last probe's retrieval manifest from the chain, deep diagnostics, metrics, the
  trace summary, retirement of every worktree, a final collection and the list of checkpoints.

Two counts appear in the evidence: snapshot labels (`after-task-100`) count scheduled tasks,
while `task_index` and the operations' `after task` column count runs including the probes
(102, 205, 308, ...). Both are retained as recorded.

## Files
- `summary.json`: every snapshot (journal, memory, store, worktree and telemetry sizes read
  back from the workspace), every probe (association status, window, seeds, entities, carried
  keys, hub masses, engine timings, the retained manifest's digest), every operation with its
  duration and key facts, the checks, the doctor at the start, the final anchors.
- `series.json`: every run's kind, state, wall time, counters, journal and memory sequence,
  epoch and retrieval times.
- `report.md`: the growth table, the probe table, the operations table, task wall times and
  the checks, rendered from the two files above.
- `work/` (not committed, `.gitignore`): the workspace, the repositories, the backups and the
  restored copies.

## Figures of the ADR-26 run (the files here)
612 runs in 1 065 s. Journal 19 836 events (151.0 MB); memory chain 2 337 entries, 171
document observations for 171 distinct document keys, 312 supported claims; store 42 510
objects (66.9 MB, of which about 21 MB are the retained projections of the checkpoints); 612
worktrees retired to 0; telemetry 14.2 MB in 2 rotated parts (35 400 spans); 5 820 independent
checks passed, 0 failed. Recovery: the replay from the latest checkpoint at the six boundaries
9.6 s (no checkpoint yet, 3 157 events from genesis), 11.1, 10.5, 10.7, 12.5 and 13.4 s (3 177 to
3 700 events reduced each time) while the journal grew to 19 836 events; the audit from genesis
at the end 58.6 s (3.0 ms per event) verifying the 7 checkpoints that existed then; restore from
the backup's checkpoint 19.5 s and 38.1 s (0 events reduced) against 45.4 s and 99.3 s from
genesis, whose audit verified 3 and 7 checkpoints, the one the default restore had trusted among
them; `gc --apply` 9.8 to 16.6 s, 5.6 s after the retirement; backup 3.3 s and 6.9 s; migration
62.4 s; `metrics` 3.2 s; retirement 14.3 s; 8 checkpoints retained. Probes as in the ADR-25 run
(1 to 5 whole history, 6 and 7 at the batch cap, 8 to 12 at the entity cap, every one
`computed`). Task wall time, first and last ten: document 721 and 696 ms, numerical 686 and
654 ms, software 1 607 and 1 531 ms.

Three earlier runs of the ADR-26 witness are not retained: on commits `d10b41d` and `f9eebdf`
(1 052 s and 1 049 s, every check passed, bounded replays of 9.0 to 14.2 s and 9.8 to 12.1 s,
audits of 60.6 s and 59.3 s) and on `0c7aa39` under concurrent load from the review's test runs
(1 105 s, every check passed, task wall times distorted, not counted). The files here are the
run on the committed witness, whose check
`full_restore_verified_the_checkpoint_the_quick_restore_trusted` replaced an earlier one that
compared only what both restores read from the same journal bytes.

## Figures of the ADR-25 run (commit `5e8c889`, retained in the history)
612 runs in 1 487 s. Journal 19 836 events (151.0 MB); memory chain 2 337 entries, 171
document observations for 171 distinct document keys, 312 supported claims; store 41 875
objects (46.1 MB); 612 worktrees (4.9 MB) retired to 0; telemetry 14.2 MB (35 400 spans);
5 820 independent checks passed, 0 failed. Compaction 117 ms to 590 ms; `gc --apply` 16.0 s
(6 948 objects) to 104.2 s (41 875); backup 3.0 s and 6.5 s; restore 64.0 s (9 524 events)
and 138.9 s (19 836 events, across the migration); migration 94.2 s; final replay 92.7 s
(4.7 ms per event); `metrics` 91.7 s; retirement 14.0 s. Probes 1 to 5 whole history, 6 and 7
at the batch cap (128 of 150 and 175 batches), 8 to 12 at the entity cap (63 of 200 to 300
batches over 64 entities), every one `computed`; retrieval 23 to 154 ms, engine 3 to 15 ms.
Task wall time, first and last ten: document 694 and 644 ms, numerical 719 and 657 ms,
software 1 528 and 1 538 ms.

## What the checks establish
- Every one of the 612 runs reached `succeeded`; no retrieval raised.
- The batch cap is a declared window: from the 129th contributing claim on, the walk saw
  exactly 128 batches while the entities fit, and the record says how many were available.
- The entity cap is a declared window: once the hub's neighbourhood passed 64 entities the walk
  ran over the latest seeded batches whose entities fit (63 batches, 64 entities), computed and
  declared; before this ADR's second round of the window rule every such probe was
  `capacity_exceeded` for the rest of the workspace's life.
- The observation table grew with distinct sources, not with tasks (one observation per
  distinct document key).
- Every compaction verified its required bytes; every collection passed with replay and chain
  verified; both restores passed with every event replayed, the second one across the recorded
  migration; the final replay, the chain, the reproductions of the first and last probe, the
  deep diagnostics and the retirement all passed.
- ADR-26: every collection re-verified the workspace from the previous checkpoint and recorded
  the next one; every boundary replay that found a checkpoint reduced a proper suffix of the
  journal (the first boundary had none and reduced everything); the audit from genesis at the
  end verified every checkpoint that existed then; both backups carried the latest checkpoint,
  so the default restore started from it and reduced nothing, and the audit of the restored
  copy (`restore --full`), which derives the state from the events alone, verified that very
  checkpoint; the telemetry rotated into parts and `metrics` read them once.

## Limits read off the evidence
- What the walk carries is the engine's readout, not the window's doing: on a star
  neighbourhood (one hub co-cited once with each ward) every non-seed ward carries one to
  three milli up to 46 entities and nothing at 64, whatever the co-citation density, so the
  probes after the entity cap are computed, windowed and carry no key. A hub co-cited with
  more than about 45 distinct sources carries none of them at the profile's time (ADR-20's
  readout, unchanged by ADR-25).
- The journal is append-only and never compacted: the audit from genesis and the migration
  (two replays plus a backup) cost time linear in the events. Since ADR-26 the restore, the
  collection's re-verification and the routine audit replay from the latest verified
  checkpoint, so their reduction is bounded by the checkpoint cadence; the restore's copy of
  every object into the restored store stays linear in the objects, and `metrics` reads the
  telemetry parts once.
- A restored workspace has no credential until the operator writes one; the witness inspects
  the restored copies through the restore report and the owner directly.
- Scripted providers only; no provider was called.
