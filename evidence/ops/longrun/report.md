# ADR-25 witness: a long run of 612 tasks in one workspace (linux_namespace)

Produced 2026-10-05T18:00:17.145851+00:00 on Linux-6.18.44-fc-v70-x86_64-with-glibc2.39; `engine_observer` a8e1f6d7db2ef7ab; scripted providers only.

## Growth (read back from the workspace)

| snapshot | tasks | epoch | journal events | journal MB | memory entries | document obs. | distinct document keys | supported claims | cache rows | store objects | store MB | worktrees | worktree MB | telemetry MB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| start | 0 | 0 | 0 | 0.2 | 0 | 0 | 0 | 0 | 0 | 1 | 0.0 | 0 | 0.0 | 0.00 |
| after-task-100 | 102 | 0 | 3157 | 24.3 | 433 | 21 | 21 | 69 | 0 | 6974 | 10.5 | 102 | 1.1 | 2.26 |
| after-task-200 | 205 | 0 | 6334 | 48.4 | 850 | 21 | 21 | 139 | 0 | 13450 | 20.4 | 205 | 2.1 | 4.54 |
| after-task-300 | 308 | 0 | 9524 | 72.8 | 1314 | 71 | 71 | 208 | 0 | 20889 | 32.3 | 308 | 3.2 | 6.82 |
| after-migration | 308 | 1 | 9524 | 72.8 | 1314 | 71 | 71 | 208 | 0 | 20892 | 32.3 | 308 | 3.2 | 6.82 |
| after-task-400 | 410 | 1 | 12681 | 97.0 | 1793 | 138 | 138 | 277 | 0 | 28597 | 44.7 | 410 | 4.3 | 9.09 |
| after-task-500 | 512 | 1 | 16136 | 123.2 | 2136 | 171 | 171 | 312 | 0 | 35827 | 56.3 | 512 | 4.9 | 11.57 |
| after-task-600 | 612 | 1 | 19836 | 151.0 | 2337 | 171 | 171 | 312 | 0 | 42509 | 66.8 | 612 | 4.9 | 14.22 |
| end | 612 | 1 | 19836 | 151.0 | 2337 | 171 | 171 | 312 | 0 | 42509 | 66.8 | 612 | 4.9 | 14.22 |
| after-retirement | 612 | 1 | 19836 | 151.0 | 2337 | 171 | 171 | 312 | 0 | 42510 | 66.9 | 0 | 0.0 | 14.22 |

## Associative probes (every 25 document tasks; the goal's lexical matches seed the walk, the hub among them)

| probe | after task | state | status | claims in history | entities in history | batches available / used | entities walked | carried | retrieval ms | engine ms |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 38 | succeeded | computed | 25 | 21 | 25 / 25 | 21 | 13 | 31,34 | 2.9 |
| 2 | 76 | succeeded | computed | 50 | 21 | 50 / 50 | 21 | 13 | 40,30 | 3.2 |
| 3 | 115 | succeeded | computed | 75 | 21 | 75 / 75 | 21 | 13 | 41,38 | 3.9 |
| 4 | 153 | succeeded | computed | 100 | 21 | 100 / 100 | 21 | 13 | 52,38 | 4.3 |
| 5 | 192 | succeeded | computed | 125 | 21 | 125 / 125 | 21 | 13 | 48,43 | 3.5 |
| 6 | 230 | succeeded | computed | 150 | 21 | 150 / 128 | 21 | 13 | 49,45 | 4.2 |
| 7 | 269 | succeeded | computed | 175 | 46 | 175 / 128 | 46 | 38 | 70,71 | 6.9 |
| 8 | 307 | succeeded | computed | 200 | 71 | 200 / 63 | 64 | 0 | 64,68 | 14.6 |
| 9 | 346 | succeeded | computed | 225 | 96 | 225 / 63 | 64 | 0 | 200,66 | 10.9 |
| 10 | 384 | succeeded | computed | 250 | 121 | 250 / 63 | 64 | 0 | 91,86 | 15.0 |
| 11 | 423 | succeeded | computed | 275 | 146 | 275 / 63 | 64 | 0 | 96,94 | 12.1 |
| 12 | 461 | succeeded | computed | 300 | 171 | 300 / 63 | 64 | 0 | 107,122 | 12.6 |

## Operations

| operation | after task | epoch | duration ms | status | key facts |
|---|---|---|---|---|---|
| replay.from_checkpoint | 102 | 0 | 9585 | ok | {"status": "passed", "events": 3157, "events_reduced": 3157, "checkpoint": null} |
| memory.compact | 102 | 0 | 126 | ok | {"status": "compacted", "removed_derived": {"cache_entries": 4, "summaries": 0}, "retained_artifact_count": 753} |
| gc.apply | 102 | 0 | 9840 | ok | {"status": "passed", "objects": 6940, "orphans": 69, "removed": 69, "replay": "passed", "memory": "passed", "checkpoint_events_reduced": 3157, "checkpoint_recor |
| replay.from_checkpoint | 205 | 0 | 11063 | ok | {"status": "passed", "events": 6334, "events_reduced": 3177, "checkpoint": "gc-1791222246381-1"} |
| memory.compact | 205 | 0 | 245 | ok | {"status": "compacted", "removed_derived": {"cache_entries": 6, "summaries": 0}, "retained_artifact_count": 1413} |
| gc.apply | 205 | 0 | 12056 | ok | {"status": "passed", "objects": 13416, "orphans": 70, "removed": 70, "replay": "passed", "memory": "passed", "checkpoint_events_reduced": 3177, "checkpoint_reco |
| replay.from_checkpoint | 308 | 0 | 10548 | ok | {"status": "passed", "events": 9524, "events_reduced": 3190, "checkpoint": "gc-1791222348113-2"} |
| memory.compact | 308 | 0 | 346 | ok | {"status": "compacted", "removed_derived": {"cache_entries": 6, "summaries": 0}, "retained_artifact_count": 2271} |
| gc.apply | 308 | 0 | 13001 | ok | {"status": "passed", "objects": 20854, "orphans": 69, "removed": 69, "replay": "passed", "memory": "passed", "checkpoint_events_reduced": 3190, "checkpoint_reco |
| backup | 308 | 0 | 3281 | ok | {"object_count": 20889, "object_bytes": 32260196} |
| restore.from_checkpoint | 308 | 0 | 19457 | ok | {"status": "passed", "objects_verified": 20889, "replay_events": 9524, "events_reduced": 0} |
| restore.full | 308 | 0 | 45397 | ok | {"status": "passed", "objects_verified": 20889, "replay_events": 9524, "events_reduced": 9524} |
| migrate | 308 | 0 | 62369 | ok | {"status": "migrated"} |
| replay.from_checkpoint | 410 | 1 | 10701 | ok | {"status": "passed", "events": 12681, "events_reduced": 3157, "checkpoint": "migration-1-eacea73b0f72"} |
| memory.compact | 410 | 1 | 511 | ok | {"status": "compacted", "removed_derived": {"cache_entries": 4, "summaries": 0}, "retained_artifact_count": 3199} |
| gc.apply | 410 | 1 | 12909 | ok | {"status": "passed", "objects": 28563, "orphans": 69, "removed": 69, "replay": "passed", "memory": "passed", "checkpoint_events_reduced": 3157, "checkpoint_reco |
| replay.from_checkpoint | 512 | 1 | 12506 | ok | {"status": "passed", "events": 16136, "events_reduced": 3455, "checkpoint": "gc-1791222700030-5"} |
| memory.compact | 512 | 1 | 673 | ok | {"status": "compacted", "removed_derived": {"cache_entries": 4, "summaries": 0}, "retained_artifact_count": 3815} |
| gc.apply | 512 | 1 | 15301 | ok | {"status": "passed", "objects": 35759, "orphans": 35, "removed": 35, "replay": "passed", "memory": "passed", "checkpoint_events_reduced": 3455, "checkpoint_reco |
| replay.from_checkpoint | 612 | 1 | 13428 | ok | {"status": "passed", "events": 19836, "events_reduced": 3700, "checkpoint": "gc-1791222827938-6"} |
| memory.compact | 612 | 1 | 663 | ok | {"status": "compacted", "removed_derived": {"cache_entries": 0, "summaries": 0}, "retained_artifact_count": 4116} |
| gc.apply | 612 | 1 | 16622 | ok | {"status": "passed", "objects": 42408, "orphans": 0, "removed": 0, "replay": "passed", "memory": "passed", "checkpoint_events_reduced": 3700, "checkpoint_record |
| backup | 612 | 1 | 6927 | ok | {"object_count": 42509, "object_bytes": 66772621} |
| restore.from_checkpoint | 612 | 1 | 38109 | ok | {"status": "passed", "objects_verified": 42509, "replay_events": 19836, "events_reduced": 0} |
| restore.full | 612 | 1 | 99300 | ok | {"status": "passed", "objects_verified": 42509, "replay_events": 19836, "events_reduced": 19836} |
| owner.replay | 612 | 1 | 58612 | ok | {"status": "passed", "events": 19836, "runs": 612, "checkpoints_verified": 7} |
| memory.verify | 612 | 1 | 131 | ok | {"status": "passed", "entries": 2337} |
| memory.reproduce | 612 | 1 | 14 | ok | {"status": "reproduced", "differences": []} |
| memory.reproduce | 612 | 1 | 47 | ok | {"status": "reproduced", "differences": []} |
| doctor.deep | 612 | 1 | 1683 | ok | {"problems": ["linux_namespace jail self-test not executed (run doctor --selftest on a Linux host that permits namespaces)"]} |
| metrics | 612 | 1 | 3155 | ok | {"runs": 612, "declared_successes": 612, "independent_checks_passed": 5820, "independent_checks_failed": 0} |
| trace.summary | 612 | 1 | 304 | ok | {"spans": 35400} |
| retire_worktrees | 612 | 1 | 14279 | ok | {"retired": 612, "bytes_freed": 4941246} |
| gc.after_retirement | 612 | 1 | 5557 | ok | {"status": "passed", "objects": 42509, "orphans": 0, "removed": 0, "checkpoint_events_reduced": 0, "checkpoint_recorded": "gc-1791223214268-8"} |
| checkpoints | 612 | 1 | 0 | ok | {} |

## Recovery (ADR-26: replay from the latest verified checkpoint against the audit from genesis)

| operation | after task | journal events | checkpoint started from | events reduced | duration ms |
|---|---|---|---|---|---|
| replay.from_checkpoint | 102 | 3157 | genesis | 3157 | 9585 |
| replay.from_checkpoint | 205 | 6334 | gc-1791222246381-1 | 3177 | 11063 |
| replay.from_checkpoint | 308 | 9524 | gc-1791222348113-2 | 3190 | 10548 |
| restore.from_checkpoint | 308 | 9524 | gc-1791222454764-3 | 0 | 19457 |
| restore.full | 308 | 9524 | genesis | 9524 | 45397 |
| replay.from_checkpoint | 410 | 12681 | migration-1-eacea73b0f72 | 3157 | 10701 |
| replay.from_checkpoint | 512 | 16136 | gc-1791222700030-5 | 3455 | 12506 |
| replay.from_checkpoint | 612 | 19836 | gc-1791222827938-6 | 3700 | 13428 |
| restore.from_checkpoint | 612 | 19836 | gc-1791222972231-7 | 0 | 38109 |
| restore.full | 612 | 19836 | genesis | 19836 | 99300 |
| owner.replay | 612 | 19836 | genesis | 19836 | 58612 |

Checkpoints retained: 8 (gc-1791222246381-1 at 3157 from genesis, gc-1791222348113-2 at 6334 from gc-1791222246381-1, gc-1791222454764-3 at 9524 from gc-1791222348113-2, migration-1-eacea73b0f72 at 9524 from genesis, gc-1791222700030-5 at 12681 from migration-1-eacea73b0f72, gc-1791222827938-6 at 16136 from gc-1791222700030-5, gc-1791222972231-7 at 19836 from gc-1791222827938-6, gc-1791223214268-8 at 19836 from gc-1791222972231-7); telemetry parts at the end: 2.

## Task wall time (ms)

| kind | tasks | first 10 mean | last 10 mean | overall mean | max |
|---|---|---|---|---|---|
| document | 300 | 721 | 696 | 662 | 939 |
| document-probe | 12 | 770 | 807 | 789 | 951 |
| numerical | 150 | 686 | 654 | 679 | 996 |
| software | 150 | 1607 | 1531 | 1564 | 1866 |

## Checks

| check | result |
|---|---|
| every_task_terminal | passed |
| document_tasks_all_succeeded | passed |
| software_tasks_all_succeeded | passed |
| numerical_tasks_all_succeeded | passed |
| probes_all_succeeded | passed |
| batch_cap_reached_and_declared | passed |
| entity_cap_reached_and_declared | passed |
| no_retrieval_raised | passed |
| document_observations_bounded_by_distinct_sources | passed |
| every_compaction_verified | passed |
| every_gc_passed | passed |
| backups_restored_and_replayed | passed |
| restore_after_migration_passed | passed |
| final_replay_passed | passed |
| every_collection_recorded_a_checkpoint | passed |
| recovery_from_checkpoint_bounded | passed |
| audit_verified_every_checkpoint | passed |
| full_restore_verified_the_checkpoint_the_quick_restore_trusted | passed |
| restores_used_the_backups_checkpoint | passed |
| telemetry_rotated | passed |
| memory_chain_verified | passed |
| first_and_last_probe_reproduce | passed |
| diagnostics_clean | passed |
| worktrees_retired | passed |

Probe statuses in order: computed, computed, computed, computed, computed, computed, computed, computed, computed, computed, computed, computed.

Status: **passed**.

Retained: `summary.json` (every snapshot, probe, operation and check), `series.json` (every task's state, wall time, counters and retrieval times).
The workspace, repositories, backups and restored copies under `work/` are not committed.
