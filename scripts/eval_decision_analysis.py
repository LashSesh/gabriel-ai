#!/usr/bin/env python3
"""Retain, per Gabriel unit of a run, what the routing policy decided (ADR-22).

For every `gabriel_*` record the script opens the retained workspace memory and reads the
run's router decisions: decision point, action, the policy, the readout score, whether the
readout abstained (pack channels missing), and the pack channels' values. It also keeps the
unit's provider statuses, so provider failures and routing decisions can be read together. The
output, ``<run>/decision_analysis.json``, carries a summary per system and family.

Usage: scripts/eval_decision_analysis.py evidence/wp15/<run-dir> [...]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gabriel_agent.artifacts import ObjectStore  # noqa: E402
from gabriel_agent.contracts.codec import loads  # noqa: E402
from gabriel_agent.memory import MemoryService  # noqa: E402


def analyze(run_dir: Path) -> dict:
    results = json.loads((run_dir / "results.json").read_text())
    rows, summary = [], {}
    for rec in sorted(results["records"], key=lambda r: (r["task_id"], r["system"], r["rep"])):
        if not rec["system"].startswith("gabriel") or rec.get("outcome") is None:
            continue
        ws_dir = run_dir / "runs" / Path(rec["run_dir"]).name / ("%s-%d-ws" % (rec["system"], rec["rep"]))
        if not (ws_dir / "memory.sqlite").is_file():
            continue
        memory = MemoryService.open(ws_dir / "memory.sqlite", ObjectStore.open(ws_dir / "objects"), lambda: 0)
        try:
            decisions = []
            for observation in sorted(memory.observations_of_kind("router_decision"), key=lambda o: (o["source_object_id"], o["source_revision"])):
                d = loads(memory.content(observation), ascii_only=False)
                if d["run_id"].startswith("history-"):
                    continue  # history runs' decisions are not the evaluated unit's
                names, values = d["channels"]["names"], d["channels"]["values_milli"]
                pack = {n: v for n, v in zip(names, values) if n not in ("requests_remaining", "tokens_remaining", "tool_attempts_remaining", "elapsed_fraction",
                                                                       "recent_failure_fraction", "mandatory_unmet_fraction", "repair_fraction", "plan_version_fraction",
                                                                       "tool_latency", "provider_failure_fraction", "unresolved_effects", "goal_length")}
                decisions.append({"decision_point": d["decision_point"], "action": d["action"], "policy_id": d["policy_id"], "score_milli": d["score_milli"],
                                  "abstained": d["reason"].startswith("readout abstains"), "layout": d["channels"]["channel_schema_id"], "pack_channels": pack,
                                  "reason": d["reason"][:160]})
        finally:
            memory.close()
        row = {"task": rec["task_id"], "family": rec["family"], "system": rec["system"], "rep": rec["rep"], "V": rec["verification"]["verified"],
               "requests": rec["outcome"]["model_requests"], "provider_statuses": rec["outcome"]["provider_statuses"], "error": rec["outcome"].get("error"),
               "decisions": decisions}
        rows.append(row)
        key = "%s|%s" % (rec["system"], rec["family"])
        s = summary.setdefault(key, {"units": 0, "verified": 0, "decisions": 0, "stops": 0, "abstentions": 0, "readout_repairs": 0,
                                     "non_completed_statuses": 0, "errors": 0})
        s["units"] += 1
        s["verified"] += int(bool(row["V"]))
        s["decisions"] += len(decisions)
        s["stops"] += sum(1 for d in decisions if d["action"] == "stop")
        s["abstentions"] += sum(1 for d in decisions if d["abstained"])
        s["readout_repairs"] += sum(1 for d in decisions if d["action"] == "repair" and not d["abstained"] and d["policy_id"].startswith("readout"))
        s["non_completed_statuses"] += sum(1 for st in row["provider_statuses"] if st != "completed")
        s["errors"] += int(bool(row["error"]))
    return {"schema": "gabriel.evidence.decision-analysis/1", "run": str(run_dir), "protocol_frozen_digest": results.get("protocol_frozen_digest"),
            "note": "per Gabriel unit: the evaluated run's retained router decisions (point, action, policy, score, abstention, pack channels) beside the "
                    "unit's provider statuses; summary per system and family", "summary": summary, "rows": rows}


def main(argv: list) -> int:
    if not argv:
        print(__doc__)
        return 2
    for arg in argv:
        run_dir = Path(arg)
        out = analyze(run_dir)
        (run_dir / "decision_analysis.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
        for key, s in sorted(out["summary"].items()):
            print(run_dir.name, key, json.dumps(s, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
