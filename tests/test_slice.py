"""WP08 coding vertical slice with the scripted provider (AT11 scripted part, AT19, AT22, AT24 coverage)."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from gabriel_agent.agent import Workspace, TaskRunner, export_task
from gabriel_agent.contracts import GabrielError, Code, loads
from gabriel_agent.evaluation.fixtures import parser_bug as fixture
from gabriel_agent.interfaces.cli import main as cli_main
from gabriel_agent.workers import SupervisorCrash


def workspace(tmp_path, backend="trusted_local"):
    return Workspace.create(tmp_path / "ws", backend=backend, allow_trusted_local=(backend == "trusted_local"))


def seeded_task(tmp_path, ws, variant="correct", **spec_over):
    repo = tmp_path / "repo"
    base = fixture.build_repo(repo)
    oracle = fixture.write_oracle(tmp_path / "oracle_kvparse.py")
    spec = fixture.task_spec(repo, base, oracle, {"kind": "scripted", "script": fixture.script(variant), "max_input_tokens": 60000, "max_output_tokens": 4000})
    spec.update(spec_over)
    return ws.create_task(spec), base, repo


def test_end_to_end_repair_with_independent_oracle(tmp_path):
    ws = workspace(tmp_path)
    created, base, repo = seeded_task(tmp_path, ws)
    task_id = created["task_id"]
    assert created["compilation_report"]["admissible"]
    clause = {c["clause_id"]: c for c in created["compilation_report"]["clauses"]}
    assert clause["goal"]["status"] == "mapped" and clause["goal"]["mapped_obligation_ids"] == ["oracle"]
    runner = TaskRunner(ws, task_id)
    summary = runner.run()
    assert summary["state"] == "succeeded", summary["log"]
    outcomes = {(a["check_id"], a["node_id"]): a["outcome"] for a in summary["assessments"]}
    assert outcomes[("oracle", "verify-oracle")] == "passed" and outcomes[("unit", "verify-unit")] == "passed"
    assert outcomes[("baseline:unit", "baseline-unit")] == "passed"  # pre-existing tests passed before the change
    assert outcomes[("scope", "review")] == "passed" and outcomes[("checks-intact", "review")] == "passed"
    # the user's repository is untouched; the worktree carries the patch
    assert (repo / "src" / "kvparse.py").read_text() == fixture.BUGGY
    assert (Path(created["worktree"]) / "src" / "kvparse.py").read_text() == fixture.FIXED
    assert summary["spent"]["model_requests"] == 2 and summary["spent"]["tool_attempts"] >= 7
    # recorded replay reproduces every projection without any port call
    replay = ws.owner.replay(expected_anchor=ws.owner.anchor())
    assert replay["status"] == "passed" and replay["external_calls"] == 0
    manifest = export_task(ws, task_id, tmp_path / "delivery")
    assert manifest["run_state"] == "succeeded" and manifest["base_commit"] == base
    assert all(r["established"] for r in manifest["assessments"] if r["mandatory"])
    assert manifest["unresolved_issues"] == [] and manifest["claims_requiring_user_review"] == []
    patch = (tmp_path / "delivery" / "patch.diff").read_text()
    assert "+        if not item.strip():" in patch and "oracle_kvparse" not in patch
    # the hostile README was observed as data only
    status = ws.status(task_id)
    assert status["state"] == "succeeded" and status["unresolved_effects"] == []
    ws.close()


def test_interrupt_after_marker_and_resume(tmp_path):
    ws = workspace(tmp_path)
    created, base, repo = seeded_task(tmp_path, ws)
    task_id = created["task_id"]
    crashes = {"n": 0}

    def crash(stage):
        if stage == "after_io" and crashes["n"] == 0:
            crashes["n"] += 1
            raise SupervisorCrash("after_io")
    runner = TaskRunner(ws, task_id, hooks={"after_io": crash})
    with pytest.raises(SupervisorCrash):
        runner.run()
    interrupted = ws.status(task_id)
    assert interrupted["state"] in ("running", "planning") and len(interrupted["active_attempts"]) == 1
    frontier = ws.owner.anchor()["sequence"]
    ws.close()
    ws2 = Workspace.open(tmp_path / "ws")
    resumed = TaskRunner(ws2, task_id)
    summary = resumed.run()
    assert summary["state"] == "succeeded", summary["log"]
    assert any("recovered" in line for line in summary["log"])
    assert ws2.owner.anchor()["sequence"] > frontier
    projection = ws2.owner.projection(summary["run_id"])
    assert projection["run"]["unresolved_effect_ids"] == []
    assert any(r["outcome"] in ("confirmed_not_executed", "confirmed_failure", "confirmed_success") for r in projection["reconciliations"].values())
    assert ws2.owner.replay()["status"] == "passed"
    assert (Path(created["worktree"]) / "src" / "kvparse.py").read_text() == fixture.FIXED
    ws2.close()


def test_false_completion_and_acceptance_weakening_are_rejected(tmp_path):
    ws = workspace(tmp_path)
    created, base, repo = seeded_task(tmp_path, ws, variant="wrong_then_weaken")
    task_id = created["task_id"]
    summary = TaskRunner(ws, task_id).run()
    assert summary["state"] != "succeeded"
    outcomes = [(a["check_id"], a["node_id"], a["outcome"]) for a in summary["assessments"]]
    assert ("oracle", "verify-oracle", "failed") in outcomes  # the model's "done" did not count
    assert ("baseline:unit", "baseline-unit", "passed") in outcomes  # existing tests alone are not the oracle
    projection = ws.owner.projection(summary["run_id"])
    assert projection["run_meta"]["repair_count"] == 1
    assert summary["hold"] is not None and summary["hold"]["reason_code"] in ("plan_unavailable", "repair_exhausted", "replan_rejected")
    assert any("plan omits mandatory check" in line for line in summary["log"])
    task = projection["task"]
    assert any(c["check_id"] == "oracle" and c["mandatory"] for c in task["checks"])  # acceptance unchanged
    manifest = export_task(ws, task_id, tmp_path / "delivery")
    assert manifest["run_state"] != "succeeded" and any("oracle" in u for u in manifest["unresolved_issues"])
    assert ws.owner.replay()["status"] == "passed"
    ws.close()


def test_task_without_oracle_needs_explicit_acknowledgement(tmp_path):
    ws = workspace(tmp_path)
    repo = tmp_path / "repo"
    base = fixture.build_repo(repo)
    oracle = fixture.write_oracle(tmp_path / "oracle.py")
    spec = fixture.task_spec(repo, base, oracle, {"kind": "scripted", "script": fixture.script()}, with_oracle=False)
    with pytest.raises(GabrielError) as info:
        ws.create_task(spec)
    assert info.value.code is Code.POLICY_DENIED and "independent oracle" in info.value.message
    spec["accept_without_independent_oracle"] = True
    created = ws.create_task(spec)
    clauses = {c["clause_id"]: c for c in created["compilation_report"]["clauses"]}
    assert clauses["goal"]["status"] == "excluded_optional" and not clauses["goal"]["mandatory"]
    bad = dict(spec, checks=spec["checks"] + [{"check_id": "x", "kind": "software/run_anything", "argv": ["sh"]}])
    with pytest.raises(GabrielError):
        ws.create_task(bad, task_id="task-bad")
    ws.close()


def test_cli_smoke(tmp_path, capsys):
    ws_dir = tmp_path / "cliws"
    assert cli_main(["init", "--workspace", str(ws_dir), "--backend", "trusted_local", "--allow-trusted-local"]) == 0
    rc = cli_main(["doctor", "--workspace", str(ws_dir)])
    report = json.loads(capsys.readouterr().out.strip().split("\n{", 1)[-1].join(["{", ""]) if False else capsys.readouterr().out or "{}") if False else None
    assert rc in (0, 3)
    repo = tmp_path / "repo"
    base = fixture.build_repo(repo)
    oracle = fixture.write_oracle(tmp_path / "oracle_kvparse.py")
    spec = fixture.task_spec(repo, base, oracle, {"kind": "scripted", "script": fixture.script(), "max_input_tokens": 60000})
    spec_path = tmp_path / "task.json"
    spec_path.write_text(json.dumps(spec))
    capsys.readouterr()
    assert cli_main(["task", "create", "--workspace", str(ws_dir), "--spec", str(spec_path)]) == 0
    created = json.loads(capsys.readouterr().out)
    task_id = created["task_id"]
    assert cli_main(["task", "status", task_id, "--workspace", str(ws_dir)]) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "admitted"
    assert cli_main(["task", "pause", task_id, "--workspace", str(ws_dir)]) == 0
    capsys.readouterr()
    assert cli_main(["task", "run", task_id, "--workspace", str(ws_dir)]) == 4  # paused: no dispatch
    assert json.loads(capsys.readouterr().out)["state"] == "admitted"
    assert cli_main(["task", "resume", task_id, "--workspace", str(ws_dir)]) == 0
    capsys.readouterr()
    assert cli_main(["task", "run", task_id, "--workspace", str(ws_dir)]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["state"] == "succeeded"
    assert cli_main(["task", "export", task_id, "--workspace", str(ws_dir), "--out", str(tmp_path / "out")]) == 0
    capsys.readouterr()
    assert cli_main(["audit", "--workspace", str(ws_dir), "--anchor", str(tmp_path / "out" / "anchor.json")]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "passed"
    assert cli_main(["replay", summary["run_id"], "--workspace", str(ws_dir), "--recorded"]) == 0
    capsys.readouterr()
    assert cli_main(["task", "inspect", task_id, "--workspace", str(ws_dir), "--evidence"]) == 0
    view = json.loads(capsys.readouterr().out)
    assert view["run"]["state"] == "succeeded" and len(view["events"]) > 20
