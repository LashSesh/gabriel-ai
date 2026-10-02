"""Versioned progress channels over the committed event stream (blueprint, routing feature experiment).

An adapter maps the owner's projection of a run to normalized numerical channels: remaining
budget fractions, recent test-failure fraction, unmet mandatory obligations, repair and plan
usage, tool latency, provider failures and unresolved effects. Channel definitions, clipping,
missing-value indicators and update timing are versioned by ``CHANNEL_SCHEMA_ID``; values are
retained as integer milli-units so every record stays inside the exact codec. Nothing here
feeds arbitrary document bytes into a dynamical system: the inputs are committed run facts.
"""
from __future__ import annotations

CHANNEL_SCHEMA_ID = "progress-channels-v1"
CHANNELS = ("requests_remaining", "tokens_remaining", "tool_attempts_remaining", "elapsed_fraction", "recent_failure_fraction",
            "mandatory_unmet_fraction", "repair_fraction", "plan_version_fraction", "tool_latency", "provider_failure_fraction",
            "unresolved_effects", "goal_length")
TOOL_TIMEOUT_MS = 600000


def _clip(value: float) -> float:
    return 0.0 if value < 0.0 else 1.0 if value > 1.0 else value


def _fraction(numerator, denominator):
    if not denominator:
        return None
    return _clip(float(numerator) / float(denominator))


def progress_channels(projection: dict, binding: dict, *, owner_time_unix_ms: int, goal_text: str = "") -> dict:
    """Channel vector at this instant of the run; missing channels carry an indicator, never a guess."""
    run, meta, ledger = projection["run"], projection["run_meta"], projection["ledger"]
    budget, spent = run["budget"], ledger["spent"]
    values = {}
    values["requests_remaining"] = None if not budget.get("model_requests") else _clip(1.0 - spent.get("model_requests", 0) / budget["model_requests"])
    values["tokens_remaining"] = None if not budget.get("model_tokens_total") else _clip(1.0 - spent.get("model_tokens", 0) / budget["model_tokens_total"])
    values["tool_attempts_remaining"] = None if not budget.get("tool_attempts") else _clip(1.0 - spent.get("tool_attempts", 0) / budget["tool_attempts"])
    started = meta.get("started_owner_time_unix_ms")
    values["elapsed_fraction"] = None if started is None or not budget.get("elapsed_ms") else _clip((owner_time_unix_ms - started) / budget["elapsed_ms"])
    latest_version = meta["plan_versions"]
    recent = [a for a in projection["assessments"].values() if a.get("plan_version", latest_version) == latest_version and a["outcome"] in ("passed", "failed")]
    values["recent_failure_fraction"] = _fraction(sum(1 for a in recent if a["outcome"] == "failed"), len(recent))
    mandatory = [c for c in projection["task"]["checks"] if c["mandatory"]]
    met = {a["check_id"] for a in projection["assessments"].values() if a["eligible"] and a["outcome"] == "passed"}
    values["mandatory_unmet_fraction"] = _fraction(sum(1 for c in mandatory if c["check_id"] not in met), len(mandatory))
    values["repair_fraction"] = _fraction(meta["repair_count"], binding.get("max_repairs", 0)) if binding.get("max_repairs", 0) else None
    values["plan_version_fraction"] = _fraction(meta["plan_versions"], binding.get("max_plan_versions", 0)) if binding.get("max_plan_versions", 0) else None
    attempts = list(projection["attempts"].values())
    finished = [a for a in attempts if a["status"] not in ("issued", "marked")]
    # the additive ledger carries cpu time per attempt; the deadline clock is separate from it
    values["tool_latency"] = None if not finished else _clip(spent.get("cpu_ms", spent.get("elapsed_ms", 0)) / (len(finished) * TOOL_TIMEOUT_MS))
    provider = [a for a in finished if a["capability_id"] == "model.generate"]
    values["provider_failure_fraction"] = _fraction(sum(1 for a in provider if a["status"] != "completed"), len(provider))
    values["unresolved_effects"] = _clip(len(run["unresolved_effect_ids"]) / 4.0)
    values["goal_length"] = _clip(len(goal_text.encode("utf8")) / 4000.0)
    return {"schema": "gabriel.progress-channels/1", "channel_schema_id": CHANNEL_SCHEMA_ID, "names": list(CHANNELS),
            "values_milli": [None if values[n] is None else int(round(values[n] * 1000)) for n in CHANNELS],
            "missing": [values[n] is None for n in CHANNELS], "owner_sequence": projection["run"].get("run_revision", 0),
            "plan_versions": latest_version, "repair_count": meta["repair_count"]}


def as_vector(channels: dict) -> list:
    """Floats in [0, 1] with missing values as 0 plus one indicator per channel (fixed layout)."""
    vector = []
    for value, missing in zip(channels["values_milli"], channels["missing"]):
        vector.append(0.0 if missing else value / 1000.0)
    vector.extend(1.0 if missing else 0.0 for missing in channels["missing"])
    return vector


def vector_names() -> list:
    return list(CHANNELS) + [n + "_missing" for n in CHANNELS]
