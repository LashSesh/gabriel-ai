"""Frozen-protocol evaluation harness and report.

Freeze first: the protocol (systems, provider, budgets, repetitions, task
identities, verification and metric definitions) is digested before any run.
``run`` refuses a protocol whose digest no longer matches. Every outcome is
retained with its raw provider envelopes, final tree patch and verification
output; failures are never discarded.

Metrics follow the blueprint: for N admitted tasks, verified success
V_i in {0,1}, declared success D_i in {0,1},
p_success = mean(V), p_false_completion = mean(D * (1 - V)), plus the
conditional false-completion fraction among declared successes with its own
denominator. Costs are reported per task. Uncertainty uses resampling
clustered by task family; the number of families is reported beside the
number of runs. Time limits count as failures.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import random
import statistics
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from ..contracts.codec import canonical
from ..contracts.errors import Code, GabrielError
from . import comparators, comparators_domains, corpus

PROTOCOL_SCHEMA = "gabriel.evaluation-protocol/1"


def harness_identity() -> str:
    here = Path(__file__).resolve().parent
    parts = []
    for name in ("corpus.py", "comparators.py", "harness.py"):
        parts.append(hashlib.sha256((here / name).read_bytes()).hexdigest())
    return hashlib.sha256("".join(parts).encode()).hexdigest()


def default_protocol(provider: dict, *, repetitions: int = 2, systems=comparators.SYSTEMS, backend: str = "linux_namespace",
                     budget: dict | None = None, task_ids=None, held_out_families=(), note: str = "", tiers=None,
                     policy: dict | None = None, episode_seed: list | None = None, declared_criterion: str = "") -> dict:
    budget = dict(comparators.Budget().__dict__, **(budget or {}))
    tasks = [t for t in corpus.tasks() if (task_ids is None or t.task_id in task_ids) and (tiers is None or t.tier in tiers)]
    if any(s in comparators.G3_SYSTEMS for s in systems) and policy is None:
        raise GabrielError(Code.INVALID_SCHEMA, "the G3 systems need a frozen router policy in the protocol")
    selected_tiers = sorted({t.tier for t in tasks})
    treatment = "gabriel" if "gabriel" in systems else ("gabriel_reference_plan" if "gabriel_reference_plan" in systems else None)
    return {
        "schema": PROTOCOL_SCHEMA,
        "purpose": "Matched comparison: increase independently verified task success or reduce resources at equal success, "
                   "under a fixed task distribution and matched constraints. Not a benchmark of general capability.",
        "corpus_digest": corpus.corpus_digest(selected_tiers),
        "tasks": [{"task_id": t.task_id, "family": t.family, "tier": t.tier, "digest": t.digest()} for t in tasks],
        "families": sorted({t.family for t in tasks}),
        "tiers": selected_tiers,
        "systems": list(systems),
        # paired differences: the treatment against every other system (verified success and model tokens per task)
        "paired": [[treatment, s] for s in systems if treatment and s != treatment],
        "provider": {k: v for k, v in provider.items() if k != "script"},
        "budget_per_task": budget,
        "repetitions": repetitions,
        "backend": backend,
        "declared_success": {
            "provider_only": "an admissible patch was applied (no verification)",
            "simple_loop": "the system's own runs of the visible tests and the oracle both exited 0",
            "gabriel": "run state succeeded (every mandatory check passed with eligible evidence, artifacts verified, effects reconciled)",
            "gabriel_no_repair": "as gabriel, with max_repairs=0 and max_plan_versions=1 (ablation of the repair cycle)",
            "gabriel_reference_plan": "as gabriel, with the domain pack's deterministic reference plan admitted without a planner request (planner ablation)",
            "gabriel_policy": "as gabriel_reference_plan, with the frozen readout policy pinned: at a failed verification it chooses repair or "
                              "stop from the progress channels, and it may retrieve frozen episodes into the worker prompt",
            "gabriel_episodes": "as gabriel_reference_plan (rule-based repair) with the frozen episodes retrievable into the worker prompt (readout ablation)",
            # document and numerical tiers (protocol 5): the same names, declared per family
            "document_and_numerical_tiers": comparators_domains.DECLARED_SUCCESS},
        "policy": policy,
        "episode_seed": episode_seed,
        "declared_criterion": declared_criterion,
        "verification": "fresh, system-independent: changed paths within allowed_paths; visible tests exit 0; oracle installed from the "
                        "corpus text and exit 0; all executed in the containment backend on the final tree",
        "metrics": ["p_success = mean(V)", "p_false_completion = mean(D*(1-V))", "conditional false completion = sum(D*(1-V))/sum(D)",
                    "model requests, model tokens and wall time per run", "recovery: Gabriel runs that used repair cycles or extra plan versions",
                    "paired differences gabriel - baseline per task (mean over repetitions)",
                    "bootstrap percentile intervals, resampling task families with replacement (and tasks as a secondary view)"],
        "time_limit_is_failure": True,
        "bootstrap": {"resamples": 2000, "seed": 20261002},
        "sample_size_statement": "%d tasks in %d families; the minimum relevant effect is not predeclared from a pilot, so intervals are "
                                 "reported as descriptive uncertainty, not as a powered test" % (len(tasks), len({t.family for t in tasks})),
        "held_out_families": sorted(held_out_families),
        "note": note,
    }


def freeze(protocol: dict, path: Path) -> dict:
    body = {k: v for k, v in protocol.items() if k not in ("frozen_digest", "frozen_at_utc", "harness_identity")}
    frozen = dict(body, frozen_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  harness_identity=harness_identity(), frozen_digest=hashlib.sha256(canonical(body)).hexdigest())
    Path(path).write_text(json.dumps(frozen, indent=2, sort_keys=True) + "\n")
    return frozen


def check_frozen(protocol: dict) -> dict:
    body = {k: v for k, v in protocol.items() if k not in ("frozen_digest", "frozen_at_utc", "harness_identity")}
    digest = hashlib.sha256(canonical(body)).hexdigest()
    if digest != protocol.get("frozen_digest"):
        raise GabrielError(Code.POLICY_DENIED, "protocol was modified after freezing (digest mismatch)")
    # the protocol pins the digest of the tiers it uses; protocols 1 to 4 pinned the digest of every software task
    if protocol["corpus_digest"] not in (corpus.corpus_digest(protocol.get("tiers")), corpus.legacy_corpus_digest()):
        raise GabrielError(Code.POLICY_DENIED, "corpus changed after the protocol was frozen")
    return {"frozen_digest": digest, "harness_identity_now": harness_identity(),
            "harness_amended": harness_identity() != protocol.get("harness_identity")}


def _unit(protocol, task, system, rep, out_dir, provider):
    run_dir = Path(out_dir) / "runs" / ("%s--%s--%d" % (task.task_id, system, rep))
    record = {"task_id": task.task_id, "family": task.family, "system": system, "rep": rep, "run_dir": str(run_dir)}
    started = time.monotonic()
    try:
        budget = comparators.Budget(**{k: protocol["budget_per_task"][k] for k in comparators.Budget().__dict__})
        if getattr(task, "domain", "software") == "software":
            ctx = comparators.EvalContext(task, run_dir, provider, budget, protocol["backend"])
            runners, verify = comparators.RUNNERS, comparators.verify
        else:
            ctx = comparators_domains.DomainEvalContext(task, run_dir, provider, budget, protocol["backend"])
            runners, verify = comparators_domains.RUNNERS, comparators_domains.verify
        record["domain"] = getattr(task, "domain", "software")
        ctx.policy = protocol.get("policy")
        ctx.episode_seed = protocol.get("episode_seed")
        try:
            outcome = runners[system](ctx, rep)
            verification = verify(ctx, outcome.worktree, "eval-verify-%s-%s-%d" % (task.task_id, system, rep))
        finally:
            if hasattr(ctx, "close"):
                ctx.close()
        record.update({"outcome": outcome.to_dict(), "verification": verification,
                       "V": int(verification["verified"]), "D": int(outcome.declared),
                       "false_completion": int(outcome.declared and not verification["verified"])})
    except Exception as exc:  # noqa: BLE001 - a harness failure is a recorded failed run, never a dropped sample
        record.update({"outcome": None, "verification": None, "V": 0, "D": 0, "false_completion": 0,
                       "harness_error": type(exc).__name__ + ": " + str(exc)[:500], "traceback": traceback.format_exc()[-3000:]})
    record["unit_wall_ms"] = int((time.monotonic() - started) * 1000)
    (run_dir / "record.json").parent.mkdir(parents=True, exist_ok=True)
    (run_dir / "record.json").write_text(json.dumps(record, indent=2, default=str) + "\n")
    return record


def run(protocol: dict, out_dir: Path, provider: dict, *, workers: int = 3, systems=None, task_ids=None, repetitions=None) -> dict:
    """Execute every (task, system, repetition) unit; retain everything under out_dir."""
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    check = check_frozen(protocol)
    tasks = [t for t in corpus.tasks() if any(t.task_id == row["task_id"] for row in protocol["tasks"])]
    if task_ids:
        tasks = [t for t in tasks if t.task_id in task_ids]
    systems = list(systems or protocol["systems"])
    reps = repetitions or protocol["repetitions"]
    units = [(t, s, r) for t in tasks for s in systems for r in range(reps) if comparators_domains.applicable(s, t)]
    (out_dir / "protocol.json").write_text(json.dumps(protocol, indent=2, sort_keys=True) + "\n")
    records = []
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_unit, protocol, t, s, r, out_dir, provider): (t.task_id, s, r) for t, s, r in units}
        for future in as_completed(futures):
            records.append(future.result())
    records.sort(key=lambda r: (r["task_id"], r["system"], r["rep"]))
    results = {"schema": "gabriel.evaluation-results/1", "protocol_frozen_digest": protocol["frozen_digest"], "frozen_check": check,
               "started_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(), "wall_ms": int((time.monotonic() - started) * 1000),
               "units": len(records), "records": records}
    (out_dir / "results.json").write_text(json.dumps(results, indent=2, default=str) + "\n")
    return results


# ------------------------------------------------------------------ report

def _mean(values):
    return statistics.fmean(values) if values else 0.0


def _bootstrap(values_by_cluster: dict, statistic, resamples: int, seed: int):
    """Percentile interval by resampling clusters with replacement."""
    clusters = sorted(values_by_cluster)
    if not clusters:
        return None
    rng = random.Random(seed)
    draws = []
    for _ in range(resamples):
        sample = [rng.choice(clusters) for _ in clusters]
        pooled = [v for c in sample for v in values_by_cluster[c]]
        draws.append(statistic(pooled))
    draws.sort()
    return {"low": draws[int(0.025 * (len(draws) - 1))], "high": draws[int(0.975 * (len(draws) - 1))], "clusters": len(clusters)}


def report(results: dict, protocol: dict) -> dict:
    full = _report(results["records"], protocol)
    full["frozen_check"] = results.get("frozen_check")
    held_out = protocol.get("held_out_families") or []
    if held_out:
        subset = [r for r in results["records"] if r["family"] in held_out]
        full["held_out"] = _report(subset, protocol) if subset else None
        seen = [r for r in results["records"] if r["family"] not in held_out]
        full["previously_seen"] = _report(seen, protocol) if seen else None
    return full


def _report(records: list, protocol: dict) -> dict:
    systems = protocol["systems"]
    resamples, seed = protocol["bootstrap"]["resamples"], protocol["bootstrap"]["seed"]
    per_system = {}
    for system in systems:
        rows = [r for r in records if r["system"] == system]
        n = len(rows)
        declared = sum(r["D"] for r in rows)
        false_completion = sum(r["false_completion"] for r in rows)
        verified = sum(r["V"] for r in rows)
        by_family, by_task = {}, {}
        for r in rows:
            by_family.setdefault(r["family"], []).append(r["V"])
            by_task.setdefault(r["task_id"], []).append(r["V"])
        costs = [r["outcome"] for r in rows if r.get("outcome")]
        per_system[system] = {
            "runs": n, "verified_successes": verified, "p_success": verified / n if n else None,
            "declared_successes": declared, "false_completions": false_completion,
            "p_false_completion": false_completion / n if n else None,
            "conditional_false_completion": (false_completion / declared) if declared else None,
            "conditional_denominator": declared,
            "harness_errors": sum(1 for r in rows if r.get("harness_error")),
            "timed_out": sum(1 for r in rows if r.get("outcome") and r["outcome"]["timed_out"]),
            "recovery_runs": sum(1 for c in costs if c.get("repairs_used", 0) or c.get("plan_versions", 0) > 1),
            "mean_model_requests": _mean([c["model_requests"] for c in costs]),
            "total_model_requests": sum(c["model_requests"] for c in costs),
            "mean_model_tokens": _mean([c["model_tokens"] for c in costs]),
            "total_model_tokens": sum(c["model_tokens"] for c in costs),
            "mean_wall_ms": _mean([c["wall_ms"] for c in costs]),
            "p_success_ci95_by_family": _bootstrap(by_family, _mean, resamples, seed),
            "p_success_ci95_by_task": _bootstrap(by_task, _mean, resamples, seed + 1),
            "per_task": {task: {"p_success": _mean(v), "runs": len(v)} for task, v in sorted(by_task.items())},
        }
    paired = {}
    pairs = protocol.get("paired") or ([["gabriel", s] for s in systems if s != "gabriel"] if "gabriel" in systems else [])
    family_of = {r["task_id"]: r["family"] for r in records}
    for treatment, baseline in pairs:
        if treatment not in systems or baseline not in systems:
            continue
        by_task = {}
        for r in records:
            if r["system"] in (treatment, baseline):
                entry = by_task.setdefault(r["task_id"], {treatment: [], baseline: []})
                entry[r["system"]].append(r)
        diffs_by_task, tokens_by_task, requests_by_task = {}, {}, {}
        for t, entry in by_task.items():
            if not entry[treatment] or not entry[baseline]:
                continue
            diffs_by_task[t] = _mean([x["V"] for x in entry[treatment]]) - _mean([x["V"] for x in entry[baseline]])
            cost = lambda rows, key: _mean([x["outcome"][key] for x in rows if x.get("outcome")])  # noqa: E731
            tokens_by_task[t] = cost(entry[treatment], "model_tokens") - cost(entry[baseline], "model_tokens")
            requests_by_task[t] = cost(entry[treatment], "model_requests") - cost(entry[baseline], "model_requests")
        diffs_by_family = {}
        for t, d in diffs_by_task.items():
            diffs_by_family.setdefault(family_of[t], []).append(d)
        paired["%s_minus_%s" % (treatment, baseline)] = {
            "per_task": diffs_by_task, "mean": _mean(list(diffs_by_task.values())),
            "ci95_by_family": _bootstrap(diffs_by_family, _mean, resamples, seed + 2),
            "ci95_by_task": _bootstrap({t: [d] for t, d in diffs_by_task.items()}, _mean, resamples, seed + 3),
            "tokens_per_task": tokens_by_task, "mean_tokens": _mean(list(tokens_by_task.values())),
            "requests_per_task": requests_by_task, "mean_requests": _mean(list(requests_by_task.values()))}
    failures = [{"task_id": r["task_id"], "system": r["system"], "rep": r["rep"], "declared": bool(r["D"]), "verified": bool(r["V"]),
                 "reason": (r.get("outcome") or {}).get("declared_reason") or r.get("harness_error"),
                 "oracle_exit": ((r.get("verification") or {}).get("oracle") or {}).get("exit_code"),
                 "visible_exit": ((r.get("verification") or {}).get("visible") or {}).get("exit_code"),
                 "out_of_scope": (r.get("verification") or {}).get("out_of_scope_paths"),
                 "problems": (r.get("verification") or {}).get("problems"),
                 "provider_statuses": (r.get("outcome") or {}).get("provider_statuses")}
                for r in records if not r["V"] or r["false_completion"]]
    return {"schema": "gabriel.evaluation-report/1", "protocol_frozen_digest": protocol["frozen_digest"],
            "tasks": len({r["task_id"] for r in records}),
            "families": len({r["family"] for r in records}), "runs": len(records), "per_system": per_system,
            "paired_differences": paired, "failures": failures,
            "claim_scope": "Scoped comparison on one synthetic task distribution with one provider; a difference here is not a general "
                           "superiority claim. Costs include every attempt, including failed and timed-out runs."}


def _table(per_system: dict) -> list:
    lines = ["| system | runs | verified | p_success | CI95 (families) | declared | false completions | cond. FC | mean requests | mean tokens | mean wall s | recovery |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for system, m in per_system.items():
        ci = m["p_success_ci95_by_family"]
        lines.append("| %s | %d | %d | %.2f | [%.2f, %.2f] | %d | %d | %s | %.2f | %.0f | %.1f | %d |" % (
            system, m["runs"], m["verified_successes"], m["p_success"] or 0, ci["low"] if ci else 0, ci["high"] if ci else 0,
            m["declared_successes"], m["false_completions"],
            ("%.2f (n=%d)" % (m["conditional_false_completion"], m["conditional_denominator"])) if m["conditional_false_completion"] is not None else "n/a (0 declared)",
            m["mean_model_requests"], m["mean_model_tokens"], m["mean_wall_ms"] / 1000, m["recovery_runs"]))
    return lines


def render_markdown(rep: dict, protocol: dict) -> str:
    lines = ["# G1 matched evaluation report", "",
             "Protocol `%s` (frozen %s), provider `%s` model `%s`, backend `%s`, %d tasks in %d families, %d runs." % (
                 protocol["frozen_digest"][:16], protocol.get("frozen_at_utc", "?"), protocol["provider"].get("kind"),
                 protocol["provider"].get("model"), protocol["backend"], rep["tasks"], rep["families"], rep["runs"]), ""]
    if rep.get("frozen_check", {}).get("harness_amended"):
        lines.append("**Harness code changed after freezing** (task set and settings unchanged); see frozen_check.")
        lines.append("")
    if protocol.get("note"):
        lines += [protocol["note"], ""]
    lines += ["## All tasks", ""] + _table(rep["per_system"])
    if rep.get("held_out"):
        lines += ["", "## Held-out families only (%s): never run before this protocol" % ", ".join(protocol["held_out_families"]), ""] + _table(rep["held_out"]["per_system"])
    if rep.get("previously_seen"):
        lines += ["", "## Previously seen tasks only (not a held-out test)", ""] + _table(rep["previously_seen"]["per_system"])
    lines += ["", "## Paired differences, all tasks (treatment minus baseline per task: verified success; mean model tokens and requests)", ""]
    for name, d in rep["paired_differences"].items():
        ci = d["ci95_by_family"]
        lines.append("- %s: success mean %+.2f, CI95 by family [%+.2f, %+.2f], by task [%+.2f, %+.2f]; tokens %+.0f, requests %+.2f; per task: %s" % (
            name, d["mean"], ci["low"] if ci else 0, ci["high"] if ci else 0, d["ci95_by_task"]["low"] if d["ci95_by_task"] else 0,
            d["ci95_by_task"]["high"] if d["ci95_by_task"] else 0, d.get("mean_tokens", 0), d.get("mean_requests", 0),
            ", ".join("%s %+.1f" % (t, v) for t, v in sorted(d["per_task"].items()))))
    lines += ["", "## Retained failures and false completions", ""]
    if not rep["failures"]:
        lines.append("none")
    for f in rep["failures"]:
        detail = ("problems %s" % "; ".join(f["problems"][:3])) if f.get("problems") else ("oracle exit %s, visible exit %s" % (f["oracle_exit"], f["visible_exit"]))
        lines.append("- %s / %s / rep %d: declared=%s verified=%s; %s; %s, out of scope %s; provider %s" % (
            f["task_id"], f["system"], f["rep"], f["declared"], f["verified"], f["reason"], detail, f["out_of_scope"], f["provider_statuses"]))
    lines += ["", rep["claim_scope"], ""]
    return "\n".join(lines)
