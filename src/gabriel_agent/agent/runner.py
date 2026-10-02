"""The execution loop: read state, plan, dispatch, verify, replan, complete.

Every transition goes through the owner. The runner is trusted local code
that selects the next admissible action; models and tools never update
authoritative state. It is re-entrant: a restart recovers leases and
continues from the retained record.

The runner is domain-neutral: the task binding names a DomainPack and every
domain-specific step (observation schema, prompt, proposal normalization,
tool argument binding, verifier selection) is delegated to it (R11).
"""
from __future__ import annotations

import hashlib
import json
import time

from ..contracts.codec import canonical, dumps_utf8, loads, sha256_hex
from ..contracts.errors import Code, GabrielError
from ..contracts.schemas import validate, validate_bytes, schema_digest
from ..domains.base import ArgsHelper
from ..models import build_model_request
from ..planning import ready_nodes
from ..state.reducer import PLAN_REQUEST_STEP, TERMINAL_STATES
from ..workers import Supervisor

STOP_STATES = TERMINAL_STATES | {"blocked", "waiting_user"}


class TaskRunner:
    def __init__(self, workspace, task_id: str, *, hooks=None, max_iterations: int = 400, extras=None):
        self.ws = workspace
        self.owner, self.store, self.registry = workspace.owner, workspace.store, workspace.registry
        self.task_id = task_id
        self.run_id, _ = workspace.resolve_task(task_id)
        projection = self.owner.projection(self.run_id)
        self.binding = validate_bytes(self.store.get(projection["binding_ref"]), "task-binding")
        self.pack = workspace.pack_for(self.binding["domain_namespace"])
        self.profile = validate_bytes(self.store.get(self.binding["provider_profile_ref"]), "provider-profile")
        self.goal_text = self.store.get(projection["task"]["goal_ref"]).decode("utf8")
        self.notes = workspace.run_notes(self.run_id)
        self.worktree = workspace.worktree_for(self.run_id, self.binding)
        self.extras = dict({"protected_paths": self.notes.get("protected_paths", [])}, **(extras or {}))
        backend = workspace.backend
        self.supervisor = Supervisor(self.owner, self.store, self.registry, workspace.credential, backend=backend, hooks=hooks,
                                     extras=dict(self.extras, memory=workspace.memory, principal_id=workspace.config["principal_id"],
                                                 numerical_cache=str(workspace.path / "numerical_cache.json")))
        self.max_iterations = max_iterations
        self.log = []
        self._ids = 0

    # ------------------------------------------------------------ helpers
    def _fresh(self, prefix):
        self._ids += 1
        return "%s-%s-%d-%s" % (prefix, self.run_id, self.owner.anchor()["sequence"], hashlib.sha256(str(time.time_ns()).encode()).hexdigest()[:6])

    def _submit(self, op, payload, command_id=None):
        return self.ws.submit(op, payload, self.task_id, self.run_id, command_id=command_id)

    def _projection(self):
        return self.owner.projection(self.run_id)

    def _plan_node(self, projection, node_id):
        return next(n for n in projection["plan"]["nodes"] if n["node_id"] == node_id)

    def _hold(self, reason_code, target_state, text, prerequisite=None, wakeup=None):
        payload = {"schema": "gabriel.hold/1", "reason_code": reason_code, "target_state": target_state,
                   "reason_ref": self.store.put(text.encode("utf8"), "text/plain; charset=utf-8"),
                   "missing_prerequisite": prerequisite, "wakeup_condition": wakeup}
        self.log.append("hold %s -> %s: %s" % (reason_code, target_state, text))
        return self._submit("record_hold", payload)

    # ------------------------------------------------------------ main loop
    def run(self) -> dict:
        recovered = self.supervisor.recover(self.run_id, worktree=self.worktree, binding=self.binding)
        if recovered:
            self.log.append("recovered: " + json.dumps(recovered))
        for _ in range(self.max_iterations):
            projection = self._projection()
            state = projection["run"]["state"]
            if state in STOP_STATES:
                break
            if projection["run"]["pause_requested"]:
                self.log.append("paused")
                break
            if state == "admitted":
                self._submit("start_run", {"schema": "gabriel.run-start/1", "run_id": self.run_id,
                                           "reason_ref": self.store.put(b"runner start", "text/plain; charset=utf-8")})
                continue
            if state == "planning":
                self._plan(projection)
                continue
            if self._verify_completed(projection):
                continue
            projection = self._projection()
            if projection["run"]["state"] != "running":
                continue
            ready = ready_nodes(projection["plan"], projection["nodes"], self._active_targets(projection),
                                concurrent_reads=projection["run"]["budget"]["concurrent_reads"], paused=projection["run"]["pause_requested"])
            if ready:
                self._dispatch(projection, ready[0])
                continue
            if any(a["status"] in ("issued", "marked") for a in projection["attempts"].values()):
                self._hold("attempt_in_flight_without_supervisor", "blocked", "an attempt is in flight but no supervisor owns it; restart recovers it",
                           prerequisite="restart", wakeup="runner-restart")
                continue
            self._handle_stall(projection)
        return self.summary()

    def summary(self) -> dict:
        projection = self._projection()
        return {"task_id": self.task_id, "run_id": self.run_id, "state": projection["run"]["state"], "run_revision": projection["run"]["run_revision"],
                "plan_versions": projection["run_meta"]["plan_versions"], "repair_count": projection["run_meta"]["repair_count"],
                "hold": projection["run_meta"]["hold"], "unresolved_effects": projection["run"]["unresolved_effect_ids"],
                "assessments": [{"check_id": a["check_id"], "outcome": a["outcome"], "eligible": a["eligible"], "node_id": a["node_id"]}
                                for a in projection["assessments"].values()],
                "spent": projection["ledger"]["spent"], "port_calls": self.supervisor.port_calls, "domain": self.pack.namespace, "log": self.log}

    @staticmethod
    def _active_targets(projection):
        active = {}
        for attempt in projection["attempts"].values():
            if attempt["status"] in ("issued", "marked"):
                slot = active.setdefault(attempt["target_id"], {"reads": 0, "writes": 0})
                slot["writes" if attempt["effect_class"] != "read" else "reads"] += 1
        return active

    # ------------------------------------------------------------ planning
    def _failure_context(self, projection) -> list:
        context = []
        for entry in projection["assessments"].values():
            if entry["outcome"] != "failed":
                continue
            try:
                evidence = loads(self.store.get(entry["evidence_ref"]), ascii_only=False)
            except GabrielError:
                evidence = {}
            text = json.dumps(evidence, ensure_ascii=False)[:2000]
            # the verifier's record nests its details under "evidence"; the witness may sit at either level
            inner = evidence.get("evidence") if isinstance(evidence, dict) else None
            witness_ref = None
            for candidate in (evidence, inner):
                if isinstance(candidate, dict) and isinstance(candidate.get("witness_ref"), dict):
                    witness_ref = candidate["witness_ref"]
                    break
            if witness_ref:
                try:
                    witness = loads(self.store.get(witness_ref))
                    stderr = self.store.get(witness["stderr"]["captured_ref"]).decode("utf8", "replace")
                    stdout = self.store.get(witness["stdout"]["captured_ref"]).decode("utf8", "replace")
                    text += "\nstdout:\n" + stdout[-1500:] + "\nstderr:\n" + stderr[-1500:]
                except GabrielError:
                    pass
            context.append({"check_id": entry["check_id"], "text": text})
        return context[-4:]

    def _attempt_diagnostics(self, projection, step_id) -> list:
        """Diagnostics of earlier failed attempts of the same node (invalid or truncated
        provider output, tool errors), so a retry does not repeat the same mistake."""
        context = []
        for attempt in projection["attempts"].values():
            if attempt["step_id"] != step_id or attempt["status"] in ("issued", "marked", "completed", "cancelled") or not attempt["result_ref"]:
                continue
            try:
                result = loads(self.store.get(attempt["result_ref"]))
            except GabrielError:
                continue
            for output in result["outputs"]:
                if output["output_slot"] in ("envelope", "error"):
                    try:
                        raw = self.store.get(output["artifact_ref"]).decode("utf8", "replace")
                    except GabrielError:
                        continue
                    context.append({"check_id": "previous-attempt:" + attempt["attempt_id"],
                                    "text": "status %s: %s" % (result["status"], raw[:1500])})
        return context[-2:]

    def _materialize(self, projection, proposal, version):
        task = projection["task"]
        return self.pack.materialize_plan(proposal, task, self.binding, self.registry.catalog(), self.profile, run_id=self.run_id,
                                          plan_id="plan-%s-v%d" % (self.run_id, version + 1),
                                          parent_plan_id=projection["plan"]["plan_id"] if projection["plan"] else None,
                                          reason_ref=self.store.put(dumps_utf8(proposal), "application/json; charset=utf-8"), store=self.store)

    def _accept_reference_plan(self, projection, reference, version):
        """Deterministic reference plan from the domain pack: no provider request, same owner validation."""
        try:
            plan, _ = self._materialize(projection, reference, version)
            receipt = self._submit("accept_plan", plan)
            self.log.append("reference plan v%d accepted: %s" % (version + 1, receipt["notes"]))
        except GabrielError as exc:
            self._hold("plan_unavailable", "blocked", "reference plan rejected: " + exc.message, prerequisite="valid-plan", wakeup="user-review")

    def _plan(self, projection):
        task = projection["task"]
        version = projection["run_meta"]["plan_versions"]
        reference = self.pack.reference_plan_proposal(task, self.binding, repair_round=version)
        if self.binding.get("planner_mode", "model") == "reference":
            self._accept_reference_plan(projection, reference, version)
            return
        failure_context = self._failure_context(projection) if version else []
        visible = self.registry.visible_catalog(self.owner.grant(task["grant_id"])["grant"])
        prompt = ("You are the planner role of Gabriel. Produce a bounded plan as JSON for the %s task below.\n" % self.pack.task_noun +
                  "Goal:\n" + self.goal_text + "\n\nAvailable capabilities (ids): " + ", ".join(t["tool_id"] for t in visible["tools"]) +
                  "\nTask checks: " + ", ".join(c["check_id"] + ("*" if c["mandatory"] else "") for c in task["checks"]) +
                  "\nEvery mandatory check (*) must be covered by some node's check_ids; omitting one is rejected.\n"
                  "Reference plan you may return verbatim:\n<<<REFERENCE_PLAN>>>\n" + json.dumps(reference, ensure_ascii=False) + "\n<<<END_REFERENCE_PLAN>>>\n"
                  + ("Previous verification failures:\n" + "\n".join(f["check_id"] + ": " + f["text"][:800] for f in failure_context) + "\n" if failure_context else "")
                  + "Respond with exactly one JSON object matching the reference's shape.").encode("utf8")
        prompt_ref = self.store.put(prompt, "text/plain; charset=utf-8")
        request = build_model_request(request_id=self._fresh("req-plan"), task_id=self.task_id, run_id=self.run_id, provider_profile=self.profile, role="planner",
                                      prompt_ref=prompt_ref, evidence_refs=[task["goal_ref"]], observation_ids=[], issue_frontier=self.owner.anchor()["sequence"],
                                      output_schema_name="plan-proposal", tool_schema_digest=sha256_hex(canonical(visible)),
                                      sampling_config_ref=self.store.put(canonical({"temperature_milli": self.profile["temperature_milli"]}), "application/json"),
                                      max_input_tokens=self.profile["max_input_tokens"], max_output_tokens=self.profile["max_output_tokens"])
        args = {"request_ref": self.store.put(canonical(request), "application/json"), "provider_profile_ref": self.binding["provider_profile_ref"],
                "output_schema": "plan-proposal", "step_key": PLAN_REQUEST_STEP, "role": "planner"}
        try:
            intent = self._intent(projection, PLAN_REQUEST_STEP, "model.generate", "provider", args)
            self._submit("issue_intent", intent)
        except GabrielError as exc:
            if exc.code is Code.BUDGET_EXHAUSTED:
                self._hold("planner_budget_exhausted", "failed", exc.message)
                return
            raise
        result, _ = self.supervisor.dispatch(intent, args, worktree=self.worktree, binding=self.binding)
        proposal = None
        if result["status"] == "completed":
            output = next(o for o in result["outputs"] if o["output_slot"] == "model_output")
            proposal = loads(self.store.get(output["artifact_ref"]), ascii_only=False)
        else:
            self.log.append("planner attempt %s" % result["status"])
        if proposal is None:
            self._plan_retry_or_hold(projection, "planner returned no usable proposal (%s)" % result["status"])
            return
        try:
            plan, args_by_node = self._materialize(projection, proposal, version)
            receipt = self._submit("accept_plan", plan)
            self.log.append("plan v%d accepted: %s" % (version + 1, receipt["notes"]))
        except GabrielError as exc:
            self.log.append("plan rejected: " + exc.message)
            self._plan_retry_or_hold(self._projection(), "plan proposal rejected: " + exc.message)

    def _plan_retry_or_hold(self, projection, reason):
        projection = self._projection()
        attempts = [a for a in projection["attempts"].values() if a["step_id"] == PLAN_REQUEST_STEP
                    and a.get("plan_version") == projection["run_meta"]["plan_versions"]]
        if len(attempts) >= 2:
            self._hold("plan_unavailable", "blocked", reason + "; planner request limit reached for this plan version",
                       prerequisite="valid-plan-proposal", wakeup="user-review")

    def _intent(self, projection, node_id, capability, target, args, approval=None):
        tool = self.registry.tool(capability)[0]
        n = self._fresh("intent")
        now = self.owner.owner_time()
        intent = {"schema": "gabriel.intent/1", "intent_id": n, "task_id": self.task_id, "run_id": self.run_id, "step_id": node_id,
                  "attempt_id": n.replace("intent", "attempt", 1), "capability_id": capability,
                  "args_ref": self.store.put(canonical(args), "application/json"), "target_id": target, "grant_id": projection["task"]["grant_id"],
                  "reservation_id": n.replace("intent", "reservation", 1), "policy_digest": projection["task"]["policy_digest"],
                  "effect_class": tool["effect_class"], "idempotency_key": "%s:%s:%d" % (target, node_id, projection["run_meta"]["next_fencing_token"]),
                  "approval_digest": approval, "precondition_ref": projection["run_meta"]["observed_snapshot_ref"] or self.store.put(b"no snapshot yet", "text/plain; charset=utf-8"),
                  "reconciliation": tool["reconciliation"], "expires_at_unix_ms": now + tool["timeout_ms"] + 60000,
                  "lease_id": n.replace("intent", "lease", 1), "fencing_token": projection["run_meta"]["next_fencing_token"]}
        return validate(intent, "intent")

    # ------------------------------------------------------------ dispatch
    def _node_args(self, projection, node):
        proposal = loads(self.store.get(projection["plan"]["reason_ref"]), ascii_only=False)
        declared = next((n["args"] for n in proposal["nodes"] if n["node_id"] == node["node_id"]), {})
        capability = node["capability_id"]
        if capability == "model.generate":
            return self._propose_args(projection, node)
        helper = ArgsHelper(projection, lambda propose_node_id: self._candidate_for(projection, propose_node_id))
        return self.pack.node_args(capability, declared, helper)

    def _snapshot(self, projection):
        ref = projection["run_meta"]["observed_snapshot_ref"]
        if ref is None:
            raise GabrielError(Code.STALE_EVIDENCE, "no observed snapshot")
        snapshot, manifest = self.pack.load_snapshot(self.store, ref)
        return ref, snapshot, manifest

    def _propose_args(self, projection, node):
        snapshot_ref, snapshot, manifest = self._snapshot(projection)
        failure_context = (self._failure_context(projection) if projection["run_meta"]["plan_versions"] > 1 else [])
        failure_context += self._attempt_diagnostics(projection, node["node_id"])
        prompt, entries, observation_ids = self.pack.build_prompt(self.goal_text, self.binding, snapshot, manifest, self.store,
                                                                  failure_context=failure_context, round_index=projection["run_meta"]["plan_versions"],
                                                                  memory=self.ws.memory, principal_id=self.ws.config["principal_id"])
        prompt_ref = self.store.put(prompt, "text/plain; charset=utf-8")
        task = projection["task"]
        visible = self.registry.visible_catalog(self.owner.grant(task["grant_id"])["grant"])
        manifest_record = {"schema": "gabriel.context-manifest/1", "manifest_id": self._fresh("ctx"), "task_id": self.task_id, "run_id": self.run_id,
                           "task_spec_revision": task["task_spec_revision"], "goal_spec_ref": projection["goal_spec_ref"], "observed_snapshot_ref": snapshot_ref,
                           "issue_frontier": self.owner.anchor()["sequence"], "entries": entries[:256], "transform_ids": ["prompt-text-v1"],
                           "omitted_obligation_ids": [], "catalog_digest": sha256_hex(canonical(visible))}
        validate(manifest_record, "context-manifest")
        manifest_ref = self.store.put(canonical(manifest_record), "application/json")
        request = build_model_request(request_id=self._fresh("req"), task_id=self.task_id, run_id=self.run_id, provider_profile=self.profile, role="worker",
                                      prompt_ref=prompt_ref, evidence_refs=[snapshot_ref, manifest_ref] + [e["artifact_ref"] for e in entries][:62],
                                      observation_ids=list(observation_ids)[:64], issue_frontier=manifest_record["issue_frontier"],
                                      output_schema_name=self.pack.proposal_schema, tool_schema_digest=manifest_record["catalog_digest"],
                                      sampling_config_ref=self.store.put(canonical({"temperature_milli": self.profile["temperature_milli"]}), "application/json"),
                                      max_input_tokens=self.profile["max_input_tokens"], max_output_tokens=self.profile["max_output_tokens"])
        return {"request_ref": self.store.put(canonical(request), "application/json"), "provider_profile_ref": self.binding["provider_profile_ref"],
                "output_schema": self.pack.proposal_schema, "step_key": node["node_id"], "role": "worker", "context_manifest_ref": manifest_ref}

    def _candidate_for(self, projection, propose_node_id):
        """Deterministically normalize the retained proposal of a completed propose node into
        the pack's candidate record. Returns (candidate artifact ref, problem)."""
        state = projection["nodes"].get(propose_node_id)
        if not state or state["status"] not in ("completed", "verified") or "model_output" not in state["outputs"]:
            return None, "propose node has no retained output"
        proposal = loads(self.store.get(state["outputs"]["model_output"]), ascii_only=False)
        try:
            validate(proposal, self.pack.proposal_schema, ascii_only=False)
        except GabrielError as exc:
            return None, exc.message
        snapshot_ref, snapshot, manifest = self._snapshot(projection)
        candidate, loss, problem = self.pack.normalize_proposal(proposal, snapshot, manifest, self.binding, self.store, task_id=self.task_id, run_id=self.run_id,
                                                                proposal_ref=state["outputs"]["model_output"], protected=set(self.extras.get("protected_paths", [])),
                                                                goal_id=projection["goal_spec_ref"]["sha256"], policy_digest=projection["task"]["policy_digest"])
        envelope = {"schema": "gabriel.proposal-envelope/1", "proposal_id": "proposal-" + state["outputs"]["model_output"]["sha256"][:16], "task_id": self.task_id,
                    "run_id": self.run_id, "role": "worker", "context_manifest_ref": state["outputs"].get("request") or state["outputs"]["model_output"],
                    "request_ref": state["outputs"].get("request") or state["outputs"]["model_output"], "raw_response_ref": state["outputs"].get("raw_response"),
                    "normalized_ref": state["outputs"]["model_output"], "normalization_profile_id": self.pack.normalization_profile_id,
                    "output_schema_digest": schema_digest(self.pack.proposal_schema), "candidate_ids": [candidate["candidate_id"]] if candidate else [],
                    "loss": (loss + ([problem] if problem else []))[:64], "status": "normalized" if candidate else "rejected"}
        validate(envelope, "proposal-envelope")
        self.store.put(canonical(envelope), "application/json")
        if candidate is None:
            return None, problem
        return self.store.put(canonical(candidate), "application/json"), None

    def _dispatch(self, projection, node):
        try:
            args = self._node_args(projection, node)
        except GabrielError as exc:
            self.log.append("cannot build args for %s: %s" % (node["node_id"], exc.message))
            self._replan_or_hold(projection, "node %s cannot run: %s" % (node["node_id"], exc.message))
            return
        target = self.pack.target_for(node["capability_id"])
        intent = self._intent(projection, node["node_id"], node["capability_id"], target, args)
        try:
            self._submit("issue_intent", intent)
        except GabrielError as exc:
            if exc.code is Code.BUDGET_EXHAUSTED:
                self._hold("budget_exhausted", "failed", "cannot issue %s: %s" % (node["node_id"], exc.message))
                return
            raise
        result, receipt = self.supervisor.dispatch(intent, args, worktree=self.worktree, binding=self.binding)
        self.log.append("%s -> %s (%s)" % (node["node_id"], result["status"], "; ".join(receipt["notes"])))

    # ------------------------------------------------------------ verification
    def _verify_completed(self, projection) -> bool:
        for node_id in sorted(projection["nodes"]):
            state = projection["nodes"][node_id]
            if state["status"] != "completed":
                continue
            node = self._plan_node(projection, node_id)
            outputs = {slot: self.store.get(ref) for slot, ref in state["outputs"].items()}
            extras = dict(self.extras)
            if node["capability_id"] == "model.generate" and node_id != PLAN_REQUEST_STEP:
                candidate_ref, problem = self._candidate_for(projection, node_id)
                if candidate_ref is None:
                    extras["proposal_problem"] = "proposal normalization rejected: " + str(problem)
            for check_id in node["check_ids"]:
                if check_id in state["assessments"]:
                    continue
                spec = next(s for s in self.binding["check_specs"] if s["check_id"] == check_id)
                record, impl = self.registry.verifier(self.pack.verifier_id(spec["predicate_kind"]))
                ctx = _VerifierContext(self.store, self.binding, extras, memory=self.ws.memory, principal_id=self.ws.config["principal_id"])
                outcome, evidence = impl(spec, outputs, ctx)
                evidence_ref = self.store.put(dumps_utf8({"check_id": check_id, "node_id": node_id, "outcome": outcome, "evidence": evidence}), "application/json; charset=utf-8")
                input_refs = [projection["run_meta"]["observed_snapshot_ref"], state["result_ref"]] + list(state["outputs"].values())
                assessment = {"schema": "gabriel.assessment/1", "assessment_id": self._fresh("assessment"), "task_id": self.task_id, "check_id": check_id,
                              "check_version": spec["version"], "input_refs": [r for r in input_refs if r is not None][:64], "outcome": outcome,
                              "evidence_ref": evidence_ref, "verifier_id": record["verifier_id"], "verifier_digest": record["implementation_fingerprint"],
                              "run_id": self.run_id}
                receipt = self._submit("accept_assessment", validate(assessment, "assessment"))
                self.log.append("assess %s/%s -> %s: %s" % (node_id, check_id, outcome, "; ".join(receipt["notes"])))
                return True
        return False

    # ------------------------------------------------------------ stalls
    def _reconcile_unresolved(self, projection) -> bool:
        """Local effects reconcile through their registered read-back/status method; manual
        review stays with the user. Returns True when a reconciliation was recorded."""
        for intent_id in list(projection["run"]["unresolved_effect_ids"]):
            attempt = next((a for a in projection["attempts"].values() if a["intent_id"] == intent_id), None)
            if attempt is None or attempt["reconciliation"] == "manual_review":
                continue
            intent = validate(loads(self.store.get(attempt["intent_ref"])), "intent")
            action = self.supervisor.reconcile(intent, worktree=self.worktree, binding=self.binding)
            self.log.append("reconciled %s: %s" % (intent_id, action["outcome"]))
            return True
        return False

    def _handle_stall(self, projection):
        failed = [nid for nid, s in projection["nodes"].items() if s["status"] == "failed"]
        if projection["run"]["unresolved_effect_ids"]:
            if self._reconcile_unresolved(projection):
                return
            self._hold("unresolved_external_effects", "waiting_user", "external outcomes await reconciliation: " + ",".join(projection["run"]["unresolved_effect_ids"]),
                       prerequisite="effect-reconciliation", wakeup="reconcile_effect")
            return
        if failed:
            reasons = ", ".join("%s(%s)" % (nid, projection["nodes"][nid]["last_failure"]) for nid in failed)
            self._replan_or_hold(projection, "failed nodes: " + reasons)
            return
        self._hold("no_admissible_work", "blocked", "no ready node, no completed node to verify and no failure to repair", wakeup="user-review")

    def _replan_or_hold(self, projection, reason):
        versions = projection["run_meta"]["plan_versions"]
        if versions >= self.binding["max_plan_versions"]:
            self._hold("repair_exhausted", "failed", reason + "; plan version limit reached")
            return
        reference = self.pack.reference_plan_proposal(projection["task"], self.binding, repair_round=versions)
        try:
            plan, _ = self._materialize(projection, reference, versions)
            receipt = self._submit("accept_plan", plan)
            self.log.append("replanned after failure (%s): %s" % (reason, "; ".join(receipt["notes"])))
        except GabrielError as exc:
            self._hold("replan_rejected", "failed", reason + "; replan rejected: " + exc.message)


class _VerifierContext:
    def __init__(self, store, binding, extras, memory=None, principal_id=None):
        self.store, self.binding, self.extras, self.memory, self.principal_id = store, binding, extras, memory, principal_id
