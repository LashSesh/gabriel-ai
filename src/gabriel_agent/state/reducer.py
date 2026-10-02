"""Pure transition function of the agent owner.

``reduce(projection, command, payload, inputs)`` performs no I/O: no network,
files, random draws, clock reads or provider SDK. Policy identities, trusted
owner time, grant state, catalog entries and artifact verification results
arrive as validated inputs and are retained beside the event so recorded
replay can recompute every projection.
"""
from __future__ import annotations

import copy
import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from ..contracts.codec import canonical, digest
from ..contracts.errors import Code, GabrielError
from ..contracts.rules import (CEILING_MAP, amendment_weakens, mandatory_check_ids, plan_authority,
                               plan_budget_feasible, plan_dag)
from ..contracts.schemas import OP_TO_EVENT, validate
from ..planning.scheduler import WRITE_CLASSES, node_dependencies_verified, writer_conflict
from ..policy import budget, grants

TERMINAL_STATES = {"succeeded", "failed", "cancelled"}
RETRYABLE_RESULT_STATUSES = {"rate_limited", "timed_out", "failed"}
MAX_ATTEMPTS_PER_NODE = 3
DEFAULT_MAX_PLAN_VERSIONS = 4
DEFAULT_MAX_REPAIRS = 2


@dataclass
class ReduceResult:
    projection: dict
    event_kind: str
    run_state: str
    notes: list = field(default_factory=list)


def reducer_identity() -> str:
    """SHA-256 of this module's source: part of every checkpoint binding."""
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _deny(message, obj=None, code=Code.POLICY_DENIED):
    raise GabrielError(code, message, obj=obj)


def _invalid(message, obj=None):
    raise GabrielError(Code.INVALID_TRANSITION, message, obj=obj)


def _require_artifacts(inputs, refs, what):
    verification = inputs.get("artifact_verification", {})
    for ref in refs:
        status = verification.get(ref["sha256"])
        if status != "ok":
            code = Code.STORAGE_FAULT if status == "corrupt" else Code.ARTIFACT_MISSING
            raise GabrielError(code, "%s artifact is %s" % (what, status or "unverified"), obj=ref["sha256"])


def _new_projection(task, run, payload, inputs):
    return {
        "task": task,
        "task_history": [inputs["task_spec_ref"]],
        "binding_ref": payload["binding_ref"],
        "goal_spec_ref": payload["goal_spec_ref"],
        "compilation_report_ref": payload["compilation_report_ref"],
        "run": run,
        "run_meta": {"started_owner_time_unix_ms": None, "repair_count": 0, "plan_versions": 0,
                     "limit_violation": False, "hold": None, "next_fencing_token": 1,
                     "observed_snapshot_ref": None, "admitted_owner_time_unix_ms": inputs["owner_time_unix_ms"],
                     "evidence_revision": 0},
        "plan": None,
        "plan_history": [],
        "nodes": {},
        "attempts": {},
        "ledger": {"spent": budget.zero(), "reserved": budget.zero(), "overruns": [], "pending_reconciliation": []},
        "assessments": {},
        "observations": {},
        "late_results": [],
        "reconciliations": {},
        "holds": [],
    }


def _active_targets(projection):
    active = {}
    for attempt in projection["attempts"].values():
        if attempt["status"] in ("issued", "marked"):
            slot = active.setdefault(attempt["target_id"], {"reads": 0, "writes": 0})
            if attempt["effect_class"] in WRITE_CLASSES:
                slot["writes"] += 1
            else:
                slot["reads"] += 1
    return active


def _binding(inputs):
    return inputs.get("binding") or {}


def _grant(inputs, projection, command):
    grant = inputs.get("grant")
    if grant is None:
        _deny("grant is not registered: " + projection["task"]["grant_id"], obj=projection["task"]["grant_id"])
    if grant["grant_id"] != projection["task"]["grant_id"]:
        _deny("supplied grant does not match the task grant", obj=grant["grant_id"])
    if command["policy_digest"] != projection["task"]["policy_digest"]:
        _deny("command policy digest does not match the task policy", obj=command["command_id"])
    return grant


# ---------------------------------------------------------------- operations

def _admit_task(command, payload, inputs):
    task = payload["task"]
    if command["task_id"] != task["task_id"] or command["run_id"] != payload["run_id"]:
        _invalid("command identities disagree with the admission payload", command["command_id"])
    if task["workspace_id"] != inputs["workspace_id"] or command["workspace_id"] != inputs["workspace_id"]:
        _deny("task belongs to another workspace", task["task_id"])
    if task["principal_id"] != inputs["principal_id"]:
        _deny("caller is not the task principal", task["task_id"])
    if task["task_spec_revision"] != 0 or command["expected_revision"] != 0:
        _invalid("admission requires task revision 0 and expected revision 0", task["task_id"])
    grant = inputs.get("grant")
    if grant is None:
        _deny("grant is not registered: " + task["grant_id"], task["grant_id"])
    grants.check_scope(grant, workspace_id=task["workspace_id"], task_id=task["task_id"], principal_id=task["principal_id"])
    ok, reason = grants.active(grant, inputs.get("grant_revoked_at"), inputs["owner_time_unix_ms"])
    if not ok:
        _deny("grant is " + reason, grant["grant_id"])
    if not (task["policy_digest"] == grant["policy_digest"] == command["policy_digest"]):
        _deny("policy digests disagree between task, grant and command", task["task_id"])
    for cfield in CEILING_MAP:
        if task["budget_ceiling"][cfield] > grant["budget_ceiling"][cfield]:
            _deny("task ceiling exceeds grant ceiling in " + cfield, task["task_id"])
    if task["budget_ceiling"]["elapsed_ms"] > grant["budget_ceiling"]["elapsed_ms"]:
        _deny("task deadline allowance exceeds grant allowance", task["task_id"])
    if task["budget_ceiling"]["currency"] != grant["budget_ceiling"]["currency"]:
        _deny("task currency differs from grant currency", task["task_id"])
    if not mandatory_check_ids(task):
        _invalid("a task needs at least one mandatory check", task["task_id"])
    refs = [task["goal_ref"], task["acceptance_ref"], payload["binding_ref"], payload["goal_spec_ref"],
            payload["compilation_report_ref"]] + list(task["base_inputs"]) + [c["spec_ref"] for c in task["checks"]]
    _require_artifacts(inputs, refs, "task input")
    report = inputs.get("compilation_report")
    if report is None or not report["admissible"] or report["unresolved_mandatory_count"] != 0:
        _deny("compilation report leaves mandatory clauses unresolved or is absent", task["task_id"])
    run = {"schema": "gabriel.run/1", "run_id": payload["run_id"], "task_id": task["task_id"], "run_revision": 0,
           "state": "admitted", "pause_requested": False, "budget": copy.deepcopy(task["budget_ceiling"]),
           "unresolved_effect_ids": [], "parent_run_id": None, "task_spec_ref": inputs["task_spec_ref"]}
    validate(run, "run")
    projection = _new_projection(task, run, payload, inputs)
    return ReduceResult(projection, OP_TO_EVENT["admit_task"], "admitted", ["task admitted"])


def _start_run(projection, command, payload, inputs):
    run = projection["run"]
    if run["state"] != "admitted":
        _invalid("start_run requires state admitted, found " + run["state"], run["run_id"])
    if payload["run_id"] != run["run_id"]:
        _invalid("run-start names another run", run["run_id"])
    grant = _grant(inputs, projection, command)
    ok, reason = grants.active(grant, inputs.get("grant_revoked_at"), inputs["owner_time_unix_ms"])
    if not ok:
        _deny("grant is " + reason, grant["grant_id"])
    run["state"] = "planning"
    projection["run_meta"]["started_owner_time_unix_ms"] = inputs["owner_time_unix_ms"]
    return ReduceResult(projection, OP_TO_EVENT["start_run"], "planning", ["run started; deadline timer armed"])


def _accept_plan(projection, command, payload, inputs):
    run, meta = projection["run"], projection["run_meta"]
    plan = payload
    if run["state"] not in ("planning", "running"):
        _invalid("accept_plan requires planning or running, found " + run["state"], run["run_id"])
    if plan["run_id"] != run["run_id"] or plan["task_id"] != run["task_id"]:
        _invalid("plan names another run or task", plan["plan_id"])
    current = projection["plan"]
    if (current is None and plan["parent_plan_id"] is not None) or (current is not None and plan["parent_plan_id"] != current["plan_id"]):
        _invalid("plan parent must be the current plan version", plan["plan_id"])
    if any(a["status"] in ("issued", "marked") for a in projection["attempts"].values()):
        _invalid("attempts are in flight; a new plan cannot supersede them", plan["plan_id"])
    if plan["plan_id"] in projection["plan_history"]:
        _invalid("plan id already used", plan["plan_id"])
    limit = _binding(inputs).get("max_plan_versions", DEFAULT_MAX_PLAN_VERSIONS)
    if meta["plan_versions"] + 1 > limit:
        _deny("plan version limit reached (%d)" % limit, plan["plan_id"], Code.BUDGET_EXHAUSTED)
    grant = _grant(inputs, projection, command)
    plan_dag(plan)
    plan_authority(plan, projection["task"], grant, inputs.get("catalog_tools", {}))
    plan_budget_feasible(plan, projection["task"]["budget_ceiling"])
    _require_artifacts(inputs, [plan["reason_ref"]] + [i for n in plan["nodes"] for i in n["inputs"] if "sha256" in i], "plan input")
    old_nodes = {n["node_id"]: n for n in current["nodes"]} if current else {}
    nodes = {}
    for node in plan["nodes"]:
        previous = projection["nodes"].get(node["node_id"])
        if (previous is not None and node["node_id"] in old_nodes
                and canonical(old_nodes[node["node_id"]]) == canonical(node)
                and previous["status"] in ("completed", "verified")):
            nodes[node["node_id"]] = previous  # identical node keeps its retained evidence
        else:
            nodes[node["node_id"]] = {"status": "pending", "attempts": 0, "result_ref": None, "outputs": {},
                                      "assessments": {}, "last_failure": None}
    projection["plan"] = plan
    projection["plan_history"].append(plan["plan_id"])
    projection["nodes"] = nodes
    meta["plan_versions"] += 1
    run["state"] = "running"
    return ReduceResult(projection, OP_TO_EVENT["accept_plan"], "running",
                        ["plan version %d accepted with %d nodes" % (meta["plan_versions"], len(nodes))])


PLAN_REQUEST_STEP = "plan-request"
MAX_PLAN_REQUESTS_PER_VERSION = 2


def _planner_node(projection, intent, inputs, tool):
    """Synthetic node for a planner model request while no plan is admitted."""
    binding = _binding(inputs)
    attempts = [a for a in projection["attempts"].values() if a["step_id"] == PLAN_REQUEST_STEP
                and a.get("plan_version") == projection["run_meta"]["plan_versions"]]
    if len(attempts) >= MAX_PLAN_REQUESTS_PER_VERSION:
        _deny("planner request limit reached for this plan version", intent["intent_id"], Code.BUDGET_EXHAUSTED)
    reservation = binding.get("planner_reservation") or {
        "model_tokens": 8000, "model_requests": 1, "tool_attempts": 0, "cpu_ms": 0, "elapsed_ms": 0,
        "artifact_bytes": 1 << 20, "currency_micro_units": 0, "currency": projection["run"]["budget"]["currency"],
        "accounting_status": "confirmed"}
    return {"node_id": PLAN_REQUEST_STEP, "capability_id": intent["capability_id"], "effect_class": tool["effect_class"],
            "retry_class": "target_idempotent_retry", "reservation": reservation, "depends_on": [], "outputs": [],
            "check_ids": [], "priority": 0, "max_repair_attempts": 0, "inputs": [], "output_schema_digest": tool["output_schema_digest"]}


def _issue_intent(projection, command, payload, inputs):
    run, meta, intent = projection["run"], projection["run_meta"], payload
    planner_request = run["state"] == "planning" and intent["step_id"] == PLAN_REQUEST_STEP
    if run["state"] != "running" and not planner_request:
        _invalid("issue_intent requires state running (or a plan-request while planning), found " + run["state"], run["run_id"])
    if run["pause_requested"]:
        _deny("run is paused; no new dispatch", run["run_id"])
    if meta["limit_violation"]:
        _deny("admission suspended after a resource limit violation", run["run_id"], Code.BUDGET_EXHAUSTED)
    if budget.deadline_exceeded(meta["started_owner_time_unix_ms"], run["budget"]["elapsed_ms"], inputs["owner_time_unix_ms"]):
        _deny("run wall-clock deadline exceeded", run["run_id"], Code.BUDGET_EXHAUSTED)
    if intent["run_id"] != run["run_id"] or intent["task_id"] != run["task_id"]:
        _invalid("intent names another run or task", intent["intent_id"])
    tool = inputs.get("catalog_tools", {}).get(intent["capability_id"])
    if tool is None:
        _deny("unknown capability " + intent["capability_id"], intent["intent_id"])
    if planner_request:
        if any(a["status"] in ("issued", "marked") for a in projection["attempts"].values()):
            _invalid("a planner request is already in flight", intent["intent_id"])
        node = _planner_node(projection, intent, inputs, tool)
        state = {"status": "pending", "attempts": 0}
    else:
        plan = projection["plan"]
        node = next((n for n in plan["nodes"] if n["node_id"] == intent["step_id"]), None)
        if node is None:
            _invalid("intent step is not in the current plan", intent["step_id"])
        state = projection["nodes"][node["node_id"]]
        if state["status"] != "pending":
            _invalid("node is not pending: " + state["status"], node["node_id"])
        if not node_dependencies_verified(node, projection["nodes"]):
            _invalid("node dependencies are not verified", node["node_id"])
        if state["attempts"] >= MAX_ATTEMPTS_PER_NODE or (node["retry_class"] == "never" and state["attempts"] >= 1):
            _deny("node attempt limit reached", node["node_id"], Code.BUDGET_EXHAUSTED)
    if intent["capability_id"] != node["capability_id"] or intent["effect_class"] != node["effect_class"]:
        _invalid("intent capability or effect class disagrees with the plan node", intent["intent_id"])
    grant = _grant(inputs, projection, command)
    grants.check_intent(intent, grant, tool, approvals=set(inputs.get("approvals", [])),
                        revoked_at=inputs.get("grant_revoked_at"), owner_time_unix_ms=inputs["owner_time_unix_ms"],
                        policy_digest=projection["task"]["policy_digest"])
    if intent["fencing_token"] != meta["next_fencing_token"]:
        _invalid("fencing token must be %d" % meta["next_fencing_token"], intent["intent_id"])
    if intent["attempt_id"] in projection["attempts"]:
        _invalid("attempt id already used", intent["attempt_id"])
    for attempt in projection["attempts"].values():
        if attempt["lease_id"] == intent["lease_id"] or attempt["intent_id"] == intent["intent_id"]:
            _invalid("lease or intent id already used", intent["intent_id"])
        if (attempt["target_id"] == intent["target_id"] and attempt["idempotency_key"] == intent["idempotency_key"]
                and attempt["status"] not in ("cancelled",)):
            _invalid("idempotency key already used on this target", intent["idempotency_key"])
    active = _active_targets(projection)
    if writer_conflict(intent["target_id"], intent["effect_class"], active):
        _invalid("another writer is active on " + intent["target_id"], intent["intent_id"])
    if intent["effect_class"] == "read":
        reads = sum(v["reads"] for v in active.values())
        if reads >= run["budget"]["concurrent_reads"]:
            _deny("concurrent read worker limit reached", intent["intent_id"], Code.BUDGET_EXHAUSTED)
    _require_artifacts(inputs, [intent["args_ref"], intent["precondition_ref"]], "intent input")
    demand = budget.usage_vector(node["reservation"])
    ledger = projection["ledger"]
    ledger["reserved"] = budget.admit(ledger["spent"], ledger["reserved"], demand, budget.ceiling_vector(run["budget"]))
    projection["attempts"][intent["attempt_id"]] = {
        "intent_ref": inputs["payload_ref"], "intent_id": intent["intent_id"], "attempt_id": intent["attempt_id"],
        "lease_id": intent["lease_id"], "fencing_token": intent["fencing_token"], "step_id": intent["step_id"],
        "status": "issued", "effect_state": "authorized", "result_ref": None, "marker_ref": None,
        "reservation": demand, "lease_expires_at_unix_ms": intent["expires_at_unix_ms"],
        "capability_id": intent["capability_id"], "target_id": intent["target_id"],
        "effect_class": intent["effect_class"], "idempotency_key": intent["idempotency_key"],
        "reconciliation": intent["reconciliation"], "issued_owner_time_unix_ms": inputs["owner_time_unix_ms"],
        "usage": None, "result_status": None, "effect_outcome": None,
        "plan_version": meta["plan_versions"],
    }
    if not planner_request:
        state["status"] = "active"
        state["attempts"] += 1
    meta["next_fencing_token"] += 1
    return ReduceResult(projection, OP_TO_EVENT["issue_intent"], run["state"],
                        ["planner request authorized and reserved" if planner_request else "intent authorized and reserved"])


def _mark_dispatch(projection, command, payload, inputs):
    run, marker = projection["run"], payload
    attempt = projection["attempts"].get(marker["attempt_id"])
    if attempt is None:
        _invalid("unknown attempt", marker["attempt_id"])
    if attempt["status"] != "issued":
        _invalid("dispatch marker requires an issued attempt, found " + attempt["status"], marker["attempt_id"])
    if (marker["intent_id"], marker["lease_id"], marker["fencing_token"], marker["run_id"]) != (
            attempt["intent_id"], attempt["lease_id"], attempt["fencing_token"], run["run_id"]):
        _invalid("marker identities disagree with the attempt", marker["attempt_id"])
    if run["state"] != "running" and not (run["state"] == "planning" and attempt["step_id"] == PLAN_REQUEST_STEP):
        _invalid("dispatch requires state running, found " + run["state"], run["run_id"])
    if run["pause_requested"]:
        _deny("run is paused; dispatch refused", run["run_id"])
    if marker["owner_time_unix_ms"] > inputs["owner_time_unix_ms"]:
        _invalid("marker time is ahead of trusted owner time", marker["attempt_id"])
    if attempt["lease_expires_at_unix_ms"] <= inputs["owner_time_unix_ms"]:
        _deny("lease expired before dispatch", marker["attempt_id"])
    grant = _grant(inputs, projection, command)
    ok, reason = grants.active(grant, inputs.get("grant_revoked_at"), inputs["owner_time_unix_ms"])
    if not ok:
        _deny("grant is %s at dispatch" % reason, grant["grant_id"])
    _require_artifacts(inputs, [marker["authorization_input_ref"]], "authorization input")
    attempt["status"] = "marked"
    attempt["effect_state"] = "dispatched"
    attempt["marker_ref"] = inputs["payload_ref"]
    attempt["marked_owner_time_unix_ms"] = inputs["owner_time_unix_ms"]
    return ReduceResult(projection, OP_TO_EVENT["mark_dispatch"], run["state"], ["dispatch attempt marked before external I/O"])


def _accept_result(projection, command, payload, inputs):
    run, meta, result = projection["run"], projection["run_meta"], payload
    attempt = projection["attempts"].get(result["attempt_id"])
    if attempt is None:
        _invalid("unknown attempt", result["attempt_id"])
    if (result["intent_id"], result["lease_id"], result["fencing_token"], result["run_id"], result["task_id"]) != (
            attempt["intent_id"], attempt["lease_id"], attempt["fencing_token"], run["run_id"], run["task_id"]):
        _invalid("result identities disagree with the attempt/lease", result["attempt_id"])
    if attempt["status"] == "issued":
        # No dispatch marker was ever committed, so no I/O can have happened: the only
        # admissible "result" is the supervisor abandoning the lease.
        if result["status"] == "cancelled" and result["effect_outcome"] == "not_applicable" and not result["outputs"]:
            ledger = projection["ledger"]
            ledger["reserved"] = budget.release(ledger["reserved"], attempt["reservation"])
            attempt["status"] = "cancelled"
            attempt["effect_state"] = "authorized"
            attempt["result_ref"] = inputs["payload_ref"]
            node_state = projection["nodes"].get(attempt["step_id"])
            if node_state is not None and node_state["status"] == "active":
                node_state["status"] = "pending"
                node_state["attempts"] = max(0, node_state["attempts"] - 1)
            return ReduceResult(projection, OP_TO_EVENT["accept_result"], run["state"],
                                ["lease abandoned before any dispatch marker; reservation released"])
        _invalid("result for an attempt that was never marked dispatched", result["attempt_id"])
    _require_artifacts(inputs, [o["artifact_ref"] for o in result["outputs"]], "result output")
    actual = budget.usage_vector(result["usage"])
    ledger = projection["ledger"]
    notes = []
    planner_request = attempt["step_id"] == PLAN_REQUEST_STEP
    if attempt["status"] != "marked" or run["state"] in TERMINAL_STATES or (attempt["step_id"] not in projection["nodes"] and not planner_request):
        # Late, duplicate, cancelled or obsolete: audit fact only, never a plan advance.
        charge_needed = attempt.get("usage") is None and attempt["status"] in ("marked", "cancelled")
        if charge_needed:
            ledger["spent"], ledger["reserved"], overrun, pending = budget.confirm(
                ledger["spent"], ledger["reserved"], attempt["reservation"], actual, result["usage"]["accounting_status"])
            attempt["usage"] = actual
            if overrun:
                ledger["overruns"].append({"attempt_id": attempt["attempt_id"], "overrun": overrun})
        projection["late_results"].append({"attempt_id": result["attempt_id"], "result_ref": inputs["payload_ref"],
                                           "status": result["status"], "effect_outcome": result["effect_outcome"],
                                           "attempt_status": attempt["status"]})
        if attempt["status"] == "cancelled":
            attempt["result_ref"] = inputs["payload_ref"]
            if result["effect_outcome"] == "outcome_unknown" and attempt["intent_id"] not in run["unresolved_effect_ids"]:
                run["unresolved_effect_ids"].append(attempt["intent_id"])
                attempt["effect_state"] = "outcome_unknown"
        return ReduceResult(projection, OP_TO_EVENT["accept_result"], run["state"],
                            ["late or obsolete result retained as audit fact; no plan advance"])
    ledger["spent"], ledger["reserved"], overrun, pending = budget.confirm(
        ledger["spent"], ledger["reserved"], attempt["reservation"], actual, result["usage"]["accounting_status"])
    attempt["usage"] = actual
    attempt["result_ref"] = inputs["payload_ref"]
    attempt["result_status"] = result["status"]
    attempt["effect_outcome"] = result["effect_outcome"]
    if overrun:
        ledger["overruns"].append({"attempt_id": attempt["attempt_id"], "overrun": overrun})
        meta["limit_violation"] = True
        notes.append("resource limit violation retained; further admission suspended")
    if pending:
        ledger["pending_reconciliation"].append(attempt["attempt_id"])
        notes.append("usage conservative pending reconciliation")
    if planner_request:
        attempt["status"] = result["status"] if result["effect_outcome"] != "outcome_unknown" else "outcome_unknown"
        attempt["effect_state"] = "confirmed" if result["effect_outcome"] != "outcome_unknown" else "outcome_unknown"
        if result["effect_outcome"] == "outcome_unknown":
            run["unresolved_effect_ids"].append(attempt["intent_id"])
            notes.append("planner request outcome unknown; reconciliation obligation recorded")
        else:
            notes.append("planner response retained (%s); plan admission is a separate decision" % result["status"])
        return ReduceResult(projection, OP_TO_EVENT["accept_result"], run["state"], notes)
    node_state = projection["nodes"][attempt["step_id"]]
    node = next(n for n in projection["plan"]["nodes"] if n["node_id"] == attempt["step_id"])
    tool = inputs.get("catalog_tools", {}).get(attempt["capability_id"], {})
    if result["effect_outcome"] == "outcome_unknown":
        attempt["status"] = "outcome_unknown"
        attempt["effect_state"] = "outcome_unknown"
        run["unresolved_effect_ids"].append(attempt["intent_id"])
        node_state["status"] = "pending" if node["retry_class"] in ("target_idempotent_retry", "read_retry") else "failed"
        node_state["last_failure"] = "outcome_unknown"
        notes.append("effect outcome unknown; reconciliation obligation recorded")
        return ReduceResult(projection, OP_TO_EVENT["accept_result"], run["state"], notes)
    if result["status"] == "completed" and result["effect_outcome"] in ("not_applicable", "acknowledged_success"):
        declared = {o["output_slot"]: o["schema_digest"] for o in node["outputs"]}
        actual_outputs = {o["output_slot"]: o["schema_digest"] for o in result["outputs"]}
        if len(actual_outputs) != len(result["outputs"]) or actual_outputs != declared:
            _invalid("completed result must bind exactly the declared output slots and schemas", result["result_id"],)
        attempt["status"] = "completed"
        attempt["effect_state"] = "confirmed" if attempt["effect_class"] != "read" else "confirmed"
        node_state["status"] = "completed"
        node_state["result_ref"] = inputs["payload_ref"]
        node_state["outputs"] = {o["output_slot"]: o["artifact_ref"] for o in result["outputs"]}
        node_state["assessments"] = {}
        slot = tool.get("observation_slot")
        if slot and slot in node_state["outputs"]:
            meta["observed_snapshot_ref"] = node_state["outputs"][slot]
            meta["evidence_revision"] += 1
            notes.append("observed snapshot advanced from read-back evidence")
        notes.append("result accepted; checks pending")
    else:
        attempt["status"] = result["status"]
        attempt["effect_state"] = "confirmed"
        node_state["last_failure"] = result["status"]
        retry_ok = (node["retry_class"] != "never" and node_state["attempts"] < MAX_ATTEMPTS_PER_NODE
                    and result["status"] in RETRYABLE_RESULT_STATUSES
                    and (node["retry_class"] != "reconcile_before_retry" or attempt["effect_class"] == "read"
                         or result["effect_outcome"] == "acknowledged_failure"))
        node_state["status"] = "pending" if retry_ok else "failed"
        notes.append("attempt %s; node %s" % (result["status"], node_state["status"]))
    return ReduceResult(projection, OP_TO_EVENT["accept_result"], run["state"], notes)


def _assessment_is_current(projection, entry):
    meta = projection["run_meta"]
    return (entry["task_spec_revision"] == projection["task"]["task_spec_revision"]
            and entry["evidence_revision"] == meta["evidence_revision"])


def _completion(projection, inputs):
    """complete = all mandatory eligible passes and artifacts verified and effects reconciled
    and every plan node verified with no attempt in flight."""
    task, run = projection["task"], projection["run"]
    mandatory = mandatory_check_ids(task)
    passed = set()
    refs = []
    for entry in projection["assessments"].values():
        if entry["outcome"] == "passed" and _assessment_is_current(projection, entry) and entry["eligible"]:
            passed.add(entry["check_id"])
            refs.append(entry["evidence_ref"])
            refs.extend(entry["input_refs"])
    if not mandatory <= passed:
        return False, "mandatory checks without eligible passing evidence: " + ",".join(sorted(mandatory - passed))
    if run["unresolved_effect_ids"]:
        return False, "unresolved external effects"
    if any(a["status"] in ("issued", "marked") for a in projection["attempts"].values()):
        return False, "attempts in flight"
    if projection["plan"] is None or any(s["status"] != "verified" for s in projection["nodes"].values()):
        return False, "plan nodes remain unverified"
    verification = inputs.get("artifact_verification", {})
    for ref in refs:
        if verification.get(ref["sha256"]) != "ok":
            return False, "required artifact not verified: " + ref["sha256"]
    return True, "complete"


def _accept_assessment(projection, command, payload, inputs):
    run, meta, task, assessment = projection["run"], projection["run_meta"], projection["task"], payload
    if run["state"] != "running":
        _invalid("accept_assessment requires state running, found " + run["state"], run["run_id"])
    if assessment["run_id"] != run["run_id"] or assessment["task_id"] != task["task_id"]:
        _invalid("assessment names another run or task", assessment["assessment_id"])
    if assessment["assessment_id"] in projection["assessments"]:
        _invalid("assessment id already used", assessment["assessment_id"])
    check = next((c for c in task["checks"] if c["check_id"] == assessment["check_id"]), None)
    if check is None:
        _invalid("assessment names an unknown check", assessment["check_id"])
    if check["version"] != assessment["check_version"]:
        _invalid("assessment check version disagrees with the admitted check", assessment["check_id"])
    verifier = inputs.get("catalog_verifiers", {}).get(assessment["verifier_id"])
    if verifier is None:
        _deny("verifier is not registered: " + assessment["verifier_id"], assessment["assessment_id"])
    if verifier["implementation_fingerprint"] != assessment["verifier_digest"]:
        _deny("verifier digest does not match the registered implementation", assessment["assessment_id"])
    binding = _binding(inputs)
    spec = next((s for s in binding.get("check_specs", []) if s["check_id"] == assessment["check_id"]), None)
    if spec is not None and spec["predicate_kind"] != verifier["predicate_kind"]:
        _deny("verifier predicate kind %s cannot assess %s" % (verifier["predicate_kind"], spec["predicate_kind"]),
              assessment["assessment_id"])
    _require_artifacts(inputs, [assessment["evidence_ref"]] + list(assessment["input_refs"]), "assessment")
    # Eligibility: evidence must bind the current observed snapshot unless the check is structural.
    structural = spec is not None and spec["role"] == "structural"
    snapshot_ref = meta["observed_snapshot_ref"]
    bound_to_snapshot = snapshot_ref is not None and any(canonical(r) == canonical(snapshot_ref) for r in assessment["input_refs"])
    eligible = structural or bound_to_snapshot
    if not eligible and snapshot_ref is None:
        raise GabrielError(Code.STALE_EVIDENCE, "no observed snapshot exists yet; evidence cannot bind", obj=assessment["assessment_id"])
    if not eligible:
        raise GabrielError(Code.STALE_EVIDENCE, "assessment evidence is not bound to the current observed snapshot",
                           obj=assessment["assessment_id"])
    # Attach to the node whose retained result produced the evidence (by artifact identity).
    node_id = None
    cited = [canonical(r) for r in [assessment["evidence_ref"]] + list(assessment["input_refs"])]
    for nid in sorted(projection["nodes"]):  # deterministic: identical under replay
        state = projection["nodes"][nid]
        if state["result_ref"] is not None and canonical(state["result_ref"]) in cited:
            node_id = nid
            break
    entry = {"assessment_id": assessment["assessment_id"], "check_id": assessment["check_id"], "outcome": assessment["outcome"],
             "evidence_ref": assessment["evidence_ref"], "input_refs": list(assessment["input_refs"]),
             "verifier_id": assessment["verifier_id"], "task_spec_revision": task["task_spec_revision"],
             "evidence_revision": meta["evidence_revision"], "eligible": eligible, "node_id": node_id,
             "mandatory": check["mandatory"], "sequence_hint": len(projection["assessments"]) + 1,
             "assessment_ref": inputs["payload_ref"]}
    projection["assessments"][assessment["assessment_id"]] = entry
    notes = ["assessment %s recorded for %s" % (assessment["outcome"], assessment["check_id"])]
    if node_id is not None:
        state = projection["nodes"][node_id]
        state["assessments"][assessment["check_id"]] = assessment["assessment_id"]
        node = next(n for n in projection["plan"]["nodes"] if n["node_id"] == node_id)
        if state["status"] == "completed":
            verdicts = {}
            roles = {s["check_id"]: s["role"] for s in binding.get("check_specs", [])}
            for cid in node["check_ids"]:
                aid = state["assessments"].get(cid)
                outcome = projection["assessments"][aid]["outcome"] if aid else "not_run"
                # A baseline-only check records the pre-change outcome; a recorded failure is
                # retained evidence (pre-existing failure), not a reason to fail the node.
                if roles.get(cid) == "baseline_only" and outcome in ("passed", "failed"):
                    outcome = "passed"
                verdicts[cid] = outcome
            if all(v == "passed" for v in verdicts.values()):
                state["status"] = "verified"
                notes.append("node %s verified from accepted assessment evidence" % node_id)
            elif any(v == "failed" for v in verdicts.values()):
                state["status"] = "failed"
                state["last_failure"] = "assessment_failed"
    if assessment["outcome"] == "failed" and check["mandatory"] and (spec is None or spec["role"] != "baseline_only"):
        limit = binding.get("max_repairs", DEFAULT_MAX_REPAIRS)
        if meta["repair_count"] < limit:
            meta["repair_count"] += 1
            run["state"] = "planning"
            notes.append("mandatory check failed; repair cycle %d of %d opened" % (meta["repair_count"], limit))
        else:
            run["state"] = "failed"
            notes.append("mandatory check failed; repair policy exhausted")
        return ReduceResult(projection, OP_TO_EVENT["accept_assessment"], run["state"], notes)
    complete, reason = _completion(projection, inputs)
    if complete:
        run["state"] = "succeeded"
        notes.append("all mandatory checks passed with verified artifacts and reconciled effects")
    else:
        notes.append("not complete: " + reason)
    return ReduceResult(projection, OP_TO_EVENT["accept_assessment"], run["state"], notes)


def _record_observation(projection, command, payload, inputs):
    run = projection["run"]
    if run["state"] in TERMINAL_STATES:
        _invalid("observations cannot be recorded on a terminal run", run["run_id"])
    if payload["workspace_id"] != inputs["workspace_id"]:
        _deny("observation belongs to another workspace", payload["observation_id"])
    if payload["observation_id"] in projection["observations"]:
        _invalid("observation id already used", payload["observation_id"])
    if payload["supersedes"] is not None and payload["supersedes"] not in projection["observations"]:
        _invalid("superseded observation is unknown", payload["observation_id"])
    _require_artifacts(inputs, [payload["content_ref"], payload["scope_ref"]], "observation")
    projection["observations"][payload["observation_id"]] = {
        "ref": inputs["payload_ref"], "source_id": payload["source_id"], "source_object_id": payload["source_object_id"],
        "source_revision": payload["source_revision"], "availability_sequence": payload["availability_sequence"],
        "supersedes": payload["supersedes"]}
    return ReduceResult(projection, OP_TO_EVENT["record_observation"], run["state"], ["observation retained"])


def _reconcile_effect(projection, command, payload, inputs):
    run = projection["run"]
    attempt = projection["attempts"].get(payload["attempt_id"])
    if attempt is None or attempt["intent_id"] != payload["intent_id"]:
        _invalid("unknown attempt/intent pair", payload["attempt_id"])
    if attempt["effect_state"] != "outcome_unknown":
        _invalid("attempt has no unresolved effect", payload["attempt_id"])
    if payload["method"] != attempt["reconciliation"] and payload["method"] != "manual_review":
        _deny("reconciliation method %s is not the registered method %s" % (payload["method"], attempt["reconciliation"]),
              payload["attempt_id"])
    _require_artifacts(inputs, [payload["evidence_ref"]], "reconciliation evidence")
    projection["reconciliations"][payload["intent_id"]] = {"outcome": payload["outcome"], "method": payload["method"],
                                                           "evidence_ref": payload["evidence_ref"],
                                                           "ref": inputs["payload_ref"]}
    notes = []
    if payload["outcome"] == "still_unknown":
        notes.append("effect remains unknown; obligation retained")
        return ReduceResult(projection, OP_TO_EVENT["reconcile_effect"], run["state"], notes)
    attempt["effect_state"] = "reconciled"
    attempt["status"] = "reconciled"
    if payload["intent_id"] in run["unresolved_effect_ids"]:
        run["unresolved_effect_ids"].remove(payload["intent_id"])
    if attempt["attempt_id"] in projection["ledger"]["pending_reconciliation"]:
        projection["ledger"]["pending_reconciliation"].remove(attempt["attempt_id"])
    if run["state"] not in TERMINAL_STATES and attempt["step_id"] in projection["nodes"] and attempt["step_id"] != PLAN_REQUEST_STEP:
        state = projection["nodes"][attempt["step_id"]]
        if payload["outcome"] == "confirmed_success":
            state["status"] = "failed"  # a confirmed effect without a retained result still needs read-back evidence
            state["last_failure"] = "confirmed_success_without_result"
            notes.append("effect confirmed; node needs a fresh read-back result to continue")
        else:
            state["status"] = "pending"
            notes.append("effect did not occur; node may be retried under its retry class")
    return ReduceResult(projection, OP_TO_EVENT["reconcile_effect"], run["state"], notes)


def _request_pause(projection, command, payload, inputs):
    run = projection["run"]
    if run["state"] in TERMINAL_STATES:
        _invalid("cannot pause a terminal run", run["run_id"])
    run["pause_requested"] = True
    return ReduceResult(projection, OP_TO_EVENT["request_pause"], run["state"], ["pause flag set; running attempts may finish"])


def _resume_run(projection, command, payload, inputs):
    run = projection["run"]
    if run["state"] in TERMINAL_STATES:
        _invalid("cannot resume a terminal run", run["run_id"])
    grant = _grant(inputs, projection, command)
    ok, reason = grants.active(grant, inputs.get("grant_revoked_at"), inputs["owner_time_unix_ms"])
    if not ok:
        _deny("grant is %s; resume refused" % reason, grant["grant_id"])
    run["pause_requested"] = False
    notes = ["pause flag cleared"]
    if run["state"] in ("blocked", "waiting_user"):
        run["state"] = "running" if projection["plan"] is not None else "planning"
        projection["run_meta"]["hold"] = None
        notes.append("hold resolved; run resumes in " + run["state"])
    return ReduceResult(projection, OP_TO_EVENT["resume_run"], run["state"], notes)


def _cancel_task(projection, command, payload, inputs):
    run = projection["run"]
    if run["state"] in TERMINAL_STATES:
        _invalid("run is already terminal", run["run_id"])
    if inputs["principal_id"] != projection["task"]["principal_id"]:
        _deny("only the task principal may cancel", run["run_id"])
    _require_artifacts(inputs, [payload["reason_ref"]], "cancellation reason")
    ledger = projection["ledger"]
    for attempt in projection["attempts"].values():
        if attempt["status"] == "issued":
            ledger["reserved"] = budget.release(ledger["reserved"], attempt["reservation"])
            attempt["status"] = "cancelled"
        elif attempt["status"] == "marked":
            attempt["status"] = "cancelled"  # may still execute: keep its reservation as a conservative charge
            attempt["effect_state"] = "outcome_unknown"
            ledger["spent"], ledger["reserved"], _, _ = budget.confirm(
                ledger["spent"], ledger["reserved"], attempt["reservation"], budget.zero(), "conservative_pending_reconciliation")
            attempt["usage"] = budget.zero()
            if attempt["intent_id"] not in run["unresolved_effect_ids"]:
                run["unresolved_effect_ids"].append(attempt["intent_id"])
    run["state"] = "cancelled"
    notes = ["task cancelled"]
    if run["unresolved_effect_ids"]:
        notes.append("%d external outcome(s) awaiting reconciliation" % len(run["unresolved_effect_ids"]))
    return ReduceResult(projection, OP_TO_EVENT["cancel_task"], "cancelled", notes)


def _amend_task(projection, command, payload, inputs):
    run, old = projection["run"], projection["task"]
    new = payload["task"]
    if run["state"] in TERMINAL_STATES:
        _invalid("cannot amend a terminal run", run["run_id"])
    for key in ("task_id", "workspace_id", "principal_id", "grant_id", "policy_digest"):
        if new[key] != old[key]:
            _deny("amendment changes immutable identity " + key, new["task_id"])
    if new["task_spec_revision"] != old["task_spec_revision"] + 1:
        _invalid("amendment must advance the task revision by one", new["task_id"])
    weakens = amendment_weakens(old, new)
    if weakens:
        if payload["amendment_kind"] != "weaken_acceptance" or not payload["principal_confirmation"]:
            _deny("amendment weakens the admitted acceptance criteria without explicit authorized confirmation", new["task_id"])
        if inputs["principal_id"] != old["principal_id"]:
            _deny("only the task principal may weaken acceptance", new["task_id"])
    elif payload["amendment_kind"] == "weaken_acceptance":
        _invalid("amendment declares weakening but does not weaken", new["task_id"])
    _require_artifacts(inputs, [payload["reason_ref"], payload["goal_spec_ref"], payload["compilation_report_ref"],
                                new["goal_ref"], new["acceptance_ref"]] + [c["spec_ref"] for c in new["checks"]], "amendment")
    report = inputs.get("compilation_report")
    if report is None or not report["admissible"]:
        _deny("amended goal compilation is not admissible", new["task_id"])
    projection["task"] = new
    projection["task_history"].append(inputs["task_spec_ref"])
    projection["goal_spec_ref"] = payload["goal_spec_ref"]
    projection["compilation_report_ref"] = payload["compilation_report_ref"]
    run["task_spec_ref"] = inputs["task_spec_ref"]
    return ReduceResult(projection, OP_TO_EVENT["amend_task"], run["state"],
                        ["task amended to revision %d%s" % (new["task_spec_revision"], " (acceptance weakened by principal)" if weakens else "")])


def _record_hold(projection, command, payload, inputs):
    run = projection["run"]
    if run["state"] not in ("planning", "running", "admitted"):
        _invalid("hold requires a non-terminal active run, found " + run["state"], run["run_id"])
    if any(a["status"] in ("issued", "marked") for a in projection["attempts"].values()) and payload["target_state"] == "failed":
        _invalid("cannot fail a run with attempts in flight", run["run_id"])
    _require_artifacts(inputs, [payload["reason_ref"]], "hold reason")
    hold = {"reason_code": payload["reason_code"], "target_state": payload["target_state"],
            "missing_prerequisite": payload["missing_prerequisite"], "wakeup_condition": payload["wakeup_condition"],
            "ref": inputs["payload_ref"], "from_state": run["state"]}
    projection["holds"].append(hold)
    projection["run_meta"]["hold"] = hold
    run["state"] = payload["target_state"]
    return ReduceResult(projection, OP_TO_EVENT["record_hold"], run["state"], ["hold recorded: " + payload["reason_code"]])


_OPS = {"start_run": _start_run, "accept_plan": _accept_plan, "issue_intent": _issue_intent,
        "mark_dispatch": _mark_dispatch, "accept_result": _accept_result, "accept_assessment": _accept_assessment,
        "record_observation": _record_observation, "reconcile_effect": _reconcile_effect,
        "request_pause": _request_pause, "resume_run": _resume_run, "cancel_task": _cancel_task,
        "amend_task": _amend_task, "record_hold": _record_hold}


def reduce(projection, command: dict, payload: dict, inputs: dict) -> ReduceResult:
    """Pure transition. ``projection`` is None only for ``admit_task``."""
    op = command["op"]
    if op == "admit_task":
        if projection is not None:
            _invalid("task already admitted", command["task_id"])
        return _admit_task(command, payload, inputs)
    if projection is None:
        raise GabrielError(Code.UNKNOWN_OBJECT, "unknown run " + command["run_id"], obj=command["run_id"])
    projection = copy.deepcopy(projection)
    run = projection["run"]
    if command["run_id"] != run["run_id"] or command["task_id"] != run["task_id"]:
        _invalid("command names another run or task", command["command_id"])
    if command["expected_revision"] != run["run_revision"]:
        raise GabrielError(Code.STALE_REVISION, "expected revision %d but run is at %d" % (command["expected_revision"], run["run_revision"]),
                           obj=run["run_id"], revision=run["run_revision"])
    result = _OPS[op](projection, command, payload, inputs)
    result.projection["run"]["run_revision"] += 1
    validate(result.projection["run"], "run")
    return result


def projection_digest(projection) -> str:
    return digest(projection)
