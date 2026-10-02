"""Shared fixture world for owner, policy, scheduler and runner tests.

Everything here is synthetic: fixture tools, fixture verifiers and fixture
artifacts exercise the owner contract; they are not domain evidence.
"""
from __future__ import annotations

import hashlib
import itertools
from pathlib import Path

from gabriel_agent.artifacts import ObjectStore
from gabriel_agent.contracts import canonical, validate
from gabriel_agent.contracts.schemas import schema_digest
from gabriel_agent.policy.principals import Credential, new_secret, secret_digest
from gabriel_agent.state import Owner

WS, PRINCIPAL, POLICY = "ws-01", "principal-01", hashlib.sha256(b"fixture-policy").hexdigest()
FAR = 2_000_000_000_000


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def budget(**over):
    base = {"model_tokens_total": 20000, "model_requests": 12, "tool_attempts": 64, "cpu_ms": 1800000,
            "elapsed_ms": 1800000, "artifact_bytes": 16777216, "scratch_bytes": 1073741824,
            "currency_micro_units": 0, "currency": "EUR", "concurrent_reads": 4,
            "concurrent_writes_per_resource": "one"}
    base.update(over)
    return base


def usage(**over):
    base = {"model_tokens": 0, "model_requests": 0, "tool_attempts": 1, "cpu_ms": 1000, "elapsed_ms": 10,
            "artifact_bytes": 1024, "currency_micro_units": 0, "currency": "EUR", "accounting_status": "confirmed"}
    base.update(over)
    return base


def tool(tool_id, effect_class, reconciliation="read_back", requires_approval=False, observation_slot=None,
         concurrency_key="read"):
    return {"schema": "gabriel.tool-descriptor/1", "tool_id": tool_id, "version": "v1", "effect_class": effect_class,
            "input_schema_digest": sha(tool_id + "-in"), "output_schema_digest": sha(tool_id + "-out"),
            "timeout_ms": 60000, "max_output_bytes": 1 << 20, "concurrency_key": concurrency_key,
            "reconciliation": reconciliation, "requires_approval": requires_approval,
            "implementation_fingerprint": sha(tool_id + "-impl"), "description": "fixture tool " + tool_id,
            "resource_forms": ["worktree"], "observation_slot": observation_slot}


def fixture_catalog():
    tools = {
        "fixture.read": tool("fixture.read", "read", observation_slot="snapshot"),
        "fixture.write": tool("fixture.write", "local_reversible_write", concurrency_key="writer"),
        "fixture.external": tool("fixture.external", "external_non_idempotent_effect", "target_status_by_key", True),
        "fixture.model": tool("fixture.model", "external_idempotent_effect", "same_key_retry", concurrency_key="model"),
    }
    for t in tools.values():
        validate(t, "tool-descriptor")
    verifiers = {
        "fixture.oracle": {"verifier_id": "fixture.oracle", "version": "v1", "predicate_kind": "fixture/passed",
                           "implementation_fingerprint": sha("fixture.oracle"), "profile_digest": sha("profile"),
                           "independent": True, "description": "fixture oracle"},
        "owner.output_valid": {"verifier_id": "owner.output_valid", "version": "v1", "predicate_kind": "owner/output_valid",
                               "implementation_fingerprint": sha("owner.output_valid"), "profile_digest": sha("profile"),
                               "independent": False, "description": "owner structural output check"},
    }
    return {"tools": tools, "verifiers": verifiers}


class World:
    def __init__(self, tmp_path: Path, clock=None, catalog=None):
        self.tmp = Path(tmp_path)
        self.store = ObjectStore.create(self.tmp / "store")
        self.secret = new_secret()
        self.cred = Credential(PRINCIPAL, self.secret)
        self.catalog = catalog or fixture_catalog()
        self.time = [1_000_000]
        self.clock = clock or (lambda: self.time[0])
        self.owner = Owner.create(self.tmp / "journal.sqlite", self.store, WS, self.catalog,
                                  principals={PRINCIPAL: secret_digest(self.secret)}, clock=self.clock)
        self._ids = itertools.count(1)
        self.snapshot_ref = None

    def reopen(self):
        self.owner.close()
        self.owner = Owner.open(self.tmp / "journal.sqlite", self.store, self.catalog, clock=self.clock)
        return self.owner

    def tick(self, ms=1000):
        self.time[0] += ms

    def fresh(self, prefix):
        return "%s-%02d" % (prefix, next(self._ids))

    def put(self, value, media="application/json"):
        if isinstance(value, (dict, list)):
            return self.store.put(canonical(value), media)
        if isinstance(value, str):
            return self.store.put(value.encode("utf8"), "text/plain; charset=utf-8")
        return self.store.put(value, media)

    # ----------------------------------------------------------- records
    def grant_record(self, grant_id="grant-01", task_id="task-01", tools=None, resources=None, effects=None, **over):
        grant = {"schema": "gabriel.grant/1", "grant_id": grant_id, "principal_id": PRINCIPAL, "workspace_id": WS,
                 "task_id": task_id, "tool_ids": tools or sorted(self.catalog["tools"]),
                 "resource_ids": resources or ["worktree-01", "provider-01"],
                 "effect_classes": effects or ["read", "local_reversible_write", "external_idempotent_effect",
                                               "external_non_idempotent_effect"],
                 "budget_ceiling": budget(), "expires_at_unix_ms": FAR, "policy_digest": POLICY, "parent_grant_id": None}
        grant.update(over)
        return validate(grant, "grant")

    def checks(self):
        spec = self.put("fixture oracle spec")
        return [{"check_id": "oracle", "version": "v1", "mandatory": True, "spec_ref": spec},
                {"check_id": "output-valid", "version": "v1", "mandatory": False, "spec_ref": spec}]

    def binding_record(self, max_repairs=2, max_plan_versions=4):
        spec = self.put("fixture oracle spec")
        binding = {"schema": "gabriel.task-binding/1", "domain_namespace": "fixture", "pack_id": "fixture-pack",
                   "pack_version": "1.0.0", "provider_profile_ref": self.put({"fixture": "provider"}),
                   "containment_backend": "trusted_local", "repository_path": "/fixture", "base_commit": "0" * 40,
                   "allowed_paths": ["src/"], "max_plan_versions": max_plan_versions, "max_repairs": max_repairs,
                   "owner_time_basis": "logical", "planner_mode": "model",
                   "check_specs": [{"check_id": "oracle", "version": "v1", "mandatory": True, "predicate_kind": "fixture/passed",
                                    "argv": ["true"], "timeout_ms": 1000, "independent": True, "role": "acceptance_only",
                                    "oracle_files": [], "allowed_paths": []},
                                   {"check_id": "output-valid", "version": "v1", "mandatory": False, "predicate_kind": "owner/output_valid",
                                    "argv": [], "timeout_ms": 0, "independent": False, "role": "structural",
                                    "oracle_files": [], "allowed_paths": []}]}
        return validate(binding, "task-binding")

    def task_record(self, task_id="task-01", grant_id="grant-01", revision=0, checks=None, budget_ceiling=None):
        task = {"schema": "gabriel.task/1", "task_id": task_id, "workspace_id": WS, "principal_id": PRINCIPAL,
                "goal_ref": self.put("Fix the fixture. Prüfung."), "acceptance_ref": self.put("fixture acceptance"),
                "grant_id": grant_id, "budget_ceiling": budget_ceiling or budget(),
                "base_inputs": [self.put("fixture base input")], "checks": checks or self.checks(),
                "policy_digest": POLICY, "task_spec_revision": revision}
        return validate(task, "task")

    def goal_and_report(self, task, admissible=True, unresolved=0):
        goal = {"schema": "gabriel.goal-spec/1", "goal_id": task["task_id"] + "-goal", "task_id": task["task_id"],
                "task_spec_revision": task["task_spec_revision"], "domain_namespace": "fixture", "pack_id": "fixture-pack",
                "pack_version": "1.0.0", "source_goal_ref": task["goal_ref"], "source_acceptance_ref": task["acceptance_ref"],
                "obligations": [{"obligation_id": "oracle", "predicate_kind": "fixture/passed", "subject_ref": None,
                                 "verifier_id": "fixture.oracle", "verifier_version": "v1", "verifier_profile_digest": sha("profile"),
                                 "mandatory": True, "depends_on": [], "execution_requirement": "observed",
                                 "spec_ref": task["checks"][0]["spec_ref"], "check_id": "oracle"}],
                "transform_profile_id": "fixture-compile-v1"}
        validate(goal, "goal-spec")
        goal_ref = self.put(goal)
        report = {"schema": "gabriel.compilation-report/1", "report_id": task["task_id"] + "-report",
                  "task_id": task["task_id"], "task_spec_revision": task["task_spec_revision"], "goal_spec_ref": goal_ref,
                  "clauses": [{"clause_id": "c1", "source_ref": task["goal_ref"], "byte_start": 0, "byte_end": 10,
                               "mapped_obligation_ids": ["oracle"], "status": "mapped", "mandatory": True, "reason": "fixture"}],
                  "raw_response_ref": None, "transform_profile_id": "fixture-compile-v1",
                  "unresolved_mandatory_count": unresolved, "admissible": admissible}
        validate(report, "compilation-report")
        return goal_ref, self.put(report)

    def command(self, op, payload, task_id, run_id, expected_revision, command_id=None):
        payload_ref = self.put(payload)
        command = {"schema": "gabriel.command/1", "command_id": command_id or self.fresh("cmd"), "workspace_id": WS,
                   "task_id": task_id, "run_id": run_id, "expected_revision": expected_revision, "op": op,
                   "payload_ref": payload_ref, "policy_digest": POLICY}
        return validate(command, "command")

    def submit(self, op, payload, task_id="task-01", run_id="run-01", expected_revision=None, command_id=None):
        if expected_revision is None:
            expected_revision = self.owner.run_record(run_id)["run_revision"]
        command = self.command(op, payload, task_id, run_id, expected_revision, command_id)
        return self.owner.submit(command, credential=self.cred)

    # ----------------------------------------------------------- flows
    def admit(self, task_id="task-01", run_id="run-01", grant=None, task=None, binding=None, report_ok=True):
        grant = grant or self.grant_record(task_id=task_id)
        self.owner.register_grant(grant, self.cred)
        task = task or self.task_record(task_id=task_id, grant_id=grant["grant_id"])
        goal_ref, report_ref = self.goal_and_report(task, admissible=report_ok, unresolved=0 if report_ok else 1)
        payload = {"schema": "gabriel.task-admission/1", "task": task, "run_id": run_id,
                   "binding_ref": self.put(binding or self.binding_record()), "goal_spec_ref": goal_ref,
                   "compilation_report_ref": report_ref}
        validate(payload, "task-admission")
        return self.submit("admit_task", payload, task_id, run_id, 0)

    def start(self, run_id="run-01", task_id="task-01"):
        return self.submit("start_run", {"schema": "gabriel.run-start/1", "run_id": run_id,
                                         "reason_ref": self.put("start")}, task_id, run_id)

    def node(self, node_id, capability, depends_on=(), outputs=("output",), check_ids=("output-valid",),
             priority=0, retry_class="read_retry", reservation=None, max_repair_attempts=2):
        cap = self.catalog["tools"][capability]
        return {"node_id": node_id, "depends_on": list(depends_on), "capability_id": capability,
                "output_schema_digest": cap["output_schema_digest"], "check_ids": list(check_ids),
                "reservation": reservation or usage(), "retry_class": retry_class, "effect_class": cap["effect_class"],
                "priority": priority, "max_repair_attempts": max_repair_attempts, "inputs": [],
                "outputs": [{"output_slot": slot, "schema_digest": cap["output_schema_digest"]} for slot in outputs]}

    def plan_record(self, nodes, plan_id=None, parent=None, run_id="run-01", task_id="task-01"):
        plan = {"schema": "gabriel.plan/1", "plan_id": plan_id or self.fresh("plan"), "task_id": task_id, "run_id": run_id,
                "parent_plan_id": parent, "reason_ref": self.put("plan reason"), "nodes": nodes, "max_depth": 12}
        return validate(plan, "plan")

    def default_plan(self, parent=None, plan_id=None):
        return self.plan_record([self.node("observe", "fixture.read", outputs=("snapshot",)),
                                 self.node("change", "fixture.write", depends_on=["observe"], check_ids=["oracle", "output-valid"],
                                           retry_class="reconcile_before_retry")], plan_id=plan_id, parent=parent)

    def accept_plan(self, plan=None, **kw):
        plan = plan or self.default_plan(**kw)
        return self.submit("accept_plan", plan, plan["task_id"], plan["run_id"])

    def intent_record(self, node_id, run_id="run-01", task_id="task-01", target="worktree-01", approval=None,
                      expires=None, fencing=None, grant_id="grant-01", **over):
        projection = self.owner.projection(run_id)
        node = next(n for n in projection["plan"]["nodes"] if n["node_id"] == node_id)
        cap = self.catalog["tools"][node["capability_id"]]
        n = next(self._ids)
        intent = {"schema": "gabriel.intent/1", "intent_id": "intent-%02d" % n, "task_id": task_id, "run_id": run_id,
                  "step_id": node_id, "attempt_id": "attempt-%02d" % n, "capability_id": node["capability_id"],
                  "args_ref": self.put({"argv": ["true"]}), "target_id": target, "grant_id": grant_id,
                  "reservation_id": "reservation-%02d" % n, "policy_digest": POLICY, "effect_class": node["effect_class"],
                  "idempotency_key": "%s-attempt-%02d" % (target, n), "approval_digest": approval,
                  "precondition_ref": self.put("precondition"), "reconciliation": cap["reconciliation"],
                  "expires_at_unix_ms": expires or (self.time[0] + 600000),
                  "lease_id": "lease-%02d" % n,
                  "fencing_token": fencing if fencing is not None else projection["run_meta"]["next_fencing_token"]}
        intent.update(over)
        return validate(intent, "intent")

    def issue(self, node_id, **kw):
        intent = self.intent_record(node_id, **kw)
        receipt = self.submit("issue_intent", intent, intent["task_id"], intent["run_id"])
        return intent, receipt

    def marker_record(self, intent):
        marker = {"schema": "gabriel.dispatch-marker/1", "run_id": intent["run_id"], "intent_id": intent["intent_id"],
                  "attempt_id": intent["attempt_id"], "lease_id": intent["lease_id"], "fencing_token": intent["fencing_token"],
                  "owner_time_unix_ms": self.owner.owner_time(), "authorization_input_ref": self.put("authorization inputs")}
        return validate(marker, "dispatch-marker")

    def mark(self, intent):
        return self.submit("mark_dispatch", self.marker_record(intent), intent["task_id"], intent["run_id"])

    def result_record(self, intent, status="completed", effect="acknowledged_success", outputs=None, usage_over=None,
                      exit_code=0):
        projection = self.owner.projection(intent["run_id"])
        node = next(n for n in projection["plan"]["nodes"] if n["node_id"] == intent["step_id"])
        if outputs is None and status == "completed":
            outputs = [{"output_slot": o["output_slot"], "schema_digest": o["schema_digest"],
                        "artifact_ref": self.put({"fixture_output": o["output_slot"], "attempt": intent["attempt_id"]})}
                       for o in node["outputs"]]
        result = {"schema": "gabriel.result/1", "result_id": "result-" + intent["attempt_id"], "intent_id": intent["intent_id"],
                  "attempt_id": intent["attempt_id"], "lease_id": intent["lease_id"], "fencing_token": intent["fencing_token"],
                  "status": status, "exit_code": exit_code, "usage": usage(**(usage_over or {})), "duration_ms": 10,
                  "effect_outcome": effect, "provider_request_id": None, "run_id": intent["run_id"],
                  "task_id": intent["task_id"], "outputs": outputs or []}
        return validate(result, "result")

    def accept_result(self, intent, **kw):
        result = self.result_record(intent, **kw)
        receipt = self.submit("accept_result", result, intent["task_id"], intent["run_id"])
        return result, receipt

    def assessment_record(self, check_id, input_refs, evidence_ref=None, outcome="passed", verifier="fixture.oracle",
                          run_id="run-01", task_id="task-01", verifier_digest=None, version="v1"):
        reg = self.catalog["verifiers"][verifier]
        record = {"schema": "gabriel.assessment/1", "assessment_id": self.fresh("assessment"), "task_id": task_id,
                  "check_id": check_id, "check_version": version, "input_refs": list(input_refs), "outcome": outcome,
                  "evidence_ref": evidence_ref or self.put({"verdict": outcome, "check": check_id}),
                  "verifier_id": verifier, "verifier_digest": verifier_digest or reg["implementation_fingerprint"],
                  "run_id": run_id}
        return validate(record, "assessment")

    def assess(self, check_id, input_refs, **kw):
        record = self.assessment_record(check_id, input_refs, **kw)
        return self.submit("accept_assessment", record, record["task_id"], record["run_id"])

    def complete_node(self, intent, check_ids=None, outcome="passed"):
        """Mark, accept a completed result and assess every declared check."""
        self.mark(intent)
        result, _ = self.accept_result(intent)
        projection = self.owner.projection(intent["run_id"])
        node_state = projection["nodes"][intent["step_id"]]
        node = next(n for n in projection["plan"]["nodes"] if n["node_id"] == intent["step_id"])
        snapshot = projection["run_meta"]["observed_snapshot_ref"]
        receipts = []
        for check_id in check_ids or node["check_ids"]:
            verifier = "owner.output_valid" if check_id == "output-valid" else "fixture.oracle"
            refs = [snapshot] if snapshot else []
            refs += [node_state["result_ref"]]
            receipts.append(self.assess(check_id, refs, verifier=verifier, outcome=outcome,
                                        run_id=intent["run_id"], task_id=intent["task_id"]))
        return result, receipts

    def run_default_to_success(self):
        self.admit(); self.start(); self.accept_plan()
        i1, _ = self.issue("observe"); self.complete_node(i1)
        i2, _ = self.issue("change"); self.complete_node(i2)
        return self.owner.run_record("run-01")
