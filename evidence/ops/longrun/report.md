# ADR-25 witness: a long run of 612 tasks in one workspace (linux_namespace)

Produced 2026-10-05T13:25:38.620863+00:00 on Linux-6.18.44-fc-v70-x86_64-with-glibc2.39; `engine_observer` a8e1f6d7db2ef7ab; scripted providers only.

## Growth (read back from the workspace)

| snapshot | tasks | epoch | journal events | journal MB | memory entries | document obs. | distinct document keys | supported claims | cache rows | store objects | store MB | worktrees | worktree MB | telemetry MB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| start | 0 | 0 | 0 | 0.2 | 0 | 0 | 0 | 0 | 0 | 1 | 0.0 | 0 | 0.0 | 0.00 |
| after-task-100 | 102 | 0 | 3157 | 24.3 | 433 | 21 | 21 | 69 | 0 | 6879 | 7.2 | 102 | 1.1 | 2.26 |
| after-task-200 | 205 | 0 | 6334 | 48.4 | 850 | 21 | 21 | 139 | 0 | 13258 | 13.8 | 205 | 2.1 | 4.54 |
| after-task-300 | 308 | 0 | 9524 | 72.8 | 1314 | 71 | 71 | 208 | 0 | 20594 | 22.2 | 308 | 3.2 | 6.82 |
| after-migration | 308 | 1 | 9524 | 72.8 | 1314 | 71 | 71 | 208 | 0 | 20596 | 22.3 | 308 | 3.2 | 6.82 |
| after-task-400 | 410 | 1 | 12681 | 97.0 | 1793 | 138 | 138 | 277 | 0 | 28189 | 31.3 | 410 | 4.3 | 9.09 |
| after-task-500 | 512 | 1 | 16136 | 123.1 | 2136 | 171 | 171 | 312 | 0 | 35313 | 39.4 | 512 | 4.9 | 11.57 |
| after-task-600 | 612 | 1 | 19836 | 151.0 | 2337 | 171 | 171 | 312 | 0 | 41875 | 46.1 | 612 | 4.9 | 14.22 |
| end | 612 | 1 | 19836 | 151.0 | 2337 | 171 | 171 | 312 | 0 | 41875 | 46.1 | 612 | 4.9 | 14.22 |
| after-retirement | 612 | 1 | 19836 | 151.0 | 2337 | 171 | 171 | 312 | 0 | 41875 | 46.1 | 0 | 0.0 | 14.22 |

## Associative probes (every 25 document tasks; the goal's lexical matches seed the walk, the hub among them)

| probe | after task | state | status | claims in history | entities in history | batches available / used | entities walked | carried | retrieval ms | engine ms |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 38 | succeeded | computed | 25 | 21 | 25 / 25 | 21 | 13 | 35,23 | 3.0 |
| 2 | 76 | succeeded | computed | 50 | 21 | 50 / 50 | 21 | 13 | 33,32 | 4.3 |
| 3 | 115 | succeeded | computed | 75 | 21 | 75 / 75 | 21 | 13 | 42,37 | 4.3 |
| 4 | 153 | succeeded | computed | 100 | 21 | 100 / 100 | 21 | 13 | 45,46 | 3.3 |
| 5 | 192 | succeeded | computed | 125 | 21 | 125 / 125 | 21 | 13 | 51,44 | 4.8 |
| 6 | 230 | succeeded | computed | 150 | 21 | 150 / 128 | 21 | 13 | 46,46 | 4.2 |
| 7 | 269 | succeeded | computed | 175 | 46 | 175 / 128 | 46 | 38 | 64,78 | 9.2 |
| 8 | 307 | succeeded | computed | 200 | 71 | 200 / 63 | 64 | 0 | 95,55 | 11.3 |
| 9 | 346 | succeeded | computed | 225 | 96 | 225 / 63 | 64 | 0 | 154,76 | 11.2 |
| 10 | 384 | succeeded | computed | 250 | 121 | 250 / 63 | 64 | 0 | 108,115 | 11.9 |
| 11 | 423 | succeeded | computed | 275 | 146 | 275 / 63 | 64 | 0 | 97,92 | 14.8 |
| 12 | 461 | succeeded | computed | 300 | 171 | 300 / 63 | 64 | 0 | 105,115 | 11.0 |

## Operations

| operation | after task | epoch | duration ms | status | key facts |
|---|---|---|---|---|---|
| memory.compact | 102 | 0 | 117 | ok | {"status": "compacted", "removed_derived": {"cache_entries": 4, "summaries": 0}, "retained_artifact_count": 753} |
| gc.apply | 102 | 0 | 15959 | ok | {"status": "passed", "objects": 6948, "orphans": 69, "removed": 69, "replay": "passed", "memory": "passed"} |
| memory.compact | 205 | 0 | 238 | ok | {"status": "compacted", "removed_derived": {"cache_entries": 6, "summaries": 0}, "retained_artifact_count": 1413} |
| gc.apply | 205 | 0 | 31400 | ok | {"status": "passed", "objects": 13328, "orphans": 70, "removed": 70, "replay": "passed", "memory": "passed"} |
| memory.compact | 308 | 0 | 352 | ok | {"status": "compacted", "removed_derived": {"cache_entries": 6, "summaries": 0}, "retained_artifact_count": 2271} |
| gc.apply | 308 | 0 | 46374 | ok | {"status": "passed", "objects": 20663, "orphans": 69, "removed": 69, "replay": "passed", "memory": "passed"} |
| backup | 308 | 0 | 3016 | ok | {"object_count": 20594, "object_bytes": 22243613} |
| restore | 308 | 0 | 64016 | ok | {"status": "passed", "objects_verified": 20594, "replay_events": 9524} |
| migrate | 308 | 0 | 94190 | ok | {"status": "migrated"} |
| memory.compact | 410 | 1 | 600 | ok | {"status": "compacted", "removed_derived": {"cache_entries": 4, "summaries": 0}, "retained_artifact_count": 3199} |
| gc.apply | 410 | 1 | 62458 | ok | {"status": "passed", "objects": 28258, "orphans": 69, "removed": 69, "replay": "passed", "memory": "passed"} |
| memory.compact | 512 | 1 | 503 | ok | {"status": "compacted", "removed_derived": {"cache_entries": 4, "summaries": 0}, "retained_artifact_count": 3815} |
| gc.apply | 512 | 1 | 79512 | ok | {"status": "passed", "objects": 35348, "orphans": 35, "removed": 35, "replay": "passed", "memory": "passed"} |
| memory.compact | 612 | 1 | 590 | ok | {"status": "compacted", "removed_derived": {"cache_entries": 0, "summaries": 0}, "retained_artifact_count": 4116} |
| gc.apply | 612 | 1 | 104170 | ok | {"status": "passed", "objects": 41875, "orphans": 0, "removed": 0, "replay": "passed", "memory": "passed"} |
| backup | 612 | 1 | 6468 | ok | {"object_count": 41875, "object_bytes": 46117428} |
| restore | 612 | 1 | 138898 | ok | {"status": "passed", "objects_verified": 41875, "replay_events": 19836} |
| owner.replay | 612 | 1 | 92668 | ok | {"status": "passed", "events": 19836, "runs": 612} |
| memory.verify | 612 | 1 | 135 | ok | {"status": "passed", "entries": 2337} |
| memory.reproduce | 612 | 1 | 26 | ok | {"status": "reproduced", "differences": []} |
| memory.reproduce | 612 | 1 | 49 | ok | {"status": "reproduced", "differences": []} |
| doctor.deep | 612 | 1 | 1688 | ok | {"problems": ["linux_namespace jail self-test not executed (run doctor --selftest on a Linux host that permits namespaces)"]} |
| metrics | 612 | 1 | 91680 | ok | {"runs": 612, "declared_successes": 612, "independent_checks_passed": 5820, "independent_checks_failed": 0} |
| trace.summary | 612 | 1 | 313 | ok | {"spans": 35400} |
| retire_worktrees | 612 | 1 | 13987 | ok | {"retired": 612, "bytes_freed": 4941246} |
| gc.after_retirement | 612 | 1 | 99110 | ok | {"status": "passed", "objects": 41875, "orphans": 0, "removed": 0} |

## Task wall time (ms)

| kind | tasks | first 10 mean | last 10 mean | overall mean | max |
|---|---|---|---|---|---|
| document | 300 | 694 | 644 | 649 | 943 |
| document-probe | 12 | 776 | 810 | 790 | 985 |
| numerical | 150 | 719 | 657 | 661 | 1095 |
| software | 150 | 1528 | 1538 | 1508 | 1841 |

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
| memory_chain_verified | passed |
| first_and_last_probe_reproduce | passed |
| diagnostics_clean | passed |
| worktrees_retired | passed |

Probe statuses in order: computed, computed, computed, computed, computed, computed, computed, computed, computed, computed, computed, computed.

Status: **passed**.

Retained: `summary.json` (every snapshot, probe, operation and check), `series.json` (every task's state, wall time, counters and retrieval times).
The workspace, repositories, backups and restored copies under `work/` are not committed.
