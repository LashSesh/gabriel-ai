"""Workspace: configuration, principals, object store, journal, registry and backends.

Layout: ``config.json`` (gabriel.workspace-config/1), ``journal.sqlite``,
``objects/``, ``credentials/<principal>.secret`` (0600, never journaled),
``worktrees/<run_id>`` and ``runs/<run_id>.json`` (derivable runtime notes).
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

from .. import __version__
from ..artifacts import ObjectStore
from ..contracts.codec import canonical, digest, loads
from ..contracts.errors import Code, GabrielError
from ..contracts.schemas import registry_digest, validate, validate_bytes
from ..domains.document import DocumentPack
from ..domains.numerical import NumericalPack
from ..domains.software import SoftwarePack
from ..memory import MemoryService
from ..models import provider_for_profile
from ..policy.principals import Credential, new_secret, secret_digest
from ..state import Owner
from ..tools import ToolRegistry
from ..workers import LinuxNamespaceBackend, TrustedLocalBackend, Worktree, backend_for, probe_backends
from ..workers.worktree import git

DEFAULT_BUDGET = {"model_tokens_total": 20000, "model_requests": 12, "tool_attempts": 64, "cpu_ms": 1800000, "elapsed_ms": 1800000,
                  "artifact_bytes": 16777216, "scratch_bytes": 1073741824, "currency_micro_units": 0, "currency": "EUR",
                  "concurrent_reads": 4, "concurrent_writes_per_resource": "one"}
RESOURCES = ["worktree", "provider", "delivery"]
GRANTED_EFFECTS = ["read", "local_reversible_write", "external_idempotent_effect"]
POLICY_ID = "gabriel.local-single-user/1"


def build_packs(backend_resolver) -> dict:
    """Every registered DomainPack, keyed by namespace. One registry serves all of them: the
    catalog digest a workspace pins covers the software, document and numerical packs alike."""
    packs = [SoftwarePack(provider_for_profile, backend_resolver), DocumentPack(provider_for_profile, backend_resolver),
             NumericalPack(provider_for_profile, backend_resolver)]
    return {pack.namespace: pack for pack in packs}


def build_registry(backend_resolver) -> ToolRegistry:
    registry = ToolRegistry()
    for pack in build_packs(backend_resolver).values():
        pack.register(registry)
    return registry


class Workspace:
    def __init__(self, path: Path, config: dict, owner: Owner, store: ObjectStore, registry: ToolRegistry, credential: Credential, memory=None, packs=None):
        self.path, self.config, self.owner, self.store, self.registry, self.credential = Path(path), config, owner, store, registry, credential
        self.memory = memory
        self.packs = packs or build_packs(lambda: None)
        self._backend = None

    def pack_for(self, namespace: str):
        try:
            return self.packs[namespace]
        except KeyError:
            raise GabrielError(Code.UNSUPPORTED, "no registered domain pack for namespace " + str(namespace))

    def policy_for(self, task: dict) -> dict:
        """The routing policy pinned by the task (a policy-pin record among its base inputs);
        the rule-based policy when none is pinned. The pin's digest must match the artifact."""
        from ..policy import router
        for ref in task["base_inputs"]:
            record = loads(self.store.get(ref))
            if record.get("schema") == "gabriel.policy-pin/1":
                validate(record, "policy-pin")
                policy = validate_bytes(self.store.get(record["policy_ref"]), "router-policy")
                if router.policy_digest(policy) != record["policy_digest"]:
                    raise GabrielError(Code.STALE_EVIDENCE, "pinned policy artifact does not match the pin digest")
                return policy
        return router.rule_based()

    def pin_policy(self, policy: dict) -> dict:
        """Store a routing policy and return the pin record's artifact reference."""
        from ..policy import router
        validate(policy, "router-policy")
        policy_ref = self.store.put(canonical(policy), "application/json")
        pin = {"schema": "gabriel.policy-pin/1", "policy_id": policy["policy_id"], "policy_ref": policy_ref,
               "policy_digest": router.policy_digest(policy), "selected_by": self.config["principal_id"]}
        validate(pin, "policy-pin")
        return self.store.put(canonical(pin), "application/json")

    # ------------------------------------------------------------ lifecycle
    @classmethod
    def create(cls, path, *, workspace_id=None, principal_id="local-user", backend="linux_namespace", allow_trusted_local=False, clock=None):
        path = Path(path)
        if path.exists() and any(path.iterdir()):
            raise GabrielError(Code.STORAGE_FAULT, "workspace directory is not empty: " + str(path))
        path.mkdir(parents=True, exist_ok=True)
        workspace_id = workspace_id or ("ws-" + hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:12])
        store = ObjectStore.create(path / "objects")
        registry = build_registry(lambda: None)
        secret = new_secret()
        (path / "credentials").mkdir(mode=0o700)
        secret_path = path / "credentials" / (principal_id + ".secret")
        fd = os.open(secret_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write(secret)
        config = {"schema": "gabriel.workspace-config/1", "schema_version": 1, "workspace_id": workspace_id, "principal_id": principal_id,
                  "artifact_root": "objects", "database": "journal.sqlite", "registry_digest": registry.catalog_digest(),
                  "containment_backend": backend, "allow_trusted_local": bool(allow_trusted_local), "default_limits": DEFAULT_BUDGET,
                  "config_revision": 0, "provider_profile_ref": None}
        validate(config, "workspace-config")
        (path / "config.json").write_bytes(canonical(config) + b"\n")
        owner = Owner.create(path / "journal.sqlite", store, workspace_id, registry.catalog(),
                             principals={principal_id: secret_digest(secret)}, clock=clock)
        (path / "worktrees").mkdir()
        (path / "runs").mkdir()
        memory = MemoryService.create(path / "memory.sqlite", store, workspace_id, lambda: owner.anchor()["sequence"])
        return cls(path, config, owner, store, registry, Credential(principal_id, secret), memory=memory)

    @classmethod
    def open(cls, path, *, clock=None):
        path = Path(path)
        config_path = path / "config.json"
        if not config_path.is_file():
            raise GabrielError(Code.STORAGE_FAULT, "not a Gabriel workspace: " + str(path))
        config = validate(loads(config_path.read_bytes()), "workspace-config")
        store = ObjectStore.open(path / config["artifact_root"])
        registry = build_registry(lambda: None)
        owner = Owner.open(path / config["database"], store, registry.catalog(), clock=clock)
        secret_path = path / "credentials" / (config["principal_id"] + ".secret")
        secret = secret_path.read_text().strip()
        memory_path = path / "memory.sqlite"
        if memory_path.is_file():
            memory = MemoryService.open(memory_path, store, lambda: owner.anchor()["sequence"])
        else:  # a restored workspace without a memory index starts an empty one
            memory = MemoryService.create(memory_path, store, config["workspace_id"], lambda: owner.anchor()["sequence"])
        ws = cls(path, config, owner, store, registry, Credential(config["principal_id"], secret), memory=memory)
        # the registry's backend resolver is bound after construction
        return ws

    def close(self):
        self.owner.close()
        if self.memory is not None:
            self.memory.close()

    @property
    def backend(self):
        if self._backend is None:
            self._backend = backend_for(self.config["containment_backend"], self.config["allow_trusted_local"])
        return self._backend

    # ------------------------------------------------------------ doctor
    def doctor(self, selftest: bool = False) -> dict:
        probes = probe_backends()
        if selftest:
            probes["linux_namespace"] = LinuxNamespaceBackend().probe(selftest=True)
        configured = self.config["containment_backend"]
        report = {"workspace_id": self.config["workspace_id"], "version": __version__, "python": platform.python_version(),
                  "platform": platform.platform(), "configured_backend": configured, "backends": probes,
                  "registry_loaded": self.registry.verify_loaded(), "catalog_digest": self.owner.catalog_digest,
                  "schema_registry_digest": registry_digest(), "journal": self.owner.anchor(),
                  "object_store": self.store.fsck([]), "effective_limits": self.config["default_limits"],
                  "git": subprocess.run(["git", "--version"], capture_output=True, text=True).stdout.strip() or "missing"}
        problems = []
        if configured == "linux_namespace" and not probes["linux_namespace"]["available"]:
            problems.append("configured containment backend linux_namespace is unavailable: " + "; ".join(probes["linux_namespace"]["reasons"]))
        if configured == "trusted_local":
            problems.append("trusted_local is an explicitly separate trusted mode: untrusted repository code must not be executed in it")
            if not self.config["allow_trusted_local"]:
                problems.append("trusted_local requires allow_trusted_local in the workspace configuration")
        if probes["linux_namespace"]["checks"].get("jail_selftest") == "not_executed":
            problems.append("linux_namespace jail self-test not executed (run doctor --selftest on a Linux host that permits namespaces)")
        report["problems"] = problems
        report["untrusted_execution_supported"] = configured == "linux_namespace" and probes["linux_namespace"]["available"] and probes["linux_namespace"]["checks"].get("jail_selftest") not in ("not_executed", None)
        return report

    # ------------------------------------------------------------ tasks
    def _grant_policy_digest(self) -> str:
        return digest({"policy": POLICY_ID, "tools": sorted(self.registry.catalog()["tools"]), "effects": GRANTED_EFFECTS,
                       "resources": RESOURCES, "catalog_digest": self.owner.catalog_digest})

    def provider_profile(self, provider_spec: dict) -> dict:
        kind = provider_spec.get("kind", "scripted")
        profile = {"schema": "gabriel.provider-profile/1", "provider_id": provider_spec.get("provider_id", kind + "-provider"), "kind": kind,
                   "model_alias": provider_spec.get("model", "fixture-v1"), "endpoint": provider_spec.get("endpoint"),
                   "credential_ref": provider_spec.get("credential_ref"), "max_input_tokens": int(provider_spec.get("max_input_tokens", 12000)),
                   "max_output_tokens": int(provider_spec.get("max_output_tokens", 4000)), "temperature_milli": int(provider_spec.get("temperature_milli", 0)),
                   "timeout_ms": int(provider_spec.get("timeout_ms", 120000)), "script_ref": None,
                   "data_classes": list(provider_spec.get("data_classes", ["repository_source", "task_goal"])), "max_retries": int(provider_spec.get("max_retries", 1))}
        if kind == "scripted":
            script = provider_spec.get("script")
            raw = json.dumps(script).encode("utf8") if isinstance(script, dict) else Path(script).read_bytes()
            profile["script_ref"] = self.store.put(raw, "application/json; charset=utf-8")
        return validate(profile, "provider-profile")

    def create_task(self, spec: dict, *, task_id=None) -> dict:
        """Compile, register the grant, admit the task and prepare its worktree."""
        repository = Path(spec["repository"]).resolve()
        base_commit = spec.get("base_commit") or git(["rev-parse", "HEAD"], repository).stdout.strip()
        if git(["rev-parse", "--verify", base_commit + "^{commit}"], repository, check=False).returncode != 0:
            raise GabrielError(Code.UNKNOWN_OBJECT, "base commit not found in repository: " + base_commit)
        task_id = task_id or ("task-" + hashlib.sha256((str(repository) + base_commit + str(time.time())).encode()).hexdigest()[:12])
        run_id = task_id.replace("task-", "run-", 1) + "-1"
        grant_id = task_id + "-grant"
        profile_ref = self.store.put(canonical(self.provider_profile(spec.get("provider", {"kind": "scripted", "script": {}}))), "application/json")
        budget = dict(DEFAULT_BUDGET, **(spec.get("budget") or {}))
        policy = self._grant_policy_digest()
        pack = self.pack_for(spec.get("domain", "software"))
        compiled = pack.compile_task(dict(spec, repository=str(repository)), self.store, task_id=task_id, workspace_id=self.config["workspace_id"],
                                     principal_id=self.config["principal_id"], grant_id=grant_id, policy_digest=policy, provider_profile_ref=profile_ref,
                                     containment_backend=self.config["containment_backend"], base_commit=base_commit, budget=budget)
        if not compiled.admissible:
            unresolved = [c for c in compiled.report["clauses"] if c["mandatory"] and c["status"] != "mapped"]
            raise GabrielError(Code.POLICY_DENIED, "task is not admissible: " + "; ".join("%s: %s" % (c["clause_id"], c["reason"]) for c in unresolved),
                               details={"compilation_report": compiled.report, "problems": compiled.problems})
        if spec.get("policy") is not None:
            # Production tasks pin one policy version; promotion affects new runs only.
            compiled.task["base_inputs"] = list(compiled.task["base_inputs"]) + [self.pin_policy(spec["policy"])]
            validate(compiled.task, "task")
        grant = {"schema": "gabriel.grant/1", "grant_id": grant_id, "principal_id": self.config["principal_id"], "workspace_id": self.config["workspace_id"],
                 "task_id": task_id, "tool_ids": sorted(self.registry.catalog()["tools"]), "resource_ids": RESOURCES, "effect_classes": GRANTED_EFFECTS,
                 "budget_ceiling": budget, "expires_at_unix_ms": self.owner.owner_time() + int(spec.get("grant_ttl_ms", 7 * 24 * 3600 * 1000)),
                 "policy_digest": policy, "parent_grant_id": None}
        self.owner.register_grant(validate(grant, "grant"), self.credential)
        payload = {"schema": "gabriel.task-admission/1", "task": compiled.task, "run_id": run_id, "binding_ref": compiled.refs["binding_ref"],
                   "goal_spec_ref": compiled.refs["goal_spec_ref"], "compilation_report_ref": compiled.refs["compilation_report_ref"]}
        validate(payload, "task-admission")
        receipt = self.submit("admit_task", payload, task_id, run_id, expected_revision=0, command_id="admit-" + task_id)
        worktree = Worktree.create(repository, base_commit, self.path / "worktrees" / run_id)
        (self.path / "runs" / (run_id + ".json")).write_text(json.dumps({"worktree": str(worktree.path), "repository": str(repository),
                                                                         "base_commit": base_commit, "protected_paths": compiled.refs["protected_paths"]}, indent=2))
        return {"task_id": task_id, "run_id": run_id, "receipt": receipt, "compilation_report": compiled.report, "worktree": str(worktree.path)}

    def submit(self, op, payload, task_id, run_id, *, expected_revision=None, command_id=None):
        if expected_revision is None:
            expected_revision = self.owner.run_record(run_id)["run_revision"]
        payload_ref = self.store.put(canonical(payload), "application/json")
        command = {"schema": "gabriel.command/1", "command_id": command_id or ("cmd-" + hashlib.sha256(canonical(payload) + str(time.time_ns()).encode()).hexdigest()[:16]),
                   "workspace_id": self.config["workspace_id"], "task_id": task_id, "run_id": run_id, "expected_revision": expected_revision,
                   "op": op, "payload_ref": payload_ref, "policy_digest": self.owner.projection(run_id)["task"]["policy_digest"] if op != "admit_task" else payload["task"]["policy_digest"]}
        return self.owner.submit(validate(command, "command"), credential=self.credential)

    def run_notes(self, run_id: str) -> dict:
        path = self.path / "runs" / (run_id + ".json")
        if not path.is_file():
            raise GabrielError(Code.STORAGE_FAULT, "runtime notes for %s are missing" % run_id)
        return json.loads(path.read_text())

    def worktree_for(self, run_id: str, binding: dict) -> Worktree:
        notes = self.run_notes(run_id)
        return Worktree.open(notes["worktree"], binding["base_commit"], notes["repository"])

    def resolve_task(self, task_id: str) -> tuple:
        info = self.owner.task(task_id)
        return info["active_run_id"], info

    # user controls
    def pause(self, task_id):
        run_id, _ = self.resolve_task(task_id)
        return self.submit("request_pause", {"schema": "gabriel.pause-request/1", "reason_ref": self.store.put(b"user requested pause", "text/plain; charset=utf-8")}, task_id, run_id)

    def resume(self, task_id):
        run_id, _ = self.resolve_task(task_id)
        return self.submit("resume_run", {"schema": "gabriel.resume/1", "reason_ref": self.store.put(b"user requested resume", "text/plain; charset=utf-8")}, task_id, run_id)

    def cancel(self, task_id, reason="user cancelled"):
        run_id, _ = self.resolve_task(task_id)
        return self.submit("cancel_task", {"schema": "gabriel.cancellation/1", "reason_ref": self.store.put(reason.encode("utf8"), "text/plain; charset=utf-8")}, task_id, run_id)

    def status(self, task_id) -> dict:
        run_id, info = self.resolve_task(task_id)
        projection = self.owner.projection(run_id)
        run, meta = projection["run"], projection["run_meta"]
        nodes = {nid: s["status"] for nid, s in projection["nodes"].items()}
        active = [a["attempt_id"] for a in projection["attempts"].values() if a["status"] in ("issued", "marked")]
        assessments = [{"check_id": a["check_id"], "outcome": a["outcome"], "eligible": a["eligible"]} for a in projection["assessments"].values()]
        return {"task_id": task_id, "run_id": run_id, "state": run["state"], "run_revision": run["run_revision"], "pause_requested": run["pause_requested"],
                "plan_versions": meta["plan_versions"], "repair_count": meta["repair_count"], "nodes": nodes, "active_attempts": active,
                "budget": {"ceiling": run["budget"], "spent": projection["ledger"]["spent"], "reserved": projection["ledger"]["reserved"],
                           "overruns": projection["ledger"]["overruns"]},
                "unresolved_effects": run["unresolved_effect_ids"], "hold": meta["hold"], "assessments": assessments,
                "observed_snapshot": meta["observed_snapshot_ref"], "anchor": self.owner.anchor()}
