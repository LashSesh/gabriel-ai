#!/usr/bin/env python3
"""AT23 and AT16 evidence: one frozen owner/scheduler/policy build across three real domain
adapters, with a real provider for the valid tasks and scripted controls for invalid and
out-of-scope inputs, plus the direct/hosted comparison of the analytical worker.

Usage:
    scripts/at23_three_domains.py --out evidence/wp10/at23 \
        --provider '{"kind":"openai_compat","model":"gpt-4.1-mini","credential_ref":"env:OPENAI_API_KEY"}' --backend linux_namespace

Everything the script records comes from the retained workspace: run states, eligible
assessments, provider statuses and model revisions, exports, replay without ports, the memory
chain check, the registry identity and the three pack manifests.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from gabriel_agent.adapters import analytical  # noqa: E402
from gabriel_agent.agent import TaskRunner, Workspace, export_task  # noqa: E402
from gabriel_agent.contracts.codec import loads  # noqa: E402
from gabriel_agent.contracts.errors import GabrielError  # noqa: E402
from gabriel_agent.evaluation.fixtures import document_amendment, numerical_series, parser_bug  # noqa: E402
from gabriel_agent.workers import backend_for  # noqa: E402
from gabriel_agent.workers.isolation import RunSpec  # noqa: E402

FIXTURES = {"software": parser_bug, "document": document_amendment, "numerical": numerical_series}
CONTROLS = {"software": ["wrong_then_weaken"], "document": ["fabricated", "wrong_source", "out_of_scope"],
            "numerical": ["dimension_mismatch", "unknown_operation", "out_of_scope_path"]}


def _run(ws, spec, out_dir: Path, label: str) -> dict:
    created = ws.create_task(spec)
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
    binding = loads(ws.store.get(projection["binding_ref"]))
    eligible = {}
    for a in projection["assessments"].values():
        if a["eligible"]:
            eligible[a["check_id"]] = a["outcome"]
    record = {"label": label, "task_id": created["task_id"], "run_id": summary["run_id"], "domain": binding["domain_namespace"],
              "pack": {"pack_id": binding["pack_id"], "pack_version": binding["pack_version"]}, "state": summary["state"],
              "plan_versions": summary["plan_versions"], "repair_count": summary["repair_count"], "hold": summary["hold"],
              "spent": {k: summary["spent"][k] for k in ("model_requests", "model_tokens", "tool_attempts")},
              "provider_statuses": statuses, "model_revisions": sorted({r for r in revisions if r}), "eligible_assessments": eligible,
              "mandatory_failed": sorted(c for c, o in eligible.items() if o != "passed" and any(t["check_id"] == c and t["mandatory"] for t in projection["task"]["checks"])),
              "worktree": created["worktree"], "log_tail": summary["log"][-8:]}
    worktree = ws.worktree_for(summary["run_id"], binding)
    (out_dir / (label + ".diff")).write_bytes(worktree.patch())
    record["final_diff_sha256"] = hashlib.sha256(worktree.patch()).hexdigest()
    try:
        manifest = export_task(ws, created["task_id"], out_dir / (label + "-delivery"))
        record["export"] = {"run_state": manifest["run_state"], "established": [r["check_id"] for r in manifest["assessments"] if r["established"]],
                            "unresolved_issues": manifest["unresolved_issues"], "final_tree_digest": manifest["final_tree_digest"]}
    except GabrielError as exc:
        record["export"] = {"error": exc.message}
    if binding["domain_namespace"] == "numerical":
        node = projection["nodes"].get("run-job")
        if node and "job_result" in node["outputs"]:
            result = loads(ws.store.get(node["outputs"]["job_result"]))
            record["job_result"] = {k: result[k] for k in ("status", "verdict", "containment", "backend_kind", "output_units", "worker_build")}
    if binding["domain_namespace"] == "document":
        for a in projection["assessments"].values():
            if a["check_id"] == "citations" and a["eligible"]:
                record["citations_evidence"] = loads(ws.store.get(a["evidence_ref"]), ascii_only=False)["evidence"]
    return record


def at16_direct_vs_hosted(backend, out_dir: Path) -> dict:
    raw = numerical_series.SERIES_TEXT.encode("utf8")
    direct = analytical.run_job("units.convert", {"to_units": "K"}, raw)
    work = out_dir / "at16-work"
    (work / "data").mkdir(parents=True, exist_ok=True)
    (work / "data" / "series.json").write_bytes(raw)
    (work / ".gabriel_worker").mkdir(exist_ok=True)
    (work / ".gabriel_worker" / "worker.py").write_bytes(Path(analytical.__file__).read_bytes())
    (work / ".gabriel_worker" / "job.json").write_text(json.dumps({"operation": "units.convert", "parameters": {"to_units": "K"}, "input_path": "data/series.json",
                                                                   "output_path": "out/series_kelvin.json", "result_path": ".gabriel_worker/result.json"}))
    witness = backend.run(RunSpec(argv=["python3", ".gabriel_worker/worker.py", ".gabriel_worker/job.json"], worktree=str(work), timeout_ms=60000,
                                  max_output_bytes=1 << 20, marker="at16"))
    hosted = json.loads((work / ".gabriel_worker" / "result.json").read_text()) if witness.exit_code == 0 else None
    hosted_output = (work / "out" / "series_kelvin.json").read_bytes() if hosted and hosted.get("verdict") == "computed" else None
    direct_output = analytical.dumps(direct["output"])
    small = json.dumps({"kind": "graph", "vertices": 3, "edges": [[0, 1]]}).encode()
    larger = json.dumps({"kind": "graph", "vertices": 4, "edges": [[0, 1]]}).encode()
    a, b = analytical.run_job("graph.small_signature", {}, small), analytical.run_job("graph.small_signature", {}, larger)
    from gabriel_agent.domains.numerical.pack import cache_key, worker_build
    build, env = worker_build(), analytical.numerical_environment()
    return {"worker_identity": {"worker_build": build, "direct_environment": env, "hosted_environment": hosted.get("numerical_environment") if hosted else None,
                                "hosted_backend": witness.backend_kind, "hosted_exit_code": witness.exit_code},
            "inputs": {"series_sha256": hashlib.sha256(raw).hexdigest(), "operation": "units.convert", "parameters": {"to_units": "K"}},
            "direct_hosted_comparison": {"direct_output_sha256": hashlib.sha256(direct_output).hexdigest(),
                                         "hosted_output_sha256": hashlib.sha256(hosted_output).hexdigest() if hosted_output else None,
                                         "equal": hosted_output == direct_output, "hosted_worker_build_matches": bool(hosted) and hosted.get("worker_build") == build},
            "scope_controls": {"dimension_mismatch": analytical.run_job("units.convert", {"to_units": "km"}, raw)["verdict"],
                               "unknown_unit": analytical.run_job("units.convert", {"to_units": "furlong"}, raw)["verdict"],
                               "unknown_operation": analytical.run_job("series.magic", {}, raw)["verdict"],
                               "graph_too_large": analytical.run_job("graph.small_signature", {}, json.dumps({"kind": "graph", "vertices": 8, "edges": []}).encode())["verdict"],
                               "wrong_input_kind": analytical.run_job("graph.small_signature", {}, raw)["verdict"]},
            "collision_control": {"legacy_padded_signature_equal": a["diagnostics"]["legacy_padded_signature"] == b["diagnostics"]["legacy_padded_signature"],
                                  "retained_signatures_differ": a["output"]["signature"] != b["output"]["signature"],
                                  "cache_keys_differ": cache_key(hashlib.sha256(small).hexdigest(), "graph.small_signature", {}, build, env)
                                  != cache_key(hashlib.sha256(larger).hexdigest(), "graph.small_signature", {}, build, env)}}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", required=True)
    parser.add_argument("--provider", required=True, help="JSON provider spec (file or inline) for the valid tasks")
    parser.add_argument("--backend", choices=("linux_namespace", "trusted_local"), default="linux_namespace")
    parser.add_argument("--no-controls", action="store_true")
    args = parser.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    provider = json.loads(args.provider if args.provider.lstrip().startswith("{") else Path(args.provider).read_text())
    provider = dict({"max_input_tokens": 60000, "max_output_tokens": 4000, "temperature_milli": 0, "timeout_ms": 120000}, **provider)
    ws = Workspace.create(out / "workspace", backend=args.backend, allow_trusted_local=(args.backend == "trusted_local"))
    try:
        doctor = ws.doctor(selftest=(args.backend == "linux_namespace"))
        summary = {"schema": "gabriel.evidence.at23/1", "produced_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                   "provider": {k: v for k, v in provider.items() if k != "script"}, "backend": args.backend,
                   "doctor": {"problems": doctor["problems"], "untrusted_execution_supported": doctor["untrusted_execution_supported"]},
                   "registry": {"catalog_digest": ws.owner.catalog_digest, "tools": sorted(ws.registry.catalog()["tools"]),
                                "verifiers": sorted(ws.registry.catalog()["verifiers"]),
                                "packs": {ns: {k: m[k] for k in ("pack_id", "pack_version", "namespace", "manifest_kind")} | {
                                    "ports": {p: v["capability_id"] for p, v in m["ports"].items()},
                                    "manifest_sha256": hashlib.sha256(json.dumps(m, sort_keys=True).encode()).hexdigest()}
                                          for ns, m in ((ns, pack.manifest(ws.registry)) for ns, pack in sorted(ws.packs.items()))}},
                   "valid_tasks": {}, "controls": {}, "at16": None}
        for domain, fixture in FIXTURES.items():
            repo = out / domain / "repo"
            repo.parent.mkdir(parents=True, exist_ok=True)
            base = fixture.build_repo(repo)
            oracle = fixture.write_oracle(out / domain / ("oracle_kvparse.py" if domain == "software" else "oracle.json"))
            spec = fixture.task_spec(repo, base, oracle, provider)
            summary["valid_tasks"][domain] = _run(ws, spec, out / domain, "valid")
            print("%s valid: %s %s" % (domain, summary["valid_tasks"][domain]["state"], summary["valid_tasks"][domain]["eligible_assessments"]))
            if not args.no_controls:
                summary["controls"][domain] = []
                for variant in CONTROLS[domain]:
                    scripted = {"kind": "scripted", "script": fixture.script(variant), "provider_id": "scripted-control"}
                    control_spec = dict(fixture.task_spec(repo, base, oracle, scripted), max_repairs=0, max_plan_versions=1)
                    if domain == "software":
                        control_spec["max_plan_versions"] = 2
                    record = _run(ws, control_spec, out / domain, "control-" + variant)
                    record["variant"] = variant
                    summary["controls"][domain].append(record)
                    print("%s control %s: %s failed=%s" % (domain, variant, record["state"], record["mandatory_failed"]))
        summary["at16"] = at16_direct_vs_hosted(ws.backend, out)
        summary["replay"] = ws.owner.replay()
        summary["memory"] = {k: ws.memory.verify()[k] for k in ("status", "entries", "head")}
        summary["memory"]["anchor"] = ws.memory.anchor()
        summary["all_valid_succeeded"] = all(r["state"] == "succeeded" for r in summary["valid_tasks"].values())
        summary["no_control_succeeded"] = all(r["state"] != "succeeded" for rs in summary["controls"].values() for r in rs)
        (out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n")
        (out / "report.md").write_text(render(summary))
        print("replay", summary["replay"]["status"], "memory", summary["memory"]["status"], "valid", summary["all_valid_succeeded"], "controls", summary["no_control_succeeded"])
        return 0 if summary["all_valid_succeeded"] and summary["no_control_succeeded"] and summary["replay"]["status"] == "passed" else 1
    finally:
        ws.close()


def render(summary: dict) -> str:
    lines = ["# AT23: one core across three domain adapters", "",
             "Backend `%s`, provider `%s` (%s), catalog digest `%s`, replay `%s` with %s external calls, memory chain `%s` (%d entries)." % (
                 summary["backend"], summary["provider"].get("model"), summary["provider"].get("kind"), summary["registry"]["catalog_digest"][:16],
                 summary["replay"]["status"], summary["replay"]["external_calls"], summary["memory"]["status"], summary["memory"]["entries"]), "",
             "| domain | pack | state | requests | tokens | model revisions | eligible assessments |", "|---|---|---|---|---|---|---|"]
    for domain, r in summary["valid_tasks"].items():
        lines.append("| %s | %s %s | %s | %d | %d | %s | %s |" % (domain, r["pack"]["pack_id"], r["pack"]["pack_version"], r["state"], r["spent"]["model_requests"],
                                                             r["spent"]["model_tokens"], ", ".join(r["model_revisions"]),
                                                             ", ".join("%s=%s" % kv for kv in sorted(r["eligible_assessments"].items()))))
    lines += ["", "## Controls (scripted invalid and out-of-scope inputs; no repair cycles)", "", "| domain | variant | state | failed mandatory checks |", "|---|---|---|---|"]
    for domain, records in summary["controls"].items():
        for r in records:
            lines.append("| %s | %s | %s | %s |" % (domain, r["variant"], r["state"], ", ".join(r["mandatory_failed"]) or "-"))
    at16 = summary["at16"]
    lines += ["", "## AT16: direct versus hosted analytical worker", "",
              "- worker build `%s`; hosted backend `%s`, exit %s; direct and hosted output bytes equal: **%s**" % (
                  at16["worker_identity"]["worker_build"][:16], at16["worker_identity"]["hosted_backend"], at16["worker_identity"]["hosted_exit_code"],
                  at16["direct_hosted_comparison"]["equal"]),
              "- scope controls: " + ", ".join("%s=%s" % kv for kv in at16["scope_controls"].items()),
              "- collision control: legacy padded signatures equal %s, retained signatures differ %s, cache keys differ %s" % (
                  at16["collision_control"]["legacy_padded_signature_equal"], at16["collision_control"]["retained_signatures_differ"],
                  at16["collision_control"]["cache_keys_differ"]), ""]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
