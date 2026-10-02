# Persistence boundary diagnosis

The controlled probes did not reproduce the historical workspace prefix regressions. They did identify a concrete additional write route: an active workspace synchronization service and a writable rsync `scratch` module. No observed event identifies that service as the writer of an affected historical database.

## Source findings

`gabriel_runtime/engine.py` uses synchronous SQLite transactions, DELETE rollback journals and `synchronous=EXTRA`. `Store.submit` commits before returning its receipt. `Store.close` closes the connection. `Store.audit` replays semantics in a read transaction and compares optional external anchors; it does not restore old states. No background or delayed writer was found in this path.

The graph adapter uses blocking `subprocess.run` with default descriptor closure, sends graph JSON through stdin, and does not send a database pathname. Its native executable is not given an owner database to edit. The older replay checker uses SQLite's connection context manager, which handles transactions rather than explicitly closing the connection. The new probe explicitly closes every reader; no mechanism was found by which that old read connection would restore a valid historical prefix.

## Environment findings

The inspected sync script watches `/workspace/scratch` and invokes rsync with `--delay-updates --update --times`, followed by a two-second debounce. The local rsync daemon exposes that scratch path with writes enabled. The script hash and relevant non-sensitive configuration lines are captured in the probe records. No service configuration was changed and no peer endpoint or credential was collected.

Workspace and `/tmp` both resolve to the same root overlay mount, reported as `fsync=volatile`. Consequently, the earlier workspace-versus-`/tmp` observation is not a contrast between two filesystem mounts. Successful `fsync` calls here do not establish backing-store or power-loss durability. The Linux documentation states that volatile overlay mounts omit synchronization to the upper filesystem. That fact limits durability claims; it does not explain a live pathname reverting after a successful read.

## Controlled observations

Every location received three controls: plain fixed-length bytes with explicit `fsync`, ordinary Python SQLite using DELETE/EXTRA, and the unchanged `Store` with a pure counter adapter. All controls retained their initial read-only descriptor. Each numbered commit and subsequent read recorded device/inode identity, size, SHA-256, nanosecond wall and monotonic clocks, logical stage, and sidecars. Writers were closed, files and containing directories explicitly synced, SQLite readers explicitly reopened and closed, and Store instances reopened with external head/event anchors. Inotify monitored file activity.

| Probe | Files | Changes per file | Timing | Result |
| --- | ---: | ---: | --- | --- |
| Paced paired controls | 24 | 14 | 0.5 s between stages; 12 s final hold | 24 final paths and held inodes preserved; no replacements |
| Burst paired controls | 36 | 14 | 0.01 s between stages; 10 s final hold | 36 preserved; no replacements; every file's 14 commits fell within one wall-clock second |
| Deliberate prefix replacement | 3 | 2 | Final path deliberately replaced with its stage-1 image | 3 replacements detected; held final inodes preserved stage 2 |

Separate tool executions rechecked all 24 paced files and all 36 burst files successfully. Both live runs had no unavailable or raced read observations and all explicit Store reopen audits passed. The burst completed in 10.670 s, with per-file commit spans between 0.432 and 0.434 s. The artificial replacement result validates the detector; it is not evidence of an environmental replacement.

The paced run used the initial probe revision, preserved in `persistence_boundary_probe_v1_source.zip`. Independent review tightened immediate baseline timing, stable-read requirements, Store anchor checks, failure reporting and watcher cleanup. `persistence_boundary_strict_review.json` rechecks the untouched paced observations under those stronger conditions. The later burst and strict rechecks used the revised source, whose hash is recorded in their raw results.

## Operational recommendation

Keep a live SQLite owner in a directory outside automatic file mirroring. For this execution environment, `/tmp` provides that separation from the observed scratch sync route, while still being transient and subject to the same volatile overlay mount. For persistent deployment, use a storage location with an appropriate durability contract.

Publish only a closed, consistently captured snapshot, with its SHA-256 and final head/event anchor retained separately. Reopen the snapshot against that anchor before publication, then recheck it after transfer. A self-consistent journal can be a valid old prefix; its own stored head cannot prove that it is the latest accepted state. External anchors detect that distinction. They are integrity references, not authentication unless independently protected.

This investigation ends with a validated replacement detector and an identified external write route, not an attribution of the old failures. The historical 32 residues and the two older workspace replay failures remain preserved as unresolved observations. Neither live probe reproduced them, and no native 32-case replay was repeated.

## Reproduction

Run from the project directory, using new output paths:

```sh
python reproduction/check_persistence_boundary.py --location workspace /workspace/scratch/NEW_PACED --location outside /tmp/NEW_PACED --records 4 --steps 14 --interval 0.5 --settle 12 --output audit/NEW_PACED.json
python reproduction/check_persistence_boundary.py --location workspace /workspace/scratch/NEW_BURST --location outside /tmp/NEW_BURST --records 6 --steps 14 --interval 0.01 --settle 10 --output audit/NEW_BURST.json
python reproduction/check_persistence_boundary.py --check audit/NEW_BURST.json --output audit/NEW_RECHECK.json
```

## Primary references

- [SQLite synchronous pragma](https://sqlite.org/pragma.html#pragma_synchronous): EXTRA adds synchronization of the directory after deletion of the rollback journal.
- [Linux overlay filesystem, volatile mount](https://docs.kernel.org/filesystems/overlayfs.html#volatile-mount): `fsync=volatile` aliases the volatile mode and omits synchronization to the upper filesystem.
- [SQLite, replacing an open database pathname](https://sqlite.org/howtocorrupt.html#_unlinking_or_renaming_a_database_file_while_in_use): replacing an open file can separate the pathname from existing connections and invalidate journal coordination.
