"""``gabriel`` command line interface over the workspace API."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..contracts.codec import loads
from ..contracts.errors import GabrielError


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
    audit = sub.add_parser("audit"); audit.add_argument("--workspace", required=True); audit.add_argument("--anchor")
    replay = sub.add_parser("replay"); replay.add_argument("run_id"); replay.add_argument("--workspace", required=True); replay.add_argument("--recorded", action="store_true", default=True)
    bk = sub.add_parser("backup", help="coherent backup: database snapshot, referenced objects, anchor"); bk.add_argument("--workspace", required=True); bk.add_argument("--out", required=True)
    rs = sub.add_parser("restore", help="restore a backup elsewhere and verify anchor, objects and replay"); rs.add_argument("--from", dest="source", required=True); rs.add_argument("--workspace", required=True)
    rm = sub.add_parser("release-manifest"); rm.add_argument("--workspace", required=False); rm.add_argument("--out", required=True); rm.add_argument("--root", default=".")
    ev = sub.add_parser("eval", help="frozen matched evaluation (WP11)"); esub = ev.add_subparsers(dest="action", required=True)
    esub.add_parser("corpus-check")
    freeze = esub.add_parser("freeze"); freeze.add_argument("--provider", required=True, help="JSON provider spec (file or inline)")
    freeze.add_argument("--out", required=True); freeze.add_argument("--repetitions", type=int, default=2)
    freeze.add_argument("--backend", choices=("linux_namespace", "trusted_local"), default="linux_namespace")
    freeze.add_argument("--systems", default=",".join(("provider_only", "simple_loop", "gabriel", "gabriel_no_repair")))
    freeze.add_argument("--tasks", default=None, help="comma-separated task ids (default: whole corpus)")
    freeze.add_argument("--held-out-families", default="", help="comma-separated families never run before this protocol")
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
            _emit(restore(args.source, args.workspace, catalog=build_registry(lambda: None).catalog())); return 0
        if args.command == "release-manifest":
            from ..agent.release import write_release_manifest
            doctor = catalog = None
            if args.workspace:
                ws = Workspace.open(args.workspace)
                try:
                    doctor, catalog = ws.doctor(), ws.owner.catalog_digest
                finally:
                    ws.close()
            evidence = {}
            for name in ("evidence/test_run.json", "evidence/live/summary.json", "evidence/wp01/baseline_manifest.json",
                         "evidence/wp02/spec_validation.json", "evidence/doctor_linux_namespace_selftest.json", "evidence/wp11/protocol.frozen.json"):
                path = Path(args.root) / name
                if path.is_file():
                    evidence[name] = __import__("hashlib").sha256(path.read_bytes()).hexdigest()
            _emit(write_release_manifest(Path(args.root), Path(args.out), evidence=evidence, catalog_digest=catalog, doctor=doctor)); return 0
        if args.command == "init":
            ws = Workspace.create(args.workspace, principal_id=args.principal, backend=args.backend, allow_trusted_local=args.allow_trusted_local)
            _emit({"status": "created", "workspace": str(ws.path), "workspace_id": ws.config["workspace_id"], "backend": args.backend})
            ws.close(); return 0
        ws = Workspace.open(args.workspace)
        try:
            if args.command == "doctor":
                report = ws.doctor(selftest=args.selftest); _emit(report)
                return 0 if not report["problems"] else 3
            if args.command == "backup":
                from ..agent.backup import backup
                _emit(backup(ws, args.out)); return 0
            if args.command == "audit":
                anchor = loads(Path(args.anchor).read_bytes()) if args.anchor else None
                _emit(ws.owner.replay(expected_anchor=anchor)); return 0
            if args.command == "replay":
                _emit(dict(ws.owner.replay(), run=ws.owner.run_record(args.run_id))); return 0
            if args.action == "create":
                spec = json.loads(Path(args.spec).read_text())
                result = ws.create_task(spec)
                _emit({"task_id": result["task_id"], "run_id": result["run_id"], "worktree": result["worktree"],
                       "compilation": {"admissible": result["compilation_report"]["admissible"],
                                       "clauses": [{"clause_id": c["clause_id"], "status": c["status"], "reason": c["reason"]} for c in result["compilation_report"]["clauses"]]}})
                return 0
            if args.action == "run":
                summary = TaskRunner(ws, args.task_id, max_iterations=args.max_iterations).run(); _emit(summary)
                return 0 if summary["state"] == "succeeded" else 4
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
        report = corpus.check_all(); _emit(report)
        return 0 if report["all_sound"] else 5
    if args.action == "freeze":
        provider = _json_arg(args.provider)
        protocol = harness.default_protocol(provider, repetitions=args.repetitions, systems=tuple(args.systems.split(",")),
                                            backend=args.backend, task_ids=args.tasks.split(",") if args.tasks else None,
                                            held_out_families=[f for f in args.held_out_families.split(",") if f], note=args.note)
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
