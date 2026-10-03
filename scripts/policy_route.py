#!/usr/bin/env python3
"""G3 route: train readout policies from explicit task outcomes, then promote on held-out evidence.

    scripts/policy_route.py train --run evidence/wp13/run4a-train --out evidence/wp13/policies
    scripts/policy_route.py promote --train-out evidence/wp13/policies --eval-run evidence/wp13/run4b-eval \
        --held-out stateful --candidate channels --out evidence/wp13/promotion

``train`` reads every Gabriel unit of a training run: the router decisions retained in each
unit workspace's memory (channels at the failed-verification boundary) labeled with the
independent verification of that run, and the episodes (goal, final diff, outcome). It fits a
logistic readout on the progress channels and one on the reference recurrent features,
reports leave-one-family-out decision loss against the rule (always repair), and writes the
candidate policy records, the training manifest, the metrics and the frozen episode seed.

``promote`` reads the frozen evaluation run, records every unit's verified outcome as a
production outcome label per system in a promotion workspace, computes the declared criterion
on the held-out family, and asks the memory service for the promotion decision (held-out
families must be disjoint from the training families). Nothing is promoted on training data.
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

from gabriel_agent.agent import Workspace  # noqa: E402
from gabriel_agent.artifacts import ObjectStore  # noqa: E402
from gabriel_agent.contracts.codec import canonical, loads  # noqa: E402
from gabriel_agent.memory import MemoryService  # noqa: E402
from gabriel_agent.policy import features as progress  # noqa: E402
from gabriel_agent.policy import recurrent, router  # noqa: E402


def _unit_memory(run_dir: Path, system: str, rep: int):
    ws_dir = run_dir / ("%s-%d-ws" % (system, rep))
    if not (ws_dir / "memory.sqlite").is_file():
        return None
    store = ObjectStore.open(ws_dir / "objects")
    return MemoryService.open(ws_dir / "memory.sqlite", store, lambda: 0)


def collect(run_root: Path, systems=("gabriel", "gabriel_reference_plan")) -> dict:
    results = json.loads((run_root / "results.json").read_text())
    samples, episodes, units = [], [], []
    for record in results["records"]:
        if record["system"] not in systems or record.get("outcome") is None:
            continue
        # unit directories are addressed relative to the run root: a retained run may have been moved
        memory = _unit_memory(run_root / "runs" / Path(record["run_dir"]).name, record["system"], record["rep"])
        if memory is None:
            continue
        try:
            decisions = sorted(memory.observations_of_kind("router_decision"), key=lambda o: (o["source_object_id"], o["source_revision"]))
            history = []
            for observation in decisions:
                decision = loads(memory.content(observation), ascii_only=False)
                samples.append({"task_id": record["task_id"], "family": record["family"], "rep": record["rep"], "run_id": decision["run_id"],
                                "decision_id": decision["decision_id"], "channels": decision["channels"], "history": list(history),
                                "label": int(record["V"]), "action_taken": decision["action"], "score_milli": decision["score_milli"]})
                history.append(decision["channels"])
            for observation in memory.observations_of_kind("episode"):
                text = memory.content(observation).decode("utf8")
                episodes.append({"id": "%s-%s-%d" % (record["task_id"], record["system"], record["rep"]), "task_id": record["task_id"],
                                 "family": record["family"], "verified": int(record["V"]), "text": text})
            units.append({"task_id": record["task_id"], "family": record["family"], "system": record["system"], "rep": record["rep"],
                          "V": record["V"], "decisions": len(decisions)})
        finally:
            memory.close()
    return {"samples": samples, "episodes": episodes, "units": units, "protocol_frozen_digest": results["protocol_frozen_digest"]}


def probability_loss(pairs: list) -> dict:
    """Log-loss and accuracy of retained decision probabilities against the labels."""
    import math
    total, correct = 0.0, 0
    for p, label in pairs:
        p = min(max(p, 1e-6), 1 - 1e-6)
        total += -(label * math.log(p) + (1 - label) * math.log(1 - p))
        correct += int((p >= 0.5) == bool(label))
    n = max(1, len(pairs))
    return {"log_loss": total / n, "accuracy": correct / n, "samples": len(pairs)}


def vectors(samples: list, source: str, config: dict | None) -> list:
    out = []
    for s in samples:
        if source == "channels":
            out.append((progress.as_vector(s["channels"]), s["label"]))
        else:
            events = [progress.as_vector(c) for c in s["history"]] + [progress.as_vector(s["channels"])]
            out.append((recurrent.extract(config, events)["features"], s["label"]))
    return out


def leave_one_family_out(samples: list, source: str, config: dict | None) -> dict:
    families = sorted({s["family"] for s in samples})
    per_family, rule_loss, fit_loss = {}, [], []
    for held in families:
        train = [s for s in samples if s["family"] != held]
        test = [s for s in samples if s["family"] == held]
        if not train or not test or len({s["label"] for s in train}) < 2:
            per_family[held] = {"skipped": "not enough labeled training decisions"}
            continue
        fit = router.train_logistic(vectors(train, source, config))
        test_vectors = vectors(test, source, config)
        per_family[held] = {"readout": router.log_loss((fit["weights"], fit["bias"]), test_vectors), "rule": router.log_loss(router.rule_based(), test_vectors),
                            "train_samples": len(train), "test_samples": len(test)}
        rule_loss.append(per_family[held]["rule"]["log_loss"])
        fit_loss.append(per_family[held]["readout"]["log_loss"])
    return {"per_family": per_family, "mean_readout_loss": sum(fit_loss) / len(fit_loss) if fit_loss else None,
            "mean_rule_loss": sum(rule_loss) / len(rule_loss) if rule_loss else None}


def train(args) -> int:
    run_root = Path(args.run)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    data = collect(run_root, systems=tuple(args.systems.split(",")))
    samples = data["samples"]
    labels = sorted({s["label"] for s in samples})
    manifest = {"schema": "gabriel.evidence.policy-training/1", "produced_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                "training_run": str(run_root), "protocol_frozen_digest": data["protocol_frozen_digest"], "units": data["units"],
                "decision_samples": len(samples), "positive_samples": sum(s["label"] for s in samples),
                "families": sorted({s["family"] for s in samples}), "channel_schema_id": progress.CHANNEL_SCHEMA_ID,
                "label_rule": "1 when the run's final tree passed the independent verification, else 0; one sample per retained router decision"}
    (out / "samples.json").write_text(json.dumps(samples, indent=1) + "\n")
    (out / "episode_seed.json").write_text(json.dumps(data["episodes"], indent=1) + "\n")
    metrics, policies = {}, {}
    if len(labels) < 2 or len(samples) < 4:
        manifest["note"] = "no readout can be trained: the training run produced %d decision samples with labels %s" % (len(samples), labels)
        (out / "training_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        (out / "metrics.json").write_text(json.dumps({"trained": False}, indent=2) + "\n")
        print(manifest["note"])
        return 0
    # ADR-22: the channel layout is the one the training decisions carry (generic channels, or generic plus
    # the pack's declared channels); a readout is bound to that layout and refuses any other
    layouts = sorted({s["channels"]["channel_schema_id"] for s in samples})
    if len(layouts) != 1:
        raise SystemExit("training decisions carry more than one channel layout: %s" % layouts)
    layout, dimension = layouts[0], len(progress.as_vector(samples[0]["channels"]))
    manifest["channel_schema_id"] = layout
    manifest["channel_names"] = progress.vector_names(samples[0]["channels"])
    config = recurrent.default_config(units=16, parents=4, channels=dimension)
    for source in ("channels", "recurrent"):
        cfg = config if source == "recurrent" else None
        validation = leave_one_family_out(samples, source, cfg)
        fit = router.train_logistic(vectors(samples, source, cfg))
        resub = router.log_loss((fit["weights"], fit["bias"]), vectors(samples, source, cfg))
        policy = router.readout_policy("readout-%s-v2" % source, feature_source=source, weights=fit["weights"], bias=fit["bias"],
                                       threshold_milli=500, episodes=args.episodes, recurrent_config=cfg, channel_schema_id=layout)
        policies[source] = policy
        metrics[source] = {"validation": validation, "resubstitution": resub, "policy_digest": router.policy_digest(policy),
                           "code_identity": hashlib.sha256((ROOT / "src/gabriel_agent/policy/router.py").read_bytes()).hexdigest()}
        (out / ("policy-%s.json" % source)).write_text(json.dumps(policy, indent=1) + "\n")
    metrics["rule"] = {"validation_mean_loss": metrics["channels"]["validation"]["mean_rule_loss"]}
    metrics["trained"] = True
    selected = min(("channels", "recurrent"), key=lambda s: metrics[s]["validation"]["mean_readout_loss"] if metrics[s]["validation"]["mean_readout_loss"] is not None else 9e9)
    metrics["selected_on_validation"] = selected
    (out / "training_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (out / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    print("samples", len(samples), "positives", manifest["positive_samples"], "selected", selected)
    for source in ("channels", "recurrent"):
        v = metrics[source]["validation"]
        print("%-10s validation readout loss %s rule loss %s" % (source, v["mean_readout_loss"], v["mean_rule_loss"]))
    return 0


def promote(args) -> int:
    train_out, eval_run, out = Path(args.train_out), Path(args.eval_run), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((train_out / "training_manifest.json").read_text())
    metrics = json.loads((train_out / "metrics.json").read_text())
    results = json.loads((eval_run / "results.json").read_text())
    report = json.loads((eval_run / "report.json").read_text())
    held_out = sorted(args.held_out.split(","))
    protocol = json.loads((eval_run / "protocol.json").read_text())
    held = report.get("held_out") or {}
    per_system = held.get("per_system", {})
    baseline, treatment = per_system.get(args.baseline), per_system.get(args.treatment)
    criterion = {"declared": protocol.get("declared_criterion"), "held_out_families": held_out, "baseline": args.baseline, "treatment": args.treatment}
    if baseline and treatment:
        criterion.update({"success_baseline": baseline["p_success"], "success_treatment": treatment["p_success"],
                          "requests_baseline": baseline["mean_model_requests"], "requests_treatment": treatment["mean_model_requests"],
                          "tokens_baseline": baseline["mean_model_tokens"], "tokens_treatment": treatment["mean_model_tokens"],
                          "false_completions_treatment": treatment["false_completions"],
                          "met": treatment["p_success"] >= baseline["p_success"] and treatment["mean_model_tokens"] < baseline["mean_model_tokens"]
                          and treatment["false_completions"] == 0})
    else:
        criterion.update({"met": False, "note": "held-out results for the baseline or the treatment are missing"})
    candidate_path = train_out / ("policy-%s.json" % args.candidate)
    if not metrics.get("trained") or not candidate_path.is_file():
        # No readout exists: record the rejection with the reason instead of pretending a candidate.
        promotion = {"schema": "gabriel.evidence.policy-promotion/1", "produced_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                     "candidate": None, "policy_id": None, "policy_digest": None, "held_out_families": held_out,
                     "promotion": {"decision": "rejected", "reason": manifest.get("note", "no trained readout candidate")},
                     "training_manifest": {k: manifest[k] for k in ("training_run", "protocol_frozen_digest", "decision_samples", "positive_samples", "families")},
                     "evaluation_run": str(eval_run), "treatment_criterion": criterion, "held_out_report": per_system}
        (out / "promotion.json").write_text(json.dumps(promotion, indent=2, default=str) + "\n")
        print("promotion: rejected -", promotion["promotion"]["reason"])
        print("treatment criterion (%s vs %s) met: %s" % (args.treatment, args.baseline, criterion.get("met")))
        return 0
    policy = json.loads(candidate_path.read_text())
    ws = Workspace.create(out / "promotion-workspace", backend="trusted_local", allow_trusted_local=True)
    try:
        memory = ws.memory
        for record in results["records"]:
            if record.get("outcome") is None:
                continue
            # every held-out family counts toward one held-out source per system (ADR-22: several held-out families)
            bucket = "held-out" if record["family"] in held_out else record["family"]
            memory.record_outcome(issue_id="%s-%s-%d" % (record["task_id"], record["system"], record["rep"]), run_id=record["system"] + "-" + record["task_id"],
                                  source_id="%s:%s" % (record["system"], bucket), maturity_condition={"condition": "independent verification executed"},
                                  outcome="success" if record["V"] else "failure", status_kind="production",
                                  detail={"declared": record["D"], "false_completion": record["false_completion"], "requests": record["outcome"]["model_requests"],
                                          "tokens": record["outcome"]["model_tokens"], "family": record["family"]})
        # decision loss on the held-out decisions of the treatment: the readout's retained score against the rule (always repair)
        held_samples = [s for s in collect(eval_run, systems=(args.treatment,))["samples"] if s["family"] in held_out]
        losses = {"samples": len(held_samples), "positives": sum(s["label"] for s in held_samples)}
        if held_samples:
            losses["readout"] = probability_loss([(s["score_milli"] / 1000.0, s["label"]) for s in held_samples])
            losses["rule"] = probability_loss([(0.999, s["label"]) for s in held_samples])
            losses["note"] = "a stop ends the run unverified, so a stopped decision is labeled 0 whatever a repair would have done; the success clause of the criterion guards against that"
        criterion["held_out_decision_loss"] = losses
        candidate = {"candidate_id": policy["policy_id"] + "-" + router.policy_digest(policy)[:12], "policy_kind": "router-readout",
                     "training_manifest_ref": memory.store.put(json.dumps({"training_run": manifest["training_run"], "units": manifest["units"]}, sort_keys=True).encode("utf8"), "application/json"),
                     "code_identity": metrics[args.candidate]["code_identity"], "config_ref": memory.store.put(canonical(policy), "application/json"),
                     "metrics_ref": memory.store.put(json.dumps({"decision": metrics[args.candidate]}, sort_keys=True).encode("utf8"), "application/json"),
                     "training_families": manifest["families"]}
        # the memory service's rule: disjoint held-out families and effective support over refutations
        decision = memory.promote(candidate, held_out={"source_id": args.treatment + ":held-out", "families": held_out})
        if decision["promotion"]["decision"] == "promoted" and not criterion["met"]:
            decision = memory.promote(dict(candidate, candidate_id=candidate["candidate_id"] + "-criterion"), held_out=None)
            decision["promotion"]["reason"] = "held-out criterion not met: " + json.dumps(criterion)[:400]
        promotion = {"schema": "gabriel.evidence.policy-promotion/1", "produced_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                     "candidate": candidate["candidate_id"], "policy_id": policy["policy_id"], "policy_digest": router.policy_digest(policy),
                     "criterion": criterion, "promotion": decision["promotion"], "held_out_support": memory.effective_support(args.treatment + ":held-out"),
                     "baseline_support": memory.effective_support(args.baseline + ":held-out"), "memory_anchor": memory.anchor()}
        (out / "promotion.json").write_text(json.dumps(promotion, indent=2, default=str) + "\n")
        print("promotion:", decision["promotion"]["decision"], "-", decision["promotion"]["reason"])
        print("criterion met:", criterion.get("met"))
        return 0
    finally:
        ws.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="G3 route: train and promote router policies")
    sub = parser.add_subparsers(dest="command", required=True)
    t = sub.add_parser("train"); t.add_argument("--run", required=True); t.add_argument("--out", required=True); t.add_argument("--episodes", type=int, default=2)
    t.add_argument("--systems", default="gabriel,gabriel_reference_plan", help="systems whose retained router decisions are the training samples")
    p = sub.add_parser("promote"); p.add_argument("--train-out", required=True); p.add_argument("--eval-run", required=True)
    p.add_argument("--held-out", required=True); p.add_argument("--candidate", default="channels"); p.add_argument("--out", required=True)
    p.add_argument("--baseline", default="gabriel_reference_plan"); p.add_argument("--treatment", default="gabriel_policy")
    args = parser.parse_args(argv)
    return train(args) if args.command == "train" else promote(args)


if __name__ == "__main__":
    raise SystemExit(main())
