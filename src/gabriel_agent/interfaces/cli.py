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
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            ws = Workspace.create(args.workspace, principal_id=args.principal, backend=args.backend, allow_trusted_local=args.allow_trusted_local)
            _emit({"status": "created", "workspace": str(ws.path), "workspace_id": ws.config["workspace_id"], "backend": args.backend})
            ws.close(); return 0
        ws = Workspace.open(args.workspace)
        try:
            if args.command == "doctor":
                report = ws.doctor(selftest=args.selftest); _emit(report)
                return 0 if not report["problems"] else 3
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


if __name__ == "__main__":
    raise SystemExit(main())
