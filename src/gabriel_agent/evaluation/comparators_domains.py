"""Matched comparators for the document and numerical families (protocol 5, ADR-16).

Every system receives the same task contract (goal, declared sources or datasets, allowed
paths, independent oracle), the same provider profile, the same containment backend for Gabriel
and the same per-task budget.

* ``provider_only``: one model request; the proposal is applied (document) or the declared
  operation is executed through the same adapter in process (numerical); declares success
  whenever an admissible deliverable was produced, without verification.
* ``simple_loop``: bounded request -> apply -> own run of the independent checks -> feedback
  loop without owner, journal, memory service or policy; declares success when its own check
  run passes. Its prompt lists the declared sources as plain files (no provenance filtering),
  which is what a minimal agent with the same corpus has.
* ``gabriel_reference_plan``: the Gabriel runner with the pack's reference plan (no planner
  request), the production retrieval view (effective revision, authorized and available
  sources), the contained worker for numerical jobs and the owner's verification loop.
* ``gabriel_plain_sources`` (document only): as above with the declared ``plain`` view, the
  ablation of provenance-aware retrieval (every declared file enters the prompt, revoked or not).
* ``gabriel_all_revisions`` (document only): as above with the declared ``all_revisions`` view,
  the ablation of the revision rule (every eligible revision enters the prompt; revocation and
  authorization still apply).
* ``gabriel``: the model planner instead of the reference plan (planner cost).

Verification is system-independent and content based (``corpus_domains.verify``): citations
are checked against the declared sources, numbers against the reference values, on the final
tree of every run.
"""
from __future__ import annotations

import time
from pathlib import Path

from ..adapters import analytical, native_graph
from ..agent import TaskRunner, Workspace
from ..agent.workspace import DEFAULT_BUDGET
from ..artifacts import ObjectStore
from ..contracts.codec import canonical, sha256_hex
from ..contracts.errors import GabrielError
from ..contracts.schemas import validate
from ..domains.document import pack as document
from ..domains.numerical import pack as numerical
from ..memory import MemoryService
from ..models import ModelGateway, build_model_request, provider_for_profile
from ..policy import router
from ..tools import fs
from ..workers import LinuxNamespaceBackend, TrustedLocalBackend, Worktree
from . import corpus_domains as cd
from .comparators import Budget, Outcome, gabriel_outcome

DOCUMENT_ONLY = ("gabriel_plain_sources", "gabriel_all_revisions", "gabriel_associative", "gabriel_associative_unlabeled", "gabriel_policy")
SYSTEMS = ("provider_only", "simple_loop", "gabriel_reference_plan", "gabriel_plain_sources", "gabriel_all_revisions", "gabriel_associative",
           "gabriel_associative_unlabeled", "gabriel_policy", "gabriel")
BASELINE_VIEW = "plain"   # what a minimal agent with the same corpus sees: the declared files, unfiltered


def applicable(system: str, task) -> bool:
    """The retrieval-view ablations only exist for document tasks."""
    domain = getattr(task, "domain", "software")
    if system in DOCUMENT_ONLY:
        return domain == "document"
    return True


class DomainEvalContext:
    """Per-(task, system, repetition) environment for a document or numerical task."""

    def __init__(self, task: cd.DomainTask, run_dir: Path, provider: dict, budget: Budget, backend_name: str):
        self.task, self.run_dir, self.budget = task, Path(run_dir).resolve(), budget
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.repo = self.run_dir / "repo"
        self.base_commit = cd.materialize(task, self.repo)
        self.oracle_path = cd.write_oracle(task, self.run_dir)
        self.store = ObjectStore.create(self.run_dir / "store")
        self.provider_spec = provider
        self.backend_name = backend_name
        self.backend = LinuxNamespaceBackend() if backend_name == "linux_namespace" else TrustedLocalBackend()
        self.profile = self._profile(provider)
        self.profile_ref = self.store.put(canonical(self.profile), "application/json")
        self.pack = document.DocumentPack(None, None) if task.domain == "document" else numerical.NumericalPack(None, None)
        self.compiled = self.pack.compile_task(
            cd.task_spec(task, self.repo, self.base_commit, self.oracle_path, provider, budget.gabriel_budget(), retrieval_view=BASELINE_VIEW), self.store,
            task_id="eval-" + task.task_id, workspace_id="ws-eval", principal_id="evaluator", grant_id="eval-grant",
            policy_digest="0" * 64, provider_profile_ref=self.profile_ref, containment_backend=backend_name,
            base_commit=self.base_commit, budget=dict(DEFAULT_BUDGET, **budget.gabriel_budget()))
        self.binding = self.compiled.binding
        self.protected = set(self.compiled.refs["protected_paths"])
        self.memory = None
        self.declaration = None
        if task.domain == "document":
            # the baselines' corpus index: the declared files, so that citations can name observation ids
            self.memory = MemoryService.create(self.run_dir / "index.sqlite", self.store, "ws-eval", lambda: 0)
            self.declaration = document.declaration_for(self.compiled.task, self.store)
        self._provider = None
        self._counter = 0
        self.policy = None
        self.episode_seed = None

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

    def close(self):
        if self.memory is not None:
            self.memory.close()
            self.memory = None

    def worktree(self, name: str) -> Worktree:
        return Worktree.create(self.repo, self.base_commit, self.run_dir / "worktrees" / name)

    # ------------------------------------------------------------ shared primitives
    @property
    def output_schema(self) -> str:
        return "document-amendment-proposal" if self.task.domain == "document" else "numerical-job-proposal"

    def call_model(self, prompt: bytes, role: str, step_key: str) -> dict:
        self._counter += 1
        request = build_model_request(request_id="eval-req-%d" % self._counter, task_id="eval-" + self.task.task_id, run_id="eval-run",
                                      provider_profile=self.profile, role=role, prompt_ref=self.store.put(prompt, "text/plain; charset=utf-8"),
                                      evidence_refs=[], observation_ids=[], issue_frontier=0, output_schema_name=self.output_schema,
                                      tool_schema_digest="0" * 64, sampling_config_ref=self.store.put(canonical({"temperature_milli": self.profile["temperature_milli"]}), "application/json"),
                                      max_input_tokens=self.budget.max_input_tokens, max_output_tokens=self.budget.max_output_tokens)
        gateway = ModelGateway(self.store, self.provider(), self.profile)
        return gateway.generate(request, prompt, output_schema_name=self.output_schema, step_key=step_key)

    def snapshot(self, worktree: Worktree):
        if self.task.domain == "document":
            return document.take_snapshot(worktree, self.binding, self.store, 0, memory=self.memory, principal_id="evaluator", declaration=self.declaration,
                                          task_id="eval-" + self.task.task_id, goal=self.task.goal.encode("utf8"), received_at_unix_ms=1)
        return numerical.take_snapshot(worktree, self.binding, self.store, 0)

    def prompt(self, worktree: Worktree, failure_context: list, round_index: int):
        snapshot, manifest = self.snapshot(worktree)
        prompt, _entries, _ids = self.pack.build_prompt(self.task.goal, self.binding, snapshot, manifest, self.store, failure_context=failure_context,
                                                        round_index=round_index, memory=self.memory, principal_id="evaluator")
        return prompt, snapshot, manifest

    def normalize(self, proposal: dict, snapshot: dict, manifest: dict, proposal_ref: dict):
        return self.pack.normalize_proposal(proposal, snapshot, manifest, self.binding, self.store, task_id="eval-" + self.task.task_id, run_id="eval-run",
                                            proposal_ref=proposal_ref, protected=self.protected, goal_id="eval-goal", policy_digest="0" * 64)

    def execute(self, worktree: Worktree, candidate: dict) -> tuple:
        """Apply the deliverable without the owner: file operations for an amendment, the declared
        operation through the same adapter (in process, uncontained) for a numerical job."""
        if self.task.domain == "document":
            with fs.ContainedRoot(str(worktree.path)) as root:
                for op in candidate["operations"]:
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
        job = candidate
        try:
            raw = self.store.get(job["input_ref"])
        except GabrielError as exc:
            return False, exc.message
        if numerical.is_native(job["operation"]):
            # the same native worker file in process (uncontained) with the executables bound by digest; a
            # window certificate goes through the same dedicated host process as the owner's run
            result = native_graph.run_job(job["operation"], job["parameters"], raw, native_graph.binaries())
            payload = native_graph.dumps(result["output"]) if result["verdict"] == "computed" else None
            if payload is not None and numerical.OPERATIONS[job["operation"]].get("certificate"):
                verdict, payload, stage = numerical.certify_output(payload)
                result = {"verdict": verdict, "diagnostics": {"reason": stage.get("reason") or ", ".join(stage.get("statuses") or [])}}
        else:
            result = analytical.run_job(job["operation"], job["parameters"], raw)
            payload = analytical.dumps(result["output"]) if result["verdict"] == "computed" else None
        if result["verdict"] != "computed":
            return False, "domain verdict %s: %s" % (result["verdict"], (result.get("diagnostics") or {}).get("reason", ""))
        with fs.ContainedRoot(str(worktree.path)) as root:
            try:
                root.write(job["output_path"], payload)
            except GabrielError as exc:
                return False, exc.message
        return True, None

    def own_check(self, worktree: Worktree) -> dict:
        """The simple loop's own run of the independent checks (it has the oracle, like the coding loop)."""
        return cd.verify(self.task, Path(worktree.path))


def _tokens(outcome: dict) -> int:
    return outcome["usage"]["model_tokens"]


# ------------------------------------------------------------------ systems

def run_provider_only(ctx: DomainEvalContext, rep: int) -> Outcome:
    started = time.monotonic()
    worktree = ctx.worktree("provider_only-%d" % rep)
    log, statuses, revisions = [], [], []
    prompt, snapshot, manifest = ctx.prompt(worktree, [], 0)
    outcome = ctx.call_model(prompt, "worker", "provider_only")
    statuses.append(outcome["status"])
    revisions.append(outcome["model_revision"])
    tokens = _tokens(outcome)
    declared, reason = False, "no admissible deliverable"
    if outcome["status"] == "completed":
        candidate, loss, problem = ctx.normalize(outcome["normalized"], snapshot, manifest, outcome["normalized_ref"])
        if candidate is None:
            reason = "proposal rejected: " + str(problem)
        else:
            ok, why = ctx.execute(worktree, candidate)
            declared, reason = ok, ("deliverable produced; declared done without verification" if ok else "execution failed: " + str(why))
    else:
        reason = "provider status " + outcome["status"]
    log.append(reason)
    return Outcome("provider_only", ctx.task.task_id, ctx.task.family, rep, declared, reason, 1, tokens,
                   int((time.monotonic() - started) * 1000), statuses, revisions, str(worktree.path), log=log)


def run_simple_loop(ctx: DomainEvalContext, rep: int) -> Outcome:
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
        candidate, loss, problem = ctx.normalize(outcome["normalized"], snapshot, manifest, outcome["normalized_ref"])
        if candidate is None:
            feedback = [{"check_id": "proposal", "text": "your previous proposal was rejected: " + str(problem)}]
            log.append("request %d: proposal rejected: %s" % (requests, problem))
            continue
        ok, why = ctx.execute(worktree, candidate)
        if not ok:
            feedback = [{"check_id": "apply", "text": "your previous deliverable could not be produced: " + str(why)}]
            log.append("request %d: execution failed: %s" % (requests, why))
            continue
        check = ctx.own_check(worktree)
        log.append("request %d: own checks %s" % (requests, "passed" if check["verified"] else "failed: " + "; ".join(check["problems"][:3])))
        if check["verified"]:
            declared, reason = True, "own check run passed after %d request(s)" % requests
            break
        feedback = [{"check_id": "verification", "text": "\n".join(check["problems"])}]
    return Outcome("simple_loop", ctx.task.task_id, ctx.task.family, rep, declared, reason, requests, tokens,
                   int((time.monotonic() - started) * 1000), statuses, revisions, str(worktree.path), timed_out=timed_out, log=log)


def run_gabriel(ctx: DomainEvalContext, rep: int, *, system: str = "gabriel", max_repairs: int = 2, max_plan_versions: int = 4,
               planner_mode: str = "model", view: str = "provenance", policy: dict | None = None) -> Outcome:
    started = time.monotonic()
    ws_dir = ctx.run_dir / ("%s-%d-ws" % (system, rep))
    ws = Workspace.create(ws_dir, backend=ctx.backend_name, allow_trusted_local=(ctx.backend_name == "trusted_local"))
    try:
        spec = cd.task_spec(ctx.task, ctx.repo, ctx.base_commit, ctx.oracle_path, ctx.provider_spec, ctx.budget.gabriel_budget(),
                            max_repairs=max_repairs, max_plan_versions=max_plan_versions, planner_mode=planner_mode)
        if ctx.task.domain == "document":
            spec["retrieval_view"] = view
        # the frozen router policy of the protocol for the policy arm; every other Gabriel arm pins the rule-based
        # policy explicitly, so the arms of protocols 5 to 8 keep their declared meaning after a pack ships a
        # default readout (ADR-15, ADR-22)
        spec["policy"] = policy if policy is not None else router.rule_based()
        spec["provider"] = dict(spec["provider"], max_input_tokens=ctx.budget.max_input_tokens, max_output_tokens=ctx.budget.max_output_tokens)
        history_log = run_history(ws, ctx)
        created = ws.create_task(spec, task_id="task-%s-%s-%d" % (ctx.task.task_id, system, rep))
        summary = TaskRunner(ws, created["task_id"]).run()
        outcome = gabriel_outcome(ws, ws_dir, created, summary, system=system, task_id=ctx.task.task_id, family=ctx.task.family, rep=rep, started=started)
        if history_log:
            outcome.log[:0] = history_log
        return outcome
    finally:
        ws.close()


def run_history(ws, ctx: DomainEvalContext) -> list:
    """ADR-20: the task's declared history tasks run first in the same workspace with their correct
    deliverable through the scripted provider, so what the system established in verified runs is
    the association history of the evaluated run. Every Gabriel arm gets the same history; a
    history run that does not succeed is recorded and the unit continues."""
    log = []
    for history_id in getattr(ctx.task, "history", ()):
        history_task = cd.task_named(history_id)
        oracle = cd.write_oracle(history_task, ctx.run_dir)
        provider = {"kind": "scripted", "provider_id": "scripted-history",
                    "script": {"by_step": {"plan-request": [{"kind": "echo_reference"}]}, "by_role": {"planner": [{"kind": "echo_reference"}], "worker": cd.history_worker_steps(history_task)}}}
        spec = cd.task_spec(history_task, ctx.repo, ctx.base_commit, oracle, provider, ctx.budget.gabriel_budget(), planner_mode="reference",
                            max_repairs=0, max_plan_versions=1, retrieval_view="provenance")
        created = ws.create_task(spec, task_id="history-%s" % history_id)
        summary = TaskRunner(ws, created["task_id"]).run()
        log.append("history %s: %s" % (history_id, summary["state"]))
    return log


RUNNERS = {"provider_only": run_provider_only, "simple_loop": run_simple_loop,
           "gabriel": lambda ctx, rep: run_gabriel(ctx, rep),
           "gabriel_no_repair": lambda ctx, rep: run_gabriel(ctx, rep, system="gabriel_no_repair", max_repairs=0, max_plan_versions=1),
           "gabriel_reference_plan": lambda ctx, rep: run_gabriel(ctx, rep, system="gabriel_reference_plan", planner_mode="reference"),
           "gabriel_plain_sources": lambda ctx, rep: run_gabriel(ctx, rep, system="gabriel_plain_sources", planner_mode="reference", view="plain"),
           "gabriel_all_revisions": lambda ctx, rep: run_gabriel(ctx, rep, system="gabriel_all_revisions", planner_mode="reference", view="all_revisions"),
           "gabriel_associative": lambda ctx, rep: run_gabriel(ctx, rep, system="gabriel_associative", planner_mode="reference", view="associative"),
           "gabriel_associative_unlabeled": lambda ctx, rep: run_gabriel(ctx, rep, system="gabriel_associative_unlabeled", planner_mode="reference",
                                                                         view="associative_unlabeled"),
           # ADR-22: the production configuration (associative view, reference plan) with the protocol's frozen readout pinned
           "gabriel_policy": lambda ctx, rep: run_gabriel(ctx, rep, system="gabriel_policy", planner_mode="reference", view="associative", policy=ctx.policy)}

DECLARED_SUCCESS = {
    "provider_only": "an admissible deliverable was produced (amendment applied or declared operation executed through the same adapter); no verification",
    "simple_loop": "the system's own run of the independent content checks passed (plain source view, no owner, memory service or policy)",
    "gabriel_reference_plan": "run state succeeded with the pack's reference plan and the production retrieval view (effective revision, "
                              "authorized and available sources; contained numerical worker)",
    "gabriel_plain_sources": "as gabriel_reference_plan with the declared plain view: every declared source file enters the prompt regardless of "
                             "revision or revocation (ablation of provenance-aware retrieval; document tasks only)",
    "gabriel_all_revisions": "as gabriel_reference_plan with the declared all_revisions view: every eligible revision enters the prompt, revocation "
                             "and authorization still apply (ablation of the revision rule; document tasks only)",
    "gabriel_associative": "as gabriel_reference_plan with the declared associative view (ADR-20): the provenance view re-ranked by the native engine's "
                           "walk over the co-citation graph of the claims that earlier verified runs in the same workspace established; since ADR-21 a "
                           "carried source is told apart in the prompt with the seed and the verified run that cited them together; document tasks only",
    "gabriel_associative_unlabeled": "as gabriel_associative with the ADR-20 presentation: carried sources enter the prompt like lexically retrieved "
                                     "ones (ablation of the association provenance in the prompt, ADR-21; document tasks only)",
    "gabriel_policy": "as gabriel_associative with the protocol's frozen readout policy pinned (ADR-22): at a failed verification it chooses "
                      "repair or stop from the generic progress channels and the document pack's declared channels; document tasks only",
    "gabriel": "as gabriel_reference_plan with the model planner (one planner request per plan version)",
    "gabriel_no_repair": "as gabriel with max_repairs=0 and max_plan_versions=1 (ablation of the repair cycle)"}


# ------------------------------------------------------------------ independent verification

def verify(ctx: DomainEvalContext, worktree_path: str, marker: str) -> dict:
    """Fresh, system-independent, content-based verification of a final tree."""
    worktree = Worktree.open(worktree_path, ctx.base_commit, ctx.repo)
    outcome = cd.verify(ctx.task, Path(worktree_path))
    patch = worktree.patch()
    outcome.update({"patch_sha256": sha256_hex(patch), "patch_bytes": len(patch), "patch": patch.decode("utf8", "replace")[:20000],
                    "head_is_base": worktree.head() == ctx.base_commit, "marker": marker})
    return outcome
