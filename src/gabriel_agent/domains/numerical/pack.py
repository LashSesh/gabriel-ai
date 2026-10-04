"""Numerical DomainPack (WP10): declared analytical transformations behind explicit contracts.

Observe: every JSON dataset outside the output scope is described (kind, units, time basis,
rows, problems) without computing anything. Propose: the model binds one declared operation
of ``adapters.analytical`` to an observed input identity and an output path. Execute: a fresh
contained worker per job runs the same adapter file; the job's cache key binds the complete
input bytes, operation, parameters, profile, worker build and numerical environment, so a
collision of the inherited padded graph signature cannot authorize reuse (AT16). Verify: an
independent reference contract (expected values, units and tolerance, kept outside the
repository) accepts only ``computed`` verdicts; ``out_of_scope``, ``invalid_input`` and
``unknown`` are retained domain verdicts, not failed transports, and never success.
"""
from __future__ import annotations

import hashlib
import json
import os
import struct
import subprocess
import sys
import time
from pathlib import Path

from ...adapters import analytical, native_graph
from ...contracts.codec import canonical, dumps_utf8, loads, sha256_hex
from ...contracts.errors import Code, GabrielError
from ...contracts.schemas import validate
from ...kernel import Artifact, candidate as kernel_candidate
from ...models import ModelGenerateTool
from ...tools import fs
from ...workers.isolation import RunSpec
from ...workers.supervisor import ToolOutcome
from ..base import DomainPack, compile_generic, descriptor, usage
from ..software.pack import (MAX_FILE_BYTES, BaseCommitPinnedVerifier, ChecksIntactVerifier, DiffInScopeVerifier, NoSecretsVerifier,
                             OutputValidVerifier, ReviewTool, _record)

NAMESPACE = "numerical"
PACK_ID = "numerical-transform"
PACK_VERSION = "0.1.0"
EXTRACTION_PROFILE = "dataset-descriptor-v1"
TRANSFORM_PROFILE = "numerical-compile-v1"
WORKER_DIR = ".gabriel_worker"
SUPPORTED_KINDS = {"numerical/reference_contract": "numerical.reference_contract", "numerical/diff_in_scope": "numerical.diff_in_scope",
                   "numerical/base_commit_pinned": "numerical.base_commit_pinned", "numerical/checks_intact": "numerical.checks_intact",
                   "numerical/no_secrets": "numerical.no_secrets", "owner/output_valid": "numerical.output_valid"}
STRUCTURAL = [("scope", "numerical/diff_in_scope"), ("base-commit", "numerical/base_commit_pinned"),
              ("checks-intact", "numerical/checks_intact"), ("no-secrets", "numerical/no_secrets")]
OUTPUT_SLOTS = {"numerical.observe": ["snapshot"], "numerical.run_job": ["job_result", "witness"], "numerical.read_back": ["snapshot", "read_back"],
                "numerical.verify": ["verification"], "numerical.review": ["review", "patch"],
                "model.generate": ["model_output", "raw_response", "request", "envelope"]}
RETRY_CLASS = {"numerical.observe": "read_retry", "numerical.run_job": "reconcile_before_retry", "numerical.read_back": "read_retry",
               "numerical.verify": "read_retry", "numerical.review": "read_retry", "model.generate": "target_idempotent_retry"}


# ADR-24: the pack's declared progress channels, committed facts of the latest reference-contract verification
PROGRESS_SCHEMA_ID = "numerical-progress-v1"
PROGRESS_CHANNELS = ("input_problems", "verdict_refused", "contract_mismatch", "units_mismatch", "rows_mismatch", "deviation_excess", "output_unbound")
FAILURE_CLASSES = ("none", "verdict", "output_binding", "contract", "units", "rows", "deviation", "structure")

WORKER_FILES = ("result.json", "job.json", "worker.py", "native_worker.py") + tuple("bin/" + name for name in native_graph.BINARIES)
CERTIFY_TIMEOUT_S = 120
OPERATIONS = {**analytical.OPERATIONS, **native_graph.OPERATIONS}  # disjoint ids: stdlib worker and native graph worker


def is_native(operation: str) -> bool:
    return operation in native_graph.OPERATIONS


def profile_id(operation: str) -> str:
    return native_graph.PROFILE_ID if is_native(operation) else analytical.PROFILE_ID


def _worker_source(operation: str = "units.convert") -> bytes:
    return Path(native_graph.__file__ if is_native(operation) else analytical.__file__).read_bytes()


def worker_build(operation: str = "units.convert") -> str:
    """Identity of the worker that runs an operation: the adapter file's bytes; for native
    operations also the digests of the bound executables (missing executables leave the build
    distinct from any complete one, so a job can never be bound to them)."""
    if is_native(operation):
        return native_graph.worker_build(native_graph.binaries())
    return hashlib.sha256(_worker_source()).hexdigest()


def numerical_environment(operation: str = "units.convert") -> dict:
    return native_graph.numerical_environment() if is_native(operation) else analytical.numerical_environment()


def cache_key(input_sha: str, operation: str, parameters: dict, build: str, environment: dict) -> str:
    """Binds complete input bytes, operation, parameters, profile, worker build and numerical environment."""
    return hashlib.sha256(canonical({"input_sha256": input_sha, "operation": operation, "parameters": parameters, "profile": profile_id(operation),
                                     "worker_build": build, "environment": environment})).hexdigest()


def _binary64(value) -> float:
    if not isinstance(value, str) or len(value) != 16:
        raise ValueError("not binary64 bits")
    return struct.unpack(">d", bytes.fromhex(value))[0]


def certify_output(output_raw: bytes) -> tuple:
    """Stage two of ``graph.window_reachability``: exact certificates (python-flint/Arb) over the
    validated native snapshot, in a dedicated host process. Returns (verdict, output bytes or
    None, stage record). The verdict is ``computed`` only when every window is decided
    (``reachable`` or ``excluded``); ``out_of_scope`` and ``unknown`` statuses, an unavailable
    arithmetic or a failed process never leave an output, and the stage record keeps what was
    established."""
    clock = time.monotonic_ns()
    source_root = Path(native_graph.__file__).resolve().parents[2]
    env = dict(os.environ, PYTHONPATH=str(source_root) + (os.pathsep + os.environ["PYTHONPATH"] if os.environ.get("PYTHONPATH") else ""))
    try:
        output = json.loads(output_raw.decode("utf8"))
        process = subprocess.run([sys.executable, "-m", "gabriel_agent.adapters.native_graph", "certify"], input=json.dumps({"output": output}).encode("utf8"),
                                 capture_output=True, timeout=CERTIFY_TIMEOUT_S, check=False, env=env, cwd=str(source_root))
        if process.returncode != 0:
            raise ValueError("certificate process failed: " + process.stderr[-2000:].decode("utf8", errors="replace").strip())
        certified = json.loads(process.stdout.decode("utf8"))
        statuses = list(certified["statuses"])
        if any(s not in ("reachable", "excluded", "unknown", "out_of_scope") for s in statuses):
            raise ValueError("certificate process returned an undeclared status")
    except (ValueError, OSError, subprocess.TimeoutExpired, KeyError, TypeError, UnicodeDecodeError) as exc:
        return "unknown", None, {"status": "unavailable", "reason": str(exc)[:500], "elapsed_us": (time.monotonic_ns() - clock) // 1000}
    verdict = "out_of_scope" if "out_of_scope" in statuses else "unknown" if "unknown" in statuses else "computed"
    output.update({"stage": "certified", "certificates": certified["certificates"], "statuses": statuses, "arithmetic": certified["arithmetic"]})
    stage = {"status": verdict, "statuses": statuses, "certificates": certified["certificates"], "arithmetic": certified["arithmetic"],
             "elapsed_us": (time.monotonic_ns() - clock) // 1000}
    return verdict, (native_graph.dumps(output) if verdict == "computed" else None), stage


# ===================================================================== compile port

def compile_task(spec: dict, store, **ids):
    def hook(raw, check_spec):
        if check_spec["predicate_kind"] == "numerical/reference_contract":
            if len(check_spec["oracle_files"]) != 1:
                return "a reference contract check needs exactly one oracle file (expected output kept outside the repository)"
            try:
                oracle = json.loads(store.get(check_spec["oracle_files"][0]["artifact_ref"]).decode("utf8"))
            except (ValueError, UnicodeDecodeError, GabrielError):
                return "the reference oracle is not a JSON document"
            if oracle.get("operation") not in OPERATIONS:
                return "the reference oracle names an unknown operation"
        return None
    pin = {"schema": "gabriel.software-repository-pin/1", "repository_path": str(spec["repository"]), "base_commit": ids["base_commit"], "pinned_by": ids["principal_id"]}
    validate(pin, "software-repository-pin")
    return compile_generic(spec, store, pack=NumericalPack(None, None), transform_profile=TRANSFORM_PROFILE, supported_kinds=SUPPORTED_KINDS,
                           structural=STRUCTURAL, independent_kinds=("numerical/reference_contract",), base_inputs=[store.put(canonical(pin), "application/json")],
                           check_hook=hook, **ids)


# ===================================================================== plans

def reference_plan_proposal(task: dict, binding: dict, repair_round: int = 0) -> dict:
    suffix = "" if repair_round == 0 else "-r%d" % repair_round
    specs = {s["check_id"]: s for s in binding["check_specs"]}
    reference_checks = [cid for cid, s in specs.items() if s["predicate_kind"] == "numerical/reference_contract"]
    structural = [cid for cid, _ in STRUCTURAL if cid in specs]
    nodes = [{"node_id": "observe" + suffix, "capability_id": "numerical.observe", "depends_on": [], "check_ids": ["output-valid"],
              "purpose": "describe the datasets and pin the worktree", "args": {}},
             {"node_id": "propose" + suffix, "capability_id": "model.generate", "depends_on": ["observe" + suffix], "check_ids": ["output-valid"],
              "purpose": "bind one declared operation to an observed input", "args": {"role": "worker"}},
             {"node_id": "run-job" + suffix, "capability_id": "numerical.run_job", "depends_on": ["propose" + suffix], "check_ids": ["output-valid"],
              "purpose": "run the job in a fresh contained worker", "args": {"from_node": "propose" + suffix}},
             {"node_id": "read-back" + suffix, "capability_id": "numerical.read_back", "depends_on": ["run-job" + suffix], "check_ids": ["output-valid"],
              "purpose": "observe the changed tree", "args": {}},
             {"node_id": "verify-reference" + suffix, "capability_id": "numerical.verify", "depends_on": ["read-back" + suffix], "check_ids": reference_checks,
              "purpose": "bind the observed output to the job result and the independent reference", "args": {"from_node": "run-job" + suffix}},
             {"node_id": "review" + suffix, "capability_id": "numerical.review", "depends_on": ["read-back" + suffix], "check_ids": structural,
              "purpose": "scope, identity and secret review of the diff", "args": {}}]
    return {"nodes": nodes, "rationale": "reference numerical plan (round %d)" % repair_round}


# ===================================================================== observe port

def take_snapshot(worktree, binding: dict, store, frontier: int) -> tuple:
    manifest = worktree.manifest()
    datasets = []
    with fs.ContainedRoot(str(worktree.path)) as root:
        for path, entry in sorted(manifest.items()):
            if entry["kind"] != "file" or not path.endswith(".json") or fs.path_in_scope(path, binding["allowed_paths"]) or path.startswith(WORKER_DIR):
                continue
            if entry["bytes"] > MAX_FILE_BYTES:
                datasets.append({"path": path, "sha256": entry["sha256"], "bytes": entry["bytes"], "format": "unsupported", "kind": "unknown", "units": None,
                                 "time_basis": None, "rows": None, "problems": ["file exceeds the artifact limit"]})
                continue
            try:
                raw = root.read(path)
            except GabrielError:
                continue
            store.put(raw, "application/json; charset=utf-8")  # retained input identity
            description = analytical.describe(raw)
            if description["format"] == "json" and description["kind"] == "unknown":
                native = native_graph.describe(raw)  # native graph kinds: bounds checked, nothing computed
                if native["kind"] != "unknown":
                    description = native
            datasets.append({"path": path, "sha256": entry["sha256"], "bytes": entry["bytes"], "format": description["format"], "kind": description["kind"],
                             "units": description["units"], "time_basis": description["time_basis"], "rows": description["rows"],
                             "problems": [p[:256] for p in description["problems"]][:16]})
    manifest_ref = store.put(dumps_utf8(manifest), "application/json; charset=utf-8")
    snapshot = {"schema": "gabriel.numerical-snapshot/1", "worktree_id": "worktree", "base_commit": worktree.base_commit, "head_commit": worktree.head(),
                "manifest_ref": manifest_ref, "tree_digest": sha256_hex(canonical(manifest)), "datasets": datasets[:64], "extraction_profile": EXTRACTION_PROFILE,
                "coverage": {"observes": ["file bytes and digests", "dataset kind, units, time basis, row count and contract problems"],
                             "does_not_observe": ["computed values", "external state"]}, "observed_frontier": frontier}
    validate(snapshot, "numerical-snapshot")
    return snapshot, manifest


class ObserveTool:
    def __call__(self, intent, args, ctx):
        snapshot, _ = take_snapshot(ctx.worktree, ctx.binding, ctx.store, ctx.owner.anchor()["sequence"])
        d = ctx.registry.tool(intent["capability_id"])[0]["output_schema_digest"]
        return ToolOutcome(outputs=[("snapshot", canonical(snapshot), "application/json", d)])

    def reconcile(self, intent, attempt, ctx):
        return "confirmed_not_executed", canonical({"read_only": True})


# ===================================================================== propose port

def build_prompt(task_goal: str, binding: dict, snapshot: dict, manifest: dict, store, *, failure_context: list, round_index: int):
    lines = ["You are the worker role of Gabriel for a numerical transformation task.",
             "Goal (verbatim user request):", task_goal.strip(), "",
             "Acceptance checks (an independent reference contract decides completion; you cannot change it):"]
    for s in binding["check_specs"]:
        if s["role"] != "structural":
            lines.append("- %s [%s] independent=%s" % (s["check_id"], s["predicate_kind"], s["independent"]))
    lines += ["", "Allowed output paths (writes elsewhere are rejected): " + ", ".join(binding["allowed_paths"]), "Base commit: " + snapshot["base_commit"], "",
              "Observed datasets (path sha256 bytes kind units time_basis rows problems):"]
    entries = []
    for d in snapshot["datasets"]:
        lines.append("  %s %s %d %s %s %s %s %s" % (d["path"], d["sha256"], d["bytes"], d["kind"], d["units"], d["time_basis"], d["rows"], "; ".join(d["problems"]) or "-"))
        entries.append({"entry_id": "ds-%d" % len(entries), "kind": "source", "artifact_ref": {"sha256": d["sha256"], "bytes": d["bytes"], "media_type": "application/json; charset=utf-8"},
                        "source_id": "worktree", "source_revision": None, "observation_id": None, "span_start": 0, "span_end": d["bytes"], "purpose": "dataset",
                        "truncated": False, "omitted_bytes": 0, "disclosure_scope": "provider"})
    lines += ["", "Declared operations (id: input kind; parameters; worker; description):"]
    for op_id, spec in sorted(OPERATIONS.items()):
        lines.append("  %s: %s; %s; %s; %s" % (op_id, spec["input_kind"], json.dumps(spec["parameters"]), "native graph engine" if is_native(op_id) else "standard library",
                                               spec["description"]))
    if failure_context:
        lines += ["", "Previous attempt failed verification (round %d). Diagnostics:" % round_index]
        for item in failure_context:
            lines += ["--- %s ---" % item["check_id"], item["text"][:4000], ""]
    lines += ["", "Respond with exactly one JSON object and nothing else:",
              '{"operation": "<operation id>", "input_path": "<observed dataset path>", "expected_sha256": "<its sha256>", "output_path": "<path inside the allowed output paths>",',
              ' "parameters": {<parameters of the operation>}, "rationale": "<short explanation>"}',
              "Rules: the operation must be one of the declared ids; parameters must match its declared types; integers only (no floats) in parameters;",
              "native graph operations take no parameters (the query is the declared dataset) and need an input of their declared kind.",
              "Do not claim completion; the independent reference contract decides."]
    return "\n".join(lines).encode("utf8"), entries


def normalize_job_proposal(proposal: dict, snapshot: dict, manifest: dict, binding: dict, store, *, task_id, run_id, proposal_ref, protected: set, goal_id: str, policy_digest: str):
    loss = []
    operation = proposal["operation"]
    if operation not in OPERATIONS:
        return None, loss, "unknown operation %r rejected (no default)" % operation
    spec = OPERATIONS[operation]
    params = proposal["parameters"]
    for name in spec["required"]:
        if name not in params:
            return None, loss, "missing parameter %s for %s" % (name, operation)
    for name, value in params.items():
        expected = spec["parameters"].get(name)
        if expected is None:
            return None, loss, "unknown parameter %s for %s" % (name, operation)
        if expected == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
            return None, loss, "parameter %s must be an integer" % name
        if expected == "string" and not isinstance(value, str):
            return None, loss, "parameter %s must be a string" % name
    try:
        fs.split_relative(proposal["input_path"])
        fs.split_relative(proposal["output_path"])
    except GabrielError as exc:
        return None, loss, exc.message
    dataset = next((d for d in snapshot["datasets"] if d["path"] == proposal["input_path"]), None)
    if dataset is None:
        return None, loss, "input_path %s is not an observed dataset" % proposal["input_path"]
    if proposal["expected_sha256"] != dataset["sha256"]:
        return None, loss, "expected_sha256 does not match the observed identity of " + proposal["input_path"]
    if not fs.path_in_scope(proposal["output_path"], binding["allowed_paths"]) or proposal["output_path"] in protected:
        return None, loss, "output_path outside the admitted scope or protected: " + proposal["output_path"]
    if proposal["output_path"].startswith(WORKER_DIR):
        return None, loss, "output_path may not name the worker directory"
    input_ref = {"sha256": dataset["sha256"], "bytes": dataset["bytes"], "media_type": "application/json; charset=utf-8"}
    try:
        store.get(input_ref)
    except GabrielError:
        return None, loss, "the observed input bytes are not retained; observe again"
    if is_native(operation) and not native_graph.available():
        return None, loss, "the native executables for %s are not available on this host (no substitute worker)" % operation
    build = worker_build(operation)
    environment = numerical_environment(operation)
    key = cache_key(dataset["sha256"], operation, params, build, environment)
    snapshot_ref = store.put(canonical(snapshot), "application/json")
    payload = Artifact(canonical({"operation": operation, "parameters": params, "input": dataset["sha256"], "output_path": proposal["output_path"]}), "application/json")
    cand = kernel_candidate(hashlib.sha256(goal_id.encode()).hexdigest(), snapshot_ref["sha256"], "job:" + operation.replace(".", "_"),
                            {"sha256": snapshot["tree_digest"], "bytes": 0, "media_type": "application/json"}, payload.ref())
    job = {"schema": "gabriel.numerical-job/1", "job_id": "job-" + cand.id[:16], "task_id": task_id, "run_id": run_id, "operation": operation,
           "profile_id": profile_id(operation), "input_path": proposal["input_path"], "input_ref": input_ref, "output_path": proposal["output_path"],
           "parameters": params, "declared_units": dataset["units"], "worker_build": build, "numerical_environment": environment, "cache_key": key,
           "candidate_id": cand.id, "proposal_ref": proposal_ref, "base_tree_digest": snapshot["tree_digest"], "base_snapshot_ref": snapshot_ref}
    validate(job, "numerical-job")
    return job, loss, None


# ===================================================================== execute port

class RunJobTool:
    """Fresh contained worker per job. The worker file (for native operations also the bound
    executables) and the job description are installed into the worktree for the run only; the
    output stays, everything else is removed. A window certificate is then computed in a dedicated
    host process (stage two); its statuses decide the job verdict."""

    def __init__(self, backend_resolver):
        self.backend_resolver = backend_resolver

    def __call__(self, intent, args, ctx):
        job = validate(loads(ctx.store.get(args["job_ref"])), "numerical-job")
        if ctx.worktree.tree_digest() != job["base_tree_digest"]:
            raise GabrielError(Code.STALE_EVIDENCE, "worktree differs from the job's base snapshot; observe and propose again")
        if job["worker_build"] != worker_build(job["operation"]):
            raise GabrielError(Code.STALE_EVIDENCE, "the worker build (adapter source or native executables) changed since the job was bound")
        backend = ctx.backend or self.backend_resolver()
        d = ctx.registry.tool(intent["capability_id"])[0]["output_schema_digest"]
        cache = _Cache(ctx.extras.get("numerical_cache"))
        hit = cache.get(job["cache_key"])
        if hit is not None:
            try:
                # a hit re-issues the retained result together with the retained witness of the run that produced it
                witness_record = validate(loads(ctx.store.get(hit["witness_ref"])), "run-witness")
                self._materialize_output(ctx, job, hit)
                result = validate(dict(hit, cache={"key": job["cache_key"], "hit": True}), "numerical-job-result")
            except GabrielError:
                hit = None  # an incomplete cache entry is a miss, never a partial answer
            else:
                return ToolOutcome(outputs=[("job_result", canonical(result), "application/json", d), ("witness", canonical(witness_record), "application/json", d)],
                                   effect_outcome="acknowledged_success", notes=["cache hit on the complete job key"])
        started = ctx.owner.owner_time()
        clock = time.monotonic_ns()
        entry = self._install(ctx, job)
        witness = backend.run(RunSpec(argv=["python3", entry, WORKER_DIR + "/job.json"], worktree=str(ctx.worktree.path),
                                      timeout_ms=120000, max_output_bytes=1 << 20, marker="gabriel-" + intent["attempt_id"]))
        stage_one_us = (time.monotonic_ns() - clock) // 1000
        stdout_ref = ctx.store.put(witness.stdout.captured, "application/octet-stream")
        stderr_ref = ctx.store.put(witness.stderr.captured, "application/octet-stream")
        witness_record = validate(witness.to_record(stdout_ref, stderr_ref), "run-witness")
        witness_ref = ctx.store.put(canonical(witness_record), "application/json")
        worker_result, output_raw = None, None
        with fs.ContainedRoot(str(ctx.worktree.path)) as root:
            try:
                worker_result = json.loads(root.read(WORKER_DIR + "/result.json").decode("utf8"))
            except (GabrielError, ValueError, UnicodeDecodeError):
                worker_result = None
            if worker_result and worker_result.get("verdict") == "computed" and root.exists(job["output_path"]):
                output_raw = root.read(job["output_path"])
        self._cleanup(ctx)
        stage_two = None
        if worker_result is not None and OPERATIONS[job["operation"]].get("certificate") and worker_result.get("verdict") == "computed" and output_raw is not None:
            worker_result, output_raw, stage_two = self._certify(ctx, job, worker_result, output_raw)
        elapsed = max(0, ctx.owner.owner_time() - started)
        diagnostics = {"worker": worker_result, "exit_code": witness.exit_code, "timed_out": witness.timed_out, "start_failure": witness.start_failure,
                       "stage_one_us": stage_one_us, "stage_two": stage_two, "worker_entry": entry}
        diagnostics_ref = ctx.store.put(dumps_utf8(diagnostics), "application/json; charset=utf-8")
        if witness.start_failure or witness.timed_out or witness.exit_code != 0 or worker_result is None:
            result = {"schema": "gabriel.numerical-job-result/1", "job_ref": args["job_ref"], "status": "failed", "verdict": "unknown", "worker_build": job["worker_build"],
                      "numerical_environment": job["numerical_environment"], "output_sha256": None, "output_ref": None, "output_units": None, "rows": None,
                      "diagnostics_ref": diagnostics_ref, "elapsed_ms": elapsed, "cache": {"key": job["cache_key"], "hit": False}, "witness_ref": witness_ref,
                      "containment": witness.backend_kind == "linux_namespace", "backend_kind": witness.backend_kind}
            validate(result, "numerical-job-result")
            return ToolOutcome(status="failed", exit_code=witness.exit_code, effect_outcome="acknowledged_failure",
                               outputs=[("job_result", canonical(result), "application/json", d), ("witness", canonical(witness_record), "application/json", d)])
        output_ref = ctx.store.put(output_raw, "application/json; charset=utf-8") if output_raw is not None else None
        if output_raw is not None and sha256_hex(output_raw) != worker_result.get("output_sha256"):
            raise GabrielError(Code.STORAGE_FAULT, "the worker's output digest does not match the file it wrote")
        result = {"schema": "gabriel.numerical-job-result/1", "job_ref": args["job_ref"], "status": "completed", "verdict": worker_result["verdict"],
                  "worker_build": worker_result.get("worker_build", job["worker_build"]),
                  "numerical_environment": {k: str(v)[:128] for k, v in (worker_result.get("numerical_environment") or job["numerical_environment"]).items()},
                  "output_sha256": worker_result.get("output_sha256"), "output_ref": output_ref, "output_units": worker_result.get("output_units"),
                  "rows": worker_result.get("rows"), "diagnostics_ref": diagnostics_ref, "elapsed_ms": elapsed, "cache": {"key": job["cache_key"], "hit": False},
                  "witness_ref": witness_ref, "containment": witness.backend_kind == "linux_namespace", "backend_kind": witness.backend_kind}
        validate(result, "numerical-job-result")
        if result["verdict"] == "computed":
            cache.put(job["cache_key"], result)
        return ToolOutcome(outputs=[("job_result", canonical(result), "application/json", d), ("witness", canonical(witness_record), "application/json", d)],
                           exit_code=witness.exit_code, effect_outcome="acknowledged_success")

    @staticmethod
    def _install(ctx, job) -> str:
        """Install the worker (and the bound native executables, re-checked against the job's build)
        with the job description; returns the worker entry path inside the worktree."""
        native = is_native(job["operation"])
        description = {"operation": job["operation"], "parameters": job["parameters"], "input_path": job["input_path"], "output_path": job["output_path"],
                       "result_path": WORKER_DIR + "/result.json", "max_input_bytes": native_graph.MAX_INPUT_BYTES if native else analytical.MAX_INPUT_BYTES}
        entry = WORKER_DIR + ("/native_worker.py" if native else "/worker.py")
        with fs.ContainedRoot(str(ctx.worktree.path)) as root:
            root.write(entry, _worker_source(job["operation"]))
            if native:
                bound = native_graph.binaries()
                if native_graph.worker_build(bound) != job["worker_build"]:
                    raise GabrielError(Code.STALE_EVIDENCE, "the native executables changed since the job was bound")
                description["binaries"] = {}
                for name, info in sorted(bound.items()):
                    raw = Path(info["path"]).read_bytes()
                    if sha256_hex(raw) != info["sha256"]:
                        raise GabrielError(Code.STALE_EVIDENCE, "native executable %s changed while being installed" % name)
                    relative = WORKER_DIR + "/bin/" + name
                    root.write(relative, raw)
                    fd = os.open(str(Path(ctx.worktree.path) / relative), os.O_RDONLY | os.O_NOFOLLOW)
                    try:
                        os.fchmod(fd, 0o755)
                    finally:
                        os.close(fd)
                    description["binaries"][name] = {"path": relative, "sha256": info["sha256"]}
            root.write(WORKER_DIR + "/job.json", json.dumps(description, sort_keys=True).encode("ascii"))
        return entry

    @staticmethod
    def _cleanup(ctx) -> list:
        removed = []
        with fs.ContainedRoot(str(ctx.worktree.path)) as root:
            for name in WORKER_FILES:
                if root.exists(WORKER_DIR + "/" + name):
                    try:
                        root.delete(WORKER_DIR + "/" + name)
                        removed.append(name)
                    except GabrielError:
                        pass
        for sub in ("bin", ""):
            try:
                (Path(ctx.worktree.path) / WORKER_DIR / sub).rmdir()
            except OSError:
                pass
        return removed

    @staticmethod
    def _drop_output(ctx, job) -> None:
        with fs.ContainedRoot(str(ctx.worktree.path)) as root:
            if root.exists(job["output_path"]):
                try:
                    root.delete(job["output_path"])
                except GabrielError:
                    pass

    @staticmethod
    def _certify(ctx, job, worker_result, output_raw):
        """Stage two of a window certificate job: exact arithmetic (python-flint/Arb) in a dedicated
        host process over the validated native snapshot. The verdict follows the statuses: computed
        only when every window is decided; out_of_scope and unknown retain their certificates in
        the diagnostics but leave no output, so nothing can be mistaken for an answer."""
        verdict, raw, stage = certify_output(output_raw)
        if verdict == "unknown" and stage["status"] == "unavailable":
            RunJobTool._drop_output(ctx, job)
            diagnostics = dict(worker_result.get("diagnostics") or {}, stage="certificate_unavailable", reason=stage["reason"])
            return dict(worker_result, verdict="unknown", output_sha256=None, diagnostics=diagnostics), None, stage
        diagnostics = dict(worker_result.get("diagnostics") or {}, stage="certified", statuses=stage["statuses"], certificates=stage["certificates"],
                           arithmetic=stage["arithmetic"], stage_two_us=stage["elapsed_us"])
        result = dict(worker_result, verdict=verdict, rows=len(stage["statuses"]), diagnostics=diagnostics, output_sha256=sha256_hex(raw) if raw is not None else None)
        if raw is not None:
            with fs.ContainedRoot(str(ctx.worktree.path)) as root:
                root.write(job["output_path"], raw)
            return result, raw, stage
        RunJobTool._drop_output(ctx, job)
        return result, None, stage

    @staticmethod
    def _materialize_output(ctx, job, result):
        """A cache hit still has to produce the output file in this worktree (same bytes)."""
        if result.get("output_ref") is None:
            return
        raw = ctx.store.get(result["output_ref"])
        with fs.ContainedRoot(str(ctx.worktree.path)) as root:
            root.write(job["output_path"], raw)

    def reconcile(self, intent, attempt, ctx):
        job = validate(loads(ctx.store.get(ctx.args["job_ref"])), "numerical-job")
        tree = ctx.worktree.tree_digest()
        leftovers = self._cleanup(ctx)
        with fs.ContainedRoot(str(ctx.worktree.path)) as root:
            output_present = root.exists(job["output_path"])
        if tree == job["base_tree_digest"]:
            return "confirmed_not_executed", canonical({"tree_digest": tree, "equals_base": True})
        if output_present and not leftovers:
            return "confirmed_success", canonical({"tree_digest": tree, "output_present": True})
        return "confirmed_failure", canonical({"tree_digest": tree, "output_present": output_present, "leftovers_removed": leftovers})


class _Cache:
    """Job-result cache keyed by the complete job key (never by a graph signature)."""

    def __init__(self, path):
        self.path = Path(path) if path else None

    def _load(self) -> dict:
        if self.path is None or not self.path.is_file():
            return {}
        try:
            return json.loads(self.path.read_text())
        except ValueError:
            return {}

    def get(self, key: str):
        return self._load().get(key)

    def put(self, key: str, result: dict):
        if self.path is None:
            return
        data = self._load()
        data[key] = result
        self.path.write_text(json.dumps(data, sort_keys=True))


class ReadBackTool:
    def __call__(self, intent, args, ctx):
        pre = validate(loads(ctx.store.get(args["pre_snapshot_ref"])), "numerical-snapshot")
        pre_manifest = loads(ctx.store.get(pre["manifest_ref"]), ascii_only=False)
        snapshot, manifest = take_snapshot(ctx.worktree, ctx.binding, ctx.store, ctx.owner.anchor()["sequence"])
        changed = sorted(p for p in set(pre_manifest) | set(manifest) if pre_manifest.get(p, {}).get("sha256") != manifest.get(p, {}).get("sha256"))
        out_of_scope = [p for p in changed if not fs.path_in_scope(p, ctx.binding["allowed_paths"])]
        record = {"schema": "gabriel.read-back/1", "read_back_id": "readback-" + intent["attempt_id"], "task_id": intent["task_id"], "run_id": intent["run_id"],
                  "intent_id": intent["intent_id"], "attempt_id": intent["attempt_id"], "pre_snapshot_ref": args["pre_snapshot_ref"],
                  "post_snapshot_ref": ctx.store.put(canonical(snapshot), "application/json"), "changed_resources": changed[:4096],
                  "invalidated_observation_ids": ["obs-" + sha256_hex(p.encode("utf8"))[:40] for p in changed][:4096], "postcondition_profile_id": "numerical-readback-v1",
                  "outcome": "confirmed" if not out_of_scope else "mismatch",
                  "detail": "changes confined to the admitted scope" if not out_of_scope else "out-of-scope changes: " + ",".join(out_of_scope)[:400]}
        validate(record, "read-back")
        d = ctx.registry.tool(intent["capability_id"])[0]["output_schema_digest"]
        return ToolOutcome(outputs=[("snapshot", canonical(snapshot), "application/json", d), ("read_back", canonical(record), "application/json", d)])

    def reconcile(self, intent, attempt, ctx):
        return "confirmed_not_executed", canonical({"read_only": True})


class VerifyTool:
    """Binds the observed output file to the retained job result after read-back."""

    def __call__(self, intent, args, ctx):
        result = validate(loads(ctx.store.get(args["job_result_ref"])), "numerical-job-result")
        job = validate(loads(ctx.store.get(result["job_ref"])), "numerical-job")
        with fs.ContainedRoot(str(ctx.worktree.path)) as root:
            present = root.exists(job["output_path"])
            observed = root.digest(job["output_path"]) if present else None
        record = {"job_ref": result["job_ref"], "job_result_ref": args["job_result_ref"], "operation": job["operation"], "output_path": job["output_path"],
                  "output_present": present, "output_sha256": observed, "matches_result": present and observed == result["output_sha256"],
                  "verdict": result["verdict"], "tree_digest": ctx.worktree.tree_digest()}
        d = ctx.registry.tool(intent["capability_id"])[0]["output_schema_digest"]
        return ToolOutcome(outputs=[("verification", canonical(record), "application/json", d)])

    def reconcile(self, intent, attempt, ctx):
        return "confirmed_not_executed", canonical({"read_only": True})


# ===================================================================== verifiers

def _input_problems(store, result: dict):
    """How many contract problems the observed input dataset of the judged job carried, read from
    the job's bound snapshot; None when the chain of references cannot be followed."""
    try:
        job = loads(store.get(result["job_ref"]))
        snapshot = loads(store.get(job["base_snapshot_ref"]))
        dataset = next(d for d in snapshot["datasets"] if d["path"] == job["input_path"])
        return len(dataset.get("problems") or [])
    except (GabrielError, ValueError, KeyError, StopIteration, TypeError):
        return None


def _worker_reason(store, result: dict):
    """What the worker said when it refused the job (its retained diagnostics); None for a computed result."""
    if result.get("verdict") == "computed" or not isinstance(result.get("diagnostics_ref"), dict):
        return None
    try:
        diagnostics = json.loads(store.get(result["diagnostics_ref"]).decode("utf8"))
        reason = ((diagnostics.get("worker") or {}).get("diagnostics") or {}).get("reason")
        return str(reason)[:256] if reason is not None else None
    except (GabrielError, ValueError, UnicodeDecodeError, AttributeError):
        return None


class ReferenceContractVerifier:
    """Independent reference: expected operation, units, values and tolerance kept outside the repository.

    Beside the reason, the evidence commits the class of a failure (``failure_class``, one of
    ``FAILURE_CLASSES``) and two facts of the job it judged: how many contract problems the
    observed input dataset carried (``input_problems``) and what the worker said when it refused
    (``worker_reason``). The pack's progress channels (ADR-24) read these fields, never the
    reason text; the worker's reason also reaches the next prompt's diagnostics."""

    def __call__(self, spec, outputs, ctx):
        verification = _record(outputs, "verification")
        if verification is None:
            return "not_run", {"reason": "no verification record"}
        if not spec["oracle_files"]:
            return "inconclusive", {"reason": "no reference oracle bound to the check"}
        try:
            oracle = json.loads(ctx.store.get(spec["oracle_files"][0]["artifact_ref"]).decode("utf8"))
            result = loads(ctx.store.get(verification["job_result_ref"]))
        except (GabrielError, ValueError, UnicodeDecodeError) as exc:
            return "inconclusive", {"reason": "reference or result unavailable: " + str(exc)[:200]}
        evidence = {"operation": verification["operation"], "verdict": result["verdict"], "expected_operation": oracle.get("operation"),
                    "output_path": verification["output_path"], "expected_output_path": oracle.get("output_path"), "containment": result["containment"],
                    "failure_class": "none", "input_problems": _input_problems(ctx.store, result), "worker_reason": _worker_reason(ctx.store, result)}

        def failed(failure_class: str, reason: str, **extra):
            return "failed", dict(evidence, failure_class=failure_class, reason=reason, **extra)

        if result["verdict"] != "computed":
            reason = "domain verdict %s is not a computed result" % result["verdict"]
            if evidence["worker_reason"]:
                reason += " (worker: %s)" % evidence["worker_reason"]
            return failed("verdict", reason)
        if not verification["output_present"] or not verification["matches_result"]:
            return failed("output_binding", "observed output does not match the retained job result")
        if verification["operation"] != oracle.get("operation") or verification["output_path"] != oracle.get("output_path"):
            return failed("contract", "operation or output path differ from the reference contract")
        if result.get("output_units") != oracle.get("units"):
            return failed("units", "output units %r differ from the reference %r" % (result.get("output_units"), oracle.get("units")))
        try:
            output = json.loads(ctx.store.get(result["output_ref"]).decode("utf8"))
        except (GabrielError, ValueError, UnicodeDecodeError, TypeError) as exc:
            return failed("output_binding", "output bytes unavailable or not JSON: " + str(exc)[:200])
        tolerance = float(oracle.get("tolerance_micro", 0)) / 1e6
        if "identity" in oracle:  # graph.snapshot: the independently recomputed snapshot identity and the vertex count
            snapshot = output.get("snapshot") if isinstance(output.get("snapshot"), dict) else {}
            vertices = snapshot.get("vertices")
            count = len(vertices) if isinstance(vertices, list) else None
            ok = snapshot.get("identity") == oracle["identity"] and count == oracle.get("vertices")
            return ("passed" if ok else "failed"), dict(evidence, failure_class="none" if ok else "structure", identity=snapshot.get("identity"),
                                                        expected_identity=oracle["identity"], vertices=count, expected_vertices=oracle.get("vertices"))
        if "masses" in oracle:  # graph.region_mass: masses within tolerance and identical decisions at identical times
            got, expected = output.get("values"), oracle["masses"]
            if not isinstance(got, list) or len(got) != len(expected):
                return failed("rows", "row count %s differs from the reference %d" % (len(got) if isinstance(got, list) else None, len(expected)))
            worst = 0.0
            for (t_e, m_e, d_e), item in zip(expected, got):
                if not isinstance(item, dict) or item.get("time_bits") != t_e:
                    return failed("deviation", "time %r differs from the reference %r" % (item.get("time_bits") if isinstance(item, dict) else item, t_e))
                try:
                    worst = max(worst, abs(_binary64(item.get("mass_bits")) - float(m_e)))
                except (ValueError, TypeError):
                    return failed("structure", "mass at %s is not a binary64 bit string" % t_e)
                if item.get("decision") != d_e:
                    return failed("structure", "decision %r differs from the reference %r at %s" % (item.get("decision"), d_e, t_e))
            if worst > tolerance:
                return failed("deviation", "maximum mass deviation %r exceeds tolerance %r" % (worst, tolerance), max_deviation_pico=int(worst * 1e12))
            return "passed", dict(evidence, rows=len(got), max_deviation_pico=int(worst * 1e12), tolerance_micro=int(tolerance * 1e6))
        if "statuses" in oracle:  # graph.window_reachability: certified statuses per window
            got = output.get("statuses")
            ok = got == oracle["statuses"] and output.get("stage") == "certified"
            return ("passed" if ok else "failed"), dict(evidence, failure_class="none" if ok else "structure", statuses=got, expected_statuses=oracle["statuses"],
                                                        stage=output.get("stage"))
        if "readout" in oracle:  # graph.state_readout: structure exact, carrier admissible, metrics within tolerance
            got, expected = output.get("ticks"), oracle["readout"]
            if output.get("kind") != "state_readout" or not isinstance(got, list) or len(got) != len(expected):
                return failed("rows", "readout kind or step count differs from the reference")
            worst = 0.0
            for item, ref in zip(got, expected):
                if not isinstance(item, dict) or item.get("tick") != ref["tick"] or item.get("vertices") != ref["vertices"] or item.get("edges") != ref["edges"]:
                    return failed("structure", "step structure differs from the reference at tick %r" % (ref["tick"],))
                if item.get("kairos") is not ref["kairos"]:
                    return failed("structure", "gate verdict differs from the reference at tick %r" % (ref["tick"],))
                if not isinstance(item.get("carrier"), dict) or item["carrier"].get("index") not in ref["admissible_carriers"]:
                    return failed("structure", "active carrier is not admissible at tick %r" % (ref["tick"],))
                try:
                    worst = max(worst, max(abs(_binary64(item.get("metrics", {}).get(name)) - float(ref["metrics"][name])) for name in ref["metrics"]))
                except (ValueError, TypeError, AttributeError):
                    return failed("structure", "metrics at tick %r are not binary64 bit strings" % (ref["tick"],))
            if worst > tolerance:
                return failed("deviation", "maximum metric deviation %r exceeds tolerance %r" % (worst, tolerance), max_deviation_pico=int(worst * 1e12))
            return "passed", dict(evidence, rows=len(got), max_deviation_pico=int(worst * 1e12), tolerance_micro=int(tolerance * 1e6))
        if "detection_ticks" in oracle:  # graph.detections: the admitted gate crossings, exactly
            found = output.get("detections")
            ticks = [d.get("tick") for d in found] if isinstance(found, list) and all(isinstance(d, dict) for d in found) else None
            vertices = [d.get("vertices") for d in found] if ticks is not None else None
            ok = output.get("kind") == "detections" and ticks == oracle["detection_ticks"] and ("detection_vertices" not in oracle or vertices == oracle["detection_vertices"])
            return ("passed" if ok else "failed"), dict(evidence, failure_class="none" if ok else "structure", detection_ticks=ticks,
                                                        expected_detection_ticks=oracle["detection_ticks"])
        if "values" in oracle:
            expected = oracle["values"]
            got = output.get("values")
            if not isinstance(got, list) or len(got) != len(expected):
                return failed("rows", "row count %s differs from the reference %d" % (len(got) if isinstance(got, list) else None, len(expected)))
            worst = 0.0
            for (t_e, v_e), (t_g, v_g) in zip(expected, got):
                if t_e != t_g:
                    return failed("deviation", "time stamp %r differs from the reference %r" % (t_g, t_e))
                worst = max(worst, abs(float(v_g) - float(v_e)))
            if worst > tolerance:
                return failed("deviation", "maximum deviation %r exceeds tolerance %r" % (worst, tolerance), max_deviation_micro=int(worst * 1e6))
            return "passed", dict(evidence, rows=len(got), max_deviation_micro=int(worst * 1e6), tolerance_micro=int(tolerance * 1e6))
        if "signature" in oracle:
            ok = output.get("signature") == oracle["signature"] and output.get("vertices") == oracle.get("vertices")
            return ("passed" if ok else "failed"), dict(evidence, failure_class="none" if ok else "structure", signature=output.get("signature"),
                                                        expected_signature=oracle["signature"], vertices=output.get("vertices"), expected_vertices=oracle.get("vertices"))
        return "inconclusive", dict(evidence, reason="reference contract declares neither values nor a signature")


class NumericalOutputValidVerifier(OutputValidVerifier):
    SLOT_SCHEMAS = {"snapshot": "numerical-snapshot", "job_result": "numerical-job-result", "witness": "run-witness", "read_back": "read-back",
                    "review": "software-review", "verification": None, "request": "model-request", "envelope": None, "raw_response": None,
                    "patch": None, "model_output": None}


# ===================================================================== pack

class NumericalPack(DomainPack):
    namespace, pack_id, pack_version = NAMESPACE, PACK_ID, PACK_VERSION
    task_noun = "numerical transformation"
    snapshot_schema, proposal_schema, candidate_schema = "numerical-snapshot", "numerical-job-proposal", "numerical-job"
    normalization_profile_id = "numerical-job-v1"
    output_slots, retry_class, verifier_ids = OUTPUT_SLOTS, RETRY_CLASS, SUPPORTED_KINDS

    def __init__(self, provider_factory, backend_resolver):
        self.provider_factory = provider_factory
        self.backend_resolver = backend_resolver

    def reservation(self, capability, profile):
        if capability == "numerical.run_job":
            return usage(cpu_ms=300000)
        return super().reservation(capability, profile)

    def register(self, registry) -> None:
        def desc(tool_id, effect, reconciliation, key, slot=None, forms=("worktree",)):
            return descriptor(tool_id, effect, reconciliation, key, pack_label="numerical", observation_slot=slot, forms=forms)
        registry.register_tool(desc("numerical.observe", "read", "read_back", "read", "snapshot"), ObserveTool())
        registry.register_tool(desc("numerical.run_job", "local_reversible_write", "read_back", "writer"), RunJobTool(self.backend_resolver))
        registry.register_tool(desc("numerical.read_back", "read", "read_back", "read", "snapshot"), ReadBackTool())
        registry.register_tool(desc("numerical.verify", "read", "read_back", "read"), VerifyTool())
        registry.register_tool(desc("numerical.review", "read", "read_back", "read"), ReviewTool())
        if registry.tool_or_none("model.generate") is None:
            registry.register_tool(desc("model.generate", "external_idempotent_effect", "same_key_retry", "model", forms=("provider",)),
                                   ModelGenerateTool(self.provider_factory))
        for verifier_id, kind, impl in [("numerical.reference_contract", "numerical/reference_contract", ReferenceContractVerifier()),
                                        ("numerical.diff_in_scope", "numerical/diff_in_scope", DiffInScopeVerifier()),
                                        ("numerical.base_commit_pinned", "numerical/base_commit_pinned", BaseCommitPinnedVerifier()),
                                        ("numerical.checks_intact", "numerical/checks_intact", ChecksIntactVerifier()),
                                        ("numerical.no_secrets", "numerical/no_secrets", NoSecretsVerifier()),
                                        ("numerical.output_valid", "owner/output_valid", NumericalOutputValidVerifier())]:
            registry.register_verifier({"verifier_id": verifier_id, "version": "v1", "predicate_kind": kind, "implementation_fingerprint": "0" * 64,
                                        "profile_digest": sha256_hex(verifier_id.encode()), "independent": verifier_id != "numerical.output_valid",
                                        "description": "numerical pack verifier " + verifier_id}, impl)
        registry.register_pack(self.manifest(registry))

    def manifest(self, registry) -> dict:
        def ref(value):
            raw = canonical(value)
            return {"sha256": sha256_hex(raw), "bytes": len(raw), "media_type": "application/json"}
        schema_ref = ref({"schema": "fixture"})
        ports = {}
        for port, tool_id, effect in [("compile", "numerical.observe", "read"), ("observe", "numerical.observe", "read"), ("evaluate", "numerical.verify", "read"),
                                      ("propose", "model.generate", "external_idempotent_effect"), ("execute", "numerical.run_job", "local_reversible_write"),
                                      ("read_back", "numerical.read_back", "read")]:
            impl = registry.tool(tool_id)[0]["implementation_fingerprint"]
            ports[port] = {"capability_id": tool_id, "input_schema_ref": schema_ref, "output_schema_ref": schema_ref,
                           "implementation_ref": {"sha256": impl, "bytes": 0, "media_type": "application/json"}, "effect_class": effect}
        manifest = {"schema": "gabriel.domain-pack/1", "pack_id": PACK_ID, "namespace": NAMESPACE, "pack_version": PACK_VERSION,
                    "manifest_kind": "implementation_release", "ports": ports,
                    "observation_coverage_ref": ref({"observes": ["dataset identity", "declared units and time basis", "row counts", "contract problems"],
                                                     "does_not_observe": ["computed values"]}),
                    "evaluation_profiles": [{"profile_id": "numerical-reference-contract-v1", "spec_ref": ref({"rule": "computed verdict within declared tolerance and units"})}],
                    "transformation_profiles": [{"profile_id": TRANSFORM_PROFILE, "spec_ref": ref({"rule": "loss-preserving compile"})},
                                                {"profile_id": analytical.PROFILE_ID, "spec_ref": ref({"worker_build": worker_build(), "operations": sorted(analytical.OPERATIONS)})},
                                                {"profile_id": native_graph.PROFILE_ID,
                                                 "spec_ref": ref({"worker_source_sha256": sha256_hex(_worker_source("graph.snapshot")), "operations": sorted(native_graph.OPERATIONS),
                                                                  "executables": list(native_graph.BINARIES), "model": native_graph.MODEL,
                                                                  "binding": "executable digests are bound per job and checked before and after every native process"})}],
                    "capability_requirements": ["numerical.observe", "numerical.run_job", "numerical.read_back", "numerical.verify", "numerical.review", "model.generate"],
                    "conventions_ref": ref({"missingness": "absent dataset is not an empty dataset", "time": "unix_ms declared by the dataset; owner sequence numbers for availability",
                                            "units": sorted(analytical.UNITS), "float_model": analytical.FLOAT_MODEL,
                                            "verdicts": ["computed", "out_of_scope", "invalid_input", "unknown"]}),
                    "fixtures": [{"fixture_id": "valid", "port": "evaluate", "case_kind": "valid", "input_ref": schema_ref, "expected_ref": schema_ref},
                                 {"fixture_id": "invalid", "port": "evaluate", "case_kind": "invalid", "input_ref": schema_ref, "expected_ref": schema_ref},
                                 {"fixture_id": "out_of_scope", "port": "evaluate", "case_kind": "out_of_scope", "input_ref": schema_ref, "expected_ref": schema_ref}]}
        return validate(manifest, "domain-pack")

    # ---------------------------------------------------------------- routing (ADR-24)
    def default_policy(self) -> dict | None:
        """The readout promoted on the numerical decision families (`policies/readout-channels-v2.json`,
        provenance beside it) is the routing policy of a numerical task that pins none; without a
        shipped readout the rule-based policy applies."""
        path = Path(__file__).parent / "policies" / "readout-channels-v2.json"
        if not path.is_file():
            return None
        return validate(loads(path.read_bytes()), "router-policy")

    def progress_channels(self, projection: dict, store) -> dict | None:
        """ADR-24: the numerical pack's declared channels at a decision point, read from the retained
        evidence of the latest reference-contract verification. Every value is a committed fact of
        the run, never a judgement: whether the job's observed input dataset carried contract
        problems, and the class of the verification's failure (the worker refused the job; the
        operation or output path differ from the contract; the units differ; the row count differs;
        values or structure deviate; the output could not be bound to the job result). A
        verification that has not run leaves every channel missing, so a layout-bound readout
        abstains and the rule applies."""
        values = {name: None for name in PROGRESS_CHANNELS}
        reference = set()
        for check in projection["task"]["checks"]:
            try:
                if loads(store.get(check["spec_ref"]))["predicate_kind"] == "numerical/reference_contract":
                    reference.add(check["check_id"])
            except (GabrielError, ValueError, KeyError):
                continue
        latest = None
        for entry in projection["assessments"].values():
            if entry["check_id"] in reference and entry["outcome"] in ("passed", "failed"):
                key = (len(entry["node_id"]), entry["node_id"])
                if latest is None or key > latest[0]:
                    latest = (key, entry)
        channels = {"schema_id": PROGRESS_SCHEMA_ID, "names": list(PROGRESS_CHANNELS), "values": values}
        if latest is None:
            return channels
        try:
            record = loads(store.get(latest[1]["evidence_ref"]), ascii_only=False)
        except (GabrielError, ValueError):
            return channels
        evidence = record["evidence"] if isinstance(record.get("evidence"), dict) else record
        failure_class = evidence.get("failure_class")
        if failure_class in FAILURE_CLASSES:
            values.update(verdict_refused=1.0 if failure_class == "verdict" else 0.0, contract_mismatch=1.0 if failure_class == "contract" else 0.0,
                          units_mismatch=1.0 if failure_class == "units" else 0.0, rows_mismatch=1.0 if failure_class == "rows" else 0.0,
                          deviation_excess=1.0 if failure_class in ("deviation", "structure") else 0.0,
                          output_unbound=1.0 if failure_class == "output_binding" else 0.0)
        problems = evidence.get("input_problems")
        if isinstance(problems, int) and not isinstance(problems, bool):
            values["input_problems"] = 1.0 if problems > 0 else 0.0
        return channels

    # ---------------------------------------------------------------- ports
    def compile_task(self, spec, store, **ids):
        return compile_task(spec, store, **ids)

    def reference_plan_proposal(self, task, binding, repair_round=0):
        return reference_plan_proposal(task, binding, repair_round=repair_round)

    def build_prompt(self, goal_text, binding, snapshot, manifest, store, *, failure_context, round_index, memory=None, principal_id=None, episodes=()):
        prompt, entries = build_prompt(goal_text, binding, snapshot, manifest, store, failure_context=failure_context, round_index=round_index)
        return prompt, entries, []

    def normalize_proposal(self, proposal, snapshot, manifest, binding, store, *, task_id, run_id, proposal_ref, protected, goal_id, policy_digest):
        return normalize_job_proposal(proposal, snapshot, manifest, binding, store, task_id=task_id, run_id=run_id, proposal_ref=proposal_ref,
                                      protected=protected, goal_id=goal_id, policy_digest=policy_digest)

    def node_args(self, capability, declared, helper):
        if capability == "numerical.run_job":
            job_ref, problem = helper.candidate_for(declared["from_node"])
            if job_ref is None:
                raise GabrielError(Code.STALE_EVIDENCE, "no admissible job from %s: %s" % (declared["from_node"], problem))
            return {"job_ref": job_ref}
        if capability == "numerical.read_back":
            return {"pre_snapshot_ref": helper.observed_snapshot_ref}
        if capability == "numerical.verify":
            state = helper.projection["nodes"].get(declared["from_node"])
            if not state or "job_result" not in state["outputs"]:
                raise GabrielError(Code.STALE_EVIDENCE, "no retained job result from " + declared["from_node"])
            return {"job_result_ref": state["outputs"]["job_result"]}
        return {}
