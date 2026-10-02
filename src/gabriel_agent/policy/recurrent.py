"""Reference recurrent feature map (``recurrent.features/1``).

The recovered model's synchronous update, written from the blueprint's equations and kept as
the mathematical object it is: a sparse bounded dynamical feature map, distinct from a language
model and from the graph engine. For activity x_i with parents P_i (size d), trace channel l
and input u:

    w_ij(t)   = b_ij + (1/d) * sum_l g_l * S_theta_l(c_lij(t))
    x_i(t+1)  = (1 - alpha_i) x_i(t) + alpha_i tanh( sum_{j in P_i} w_ij(t) x_j(t) + (U u(t))_i + beta_i )
    c_lij(t+1)= (1 - rho_l) c_lij(t) + rho_l x_i(t) x_j(t)

with S_theta(c) = sign(c) max(|c| - theta, 0); every right-hand side uses old state. With
0 < alpha_i, rho_l <= 1 and initial activities/traces in [-1, 1] both stay in that interval. The
trace-only profile sets every g_l to zero and keeps the trace features.

Contract: configuration digest, seed, numerical environment, channel-schema identity, ordered
event inputs and the requested feature schema are bound to the output; configuration mismatch,
missing sequence elements and nonfinite inputs reject. The default extraction runs the reference
sequence from the known initial state (zeros); persistent snapshots are not implemented.
This is a routing-feature experiment, not a claim about stability of the agent loop.
"""
from __future__ import annotations

import hashlib
import math
import platform
import random

from ..contracts.codec import canonical
from ..contracts.errors import Code, GabrielError

CAPABILITY = "recurrent.features/1"
FEATURE_SCHEMA = "recurrent-features-v1"


def default_config(*, units: int = 16, parents: int = 4, channels: int = 24, seed: int = 20261002, profile: str = "adaptive") -> dict:
    """Integer milli-unit parameters so the configuration is an exact record."""
    return {"schema": "gabriel.recurrent-config/1", "units": units, "parents": parents, "channels": channels, "seed": seed,
            "profile": profile, "alpha_milli": 300, "beta_milli": 0, "bias_scale_milli": 400, "input_scale_milli": 800,
            "trace": [{"g_milli": 0 if profile == "trace_only" else 100, "theta_milli": 200, "rho_milli": 100}],
            "float_model": "ieee754-binary64"}


def config_digest(config: dict) -> str:
    return hashlib.sha256(canonical(config)).hexdigest()


def _topology(config: dict):
    rng = random.Random(config["seed"])
    n, d, m = config["units"], config["parents"], config["channels"]
    parents, bias, inputs = [], [], []
    scale = config["bias_scale_milli"] / 1000.0
    for i in range(n):
        choices = [j for j in range(n) if j != i]
        rng.shuffle(choices)
        parents.append(sorted(choices[:d]))
        bias.append([rng.uniform(-scale, scale) / d for _ in range(d)])
        inputs.append([rng.uniform(-1.0, 1.0) * config["input_scale_milli"] / 1000.0 / max(1, m) for _ in range(m)])
    return parents, bias, inputs


def _soft(c: float, theta: float) -> float:
    magnitude = abs(c) - theta
    return 0.0 if magnitude <= 0 else math.copysign(magnitude, c)


def step(config: dict, state: dict, u: list) -> dict:
    """One synchronous update; all right-hand sides read the old state."""
    parents, bias, inputs = state["_topology"]
    n, d = config["units"], config["parents"]
    alpha, beta = config["alpha_milli"] / 1000.0, config["beta_milli"] / 1000.0
    x, traces = state["x"], state["c"]
    new_x = []
    for i in range(n):
        total = 0.0
        for k, j in enumerate(parents[i]):
            w = bias[i][k]
            for l, channel in enumerate(config["trace"]):
                w += (channel["g_milli"] / 1000.0) * _soft(traces[l][i][k], channel["theta_milli"] / 1000.0) / d
            total += w * x[j]
        total += sum(inputs[i][m] * u[m] for m in range(len(u)))
        new_x.append((1.0 - alpha) * x[i] + alpha * math.tanh(total + beta))
    new_traces = []
    for l, channel in enumerate(config["trace"]):
        rho = channel["rho_milli"] / 1000.0
        new_traces.append([[(1.0 - rho) * traces[l][i][k] + rho * x[i] * x[j] for k, j in enumerate(parents[i])] for i in range(n)])
    return {"x": new_x, "c": new_traces, "_topology": state["_topology"], "steps": state["steps"] + 1}


def initial_state(config: dict) -> dict:
    n, d = config["units"], config["parents"]
    return {"x": [0.0] * n, "c": [[[0.0] * d for _ in range(n)] for _ in config["trace"]], "_topology": _topology(config), "steps": 0}


def contraction_load(config: dict) -> dict:
    """The source's sufficient contraction condition q + 2 sum_l g_l < 1 (a diagnostic, not a rejection)."""
    parents, bias, _ = _topology(config)
    g = [c["g_milli"] / 1000.0 for c in config["trace"]]
    theta = [c["theta_milli"] / 1000.0 for c in config["trace"]]
    q = max(sum(abs(b) for b in row) for row in bias) + sum(gl * (1 - th) for gl, th in zip(g, theta))
    return {"q": q, "load": q + 2 * sum(g), "holds": q + 2 * sum(g) < 1}


def extract(config: dict, events: list, *, expected_config_digest: str | None = None, channel_schema_id: str = "progress-channels-v1") -> dict:
    """Run the reference sequence from the initial state over ordered channel vectors."""
    digest = config_digest(config)
    if expected_config_digest is not None and expected_config_digest != digest:
        raise GabrielError(Code.STALE_EVIDENCE, "recurrent configuration digest mismatch")
    if not isinstance(events, list):
        raise GabrielError(Code.INVALID_SCHEMA, "events must be an ordered list of channel vectors")
    state = initial_state(config)
    for index, u in enumerate(events):
        if u is None or not isinstance(u, list) or len(u) != config["channels"]:
            raise GabrielError(Code.INVALID_SCHEMA, "missing or mis-sized sequence element at %d" % index)
        if any((not isinstance(v, (int, float))) or isinstance(v, bool) or not math.isfinite(float(v)) for v in u):
            raise GabrielError(Code.INVALID_SCHEMA, "nonfinite or non-numeric input at %d" % index)
        state = step(config, state, [float(v) for v in u])
    x = state["x"]
    trace_energy = [sum(abs(v) for row in traces for v in row) / max(1, config["units"] * config["parents"]) for traces in state["c"]]
    features = list(x) + trace_energy + [sum(abs(v) for v in x) / max(1, len(x))]
    return {"schema": "gabriel.recurrent-features/1", "capability": CAPABILITY, "config_digest": digest, "seed": config["seed"],
            "channel_schema_id": channel_schema_id, "feature_schema": FEATURE_SCHEMA, "steps": state["steps"],
            "numerical_environment": {"python": platform.python_version(), "float_model": config["float_model"]},
            "final_state_milli": [int(round(v * 1000)) for v in x], "features_milli": [int(round(v * 1000)) for v in features],
            "features": features, "bounded": all(-1.0 <= v <= 1.0 for v in x)}


def feature_names(config: dict) -> list:
    return ["x%d" % i for i in range(config["units"])] + ["trace_energy_%d" % l for l in range(len(config["trace"]))] + ["mean_abs_x"]
