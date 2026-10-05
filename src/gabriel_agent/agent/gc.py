"""Artifact garbage collection (blueprint: operations). Respects retained event references,
checkpoints, exports' anchors, the memory chain and active attempts.

The referenced set is the transitive closure over every artifact the journal, the memory
index, the checkpoints, the catalog records and the migration records name, following the
references nested inside JSON artifacts (a model request names its prompt, a snapshot its
retrieval manifest, a result its outputs). Only objects outside that closure and older than
the grace period are orphans; an attempt in flight may still be writing objects it has not
committed, which the grace period protects. Dry run by default; ``apply`` removes the orphans
and re-verifies the journal replay and the memory chain afterwards.
"""
from __future__ import annotations

import datetime
import json
import time
from pathlib import Path

from ..contracts.codec import canonical, loads, sha256_hex
from ..contracts.errors import GabrielError
from ..state.owner import _walk_refs


def referenced_closure(store, roots: dict) -> set:
    """Every artifact reachable from the roots ({sha256: media_type or None}) through nested references."""
    seen, queue = set(), list(roots.items())
    while queue:
        sha, media = queue.pop()
        if sha in seen:
            continue
        seen.add(sha)
        path = store.path_for(sha)
        if not path.is_file():
            continue
        if media is not None and not media.startswith("application/json"):
            continue
        try:
            raw = path.read_bytes()
            if raw[:1] not in (b"{", b"["):
                continue
            value = json.loads(raw.decode("utf8"))
        except (OSError, ValueError, UnicodeDecodeError):
            continue
        for ref in _walk_refs(value, {}).values():
            if ref["sha256"] not in seen:
                queue.append((ref["sha256"], ref["media_type"]))
    return seen


def roots_of(workspace) -> dict:
    owner, memory = workspace.owner, workspace.memory
    roots = {}
    for sha, media in owner._db.execute("SELECT sha256, media_type FROM artifact_refs").fetchall():
        roots[sha] = media
    # the retained inputs of every event name artifacts too (the admitted task record, the payload, grants)
    for (inputs_text,) in owner._db.execute("SELECT inputs_text FROM events").fetchall():
        for ref in _walk_refs(loads(inputs_text), {}).values():
            roots.setdefault(ref["sha256"], ref["media_type"])
    for (manifest_text,) in owner._db.execute("SELECT manifest_text FROM checkpoints").fetchall():
        for ref in _walk_refs(loads(manifest_text), {}).values():
            roots.setdefault(ref["sha256"], ref["media_type"])
    if owner._has_table("catalog_records"):
        for (sha,) in owner._db.execute("SELECT record_sha256 FROM catalog_records").fetchall():
            roots.setdefault(sha, "application/json")
    for record in owner.migrations():
        roots.setdefault(sha256_hex(canonical(record)), "application/json")
    if memory is not None:
        for sha in memory.referenced_artifacts():
            roots.setdefault(sha, None)
        for (sha,) in memory._db.execute("SELECT manifest_sha FROM cache").fetchall():
            roots.setdefault(sha, "application/json")
        for (sha,) in memory._db.execute("SELECT summary_sha FROM summaries").fetchall():
            roots.setdefault(sha, "application/json")
    profile = workspace.config.get("provider_profile_ref")
    if isinstance(profile, dict):
        roots.setdefault(profile["sha256"], profile["media_type"])
    return roots


def collect_garbage(workspace, *, apply: bool = False, grace_seconds: int = 3600, now: float | None = None) -> dict:
    owner, store, memory = workspace.owner, workspace.store, workspace.memory
    started = time.monotonic()
    roots = roots_of(workspace)
    referenced = referenced_closure(store, roots)
    orphans = store.scan_orphans(referenced, grace_seconds=grace_seconds, now=now)
    sizes = {}
    for name in orphans:
        try:
            sizes[name] = store.path_for(name).stat().st_size
        except OSError:
            sizes[name] = 0
    in_flight = [{"attempt_id": r[0], "run_id": r[1], "status": r[2]} for r in owner._db.execute(
        "SELECT attempt_id, run_id, status FROM attempts WHERE status IN ('issued','marked')").fetchall()]
    total_objects = sum(1 for _ in store.list_objects())
    report = {"schema": "gabriel.gc-report/1", "workspace_id": workspace.config["workspace_id"],
              "started_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(), "apply": bool(apply), "grace_seconds": int(grace_seconds),
              "roots": len(roots), "referenced": len(referenced), "objects": total_objects,
              "orphans": len(orphans), "orphan_bytes": sum(sizes.values()), "orphan_sample": sorted(orphans)[:64],
              "in_flight_attempts": in_flight, "removed": 0, "removed_bytes": 0, "replay": None, "memory": None}
    if apply:
        removed = store.collect(orphans)
        report["removed"] = removed
        report["removed_bytes"] = sum(sizes.values())
        # ADR-26: the re-verification replays from the latest verified checkpoint and retains the state it reached as the
        # next one, so every collection also bounds the next recovery; the full replay stays the audit (`gabriel audit`)
        checkpoint_id = "gc-%d-%d" % (int(time.time() * 1000), len(owner.checkpoints()) + 1)
        try:
            replay = owner.replay(from_checkpoint=True, record_checkpoint=checkpoint_id, reason="gc --apply re-verification")
        except GabrielError as exc:
            # the removal happened; the report says so and names the fault before it is raised
            report.update(replay="failed", error=exc.to_record(), status="storage_fault", elapsed_ms=int((time.monotonic() - started) * 1000))
            _write_report(workspace, report)
            raise
        report["replay"] = replay["status"]
        report["checkpoint"] = {"started_from": replay["checkpoint"], "events_reduced": replay["events_reduced"],
                                "recorded": None if replay["checkpoint_recorded"] is None else
                                {"checkpoint_id": checkpoint_id, "sequence": replay["events"], "run_count": replay["checkpoint_recorded"]["run_count"]},
                                "skipped": replay["checkpoints_skipped"]}
        report["memory"] = memory.verify()["status"] if memory is not None else None
        report["status"] = "passed" if report["replay"] == "passed" and report["memory"] in (None, "passed") else "storage_fault"
    else:
        report["status"] = "dry_run"
    report["elapsed_ms"] = int((time.monotonic() - started) * 1000)
    _write_report(workspace, report)
    return report


def _write_report(workspace, report: dict) -> None:
    directory = Path(workspace.path) / "gc"
    directory.mkdir(exist_ok=True)
    (directory / ("gc-%d.json" % int(time.time() * 1000))).write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n")
