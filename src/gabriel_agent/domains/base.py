"""The DomainPack contract the core calls (requirement R11).

The owner, scheduler, supervisor and runner never branch on a domain name: a task binding
names its pack by namespace, and every domain-specific decision (how to observe, what the
model proposes, how a proposal becomes a candidate, which verifier judges which predicate
kind, how a plan node turns into tool arguments) goes through the methods below. Everything
in this module is domain-neutral; the software, document and numerical packs implement it.
"""
from __future__ import annotations

from ..contracts.codec import loads
from ..contracts.errors import Code, GabrielError
from ..contracts.schemas import schema_digest, validate


def usage(**over) -> dict:
    base = {"model_tokens": 0, "model_requests": 0, "tool_attempts": 1, "cpu_ms": 60000, "elapsed_ms": 0, "artifact_bytes": 4 << 20,
            "currency_micro_units": 0, "currency": "EUR", "accounting_status": "confirmed"}
    base.update(over)
    return base


def descriptor(tool_id, effect_class, reconciliation, concurrency_key, *, pack_label, observation_slot=None, forms=("worktree",), approval=False):
    return {"tool_id": tool_id, "version": "v1", "effect_class": effect_class, "input_schema_digest": schema_digest("task-binding"),
            "output_schema_digest": schema_digest("result"), "timeout_ms": 600000, "max_output_bytes": 1 << 20,
            "concurrency_key": concurrency_key, "reconciliation": reconciliation, "requires_approval": approval,
            "description": "%s pack %s" % (pack_label, tool_id), "resource_forms": list(forms), "observation_slot": observation_slot}


class ArgsHelper:
    """What a pack may ask the runner for while turning a plan node into tool arguments."""

    def __init__(self, projection, candidate_for):
        self.projection = projection
        self._candidate_for = candidate_for

    @property
    def observed_snapshot_ref(self):
        return self.projection["run_meta"]["observed_snapshot_ref"]

    def candidate_for(self, propose_node_id: str):
        """(candidate artifact ref, problem) for the retained proposal of a completed propose node."""
        return self._candidate_for(propose_node_id)


class DomainPack:
    namespace = pack_id = pack_version = None
    task_noun = "task"
    snapshot_schema = proposal_schema = candidate_schema = None
    normalization_profile_id = None
    output_slots: dict = {}
    retry_class: dict = {}
    verifier_ids: dict = {}

    # ---------------------------------------------------------------- registration
    def register(self, registry) -> None:
        raise NotImplementedError

    def manifest(self, registry) -> dict:
        raise NotImplementedError

    def claims_after_success(self, projection: dict, store) -> list:
        """Claims a succeeded run establishes for the memory (ADR-20); none by default. Each entry:
        proposition bytes, supporting observation ids, the frontier, the verifier id and a reason."""
        return []

    def default_policy(self) -> dict | None:
        """The routing policy a task of this pack pins when its spec names none (ADR-22): a promoted
        readout the pack ships with its provenance, or None for the rule-based policy."""
        return None

    def progress_channels(self, projection: dict, store) -> dict | None:
        """Domain-declared progress channels at a decision point (ADR-22): committed facts of the
        run's latest verification in the pack's own terms, as ``{"schema_id", "names", "values"}``
        with values in [0, 1] or None (missing). None when the pack declares no channels. They are
        appended to the generic channels of the policy route and retained with every decision."""
        return None

    # ---------------------------------------------------------------- compile port
    def compile_task(self, spec: dict, store, **ids):
        raise NotImplementedError

    # ---------------------------------------------------------------- plans
    def reference_plan_proposal(self, task: dict, binding: dict, repair_round: int = 0) -> dict:
        raise NotImplementedError

    def reservation(self, capability: str, profile: dict) -> dict:
        if capability == "model.generate":
            return usage(model_tokens=profile["max_input_tokens"] + profile["max_output_tokens"], model_requests=1, tool_attempts=0, cpu_ms=0)
        return usage()

    def materialize_plan(self, proposal: dict, task: dict, binding: dict, catalog: dict, profile: dict, *, run_id, plan_id, parent_plan_id, reason_ref, store) -> tuple:
        """Turn a (model or reference) proposal into a gabriel.plan/1 record. Rejects unknown
        capabilities, unknown checks and any plan that omits a mandatory check."""
        validate(proposal, "plan-proposal", ascii_only=False)
        known_checks = {c["check_id"] for c in task["checks"]}
        mandatory = {c["check_id"] for c in task["checks"] if c["mandatory"]}
        covered, nodes, ids = set(), [], set()
        for item in proposal["nodes"]:
            cap = catalog["tools"].get(item["capability_id"])
            if cap is None:
                raise GabrielError(Code.POLICY_DENIED, "plan proposal names an unknown capability " + item["capability_id"])
            if item["node_id"] in ids:
                raise GabrielError(Code.INVALID_SCHEMA, "duplicate node id in proposal " + item["node_id"])
            ids.add(item["node_id"])
            if not set(item["check_ids"]) <= known_checks:
                raise GabrielError(Code.INVALID_SCHEMA, "plan proposal names an unknown check in node " + item["node_id"])
            covered |= set(item["check_ids"])
            slots = self.output_slots.get(item["capability_id"], ["output"])
            nodes.append({"node_id": item["node_id"], "depends_on": list(item["depends_on"]), "capability_id": item["capability_id"],
                          "output_schema_digest": cap["output_schema_digest"], "check_ids": list(item["check_ids"]),
                          "reservation": self.reservation(item["capability_id"], profile), "retry_class": self.retry_class.get(item["capability_id"], "never"),
                          "effect_class": cap["effect_class"], "priority": 0, "max_repair_attempts": 2, "inputs": [],
                          "outputs": [{"output_slot": s, "schema_digest": cap["output_schema_digest"]} for s in slots]})
        missing = mandatory - covered
        if missing:
            raise GabrielError(Code.POLICY_DENIED, "plan omits mandatory check(s): " + ", ".join(sorted(missing)) + "; a plan may not weaken acceptance")
        depth = {}

        def level(nid, seen=()):
            if nid in depth:
                return depth[nid]
            node = next((n for n in nodes if n["node_id"] == nid), None)
            if node is None or nid in seen:
                return 0
            depth[nid] = 1 + max((level(d, seen + (nid,)) for d in node["depends_on"]), default=0)
            return depth[nid]
        for node in nodes:
            node["priority"] = max(0, 64 - level(node["node_id"]))
        plan = {"schema": "gabriel.plan/1", "plan_id": plan_id, "task_id": task["task_id"], "run_id": run_id, "parent_plan_id": parent_plan_id,
                "reason_ref": reason_ref, "nodes": nodes, "max_depth": 12}
        validate(plan, "plan")
        args_by_node = {item["node_id"]: item["args"] for item in proposal["nodes"]}
        return plan, args_by_node

    # ---------------------------------------------------------------- observe port (read side)
    def load_snapshot(self, store, ref) -> tuple:
        snapshot = validate(loads(store.get(ref)), self.snapshot_schema)
        manifest = loads(store.get(snapshot["manifest_ref"]), ascii_only=False)
        return snapshot, manifest

    # ---------------------------------------------------------------- propose port
    def build_prompt(self, goal_text: str, binding: dict, snapshot: dict, manifest: dict, store, *, failure_context: list, round_index: int,
                     memory=None, principal_id: str | None = None, episodes=()) -> tuple:
        """Returns (prompt bytes, context entries, selected observation ids). ``episodes`` are
        past cases the pinned policy selected; a pack may ignore them."""
        raise NotImplementedError

    def normalize_proposal(self, proposal: dict, snapshot: dict, manifest: dict, binding: dict, store, *, task_id, run_id, proposal_ref,
                           protected: set, goal_id: str, policy_digest: str) -> tuple:
        """Returns (candidate record or None, loss list, problem)."""
        raise NotImplementedError

    # ---------------------------------------------------------------- execute port (argument binding)
    def node_args(self, capability: str, declared: dict, helper: ArgsHelper) -> dict:
        raise NotImplementedError

    def target_for(self, capability: str) -> str:
        return "provider" if capability == "model.generate" else "worktree"

    # ---------------------------------------------------------------- evaluate port
    def verifier_id(self, predicate_kind: str) -> str:
        try:
            return self.verifier_ids[predicate_kind]
        except KeyError:
            raise GabrielError(Code.UNSUPPORTED, "no verifier for predicate kind %s in pack %s" % (predicate_kind, self.namespace))


class CompiledTask:
    def __init__(self, task, binding, goal_spec, report, refs, problems):
        self.task, self.binding, self.goal_spec, self.report, self.refs, self.problems = task, binding, goal_spec, report, refs, problems

    @property
    def admissible(self):
        return self.report["admissible"]


def compile_generic(spec: dict, store, *, pack, transform_profile: str, supported_kinds: dict, structural: list, independent_kinds: tuple,
                    base_inputs: list, check_hook=None, task_id, workspace_id, principal_id, grant_id, policy_digest, provider_profile_ref,
                    containment_backend, base_commit, budget, revision=0, oracle_loader=None) -> CompiledTask:
    """Loss-preserving compilation shared by packs without a baseline-run notion: every declared
    check maps to an obligation or is recorded as unsupported; unknown kinds reject; the
    behavioral goal clause is established only by an independent oracle check."""
    import re
    from ..contracts.codec import canonical, digest
    problems = []
    goal_text = spec.get("goal")
    if not isinstance(goal_text, str) or not goal_text.strip():
        raise GabrielError(Code.INVALID_SCHEMA, "task spec needs a non-empty goal")
    allowed = spec.get("allowed_paths") or []
    if not isinstance(allowed, list) or not all(isinstance(p, str) and p.isascii() for p in allowed) or not allowed:
        raise GabrielError(Code.INVALID_SCHEMA, "task spec needs allowed_paths (ASCII relative prefixes)")
    goal_ref = store.put(goal_text.encode("utf8"), "text/plain; charset=utf-8")
    clauses = [{"clause_id": "goal", "source_ref": goal_ref, "byte_start": 0, "byte_end": len(goal_text.encode("utf8")),
                "mapped_obligation_ids": [], "status": "ambiguous", "mandatory": True, "reason": "pending"}]
    check_specs, task_checks, obligations, protected, independent_oracles, seen = [], [], [], [], [], set()

    def obligation(check_spec, spec_ref):
        return {"obligation_id": check_spec["check_id"], "predicate_kind": check_spec["predicate_kind"], "subject_ref": None,
                "verifier_id": supported_kinds[check_spec["predicate_kind"]], "verifier_version": "v1", "verifier_profile_digest": digest(check_spec),
                "mandatory": check_spec["mandatory"], "depends_on": [], "execution_requirement": "observed", "spec_ref": spec_ref, "check_id": check_spec["check_id"]}

    for index, raw in enumerate(spec.get("checks") or []):
        cid, kind = raw.get("check_id"), raw.get("kind")
        clause_id = "check-%s" % (cid or index)
        if not isinstance(cid, str) or cid in seen or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,100}", cid or ""):
            problems.append("invalid or duplicate check id at index %d" % index)
            clauses.append({"clause_id": clause_id, "source_ref": goal_ref, "byte_start": 0, "byte_end": 0, "mapped_obligation_ids": [],
                            "status": "unsupported", "mandatory": True, "reason": "invalid check id"})
            continue
        seen.add(cid)
        if kind not in supported_kinds:
            clauses.append({"clause_id": clause_id, "source_ref": goal_ref, "byte_start": 0, "byte_end": 0, "mapped_obligation_ids": [],
                            "status": "unknown_operation_rejected", "mandatory": bool(raw.get("mandatory", True)), "reason": "unsupported check kind " + str(kind)[:100]})
            continue
        oracle_files = []
        for item in raw.get("oracle_files") or []:
            content = oracle_loader(item["source"]) if oracle_loader else open(item["source"], "rb").read()
            oracle_files.append({"path": item["path"], "artifact_ref": store.put(content, "application/json; charset=utf-8")})
            protected.append(item["path"])
        check_spec = {"check_id": cid, "version": "v1", "mandatory": bool(raw.get("mandatory", True)), "predicate_kind": kind, "argv": list(raw.get("argv") or []),
                      "timeout_ms": int(raw.get("timeout_ms", 120000)), "independent": bool(raw.get("independent", False)),
                      "role": raw.get("role") or "acceptance_only", "oracle_files": oracle_files, "allowed_paths": list(allowed)}
        problem = check_hook(raw, check_spec) if check_hook else None
        if problem:
            clauses.append({"clause_id": clause_id, "source_ref": goal_ref, "byte_start": 0, "byte_end": 0, "mapped_obligation_ids": [],
                            "status": "unsupported", "mandatory": True, "reason": problem[:200]})
            continue
        check_specs.append(check_spec)
        spec_ref = store.put(canonical(check_spec), "application/json")
        task_checks.append({"check_id": cid, "version": "v1", "mandatory": check_spec["mandatory"], "spec_ref": spec_ref})
        obligations.append(obligation(check_spec, spec_ref))
        clauses.append({"clause_id": clause_id, "source_ref": spec_ref, "byte_start": 0, "byte_end": spec_ref["bytes"],
                        "mapped_obligation_ids": [cid], "status": "mapped", "mandatory": check_spec["mandatory"], "reason": "declared check"})
        if check_spec["independent"] and kind in independent_kinds:
            independent_oracles.append(cid)
    for cid, kind in structural + [("output-valid", "owner/output_valid")]:
        if cid in seen:
            continue
        mandatory = cid != "output-valid"
        check_spec = {"check_id": cid, "version": "v1", "mandatory": mandatory, "predicate_kind": kind, "argv": [], "timeout_ms": 0,
                      "independent": True, "role": "structural", "oracle_files": [], "allowed_paths": list(allowed)}
        check_specs.append(check_spec)
        spec_ref = store.put(canonical(check_spec), "application/json")
        task_checks.append({"check_id": cid, "version": "v1", "mandatory": mandatory, "spec_ref": spec_ref})
        obligations.append(obligation(check_spec, spec_ref))
        clauses.append({"clause_id": "structural-" + cid, "source_ref": spec_ref, "byte_start": 0, "byte_end": spec_ref["bytes"],
                        "mapped_obligation_ids": [cid], "status": "mapped", "mandatory": mandatory, "reason": "structural acceptance rule from the blueprint"})
    goal_clause = clauses[0]
    if independent_oracles:
        goal_clause.update(status="mapped", mapped_obligation_ids=list(independent_oracles), reason="behavioral goal is established by the independent oracle check(s)")
    elif spec.get("accept_without_independent_oracle"):
        goal_clause.update(status="excluded_optional", mandatory=False, reason="no independent oracle; the behavioral claim requires user review and is not an acceptance obligation")
    else:
        goal_clause.update(status="unsupported", reason="no independent oracle check establishes the behavioral goal; set accept_without_independent_oracle to proceed with a reviewed proposal")
    unresolved = sum(1 for c in clauses if c["mandatory"] and c["status"] in ("ambiguous", "unsupported", "unknown_operation_rejected"))
    acceptance_ref = store.put(canonical({"checks": check_specs, "allowed_paths": allowed, "goal_clause": goal_clause["status"]}), "application/json")
    task = {"schema": "gabriel.task/1", "task_id": task_id, "workspace_id": workspace_id, "principal_id": principal_id, "goal_ref": goal_ref,
            "acceptance_ref": acceptance_ref, "grant_id": grant_id, "budget_ceiling": budget, "base_inputs": list(base_inputs), "checks": task_checks[:64],
            "policy_digest": policy_digest, "task_spec_revision": revision}
    validate(task, "task")
    binding = {"schema": "gabriel.task-binding/1", "domain_namespace": pack.namespace, "pack_id": pack.pack_id, "pack_version": pack.pack_version,
               "provider_profile_ref": provider_profile_ref, "containment_backend": containment_backend, "repository_path": str(spec["repository"]),
               "base_commit": base_commit, "allowed_paths": allowed, "check_specs": check_specs, "max_plan_versions": int(spec.get("max_plan_versions", 4)),
               "max_repairs": int(spec.get("max_repairs", 2)), "owner_time_basis": "host_clock", "planner_mode": spec.get("planner_mode", "model")}
    validate(binding, "task-binding")
    goal_spec = {"schema": "gabriel.goal-spec/1", "goal_id": task_id + "-goal-r%d" % revision, "task_id": task_id, "task_spec_revision": revision,
                 "domain_namespace": pack.namespace, "pack_id": pack.pack_id, "pack_version": pack.pack_version, "source_goal_ref": goal_ref,
                 "source_acceptance_ref": acceptance_ref, "obligations": obligations[:64], "transform_profile_id": transform_profile}
    validate(goal_spec, "goal-spec")
    goal_spec_ref = store.put(canonical(goal_spec), "application/json")
    report = {"schema": "gabriel.compilation-report/1", "report_id": task_id + "-compilation-r%d" % revision, "task_id": task_id,
              "task_spec_revision": revision, "goal_spec_ref": goal_spec_ref, "clauses": clauses, "raw_response_ref": None,
              "transform_profile_id": transform_profile, "unresolved_mandatory_count": unresolved, "admissible": unresolved == 0 and not problems}
    validate(report, "compilation-report")
    refs = {"goal_spec_ref": goal_spec_ref, "compilation_report_ref": store.put(canonical(report), "application/json"),
            "binding_ref": store.put(canonical(binding), "application/json"), "protected_paths": protected}
    return CompiledTask(task, binding, goal_spec, report, refs, problems)
