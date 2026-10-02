"""Owner contract: AT04, AT05, AT06, AT07, AT12/AT13 (owner side), AT18 (checkpoint binding)."""
import copy
import os
import sqlite3
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from gabriel_agent.contracts import GabrielError, Code, canonical, loads
from gabriel_agent.contracts.rules import approval_digest
from gabriel_agent.state import Owner
from gabriel_agent.state.reducer import reducer_identity

from .harness import World, FAR, budget, usage


def test_lifecycle_to_success_and_replay(tmp_path):
    w = World(tmp_path)
    run = w.run_default_to_success()
    assert run["state"] == "succeeded" and run["run_revision"] == 11
    events = w.owner.events("run-01")
    kinds = [e["event"]["kind"] for e in events]
    assert kinds == ["TaskAdmitted", "RunStarted", "PlanAccepted", "IntentIssued", "DispatchAttemptMarked", "ResultAccepted",
                     "AssessmentAccepted", "IntentIssued", "DispatchAttemptMarked", "ResultAccepted", "AssessmentAccepted",
                     "AssessmentAccepted"]
    # chain: each previous_hash equals the prior stored hash
    prev = "0" * 64
    for item in events:
        assert item["event"]["previous_hash"] == prev
        prev = item["hash"]
    report = w.owner.replay(expected_anchor=w.owner.anchor())
    assert report["status"] == "passed" and report["events"] == 12 and report["external_calls"] == 0
    projection = w.owner.projection("run-01")
    assert projection["ledger"]["reserved"] == {d: 0 for d in projection["ledger"]["reserved"]}
    assert projection["ledger"]["spent"]["tool_attempts"] == 2
    assert all(n["status"] == "verified" for n in projection["nodes"].values())
    # terminal: no new execution transition
    with pytest.raises(GabrielError) as info:
        w.start()
    assert info.value.code is Code.INVALID_TRANSITION
    assert w.owner.list_tasks() == [{"task_id": "task-01", "active_run_id": "run-01", "state": "succeeded"}]


def test_admission_rejects_unverified_artifacts_and_foreign_principal(tmp_path):
    w = World(tmp_path)
    grant = w.grant_record()
    w.owner.register_grant(grant, w.cred)
    task = w.task_record()
    task["goal_ref"] = dict(task["goal_ref"], sha256="1" * 64)
    goal_ref, report_ref = w.goal_and_report(task)
    payload = {"schema": "gabriel.task-admission/1", "task": task, "run_id": "run-01", "binding_ref": w.put(w.binding_record()),
               "goal_spec_ref": goal_ref, "compilation_report_ref": report_ref}
    with pytest.raises(GabrielError) as info:
        w.submit("admit_task", payload, expected_revision=0)
    assert info.value.code is Code.ARTIFACT_MISSING
    assert w.owner.anchor()["sequence"] == 0  # unchanged frontier
    # a lossy compilation report cannot admit
    with pytest.raises(GabrielError) as info:
        w.admit(task_id="task-02", run_id="run-02", grant=w.grant_record("grant-02", "task-02"), report_ok=False)
    assert info.value.code is Code.POLICY_DENIED
    # ceiling above grant
    big = w.task_record(task_id="task-03", grant_id="grant-03")
    big["budget_ceiling"]["model_requests"] = 13
    with pytest.raises(GabrielError):
        w.admit(task_id="task-03", run_id="run-03", grant=w.grant_record("grant-03", "task-03"), task=big)


def test_exact_retry_returns_receipt_and_changed_reuse_rejects(tmp_path):
    w = World(tmp_path)
    w.admit()
    command = w.command("start_run", {"schema": "gabriel.run-start/1", "run_id": "run-01", "reason_ref": w.put("s")},
                        "task-01", "run-01", 0, command_id="cmd-start")
    first = w.owner.submit(command, credential=w.cred)
    before = w.owner.anchor()
    again = w.owner.submit(command, credential=w.cred)  # identical bytes, even after the run advanced
    assert canonical(first) == canonical(again) and w.owner.anchor() == before
    changed = dict(command, payload_ref=w.put("other reason bytes"))
    with pytest.raises(GabrielError) as info:
        w.owner.submit(changed, credential=w.cred)
    assert info.value.code is Code.ID_REUSE
    # stale: expected revision 0 again with a new id
    with pytest.raises(GabrielError) as info:
        w.submit("start_run", {"schema": "gabriel.run-start/1", "run_id": "run-01", "reason_ref": w.put("s")}, expected_revision=0)
    assert info.value.code is Code.STALE_REVISION and info.value.revision == 1
    assert w.owner.anchor() == before


def test_race_two_commands_at_same_revision_admits_exactly_one(tmp_path):
    w = World(tmp_path)
    w.admit()
    commands = [w.command("start_run", {"schema": "gabriel.run-start/1", "run_id": "run-01", "reason_ref": w.put("r%d" % i)},
                          "task-01", "run-01", 0) for i in range(2)]
    outcomes = {}
    barrier = threading.Barrier(2)

    def worker(index):
        owner = Owner.open(w.tmp / "journal.sqlite", w.store, w.catalog, clock=w.clock)
        barrier.wait()
        try:
            outcomes[index] = owner.submit(commands[index], credential=w.cred)
        except GabrielError as exc:
            outcomes[index] = exc.code
        finally:
            owner.close()
    threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    kinds = sorted(type(v).__name__ for v in outcomes.values())
    assert kinds == ["Code", "dict"]
    assert [v for v in outcomes.values() if not isinstance(v, dict)] == [Code.STALE_REVISION]
    assert w.owner.run_record("run-01")["run_revision"] == 1


class Crash(Exception):
    pass


def test_crash_before_and_after_commit_with_replay(tmp_path):
    w = World(tmp_path)
    w.admit()
    payload = {"schema": "gabriel.run-start/1", "run_id": "run-01", "reason_ref": w.put("s")}
    command = w.command("start_run", payload, "task-01", "run-01", 0, command_id="cmd-crash-1")
    stages = []

    def before(stage):
        stages.append(stage)
        if stage == "before_commit":
            raise Crash()
    w.owner._hook = before
    with pytest.raises(Crash):
        w.owner.submit(command, credential=w.cred)
    w.owner._hook = None
    assert w.owner.anchor()["sequence"] == 1 and w.owner.run_record("run-01")["state"] == "admitted"
    receipt = w.owner.submit(command, credential=w.cred)  # retry with the same command id admits once
    assert receipt["sequence"] == 2

    def after(stage):
        if stage == "after_commit":
            raise Crash()
    w.owner._hook = after
    plan = w.default_plan()
    command2 = w.command("accept_plan", plan, "task-01", "run-01", 1, command_id="cmd-crash-2")
    with pytest.raises(Crash):
        w.owner.submit(command2, credential=w.cred)
    w.owner._hook = None
    stored = w.owner.receipt("cmd-crash-2")
    assert canonical(w.owner.submit(command2, credential=w.cred)) == canonical(stored)
    assert w.owner.anchor()["sequence"] == 3
    report = w.reopen().replay()
    assert report["status"] == "passed" and report["events"] == 3 and report["external_calls"] == 0


def test_process_kill_before_commit_leaves_journal_consistent(tmp_path):
    w = World(tmp_path)
    w.admit()
    w.owner.close()
    script = r"""
import os, sys
sys.path.insert(0, %r); sys.path.insert(0, %r)
from tests.harness import World
from gabriel_agent.state import Owner
from gabriel_agent.policy.principals import Credential
from gabriel_agent.artifacts import ObjectStore
from gabriel_agent.contracts import validate
from tests.harness import fixture_catalog, WS, POLICY
store = ObjectStore.open(%r)
owner = Owner.open(%r, store, fixture_catalog(), clock=lambda: 1000000)
cred = Credential("principal-01", %r)
payload_ref = store.put(b'{"reason_ref":%s,"run_id":"run-01","schema":"gabriel.run-start/1"}', "application/json")
command = {"schema": "gabriel.command/1", "command_id": "cmd-kill", "workspace_id": WS, "task_id": "task-01", "run_id": "run-01",
           "expected_revision": 0, "op": "start_run", "payload_ref": payload_ref, "policy_digest": POLICY}
owner._hook = lambda stage: os._exit(77) if stage == %r else None
owner.submit(command, credential=cred)
""" % (str(w.tmp.parents[1]), str(Path(__file__).resolve().parents[1] / "src"), str(w.tmp / "store"),
       str(w.tmp / "journal.sqlite"), w.secret, canonical(w.put("kill reason")).decode(), "before_commit")
    root = Path(__file__).resolve().parents[1]
    proc = subprocess.run([sys.executable, "-c", script.replace(str(w.tmp.parents[1]), str(root), 1)], capture_output=True, text=True, cwd=root)
    assert proc.returncode == 77, proc.stderr
    owner = Owner.open(w.tmp / "journal.sqlite", w.store, w.catalog, clock=w.clock)
    assert owner.anchor()["sequence"] == 1 and owner.run_record("run-01")["state"] == "admitted"
    assert owner.replay()["status"] == "passed"
    with pytest.raises(GabrielError):
        owner.receipt("cmd-kill")
    owner.close()


def test_pause_blocks_dispatch_and_resume_restores(tmp_path):
    w = World(tmp_path)
    w.admit(); w.start(); w.accept_plan()
    intent, _ = w.issue("observe")
    w.submit("request_pause", {"schema": "gabriel.pause-request/1", "reason_ref": w.put("pause")})
    assert w.owner.run_record("run-01")["pause_requested"] is True
    with pytest.raises(GabrielError) as info:
        w.mark(intent)  # leased but unmarked job must recheck the pause flag
    assert info.value.code is Code.POLICY_DENIED
    with pytest.raises(GabrielError):
        w.issue("observe")
    w.submit("resume_run", {"schema": "gabriel.resume/1", "reason_ref": w.put("resume")})
    w.mark(intent)
    w.accept_result(intent)
    assert w.owner.projection("run-01")["nodes"]["observe"]["status"] == "completed"


def test_grant_revocation_and_approval_mutation_at_dispatch(tmp_path):
    w = World(tmp_path)
    w.admit(); w.start()
    plan = w.plan_record([w.node("observe", "fixture.read", outputs=("snapshot",)),
                          w.node("publish", "fixture.external", depends_on=["observe"], check_ids=["oracle"], retry_class="never")])
    w.accept_plan(plan)
    i1, _ = w.issue("observe"); w.complete_node(i1)
    # approval binds the exact intent digest
    intent = w.intent_record("publish", target="worktree-01")
    with pytest.raises(GabrielError) as info:
        w.submit("issue_intent", intent)
    assert info.value.code is Code.POLICY_DENIED
    w.owner.register_approval(intent, w.cred)
    approved = dict(intent, approval_digest=approval_digest(intent))
    edited = dict(approved, args_ref=w.put({"argv": ["rm", "-rf"]}))
    with pytest.raises(GabrielError) as info:
        w.submit("issue_intent", edited)
    assert info.value.code is Code.POLICY_DENIED
    w.submit("issue_intent", approved)
    # revoke before dispatch marker: dispatch rejects, intent stays authorized but unmarked
    w.owner.revoke_grant("grant-01", w.cred)
    with pytest.raises(GabrielError) as info:
        w.mark(approved)
    assert info.value.code is Code.POLICY_DENIED
    attempt = w.owner.projection("run-01")["attempts"][approved["attempt_id"]]
    assert attempt["status"] == "issued" and attempt["effect_state"] == "authorized"
    assert w.owner.expired_attempts(w.time[0]) == []


def test_in_flight_effect_survives_revocation_as_reconciliation_obligation(tmp_path):
    w = World(tmp_path)
    w.admit(); w.start(); w.accept_plan()
    i1, _ = w.issue("observe"); w.complete_node(i1)
    i2, _ = w.issue("change"); w.mark(i2)
    w.owner.revoke_grant("grant-01", w.cred)
    # the marked attempt may have executed: an outcome_unknown result records the obligation
    result, receipt = w.accept_result(i2, status="timed_out", effect="outcome_unknown", outputs=[])
    run = w.owner.run_record("run-01")
    assert run["unresolved_effect_ids"] == [i2["intent_id"]]
    assert "reconciliation obligation" in " ".join(receipt["notes"])
    reconciliation = {"schema": "gabriel.effect-reconciliation/1", "intent_id": i2["intent_id"], "attempt_id": i2["attempt_id"],
                      "method": "read_back", "outcome": "confirmed_not_executed", "evidence_ref": w.put("read back: unchanged")}
    w.submit("reconcile_effect", reconciliation)
    assert w.owner.run_record("run-01")["unresolved_effect_ids"] == []
    assert w.owner.projection("run-01")["nodes"]["change"]["status"] == "pending"


def test_budget_race_unknown_usage_and_no_reset_on_retry(tmp_path):
    w = World(tmp_path)
    w.admit(); w.start()
    reservation = usage(model_tokens=12000, model_requests=1)
    plan = w.plan_record([w.node("m1", "fixture.model", outputs=("model_output",), reservation=reservation, retry_class="target_idempotent_retry"),
                          w.node("m2", "fixture.model", outputs=("model_output",), reservation=reservation, retry_class="target_idempotent_retry")])
    w.accept_plan(plan)
    i1, _ = w.issue("m1", target="provider-01")
    with pytest.raises(GabrielError) as info:  # 12000 + 12000 > 20000
        w.issue("m2", target="provider-01")
    assert info.value.code is Code.BUDGET_EXHAUSTED and "model_tokens" in info.value.details["dimensions"]
    w.mark(i1)
    # paid-provider timeout with unknown usage keeps the conservative charge
    w.accept_result(i1, status="timed_out", effect="not_applicable", outputs=[],
                    usage_over={"model_tokens": 0, "model_requests": 1, "accounting_status": "conservative_pending_reconciliation"})
    ledger = w.owner.projection("run-01")["ledger"]
    assert ledger["spent"]["model_tokens"] == 12000 and ledger["reserved"]["model_tokens"] == 0
    assert ledger["pending_reconciliation"] == [i1["attempt_id"]]
    assert w.owner.projection("run-01")["nodes"]["m1"]["status"] == "pending"  # retry allowed by class
    with pytest.raises(GabrielError) as info:  # the retry cannot restore the budget
        w.issue("m1", target="provider-01")
    assert info.value.code is Code.BUDGET_EXHAUSTED
    # confirmed overrun is retained and suspends admission
    small = w.plan_record([w.node("r", "fixture.read", outputs=("snapshot",), reservation=usage(cpu_ms=10))], parent=plan["plan_id"])
    w.accept_plan(small)
    ir, _ = w.issue("r"); w.mark(ir)
    w.accept_result(ir, usage_over={"cpu_ms": 500})
    projection = w.owner.projection("run-01")
    assert projection["ledger"]["overruns"][0]["overrun"] == {"cpu_ms": 490}
    assert projection["ledger"]["spent"]["cpu_ms"] == 1000 + 500 and projection["run_meta"]["limit_violation"]


def test_cancel_retains_unknown_effects_and_late_result_is_audit_only(tmp_path):
    w = World(tmp_path)
    w.admit(); w.start(); w.accept_plan()
    i1, _ = w.issue("observe"); w.complete_node(i1)
    i2, _ = w.issue("change"); w.mark(i2)
    receipt = w.submit("cancel_task", {"schema": "gabriel.cancellation/1", "reason_ref": w.put("user cancelled")})
    run = w.owner.run_record("run-01")
    assert run["state"] == "cancelled" and run["unresolved_effect_ids"] == [i2["intent_id"]]
    assert "awaiting reconciliation" in " ".join(receipt["notes"])
    # a late result from the cancelled attempt cannot advance the plan or create a new attempt
    result, late = w.accept_result(i2)
    assert "audit fact" in " ".join(late["notes"])
    projection = w.owner.projection("run-01")
    assert projection["run"]["state"] == "cancelled" and projection["late_results"][0]["attempt_id"] == i2["attempt_id"]
    assert projection["nodes"]["change"]["status"] == "active"
    # reconciliation still appends after cancellation
    w.submit("reconcile_effect", {"schema": "gabriel.effect-reconciliation/1", "intent_id": i2["intent_id"],
                                  "attempt_id": i2["attempt_id"], "method": "read_back", "outcome": "confirmed_success",
                                  "evidence_ref": w.put("read back")})
    assert w.owner.run_record("run-01")["unresolved_effect_ids"] == []
    with pytest.raises(GabrielError):
        w.submit("resume_run", {"schema": "gabriel.resume/1", "reason_ref": w.put("x")})


def test_unmarked_attempt_result_rejected_and_fencing_enforced(tmp_path):
    w = World(tmp_path)
    w.admit(); w.start(); w.accept_plan()
    intent, _ = w.issue("observe")
    with pytest.raises(GabrielError) as info:
        w.accept_result(intent)
    assert info.value.code is Code.INVALID_TRANSITION
    with pytest.raises(GabrielError):
        w.issue("observe")  # node is active; and fencing token would be stale anyway
    w.mark(intent)
    forged = w.result_record(intent)
    forged["fencing_token"] = 99
    with pytest.raises(GabrielError):
        w.submit("accept_result", forged)
    # expired lease is visible for recovery but never auto-repeated
    w.time[0] += 700000
    assert [a["attempt_id"] for a in w.owner.expired_attempts()] == [intent["attempt_id"]]


def test_assessment_eligibility_and_verifier_registration(tmp_path):
    w = World(tmp_path)
    w.admit(); w.start(); w.accept_plan()
    i1, _ = w.issue("observe"); w.mark(i1); w.accept_result(i1)
    projection = w.owner.projection("run-01")
    snapshot = projection["run_meta"]["observed_snapshot_ref"]
    result_ref = projection["nodes"]["observe"]["result_ref"]
    with pytest.raises(GabrielError) as info:  # not bound to the current snapshot
        w.assess("oracle", [result_ref])
    assert info.value.code is Code.STALE_EVIDENCE
    with pytest.raises(GabrielError) as info:  # unregistered verifier digest
        w.assess("oracle", [snapshot, result_ref], verifier_digest="9" * 64)
    assert info.value.code is Code.POLICY_DENIED
    with pytest.raises(GabrielError) as info:  # wrong predicate kind for this check
        w.assess("oracle", [snapshot, result_ref], verifier="owner.output_valid")
    assert info.value.code is Code.POLICY_DENIED
    with pytest.raises(GabrielError):
        w.assess("unknown-check", [snapshot, result_ref])
    # a passing oracle on the observe node alone cannot complete the run: the change node is unverified
    w.assess("output-valid", [snapshot, result_ref], verifier="owner.output_valid")
    receipt = w.assess("oracle", [snapshot, result_ref])
    assert receipt["run_state"] == "running" and "unverified" in " ".join(receipt["notes"])


def test_failed_mandatory_check_opens_bounded_repair_cycles(tmp_path):
    w = World(tmp_path)
    w.admit(); w.start(); w.accept_plan()
    i1, _ = w.issue("observe"); w.complete_node(i1)
    i2, _ = w.issue("change"); w.mark(i2); w.accept_result(i2)
    projection = w.owner.projection("run-01")
    refs = [projection["run_meta"]["observed_snapshot_ref"], projection["nodes"]["change"]["result_ref"]]
    receipt = w.assess("oracle", refs, outcome="failed")
    assert receipt["run_state"] == "planning" and "repair cycle 1 of 2" in " ".join(receipt["notes"])
    plan2 = w.plan_record([w.node("change", "fixture.write", check_ids=["oracle", "output-valid"], retry_class="reconcile_before_retry")],
                          parent=projection["plan"]["plan_id"])
    w.accept_plan(plan2)
    i3, _ = w.issue("change"); w.mark(i3); w.accept_result(i3)
    projection = w.owner.projection("run-01")
    refs = [projection["run_meta"]["observed_snapshot_ref"], projection["nodes"]["change"]["result_ref"]]
    w.assess("oracle", refs, outcome="failed")
    plan3 = w.plan_record([w.node("change", "fixture.write", check_ids=["oracle", "output-valid"], retry_class="reconcile_before_retry")],
                          parent=plan2["plan_id"])
    w.accept_plan(plan3)
    i4, _ = w.issue("change"); w.mark(i4); w.accept_result(i4)
    projection = w.owner.projection("run-01")
    refs = [projection["run_meta"]["observed_snapshot_ref"], projection["nodes"]["change"]["result_ref"]]
    receipt = w.assess("oracle", refs, outcome="failed")
    assert receipt["run_state"] == "failed"
    recorded = w.owner.projection("run-01")["assessments"].values()
    assert sorted(a["outcome"] for a in recorded) == ["failed", "failed", "failed", "passed"]  # every failure remains visible


def test_amendment_cannot_weaken_without_principal_confirmation(tmp_path):
    w = World(tmp_path)
    w.admit(); w.start()
    task = w.owner.projection("run-01")["task"]
    weaker = copy.deepcopy(task)
    weaker["task_spec_revision"] = 1
    weaker["checks"][0]["mandatory"] = False
    goal_ref, report_ref = w.goal_and_report(weaker)
    payload = {"schema": "gabriel.task-amendment/1", "task": weaker, "reason_ref": w.put("model wants it"),
               "amendment_kind": "clarify", "goal_spec_ref": goal_ref, "compilation_report_ref": report_ref,
               "principal_confirmation": False}
    with pytest.raises(GabrielError) as info:
        w.submit("amend_task", payload)
    assert info.value.code is Code.POLICY_DENIED
    payload.update(amendment_kind="weaken_acceptance", principal_confirmation=True)
    receipt = w.submit("amend_task", payload)
    assert "weakened by principal" in " ".join(receipt["notes"])
    assert w.owner.projection("run-01")["task"]["task_spec_revision"] == 1


def test_hold_records_and_resume(tmp_path):
    w = World(tmp_path)
    w.admit(); w.start()
    receipt = w.submit("record_hold", {"schema": "gabriel.hold/1", "reason_code": "missing_credential", "target_state": "blocked",
                                       "reason_ref": w.put("no provider credential"), "missing_prerequisite": "provider-credential",
                                       "wakeup_condition": "credential-configured"})
    assert receipt["run_state"] == "blocked"
    with pytest.raises(GabrielError):
        w.accept_plan()
    w.submit("resume_run", {"schema": "gabriel.resume/1", "reason_ref": w.put("configured")})
    assert w.owner.run_record("run-01")["state"] == "planning"
    w.accept_plan()
    receipt = w.submit("record_hold", {"schema": "gabriel.hold/1", "reason_code": "repair_exhausted", "target_state": "failed",
                                       "reason_ref": w.put("done"), "missing_prerequisite": None, "wakeup_condition": None})
    assert receipt["run_state"] == "failed"


def test_plan_bounds_at_owner(tmp_path):
    w = World(tmp_path)
    w.admit(); w.start()
    unknown = w.plan_record([dict(w.node("x", "fixture.read"), capability_id="tool.unknown")])
    with pytest.raises(GabrielError) as info:
        w.accept_plan(unknown)
    assert info.value.code is Code.POLICY_DENIED
    cyc = w.plan_record([w.node("a", "fixture.read", depends_on=["b"]), w.node("b", "fixture.read", depends_on=["a"])])
    with pytest.raises(GabrielError) as info:
        w.accept_plan(cyc)
    assert info.value.code is Code.INVALID_SCHEMA
    w.accept_plan()
    with pytest.raises(GabrielError):  # parent must be the current version
        w.accept_plan(w.default_plan(parent=None))
    # plan version limit (binding max_plan_versions=4)
    current = w.owner.projection("run-01")["plan"]["plan_id"]
    for _ in range(3):
        plan = w.default_plan(parent=current)
        w.accept_plan(plan)
        current = plan["plan_id"]
    with pytest.raises(GabrielError) as info:
        w.accept_plan(w.default_plan(parent=current))
    assert info.value.code is Code.BUDGET_EXHAUSTED


def test_anchor_detects_truncated_suffix_and_checkpoint_binding(tmp_path):
    w = World(tmp_path)
    w.admit(); w.start()
    backup = w.owner.backup(w.tmp / "backup.sqlite")
    w.accept_plan()
    later = w.owner.anchor()
    restored = Owner.open(w.tmp / "backup.sqlite", w.store, w.catalog, clock=w.clock)
    assert restored.replay()["status"] == "passed"  # internally consistent prefix
    with pytest.raises(GabrielError) as info:
        restored.verify_anchor(later)
    assert info.value.code is Code.STORAGE_FAULT
    restored.verify_anchor(backup["anchor"])
    restored.close()
    manifest = w.owner.checkpoint("cp-1", w.put("dependency manifest"))
    projections = {"run-01": w.owner.projection("run-01")}
    assert w.owner.verify_checkpoint(manifest, projections)["status"] == "passed"
    corrupted = copy.deepcopy(projections)
    corrupted["run-01"]["run"]["state"] = "succeeded"  # same frontier, changed projection
    with pytest.raises(GabrielError) as info:
        w.owner.verify_checkpoint(manifest, corrupted)
    assert info.value.code is Code.STORAGE_FAULT
    forged = dict(manifest, projection_digest=w.owner.all_projections_digest(), reducer_identity="0" * 64)
    with pytest.raises(GabrielError):
        w.owner.verify_checkpoint(forged, projections)


def test_replay_rejects_tampered_event(tmp_path):
    w = World(tmp_path)
    w.admit(); w.start()
    w.owner.close()
    db = sqlite3.connect(str(w.tmp / "journal.sqlite"))
    db.execute("UPDATE events SET event_text=replace(event_text, 'RunStarted', 'TaskCancelled') WHERE sequence=2")
    db.commit(); db.close()
    owner = Owner.open(w.tmp / "journal.sqlite", w.store, w.catalog, clock=w.clock)
    with pytest.raises(GabrielError) as info:
        owner.replay()
    assert info.value.code is Code.STORAGE_FAULT
    owner.close()


def test_open_refuses_changed_catalog(tmp_path):
    w = World(tmp_path)
    w.admit()
    w.owner.close()
    changed = copy.deepcopy(w.catalog)
    changed["tools"]["fixture.read"]["implementation_fingerprint"] = "1" * 64
    with pytest.raises(GabrielError) as info:
        Owner.open(w.tmp / "journal.sqlite", w.store, changed, clock=w.clock)
    assert info.value.code is Code.UNSUPPORTED
