"""Artifact export: patch, base identity, final tree identity, assessment manifest and gaps."""
from __future__ import annotations

import json
from pathlib import Path

from ..contracts.codec import canonical, loads, dumps_utf8
from ..contracts.errors import Code, GabrielError
from ..contracts.schemas import validate, validate_bytes
from ..contracts.rules import mandatory_check_ids


def export_task(workspace, task_id: str, out_dir) -> dict:
    out = Path(out_dir)
    if out.exists() and any(out.iterdir()):
        raise GabrielError(Code.STORAGE_FAULT, "export directory is not empty: " + str(out))
    out.mkdir(parents=True, exist_ok=True)
    run_id, _ = workspace.resolve_task(task_id)
    projection = workspace.owner.projection(run_id)
    binding = validate_bytes(workspace.store.get(projection["binding_ref"]), "task-binding")
    report = validate_bytes(workspace.store.get(projection["compilation_report_ref"]), "compilation-report")
    worktree = workspace.worktree_for(run_id, binding)
    patch = worktree.patch()
    patch_ref = workspace.store.put(patch, "text/x-diff; charset=utf-8")
    (out / "patch.diff").write_bytes(patch)
    task = projection["task"]
    mandatory = mandatory_check_ids(task)
    current = {}
    for entry in projection["assessments"].values():
        if entry["eligible"] and entry["task_spec_revision"] == task["task_spec_revision"] and entry["evidence_revision"] == projection["run_meta"]["evidence_revision"]:
            current[entry["check_id"]] = entry
    rows, evidence_refs, unresolved = [], [], []
    for check in task["checks"]:
        entry = current.get(check["check_id"])
        outcome = entry["outcome"] if entry else "not_run"
        established = bool(entry) and outcome == "passed"
        rows.append({"check_id": check["check_id"], "mandatory": check["mandatory"], "outcome": outcome,
                     "assessment_id": entry["assessment_id"] if entry else None, "established": established})
        if entry:
            evidence_refs.append(entry["evidence_ref"])
        if check["mandatory"] and not established:
            unresolved.append("mandatory check %s: %s" % (check["check_id"], outcome))
    for failed in [a for a in projection["assessments"].values() if a["outcome"] == "failed"]:
        unresolved.append("retained failure: %s (%s)" % (failed["check_id"], failed["assessment_id"]))
    review = [c["reason"] for c in report["clauses"] if c["status"] in ("excluded_optional", "unsupported", "ambiguous")]
    if projection["run"]["unresolved_effect_ids"]:
        unresolved.append("unresolved external effects: " + ",".join(projection["run"]["unresolved_effect_ids"]))
    if projection["run_meta"]["hold"]:
        unresolved.append("hold: " + projection["run_meta"]["hold"]["reason_code"])
    manifest = {"schema": "gabriel.export-manifest/1", "export_id": "export-" + run_id, "task_id": task_id, "run_id": run_id,
                "run_state": projection["run"]["state"], "base_commit": binding["base_commit"], "final_tree_digest": worktree.tree_digest(),
                "patch_ref": patch_ref, "assessments": rows, "unresolved_issues": [u[:512] for u in unresolved][:64],
                "evidence_refs": evidence_refs[:256], "anchor": workspace.owner.anchor(), "claims_requiring_user_review": [r[:512] for r in review][:64]}
    validate(manifest, "export-manifest")
    (out / "manifest.json").write_bytes(canonical(manifest) + b"\n")
    (out / "anchor.json").write_bytes(canonical(manifest["anchor"]) + b"\n")
    (out / "task.json").write_bytes(canonical(task) + b"\n")
    (out / "binding.json").write_bytes(canonical(binding) + b"\n")
    (out / "compilation_report.json").write_bytes(canonical(report) + b"\n")
    evidence_dir = out / "evidence"
    evidence_dir.mkdir()
    assessments = []
    for entry in projection["assessments"].values():
        record = loads(workspace.store.get(entry["assessment_ref"]))
        assessments.append(record)
        raw = workspace.store.get(entry["evidence_ref"])
        (evidence_dir / (entry["evidence_ref"]["sha256"] + ".json")).write_bytes(raw)
    (out / "assessments.json").write_bytes(dumps_utf8(assessments) + b"\n")
    (out / "README.txt").write_text(
        "Gabriel export for %s (%s)\nrun state: %s\nbase commit: %s\nfinal tree digest: %s\n\nEstablished claims are the rows with established=true in manifest.json.\n"
        "Unresolved issues and claims requiring user review are listed in manifest.json. Success follows the checks, not this export.\n"
        % (task_id, run_id, projection["run"]["state"], binding["base_commit"], manifest["final_tree_digest"]))
    return manifest
