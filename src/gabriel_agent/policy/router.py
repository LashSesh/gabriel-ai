"""Readout router over authorized choices (blueprint, routing feature experiment; ADR-15).

At a decision point the runner asks the pinned policy for one of the already authorized
choices. The first decision point is the failed-verification boundary: request a bounded
repair (the current rule) or stop for a documented prerequisite. A policy also fixes how many
past episodes enter the worker prompt. The owner still validates every selected action; a
readout never gains rights, budget or checks.

Policy configurations are content-addressed records. ``rule_based`` is the baseline that
always repairs within the admitted limits and uses no episodes. A ``readout`` policy scores
the probability that a repair round ends in verified success from the progress channels
(optionally transformed by the reference recurrent map) with a logistic readout trained from
explicit task outcomes; it repairs when the score reaches the threshold.
"""
from __future__ import annotations

import hashlib
import math

from ..contracts.codec import canonical
from ..contracts.errors import Code, GabrielError
from . import features as progress
from . import recurrent

POLICY_SCHEMA = "gabriel.router-policy/1"
ACTIONS = ("repair", "stop")


def rule_based(*, episodes: int = 0) -> dict:
    return {"schema": POLICY_SCHEMA, "policy_id": "rule-based-v1" if not episodes else "rule-based-episodes%d-v1" % episodes, "kind": "rule_based",
            "feature_source": "channels", "channel_schema_id": progress.CHANNEL_SCHEMA_ID, "recurrent_config": None, "readout": None,
            "threshold_milli": 0, "episodes": {"k": int(episodes), "min_score_milli": 0}, "decision_point": "any_boundary"}


def readout_policy(policy_id: str, *, feature_source: str, weights: list, bias: float, threshold_milli: int = 500, episodes: int = 0,
                   recurrent_config: dict | None = None, decision_point: str = "any_boundary") -> dict:
    if feature_source not in ("channels", "recurrent"):
        raise GabrielError(Code.INVALID_SCHEMA, "unknown feature source " + feature_source)
    if feature_source == "recurrent" and recurrent_config is None:
        recurrent_config = recurrent.default_config()
    return {"schema": POLICY_SCHEMA, "policy_id": policy_id, "kind": "readout", "feature_source": feature_source,
            "channel_schema_id": progress.CHANNEL_SCHEMA_ID, "recurrent_config": recurrent_config,
            "readout": {"weights_micro": [int(round(w * 1e6)) for w in weights], "bias_micro": int(round(bias * 1e6))},
            "threshold_milli": int(threshold_milli), "episodes": {"k": int(episodes), "min_score_milli": 0}, "decision_point": decision_point}


def covers(policy: dict, boundary: str) -> bool:
    """Whether the policy decides at this boundary; otherwise the rule (repair) applies there."""
    return policy["decision_point"] == "any_boundary" or policy["decision_point"] == boundary


def policy_digest(policy: dict) -> str:
    return hashlib.sha256(canonical(policy)).hexdigest()


def feature_vector(policy: dict, channels: dict, history: list) -> list:
    """Feature vector for one decision: the current channels, or the recurrent map run over the
    ordered channel history (every earlier decision point of this run plus the current one)."""
    if policy["feature_source"] == "channels":
        return progress.as_vector(channels)
    events = [progress.as_vector(c) for c in history] + [progress.as_vector(channels)]
    return recurrent.extract(policy["recurrent_config"], events)["features"]


def score(policy: dict, vector: list) -> float:
    readout = policy["readout"]
    if readout is None:
        return 1.0
    weights = [w / 1e6 for w in readout["weights_micro"]]
    if len(weights) != len(vector):
        raise GabrielError(Code.STALE_EVIDENCE, "readout dimension %d does not match the feature vector %d" % (len(weights), len(vector)))
    z = readout["bias_micro"] / 1e6 + sum(w * v for w, v in zip(weights, vector))
    return 1.0 / (1.0 + math.exp(-max(-60.0, min(60.0, z))))


def decide(policy: dict, channels: dict, history: list) -> dict:
    """Decision record: action, score and the exact inputs it was computed from."""
    if policy["kind"] == "rule_based":
        return {"action": "repair", "score_milli": 1000, "policy_id": policy["policy_id"], "feature_source": policy["feature_source"],
                "channels": channels, "reason": "rule: repair within the admitted limits"}
    vector = feature_vector(policy, channels, history)
    p = score(policy, vector)
    action = "repair" if p * 1000 >= policy["threshold_milli"] else "stop"
    return {"action": action, "score_milli": int(round(p * 1000)), "policy_id": policy["policy_id"], "feature_source": policy["feature_source"],
            "channels": channels, "features_milli": [int(round(v * 1000)) for v in vector],
            "reason": "readout p(repair succeeds)=%.3f %s threshold %.3f" % (p, ">=" if action == "repair" else "<", policy["threshold_milli"] / 1000.0)}


# ------------------------------------------------------------------ training (explicit task outcomes)

def train_logistic(samples: list, *, l2: float = 0.01, iterations: int = 400, rate: float = 0.5) -> dict:
    """Deterministic batch gradient descent on log-loss. samples: [(vector, label in {0,1})]."""
    if not samples:
        raise GabrielError(Code.INVALID_SCHEMA, "no training samples")
    dim = len(samples[0][0])
    if any(len(v) != dim for v, _ in samples):
        raise GabrielError(Code.INVALID_SCHEMA, "inconsistent feature dimensions")
    weights, bias = [0.0] * dim, 0.0
    n = len(samples)
    for _ in range(iterations):
        grad_w, grad_b = [l2 * w for w in weights], 0.0
        for vector, label in samples:
            z = bias + sum(w * v for w, v in zip(weights, vector))
            p = 1.0 / (1.0 + math.exp(-max(-60.0, min(60.0, z))))
            err = p - label
            for k in range(dim):
                grad_w[k] += err * vector[k] / n
            grad_b += err / n
        weights = [w - rate * g for w, g in zip(weights, grad_w)]
        bias -= rate * grad_b
    return {"weights": weights, "bias": bias, "samples": n, "positives": sum(l for _, l in samples)}


def log_loss(policy_or_weights, samples: list) -> dict:
    """Decision loss of a readout (or of the rule, which always repairs) on labeled samples."""
    total, correct = 0.0, 0
    for vector, label in samples:
        if isinstance(policy_or_weights, dict) and policy_or_weights.get("kind") == "rule_based":
            p = 0.999
        elif isinstance(policy_or_weights, dict) and "readout" in policy_or_weights:
            p = score(policy_or_weights, vector)
        else:
            w, b = policy_or_weights
            z = b + sum(wi * v for wi, v in zip(w, vector))
            p = 1.0 / (1.0 + math.exp(-max(-60.0, min(60.0, z))))
        p = min(max(p, 1e-6), 1 - 1e-6)
        total += -(label * math.log(p) + (1 - label) * math.log(1 - p))
        correct += int((p >= 0.5) == bool(label))
    n = max(1, len(samples))
    return {"log_loss": total / n, "accuracy": correct / n, "samples": len(samples)}
