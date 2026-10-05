"""Operations, observability and release discipline (blueprint section): explicit versioned
migrations with backup, equivalence replay and refusal; startup validation; the clean shutdown
contract; telemetry; metrics; artifact garbage collection."""
import json
import os
import signal
import time
from pathlib import Path

import pytest

from gabriel_agent.agent import TaskRunner, Workspace
from gabriel_agent.agent import workspace as workspace_module
from gabriel_agent.contracts import GabrielError
from gabriel_agent.contracts.errors import Code
from gabriel_agent.contracts.codec import loads
from gabriel_agent.domains.base import descriptor
from gabriel_agent.evaluation.fixtures import parser_bug
from gabriel_agent.interfaces import cli
from gabriel_agent.state import owner as owner_module


def finished_workspace(tmp_path, name="ws"):
    root = tmp_path / name
    repo = root / "repo"
    base = parser_bug.build_repo(repo)
    oracle = parser_bug.write_oracle(root / "oracle_kvparse.py")
    spec = parser_bug.task_spec(repo, base, oracle, {"kind": "scripted", "script": parser_bug.script(), "max_input_tokens": 60000})
    ws = Workspace.create(root / "workspace", backend="trusted_local", allow_trusted_local=True)
    created = ws.create_task(spec)
    summary = TaskRunner(ws, created["task_id"]).run()
    assert summary["state"] == "succeeded", summary["log"]
    return ws, created, spec


class _Probe:
    """An extra read-only tool: registering it changes the capability catalog of the running code."""

    def __call__(self, intent, args, ctx):
        raise NotImplementedError

    def reconcile(self, intent, attempt, ctx):
        return "confirmed_not_executed", b"{}"


def _registry_with_probe(backend_resolver):
    registry = _ORIGINAL_BUILD_REGISTRY(backend_resolver)
    registry.register_tool(descriptor("ops.probe", "read", "read_back", "read", pack_label="ops"), _Probe())
    return registry


_ORIGINAL_BUILD_REGISTRY = workspace_module.build_registry


# ------------------------------------------------------------------ explicit migrations

def test_catalog_change_refuses_open_and_an_explicit_migration_moves_the_journal(tmp_path, monkeypatch):
    ws, created, spec = finished_workspace(tmp_path)
    path, run_id = ws.path, created["run_id"]
    events_before = ws.owner.anchor()["sequence"]
    ws.close()
    # the running code's catalog changed: a plain open refuses, naming the explicit migration
    monkeypatch.setattr(workspace_module, "build_registry", _registry_with_probe)
    with pytest.raises(GabrielError) as excinfo:
        Workspace.open(path)
    assert "explicit migration" in excinfo.value.message
    report = Workspace.migrate(path, reason="ops.probe tool added to the catalog")
    assert report["status"] == "migrated", report
    assert report["backup"]["object_count"] > 0 and Path(report["backup"]["path"]).is_dir()
    assert report["equivalence_replay"]["events"] == events_before and report["replay_after"]["status"] == "passed"
    migration = report["migration"]
    assert migration["from_catalog_digest"] == report["registered"]["catalog_digest"] and migration["to_catalog_digest"] == report["running"]["catalog_digest"]
    assert migration["sequence"] == events_before and migration["replayed_events"] == events_before
    assert (path / "migrations" / (migration["migration_id"] + ".json")).is_file()
    # the migrated workspace opens, replays across the epoch boundary and keeps working
    ws2 = Workspace.open(path)
    try:
        assert ws2.owner.migrations()[0]["migration_id"] == migration["migration_id"]
        assert ws2.owner.replay()["status"] == "passed"
        assert ws2.owner.run_record(run_id)["state"] == "succeeded"
        assert ws2.config["config_revision"] == 1 and ws2.config["registry_digest"] == ws2.registry.catalog_digest()
        startup = ws2.startup_validation()
        assert [m["migration_id"] for m in startup["migrations"]] == [migration["migration_id"]]
        assert Workspace.migrate(path, reason="again")["status"] == "nothing_to_migrate"
    finally:
        ws2.close()
    # the events retain the digest in force when they were committed: the old code can no longer open the journal
    monkeypatch.setattr(workspace_module, "build_registry", _ORIGINAL_BUILD_REGISTRY)
    with pytest.raises(GabrielError):
        Workspace.open(path)
    # ... but it can be migrated back explicitly, which is a second recorded epoch
    back = Workspace.migrate(path, reason="ops.probe tool removed again")
    assert back["status"] == "migrated" and back["migration"]["from_catalog_digest"] == migration["to_catalog_digest"]
    ws3 = Workspace.open(path)
    try:
        assert len(ws3.owner.migrations()) == 2 and ws3.owner.replay()["status"] == "passed"
        # the journal still accepts commands after two migrations
        created2 = ws3.create_task(spec)
        assert TaskRunner(ws3, created2["task_id"]).run()["state"] == "succeeded"
        assert ws3.owner.replay()["status"] == "passed"
    finally:
        ws3.close()


def test_migration_is_refused_when_the_new_code_does_not_reproduce_the_journal(tmp_path, monkeypatch):
    ws, created, _ = finished_workspace(tmp_path)
    path = ws.path
    meta_before = (ws.owner.registered, ws.owner.anchor())
    ws.close()
    monkeypatch.setattr(workspace_module, "build_registry", _registry_with_probe)
    original_reduce = owner_module.reduce

    def tampering_reduce(projection, command, payload, inputs):
        result = original_reduce(projection, command, payload, inputs)
        result.projection["run_meta"]["tampered"] = True  # a reducer that produces other projections
        return result

    monkeypatch.setattr(owner_module, "reduce", tampering_reduce)
    report = Workspace.migrate(path, reason="catalog change with a reducer that differs")
    assert report["status"] == "refused" and "replayed projection differs" in report["equivalence_replay"]["error"]
    assert Path(report["backup"]["path"]).is_dir()
    refused = list((path / "migrations").glob("refused-*.json"))
    assert len(refused) == 1
    monkeypatch.setattr(owner_module, "reduce", original_reduce)
    monkeypatch.setattr(workspace_module, "build_registry", _ORIGINAL_BUILD_REGISTRY)
    # nothing changed: the old code opens the journal exactly as before, no migration recorded
    ws2 = Workspace.open(path)
    try:
        assert ws2.owner.migrations() == [] and (ws2.owner.registered, ws2.owner.anchor()) == meta_before
        assert ws2.owner.replay()["status"] == "passed"
    finally:
        ws2.close()


def test_cli_migrate_reports_and_exits_by_outcome(tmp_path, monkeypatch, capsys):
    ws, _, _ = finished_workspace(tmp_path)
    path = ws.path
    ws.close()
    assert cli.main(["migrate", "--workspace", str(path), "--reason", "no change"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "nothing_to_migrate"
    monkeypatch.setattr(workspace_module, "build_registry", _registry_with_probe)
    assert cli.main(["migrate", "--workspace", str(path), "--reason", "probe added"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "migrated" and out["migration"]["reason"] == "probe added"
    cli.main(["doctor", "--workspace", str(path)])  # exit 3: a trusted_local workspace always reports its mode as a problem
    doctor = json.loads(capsys.readouterr().out)
    assert len(doctor["startup"]["migrations"]) == 1 and not any("referenced object" in p for p in doctor["problems"])


# ------------------------------------------------------------------ startup validation

def test_startup_validation_reports_storage_root_and_reconciliation_work(tmp_path):
    ws, created, _ = finished_workspace(tmp_path)
    try:
        report = ws.doctor(deep=True)
        startup = report["startup"]
        assert startup["journal_format"] == "gabriel.agent-journal/1" and startup["storage"]["referenced_objects"] > 0
        assert startup["storage"]["missing"] == [] and startup["storage"]["corrupt"] == [] and startup["storage"]["deep"]
        assert startup["artifact_root"]["exists"] and startup["artifact_root"]["writable"]
        assert startup["reconciliation_work"] == [] and startup["memory_chain"]["schema"] == "gabriel.memory-anchor/1"
        assert not any("referenced object" in p for p in report["problems"])
        # a referenced object with changed bytes is only found by the deep check; a missing one by both
        sha = sorted(ws.owner.referenced_artifacts())[0]
        target = ws.store.path_for(sha)
        original = target.read_bytes()
        target.write_bytes(original + b"x")
        assert ws.doctor()["startup"]["storage"]["corrupt"] == []
        deep = ws.doctor(deep=True)
        assert deep["startup"]["storage"]["corrupt"] == [sha] and any("changed bytes" in p for p in deep["problems"])
        target.unlink()
        shallow = ws.doctor()
        assert shallow["startup"]["storage"]["missing"] == [sha] and any("missing from the store" in p for p in shallow["problems"])
        target.write_bytes(original)
        assert ws.doctor(deep=True)["startup"]["storage"]["missing"] == []
        # an expired lease of a crashed supervisor is reconciliation work, listed and never repeated automatically
        run_id = created["run_id"]
        ws.owner._db.execute("INSERT INTO attempts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                             ("attempt-crashed", run_id, "intent-crashed", "lease-crashed", 999, "step-x", "marked", "unknown", "target-x", "key-x", 1,
                              "software.apply_patch", "{}"))
        ws.owner._db.commit()
        report = ws.doctor()
        assert [a["attempt_id"] for a in report["startup"]["reconciliation_work"]] == ["attempt-crashed"]
        assert any("await reconciliation" in p for p in report["problems"])
    finally:
        ws.close()


# ------------------------------------------------------------------ clean shutdown contract

def test_stop_request_records_a_pause_and_the_run_resumes_from_the_journal(tmp_path):
    root = tmp_path / "shutdown"
    repo = root / "repo"
    base = parser_bug.build_repo(repo)
    oracle = parser_bug.write_oracle(root / "oracle_kvparse.py")
    spec = parser_bug.task_spec(repo, base, oracle, {"kind": "scripted", "script": parser_bug.script(), "max_input_tokens": 60000})
    ws = Workspace.create(root / "workspace", backend="trusted_local", allow_trusted_local=True)
    try:
        created = ws.create_task(spec)
        runner = TaskRunner(ws, created["task_id"])
        runner.request_stop()
        summary = runner.run()
        assert summary["stop_requested"] and summary["pause_requested"] and summary["state"] not in ("succeeded", "failed", "cancelled")
        assert any("shutdown requested" in line for line in summary["log"])
        assert ws.owner.replay()["status"] == "passed"
        ws.resume(created["task_id"])
        summary2 = TaskRunner(ws, created["task_id"]).run()
        assert summary2["state"] == "succeeded" and not summary2["pause_requested"], summary2["log"]
    finally:
        ws.close()


def test_sigterm_during_a_run_stops_cleanly_at_the_next_boundary(tmp_path):
    root = tmp_path / "sigterm"
    repo = root / "repo"
    base = parser_bug.build_repo(repo)
    oracle = parser_bug.write_oracle(root / "oracle_kvparse.py")
    spec = parser_bug.task_spec(repo, base, oracle, {"kind": "scripted", "script": parser_bug.script(), "max_input_tokens": 60000})
    ws = Workspace.create(root / "workspace", backend="trusted_local", allow_trusted_local=True)
    try:
        created = ws.create_task(spec)
        sent = {"count": 0}

        def hook(stage):
            # the third committed event of the run: the handler installed by run() receives the signal
            if stage == "after_commit":
                sent["count"] += 1
                if sent["count"] == 3:
                    os.kill(os.getpid(), signal.SIGTERM)
        ws.owner._hook = hook
        summary = TaskRunner(ws, created["task_id"]).run()
        ws.owner._hook = None
        assert summary["stop_requested"] and summary["pause_requested"], summary["log"]
        assert summary["state"] not in ("succeeded", "failed", "cancelled")
        assert signal.getsignal(signal.SIGTERM) == signal.SIG_DFL  # the previous handler is restored after run()
        ws.resume(created["task_id"])
        summary2 = TaskRunner(ws, created["task_id"]).run()
        assert summary2["state"] == "succeeded", summary2["log"]
        assert ws.owner.replay()["status"] == "passed"
    finally:
        ws.close()


def _registry_with_changed_verifier(backend_resolver):
    """The software test verifier's implementation changed: its registered fingerprint differs, so
    assessments of earlier epochs can only be reproduced with the catalog retained for them."""
    registry = _ORIGINAL_BUILD_REGISTRY(backend_resolver)
    record, impl = registry._verifiers["software.test_passed"]
    registry._verifiers["software.test_passed"] = (dict(record, implementation_fingerprint="f" * 64), impl)
    return registry


def test_changed_verifier_migrates_a_journal_whose_epoch_catalog_was_retained(tmp_path, monkeypatch):
    ws, created, spec = finished_workspace(tmp_path)
    path, run_id = ws.path, created["run_id"]
    assessments_before = len(ws.owner.projection(run_id)["assessments"])
    ws.close()
    monkeypatch.setattr(workspace_module, "build_registry", _registry_with_changed_verifier)
    report = Workspace.migrate(path, reason="software.test_passed implementation changed")
    assert report["status"] == "migrated", report
    ws2 = Workspace.open(path)
    try:
        # the old run's assessments replay against the catalog retained for their epoch
        assert ws2.owner.replay()["status"] == "passed" and len(ws2.owner.projection(run_id)["assessments"]) == assessments_before
        # a new task is assessed by the changed verifier under the new epoch and replays as well
        created2 = ws2.create_task(spec)
        assert TaskRunner(ws2, created2["task_id"]).run()["state"] == "succeeded"
        assert ws2.owner.replay()["status"] == "passed"
        digests = {m["from_catalog_digest"] for m in ws2.owner.migrations()} | {m["to_catalog_digest"] for m in ws2.owner.migrations()}
        assert all(ws2.owner._catalog_for_digest(d) is not None for d in digests)
    finally:
        ws2.close()


# ------------------------------------------------------------------ telemetry and metrics

def test_spans_separate_the_named_phases_and_carry_no_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("GABRIEL_TEST_SECRET", "sk-live-9f8e7d6c5b4a-never-in-telemetry")
    ws, created, _ = finished_workspace(tmp_path)
    try:
        run_id = created["run_id"]
        report = ws.trace(run_id)
        kinds = {s["kind"] for s in report["spans"]}
        assert {"run", "queue_wait", "provider", "tool_execution", "verification", "journal_commit"} <= kinds, kinds
        run_span = next(s for s in report["spans"] if s["kind"] == "run")
        assert run_span["parent_span_id"] is None and run_span["attributes"]["state"] == "succeeded" and run_span["duration_ms"] >= 0
        commits = [s for s in report["spans"] if s["kind"] == "journal_commit"]
        # commits of the run nest under the run span; the admission commit precedes the run
        assert commits and all(s["parent_span_id"] == run_span["span_id"] for s in commits if s["attributes"].get("op") != "admit_task")
        assert next(s for s in commits if s["attributes"].get("op") == "admit_task")["parent_span_id"] is None
        assert all(s["task_id"] == created["task_id"] for s in report["spans"])
        tools = [s for s in report["spans"] if s["kind"] == "tool_execution"]
        assert {s["attributes"]["capability_id"] for s in tools} >= {"software.observe", "model.generate", "software.apply_patch"}
        assert all(s["attempt_id"] for s in tools) and all(s["step_id"] for s in tools)
        verifications = [s for s in report["spans"] if s["kind"] == "verification"]
        assert any(s["attributes"]["independent"] for s in verifications) and all(s["attributes"]["check_id"] for s in verifications)
        provider = next(s for s in report["spans"] if s["kind"] == "provider")
        assert provider["attributes"]["provider_status"] == "completed" and provider["attributes"]["prompt_bytes"] > 0
        io = report["summary"]["artifact_io"]
        assert io["put_calls"] > 0 and io["get_calls"] > 0 and io["put_bytes"] > 0
        assert report["exporter"]["dropped"] == 0 and report["exporter"]["written"] == len(read_all(ws))
        # identifiers, kinds and counters only: no secret, prompt or artifact bytes reach the trace file
        raw = ws.tracer.path.read_text()
        secret = (ws.path / "credentials" / "local-user.secret").read_text().strip()
        assert secret not in raw and "sk-live-9f8e7d6c5b4a" not in raw and "You are the worker role" not in raw
        # the CLI exposes the same
        import io as _io, contextlib
        buffer = _io.StringIO()
        with contextlib.redirect_stdout(buffer):
            assert cli.main(["trace", run_id, "--workspace", str(ws.path), "--summary"]) == 0
        summary = json.loads(buffer.getvalue())
        assert "spans" not in summary and summary["summary"]["per_kind"]["tool_execution"]["count"] == len(tools)
    finally:
        ws.close()


def read_all(ws):
    from gabriel_agent.telemetry import read_spans
    return read_spans(ws.tracer.path)


def test_exporter_failure_never_affects_the_audit_journal(tmp_path):
    root = tmp_path / "noexport"
    repo = root / "repo"
    base = parser_bug.build_repo(repo)
    oracle = parser_bug.write_oracle(root / "oracle_kvparse.py")
    spec = parser_bug.task_spec(repo, base, oracle, {"kind": "scripted", "script": parser_bug.script(), "max_input_tokens": 60000})
    ws = Workspace.create(root / "workspace", backend="trusted_local", allow_trusted_local=True)
    try:
        # the exporter path is a directory: every write fails
        ws.tracer.path.parent.mkdir(parents=True, exist_ok=True)
        ws.tracer.path.mkdir()
        created = ws.create_task(spec)
        summary = TaskRunner(ws, created["task_id"]).run()
        assert summary["state"] == "succeeded", summary["log"]
        assert ws.tracer.dropped > 0 and ws.tracer.written == 0
        assert ws.owner.replay()["status"] == "passed"
        metrics = ws.metrics(created["run_id"])
        assert metrics["exporter"]["dropped"] == ws.tracer.dropped and metrics["runs"][0]["telemetry"] == {}
    finally:
        ws.close()


def test_metrics_report_the_blueprint_quantities_per_run(tmp_path):
    ws, created, _ = finished_workspace(tmp_path)
    try:
        report = ws.metrics()
        assert report["totals"]["runs"] == 1 and report["totals"]["declared_successes"] == 1 and report["totals"]["by_state"] == {"succeeded": 1}
        run = report["runs"][0]
        assert run["run_id"] == created["run_id"] and run["declared_success"] and run["state"] == "succeeded"
        assert run["independent_checks"]["passed"] >= 1 and run["independent_checks"]["failed"] == 0
        assert run["unknown_effects"] == 0 and run["retries"] == 0 and run["budget_overruns"] == 0 and run["holds"] == 0 and run["recovery_ms"] == 0
        assert run["time_to_first_useful_artifact_ms"] is not None and 0 <= run["time_to_first_useful_artifact_ms"] <= run["total_ms"]
        assert run["resource_use"]["model_requests"] >= 1 and run["path"] == "cold" and run["events"] > 0
        assert run["telemetry"]["tool_execution"]["count"] >= 3
        single = ws.metrics(created["run_id"])
        assert single["runs"] == [run]
    finally:
        ws.close()


# ------------------------------------------------------------------ artifact garbage collection

def test_gc_removes_only_unreferenced_objects_past_the_grace_period(tmp_path):
    ws, created, _ = finished_workspace(tmp_path)
    try:
        store = ws.store
        run_id = created["run_id"]
        # an artifact referenced only inside another JSON artifact: the worker prompt named by the retained model request
        projection = ws.owner.projection(run_id)
        request = loads(store.get(projection["nodes"]["propose"]["outputs"]["request"]))
        prompt_sha = request["prompt_ref"]["sha256"]
        assert prompt_sha not in ws.owner.referenced_artifacts()  # nested, not a top-level journal reference
        old = [store.put(b"stray-%d" % i, "application/octet-stream")["sha256"] for i in range(3)]
        fresh = store.put(b"fresh-stray", "application/octet-stream")["sha256"]
        past = time.time() - 7200
        for sha in old:
            os.utime(store.path_for(sha), (past, past))
        dry = ws.gc(grace_seconds=3600)
        assert dry["status"] == "dry_run" and dry["orphans"] == 3 and set(dry["orphan_sample"]) == set(old) and dry["removed"] == 0
        assert all(store.path_for(sha).is_file() for sha in old + [fresh])
        assert prompt_sha in referenced_set(ws) and dry["referenced"] > dry["roots"]
        applied = ws.gc(apply=True, grace_seconds=3600)
        assert applied["status"] == "passed" and applied["removed"] == 3 and applied["replay"] == "passed" and applied["memory"] == "passed"
        assert not any(store.path_for(sha).is_file() for sha in old) and store.path_for(fresh).is_file()
        assert store.path_for(prompt_sha).is_file() and store.get(request["prompt_ref"])
        # with no grace, the fresh stray goes too; nothing referenced is ever touched
        before = {name for name, _ in store.list_objects()}
        applied2 = ws.gc(apply=True, grace_seconds=0)
        assert applied2["removed"] == 1 and not store.path_for(fresh).is_file()
        assert {name for name, _ in store.list_objects()} == before - {fresh}
        assert ws.owner.replay()["status"] == "passed" and ws.memory.verify()["status"] == "passed"
        assert ws.doctor()["startup"]["storage"]["missing"] == []
        assert list((ws.path / "gc").glob("gc-*.json"))
    finally:
        ws.close()


def referenced_set(ws):
    from gabriel_agent.agent.gc import referenced_closure, roots_of
    return referenced_closure(ws.store, roots_of(ws))


def test_cli_gc_dry_run_and_apply(tmp_path, capsys):
    ws, _, _ = finished_workspace(tmp_path)
    path = ws.path
    sha = ws.store.put(b"cli-stray", "application/octet-stream")["sha256"]
    past = time.time() - 7200
    os.utime(ws.store.path_for(sha), (past, past))
    ws.close()
    assert cli.main(["gc", "--workspace", str(path)]) == 0
    dry = json.loads(capsys.readouterr().out)
    assert dry["status"] == "dry_run" and dry["orphans"] == 1
    assert cli.main(["gc", "--workspace", str(path), "--apply"]) == 0
    applied = json.loads(capsys.readouterr().out)
    assert applied["status"] == "passed" and applied["removed"] == 1


# ------------------------------------------------------------------ ADR-25: backup closure, worktree retirement

def test_backup_carries_the_referenced_closure_so_a_restore_after_a_migration_replays_every_epoch(tmp_path, monkeypatch):
    """ADR-25: the backup copies the same closure the garbage collector keeps (the retained catalog
    of every epoch, the task specs named by the events' inputs, the artifacts nested in JSON
    artifacts), so a backup taken after a recorded migration restores and replays across the
    epoch boundary; before ADR-25 the restore failed with a missing old-epoch catalog object."""
    from gabriel_agent.agent.backup import backup, restore
    from gabriel_agent.agent.gc import referenced_closure, roots_of
    ws, created, spec = finished_workspace(tmp_path)
    path = ws.path
    ws.close()
    monkeypatch.setattr(workspace_module, "build_registry", _registry_with_probe)
    assert Workspace.migrate(path, reason="ops.probe tool added")["status"] == "migrated"
    ws2 = Workspace.open(path)
    try:
        created2 = ws2.create_task(spec)
        assert TaskRunner(ws2, created2["task_id"]).run()["state"] == "succeeded"
        closure = referenced_closure(ws2.store, roots_of(ws2))
        top_level = set(ws2.owner.referenced_artifacts()) | ws2.memory.referenced_artifacts()
        assert len(closure) > len(top_level)  # the catalog records, task specs and nested artifacts are closure, not top-level references
        # a JSON observation (user-supplied content) that names a digest no object has: recorded, never fatal
        dangling = {"sha256": "f" * 64, "bytes": 3, "media_type": "application/json"}
        ws2.memory.ingest(source_id="user", source_object_id="json-doc", source_revision=1, content=json.dumps({"ref": dangling}).encode("utf8"),
                          media_type="application/json", received_at_unix_ms=1, extraction_digest="0" * 64,
                          scope={"principals": [ws2.config["principal_id"]], "source_kind": "document"})
        closure = referenced_closure(ws2.store, roots_of(ws2))
        assert "f" * 64 in closure
        manifest = backup(ws2, tmp_path / "backup-after-migration")
        assert set(manifest["objects"]) == closure - {"f" * 64} and manifest["object_count"] == len(closure) - 1
        assert manifest["unresolved_nested_references"] == ["f" * 64] and manifest["unresolved_nested_reference_count"] == 1
        anchor = ws2.owner.anchor()
    finally:
        ws2.close()
    catalog = workspace_module.build_registry(lambda: None).catalog()
    report = restore(tmp_path / "backup-after-migration", tmp_path / "restored", catalog=catalog)
    assert report["status"] == "passed" and report["replay"]["events"] == anchor["sequence"] and report["replay"]["runs"] == 2
    assert report["memory"]["status"] == "passed" and report["memory"]["anchor_match"]
    from gabriel_agent.artifacts import ObjectStore
    owner = owner_module.Owner.open(tmp_path / "restored" / "journal.sqlite", ObjectStore.open(tmp_path / "restored" / "objects"), catalog)
    try:
        assert [m["reason"] for m in owner.migrations()] == ["ops.probe tool added"]
        assert owner.run_record(created["run_id"])["state"] == "succeeded" and owner.run_record(created2["run_id"])["state"] == "succeeded"
    finally:
        owner.close()


def test_startup_validation_checks_the_roots_the_backup_and_the_collector_keep(tmp_path, monkeypatch):
    """ADR-25: a retained catalog of an earlier epoch is named by the journal's migration rows, not by
    its artifact table; losing it breaks replay and backup, so the deep doctor must see it missing."""
    from gabriel_agent.agent.backup import backup
    ws, created, spec = finished_workspace(tmp_path)
    path = ws.path
    ws.close()
    monkeypatch.setattr(workspace_module, "build_registry", _registry_with_probe)
    report = Workspace.migrate(path, reason="ops.probe tool added")
    assert report["status"] == "migrated"
    ws2 = Workspace.open(path)
    try:
        before = ws2.startup_validation(deep=True)
        assert before["storage"]["missing"] == [] and before["storage"]["corrupt"] == []
        old_catalog = [sha for (sha,) in ws2.owner._db.execute("SELECT record_sha256 FROM catalog_records").fetchall()
                       if sha not in set(ws2.owner.referenced_artifacts())]
        assert old_catalog, "the retained catalogs are not top-level references"
        Path(ws2.store.path_for(old_catalog[0])).unlink()
        after = ws2.startup_validation(deep=True)
        assert old_catalog[0] in after["storage"]["missing"]
        with pytest.raises(GabrielError) as excinfo:
            backup(ws2, tmp_path / "backup-missing-catalog")
        assert excinfo.value.code == Code.STORAGE_FAULT and old_catalog[0] in excinfo.value.message
    finally:
        ws2.close()


def test_retiring_worktrees_frees_disk_keeps_the_journal_and_refuses_a_later_export(tmp_path, capsys):
    """ADR-25: terminal runs' worktrees are removed and their registrations pruned; the journal,
    the retained artifacts and an export taken before stay what they are, a later export refuses
    with the retirement named, a run that is not terminal is skipped, and the CLI reports it."""
    from gabriel_agent.agent import export_task
    from gabriel_agent.workers.worktree import git
    ws, created, spec = finished_workspace(tmp_path)
    delivered = export_task(ws, created["task_id"], tmp_path / "delivery")
    pending = ws.create_task(spec)  # admitted, never run: not terminal
    worktree = Path(created["worktree"])
    assert worktree.is_dir() and created["run_id"] in git(["worktree", "list"], tmp_path / "ws" / "repo").stdout
    report = ws.retire_worktrees()
    assert report["retired"] == [created["run_id"]] and report["bytes_freed"] > 0 and report["repositories_pruned"]
    assert [s["run_id"] for s in report["skipped"]] == [pending["run_id"]] and "not terminal" in report["skipped"][0]["reason"]
    assert not worktree.exists() and created["run_id"] not in git(["worktree", "list"], tmp_path / "ws" / "repo").stdout
    assert ws.run_notes(created["run_id"])["worktree_retired"] is True
    with pytest.raises(GabrielError) as excinfo:
        export_task(ws, created["task_id"], tmp_path / "delivery2")
    assert "retired" in excinfo.value.message
    assert ws.store.get(delivered["patch_ref"]) == (tmp_path / "delivery" / "patch.diff").read_bytes()
    assert ws.owner.replay()["status"] == "passed" and ws.gc()["status"] == "dry_run"
    assert ws.retire_worktrees()["retired"] == []  # idempotent
    # the report is retained in the workspace; an unknown run is refused, not silently skipped
    reports = sorted((ws.path / "retirements").glob("retire-*.json"))
    assert len(reports) == 2 and json.loads(reports[0].read_text())["retired"] == [created["run_id"]]
    with pytest.raises(GabrielError) as excinfo:
        ws.retire_worktrees(run_ids=["run-does-not-exist"])
    assert excinfo.value.code == Code.UNKNOWN_OBJECT
    # the retired terminal run still reports its state through the runner instead of failing on its worktree
    assert TaskRunner(ws, created["task_id"]).run()["state"] == "succeeded"
    # the pending run keeps its worktree and still runs to success afterwards
    assert TaskRunner(ws, pending["task_id"]).run()["state"] == "succeeded"
    path = ws.path
    ws.close()
    assert cli.main(["retire", "--workspace", str(path)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["schema"] == "gabriel.worktree-retirement/1" and out["retired"] == [pending["run_id"]]
