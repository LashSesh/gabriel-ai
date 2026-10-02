"""WP12 / AT18: coherent backup, restore elsewhere, anchor, replay, export equality, corruption controls."""
import json
import os
import sqlite3
from pathlib import Path

import pytest

from gabriel_agent.agent import Workspace, TaskRunner, export_task
from gabriel_agent.agent.backup import backup, restore
from gabriel_agent.agent.release import release_manifest
from gabriel_agent.agent.workspace import build_registry
from gabriel_agent.contracts import GabrielError, Code, canonical
from gabriel_agent.evaluation.fixtures import parser_bug as fixture
from gabriel_agent.interfaces.cli import main as cli_main
from gabriel_agent.state import Owner


def finished_workspace(tmp_path):
    ws = Workspace.create(tmp_path / "ws", backend="trusted_local", allow_trusted_local=True)
    repo = tmp_path / "repo"
    base = fixture.build_repo(repo)
    oracle = fixture.write_oracle(tmp_path / "oracle_kvparse.py")
    spec = fixture.task_spec(repo, base, oracle, {"kind": "scripted", "script": fixture.script(), "max_input_tokens": 60000})
    created = ws.create_task(spec)
    summary = TaskRunner(ws, created["task_id"]).run()
    assert summary["state"] == "succeeded"
    return ws, created["task_id"], summary["run_id"]


def test_backup_restore_replay_and_export_match(tmp_path):
    ws, task_id, run_id = finished_workspace(tmp_path)
    delivered = export_task(ws, task_id, tmp_path / "delivery")
    manifest = backup(ws, tmp_path / "backup")
    assert manifest["anchor"] == ws.owner.anchor() and manifest["object_count"] > 10
    assert not (tmp_path / "backup" / "credentials").exists()
    ws.close()
    catalog = build_registry(lambda: None).catalog()
    report = restore(tmp_path / "backup", tmp_path / "restored", catalog=catalog)
    assert report["status"] == "passed" and report["replay"]["events"] == manifest["anchor"]["sequence"]
    assert report["anchor_check"]["anchored_sequence"] == manifest["anchor"]["sequence"]
    # the restored journal reaches the expected frontier and the retained bytes verify
    owner = Owner.open(tmp_path / "restored" / "journal.sqlite", __import__("gabriel_agent.artifacts", fromlist=["ObjectStore"]).ObjectStore.open(tmp_path / "restored" / "objects"), catalog)
    assert owner.anchor() == manifest["anchor"]
    projection = owner.projection(run_id)
    assert projection["run"]["state"] == "succeeded"
    store = owner.store
    for entry in projection["assessments"].values():
        assert store.verify(entry["evidence_ref"])
    # exported evidence bytes from the restored store equal the delivered bytes
    for path in sorted((tmp_path / "delivery" / "evidence").glob("*.json")):
        ref_sha = path.stem
        assert store.get({"sha256": ref_sha, "bytes": path.stat().st_size, "media_type": "application/json; charset=utf-8"}) == path.read_bytes()
    assert store.get(delivered["patch_ref"]) == (tmp_path / "delivery" / "patch.diff").read_bytes()
    owner.close()


def test_restore_rejects_corrupted_object_and_truncated_journal(tmp_path):
    ws, task_id, run_id = finished_workspace(tmp_path)
    manifest = backup(ws, tmp_path / "backup")
    ws.close()
    catalog = build_registry(lambda: None).catalog()
    # corrupt one referenced object inside the backup
    sha = next(iter(manifest["objects"]))
    path = tmp_path / "backup" / "objects" / sha[:2] / sha
    path.write_bytes(path.read_bytes() + b"x")
    with pytest.raises(GabrielError) as info:
        restore(tmp_path / "backup", tmp_path / "restored-corrupt", catalog=catalog)
    assert info.value.code is Code.STORAGE_FAULT and info.value.details["object_faults"][0]["fault"] == "corrupt"
    path.write_bytes(path.read_bytes()[:-1])
    # truncate the journal suffix while keeping the retained anchor: the anchor detects it
    db = sqlite3.connect(str(tmp_path / "backup" / "journal.sqlite"))
    last = db.execute("SELECT MAX(sequence) FROM events").fetchone()[0]
    db.execute("DELETE FROM events WHERE sequence=?", (last,))
    db.execute("DELETE FROM commands WHERE sequence=?", (last,))
    db.execute("UPDATE meta SET event_count=event_count-1, head=(SELECT hash FROM events WHERE sequence=?), inputs_head=(SELECT inputs_hash FROM events WHERE sequence=?)", (last - 1, last - 1))
    db.commit(); db.close()
    truncated = json.loads((tmp_path / "backup" / "manifest.json").read_text())
    truncated["database_sha256"] = __import__("hashlib").sha256((tmp_path / "backup" / "journal.sqlite").read_bytes()).hexdigest()
    (tmp_path / "backup" / "manifest.json").write_text(json.dumps(truncated))
    with pytest.raises(GabrielError) as info:
        restore(tmp_path / "backup", tmp_path / "restored-truncated", catalog=catalog)
    assert info.value.code is Code.STORAGE_FAULT and "anchor" in info.value.message or "shorter" in info.value.message


def test_cli_backup_restore_and_release_manifest(tmp_path, capsys):
    ws, task_id, run_id = finished_workspace(tmp_path)
    ws.close()
    assert cli_main(["backup", "--workspace", str(tmp_path / "ws"), "--out", str(tmp_path / "bk")]) == 0
    capsys.readouterr()
    assert cli_main(["restore", "--from", str(tmp_path / "bk"), "--workspace", str(tmp_path / "rs")]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "passed"
    assert cli_main(["release-manifest", "--workspace", str(tmp_path / "ws"), "--out", str(tmp_path / "release.json"), "--root", str(Path(__file__).resolve().parents[1])]) == 0
    manifest = json.loads((tmp_path / "release.json").read_text())
    assert manifest["schema"] == "gabriel.release-manifest/1" and manifest["package_source_files"] > 50
    assert manifest["license"]["status"] == "unresolved" and "G2" in manifest["gates"]
    assert manifest["catalog_digest"] and manifest["doctor"]["configured_backend"] == "trusted_local"


def test_release_manifest_binds_source_identity(tmp_path):
    root = Path(__file__).resolve().parents[1]
    first = release_manifest(root)
    second = release_manifest(root)
    assert first["package_source_identity"] == second["package_source_identity"]
    assert first["schema_registry_digest"] == second["schema_registry_digest"] and first["reducer_identity"]
