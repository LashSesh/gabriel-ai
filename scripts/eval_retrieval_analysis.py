#!/usr/bin/env python3
"""Retain, per Gabriel unit of an association-tier run, what the retrieval actually carried.

For every record of a `gabriel_*` system the script opens the retained workspace, reads the
evaluated run's observed snapshot and its retrieval manifest, and records the rank, lexical score
and structural score of the topic's visible and hidden source, the association record's status
and seeds, and whether each source reached the first worker prompt. The output,
``<run>/retrieval_analysis.json``, is what protocol 6's analysis is based on (ADR-20).

Usage: scripts/eval_retrieval_analysis.py evidence/wp15/<run-dir> [...]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gabriel_agent.agent.workspace import Workspace  # noqa: E402
from gabriel_agent.contracts.codec import loads  # noqa: E402
from gabriel_agent.evaluation import corpus_domains as cd  # noqa: E402

PAIRS = {topic[0]: (topic[1][0], topic[2][0]) for topic in cd.ASSOCIATION_TOPICS}


def analyze(run_dir: Path) -> dict:
    results = json.loads((run_dir / "results.json").read_text())
    rows = []
    for rec in sorted(results["records"], key=lambda r: (r["task_id"], r["system"], r["rep"])):
        if not rec["system"].startswith("gabriel") or rec["task_id"].split("-", 1)[1] not in PAIRS:
            continue
        gabriel = rec["outcome"].get("gabriel") or {}
        if not gabriel.get("workspace"):
            continue
        visible, hidden = PAIRS[rec["task_id"].split("-", 1)[1]]
        ws = Workspace.open(gabriel["workspace"])
        try:
            projection = ws.owner.projection(gabriel["run_id"])
            snapshot = loads(ws.store.get(projection["run_meta"]["observed_snapshot_ref"]))
            manifest = loads(ws.store.get(snapshot["retrieval_manifest_ref"]))
            items = manifest["items"]
            ranks = {it["source_id"]: [i + 1, it["score_milli"], it.get("structural_milli")] for i, it in enumerate(items)}
            record = manifest.get("association") or {}
            nodes = projection["nodes"]
            propose = sorted(n for n in nodes if n.startswith("propose") and nodes[n].get("outputs", {}).get("request"))
            prompt = ""
            if propose:
                request = loads(ws.store.get(nodes[propose[0]]["outputs"]["request"]))
                prompt = ws.store.get(request["prompt_ref"]).decode("utf8")
            masses = record.get("masses_milli")
            rows.append({"task": rec["task_id"], "system": rec["system"], "rep": rec["rep"], "V": rec["verification"]["verified"],
                         "items": len(items), "excluded_budget": sum(1 for e in manifest.get("excluded", []) if e["reason"] == "budget"),
                         "visible_rank": ranks.get(visible), "hidden_rank": ranks.get(hidden), "assoc_status": record.get("status") or None,
                         "seeds": record.get("seeds"), "frontier": manifest.get("frontier"),
                         "masses": ({k: v for k, v in masses.items() if v} if isinstance(masses, dict) else masses),
                         "visible_in_prompt": ("source %s revision" % visible) in prompt, "hidden_in_prompt": ("source %s revision" % hidden) in prompt,
                         "first_node": propose[:1], "prompt_bytes": len(prompt)})
        finally:
            ws.close()
    budgeted = [r for r in rows if r["task"].startswith(("da-", "du-"))]
    summary = {"gabriel_units": len(rows), "budgeted_units": len(budgeted),
               "budgeted_without_visible_source_in_prompt": sum(1 for r in budgeted if not r["visible_in_prompt"]),
               "budgeted_associative_units": sum(1 for r in budgeted if r["system"] == "gabriel_associative"),
               "budgeted_associative_without_seed": sum(1 for r in budgeted if r["assoc_status"] == "no_seeds_in_history"),
               "needed_associative_with_hidden_in_prompt": sum(1 for r in rows if r["task"].startswith("da-") and r["system"] == "gabriel_associative" and r["hidden_in_prompt"]),
               "needed_reference_with_hidden_in_prompt": sum(1 for r in rows if r["task"].startswith("da-") and r["system"] == "gabriel_reference_plan" and r["hidden_in_prompt"])}
    return {"schema": "gabriel.evidence.retrieval-analysis/1", "run": str(run_dir), "protocol_frozen_digest": results.get("protocol_frozen_digest"),
            "note": "per Gabriel unit: retrieval manifest ranks of the visible and hidden source [rank, score_milli, structural_milli], association record "
                    "status and seeds, and whether each source reached the first worker prompt; read from the retained workspaces",
            "summary": summary, "rows": rows}


def main(argv: list) -> int:
    if not argv:
        print(__doc__)
        return 2
    for arg in argv:
        run_dir = Path(arg)
        out = analyze(run_dir)
        (run_dir / "retrieval_analysis.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
        print(run_dir, json.dumps(out["summary"], sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
