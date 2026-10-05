#!/usr/bin/env python3
"""ADR-25 witness: a long run of tasks in ONE workspace under the operations that bound it.

Usage:
    scripts/longrun_witness.py --out evidence/ops/longrun --backend linux_namespace --tasks 600

Hundreds of tasks of the three packs run through one workspace with scripted providers (the
mechanism under witness is the store, the journal, the memory and the operations, not a model):
document tasks whose verified runs establish claims (first over a fixed set of sources, so the
association history outgrows the engine's batch cap; then over new sources, so it outgrows the
entity cap), software tasks with contained test runs, numerical tasks with a contained worker.
Associative probes every few document tasks retain what the walk saw and how long a retrieval
took. On a schedule the witness compacts the memory, collects garbage with the grace period at
zero (nothing is in flight between tasks), backs the workspace up and restores it elsewhere,
migrates it to a changed capability catalog and continues under the new epoch, and at the end
replays the journal, verifies the chain, reproduces the first and the last probe, runs the
diagnostics and retires the worktrees. Every number recorded is read back from the workspace.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import platform
import shutil
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from gabriel_agent.adapters import native_graph  # noqa: E402
from gabriel_agent.agent import TaskRunner, Workspace  # noqa: E402
from gabriel_agent.agent import workspace as workspace_module  # noqa: E402
from gabriel_agent.agent.backup import backup, restore  # noqa: E402
from gabriel_agent.contracts.codec import loads  # noqa: E402
from gabriel_agent.contracts.errors import GabrielError  # noqa: E402
from gabriel_agent.domains.base import descriptor  # noqa: E402
from gabriel_agent.evaluation.corpus_domains import materialize  # noqa: E402
from gabriel_agent.evaluation.fixtures import numerical_series, parser_bug  # noqa: E402
from gabriel_agent.memory import association  # noqa: E402
from gabriel_agent.policy import router  # noqa: E402

HUB = "# Hub register\n\nThe reporting threshold of every ward is fixed in the ward registers; the hub holds no figure of its own.\n"
HUB_GOAL = ("Amend doc/notes.md so that it records the hub's rule that the reporting threshold is fixed in the ward registers and the threshold "
            "of ward %03d from its register. Every statement must be followed by a citation of the exact source span that supports it. Do not change the sources.")
PROBE_GOAL = ("Amend doc/notes.md so that it records the hub's rule about where the reporting threshold is fixed. Every statement must be followed by a "
              "citation of the exact source span that supports it. Do not change the sources.")
NOTES_SEED = "# Notes\n\n(to be completed)\n"
FIXED_WARDS = 20      # phase A: claims over a fixed set of keys, so the batch cap is reached while the entity cap is not
PROBE_EVERY = 25
BUDGET = {"model_tokens_total": 400000, "model_requests": 12}


def ward_text(index: int) -> str:
    return "# Ward %03d register\n\nWard %03d reports a threshold of %d EUR for the current period.\n" % (index, index, 100 + index)


def document_repo(path: Path, wards: int) -> str:
    files = {"sources/hub.md": HUB, "doc/notes.md": NOTES_SEED, "README.md": "# Registers\n\nThe hub register and one register per ward.\n"}
    for index in range(wards):
        files["sources/ward%03d.md" % index] = ward_text(index)

    class _Task:
        task_id = "longrun-documents"

        @staticmethod
        def files_map():
            return files
    return materialize(_Task, path)


def scripted(worker: list, provider_id: str) -> dict:
    planner = [{"kind": "echo_reference"}]
    return {"kind": "scripted", "provider_id": provider_id, "script": {"by_step": {"plan-request": planner}, "by_role": {"planner": planner, "worker": worker}}}


def hub_spec(repo: Path, base: str, oracle_dir: Path, ward: int) -> dict:
    """A claim-producing document task under the plain view: cites the hub and one ward."""
    content = ("# Notes\n\nThe reporting threshold is fixed in the ward registers. [[cite:{{obs:file:sources/hub.md}} \"fixed in the ward registers\"]]\n\n"
               "Ward %03d reports a threshold of %d EUR. [[cite:{{obs:file:sources/ward%03d.md}} \"threshold of %d EUR\"]]\n" % (ward, 100 + ward, ward, 100 + ward))
    oracle = oracle_dir / ("hub-%03d.json" % ward)
    oracle.write_text(json.dumps({"claims": [{"path": "doc/notes.md", "must_contain": ["fixed in the ward registers"], "cited_source_id": "hub", "quote_must_include": "fixed in the ward registers"},
                                             {"path": "doc/notes.md", "must_contain": ["%d EUR" % (100 + ward)], "cited_source_id": "ward%03d" % ward,
                                              "quote_must_include": "threshold of %d EUR" % (100 + ward)}], "forbidden": []}, indent=1))
    worker = [{"kind": "template", "value": {"operations": [{"kind": "modify", "path": "doc/notes.md", "expected_sha256": "{{sha:doc/notes.md}}", "content": content}],
                                             "rationale": "record the hub rule and the ward figure with cited spans"}}]
    return {"domain": "document", "goal": HUB_GOAL % ward, "repository": str(repo), "base_commit": base, "allowed_paths": ["doc/"],
            "sources": [{"path": "sources/hub.md", "source_id": "hub", "revision": 1, "event_kind": "timeless_document"},
                        {"path": "sources/ward%03d.md" % ward, "source_id": "ward%03d" % ward, "revision": 1, "event_kind": "timeless_document"}],
            "targets": ["doc/notes.md"],
            "checks": [{"check_id": "citations", "kind": "document/citations_bound", "independent": True, "role": "acceptance_only"},
                       {"check_id": "claims", "kind": "document/required_claims", "independent": True, "role": "acceptance_only",
                        "oracle_files": [{"path": "oracle/required_claims.json", "source": str(oracle)}]}],
            "provider": scripted(worker, "scripted-hub-%03d" % ward), "budget": BUDGET, "retrieval_view": "plain", "planner_mode": "reference",
            "max_repairs": 0, "max_plan_versions": 1, "policy": router.rule_based()}


def probe_spec(repo: Path, base: str, oracle_dir: Path, index: int) -> dict:
    """An associative-view task whose goal names the hub (the goal's lexical matches seed the walk, the hub among them):
    its retrieval manifest retains what the walk saw."""
    content = "# Notes\n\nThe reporting threshold is fixed in the ward registers. [[cite:{{obs:hub}} \"fixed in the ward registers\"]]\n"
    oracle = oracle_dir / ("probe-%03d.json" % index)
    oracle.write_text(json.dumps({"claims": [{"path": "doc/notes.md", "must_contain": ["fixed in the ward registers"], "cited_source_id": "hub",
                                              "quote_must_include": "fixed in the ward registers"}], "forbidden": []}, indent=1))
    worker = [{"kind": "template", "value": {"operations": [{"kind": "modify", "path": "doc/notes.md", "expected_sha256": "{{sha:doc/notes.md}}", "content": content}],
                                             "rationale": "record the hub rule with its cited span"}}]
    return {"domain": "document", "goal": PROBE_GOAL, "repository": str(repo), "base_commit": base, "allowed_paths": ["doc/"],
            "sources": [{"path": "sources/hub.md", "source_id": "hub", "revision": 1, "event_kind": "timeless_document"}], "targets": ["doc/notes.md"],
            "checks": [{"check_id": "citations", "kind": "document/citations_bound", "independent": True, "role": "acceptance_only"},
                       {"check_id": "claims", "kind": "document/required_claims", "independent": True, "role": "acceptance_only",
                        "oracle_files": [{"path": "oracle/required_claims.json", "source": str(oracle)}]}],
            "provider": scripted(worker, "scripted-probe"), "budget": BUDGET, "retrieval_view": "associative", "planner_mode": "reference",
            "max_repairs": 0, "max_plan_versions": 1, "policy": router.rule_based()}


class _Probe:
    """An extra read-only tool: registering it changes the capability catalog of the running code (as in tests/test_ops.py)."""

    def __call__(self, intent, args, ctx):
        raise NotImplementedError

    def reconcile(self, intent, attempt, ctx):
        return "confirmed_not_executed", b"{}"


# The registry fingerprints a tool from its module's source. The probe is bound to a name that is no module, so its
# fingerprint is a function of its qualified name alone and the catalog the witness migrates to does not depend on the
# bytes of this script (an edit of the script during the run would otherwise change the catalog between the migration
# and the reopen).
_Probe.__module__ = "gabriel.longrun-witness.probe"

_ORIGINAL_BUILD_REGISTRY = workspace_module.build_registry


def _registry_with_probe(backend_resolver):
    registry = _ORIGINAL_BUILD_REGISTRY(backend_resolver)
    registry.register_tool(descriptor("ops.probe", "read", "read_back", "read", pack_label="ops"), _Probe())
    return registry


def _size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    if path.is_dir():
        return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
    return 0


def _count(db, table: str, where: str = "") -> int:
    return db.execute("SELECT COUNT(*) FROM %s %s" % (table, where)).fetchone()[0]


class Witness:
    def __init__(self, out: Path, backend: str):
        self.out, self.backend = out, backend
        self.work = out / "work"
        self.ws_path = self.work / "workspace"
        self.ws = None
        self.series, self.probes, self.operations, self.retrievals, self.retrieval_errors = [], [], [], [], []
        self.epoch = 0
        self.task_index = 0
        self.started = time.monotonic()

    # ------------------------------------------------------------ measurements
    def snapshot(self, label: str, store_walk: bool) -> dict:
        ws = self.ws
        o, m = ws.owner._db, ws.memory._db
        record = {"label": label, "task_index": self.task_index, "epoch": self.epoch, "elapsed_s": round(time.monotonic() - self.started, 1),
                  "journal": {"events": _count(o, "events"), "runs": _count(o, "runs"), "attempts": _count(o, "attempts"), "artifact_refs": _count(o, "artifact_refs"),
                              "bytes": _size(self.ws_path / "journal.sqlite")},
                  "memory": {"entries": _count(m, "entries"), "observations": _count(m, "observations"), "document_observations": _count(m, "observations", "WHERE source_kind = 'document'"),
                             "distinct_keys": m.execute("SELECT COUNT(DISTINCT source_key) FROM observations").fetchone()[0],
                             "distinct_document_keys": m.execute("SELECT COUNT(DISTINCT source_key) FROM observations WHERE source_kind = 'document'").fetchone()[0],
                             "claims": _count(m, "claims"), "supported_claims": _count(m, "claims", "WHERE status = 'supported'"), "labels": _count(m, "labels"),
                             "cache_rows": _count(m, "cache"), "compactions": _count(m, "compactions"), "work_items": _count(m, "work_items"),
                             "bytes": _size(self.ws_path / "memory.sqlite"), "wal_bytes": _size(self.ws_path / "memory.sqlite-wal")},
                  "telemetry_bytes": _size(ws.tracer.path), "worktrees": len([p for p in (self.ws_path / "worktrees").iterdir() if p.is_dir()]) if (self.ws_path / "worktrees").is_dir() else 0,
                  "worktree_bytes": None, "numerical_cache_bytes": _size(self.ws_path / "numerical_cache.json"), "migrations_bytes": _size(self.ws_path / "migrations"),
                  "store": None}
        if store_walk:
            objects = list(ws.store.list_objects())
            record["store"] = {"objects": len(objects), "bytes": sum(p.stat().st_size for _, p in objects)}
            record["worktree_bytes"] = _size(self.ws_path / "worktrees")
        return record

    def operation(self, name: str, fn, **extra) -> dict:
        clock = time.monotonic()
        try:
            result = fn()
            status = "ok"
        except GabrielError as exc:
            result, status = {"error": exc.message, "code": str(exc.code)}, "error"
        entry = {"name": name, "task_index": self.task_index, "epoch": self.epoch, "duration_ms": int((time.monotonic() - clock) * 1000), "status": status,
                 "result": self.relativized(result)}
        entry.update(extra)
        self.operations.append(entry)
        return entry

    # ------------------------------------------------------------ tasks
    def run_task(self, spec: dict, kind: str, label: str) -> dict:
        ws = self.ws
        clock = time.monotonic()
        created = ws.create_task(spec)
        summary = TaskRunner(ws, created["task_id"]).run()
        wall_ms = int((time.monotonic() - clock) * 1000)
        self.task_index += 1
        record = {"index": self.task_index, "kind": kind, "label": label, "run_id": created["run_id"], "state": summary["state"], "wall_ms": wall_ms,
                  "repair_count": summary["repair_count"], "spent": {k: summary["spent"].get(k) for k in ("model_requests", "tool_attempts", "cpu_ms")},
                  "journal_events": ws.owner.anchor()["sequence"], "memory_entries": ws.memory.anchor()["memory_sequence"], "epoch": self.epoch}
        if self.retrievals:
            record["retrievals_ms"] = [r["duration_ms"] for r in self.retrievals]
            self.retrievals = []
        self.series.append(record)
        return dict(record, created=created, summary=summary)

    def timed_retrieve(self):
        """Wrap the live memory's retrieve so that every retrieval's wall time is retained beside its manifest facts."""
        memory = self.ws.memory
        original = memory.retrieve
        witness = self

        def timed(**kwargs):
            clock = time.monotonic()
            try:
                manifest = original(**kwargs)
            except BaseException as exc:  # a retrieval that raises is the cliff ADR-25 removes; it is retained, then re-raised
                witness.retrieval_errors.append({"task_index": witness.task_index, "error": repr(exc)})
                raise
            witness.retrievals.append({"duration_ms": int((time.monotonic() - clock) * 1000), "cached": manifest.get("cached"), "items": len(manifest["items"]),
                                       "excluded": len(manifest["excluded"]), "association": (manifest.get("association") or {}).get("status")})
            return manifest
        memory.retrieve = timed

    def open_workspace(self, create: bool):
        self.ws = Workspace.create(self.ws_path, backend=self.backend, allow_trusted_local=(self.backend == "trusted_local")) if create else Workspace.open(self.ws_path)
        self.timed_retrieve()

    def probe(self, repo: Path, base: str, oracle_dir: Path, index: int) -> dict:
        ws = self.ws
        before = list(self.retrievals)
        result = self.run_task(probe_spec(repo, base, oracle_dir, index), "document-probe", "probe-%03d" % index)
        projection = ws.owner.projection(result["run_id"])
        snapshot = loads(ws.store.get(projection["run_meta"]["observed_snapshot_ref"]))
        manifest = loads(ws.store.get(snapshot["retrieval_manifest_ref"]))
        record = manifest.get("association") or {}
        history, erosion = association.cocitation_history(ws.memory, ws.memory.frontier(), None)
        entry = {"index": index, "task_index": self.task_index, "state": result["state"], "retrieval_manifest_sha256": snapshot["retrieval_manifest_ref"]["sha256"],
                 "retrievals": result.get("retrievals_ms"), "items": len(manifest["items"]), "excluded": len(manifest["excluded"]),
                 "association": {k: record.get(k) for k in ("status", "window", "erosion")}, "entities": len(record.get("entities") or []),
                 "seeds": record.get("seeds"), "carried": len(record.get("links") or {}), "hub_mass_milli": {k: v for k, v in (record.get("masses_milli") or {}).items() if k.startswith("hub/")},
                 "history_claims": len(history), "history_entities": len(association._entities([h["keys"] for h in history])),
                 "engine": dict(native_graph.LAST_TIMINGS) if record.get("status") == "computed" else None, "manifest": manifest}
        self.probes.append(entry)
        del before
        return entry

    # ------------------------------------------------------------ the run
    def run(self, tasks: int) -> dict:
        self.work.mkdir(parents=True, exist_ok=False)
        oracle_dir = self.work / "oracles"
        oracle_dir.mkdir()
        documents = max(1, tasks // 2)
        software = max(1, tasks // 4)
        numerical = max(1, tasks - documents - software)
        wards = FIXED_WARDS + max(0, documents - documents // 2)
        doc_repo, sw_repo, num_repo = self.work / "repo-documents", self.work / "repo-software", self.work / "repo-numerical"
        doc_base = document_repo(doc_repo, wards)
        sw_base = parser_bug.build_repo(sw_repo)
        sw_oracle = parser_bug.write_oracle(self.work / "oracle_kvparse.py")
        num_base = numerical_series.build_repo(num_repo)
        num_oracle = numerical_series.write_oracle(self.work / "oracle_numerical.json")
        sw_provider = {"kind": "scripted", "script": parser_bug.script(), "max_input_tokens": 60000, "provider_id": "scripted-software"}
        num_provider = {"kind": "scripted", "script": numerical_series.script("correct"), "provider_id": "scripted-numerical"}
        self.open_workspace(create=True)
        doctor = self.ws.doctor(selftest=(self.backend == "linux_namespace"))
        plan = []
        # interleave: two document tasks, one software, two document, one numerical, ...; the first half of the documents cycle over a fixed
        # ward set (the batch cap), the second half names new wards (the entity cap)
        d = s = n = 0
        while d < documents or s < software or n < numerical:
            for _ in range(2):
                if d < documents:
                    ward = (d % FIXED_WARDS) if d < documents // 2 else FIXED_WARDS + (d - documents // 2)
                    plan.append(("document", d, ward))
                    d += 1
            if s < software:
                plan.append(("software", s, None)); s += 1
            for _ in range(2):
                if d < documents:
                    ward = (d % FIXED_WARDS) if d < documents // 2 else FIXED_WARDS + (d - documents // 2)
                    plan.append(("document", d, ward))
                    d += 1
            if n < numerical:
                plan.append(("numerical", n, None)); n += 1
        self.operations.append({"name": "plan", "task_index": 0, "epoch": 0, "duration_ms": 0, "status": "ok",
                                "result": {"tasks": len(plan), "documents": documents, "software": software, "numerical": numerical, "wards": wards,
                                           "fixed_wards": FIXED_WARDS, "probe_every": PROBE_EVERY}})
        snapshots = [self.snapshot("start", True)]
        probes_done = 0
        migrated = False
        backup_dirs = []
        for position, (kind, index, ward) in enumerate(plan):
            if kind == "document":
                self.run_task(hub_spec(doc_repo, doc_base, oracle_dir, ward), "document", "hub-%03d-ward-%03d" % (index, ward))
                if (index + 1) % PROBE_EVERY == 0:
                    probes_done += 1
                    self.probe(doc_repo, doc_base, oracle_dir, probes_done)
            elif kind == "software":
                self.run_task(parser_bug.task_spec(sw_repo, sw_base, sw_oracle, sw_provider), "software", "parser-%03d" % index)
            else:
                self.run_task(numerical_series.task_spec(num_repo, num_base, num_oracle, num_provider), "numerical", "series-%03d" % index)
            done = position + 1
            if done % 100 == 0 or done == len(plan):
                self.operation("memory.compact", lambda: {k: v for k, v in self.ws.memory.compact().items() if k not in ("retained_artifacts", "anchors")})
                self.operation("gc.apply", lambda: {k: v for k, v in self.ws.gc(apply=True, grace_seconds=0).items() if k != "orphan_sample"}, grace_seconds=0)
                snapshots.append(self.snapshot("after-task-%d" % done, True))
            if done == len(plan) // 2 and not migrated:
                # backup, restore elsewhere, then migrate to a changed catalog and continue under the new epoch
                backup_dir = self.work / ("backup-%d" % done)
                self.operation("backup", lambda: {k: v for k, v in backup(self.ws, backup_dir).items() if k != "objects"}, path=self.relative(backup_dir))
                backup_dirs.append(backup_dir)
                self.ws.close()
                self.operation("restore", lambda: restore(backup_dir, self.work / ("restored-%d" % done), catalog=workspace_module.build_registry(lambda: None).catalog()),
                               source=self.relative(backup_dir))
                workspace_module.build_registry = _registry_with_probe
                migration = self.operation("migrate", lambda: Workspace.migrate(self.ws_path, reason="longrun witness: ops.probe tool added to the catalog"))
                if migration["status"] == "ok":
                    migration["result"] = {k: v for k, v in migration["result"].items() if k in ("status", "backup", "equivalence_replay", "migration", "replay_after", "problems")}
                    if isinstance(migration["result"].get("backup"), dict):
                        migration["result"]["backup"] = {k: v for k, v in migration["result"]["backup"].items() if k != "objects"}
                self.epoch = 1
                migrated = True
                self.open_workspace(create=False)
                snapshots.append(self.snapshot("after-migration", True))
        # the end: a second backup and restore under the new epoch, replay, chain, reproduction, diagnostics, metrics, retirement
        final_backup = self.work / "backup-final"
        self.operation("backup", lambda: {k: v for k, v in backup(self.ws, final_backup).items() if k != "objects"}, path=self.relative(final_backup))
        self.operation("restore", lambda: restore(final_backup, self.work / "restored-final", catalog=workspace_module.build_registry(lambda: None).catalog()),
                       source=self.relative(final_backup))
        self.operation("owner.replay", lambda: self.ws.owner.replay())
        self.operation("memory.verify", lambda: self.ws.memory.verify())
        for which in ("first", "last"):
            probe = self.probes[0] if which == "first" else self.probes[-1]
            self.operation("memory.reproduce", lambda probe=probe: self.ws.memory.reproduce(probe["manifest"]), probe=probe["index"], which=which)
        self.operation("doctor.deep", lambda: {k: v for k, v in self.ws.doctor(deep=True).items() if k in ("problems", "startup")})
        self.operation("metrics", lambda: {"totals": self.ws.metrics()["totals"]})
        self.operation("trace.summary", lambda: self.ws.trace()["summary"])
        snapshots.append(self.snapshot("end", True))
        self.operation("retire_worktrees", lambda: {k: (v if k != "retired" else len(v)) for k, v in self.ws.retire_worktrees().items()})
        self.operation("gc.after_retirement", lambda: {k: v for k, v in self.ws.gc(apply=True, grace_seconds=0).items() if k != "orphan_sample"})
        snapshots.append(self.snapshot("after-retirement", True))
        anchor, memory_anchor = self.ws.owner.anchor(), self.ws.memory.anchor()
        self.ws.close()
        workspace_module.build_registry = _ORIGINAL_BUILD_REGISTRY
        return {"doctor": {"configured_backend": doctor.get("configured_backend"), "problems": doctor.get("problems"),
                           "linux_namespace": (doctor.get("backends") or {}).get("linux_namespace")}, "snapshots": snapshots, "anchor": anchor, "memory_anchor": memory_anchor,
                "backups": [self.relative(p) for p in backup_dirs] + [self.relative(final_backup)]}

    def relative(self, path: Path) -> str:
        """Paths in the evidence are relative to the output directory, whatever --out the host was given."""
        try:
            return str(Path(path).resolve().relative_to(self.out.resolve()))
        except ValueError:
            return str(Path(path).name)

    def relativized(self, value):
        """Every string inside a result that names a path under the output directory, made relative to it."""
        if isinstance(value, dict):
            return {k: self.relativized(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.relativized(v) for v in value]
        if isinstance(value, str) and (value.startswith("/") or value.startswith(str(self.out))):
            try:
                return str(Path(value).resolve().relative_to(self.out.resolve()))
            except (ValueError, OSError):
                return value
        return value


def checks(summary: dict, witness: Witness) -> dict:
    ops = {}
    for entry in witness.operations:
        ops.setdefault(entry["name"], []).append(entry)
    tasks = witness.series
    by_kind = {}
    for record in tasks:
        by_kind.setdefault(record["kind"], []).append(record)
    first, last = witness.probes[0], witness.probes[-1]
    statuses = [p["association"]["status"] for p in witness.probes]
    windowed = [p for p in witness.probes if p["association"]["status"] == "computed" and (p["association"].get("window") or {}).get("used", 0) < (p["association"].get("window") or {}).get("available", 0)]
    return {
        "every_task_terminal": all(r["state"] in ("succeeded", "failed", "cancelled") for r in tasks),
        "document_tasks_all_succeeded": all(r["state"] == "succeeded" for r in by_kind.get("document", [])),
        "software_tasks_all_succeeded": all(r["state"] == "succeeded" for r in by_kind.get("software", [])),
        "numerical_tasks_all_succeeded": all(r["state"] == "succeeded" for r in by_kind.get("numerical", [])),
        "probes_all_succeeded": all(p["state"] == "succeeded" for p in witness.probes),
        # beyond the batch cap with the entities within the entity cap, the walk sees exactly max_batches batches
        "batch_cap_reached_and_declared": any(p["history_claims"] > native_graph.CAPS["max_batches"] and p["history_entities"] <= native_graph.CAPS["max_nodes"] for p in witness.probes)
                                           and bool(windowed)
                                           and all((p["association"]["window"] or {}).get("used") == native_graph.CAPS["max_batches"]
                                                   for p in windowed if p["history_entities"] <= native_graph.CAPS["max_nodes"]),
        # beyond the entity cap the walk sees the latest seeded batches whose entities fit, computed and declared, never off
        "entity_cap_reached_and_declared": any(p["history_entities"] > native_graph.CAPS["max_nodes"] for p in witness.probes)
                                            and all(p["association"]["status"] == "computed" and 0 < p["entities"] <= native_graph.CAPS["max_nodes"]
                                                    and (p["association"].get("window") or {}).get("used", 0) < (p["association"].get("window") or {}).get("available", 0)
                                                    for p in witness.probes if p["history_entities"] > native_graph.CAPS["max_nodes"]),
        "no_retrieval_raised": witness.retrieval_errors == [],
        # every source has one revision and one extraction here, so one observation per distinct document key is the ADR-25 bound
        "document_observations_bounded_by_distinct_sources": summary["snapshots"][-1]["memory"]["document_observations"] == summary["snapshots"][-1]["memory"]["distinct_document_keys"],
        "every_compaction_verified": all(e["status"] == "ok" and e["result"]["status"] == "compacted" and e["result"]["required_bytes_verified"] for e in ops.get("memory.compact", [])),
        "every_gc_passed": all(e["status"] == "ok" and e["result"]["status"] == "passed" for e in ops.get("gc.apply", []) + ops.get("gc.after_retirement", [])),
        "backups_restored_and_replayed": len(ops.get("restore", [])) == 2 and all(e["status"] == "ok" and e["result"]["status"] == "passed" for e in ops["restore"]),
        "restore_after_migration_passed": ops.get("restore", [{}])[-1].get("result", {}).get("replay", {}).get("status") == "passed" and any(e["status"] == "ok" and e["result"]["status"] == "migrated" for e in ops.get("migrate", [])),
        "final_replay_passed": ops.get("owner.replay", [{}])[-1].get("result", {}).get("status") == "passed",
        "memory_chain_verified": ops.get("memory.verify", [{}])[-1].get("result", {}).get("status") == "passed",
        "first_and_last_probe_reproduce": all(e["status"] == "ok" and e["result"]["status"] == "reproduced" for e in ops.get("memory.reproduce", [])),
        # the deep doctor ran, found no missing or changed bytes and no reconciliation work, and its only problem is the
        # jail self-test it does not execute itself (the witness runs that self-test at the start)
        "diagnostics_clean": bool(ops.get("doctor.deep")) and ops["doctor.deep"][-1]["status"] == "ok"
                             and ops["doctor.deep"][-1]["result"]["startup"]["storage"]["missing"] == []
                             and ops["doctor.deep"][-1]["result"]["startup"]["storage"]["corrupt"] == []
                             and ops["doctor.deep"][-1]["result"]["startup"]["reconciliation_work"] == []
                             and all("self-test" in problem for problem in ops["doctor.deep"][-1]["result"]["problems"])
                             and summary["doctor"]["linux_namespace"] is not None,
        "worktrees_retired": ops.get("retire_worktrees", [{}])[-1].get("result", {}).get("retired") == len(tasks) and summary["snapshots"][-1]["worktrees"] == 0,
        "probe_statuses": statuses, "first_probe": first["association"]["status"], "last_probe": last["association"]["status"],
    }


def report_lines(summary: dict, witness: Witness, verdict: dict, args) -> list:
    snaps = summary["snapshots"]
    lines = ["# ADR-25 witness: a long run of %d tasks in one workspace (%s)" % (len(witness.series), args.backend), "",
             "Produced %s on %s; `engine_observer` %s; scripted providers only." % (summary["produced_at_utc"], summary["platform"], summary["engine_observer_sha256"][:16]),
             "", "## Growth (read back from the workspace)", "",
             "| snapshot | tasks | epoch | journal events | journal MB | memory entries | document obs. | distinct document keys | supported claims | cache rows | store objects | store MB | worktrees | worktree MB | telemetry MB |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for s in snaps:
        store = s["store"] or {}
        lines.append("| %s | %d | %d | %d | %.1f | %d | %d | %d | %d | %d | %s | %s | %d | %s | %.2f |" % (
            s["label"], s["task_index"], s["epoch"], s["journal"]["events"], s["journal"]["bytes"] / 1e6, s["memory"]["entries"], s["memory"]["document_observations"],
            s["memory"]["distinct_document_keys"], s["memory"]["supported_claims"], s["memory"]["cache_rows"], store.get("objects", "-"),
            ("%.1f" % (store["bytes"] / 1e6)) if store else "-", s["worktrees"], ("%.1f" % (s["worktree_bytes"] / 1e6)) if s["worktree_bytes"] is not None else "-",
            s["telemetry_bytes"] / 1e6))
    lines += ["", "## Associative probes (every %d document tasks; the goal's lexical matches seed the walk, the hub among them)" % PROBE_EVERY, "",
              "| probe | after task | state | status | claims in history | entities in history | batches available / used | entities walked | carried | retrieval ms | engine ms |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for p in witness.probes:
        window = p["association"].get("window") or {}
        engine = p["engine"] or {}
        lines.append("| %d | %d | %s | %s | %d | %d | %s / %s | %d | %d | %s | %s |" % (
            p["index"], p["task_index"], p["state"], p["association"]["status"], p["history_claims"], p["history_entities"], window.get("available", "-"), window.get("used", "-"),
            p["entities"], p["carried"], ",".join(str(x) for x in (p["retrievals"] or [])), ("%.1f" % (engine["native_process_us"] / 1000)) if engine else "-"))
    lines += ["", "## Operations", "", "| operation | after task | epoch | duration ms | status | key facts |", "|---|---|---|---|---|---|"]
    for e in witness.operations:
        if e["name"] == "plan":
            continue
        facts = e["result"] if isinstance(e["result"], dict) else {}
        keys = {"memory.compact": ("status", "removed_derived", "retained_artifact_count"), "gc.apply": ("status", "objects", "orphans", "removed", "replay", "memory"),
                "gc.after_retirement": ("status", "objects", "orphans", "removed"), "backup": ("object_count", "object_bytes"), "restore": ("status", "objects_verified"),
                "migrate": ("status",), "owner.replay": ("status", "events", "runs"), "memory.verify": ("status", "entries"), "memory.reproduce": ("status", "differences"),
                "doctor.deep": ("problems",), "metrics": ("totals",), "trace.summary": ("spans",), "retire_worktrees": ("retired", "bytes_freed")}.get(e["name"], ())
        shown = {k: facts.get(k) for k in keys if k in facts}
        if e["name"] == "restore" and isinstance(facts.get("replay"), dict):
            shown["replay_events"] = facts["replay"].get("events")
        if e["name"] == "metrics" and isinstance(facts.get("totals"), dict):
            shown = {k: facts["totals"].get(k) for k in ("runs", "declared_successes", "independent_checks_passed", "independent_checks_failed")}
        lines.append("| %s | %d | %d | %d | %s | %s |" % (e["name"], e["task_index"], e["epoch"], e["duration_ms"], e["status"], json.dumps(shown, default=str)[:160]))
    by_kind = {}
    for r in witness.series:
        by_kind.setdefault(r["kind"], []).append(r["wall_ms"])
    lines += ["", "## Task wall time (ms)", "", "| kind | tasks | first 10 mean | last 10 mean | overall mean | max |", "|---|---|---|---|---|---|"]
    for kind, values in sorted(by_kind.items()):
        lines.append("| %s | %d | %.0f | %.0f | %.0f | %d |" % (kind, len(values), sum(values[:10]) / len(values[:10]), sum(values[-10:]) / len(values[-10:]), sum(values) / len(values), max(values)))
    lines += ["", "## Checks", "", "| check | result |", "|---|---|"]
    for key, value in verdict.items():
        if isinstance(value, bool):
            lines.append("| %s | %s |" % (key, "passed" if value else "FAILED"))
    lines += ["", "Probe statuses in order: %s." % ", ".join(verdict["probe_statuses"]),
              "", "Status: **%s**." % summary["status"], "",
              "Retained: `summary.json` (every snapshot, probe, operation and check), `series.json` (every task's state, wall time, counters and retrieval times).",
              "The workspace, repositories, backups and restored copies under `work/` are not committed."]
    return lines


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", required=True)
    parser.add_argument("--backend", choices=("linux_namespace", "trusted_local"), default="linux_namespace")
    parser.add_argument("--tasks", type=int, default=600)
    args = parser.parse_args(argv)
    if args.tasks < 4 * PROBE_EVERY:
        raise SystemExit("--tasks must be at least %d so that the schedule holds probes, a compaction and a migration" % (4 * PROBE_EVERY))
    if native_graph.binaries().get("engine_observer") is None:
        raise SystemExit("the native engine_observer is not built; the associative probes need it")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    witness = Witness(out, args.backend)
    if witness.work.exists():
        raise SystemExit("refusing to overwrite " + str(witness.work))
    try:
        summary = witness.run(args.tasks)
    except BaseException as exc:
        # an aborted run still retains what it measured: the series, probes and operations so far, and the failure
        aborted = {"schema": "gabriel.evidence.longrun-witness/1", "status": "aborted", "error": repr(exc), "traceback": traceback.format_exc(),
                   "tasks": len(witness.series), "probes": [{k: v for k, v in p.items() if k != "manifest"} for p in witness.probes],
                   "operations": witness.operations, "elapsed_s": round(time.monotonic() - witness.started, 1), "backend": args.backend}
        (out / "summary.json").write_text(json.dumps(aborted, indent=1, sort_keys=True, default=str) + "\n")
        (out / "series.json").write_text(json.dumps(witness.series, indent=1, default=str) + "\n")
        (out / "report.md").write_text("# ADR-25 witness: aborted after %d tasks\n\n```\n%s```\n" % (len(witness.series), traceback.format_exc()))
        raise
    finally:
        workspace_module.build_registry = _ORIGINAL_BUILD_REGISTRY
    verdict = checks(summary, witness)
    summary.update({"schema": "gabriel.evidence.longrun-witness/1", "produced_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "adr": "docs/adr/ADR-25-long-running-operation.md",
                    "backend": args.backend, "platform": platform.platform(), "engine_observer_sha256": native_graph.binaries()["engine_observer"]["sha256"],
                    "caps": dict(native_graph.CAPS), "tasks": len(witness.series), "probes": [{k: v for k, v in p.items() if k != "manifest"} for p in witness.probes],
                    "operations": witness.operations, "checks": verdict, "elapsed_s": round(time.monotonic() - witness.started, 1),
                    "status": "passed" if all(v for v in verdict.values() if isinstance(v, bool)) else "failed"})
    (out / "summary.json").write_text(json.dumps(summary, indent=1, sort_keys=True, default=str) + "\n")
    (out / "series.json").write_text(json.dumps(witness.series, indent=1, default=str) + "\n")
    (out / "report.md").write_text("\n".join(report_lines(summary, witness, verdict, args)) + "\n")
    for name in ("restored-final",):
        shutil.rmtree(witness.work / name, ignore_errors=True)
    print(json.dumps({"status": summary["status"], "tasks": summary["tasks"], "elapsed_s": summary["elapsed_s"], "checks": {k: v for k, v in verdict.items() if isinstance(v, bool)}}, indent=1))
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
