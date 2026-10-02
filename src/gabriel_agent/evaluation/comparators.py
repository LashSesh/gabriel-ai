"""Matched comparators for the G1 evaluation.

All systems receive the same task contract (goal, allowed paths, visible test
command, independent oracle command and oracle file), the same provider
profile, the same containment backend and the same per-task budget.

* ``provider_only``: one model request, patch applied, no verification;
  declares success whenever an admissible patch was applied.
* ``simple_loop``: bounded request -> apply -> run checks -> feedback loop
  without owner, journal, kernel or policy; declares success when its own
  check runs pass.
* ``gabriel``: the Gabriel runner (owner, scheduler, verifiers, repair
  cycles); declares success only in run state ``succeeded``.
* ``gabriel_no_repair``: ablation of the repair cycle (one plan version, no
  repairs).

Every provider call is made through the same gateway, so raw requests and
responses are retained for every system.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

from ..agent import Workspace, TaskRunner
from ..agent.workspace import DEFAULT_BUDGET
from ..artifacts import ObjectStore
from ..contracts.codec import canonical, loads, sha256_hex
from ..contracts.errors import GabrielError
from ..contracts.schemas import validate
from ..domains.software import pack as software
from ..models import ModelGateway, build_model_request, provider_for_profile
from ..tools import fs
from ..workers import LinuxNamespaceBackend, TrustedLocalBackend, RunSpec, Worktree
from . import corpus

SYSTEMS = ("provider_only", "simple_loop", "gabriel", "gabriel_no_repair", "gabriel_reference_plan")
G3_SYSTEMS = ("gabriel_policy", "gabriel_episodes")


@dataclass
class Budget:
    model_requests: int = 6
    model_tokens_total: int = 120000
    max_input_tokens: int = 60000
    max_output_tokens: int = 4000
    wall_ms: int = 600000
    tool_attempts: int = 64

    def gabriel_budget(self) -> dict:
        return {"model_tokens_total": self.model_tokens_total, "model_requests": self.model_requests,
                "tool_attempts": self.tool_attempts, "elapsed_ms": self.wall_ms}


@dataclass
class Outcome:
    system: str
    task_id: str
    family: str
    rep: int
    declared: bool
    declared_reason: str
    model_requests: int
    model_tokens: int
    wall_ms: int
    provider_statuses: list
    model_revisions: list
    worktree: str
    timed_out: bool = False
    error: str | None = None
    log: list = field(default_factory=list)
    gabriel: dict | None = None
    repairs_used: int = 0
    plan_versions: int = 0

    def to_dict(self):
        return asdict(self)


class EvalContext:
    """Per-(task, system, repetition) environment: repository, oracle, store, backend, profile."""

    def __init__(self, task: corpus.EvalTask, run_dir: Path, provider: dict, budget: Budget, backend_name: str):
        self.task, self.run_dir, self.budget = task, Path(run_dir).resolve(), budget
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.repo = self.run_dir / "repo"
        self.base_commit = corpus.materialize(task, self.repo)
        self.oracle_path = corpus.write_oracle(task, self.run_dir)
        self.oracle_rel = "oracle_%s.py" % task.module
        self.store = ObjectStore.create(self.run_dir / "store")
        self.provider_spec = provider
        self.backend_name = backend_name
        self.backend = LinuxNamespaceBackend() if backend_name == "linux_namespace" else TrustedLocalBackend()
        self.profile = self._profile(provider)
        self.profile_ref = self.store.put(canonical(self.profile), "application/json")
        self.oracle_ref = self.store.put(task.oracle.encode("utf8"), "text/plain; charset=utf-8")
        self.compiled = software.compile_task(
            corpus.task_spec(task, self.repo, self.base_commit, self.oracle_path, provider, budget.gabriel_budget()), self.store,
            task_id="eval-" + task.task_id, workspace_id="ws-eval", principal_id="evaluator", grant_id="eval-grant",
            policy_digest="0" * 64, provider_profile_ref=self.profile_ref, containment_backend=backend_name,
            base_commit=self.base_commit, budget=dict(DEFAULT_BUDGET, **budget.gabriel_budget()))
        self.binding = self.compiled.binding
        self.protected = set(self.compiled.refs["protected_paths"])
        self._provider = None
        self._counter = 0
        self.policy = None          # router policy record of the frozen protocol (G3 arms)
        self.episode_seed = None    # frozen list of {"id", "text"} episodes (G3 arms)

    def _profile(self, provider: dict) -> dict:
        kind = provider.get("kind", "scripted")
        profile = {"schema": "gabriel.provider-profile/1", "provider_id": provider.get("provider_id", "eval-" + kind), "kind": kind,
                   "model_alias": provider.get("model", "fixture-v1"), "endpoint": provider.get("endpoint"),
                   "credential_ref": provider.get("credential_ref"), "max_input_tokens": self.budget.max_input_tokens,
                   "max_output_tokens": self.budget.max_output_tokens, "temperature_milli": int(provider.get("temperature_milli", 0)),
                   "timeout_ms": int(provider.get("timeout_ms", 120000)), "script_ref": None, "data_classes": ["repository_source", "task_goal"],
                   "max_retries": 1}
        if kind == "scripted":
            import json
            profile["script_ref"] = self.store.put(json.dumps(provider.get("script", {})).encode("utf8"), "application/json; charset=utf-8")
        return validate(profile, "provider-profile")

    def provider(self):
        if self._provider is None:
            self._provider = provider_for_profile(self.profile, self.store)
        return self._provider

    def worktree(self, name: str) -> Worktree:
        return Worktree.create(self.repo, self.base_commit, self.run_dir / "worktrees" / name)

    # ------------------------------------------------------------ shared primitives
    def call_model(self, prompt: bytes, role: str, step_key: str, output_schema: str = "software-patch-proposal") -> dict:
        self._counter += 1
        request = build_model_request(request_id="eval-req-%d" % self._counter, task_id="eval-" + self.task.task_id, run_id="eval-run",
                                      provider_profile=self.profile, role=role, prompt_ref=self.store.put(prompt, "text/plain; charset=utf-8"),
                                      evidence_refs=[], observation_ids=[], issue_frontier=0, output_schema_name=output_schema,
                                      tool_schema_digest="0" * 64, sampling_config_ref=self.store.put(canonical({"temperature_milli": self.profile["temperature_milli"]}), "application/json"),
                                      max_input_tokens=self.budget.max_input_tokens, max_output_tokens=self.budget.max_output_tokens)
        gateway = ModelGateway(self.store, self.provider(), self.profile)
        return gateway.generate(request, prompt, output_schema_name=output_schema, step_key=step_key)

    def snapshot(self, worktree: Worktree):
        return software.take_snapshot(worktree, self.binding, self.store, 0)

    def prompt(self, worktree: Worktree, failure_context: list, round_index: int) -> bytes:
        snapshot, manifest = self.snapshot(worktree)
        prompt, _ = software.build_prompt(self.task.goal, self.binding, snapshot, manifest, self.store,
                                          failure_context=failure_context, round_index=round_index)
        return prompt, snapshot, manifest

    def normalize(self, proposal: dict, snapshot: dict, manifest: dict, proposal_ref: dict):
        return software.normalize_patch_proposal(proposal, snapshot, manifest, self.binding, self.store, task_id="eval-" + self.task.task_id,
                                                 run_id="eval-run", proposal_ref=proposal_ref, protected=self.protected,
                                                 goal_id="eval-goal", policy_digest="0" * 64)

    def apply(self, worktree: Worktree, patch: dict) -> tuple[bool, str | None]:
        """Same preconditions as the software pack's execute port, applied without the owner."""
        with fs.ContainedRoot(str(worktree.path)) as root:
            for op in patch["operations"]:
                try:
                    if not fs.path_in_scope(op["path"], self.binding["allowed_paths"]) or op["path"] in self.protected:
                        return False, "out of scope or protected: " + op["path"]
                    exists = root.exists(op["path"])
                    if op["kind"] == "create":
                        if exists:
                            return False, "create target exists: " + op["path"]
                        root.write(op["path"], self.store.get(op["content_ref"]))
                    elif op["kind"] == "modify":
                        if not exists or root.digest(op["path"]) != op["expected_sha256"]:
                            return False, "identity mismatch: " + op["path"]
                        root.write(op["path"], self.store.get(op["content_ref"]))
                    else:
                        if not exists or root.digest(op["path"]) != op["expected_sha256"]:
                            return False, "identity mismatch: " + op["path"]
                        root.delete(op["path"])
                except GabrielError as exc:
                    return False, exc.message
        return True, None

    def run_check(self, worktree: Worktree, argv: list, with_oracle: bool, marker: str) -> dict:
        """Run a check command in the containment backend; the oracle is installed fresh and removed after."""
        if with_oracle:
            with fs.ContainedRoot(str(worktree.path)) as root:
                root.write(self.oracle_rel, self.task.oracle.encode("utf8"))
        witness = self.backend.run(RunSpec(argv=list(argv), worktree=str(worktree.path), timeout_ms=60000, max_output_bytes=1 << 20, marker=marker))
        if with_oracle:
            with fs.ContainedRoot(str(worktree.path)) as root:
                try:
                    root.delete(self.oracle_rel)
                except GabrielError:
                    pass
        return {"argv": list(argv), "exit_code": witness.exit_code, "timed_out": witness.timed_out, "start_failure": witness.start_failure,
                "stdout_tail": witness.stdout.captured[-1500:].decode("utf8", "replace"),
                "stderr_tail": witness.stderr.captured[-1500:].decode("utf8", "replace"), "backend": witness.backend_kind}


def _tokens(outcome: dict) -> int:
    return outcome["usage"]["model_tokens"]


# ------------------------------------------------------------------ systems

def run_provider_only(ctx: EvalContext, rep: int) -> Outcome:
    started = time.monotonic()
    worktree = ctx.worktree("provider_only-%d" % rep)
    log, statuses, revisions = [], [], []
    prompt, snapshot, manifest = ctx.prompt(worktree, [], 0)
    outcome = ctx.call_model(prompt, "worker", "provider_only")
    statuses.append(outcome["status"])
    revisions.append(outcome["model_revision"])
    tokens = _tokens(outcome)
    declared, reason = False, "no admissible patch"
    if outcome["status"] == "completed":
        patch, loss, problem = ctx.normalize(outcome["normalized"], snapshot, manifest, outcome["normalized_ref"])
        if patch is None:
            reason = "proposal rejected: " + str(problem)
        else:
            ok, why = ctx.apply(worktree, patch)
            declared, reason = ok, ("patch applied; declared done without verification" if ok else "apply failed: " + str(why))
    else:
        reason = "provider status " + outcome["status"]
    log.append(reason)
    return Outcome("provider_only", ctx.task.task_id, ctx.task.family, rep, declared, reason, 1, tokens,
                   int((time.monotonic() - started) * 1000), statuses, revisions, str(worktree.path), log=log)


def run_simple_loop(ctx: EvalContext, rep: int) -> Outcome:
    started = time.monotonic()
    worktree = ctx.worktree("simple_loop-%d" % rep)
    log, statuses, revisions = [], [], []
    requests, tokens = 0, 0
    feedback = []
    declared, reason, timed_out = False, "budget exhausted without passing checks", False
    while requests < ctx.budget.model_requests and tokens < ctx.budget.model_tokens_total:
        if (time.monotonic() - started) * 1000 > ctx.budget.wall_ms:
            timed_out, reason = True, "wall-clock limit"
            break
        prompt, snapshot, manifest = ctx.prompt(worktree, feedback, requests)
        outcome = ctx.call_model(prompt, "worker", "simple_loop")
        requests += 1
        tokens += _tokens(outcome)
        statuses.append(outcome["status"])
        revisions.append(outcome["model_revision"])
        if outcome["status"] != "completed":
            feedback = [{"check_id": "provider", "text": "previous request ended with status %s: %s" % (outcome["status"], outcome["envelope"].get("error"))}]
            log.append("request %d: %s" % (requests, outcome["status"]))
            continue
        patch, loss, problem = ctx.normalize(outcome["normalized"], snapshot, manifest, outcome["normalized_ref"])
        if patch is None:
            feedback = [{"check_id": "proposal", "text": "your previous proposal was rejected: " + str(problem)}]
            log.append("request %d: proposal rejected: %s" % (requests, problem))
            continue
        ok, why = ctx.apply(worktree, patch)
        if not ok:
            feedback = [{"check_id": "apply", "text": "your previous patch could not be applied: " + str(why)}]
            log.append("request %d: apply failed: %s" % (requests, why))
            continue
        visible = ctx.run_check(worktree, corpus.visible_argv(ctx.task), False, "eval-sl-%d-%d" % (rep, requests))
        oracle = ctx.run_check(worktree, corpus.oracle_argv(ctx.task), True, "eval-slo-%d-%d" % (rep, requests))
        log.append("request %d: visible exit %s, oracle exit %s" % (requests, visible["exit_code"], oracle["exit_code"]))
        if visible["exit_code"] == 0 and oracle["exit_code"] == 0:
            declared, reason = True, "own check runs passed after %d request(s)" % requests
            break
        feedback = [{"check_id": "unit", "text": "exit %s\n%s" % (visible["exit_code"], visible["stderr_tail"])},
                    {"check_id": "oracle", "text": "exit %s\n%s" % (oracle["exit_code"], oracle["stderr_tail"])}]
    return Outcome("simple_loop", ctx.task.task_id, ctx.task.family, rep, declared, reason, requests, tokens,
                   int((time.monotonic() - started) * 1000), statuses, revisions, str(worktree.path), timed_out=timed_out, log=log)


def run_gabriel(ctx: EvalContext, rep: int, *, system: str = "gabriel", max_repairs: int = 2, max_plan_versions: int = 4,
               planner_mode: str = "model", policy: dict | None = None, episode_seed: list | None = None) -> Outcome:
    started = time.monotonic()
    ws_dir = ctx.run_dir / ("%s-%d-ws" % (system, rep))
    ws = Workspace.create(ws_dir, backend=ctx.backend_name, allow_trusted_local=(ctx.backend_name == "trusted_local"))
    try:
        spec = corpus.task_spec(ctx.task, ctx.repo, ctx.base_commit, ctx.oracle_path, ctx.provider_spec, ctx.budget.gabriel_budget(),
                               max_repairs=max_repairs, max_plan_versions=max_plan_versions, planner_mode=planner_mode)
        spec["provider"] = dict(spec["provider"], max_input_tokens=ctx.budget.max_input_tokens, max_output_tokens=ctx.budget.max_output_tokens)
        if policy is not None:
            spec["policy"] = policy
        for episode in episode_seed or []:
            # scoped past cases from the frozen seed enter this workspace's memory before the run; the
            # worker request records which of them entered the prompt
            ws.memory.ingest(source_id="episode", source_object_id=episode["id"], source_revision=1, content=episode["text"].encode("utf8"),
                             received_at_unix_ms=1, extraction_digest=sha256_hex(b"episode/1"),
                             scope={"principals": [ws.config["principal_id"]], "source_kind": "episode", "task_id": None})
        created = ws.create_task(spec, task_id="task-%s-%s-%d" % (ctx.task.task_id, system, rep))
        summary = TaskRunner(ws, created["task_id"]).run()
        projection = ws.owner.projection(summary["run_id"])
        statuses, revisions = [], []
        for attempt in projection["attempts"].values():
            if attempt["capability_id"] == "model.generate" and attempt["result_ref"]:
                result = loads(ws.store.get(attempt["result_ref"]))
                statuses.append(result["status"])
                for output in result["outputs"]:
                    if output["output_slot"] == "envelope":
                        revisions.append(loads(ws.store.get(output["artifact_ref"])).get("model_revision"))
        replay = ws.owner.replay()
        deadline = projection["run_meta"]["hold"] is not None and projection["run_meta"]["hold"]["reason_code"] in ("budget_exhausted", "planner_budget_exhausted")
        return Outcome(system, ctx.task.task_id, ctx.task.family, rep, summary["state"] == "succeeded", "run state " + summary["state"],
                       summary["spent"]["model_requests"], summary["spent"]["model_tokens"], int((time.monotonic() - started) * 1000),
                       statuses, sorted({r for r in revisions if r}), created["worktree"], timed_out=deadline,
                       log=summary["log"][-12:], gabriel={"run_id": summary["run_id"], "workspace": str(ws_dir), "hold": summary["hold"],
                                                          "replay": replay["status"], "events": replay["events"],
                                                          "assessments": summary["assessments"]},
                       repairs_used=summary["repair_count"], plan_versions=summary["plan_versions"])
    finally:
        ws.close()


RUNNERS = {"provider_only": run_provider_only, "simple_loop": run_simple_loop,
           "gabriel": lambda ctx, rep: run_gabriel(ctx, rep),
           "gabriel_no_repair": lambda ctx, rep: run_gabriel(ctx, rep, system="gabriel_no_repair", max_repairs=0, max_plan_versions=1),
           "gabriel_reference_plan": lambda ctx, rep: run_gabriel(ctx, rep, system="gabriel_reference_plan", planner_mode="reference"),
           # G3 arms: the pinned readout policy (decides repair versus stop, may retrieve episodes) and
           # the rule-based policy with episodic retrieval only (ablation of the readout)
           # both use the reference plan (no planner request), like gabriel_reference_plan, their matched comparator
           "gabriel_policy": lambda ctx, rep: run_gabriel(ctx, rep, system="gabriel_policy", planner_mode="reference", policy=ctx.policy, episode_seed=ctx.episode_seed),
           "gabriel_episodes": lambda ctx, rep: run_gabriel(ctx, rep, system="gabriel_episodes", planner_mode="reference", policy=_rule_with_episodes(ctx),
                                                            episode_seed=ctx.episode_seed)}


def _rule_with_episodes(ctx: EvalContext) -> dict:
    from ..policy import router
    k = int((ctx.policy or {}).get("episodes", {}).get("k", 3)) or 3
    return router.rule_based(episodes=k)


# ------------------------------------------------------------------ independent verification

def verify(ctx: EvalContext, worktree_path: str, marker: str) -> dict:
    """Fresh, system-independent verification of a final tree: scope, visible tests, oracle."""
    worktree = Worktree.open(worktree_path, ctx.base_commit, ctx.repo)
    changed = worktree.changed_paths()
    changed = [p for p in changed if p != ctx.oracle_rel]
    out_of_scope = [p for p in changed if not fs.path_in_scope(p, ctx.binding["allowed_paths"])]
    visible = ctx.run_check(worktree, corpus.visible_argv(ctx.task), False, marker + "-v")
    oracle = ctx.run_check(worktree, corpus.oracle_argv(ctx.task), True, marker + "-o")
    patch = worktree.patch()
    verified = not out_of_scope and visible["exit_code"] == 0 and oracle["exit_code"] == 0
    return {"verified": verified, "changed_paths": changed, "out_of_scope_paths": out_of_scope, "visible": visible, "oracle": oracle,
            "patch_sha256": sha256_hex(patch), "patch_bytes": len(patch), "patch": patch.decode("utf8", "replace")[:20000],
            "head_is_base": worktree.head() == ctx.base_commit}
