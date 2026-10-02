"""Software (repository repair) domain pack: six ports behind the owner/broker.

Compile: structured task input -> GoalSpec + loss-preserving CompilationReport.
Observe: pinned worktree -> immutable snapshot (file manifest, lexical Python
structure, test presence; behavior is explicitly not observed).
Evaluate: declared checks run inside the containment backend and produce
retained witnesses; verifiers turn witnesses into assessments.
Propose: context manifest + prompt -> model request; strict normalization of
the patch proposal (unknown kinds reject; create/modify/delete are distinct
identities bound to the expected prior digest).
Execute: contained patch application with preconditions; partial failures
are recorded and reconciled by read-back.
Read back: fresh snapshot and diff; only this advances observed state.
"""
from __future__ import annotations

import ast
import hashlib
import re
import time

from ...contracts.codec import CodecError, canonical, digest, dumps_utf8, loads, sha256_hex, is_digest
from ...contracts.errors import Code, GabrielError
from ...contracts.schemas import schema_digest, validate
from ...kernel import Artifact, candidate as kernel_candidate
from ...models import ModelGenerateTool, build_model_request
from ...tools import fs
from ...tools.registry import ToolRegistry
from ...workers.isolation import RunSpec
from ...workers.supervisor import ToolOutcome

NAMESPACE = "software"
PACK_ID = "software-repair"
PACK_VERSION = "0.1.0"
EXTRACTION_PROFILE = "python-ast-lexical-v1"
TRANSFORM_PROFILE = "software-compile-v1"
SUPPORTED_KINDS = {"software/test_passed": "software.test_passed", "software/diff_in_scope": "software.diff_in_scope",
                   "software/base_commit_pinned": "software.base_commit_pinned", "software/checks_intact": "software.checks_intact",
                   "software/no_secrets": "software.no_secrets", "owner/output_valid": "owner.output_valid"}
STRUCTURAL = [("scope", "software/diff_in_scope"), ("base-commit", "software/base_commit_pinned"),
              ("checks-intact", "software/checks_intact"), ("no-secrets", "software/no_secrets")]
SECRET_PATTERNS = [("aws_access_key", re.compile(rb"AKIA[0-9A-Z]{16}")), ("private_key_block", re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
                   ("bearer_like_token", re.compile(rb"(?i)(api[_-]?key|secret|token)\s*[=:]\s*['\"][A-Za-z0-9_\-]{24,}['\"]")),
                   ("openai_style_key", re.compile(rb"sk-[A-Za-z0-9]{20,}"))]
PROMPT_SOURCE_BUDGET = 48 * 1024
MAX_FILE_BYTES = 1 << 20
OUTPUT_SLOTS = {"software.observe": ["snapshot"], "software.run_check": ["check_result", "witness"],
                "model.generate": ["model_output", "raw_response", "request", "envelope"],
                "software.apply_patch": ["apply_report"], "software.read_back": ["snapshot", "read_back"],
                "software.review": ["review", "patch"]}
RETRY_CLASS = {"software.observe": "read_retry", "software.run_check": "reconcile_before_retry", "model.generate": "target_idempotent_retry",
               "software.apply_patch": "reconcile_before_retry", "software.read_back": "read_retry", "software.review": "read_retry"}


def _usage(**over):
    base = {"model_tokens": 0, "model_requests": 0, "tool_attempts": 1, "cpu_ms": 60000, "elapsed_ms": 0, "artifact_bytes": 4 << 20,
            "currency_micro_units": 0, "currency": "EUR", "accounting_status": "confirmed"}
    base.update(over)
    return base


def _reservation(capability, profile):
    if capability == "model.generate":
        return _usage(model_tokens=profile["max_input_tokens"] + profile["max_output_tokens"], model_requests=1, tool_attempts=0, cpu_ms=0)
    if capability == "software.run_check":
        return _usage(cpu_ms=300000)
    return _usage()


# ===================================================================== compile port

class CompiledTask:
    def __init__(self, task, binding, goal_spec, report, refs, problems):
        self.task, self.binding, self.goal_spec, self.report, self.refs, self.problems = task, binding, goal_spec, report, refs, problems

    @property
    def admissible(self):
        return self.report["admissible"]


def compile_task(spec: dict, store, *, task_id, workspace_id, principal_id, grant_id, policy_digest, provider_profile_ref,
                 containment_backend, base_commit, budget, revision=0, oracle_loader=None) -> CompiledTask:
    """Loss-preserving compilation of the structured task input."""
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
    check_specs, task_checks, obligations, protected = [], [], [], []
    seen = set()
    independent_oracles = []
    for index, raw in enumerate(spec.get("checks") or []):
        cid = raw.get("check_id")
        kind = raw.get("kind")
        clause_id = "check-%s" % (cid or index)
        if not isinstance(cid, str) or cid in seen or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,100}", cid or ""):
            problems.append("invalid or duplicate check id at index %d" % index)
            clauses.append({"clause_id": clause_id, "source_ref": goal_ref, "byte_start": 0, "byte_end": 0, "mapped_obligation_ids": [],
                            "status": "unsupported", "mandatory": True, "reason": "invalid check id"})
            continue
        seen.add(cid)
        if kind not in SUPPORTED_KINDS:
            clauses.append({"clause_id": clause_id, "source_ref": goal_ref, "byte_start": 0, "byte_end": 0, "mapped_obligation_ids": [],
                            "status": "unknown_operation_rejected", "mandatory": bool(raw.get("mandatory", True)),
                            "reason": "unsupported check kind " + str(kind)[:100]})
            continue
        argv = raw.get("argv") or []
        if kind == "software/test_passed" and (not argv or not all(isinstance(a, str) and a.isascii() for a in argv)):
            clauses.append({"clause_id": clause_id, "source_ref": goal_ref, "byte_start": 0, "byte_end": 0, "mapped_obligation_ids": [],
                            "status": "unsupported", "mandatory": True, "reason": "test check needs an ASCII argv"})
            continue
        oracle_files = []
        for item in raw.get("oracle_files") or []:
            content = oracle_loader(item["source"]) if oracle_loader else open(item["source"], "rb").read()
            oracle_files.append({"path": item["path"], "artifact_ref": store.put(content, "text/plain; charset=utf-8")})
            protected.append(item["path"])
        role = raw.get("role") or ("acceptance_only" if raw.get("independent") else "baseline_and_acceptance")
        check_spec = {"check_id": cid, "version": "v1", "mandatory": bool(raw.get("mandatory", True)), "predicate_kind": kind,
                      "argv": list(argv), "timeout_ms": int(raw.get("timeout_ms", 120000)), "independent": bool(raw.get("independent", False)),
                      "role": role, "oracle_files": oracle_files, "allowed_paths": list(allowed)}
        check_specs.append(check_spec)
        spec_ref = store.put(canonical(check_spec), "application/json")
        task_checks.append({"check_id": cid, "version": "v1", "mandatory": check_spec["mandatory"], "spec_ref": spec_ref})
        obligations.append({"obligation_id": cid, "predicate_kind": kind, "subject_ref": None, "verifier_id": SUPPORTED_KINDS[kind],
                            "verifier_version": "v1", "verifier_profile_digest": digest(check_spec), "mandatory": check_spec["mandatory"],
                            "depends_on": [], "execution_requirement": "observed", "spec_ref": spec_ref, "check_id": cid})
        clauses.append({"clause_id": clause_id, "source_ref": spec_ref, "byte_start": 0, "byte_end": spec_ref["bytes"],
                        "mapped_obligation_ids": [cid], "status": "mapped", "mandatory": check_spec["mandatory"], "reason": "declared check"})
        if check_spec["independent"] and kind == "software/test_passed":
            independent_oracles.append(cid)
        if role == "baseline_and_acceptance" and kind == "software/test_passed":
            bid = "baseline:" + cid
            bspec = dict(check_spec, check_id=bid, mandatory=False, role="baseline_only", independent=False)
            check_specs.append(bspec)
            bref = store.put(canonical(bspec), "application/json")
            task_checks.append({"check_id": bid, "version": "v1", "mandatory": False, "spec_ref": bref})
            obligations.append({"obligation_id": bid, "predicate_kind": kind, "subject_ref": None, "verifier_id": SUPPORTED_KINDS[kind],
                                "verifier_version": "v1", "verifier_profile_digest": digest(bspec), "mandatory": False, "depends_on": [],
                                "execution_requirement": "observed", "spec_ref": bref, "check_id": bid})
    for cid, kind in STRUCTURAL + [("output-valid", "owner/output_valid")]:
        if cid in seen:
            continue
        mandatory = cid != "output-valid"
        check_spec = {"check_id": cid, "version": "v1", "mandatory": mandatory, "predicate_kind": kind, "argv": [], "timeout_ms": 0,
                      "independent": True, "role": "structural", "oracle_files": [], "allowed_paths": list(allowed)}
        check_specs.append(check_spec)
        spec_ref = store.put(canonical(check_spec), "application/json")
        task_checks.append({"check_id": cid, "version": "v1", "mandatory": mandatory, "spec_ref": spec_ref})
        obligations.append({"obligation_id": cid, "predicate_kind": kind, "subject_ref": None, "verifier_id": SUPPORTED_KINDS[kind],
                            "verifier_version": "v1", "verifier_profile_digest": digest(check_spec), "mandatory": mandatory, "depends_on": [],
                            "execution_requirement": "observed", "spec_ref": spec_ref, "check_id": cid})
        clauses.append({"clause_id": "structural-" + cid, "source_ref": spec_ref, "byte_start": 0, "byte_end": spec_ref["bytes"],
                        "mapped_obligation_ids": [cid], "status": "mapped", "mandatory": mandatory, "reason": "structural acceptance rule from the blueprint"})
    goal_clause = clauses[0]
    if independent_oracles:
        goal_clause.update(status="mapped", mapped_obligation_ids=list(independent_oracles),
                           reason="behavioral goal is established by the independent oracle check(s)")
    elif spec.get("accept_without_independent_oracle"):
        goal_clause.update(status="excluded_optional", mandatory=False,
                           reason="no independent oracle; the behavioral claim requires user review and is not an acceptance obligation")
    else:
        goal_clause.update(status="unsupported", reason="no independent oracle check establishes the behavioral goal; set accept_without_independent_oracle to proceed with a reviewed proposal")
    unresolved = sum(1 for c in clauses if c["mandatory"] and c["status"] in ("ambiguous", "unsupported", "unknown_operation_rejected"))
    acceptance = {"checks": [c for c in check_specs], "allowed_paths": allowed, "goal_clause": goal_clause["status"]}
    acceptance_ref = store.put(canonical(acceptance), "application/json")
    pin = {"schema": "gabriel.software-repository-pin/1", "repository_path": str(spec["repository"]), "base_commit": base_commit, "pinned_by": principal_id}
    validate(pin, "software-repository-pin")
    task = {"schema": "gabriel.task/1", "task_id": task_id, "workspace_id": workspace_id, "principal_id": principal_id, "goal_ref": goal_ref,
            "acceptance_ref": acceptance_ref, "grant_id": grant_id, "budget_ceiling": budget,
            "base_inputs": [store.put(canonical(pin), "application/json")], "checks": task_checks[:64], "policy_digest": policy_digest,
            "task_spec_revision": revision}
    validate(task, "task")
    binding = {"schema": "gabriel.task-binding/1", "domain_namespace": NAMESPACE, "pack_id": PACK_ID, "pack_version": PACK_VERSION,
               "provider_profile_ref": provider_profile_ref, "containment_backend": containment_backend, "repository_path": str(spec["repository"]),
               "base_commit": base_commit, "allowed_paths": allowed, "check_specs": check_specs, "max_plan_versions": int(spec.get("max_plan_versions", 4)),
               "max_repairs": int(spec.get("max_repairs", 2)), "owner_time_basis": "host_clock",
               "planner_mode": spec.get("planner_mode", "model")}
    validate(binding, "task-binding")
    goal_spec = {"schema": "gabriel.goal-spec/1", "goal_id": task_id + "-goal-r%d" % revision, "task_id": task_id, "task_spec_revision": revision,
                 "domain_namespace": NAMESPACE, "pack_id": PACK_ID, "pack_version": PACK_VERSION, "source_goal_ref": goal_ref,
                 "source_acceptance_ref": acceptance_ref, "obligations": obligations[:64], "transform_profile_id": TRANSFORM_PROFILE}
    validate(goal_spec, "goal-spec")
    goal_spec_ref = store.put(canonical(goal_spec), "application/json")
    report = {"schema": "gabriel.compilation-report/1", "report_id": task_id + "-compilation-r%d" % revision, "task_id": task_id,
              "task_spec_revision": revision, "goal_spec_ref": goal_spec_ref, "clauses": clauses, "raw_response_ref": None,
              "transform_profile_id": TRANSFORM_PROFILE, "unresolved_mandatory_count": unresolved,
              "admissible": unresolved == 0 and not problems}
    validate(report, "compilation-report")
    refs = {"goal_spec_ref": goal_spec_ref, "compilation_report_ref": store.put(canonical(report), "application/json"),
            "binding_ref": store.put(canonical(binding), "application/json"), "protected_paths": protected}
    return CompiledTask(task, binding, goal_spec, report, refs, problems)


# ===================================================================== plans

def reference_plan_proposal(task: dict, binding: dict, repair_round: int = 0) -> dict:
    """Deterministic reference proposal: the planner may return it verbatim."""
    suffix = "" if repair_round == 0 else "-r%d" % repair_round
    specs = {s["check_id"]: s for s in binding["check_specs"]}
    nodes = [{"node_id": "observe", "capability_id": "software.observe", "depends_on": [], "check_ids": ["output-valid"],
              "purpose": "pin and observe the worktree", "args": {}}]
    baseline_ids = []
    for s in binding["check_specs"]:
        if s["role"] == "baseline_only":
            nid = "baseline-" + s["check_id"].split(":", 1)[1]
            baseline_ids.append(nid)
            nodes.append({"node_id": nid, "capability_id": "software.run_check", "depends_on": ["observe"], "check_ids": [s["check_id"]],
                          "purpose": "baseline run of " + s["check_id"], "args": {"check_id": s["check_id"]}})
    observe_id = "observe"
    if repair_round > 0:
        # A repair round starts from a fresh observation: partial effects of the failed
        # round are read back before any new proposal binds file identities.
        observe_id = "observe" + suffix
        nodes.append({"node_id": observe_id, "capability_id": "software.observe", "depends_on": [], "check_ids": ["output-valid"],
                      "purpose": "re-observe the worktree after the failed round", "args": {}})
    nodes.append({"node_id": "propose" + suffix, "capability_id": "model.generate", "depends_on": [observe_id] + baseline_ids,
                  "check_ids": ["output-valid"], "purpose": "propose a patch", "args": {"role": "worker"}})
    nodes.append({"node_id": "apply" + suffix, "capability_id": "software.apply_patch", "depends_on": ["propose" + suffix],
                  "check_ids": ["output-valid"], "purpose": "apply the proposed patch", "args": {"from_node": "propose" + suffix}})
    nodes.append({"node_id": "read-back" + suffix, "capability_id": "software.read_back", "depends_on": ["apply" + suffix],
                  "check_ids": ["output-valid"], "purpose": "observe the changed tree", "args": {}})
    for s in binding["check_specs"]:
        if s["predicate_kind"] == "software/test_passed" and s["role"] in ("baseline_and_acceptance", "acceptance_only"):
            nodes.append({"node_id": "verify-%s%s" % (s["check_id"], suffix), "capability_id": "software.run_check", "depends_on": ["read-back" + suffix],
                          "check_ids": [s["check_id"]], "purpose": "acceptance run of " + s["check_id"], "args": {"check_id": s["check_id"]}})
    structural = [cid for cid, _ in STRUCTURAL if cid in specs]
    nodes.append({"node_id": "review" + suffix, "capability_id": "software.review", "depends_on": ["read-back" + suffix],
                  "check_ids": structural, "purpose": "scope, identity and secret review of the diff", "args": {}})
    return {"nodes": nodes, "rationale": "reference repair plan (round %d)" % repair_round}


def materialize_plan(proposal: dict, task: dict, binding: dict, catalog: dict, profile: dict, *, run_id, plan_id, parent_plan_id, reason_ref, store) -> dict:
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
        slots = OUTPUT_SLOTS.get(item["capability_id"], ["output"])
        nodes.append({"node_id": item["node_id"], "depends_on": list(item["depends_on"]), "capability_id": item["capability_id"],
                      "output_schema_digest": cap["output_schema_digest"], "check_ids": list(item["check_ids"]),
                      "reservation": _reservation(item["capability_id"], profile), "retry_class": RETRY_CLASS.get(item["capability_id"], "never"),
                      "effect_class": cap["effect_class"], "priority": 0, "max_repair_attempts": 2, "inputs": [],
                      "outputs": [{"output_slot": s, "schema_digest": cap["output_schema_digest"]} for s in slots]})
    missing = mandatory - covered
    if missing:
        raise GabrielError(Code.POLICY_DENIED, "plan omits mandatory check(s): " + ", ".join(sorted(missing)) + "; a plan may not weaken acceptance")
    # priority: earlier topological levels first (deterministic)
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


# ===================================================================== observation helpers

def _python_structure(root: fs.ContainedRoot, manifest: dict, allowed) -> dict:
    structure = {}
    for path, entry in sorted(manifest.items()):
        if entry["kind"] != "file" or not path.endswith(".py") or not fs.path_in_scope(path, allowed) or entry["bytes"] > MAX_FILE_BYTES:
            continue
        try:
            tree = ast.parse(root.read(path).decode("utf8"))
        except (SyntaxError, UnicodeDecodeError, GabrielError):
            structure[path] = {"parse": "failed"}
            continue
        functions = sorted(n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))
        classes = sorted(n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef))
        structure[path] = {"parse": "ok", "functions": functions, "classes": classes}
    return structure


RETAINED_SOURCE_SUFFIXES = (".py", ".md", ".txt", ".cfg", ".toml", ".ini")
RETAINED_SOURCE_BUDGET = 2 << 20


def _retain_sources(root: fs.ContainedRoot, manifest: dict, allowed, store) -> int:
    """Retain the bytes of in-scope text files in the artifact store (the inputs a proposal
    edits), bounded by ``RETAINED_SOURCE_BUDGET``. The manifest already carries every digest; the
    worker prompt reads the content back from the store by that digest, so an observation
    that does not retain a file leaves the model without it. Returns the retained byte count."""
    retained = 0
    for path, entry in sorted(manifest.items()):
        if entry["kind"] != "file" or not path.endswith(RETAINED_SOURCE_SUFFIXES) or not fs.path_in_scope(path, allowed):
            continue
        if entry["bytes"] > MAX_FILE_BYTES or retained + entry["bytes"] > RETAINED_SOURCE_BUDGET:
            continue
        try:
            data = root.read(path)
        except GabrielError:
            continue
        if sha256_hex(data) != entry["sha256"]:
            continue  # changed under us; the next observation sees the new identity
        store.put(data, "text/plain; charset=utf-8")
        retained += len(data)
    return retained


def take_snapshot(worktree, binding: dict, store, frontier: int) -> tuple[dict, dict]:
    manifest = worktree.manifest()
    with fs.ContainedRoot(str(worktree.path)) as root:
        structure = _python_structure(root, manifest, binding["allowed_paths"])
        _retain_sources(root, manifest, binding["allowed_paths"], store)
    manifest_ref = store.put(dumps_utf8(manifest), "application/json; charset=utf-8")
    tests = sorted(p for p in manifest if re.search(r"(^|/)(test_[^/]*\.py|[^/]*_test\.py)$", p))
    snapshot = {"schema": "gabriel.software-snapshot/1", "worktree_id": "worktree", "base_commit": worktree.base_commit,
                "head_commit": worktree.head(), "manifest_ref": manifest_ref, "tree_digest": digest(manifest),
                "structure_ref": store.put(dumps_utf8(structure), "application/json; charset=utf-8"), "extraction_profile": EXTRACTION_PROFILE,
                "test_files": tests[:4096], "file_count": sum(1 for e in manifest.values() if e["kind"] == "file"),
                "symlink_count": sum(1 for e in manifest.values() if e["kind"] == "symlink"),
                "coverage": {"observes": ["file bytes and digests", "lexical Python functions and classes", "test file presence by name"],
                             "does_not_observe": ["behavior", "test outcomes", "non-Python structure", "external state"]},
                "observed_frontier": frontier}
    validate(snapshot, "software-snapshot")
    return snapshot, manifest


# ===================================================================== tools

class ObserveTool:
    def __call__(self, intent, args, ctx):
        snapshot, _ = take_snapshot(ctx.worktree, ctx.binding, ctx.store, ctx.owner.anchor()["sequence"])
        d = ctx.registry.tool(intent["capability_id"])[0]["output_schema_digest"]
        return ToolOutcome(outputs=[("snapshot", canonical(snapshot), "application/json", d)])

    def reconcile(self, intent, attempt, ctx):
        return "confirmed_not_executed", canonical({"read_only": True})


class RunCheckTool:
    def __init__(self, backend_resolver):
        self.backend_resolver = backend_resolver

    def __call__(self, intent, args, ctx):
        spec = next((s for s in ctx.binding["check_specs"] if s["check_id"] == args["check_id"]), None)
        if spec is None:
            raise GabrielError(Code.INVALID_SCHEMA, "unknown check " + str(args.get("check_id")))
        if spec["predicate_kind"] != "software/test_passed" or not spec["argv"]:
            raise GabrielError(Code.UNSUPPORTED, "check %s is not an executable test check" % spec["check_id"])
        backend = ctx.backend or self.backend_resolver()
        oracle_states, previous = [], {}
        pre = ctx.worktree.tree_digest()
        with fs.ContainedRoot(str(ctx.worktree.path)) as root:
            for item in spec["oracle_files"]:
                content = ctx.store.get(item["artifact_ref"])
                if root.exists(item["path"]):
                    previous[item["path"]] = root.read(item["path"])
                root.write(item["path"], content)
                oracle_states.append({"path": item["path"], "sha256": sha256_hex(content)})
        witness = backend.run(RunSpec(argv=list(spec["argv"]), worktree=str(ctx.worktree.path), timeout_ms=spec["timeout_ms"],
                                      max_output_bytes=1 << 20, marker="gabriel-" + intent["attempt_id"]))
        with fs.ContainedRoot(str(ctx.worktree.path)) as root:
            for state in oracle_states:
                try:
                    state["intact_after_run"] = root.digest(state["path"]) == state["sha256"]
                except GabrielError:
                    state["intact_after_run"] = False
                # The oracle is installed only for the run; it is never part of the deliverable.
                try:
                    if state["path"] in previous:
                        root.write(state["path"], previous[state["path"]])
                    elif root.exists(state["path"]):
                        root.delete(state["path"])
                except GabrielError:
                    pass
        post = ctx.worktree.tree_digest()
        stdout_ref = ctx.store.put(witness.stdout.captured, "application/octet-stream")
        stderr_ref = ctx.store.put(witness.stderr.captured, "application/octet-stream")
        witness_record = validate(witness.to_record(stdout_ref, stderr_ref), "run-witness")
        witness_ref = ctx.store.put(canonical(witness_record), "application/json")
        if witness.start_failure or witness.timed_out:
            outcome = "inconclusive"
        elif witness.exit_code == 0 and all(s["intact_after_run"] for s in oracle_states):
            outcome = "passed"
        else:
            outcome = "failed"
        result = {"schema": "gabriel.software-check-result/1", "check_id": spec["check_id"], "role": "baseline" if spec["role"] == "baseline_only" else "acceptance",
                  "argv": list(spec["argv"]), "exit_code": witness.exit_code, "timed_out": witness.timed_out, "start_failure": witness.start_failure,
                  "outcome": outcome, "witness_ref": witness_ref, "pre_tree_digest": pre, "post_tree_digest": post, "oracle_files": oracle_states,
                  "backend_kind": witness.backend_kind, "containment": witness.backend_kind == "linux_namespace"}
        validate(result, "software-check-result")
        d = ctx.registry.tool(intent["capability_id"])[0]["output_schema_digest"]
        return ToolOutcome(outputs=[("check_result", canonical(result), "application/json", d), ("witness", canonical(witness_record), "application/json", d)],
                           exit_code=witness.exit_code, effect_outcome="acknowledged_success")

    def reconcile(self, intent, attempt, ctx):
        snapshot, _ = take_snapshot(ctx.worktree, ctx.binding, ctx.store, ctx.owner.anchor()["sequence"])
        return "confirmed_failure", canonical({"read_back_tree_digest": snapshot["tree_digest"], "note": "check run without retained witness; rerun under a new attempt"})


class ApplyPatchTool:
    def __call__(self, intent, args, ctx):
        patch = validate(loads(ctx.store.get(args["patch_ref"])), "software-patch")
        pre = ctx.worktree.tree_digest()
        if pre != patch["base_tree_digest"]:
            raise GabrielError(Code.STALE_EVIDENCE, "worktree differs from the patch's base snapshot; reread and propose again")
        applied, failed_at, reason = [], None, None
        protected = set(ctx.extras.get("protected_paths", []))
        with fs.ContainedRoot(str(ctx.worktree.path)) as root:
            for index, op in enumerate(patch["operations"]):
                try:
                    if not fs.path_in_scope(op["path"], ctx.binding["allowed_paths"]) or op["path"] in protected:
                        raise GabrielError(Code.POLICY_DENIED, "path outside the admitted scope or protected: " + op["path"])
                    exists = root.exists(op["path"])
                    if op["kind"] == "create":
                        if exists:
                            raise GabrielError(Code.STALE_EVIDENCE, "create target already exists: " + op["path"])
                        content = ctx.store.get(op["content_ref"])
                        applied.append({"kind": "create", "path": op["path"], "result_sha256": root.write(op["path"], content)})
                    elif op["kind"] == "modify":
                        if not exists or root.digest(op["path"]) != op["expected_sha256"]:
                            raise GabrielError(Code.STALE_EVIDENCE, "file identity mismatch for " + op["path"])
                        content = ctx.store.get(op["content_ref"])
                        applied.append({"kind": "modify", "path": op["path"], "result_sha256": root.write(op["path"], content)})
                    elif op["kind"] == "delete":
                        if not exists or root.digest(op["path"]) != op["expected_sha256"]:
                            raise GabrielError(Code.STALE_EVIDENCE, "file identity mismatch for " + op["path"])
                        root.delete(op["path"])
                        applied.append({"kind": "delete", "path": op["path"], "result_sha256": None})
                    else:
                        raise GabrielError(Code.INVALID_SCHEMA, "unknown operation kind")
                    if ctx.extras.get("crash_between_writes") and index == 0 and len(patch["operations"]) > 1:
                        ctx.extras["crash_between_writes"]()
                except GabrielError as exc:
                    failed_at, reason = index, exc.message[:500]
                    break
        post = ctx.worktree.tree_digest()
        report = {"schema": "gabriel.software-apply-report/1", "patch_ref": args["patch_ref"], "applied": applied, "failed_at": failed_at,
                  "reason": reason, "pre_tree_digest": pre, "post_tree_digest": post, "complete": failed_at is None}
        validate(report, "software-apply-report")
        d = ctx.registry.tool(intent["capability_id"])[0]["output_schema_digest"]
        if failed_at is not None:
            return ToolOutcome(status="failed", exit_code=1, effect_outcome="acknowledged_failure",
                               outputs=[("apply_report", canonical(report), "application/json", d)])
        return ToolOutcome(outputs=[("apply_report", canonical(report), "application/json", d)], effect_outcome="acknowledged_success")

    def reconcile(self, intent, attempt, ctx):
        patch = validate(loads(ctx.store.get(ctx.args["patch_ref"])), "software-patch")
        tree = ctx.worktree.tree_digest()
        if tree == patch["base_tree_digest"]:
            return "confirmed_not_executed", canonical({"tree_digest": tree, "equals_base": True})
        with fs.ContainedRoot(str(ctx.worktree.path)) as root:
            states = []
            for op in patch["operations"]:
                if op["kind"] == "delete":
                    states.append(not root.exists(op["path"]))
                else:
                    states.append(root.exists(op["path"]) and root.digest(op["path"]) == op["content_sha256"])
        if all(states):
            return "confirmed_success", canonical({"tree_digest": tree, "all_operations_reflected": True})
        return "confirmed_failure", canonical({"tree_digest": tree, "operations_reflected": states})


class ReadBackTool:
    def __call__(self, intent, args, ctx):
        pre = validate(loads(ctx.store.get(args["pre_snapshot_ref"])), "software-snapshot")
        pre_manifest = loads(ctx.store.get(pre["manifest_ref"]), ascii_only=False)
        snapshot, manifest = take_snapshot(ctx.worktree, ctx.binding, ctx.store, ctx.owner.anchor()["sequence"])
        changed = sorted(p for p in set(pre_manifest) | set(manifest)
                         if pre_manifest.get(p, {}).get("sha256") != manifest.get(p, {}).get("sha256"))
        out_of_scope = [p for p in changed if not fs.path_in_scope(p, ctx.binding["allowed_paths"]) and not p.endswith(".pyc") and "__pycache__" not in p]
        record = {"schema": "gabriel.read-back/1", "read_back_id": "readback-" + intent["attempt_id"], "task_id": intent["task_id"], "run_id": intent["run_id"],
                  "intent_id": intent["intent_id"], "attempt_id": intent["attempt_id"], "pre_snapshot_ref": args["pre_snapshot_ref"],
                  "post_snapshot_ref": ctx.store.put(canonical(snapshot), "application/json"), "changed_resources": changed[:4096],
                  "invalidated_observation_ids": ["obs-" + sha256_hex(p.encode("utf8"))[:40] for p in changed][:4096], "postcondition_profile_id": "software-readback-v1",
                  "outcome": "confirmed" if not out_of_scope else "mismatch",
                  "detail": "changes confined to the admitted scope" if not out_of_scope else "out-of-scope changes: " + ",".join(out_of_scope)[:400]}
        validate(record, "read-back")
        d = ctx.registry.tool(intent["capability_id"])[0]["output_schema_digest"]
        return ToolOutcome(outputs=[("snapshot", canonical(snapshot), "application/json", d), ("read_back", canonical(record), "application/json", d)])

    def reconcile(self, intent, attempt, ctx):
        return "confirmed_not_executed", canonical({"read_only": True})


class ReviewTool:
    def __call__(self, intent, args, ctx):
        protected = set(ctx.extras.get("protected_paths", []))
        changed = ctx.worktree.changed_paths()
        changed = [p for p in changed if "__pycache__" not in p and not p.endswith(".pyc")]
        patch_bytes = ctx.worktree.patch()
        secrets, large = [], []
        with fs.ContainedRoot(str(ctx.worktree.path)) as root:
            for path in changed:
                if not root.exists(path):
                    continue
                try:
                    data = root.read(path)
                except GabrielError:
                    large.append(path)
                    continue
                if len(data) > MAX_FILE_BYTES or b"\x00" in data:
                    large.append(path)
                for name, pattern in SECRET_PATTERNS:
                    if pattern.search(data):
                        secrets.append({"path": path, "pattern": name})
        review = {"schema": "gabriel.software-review/1", "base_commit": ctx.worktree.base_commit, "head_commit": ctx.worktree.head(),
                  "changed_paths": changed, "out_of_scope_paths": [p for p in changed if not fs.path_in_scope(p, ctx.binding["allowed_paths"])],
                  "protected_modified": [p for p in changed if p in protected], "secrets_found": secrets, "binary_or_large": large,
                  "patch_ref": ctx.store.put(patch_bytes, "text/x-diff; charset=utf-8"), "patch_bytes": len(patch_bytes),
                  "tree_digest": ctx.worktree.tree_digest()}
        validate(review, "software-review")
        d = ctx.registry.tool(intent["capability_id"])[0]["output_schema_digest"]
        return ToolOutcome(outputs=[("review", canonical(review), "application/json", d), ("patch", patch_bytes, "text/x-diff; charset=utf-8", d)])

    def reconcile(self, intent, attempt, ctx):
        return "confirmed_not_executed", canonical({"read_only": True})


# ===================================================================== verifiers
# verify(check_spec, outputs, ctx) -> (outcome, evidence dict). outputs: {slot: parsed record or bytes}

def _record(outputs, slot):
    value = outputs.get(slot)
    if isinstance(value, (bytes, bytearray)):
        return loads(value, ascii_only=False)
    return value


class TestPassedVerifier:
    def __call__(self, spec, outputs, ctx):
        result = _record(outputs, "check_result")
        if result is None or result.get("check_id") != spec["check_id"]:
            return "not_run", {"reason": "no retained check result for " + spec["check_id"]}
        witness = _record(outputs, "witness")
        if result["outcome"] == "inconclusive":
            return "inconclusive", {"reason": result["start_failure"] or "timed out", "witness": witness}
        intact = all(o["intact_after_run"] for o in result["oracle_files"])
        if not intact:
            return "failed", {"reason": "oracle files were modified during the run", "oracle_files": result["oracle_files"]}
        return ("passed" if result["exit_code"] == 0 else "failed"), {"exit_code": result["exit_code"], "argv": result["argv"],
                                                                      "witness_ref": result["witness_ref"], "backend": result["backend_kind"],
                                                                      "containment": result["containment"]}


class DiffInScopeVerifier:
    def __call__(self, spec, outputs, ctx):
        review = _record(outputs, "review")
        if review is None:
            return "not_run", {"reason": "no review"}
        return ("passed" if not review["out_of_scope_paths"] else "failed"), {"changed_paths": review["changed_paths"], "out_of_scope_paths": review["out_of_scope_paths"]}


class BaseCommitPinnedVerifier:
    def __call__(self, spec, outputs, ctx):
        review = _record(outputs, "review")
        if review is None:
            return "not_run", {"reason": "no review"}
        ok = review["base_commit"] == ctx.binding["base_commit"] == review["head_commit"]
        return ("passed" if ok else "failed"), {"base_commit": review["base_commit"], "head_commit": review["head_commit"], "admitted": ctx.binding["base_commit"]}


class ChecksIntactVerifier:
    def __call__(self, spec, outputs, ctx):
        review = _record(outputs, "review")
        if review is None:
            return "not_run", {"reason": "no review"}
        return ("passed" if not review["protected_modified"] else "failed"), {"protected_modified": review["protected_modified"]}


class NoSecretsVerifier:
    def __call__(self, spec, outputs, ctx):
        review = _record(outputs, "review")
        if review is None:
            return "not_run", {"reason": "no review"}
        ok = not review["secrets_found"] and not review["binary_or_large"]
        return ("passed" if ok else "failed"), {"secrets_found": review["secrets_found"], "binary_or_large": review["binary_or_large"]}


class OutputValidVerifier:
    """Structural: every declared output parses as the record its slot promises."""
    SLOT_SCHEMAS = {"snapshot": "software-snapshot", "check_result": "software-check-result", "witness": "run-witness",
                    "apply_report": "software-apply-report", "read_back": "read-back", "review": "software-review",
                    "request": "model-request", "envelope": None, "raw_response": None, "patch": None, "model_output": None}

    def __call__(self, spec, outputs, ctx):
        problems = []
        for slot, value in outputs.items():
            name = self.SLOT_SCHEMAS.get(slot)
            if name is None:
                continue
            try:
                validate(_record(outputs, slot), name, ascii_only=False)
            except (GabrielError, CodecError) as exc:
                problems.append("%s: %s" % (slot, str(exc)[:200]))
        if "apply_report" in outputs and not _record(outputs, "apply_report")["complete"]:
            problems.append("patch application incomplete")
        if "read_back" in outputs and _record(outputs, "read_back")["outcome"] != "confirmed":
            problems.append("read-back mismatch: " + _record(outputs, "read_back")["detail"])
        if "model_output" in outputs and ctx.extras.get("proposal_problem"):
            problems.append(ctx.extras["proposal_problem"])
        return ("passed" if not problems else "failed"), {"problems": problems, "slots": sorted(outputs)}


# ===================================================================== propose port

def build_prompt(task_goal: str, binding: dict, snapshot: dict, manifest: dict, store, *, failure_context: list, round_index: int):
    """Returns (prompt bytes, context entries, omitted obligations)."""
    allowed = binding["allowed_paths"]
    lines = ["You are the worker role of Gabriel, a repository repair agent.",
             "Goal (verbatim user request):", task_goal.strip(), "",
             "Acceptance checks (independent oracles decide completion; you cannot change them):"]
    for s in binding["check_specs"]:
        if s["role"] == "structural" or s["role"] == "baseline_only":
            continue
        lines.append("- %s [%s] argv=%s independent=%s" % (s["check_id"], s["predicate_kind"], " ".join(s["argv"]), s["independent"]))
    lines += ["", "Allowed paths (changes elsewhere are rejected): " + ", ".join(allowed),
              "Base commit: " + snapshot["base_commit"], "",
              "Files (path sha256 bytes):"]
    entries = []
    budget = PROMPT_SOURCE_BUDGET
    sources = []
    for path, entry in sorted(manifest.items()):
        if entry["kind"] != "file":
            continue
        lines.append("  %s %s %d" % (path, entry["sha256"], entry["bytes"]))
        if fs.path_in_scope(path, allowed) and path.endswith(RETAINED_SOURCE_SUFFIXES):
            sources.append((path, entry))
    lines += ["", "Source files in scope:"]
    for path, entry in sources:
        ref = {"sha256": entry["sha256"], "bytes": entry["bytes"], "media_type": "text/plain; charset=utf-8"}
        try:
            data = store.get(ref)
        except GabrielError:
            # Never omit a file silently: the model must know that it is editing unseen content.
            lines += ["=== %s (sha256 %s) === [CONTENT NOT RETAINED: %d bytes not shown]" % (path, entry["sha256"], entry["bytes"]), ""]
            continue
        truncated = len(data) > budget
        shown = data[:max(budget, 0)]
        budget -= len(shown)
        text = shown.decode("utf8", "replace")
        lines += ["=== %s (sha256 %s)%s ===" % (path, entry["sha256"], " [TRUNCATED]" if truncated else ""), text, ""]
        entries.append({"entry_id": "src-%d" % len(entries), "kind": "source", "artifact_ref": ref, "source_id": "worktree", "source_revision": None,
                        "observation_id": None, "span_start": 0, "span_end": len(shown), "purpose": "source", "truncated": truncated,
                        "omitted_bytes": len(data) - len(shown), "disclosure_scope": "provider"})
        if budget <= 0:
            break
    if failure_context:
        lines += ["", "Previous attempt failed verification (round %d). Diagnostics:" % round_index]
        for item in failure_context:
            lines += ["--- %s ---" % item["check_id"], item["text"][:4000], ""]
    lines += ["", "Respond with exactly one JSON object and nothing else:",
              '{"operations": [{"kind": "modify", "path": "<relative path>", "expected_sha256": "<sha256 listed above>", "content": "<complete new file content>"}],',
              ' "rationale": "<short explanation>"}',
              "Rules: kind is one of create, modify, delete. For modify/delete expected_sha256 must equal the listed digest.",
              "For create expected_sha256 is null. For delete content is null. Do not touch oracle or test command files.",
              "Do not claim completion; the independent checks decide."]
    return "\n".join(lines).encode("utf8"), entries


def normalize_patch_proposal(proposal: dict, snapshot: dict, manifest: dict, binding: dict, store, *, task_id, run_id, proposal_ref,
                             protected: set, goal_id: str, policy_digest: str):
    """Strict domain normalization. Returns (patch record or None, loss list, problem)."""
    loss, operations, seen_paths = [], [], set()
    if not proposal["operations"]:
        return None, loss, "proposal contains no operations"
    for index, op in enumerate(proposal["operations"]):
        kind = op["kind"]
        if kind not in ("create", "modify", "delete"):
            return None, loss, "unknown operation kind %r rejected (no default)" % kind
        try:
            fs.split_relative(op["path"])
        except GabrielError as exc:
            return None, loss, "operation %d: %s" % (index, exc.message)
        path = op["path"]
        if path in seen_paths:
            return None, loss, "duplicate path in proposal: " + path
        seen_paths.add(path)
        if not fs.path_in_scope(path, binding["allowed_paths"]):
            return None, loss, "operation %d targets a path outside the admitted scope: %s" % (index, path)
        if path in protected:
            return None, loss, "operation %d targets a protected oracle/check file: %s" % (index, path)
        current = manifest.get(path)
        if kind == "create":
            if current is not None:
                return None, loss, "create targets an existing file: " + path
            if op["expected_sha256"] is not None:
                loss.append("create ignores expected_sha256 for " + path)
            if not isinstance(op["content"], str):
                return None, loss, "create needs content for " + path
        else:
            if current is None or current["kind"] != "file":
                return None, loss, "%s targets a missing file: %s" % (kind, path)
            if op["expected_sha256"] != current["sha256"]:
                return None, loss, "%s expected_sha256 does not match the observed file identity for %s" % (kind, path)
            if kind == "modify" and not isinstance(op["content"], str):
                return None, loss, "modify needs content for " + path
            if kind == "delete" and op["content"] is not None:
                loss.append("delete ignores content for " + path)
        content_ref = content_sha = None
        if kind != "delete":
            raw = op["content"].encode("utf8")
            if len(raw) > MAX_FILE_BYTES:
                return None, loss, "content exceeds the artifact limit for " + path
            content_ref = store.put(raw, "text/plain; charset=utf-8")
            content_sha = content_ref["sha256"]
        operations.append({"kind": kind, "path": path, "expected_sha256": None if kind == "create" else op["expected_sha256"],
                           "content_ref": content_ref, "content_sha256": content_sha})
    rationale_ref = store.put(proposal["rationale"].encode("utf8"), "text/plain; charset=utf-8")
    ops_blob = Artifact(canonical(operations), "application/json")
    snapshot_ref = store.put(canonical(snapshot), "application/json")
    cand = kernel_candidate(hashlib.sha256(goal_id.encode()).hexdigest(), snapshot_ref["sha256"], "patch:" + ".".join(sorted({o["kind"] for o in operations})),
                            {"sha256": snapshot["tree_digest"], "bytes": 0, "media_type": "application/json"}, ops_blob.ref())
    patch = {"schema": "gabriel.software-patch/1", "patch_id": "patch-" + cand.id[:16], "task_id": task_id, "run_id": run_id,
             "base_tree_digest": snapshot["tree_digest"], "base_snapshot_ref": snapshot_ref, "operations": operations,
             "rationale_ref": rationale_ref, "proposal_ref": proposal_ref, "candidate_id": cand.id}
    validate(patch, "software-patch")
    return patch, loss, None


# ===================================================================== pack

class SoftwarePack:
    namespace, pack_id, pack_version = NAMESPACE, PACK_ID, PACK_VERSION

    def __init__(self, provider_factory, backend_resolver):
        self.provider_factory = provider_factory
        self.backend_resolver = backend_resolver

    def register(self, registry: ToolRegistry) -> None:
        def descriptor(tool_id, effect_class, reconciliation, concurrency_key, observation_slot=None, forms=("worktree",), approval=False):
            return {"tool_id": tool_id, "version": "v1", "effect_class": effect_class, "input_schema_digest": schema_digest("task-binding"),
                    "output_schema_digest": schema_digest("result"), "timeout_ms": 600000, "max_output_bytes": 1 << 20,
                    "concurrency_key": concurrency_key, "reconciliation": reconciliation, "requires_approval": approval,
                    "description": "software pack " + tool_id, "resource_forms": list(forms), "observation_slot": observation_slot}
        registry.register_tool(descriptor("software.observe", "read", "read_back", "read", "snapshot"), ObserveTool())
        registry.register_tool(descriptor("software.run_check", "local_reversible_write", "read_back", "writer"), RunCheckTool(self.backend_resolver))
        registry.register_tool(descriptor("software.apply_patch", "local_reversible_write", "read_back", "writer"), ApplyPatchTool())
        registry.register_tool(descriptor("software.read_back", "read", "read_back", "read", "snapshot"), ReadBackTool())
        registry.register_tool(descriptor("software.review", "read", "read_back", "read"), ReviewTool())
        registry.register_tool(descriptor("model.generate", "external_idempotent_effect", "same_key_retry", "model", forms=("provider",)),
                               ModelGenerateTool(self.provider_factory))
        for verifier_id, kind, impl, independent in [("software.test_passed", "software/test_passed", TestPassedVerifier(), True),
                                                     ("software.diff_in_scope", "software/diff_in_scope", DiffInScopeVerifier(), True),
                                                     ("software.base_commit_pinned", "software/base_commit_pinned", BaseCommitPinnedVerifier(), True),
                                                     ("software.checks_intact", "software/checks_intact", ChecksIntactVerifier(), True),
                                                     ("software.no_secrets", "software/no_secrets", NoSecretsVerifier(), True),
                                                     ("owner.output_valid", "owner/output_valid", OutputValidVerifier(), False)]:
            registry.register_verifier({"verifier_id": verifier_id, "version": "v1", "predicate_kind": kind, "implementation_fingerprint": "0" * 64,
                                        "profile_digest": sha256_hex(verifier_id.encode()), "independent": independent,
                                        "description": "software pack verifier " + verifier_id}, impl)
        registry.register_pack(self.manifest(registry))

    def manifest(self, registry: ToolRegistry) -> dict:
        from ...artifacts import ObjectStore  # noqa: F401 - manifest refs are digests of in-memory records
        def ref(value):
            raw = canonical(value)
            return {"sha256": sha256_hex(raw), "bytes": len(raw), "media_type": "application/json"}
        schema_ref = ref({"schema": "fixture"})
        ports = {}
        for port, tool_id, effect in [("compile", "software.observe", "read"), ("observe", "software.observe", "read"), ("evaluate", "software.run_check", "local_reversible_write"),
                                      ("propose", "model.generate", "external_idempotent_effect"), ("execute", "software.apply_patch", "local_reversible_write"),
                                      ("read_back", "software.read_back", "read")]:
            impl = registry.tool(tool_id)[0]["implementation_fingerprint"]
            ports[port] = {"capability_id": tool_id, "input_schema_ref": schema_ref, "output_schema_ref": schema_ref,
                           "implementation_ref": {"sha256": impl, "bytes": 0, "media_type": "application/json"}, "effect_class": effect}
        manifest = {"schema": "gabriel.domain-pack/1", "pack_id": PACK_ID, "namespace": NAMESPACE, "pack_version": PACK_VERSION,
                    "manifest_kind": "implementation_release", "ports": ports, "observation_coverage_ref": ref({"observes": ["files", "lexical python structure", "test presence"], "does_not_observe": ["behavior"]}),
                    "evaluation_profiles": [{"profile_id": "software-test-passed-v1", "spec_ref": ref({"rule": "exit code 0 with intact oracle files"})}],
                    "transformation_profiles": [{"profile_id": TRANSFORM_PROFILE, "spec_ref": ref({"rule": "loss-preserving compile"})}],
                    "capability_requirements": ["software.observe", "software.run_check", "software.apply_patch", "software.read_back", "software.review", "model.generate"],
                    "conventions_ref": ref({"missingness": "absent file is not an empty file", "time": "owner sequence numbers", "units": ["bytes"]}),
                    "fixtures": [{"fixture_id": "valid", "port": "evaluate", "case_kind": "valid", "input_ref": schema_ref, "expected_ref": schema_ref},
                                 {"fixture_id": "invalid", "port": "evaluate", "case_kind": "invalid", "input_ref": schema_ref, "expected_ref": schema_ref},
                                 {"fixture_id": "out_of_scope", "port": "evaluate", "case_kind": "out_of_scope", "input_ref": schema_ref, "expected_ref": schema_ref}]}
        return validate(manifest, "domain-pack")
