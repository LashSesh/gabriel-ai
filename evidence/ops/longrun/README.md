# ADR-25 long-run witness (evidence/ops/longrun)

One workspace driven through 600 scheduled tasks plus 12 associative probe tasks (612 runs) in
`linux_namespace` with the scripted providers, so that growth and the operations under it are
measured, not the model. Produced by `scripts/longrun_witness.py` at commit `5e8c889` of this
branch (`summary.json` records `produced_at_utc`, the platform and the `engine_observer`
digest). Status: **passed** (every check in `summary.json["checks"]`).

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
- After every 100 scheduled tasks: `memory.compact()` then `gc(apply=True, grace_seconds=0)`,
  each followed by replay and chain verification, and a snapshot of the workspace.
- At task 300: backup, restore elsewhere (verified, replayed), then an explicit migration to a
  changed catalog (an extra read-only tool) and a reopen under the new epoch.
- At the end: backup and restore under the new epoch, full replay, chain verification, the
  reproduction of the first and the last probe's retrieval manifest from the chain, deep
  diagnostics, metrics, the trace summary, retirement of every worktree and a final collection.

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

## Figures of the final run
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

## Limits read off the evidence
- What the walk carries is the engine's readout, not the window's doing: on a star
  neighbourhood (one hub co-cited once with each ward) every non-seed ward carries one to
  three milli up to 46 entities and nothing at 64, whatever the co-citation density, so the
  probes after the entity cap are computed, windowed and carry no key. A hub co-cited with
  more than about 45 distinct sources carries none of them at the profile's time (ADR-20's
  readout, unchanged by ADR-25).
- The journal is append-only and never compacted: the full replay, the migration (two replays
  plus a backup) and the restore cost time linear in the events, and `metrics` without `--run`
  reads the whole telemetry file once per run; the operations table shows these durations
  growing with the workspace.
- A restored workspace has no credential until the operator writes one; the witness inspects
  the restored copies through the restore report and the owner directly.
- Scripted providers only; no provider was called.
