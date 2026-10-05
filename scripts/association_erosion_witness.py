#!/usr/bin/env python3
"""ADR-23 witness: erosion of the association history through the owner, with reproduction.

Usage:
    scripts/association_erosion_witness.py --out evidence/wp16 --backend linux_namespace

Three document tasks run through one workspace with the scripted provider (the mechanism under
witness is the memory's, not a model's): the history task establishes a supported claim citing
the charter and the annex together; the summary task under the associative view carries the
annex into its prompt by the engine's walk; the same summary task with the annex declared
withdrawn revokes it before its retrieval, after which the history that cited it contributes
nothing, the prompt names no annex and the record says what eroded. Both retained retrieval
manifests are then recomputed from the chain at their own frontier and access policy revision
(`MemoryService.reproduce`, also through `gabriel memory reproduce`), the owner's journal is
replayed and the memory chain verified. Everything recorded comes from the retained workspace.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from gabriel_agent.adapters import native_graph  # noqa: E402
from gabriel_agent.agent import TaskRunner, Workspace  # noqa: E402
from gabriel_agent.contracts.codec import loads  # noqa: E402
from gabriel_agent.evaluation.fixtures import document_association as da  # noqa: E402

HEADER = "Sources associated by verified history"


def _run(ws, spec: dict, label: str) -> dict:
    created = ws.create_task(spec)
    summary = TaskRunner(ws, created["task_id"]).run()
    projection = ws.owner.projection(created["run_id"])
    snapshot = loads(ws.store.get(projection["run_meta"]["observed_snapshot_ref"]))
    manifest_ref = snapshot["retrieval_manifest_ref"]
    manifest = loads(ws.store.get(manifest_ref))
    nodes = projection["nodes"]
    node = sorted(n for n in nodes if n.startswith("propose") and nodes[n].get("outputs", {}).get("request"))[0]
    request = loads(ws.store.get(nodes[node]["outputs"]["request"]))
    prompt = ws.store.get(request["prompt_ref"]).decode("utf8")
    record = manifest.get("association") or {}
    annex_items = [i for i in manifest["items"] if i["source_id"] == "annex"]
    return {"label": label, "task_id": created["task_id"], "run_id": created["run_id"], "state": summary["state"],
            "retrieval_view": snapshot.get("retrieval_view"), "declared_sources": [{k: s[k] for k in ("source_id", "access") if k in s} for s in spec["sources"][:2]],
            "claims_logged": [line for line in summary["log"] if line.startswith("claim ")],
            "retrieval_manifest_sha256": manifest_ref["sha256"], "frontier": manifest["frontier"], "access_policy_revision": manifest["access_policy_revision"],
            "items": [i["source_id"] for i in manifest["items"]][:8], "item_count": len(manifest["items"]),
            "annex": {"retrieved": bool(annex_items), "rank": (manifest["items"].index(annex_items[0]) + 1) if annex_items else None,
                      "lexical_milli": annex_items[0].get("lexical_milli") if annex_items else None, "structural_milli": annex_items[0].get("structural_milli") if annex_items else None,
                      "excluded_reasons": sorted({e["reason"] for e in manifest["excluded"]
                                                  if (ws.memory.observation(e["observation_id"]) or {}).get("source_id") == "annex"})},
            "association": {k: record.get(k) for k in ("status", "entities", "seeds", "masses_milli", "links", "erosion", "batches_sha256", "executable_sha256", "snapshot_identity")},
            "prompt": {"bytes": len(prompt.encode("utf8")), "names_annex": "source annex revision" in prompt, "has_association_heading": HEADER in prompt,
                       "states_annex_figure": "one hundred twenty" in prompt, "annex_unavailable_line": any(line.endswith(": revoked") for line in prompt.splitlines())},
            "manifest": manifest}


def _cli_reproduce(workspace: Path, sha: str) -> dict:
    proc = subprocess.run([sys.executable, "-c", "from gabriel_agent.interfaces.cli import main; raise SystemExit(main())", "memory", "reproduce",
                           "--workspace", str(workspace), "--manifest", sha], capture_output=True, text=True, cwd=str(ROOT),
                          env={"PYTHONPATH": str(ROOT / "src"), "PATH": "/usr/bin:/bin", "HOME": str(Path.home())})
    try:
        report = json.loads(proc.stdout)
    except json.JSONDecodeError:
        report = {"stdout": proc.stdout[-2000:], "stderr": proc.stderr[-2000:]}
    return {"exit_code": proc.returncode, "report": report}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", required=True)
    parser.add_argument("--backend", choices=("linux_namespace", "trusted_local"), default="linux_namespace")
    args = parser.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    work = out / "work"
    if work.exists():
        raise SystemExit("refusing to overwrite " + str(work))
    repo = work / "repo"
    base = da.build_repo(repo)
    ws = Workspace.create(work / "workspace", backend=args.backend, allow_trusted_local=(args.backend == "trusted_local"))
    try:
        doctor = ws.doctor(selftest=(args.backend == "linux_namespace"))
        steps = [_run(ws, da.history_spec(repo, base, da.history_oracle(work / "history.json"), da.provider("history")), "history"),
                 _run(ws, da.summary_spec(repo, base, da.summary_oracle(work / "summary.json"), da.provider("summary")), "summary_associative"),
                 _run(ws, da.summary_spec(repo, base, da.summary_oracle(work / "summary.json"), da.provider("summary"), revoked=("annex",),
                                          max_plan_versions=1, max_repairs=0), "summary_annex_withdrawn")]
        reproductions = {}
        for step in steps[1:]:
            reproductions[step["label"]] = {"service": ws.memory.reproduce(step["manifest"]),
                                            "cli": _cli_reproduce(work / "workspace", step["retrieval_manifest_sha256"])}
        replay = ws.owner.replay()
        verify = ws.memory.verify()
        anchor = ws.memory.anchor()
        revocations = [e for e in ws.memory.entries() if e["kind"] == "access_revocation"]
    finally:
        ws.close()
    before, after = steps[1], steps[2]
    checks = {
        "history_established_a_supported_claim": steps[0]["state"] == "succeeded" and len(steps[0]["claims_logged"]) >= 1,
        "associative_view_carried_the_annex": before["state"] == "succeeded" and before["association"]["status"] == "computed" and before["annex"]["retrieved"]
                                               and before["prompt"]["has_association_heading"] and before["prompt"]["names_annex"],
        "withdrawal_recorded_in_the_chain_by_the_run": len(revocations) == 1 and after["access_policy_revision"] == before["access_policy_revision"] + 1,
        "history_eroded_after_the_withdrawal": after["association"]["status"] == "eroded" and after["association"]["entities"] == []
                                               and after["association"]["links"] == {} and after["association"]["erosion"]["claims_contributing"] == 0
                                               and after["association"]["erosion"]["removed_by"] == {"revoked": after["association"]["erosion"]["claims_available"]},
        # the key's effective observation is the revoked one (since ADR-25 the unchanged annex is one observation across the tasks)
        "annex_absent_from_the_prompt": not after["annex"]["retrieved"] and "revoked" in after["annex"]["excluded_reasons"] and not after["prompt"]["names_annex"]
                                        and not after["prompt"]["has_association_heading"] and not after["prompt"]["states_annex_figure"],
        "no_key_outside_the_candidates_named": "annex/" not in json.dumps(after["manifest"]),
        "both_manifests_reproduce_from_the_chain": all(r["service"]["status"] == "reproduced" and r["cli"]["exit_code"] == 0
                                                       and r["cli"]["report"].get("status") == "reproduced" for r in reproductions.values()),
        "earlier_manifest_reproduces_at_its_own_revision": reproductions["summary_associative"]["service"]["access_policy_revision"] == before["access_policy_revision"]
                                                           and reproductions["summary_associative"]["service"]["current_policy_revision"] == after["access_policy_revision"],
        "owner_replay_passed": replay["status"] == "passed",
        "memory_chain_verified": verify["status"] == "passed",
    }
    witness = {"schema": "gabriel.evidence.association-erosion-witness/1", "produced_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
               "adr": "docs/adr/ADR-23-association-erosion.md", "backend": args.backend, "platform": platform.platform(),
               "doctor": {"configured_backend": doctor.get("configured_backend"), "status": doctor.get("status"), "problems": doctor.get("problems"),
                          "linux_namespace": (doctor.get("backends") or {}).get("linux_namespace")},
               "provider": {"kind": "scripted", "note": "the mechanism under witness is the memory's; the deliverables are the fixture's scripted correct ones"},
               "engine_observer_sha256": native_graph.binaries()["engine_observer"]["sha256"],
               "steps": [{k: v for k, v in step.items() if k != "manifest"} for step in steps],
               "reproductions": reproductions, "revocations": revocations, "replay": {k: replay.get(k) for k in ("status", "events", "faults") if k in replay},
               "memory_verify": {k: verify[k] for k in ("status", "entries", "head")}, "memory_anchor": anchor,
               "checks": checks, "status": "passed" if all(checks.values()) else "failed"}
    (out / "witness.json").write_text(json.dumps(witness, indent=1, sort_keys=True) + "\n")
    for step in steps:
        (out / ("manifest-%s.json" % step["label"])).write_text(json.dumps(step["manifest"], indent=1, sort_keys=True) + "\n")
    lines = ["# ADR-23 witness: erosion of the association history (%s)" % args.backend, "",
             "Produced %s on %s; `engine_observer` %s; provider scripted (fixture deliverables)." % (witness["produced_at_utc"], witness["platform"], witness["engine_observer_sha256"][:16]),
             "", "| step | state | view | policy revision | association status | annex in prompt | erosion |", "|---|---|---|---|---|---|---|"]
    for step in steps:
        er = step["association"].get("erosion") or {}
        lines.append("| %s | %s | %s | %d | %s | %s | %s |" % (step["label"], step["state"], step["retrieval_view"], step["access_policy_revision"],
                                                              step["association"].get("status"), "yes (rank %s, %s milli)" % (step["annex"]["rank"], step["annex"]["structural_milli"])
                                                              if step["annex"]["retrieved"] else "no (%s)" % ", ".join(step["annex"]["excluded_reasons"]),
                                                              ("%d/%d claims, removed %s" % (er.get("claims_contributing", 0), er.get("claims_available", 0), er.get("removed_by"))) if er else "-"))
    lines += ["", "| reproduction | service | CLI exit | retained -> recomputed status |", "|---|---|---|---|"]
    for label, rep in reproductions.items():
        lines.append("| %s | %s (differences %s) | %d | %s -> %s |" % (label, rep["service"]["status"], rep["service"]["differences"], rep["cli"]["exit_code"],
                                                                    rep["service"]["association_status"]["retained"], rep["service"]["association_status"]["recomputed"]))
    lines += ["", "| check | result |", "|---|---|"] + ["| %s | %s |" % (k, "passed" if v else "FAILED") for k, v in checks.items()]
    lines += ["", "Status: **%s**. Owner replay %s; memory chain %s (%d entries); %d revocation record(s) in the chain." %
              (witness["status"], replay["status"], verify["status"], verify["entries"], len(revocations)),
              "", "Retained: `witness.json` (every value above with the retrieval manifest digests), `manifest-<step>.json` (the three retrieval manifests as retained).",
              "The workspace under `work/` is not committed."]
    (out / "report.md").write_text("\n".join(lines) + "\n")
    print(json.dumps({"status": witness["status"], "checks": checks}, indent=1))
    return 0 if witness["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
