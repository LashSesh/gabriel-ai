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
import shutil
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
from ..state.owner import CODEC_VERSION as JOURNAL_CODEC_VERSION, FORMAT as JOURNAL_FORMAT
from ..state.reducer import reducer_identity
from ..telemetry import Tracer, read_spans, summarize
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


def _write_migration_report(path: Path, report: dict) -> None:
    directory = Path(path) / "migrations"
    directory.mkdir(exist_ok=True)
    name = (report.get("migration") or {}).get("migration_id") or ("refused-%d" % int(time.time() * 1000))
    (directory / (name + ".json")).write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n")


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
        # operational telemetry: best-effort JSONL spans under the workspace; the owner and the store
        # reach the tracer through their attributes, audit events never depend on it
        self.tracer = Tracer(Path(path) / "telemetry" / "spans.jsonl", trace_id=config["workspace_id"])
        store.tracer = self.tracer
        owner.tracer = self.tracer
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

    @classmethod
    def migrate(cls, path, *, reason: str, backup_dir=None, clock=None) -> dict:
        """Explicit versioned migration of a workspace whose journal registered other catalog,
        schema registry or reducer identities than the running code (blueprint: operations).
        Order: coherent backup first; equivalence replay of every retained event under the running
        code; the migration is recorded only when every retained projection digest and chain hash
        is reproduced. Otherwise it is refused and the journal is untouched: an old journal is
        never rewritten to match new code."""
        from .backup import backup
        path = Path(path)
        config_path = path / "config.json"
        if not config_path.is_file():
            raise GabrielError(Code.STORAGE_FAULT, "not a Gabriel workspace: " + str(path))
        config = validate(loads(config_path.read_bytes()), "workspace-config")
        store = ObjectStore.open(path / config["artifact_root"])
        registry = build_registry(lambda: None)
        owner = Owner.open(path / config["database"], store, registry.catalog(), clock=clock, tolerate_mismatch=True)
        secret = (path / "credentials" / (config["principal_id"] + ".secret")).read_text().strip()
        memory_path = path / "memory.sqlite"
        memory = MemoryService.open(memory_path, store, lambda: owner.anchor()["sequence"]) if memory_path.is_file() else None
        ws = cls(path, config, owner, store, registry, Credential(config["principal_id"], secret), memory=memory)
        try:
            report = {"schema": "gabriel.migration-report/1", "workspace_id": config["workspace_id"], "workspace": str(path),
                      "registered": dict(owner.registered),
                      "running": {"catalog_digest": owner.catalog_digest, "schema_registry_digest": registry_digest(), "reducer_identity": reducer_identity()},
                      "problems": list((owner.pending_migration or {}).get("problems", [])), "status": None}
            if owner.pending_migration is None:
                report["status"] = "nothing_to_migrate"
                return report
            backup_dir = Path(backup_dir) if backup_dir else path / "migrations" / ("backup-%d-%d" % (owner.anchor()["sequence"], owner.owner_time()))
            manifest = backup(ws, backup_dir)
            manifest_sha = hashlib.sha256((backup_dir / "manifest.json").read_bytes()).hexdigest()
            report["backup"] = {"path": str(backup_dir), "manifest_sha256": manifest_sha, "object_count": manifest["object_count"],
                                "object_bytes": manifest["object_bytes"], "anchor": manifest["anchor"], "memory_anchor": manifest.get("memory_anchor")}
            try:
                replay = owner.replay(pending_from_digest=owner.registered["catalog_digest"])
            except GabrielError as exc:
                report.update({"status": "refused", "equivalence_replay": {"status": "failed", "error": exc.message},
                               "note": "the running code does not reproduce the retained journal; nothing was changed, the backup is retained"})
                _write_migration_report(path, report)
                return report
            if replay["status"] != "passed":
                report.update({"status": "refused", "equivalence_replay": replay, "note": "replay reported missing referenced artifacts; nothing was changed"})
                _write_migration_report(path, report)
                return report
            record = owner.record_migration(reason=reason, backup_manifest_sha256=manifest_sha, replayed_events=replay["events"])
            report["equivalence_replay"] = replay
            report["migration"] = record
            report["replay_after"] = owner.replay()
            # the workspace configuration carries the catalog identity the registry was built from
            config = dict(config, registry_digest=registry.catalog_digest(), config_revision=int(config.get("config_revision", 0)) + 1)
            validate(config, "workspace-config")
            config_path.write_bytes(canonical(config) + b"\n")
            report["status"] = "migrated"
            _write_migration_report(path, report)
            return report
        finally:
            ws.close()

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
    # ------------------------------------------------------------ operational metrics and traces
    def trace(self, run_id: str | None = None) -> dict:
        """Retained telemetry spans of a run (or of the workspace) with totals per kind."""
        spans = read_spans(self.tracer.path, run_id)
        return {"run_id": run_id, "path": str(self.tracer.path), "summary": summarize(spans), "spans": spans,
                "exporter": {"written": self.tracer.written, "dropped": self.tracer.dropped}}

    def _run_metrics(self, run_id: str) -> dict:
        """Per-run operational metrics from the journal (blueprint: track verified success, false
        completion, unknown effects, retries, budget overruns, recovery, time to first useful
        artifact and resource use; cold and warm paths separately)."""
        projection = self.owner.projection(run_id)
        rows = self.owner._db.execute("SELECT e.sequence, e.kind, e.inputs_text, c.command_text, e.command_id FROM events e JOIN commands c "
                                      "ON e.command_id = c.command_id WHERE e.run_id = ? ORDER BY e.sequence", (run_id,)).fetchall()
        events = []
        for sequence, kind, inputs_text, command_text, command_id in rows:
            events.append({"sequence": sequence, "kind": kind, "op": loads(command_text)["op"], "command_id": command_id,
                           "owner_time_unix_ms": loads(inputs_text)["owner_time_unix_ms"]})
        first_time = events[0]["owner_time_unix_ms"] if events else None
        last_time = events[-1]["owner_time_unix_ms"] if events else None
        attempts = projection["attempts"]
        # time to the first useful artifact: the first accepted, completed result of a propose step
        first_artifact_ms = None
        for event in events:
            if event["op"] != "accept_result":
                continue
            attempt = attempts.get(event["command_id"].removeprefix("result-"))
            if attempt and attempt["capability_id"] == "model.generate" and attempt["status"] == "completed" and attempt["step_id"] != "plan-request":
                first_artifact_ms = event["owner_time_unix_ms"] - first_time
                break
        # recovery: every hold until the next event of another kind (or the end of the journal)
        holds, recovery_ms = 0, 0
        for index, event in enumerate(events):
            if event["op"] != "hold":
                continue
            holds += 1
            following = next((e for e in events[index + 1:] if e["op"] != "hold"), None)
            recovery_ms += ((following or {"owner_time_unix_ms": last_time})["owner_time_unix_ms"] - event["owner_time_unix_ms"])
        per_step = {}
        for attempt in attempts.values():
            per_step[attempt["step_id"]] = per_step.get(attempt["step_id"], 0) + 1
        retries = sum(count - 1 for count in per_step.values())
        unknown_effects = len(projection["run"]["unresolved_effect_ids"]) + sum(1 for a in attempts.values() if a["effect_state"] in ("unknown", "ambiguous"))
        assessments = list(projection["assessments"].values())
        specs = {}
        try:
            specs = {s["check_id"]: s for s in validate_bytes(self.store.get(projection["binding_ref"]), "task-binding")["check_specs"]}
        except (GabrielError, KeyError, TypeError):
            pass
        independent_passed = sum(1 for a in assessments if a["eligible"] and a["outcome"] == "passed" and specs.get(a["check_id"], {}).get("independent"))
        independent_failed = sum(1 for a in assessments if a["eligible"] and a["outcome"] == "failed" and specs.get(a["check_id"], {}).get("independent"))
        # cold or warm path: a run that reused a cached job result or retrieval manifest took the warm path
        warm = False
        for attempt in attempts.values():
            if attempt.get("result_ref"):
                try:
                    result = loads(self.store.get(attempt["result_ref"]))
                except GabrielError:
                    continue
                for output in result.get("outputs", []):
                    if output["output_slot"] == "job_result":
                        try:
                            warm = warm or bool(loads(self.store.get(output["artifact_ref"])).get("cache", {}).get("hit"))
                        except GabrielError:
                            pass
        overruns = projection["ledger"].get("overruns")
        return {"run_id": run_id, "task_id": projection["task"]["task_id"], "domain": projection["task"].get("domain"), "state": projection["run"]["state"],
                "declared_success": projection["run"]["state"] == "succeeded",
                "independent_checks": {"passed": independent_passed, "failed": independent_failed},
                "unknown_effects": unknown_effects, "retries": retries, "attempts": len(attempts),
                "budget_overruns": len(overruns) if isinstance(overruns, (list, dict)) else int(bool(overruns)),
                "holds": holds, "recovery_ms": recovery_ms, "repair_count": projection["run_meta"]["repair_count"], "plan_versions": projection["run_meta"]["plan_versions"],
                "time_to_first_useful_artifact_ms": first_artifact_ms, "total_ms": (last_time - first_time) if events else None,
                "resource_use": projection["ledger"]["spent"], "path": "warm" if warm else "cold", "events": len(events),
                "telemetry": summarize(read_spans(self.tracer.path, run_id))["per_kind"]}

    def metrics(self, run_id: str | None = None) -> dict:
        """Operational metrics of one run or of every run in the workspace, with totals."""
        run_ids = [run_id] if run_id else [r[0] for r in self.owner._db.execute("SELECT run_id FROM runs ORDER BY run_id").fetchall()]
        runs = [self._run_metrics(r) for r in run_ids]
        by_state = {}
        for run in runs:
            by_state[run["state"]] = by_state.get(run["state"], 0) + 1
        totals = {"runs": len(runs), "by_state": by_state, "declared_successes": sum(r["declared_success"] for r in runs),
                  "independent_checks_passed": sum(r["independent_checks"]["passed"] for r in runs),
                  "independent_checks_failed": sum(r["independent_checks"]["failed"] for r in runs),
                  "unknown_effects": sum(r["unknown_effects"] for r in runs), "retries": sum(r["retries"] for r in runs),
                  "budget_overruns": sum(r["budget_overruns"] for r in runs), "holds": sum(r["holds"] for r in runs),
                  "recovery_ms": sum(r["recovery_ms"] for r in runs),
                  "cold_runs": sum(1 for r in runs if r["path"] == "cold"), "warm_runs": sum(1 for r in runs if r["path"] == "warm"),
                  "model_requests": sum(r["resource_use"].get("model_requests", 0) for r in runs),
                  "model_tokens": sum(r["resource_use"].get("model_tokens", 0) for r in runs)}
        return {"schema": "gabriel.metrics/1", "workspace_id": self.config["workspace_id"], "totals": totals, "runs": runs,
                "telemetry": summarize(read_spans(self.tracer.path)), "exporter": {"written": self.tracer.written, "dropped": self.tracer.dropped}}

    def gc(self, *, apply: bool = False, grace_seconds: int = 3600, now: float | None = None) -> dict:
        """Artifact garbage collection: dry run unless ``apply``; see ``agent/gc.py``."""
        from .gc import collect_garbage
        return collect_garbage(self, apply=apply, grace_seconds=grace_seconds, now=now)

    def startup_validation(self, deep: bool = False) -> dict:
        """What the owner validates at start (blueprint: operations): schema and format versions,
        storage integrity of every referenced object (presence; bytes with ``deep``), registry
        compatibility and recorded migrations, the artifact root, and outstanding leases, which
        are reconciliation work and never automatic repeats."""
        referenced = set(self.owner.referenced_artifacts())
        if self.memory is not None:
            referenced |= self.memory.referenced_artifacts()
        missing, corrupt = [], []
        for sha in sorted(referenced):
            path = self.store.path_for(sha)
            if not path.is_file():
                missing.append(sha)
            elif deep and hashlib.sha256(path.read_bytes()).hexdigest() != sha:
                corrupt.append(sha)
        root = self.path / self.config["artifact_root"]
        return {"journal_format": JOURNAL_FORMAT, "codec_version": JOURNAL_CODEC_VERSION, "config_schema_version": self.config.get("schema_version"),
                "registered_identities": dict(self.owner.registered), "migrations": [{"migration_id": m["migration_id"], "sequence": m["sequence"],
                                                                                     "from_catalog_digest": m["from_catalog_digest"], "to_catalog_digest": m["to_catalog_digest"]}
                                                                                    for m in self.owner.migrations()],
                "storage": {"referenced_objects": len(referenced), "missing": missing[:64], "corrupt": corrupt[:64], "deep": deep,
                            "stray_temporaries": self.store.fsck([])["stray_temporaries"]},
                "artifact_root": {"path": str(root), "exists": root.is_dir(), "writable": os.access(root, os.W_OK)},
                "reconciliation_work": self.owner.expired_attempts(),
                "memory_chain": self.memory.anchor() if self.memory is not None else None}

    def doctor(self, selftest: bool = False, deep: bool = False) -> dict:
        probes = probe_backends()
        if selftest:
            probes["linux_namespace"] = LinuxNamespaceBackend().probe(selftest=True)
        configured = self.config["containment_backend"]
        startup = self.startup_validation(deep=deep)
        report = {"workspace_id": self.config["workspace_id"], "version": __version__, "python": platform.python_version(),
                  "platform": platform.platform(), "configured_backend": configured, "backends": probes,
                  "registry_loaded": self.registry.verify_loaded(), "catalog_digest": self.owner.catalog_digest,
                  "schema_registry_digest": registry_digest(), "journal": self.owner.anchor(),
                  "object_store": self.store.fsck([]), "effective_limits": self.config["default_limits"],
                  "startup": startup,
                  "git": subprocess.run(["git", "--version"], capture_output=True, text=True).stdout.strip() or "missing"}
        problems = []
        if startup["storage"]["missing"]:
            problems.append("%d referenced object(s) missing from the store" % len(startup["storage"]["missing"]))
        if startup["storage"]["corrupt"]:
            problems.append("%d referenced object(s) with changed bytes" % len(startup["storage"]["corrupt"]))
        if not startup["artifact_root"]["exists"] or not startup["artifact_root"]["writable"]:
            problems.append("artifact root missing or not writable: " + startup["artifact_root"]["path"])
        if startup["reconciliation_work"]:
            problems.append("%d expired attempt lease(s) await reconciliation (never repeated automatically): %s"
                            % (len(startup["reconciliation_work"]), ", ".join(a["attempt_id"] for a in startup["reconciliation_work"][:5])))
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
        # Production tasks pin one policy version; promotion affects new runs only. A task that pins none
        # gets the pack's default policy (ADR-22: a promoted readout the pack ships with its provenance),
        # or no pin at all, which means the rule-based policy.
        pinned = spec["policy"] if spec.get("policy") is not None else pack.default_policy()
        if pinned is not None:
            compiled.task["base_inputs"] = list(compiled.task["base_inputs"]) + [self.pin_policy(pinned)]
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
        if notes.get("worktree_retired"):
            raise GabrielError(Code.STORAGE_FAULT, "the worktree of %s was retired at owner time %s; the run's candidate artifacts stay retained in the journal"
                               % (run_id, notes.get("retired_owner_time_unix_ms")))
        return Worktree.open(notes["worktree"], binding["base_commit"], notes["repository"])

    def retire_worktrees(self, run_ids=None) -> dict:
        """ADR-25: remove the disposable worktrees of terminal runs and prune their registrations in the
        source repositories. The journal, the retained candidate artifacts and exports already taken are
        untouched; the run's notes keep the retirement, and `task export` for a retired run refuses.
        Runs that are not terminal are skipped and named."""
        from ..state import TERMINAL_STATES
        report = {"schema": "gabriel.worktree-retirement/1", "workspace_id": self.config["workspace_id"], "retired": [], "skipped": [],
                  "bytes_freed": 0, "repositories_pruned": []}
        repositories = set()
        for run_id, state in self.owner._db.execute("SELECT run_id, state FROM runs ORDER BY run_id").fetchall():
            if run_ids is not None and run_id not in run_ids:
                continue
            if state not in TERMINAL_STATES:
                report["skipped"].append({"run_id": run_id, "reason": "run state %s is not terminal" % state})
                continue
            notes_path = self.path / "runs" / (run_id + ".json")
            if not notes_path.is_file():
                report["skipped"].append({"run_id": run_id, "reason": "runtime notes missing"})
                continue
            notes = json.loads(notes_path.read_text())
            if notes.get("worktree_retired"):
                continue
            path = Path(notes["worktree"])
            size = sum(p.stat().st_size for p in path.rglob("*") if p.is_file()) if path.is_dir() else 0
            if path.is_dir():
                Worktree(path, notes["base_commit"], notes["repository"]).remove()
                if path.exists():
                    shutil.rmtree(path, ignore_errors=True)
            notes.update(worktree_retired=True, retired_owner_time_unix_ms=self.owner.owner_time())
            notes_path.write_text(json.dumps(notes, indent=2))
            repositories.add(notes["repository"])
            report["retired"].append(run_id)
            report["bytes_freed"] += size
        for repository in sorted(repositories):
            if Path(repository).is_dir():
                git(["worktree", "prune"], repository, check=False)
                report["repositories_pruned"].append(repository)
        return report

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
