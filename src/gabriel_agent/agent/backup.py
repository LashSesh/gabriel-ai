"""Coherent backup and restore of a workspace (WP12, AT18).

A backup captures a coherent database snapshot through SQLite's online
backup API, every artifact in the referenced closure of the journal and the
memory chain (the set the garbage collector keeps, byte-verified; ADR-25), the
workspace configuration, the independent anchor and a manifest. Restore
rebuilds the layout elsewhere, re-verifies every referenced object, checks
the restored journal against the independently retained anchor and replays
it. The principal secret is never part of a backup.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import shutil
from pathlib import Path

from .. import __version__
from ..artifacts import ObjectStore
from ..contracts.codec import canonical, loads
from ..contracts.errors import Code, GabrielError
from ..contracts.schemas import registry_digest, validate
from ..memory import MemoryService
from ..state import Owner
from ..state.reducer import reducer_identity


def backup(workspace, destination) -> dict:
    destination = Path(destination)
    if destination.exists() and any(destination.iterdir()):
        raise GabrielError(Code.STORAGE_FAULT, "backup destination is not empty: " + str(destination))
    destination.mkdir(parents=True, exist_ok=True)
    from .gc import referenced_closure, roots_of
    owner, store = workspace.owner, workspace.store
    db = owner.backup(destination / "journal.sqlite")
    anchor = db["anchor"]
    memory_anchor = None
    if getattr(workspace, "memory", None) is not None:
        memory_anchor = workspace.memory.backup(destination / "memory.sqlite")
    # ADR-25: the backup carries the same closure the garbage collector keeps (the retained catalog and migration
    # records, the task specs and grants named by every event's retained inputs, the artifacts nested inside JSON
    # artifacts such as a request's prompt), not only the top-level references, so a restore after a recorded
    # migration can replay every epoch with its retained catalog
    referenced = sorted(referenced_closure(store, roots_of(workspace)))
    objects = destination / "objects"
    objects.mkdir()
    copied = {}
    for sha in referenced:
        src = store.path_for(sha)
        if not src.is_file():
            raise GabrielError(Code.STORAGE_FAULT, "referenced artifact missing from the store: " + sha, obj=sha)
        raw = src.read_bytes()
        if hashlib.sha256(raw).hexdigest() != sha:
            raise GabrielError(Code.STORAGE_FAULT, "referenced artifact bytes changed: " + sha, obj=sha)
        target = objects / sha[:2] / sha
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        copied[sha] = len(raw)
    (destination / "config.json").write_bytes(canonical(workspace.config) + b"\n")
    (destination / "anchor.json").write_bytes(canonical(anchor) + b"\n")
    if memory_anchor is not None:
        (destination / "memory_anchor.json").write_bytes(canonical(memory_anchor) + b"\n")
    manifest = {"schema": "gabriel.backup-manifest/1", "version": __version__, "workspace_id": workspace.config["workspace_id"],
                "created_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(), "anchor": anchor,
                "database_sha256": hashlib.sha256((destination / "journal.sqlite").read_bytes()).hexdigest(),
                "memory_sha256": hashlib.sha256((destination / "memory.sqlite").read_bytes()).hexdigest() if memory_anchor is not None else None,
                "memory_anchor": memory_anchor,
                "objects": copied, "object_count": len(copied), "object_bytes": sum(copied.values()),
                # the identities the journal registered (equal to the running code's unless a migration is pending)
                "catalog_digest": owner.registered["catalog_digest"], "schema_registry_digest": owner.registered["schema_registry_digest"],
                "reducer_identity": owner.registered["reducer_identity"],
                "running": {"catalog_digest": owner.catalog_digest, "schema_registry_digest": registry_digest(), "reducer_identity": reducer_identity()},
                "excluded": ["credentials/ (principal secret)", "worktrees/ (disposable; patches are exported separately)", "runs/ runtime notes"]}
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def restore(source, destination, *, catalog, clock=None) -> dict:
    """Rebuild a workspace from a backup and verify it against the retained anchor."""
    source, destination = Path(source), Path(destination)
    manifest = json.loads((source / "manifest.json").read_text())
    if manifest.get("schema") != "gabriel.backup-manifest/1":
        raise GabrielError(Code.UNSUPPORTED, "not a Gabriel backup")
    if destination.exists() and any(destination.iterdir()):
        raise GabrielError(Code.STORAGE_FAULT, "restore destination is not empty: " + str(destination))
    destination.mkdir(parents=True, exist_ok=True)
    db_bytes = (source / "journal.sqlite").read_bytes()
    if hashlib.sha256(db_bytes).hexdigest() != manifest["database_sha256"]:
        raise GabrielError(Code.STORAGE_FAULT, "backup database bytes differ from the manifest")
    (destination / "journal.sqlite").write_bytes(db_bytes)
    shutil.copy(source / "config.json", destination / "config.json")
    if manifest.get("memory_sha256"):
        memory_bytes = (source / "memory.sqlite").read_bytes()
        if hashlib.sha256(memory_bytes).hexdigest() != manifest["memory_sha256"]:
            raise GabrielError(Code.STORAGE_FAULT, "backup memory index bytes differ from the manifest")
        (destination / "memory.sqlite").write_bytes(memory_bytes)
    store = ObjectStore.create(destination / "objects")
    verified, faults = 0, []
    for sha, size in manifest["objects"].items():
        path = source / "objects" / sha[:2] / sha
        try:
            raw = path.read_bytes()
        except OSError:
            faults.append({"sha256": sha, "fault": "missing"})
            continue
        if len(raw) != size or hashlib.sha256(raw).hexdigest() != sha:
            faults.append({"sha256": sha, "fault": "corrupt"})
            continue
        store.put(raw, "application/octet-stream")
        verified += 1
    (destination / "credentials").mkdir(mode=0o700)
    (destination / "worktrees").mkdir()
    (destination / "runs").mkdir()
    anchor = validate(loads((source / "anchor.json").read_bytes()), "anchor")
    report = {"schema": "gabriel.restore-report/1", "destination": str(destination), "objects_verified": verified, "object_faults": faults,
              "anchor": anchor, "anchor_check": None, "replay": None, "status": "storage_fault",
              "note": "the principal secret is not restored; create a new credential before submitting commands"}
    if faults:
        (destination / "restore_report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        raise GabrielError(Code.STORAGE_FAULT, "restore verification failed: %d referenced object(s) missing or corrupt" % len(faults), details=report)
    owner = Owner.open(destination / "journal.sqlite", store, catalog, clock=clock)
    try:
        report["anchor_check"] = owner.verify_anchor(anchor)
        report["replay"] = owner.replay(expected_anchor=anchor)
        report["memory"] = None
        if manifest.get("memory_sha256"):
            memory = MemoryService.open(destination / "memory.sqlite", store, lambda: owner.anchor()["sequence"])
            try:
                check = memory.verify()
                retained = loads((source / "memory_anchor.json").read_bytes())
                check["anchor_match"] = retained["head"] == check["head"] and retained["memory_sequence"] == check["entries"]
                if not check["anchor_match"]:
                    check["status"] = "storage_fault"
                    check["faults"].append({"fault": "memory_anchor_mismatch"})
                report["memory"] = check
            finally:
                memory.close()
    finally:
        owner.close()
    memory_ok = report["memory"] is None or report["memory"]["status"] == "passed"
    report["status"] = "passed" if report["replay"]["status"] == "passed" and memory_ok else "storage_fault"
    (destination / "restore_report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    if report["status"] != "passed":
        raise GabrielError(Code.STORAGE_FAULT, "restore verification failed: replay or memory chain reported missing or changed bytes", details=report)
    return report
