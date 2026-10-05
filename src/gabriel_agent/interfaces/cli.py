"""``gabriel`` command line interface over the workspace API."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..contracts.codec import loads
from ..contracts.errors import Code, GabrielError


def _emit(value):
    sys.stdout.write(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n")


def main(argv=None) -> int:
    from ..agent import Workspace, TaskRunner, export_task
    parser = argparse.ArgumentParser(prog="gabriel", description="Gabriel AI agent application")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init"); init.add_argument("--workspace", required=True)
    init.add_argument("--backend", choices=("linux_namespace", "trusted_local"), default="linux_namespace")
    init.add_argument("--allow-trusted-local", action="store_true"); init.add_argument("--principal", default="local-user")
    doctor = sub.add_parser("doctor"); doctor.add_argument("--workspace", required=True); doctor.add_argument("--selftest", action="store_true")
    doctor.add_argument("--deep", action="store_true", help="verify the bytes of every referenced object, not only their presence")
    mig = sub.add_parser("migrate", help="explicit versioned migration of a journal to the running code's catalog, registry and reducer identities")
    mig.add_argument("--workspace", required=True); mig.add_argument("--reason", required=True, help="why the identities changed (recorded)")
    mig.add_argument("--backup", default=None, help="backup directory (default: <workspace>/migrations/backup-<sequence>-<time>)")
    task = sub.add_parser("task"); tsub = task.add_subparsers(dest="action", required=True)
    create = tsub.add_parser("create"); create.add_argument("--workspace", required=True); create.add_argument("--spec", required=True)
    for name in ("run", "status", "pause", "resume", "cancel", "inspect", "export"):
        p = tsub.add_parser(name); p.add_argument("task_id"); p.add_argument("--workspace", required=True)
        if name == "run":
            p.add_argument("--max-iterations", type=int, default=400)
        if name == "inspect":
            p.add_argument("--evidence", action="store_true")
        if name == "export":
            p.add_argument("--out", required=True)
    audit = sub.add_parser("audit", help="recorded replay of the whole journal from genesis (the audit; it verifies every checkpoint it passes)")
    audit.add_argument("--workspace", required=True); audit.add_argument("--anchor")
    audit.add_argument("--from-checkpoint", action="store_true", help="ADR-26: verify both chains over every event but reduce only the events after the latest verified checkpoint")
    audit.add_argument("--checkpoint", default=None, help="ADR-26: retain the state the replay reached as a checkpoint with this id")
    cp = sub.add_parser("checkpoint", help="ADR-26: replay from the latest verified checkpoint (or from genesis with --full) and retain the state reached as a new verified checkpoint")
    cp.add_argument("--workspace", required=True); cp.add_argument("--full", action="store_true"); cp.add_argument("--reason", default="operator checkpoint")
    replay = sub.add_parser("replay"); replay.add_argument("run_id"); replay.add_argument("--workspace", required=True); replay.add_argument("--recorded", action="store_true", default=True)
    bk = sub.add_parser("backup", help="coherent backup: database snapshot, referenced objects, anchor"); bk.add_argument("--workspace", required=True); bk.add_argument("--out", required=True)
    rs = sub.add_parser("restore", help="restore a backup elsewhere and verify anchor, objects and replay (from the latest verified checkpoint the backup carries, or from genesis with --full)")
    rs.add_argument("--from", dest="source", required=True); rs.add_argument("--workspace", required=True); rs.add_argument("--full", action="store_true")
    rm = sub.add_parser("release-manifest"); rm.add_argument("--workspace", required=False); rm.add_argument("--out", required=True); rm.add_argument("--root", default=".")
    rm.add_argument("--selftest", action="store_true", help="run the containment self-test so the recorded doctor report carries its result")
    metrics = sub.add_parser("metrics", help="operational metrics of a workspace or one run (verified success, unknown effects, retries, overruns, recovery, time to first artifact, resource use, cold/warm)")
    metrics.add_argument("--workspace", required=True); metrics.add_argument("--run", default=None)
    trace = sub.add_parser("trace", help="telemetry spans of a run: queue wait, provider latency, tool execution, verification, journal commit, artifact I/O")
    trace.add_argument("run_id"); trace.add_argument("--workspace", required=True); trace.add_argument("--summary", action="store_true", help="totals per kind only")
    gc = sub.add_parser("gc", help="artifact garbage collection: objects outside the referenced closure (journal, memory chain, checkpoints, catalog and migration records) and older than the grace period; dry run unless --apply")
    gc.add_argument("--workspace", required=True); gc.add_argument("--apply", action="store_true"); gc.add_argument("--grace-seconds", type=int, default=3600)
    retire = sub.add_parser("retire", help="ADR-25: remove the disposable worktrees of terminal runs and prune their registrations; the journal and retained artifacts are untouched, task export for a retired run refuses")
    retire.add_argument("--workspace", required=True); retire.add_argument("--run", default=None, help="one run id (default: every terminal run)")
    mem = sub.add_parser("memory", help="evidence index (WP09)"); msub = mem.add_subparsers(dest="action", required=True)
    for name in ("status", "verify", "compact"):
        p = msub.add_parser(name); p.add_argument("--workspace", required=True)
    rp = msub.add_parser("reproduce", help="ADR-23: recompute a retained retrieval manifest from the chain at its own frontier and access policy revision and compare")
    rp.add_argument("--workspace", required=True); rp.add_argument("--manifest", required=True, help="sha256 of the retained retrieval manifest object")
    ev = sub.add_parser("eval", help="frozen matched evaluation (WP11)"); esub = ev.add_subparsers(dest="action", required=True)
    cc = esub.add_parser("corpus-check"); cc.add_argument("--tier", choices=("standard", "hard", "document", "numerical", "graph", "association"), default=None)
    freeze = esub.add_parser("freeze"); freeze.add_argument("--provider", required=True, help="JSON provider spec (file or inline)")
    freeze.add_argument("--out", required=True); freeze.add_argument("--repetitions", type=int, default=2)
    freeze.add_argument("--backend", choices=("linux_namespace", "trusted_local"), default="linux_namespace")
    freeze.add_argument("--systems", default=",".join(("provider_only", "simple_loop", "gabriel", "gabriel_no_repair")))
    freeze.add_argument("--tasks", default=None, help="comma-separated task ids (default: whole corpus)")
    freeze.add_argument("--held-out-families", default="", help="comma-separated families never run before this protocol")
    freeze.add_argument("--tiers", default="", help="comma-separated corpus tiers to include (default: all)")
    freeze.add_argument("--policy", default=None, help="router policy record (JSON file) frozen with the protocol for the G3 systems")
    freeze.add_argument("--episode-seed", default=None, help="JSON file with the frozen episode seed [{id, text}] for the G3 systems")
    freeze.add_argument("--criterion", default="", help="declared held-out criterion the G3 systems must meet")
    freeze.add_argument("--note", default="", help="free-text provenance note recorded in the protocol")
    erun = esub.add_parser("run"); erun.add_argument("--protocol", required=True); erun.add_argument("--out", required=True)
    erun.add_argument("--provider", required=True, help="JSON provider spec with credential_ref (file or inline)")
    erun.add_argument("--workers", type=int, default=3); erun.add_argument("--systems", default=None); erun.add_argument("--tasks", default=None)
    erun.add_argument("--repetitions", type=int, default=None)
    erep = esub.add_parser("report"); erep.add_argument("--run", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "eval":
            return _eval(args)
        if args.command == "restore":
            from ..agent.backup import restore
            from ..agent.workspace import build_registry
            _emit(restore(args.source, args.workspace, catalog=build_registry(lambda: None).catalog(), full=args.full)); return 0
        if args.command == "release-manifest":
            from ..agent.release import write_release_manifest
            doctor = catalog = None
            if args.workspace:
                ws = Workspace.open(args.workspace)
                try:
                    doctor, catalog = ws.doctor(selftest=args.selftest), ws.owner.catalog_digest
                finally:
                    ws.close()
            evidence = {}
            for name in ("evidence/test_run.json", "evidence/live/summary.json", "evidence/wp01/baseline_manifest.json",
                         "evidence/wp02/spec_validation.json", "evidence/doctor_linux_namespace_selftest.json",
                         "evidence/wp11/protocol.frozen.json", "evidence/wp11/run-gpt-4.1-mini/report.json",
                         "evidence/wp11/protocol2.frozen.json", "evidence/wp11/run2-gpt-4.1-mini/report.json",
                         "evidence/wp11/protocol3.frozen.json", "evidence/wp11/run3-gpt-4.1-mini/report.json"):
                path = Path(args.root) / name
                if path.is_file():
                    evidence[name] = __import__("hashlib").sha256(path.read_bytes()).hexdigest()
            _emit(write_release_manifest(Path(args.root), Path(args.out), evidence=evidence, catalog_digest=catalog, doctor=doctor)); return 0
        if args.command == "migrate":
            report = Workspace.migrate(args.workspace, reason=args.reason, backup_dir=args.backup); _emit(report)
            return 0 if report["status"] in ("migrated", "nothing_to_migrate") else 5
        if args.command == "init":
            ws = Workspace.create(args.workspace, principal_id=args.principal, backend=args.backend, allow_trusted_local=args.allow_trusted_local)
            _emit({"status": "created", "workspace": str(ws.path), "workspace_id": ws.config["workspace_id"], "backend": args.backend})
            ws.close(); return 0
        ws = Workspace.open(args.workspace)
        try:
            if args.command == "doctor":
                report = ws.doctor(selftest=args.selftest, deep=args.deep); _emit(report)
                return 0 if not report["problems"] else 3
            if args.command == "backup":
                from ..agent.backup import backup
                _emit(backup(ws, args.out)); return 0
            if args.command == "audit":
                anchor = loads(Path(args.anchor).read_bytes()) if args.anchor else None
                report = ws.owner.replay(expected_anchor=anchor, from_checkpoint=args.from_checkpoint, record_checkpoint=args.checkpoint,
                                         reason="audit" if args.checkpoint else None)
                _emit(report); return 0 if report["status"] == "passed" else 3
            if args.command == "checkpoint":
                report = ws.owner.replay(from_checkpoint=not args.full, record_checkpoint="checkpoint-%d" % ws.owner.owner_time(), reason=args.reason)
                _emit(report); return 0 if report["status"] == "passed" else 3
            if args.command == "replay":
                _emit(dict(ws.owner.replay(), run=ws.owner.run_record(args.run_id))); return 0
            if args.command == "gc":
                report = ws.gc(apply=args.apply, grace_seconds=args.grace_seconds); _emit(report)
                return 0 if report["status"] in ("dry_run", "passed") else 3
            if args.command == "metrics":
                _emit(ws.metrics(args.run)); return 0
            if args.command == "retire":
                _emit(ws.retire_worktrees(run_ids=[args.run] if args.run else None)); return 0
            if args.command == "trace":
                report = ws.trace(args.run_id)
                _emit({k: v for k, v in report.items() if k != "spans"} if args.summary else report); return 0
            if args.command == "memory":
                if args.action == "status":
                    _emit({"anchor": ws.memory.anchor(), "entries": len(ws.memory.entries()), "work_items": ws.memory.work_items()}); return 0
                if args.action == "verify":
                    report = ws.memory.verify(); _emit(report); return 0 if report["status"] == "passed" else 3
                if args.action == "compact":
                    _emit(ws.memory.compact()); return 0
                if args.action == "reproduce":
                    path = ws.store.path_for(args.manifest)
                    if not path.is_file():
                        raise GabrielError(Code.UNKNOWN_OBJECT, "no retained retrieval manifest with digest " + args.manifest)
                    manifest = loads(ws.store.get({"sha256": args.manifest, "bytes": path.stat().st_size, "media_type": "application/json"}))
                    report = ws.memory.reproduce(manifest); _emit(report); return 0 if report["status"] == "reproduced" else 3
            if args.action == "create":
                spec = json.loads(Path(args.spec).read_text())
                result = ws.create_task(spec)
                _emit({"task_id": result["task_id"], "run_id": result["run_id"], "worktree": result["worktree"],
                       "compilation": {"admissible": result["compilation_report"]["admissible"],
                                       "clauses": [{"clause_id": c["clause_id"], "status": c["status"], "reason": c["reason"]} for c in result["compilation_report"]["clauses"]]}})
                return 0
            if args.action == "run":
                summary = TaskRunner(ws, args.task_id, max_iterations=args.max_iterations).run(); _emit(summary)
                if summary["state"] == "succeeded":
                    return 0
                return 3 if summary.get("pause_requested") and summary["state"] not in ("succeeded", "failed", "cancelled") else 4
            if args.action == "status":
                _emit(ws.status(args.task_id)); return 0
            if args.action == "pause":
                _emit(ws.pause(args.task_id)); return 0
            if args.action == "resume":
                _emit(ws.resume(args.task_id)); return 0
            if args.action == "cancel":
                _emit(ws.cancel(args.task_id)); return 0
            if args.action == "inspect":
                run_id, _ = ws.resolve_task(args.task_id)
                projection = ws.owner.projection(run_id)
                view = {"task": projection["task"], "run": projection["run"], "run_meta": projection["run_meta"], "plan_history": projection["plan_history"],
                        "nodes": projection["nodes"], "attempts": projection["attempts"], "ledger": projection["ledger"], "holds": projection["holds"],
                        "late_results": projection["late_results"], "reconciliations": projection["reconciliations"]}
                if args.evidence:
                    view["assessments"] = projection["assessments"]
                    view["events"] = [e["event"] for e in ws.owner.events(run_id)]
                _emit(view); return 0
            if args.action == "export":
                _emit(export_task(ws, args.task_id, args.out)); return 0
        finally:
            ws.close()
    except GabrielError as exc:
        sys.stderr.write("gabriel: " + json.dumps(exc.to_record(), sort_keys=True) + "\n")
        return 2
    return 1


def _json_arg(value):
    text = value if value.lstrip().startswith("{") else Path(value).read_text()
    return json.loads(text)


def _eval(args) -> int:
    from ..evaluation import corpus, harness
    if args.action == "corpus-check":
        report = corpus.check_all(tier=args.tier); _emit(report)
        return 0 if report["all_sound"] else 5
    if args.action == "freeze":
        provider = _json_arg(args.provider)
        protocol = harness.default_protocol(provider, repetitions=args.repetitions, systems=tuple(args.systems.split(",")),
                                            backend=args.backend, task_ids=args.tasks.split(",") if args.tasks else None,
                                            held_out_families=[f for f in args.held_out_families.split(",") if f], note=args.note,
                                            tiers=[t for t in args.tiers.split(",") if t] or None,
                                            policy=_json_arg(args.policy) if args.policy else None,
                                            episode_seed=_json_arg(args.episode_seed) if args.episode_seed else None,
                                            declared_criterion=args.criterion)
        frozen = harness.freeze(protocol, Path(args.out))
        _emit({"frozen_digest": frozen["frozen_digest"], "corpus_digest": frozen["corpus_digest"], "tasks": len(frozen["tasks"]),
               "systems": frozen["systems"], "repetitions": frozen["repetitions"], "path": args.out})
        return 0
    if args.action == "run":
        protocol = json.loads(Path(args.protocol).read_text())
        provider = _json_arg(args.provider)
        results = harness.run(protocol, Path(args.out), provider, workers=args.workers,
                              systems=args.systems.split(",") if args.systems else None,
                              task_ids=args.tasks.split(",") if args.tasks else None, repetitions=args.repetitions)
        rep = harness.report(results, protocol)
        (Path(args.out) / "report.json").write_text(json.dumps(rep, indent=2) + "\n")
        (Path(args.out) / "report.md").write_text(harness.render_markdown(rep, protocol))
        _emit({"units": results["units"], "wall_ms": results["wall_ms"], "per_system": {k: {"p_success": v["p_success"], "false_completions": v["false_completions"], "runs": v["runs"]} for k, v in rep["per_system"].items()}})
        return 0
    if args.action == "report":
        run_dir = Path(args.run)
        results = json.loads((run_dir / "results.json").read_text())
        protocol = json.loads((run_dir / "protocol.json").read_text())
        rep = harness.report(results, protocol)
        (run_dir / "report.json").write_text(json.dumps(rep, indent=2) + "\n")
        (run_dir / "report.md").write_text(harness.render_markdown(rep, protocol))
        sys.stdout.write(harness.render_markdown(rep, protocol))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
