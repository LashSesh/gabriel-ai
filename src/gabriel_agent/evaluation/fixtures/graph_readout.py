"""Native state readout fixture (ADR-19): the specified readout of the engine over an observation
stream with declared phases and amplitudes, with a standard-library reference that implements
the specification independently of the engine.

The specification (every quantity is a function of the stream and the declared profile only):

* Graph: entities are vertices in first-observation order; every pair of entities co-observed in
  a batch is one directed edge of weight 1 from the smaller to the larger vertex identifier
  (FNV-1a of ``sensor-<entity>``); repeated co-observation keeps the weight at 1
  (``(w + 1) / 2``). Activation: a vertex counts one activation per observation plus one per
  co-observed partner in the batch (a new vertex starts at one with its first observation).
* Embedding per vertex after each batch (all clamped to [0, 1]): ``p`` incident weight sum over
  the maximum incident weight sum, ``rho`` the local clustering coefficient over distinct
  neighbours, ``omega`` activation over the maximum activation, ``chi`` distinct-neighbour
  degree over the maximum degree (at least 1), ``eta`` out-degree over total degree (0.5 for
  an isolated vertex); the out-degree counts the partners with a larger vertex identifier.
* Data helix per batch: ``phi`` the circular mean of the declared phases wrapped to [0, 2pi),
  ``r`` the arithmetic mean of the declared amplitudes.
* Carriers: ``n`` carriers at phases ``pi i / n`` (a half turn: the phase lock below is
  pi-periodic in the carrier phase and every carrier contains its antiphase partner, so a full
  turn would hold each carrier twice) with radius 1; carrier coherence
  ``kappa_c = exp(-lambda * delta_phi) * exp(-mu_r * r^2)`` with ``delta_phi`` the wrapped
  antiphase gap (pi up to rounding). The real mandorla against the data helix is
  ``kappa = kappa_c * (1 + cos(2 (phi_data - phi_carrier))) / 2 * exp(-eta_r (r_data - 1)^2)``.
  With ``adaptive_carrier`` a carrier of maximal kappa is active for the step (the engine takes
  the first strictly larger value in index order; when several carriers lie within 1e-12 of the
  maximum the choice among them is not specified beyond that set); otherwise carrier 0 stays
  active.
* Metrics: ``d`` saturate(max(mean, p90, churn); mu_d) of the relative embedding change over
  vertices present in both steps (0.75 on the first step or when the change is zero or not
  finite); ``q`` kappa / kappa_c clamped to [0, 1]; ``r`` and ``p`` are exp(-lambda_r * 0) and
  exp(-lambda_p * 0) = 1 because the intrinsic state stays at the origin without commits;
  ``g = gamma_d d + gamma_q q + gamma_r r``; ``j`` saturate(edges / vertices; mu_j);
  ``n = exp(-lambda_seam * delta_phi)``; ``k = lambda_c q + lambda_e max(0, 1 - delta_phi/pi)``.
  The gate passes (``kairos``) when every metric is at least its declared threshold.
* Detections: with a schedule ``{min_tick, cooldown}``, a detection is a step whose gate passes,
  whose tick is at least ``min_tick`` and which lies more than ``cooldown`` ticks after the
  previous detection. A detection's identity covers the readout identity, the tick, the
  vertices, the metric bits, the thresholds and the schedule.

Under this profile ``r``, ``p`` and ``n`` are constants and ``k`` is ``lambda_c q``: of the
inherited eight gates, three quantities vary (``d``, ``q``, ``j``). That is a finding of the
specification, stated here rather than hidden behind the gate's eight names.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import struct
import subprocess
from pathlib import Path

TAU = 2.0 * math.pi
NORMALIZATION = {"mu_d": 0.2, "mu_j": 1.0, "lambda_r": 1.0, "lambda_p": 1.0, "lambda_seam": 0.1, "gamma_d": 0.33, "gamma_q": 0.33, "gamma_r": 0.34,
                 "lambda_c": 1.0, "lambda_e": 0.0}
THRESHOLDS = {"d": 0.5, "q": 0.5, "r": 0.5, "g": 0.5, "j": 0.5, "p": 0.5, "n": 0.5, "k": 0.5}
STREAM = [[(0, 0.0, 0.5), (1, 0.7, 0.6), (2, 1.4, 0.7)], [(2, 1.4, 0.7), (3, 2.1, 0.8)], [(0, 0.0, 0.5), (3, 2.1, 0.8)],
          [(0, 0.0, 0.5), (1, 0.7, 0.6), (2, 1.4, 0.7), (3, 2.1, 0.8)]]
SCHEDULE = {"min_tick": 1, "cooldown": 1}
OUTPUTS = {"graph.state_readout": "out/readout.json", "graph.detections": "out/detections.json"}
INPUTS = {"graph.state_readout": "data/stream.json", "graph.detections": "data/detection_query.json"}
GOALS = {"graph.state_readout": "Run the native engine's specified state readout over the declared observation stream in data/stream.json "
                                "(embedding, data helix, active carrier, gate metrics and gate verdict per step) and write it to out/readout.json.",
         "graph.detections": "Compute the detections of the declared observation stream in data/detection_query.json under its thresholds and "
                             "schedule (gate crossings admitted by the schedule) and write them to out/detections.json."}


def bits(value: float) -> str:
    return struct.pack(">d", float(value)).hex()


def number(value: str) -> float:
    return struct.unpack(">d", bytes.fromhex(value))[0]


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf8")).hexdigest()


# ------------------------------------------------------------------ datasets

def profile(carriers: int = 4, adaptive_carrier: bool = True, lam: float = 0.1, mu_r: float = 0.3, eta_r: float = 1.0, dt2: float = 0.01,
            normalization: dict | None = None, thresholds: dict | None = None) -> dict:
    return {"carriers": carriers, "adaptive_carrier": adaptive_carrier, "lambda_bits": bits(lam), "mu_r_bits": bits(mu_r), "eta_r_bits": bits(eta_r),
            "dt2_bits": bits(dt2), "normalization": {k: bits(v) for k, v in (normalization or NORMALIZATION).items()},
            "thresholds": {k: bits(v) for k, v in (thresholds or THRESHOLDS).items()}}


def stream_batches(stream=STREAM) -> list:
    return [[{"entity": e, "phase_bits": bits(phi), "amplitude_bits": bits(r)} for e, phi, r in batch] for batch in stream]


def stream_dataset(stream=STREAM, prof: dict | None = None) -> dict:
    return {"kind": "observation_stream", "batches": stream_batches(stream), "profile": prof or profile()}


def detection_dataset(stream=STREAM, prof: dict | None = None, schedule: dict | None = None) -> dict:
    return {"kind": "detection_query", "batches": stream_batches(stream), "profile": prof or profile(), "schedule": dict(schedule or SCHEDULE)}


def text(dataset: dict) -> str:
    return json.dumps(dataset, indent=1) + "\n"


def decoded_profile(prof: dict) -> dict:
    return {"carriers": prof["carriers"], "adaptive_carrier": prof["adaptive_carrier"], "lambda": number(prof["lambda_bits"]), "mu_r": number(prof["mu_r_bits"]),
            "eta_r": number(prof["eta_r_bits"]), "dt2": number(prof["dt2_bits"]), "normalization": {k: number(v) for k, v in prof["normalization"].items()},
            "thresholds": {k: number(v) for k, v in prof["thresholds"].items()}}


def decoded_stream(batches: list) -> list:
    return [[(o["entity"], number(o["phase_bits"]), number(o["amplitude_bits"])) for o in batch] for batch in batches]


# ------------------------------------------------------------------ reference implementation (standard library only)

def sensor_vertex_id(entity: int) -> int:
    value = 0xcbf29ce484222325
    for byte in ("sensor-%d" % entity).encode("ascii"):
        value = ((value ^ byte) * 0x100000001b3) & ((1 << 64) - 1)
    return value


def saturate(u: float, mu: float) -> float:
    return u / (u + mu)


def wrapped_antiphase_gap(phi: float) -> float:
    beta = math.fmod(phi + math.pi, TAU)
    raw = abs(phi - beta)
    return min(raw, TAU - raw)


def carrier_kappa(phi: float, data_phi: float, data_r: float, lam: float, mu_r: float, eta_r: float) -> tuple:
    """(kappa_carrier, kappa_real, delta_phi) for a carrier of radius 1 at phase phi."""
    delta_phi = wrapped_antiphase_gap(phi)
    kappa = math.exp(-lam * delta_phi) * math.exp(-mu_r * 1.0 * 1.0)
    phase_lock = 0.5 * (1.0 + math.cos(2.0 * (data_phi - phi)))
    amp_match = math.exp(-eta_r * (data_r - 1.0) ** 2)
    return kappa, kappa * (phase_lock * amp_match), delta_phi


NEAR_MAXIMAL = 1e-12


def reference_readout(stream: list, prof: dict, carrier_choices: list | None = None) -> list:
    """Per-step readout of the specification above. ``stream``: batches of (entity, phase, amplitude)
    floats; ``prof``: decoded profile. ``carrier_choices``: an engine's active-carrier indices per
    step, accepted only when they lie in the near-maximal set of that step (the reference then
    continues with that choice, so the comparison is exact up to rounding); without them the first
    near-maximal index is taken. Returns one dict per step with float values; each step carries the
    near-maximal set under ``admissible_carriers``."""
    norm, thresholds = prof["normalization"], prof["thresholds"]
    carriers = [math.pi * i / prof["carriers"] for i in range(prof["carriers"])]
    order, ids = [], {}
    activation, edges = {}, {}   # entity -> count; (from_id, to_id) -> weight, from < to by vertex id
    prev_embedding = {}
    active = 0
    steps = []
    for tick, batch in enumerate(stream, start=1):
        # data helix
        n = len(batch)
        sum_sin = sum_cos = sum_r = 0.0
        for entity, phi, amplitude in batch:
            phase = math.fmod(phi, TAU) if phi >= 0 else math.fmod(phi, TAU) + TAU
            sum_sin += math.sin(phase)
            sum_cos += math.cos(phase)
            sum_r += min(max(amplitude, 0.0), 1.0)
        data_phi = math.atan2(sum_sin / n, sum_cos / n)
        if data_phi < 0.0:
            data_phi += TAU
        data_r = sum_r / n
        # adaptive carrier selection: a carrier of maximal kappa (near-maximal set within rounding)
        admissible = [active]
        if prof["adaptive_carrier"]:
            kappas = [carrier_kappa(phi, data_phi, data_r, prof["lambda"], prof["mu_r"], prof["eta_r"])[1] for phi in carriers]
            top = max(kappas)
            admissible = [index for index, kappa in enumerate(kappas) if kappa >= top - NEAR_MAXIMAL]
            active = admissible[0]
        if carrier_choices is not None:
            chosen = carrier_choices[tick - 1]
            if chosen not in admissible:
                raise ValueError("carrier %d at tick %d is not near-maximal (admissible: %s)" % (chosen, tick, admissible))
            active = chosen
        # graph update
        for entity, _, _ in batch:
            if entity not in ids:
                ids[entity] = sensor_vertex_id(entity)
                order.append(entity)
                activation[entity] = 1
            else:
                activation[entity] += 1
        batch_ids = sorted(ids[e] for e, _, _ in batch)
        for i in range(len(batch_ids)):
            for j in range(i + 1, len(batch_ids)):
                key = (batch_ids[i], batch_ids[j])
                edges[key] = 1.0 if key not in edges else (edges[key] + 1.0) * 0.5
                for vid in key:
                    entity = next(e for e, v in ids.items() if v == vid)
                    activation[entity] += 1
        # embedding
        neighbours = {e: set() for e in order}
        incident = {e: 0.0 for e in order}
        out_degree = {e: 0 for e in order}
        by_id = {v: e for e, v in ids.items()}
        for (a, b), weight in edges.items():
            ea, eb = by_id[a], by_id[b]
            neighbours[ea].add(eb)
            neighbours[eb].add(ea)
            incident[ea] += weight
            incident[eb] += weight
            out_degree[ea] += 1
        max_degree = max(1.0, max(float(len(neighbours[e])) for e in order))
        max_activation = max(1, max(activation[e] for e in order))
        max_incident = max(1e-9, max(incident[e] for e in order))
        embedding = {}
        for e in order:
            nb = sorted(neighbours[e])
            k = len(nb)
            if k < 2:
                rho = 0.0
            else:
                connected = 0.0
                for i in range(k):
                    for j in range(i + 1, k):
                        if nb[j] in neighbours[nb[i]]:
                            connected += 1.0
                rho = connected / float(k * (k - 1) // 2)
            degree = float(k)
            out_deg, in_deg = float(out_degree[e]), degree - out_degree[e]
            eta = 0.5 if out_deg + in_deg < 1e-12 else out_deg / (out_deg + in_deg)
            clamp = lambda x: min(max(x, 0.0), 1.0)
            embedding[e] = [clamp(incident[e] / max_incident), clamp(rho), clamp(activation[e] / max_activation), clamp(degree / max_degree), clamp(eta)]
        # d: deformation
        if not prev_embedding:
            d_raw = 0.75
        else:
            diffs = []
            for e in order:
                curr = embedding[e]
                curr_norm = math.sqrt(sum(x * x for x in curr))
                if curr_norm < 1e-9 or e not in prev_embedding:
                    continue
                prev = prev_embedding[e]
                if math.sqrt(sum(x * x for x in prev)) < 1e-9:
                    continue
                diff = math.sqrt(sum((c - p) ** 2 for c, p in zip(curr, prev)))
                diffs.append(diff / (curr_norm + 1e-9))
            mean = sum(diffs) / len(diffs) if diffs else 0.0
            if diffs:
                diffs.sort()
                index = min(max(math.ceil(len(diffs) * 0.90) - 1, 0), len(diffs) - 1)
                p90 = diffs[index]
            else:
                p90 = 0.0
            n_curr, n_prev = len(order), len(prev_embedding)
            intersect = sum(1 for e in order if e in prev_embedding)
            denominator = max(n_curr, n_prev)
            churn = 1.0 - intersect / denominator if denominator > 0 else 0.0
            candidate = max(mean, p90, churn)
            d_raw = candidate if math.isfinite(candidate) and candidate > 0.0 else 0.75
        prev_embedding = {e: list(v) for e, v in embedding.items()}
        d = saturate(d_raw, norm["mu_d"])
        # carrier mandorla and the remaining metrics
        kappa_c, kappa_real, delta_phi = carrier_kappa(carriers[active], data_phi, data_r, prof["lambda"], prof["mu_r"], prof["eta_r"])
        kappa_max = math.exp(-prof["lambda"] * math.pi) * math.exp(-prof["mu_r"] * 1.0 * 1.0)
        q = min(max(kappa_real / kappa_max, 0.0), 1.0) if kappa_max > 1e-9 else 0.0
        r = math.exp(-norm["lambda_r"] * 0.0)
        g = norm["gamma_d"] * d + norm["gamma_q"] * q + norm["gamma_r"] * r
        j = saturate(len(edges) / len(order) if order else 0.0, norm["mu_j"])
        p = math.exp(-norm["lambda_p"] * 0.0)
        n_seam = math.exp(-norm["lambda_seam"] * delta_phi)
        k = norm["lambda_c"] * q + norm["lambda_e"] * max(1.0 - delta_phi / math.pi, 0.0)
        metrics = {"d": d, "q": q, "r": r, "g": g, "j": j, "p": p, "n": n_seam, "k": k}
        steps.append({"tick": tick, "vertices": list(order), "edges": len(edges), "helix": {"phi": data_phi, "r": data_r},
                      "carrier": {"index": active, "phi": carriers[active], "kappa": kappa_real, "delta_phi": delta_phi},
                      "metrics": metrics, "kairos": all(metrics[name] >= thresholds[name] for name in metrics),
                      "embedding": [embedding[e] for e in order], "admissible_carriers": admissible})
    return steps


def reference_detection_ticks(steps: list, schedule: dict) -> list:
    ticks, last = [], None
    for step in steps:
        if not step["kairos"] or step["tick"] < schedule["min_tick"]:
            continue
        if last is not None and step["tick"] <= last + schedule["cooldown"]:
            continue
        ticks.append(step["tick"])
        last = step["tick"]
    return ticks


def decode_readout(output: dict) -> list:
    """The engine's bit-string readout as floats, in the reference's shape."""
    steps = []
    for item in output["ticks"]:
        steps.append({"tick": item["tick"], "vertices": item["vertices"], "edges": item["edges"],
                      "helix": {"phi": number(item["helix"]["phi_bits"]), "r": number(item["helix"]["r_bits"])},
                      "carrier": {"index": item["carrier"]["index"], "phi": number(item["carrier"]["phi_bits"]), "kappa": number(item["carrier"]["kappa_bits"]),
                                  "delta_phi": number(item["carrier"]["delta_phi_bits"])},
                      "metrics": {name: number(value) for name, value in item["metrics"].items()}, "kairos": item["kairos"],
                      "embedding": [[number(x) for x in row] for row in item["embedding"]]})
    return steps


def compare_readout(engine_steps: list, stream: list, prof: dict) -> float:
    """Largest absolute difference between an engine readout and the reference computed under the
    engine's admissible carrier choices; raises when the structure (steps, vertices, edges,
    carrier admissibility, gate verdicts) differs."""
    choices = [step["carrier"]["index"] for step in engine_steps]
    if len(choices) != len(stream):
        raise ValueError("step count differs")
    return max_deviation(engine_steps, reference_readout(stream, prof, carrier_choices=choices))


def max_deviation(engine_steps: list, reference_steps: list) -> float:
    """Largest absolute difference over every real quantity; structure must match exactly."""
    if len(engine_steps) != len(reference_steps):
        raise ValueError("step count differs")
    worst = 0.0
    for a, b in zip(engine_steps, reference_steps):
        if (a["tick"], a["vertices"], a["edges"], a["carrier"]["index"], a["kairos"]) != (b["tick"], b["vertices"], b["edges"], b["carrier"]["index"], b["kairos"]):
            raise ValueError("structure differs at tick %d: %r / %r" % (a["tick"], (a["vertices"], a["edges"], a["carrier"]["index"], a["kairos"]),
                                                                       (b["vertices"], b["edges"], b["carrier"]["index"], b["kairos"])))
        for key in ("phi", "r"):
            worst = max(worst, abs(a["helix"][key] - b["helix"][key]))
        for key in ("phi", "kappa", "delta_phi"):
            worst = max(worst, abs(a["carrier"][key] - b["carrier"][key]))
        for name in a["metrics"]:
            worst = max(worst, abs(a["metrics"][name] - b["metrics"][name]))
        for row_a, row_b in zip(a["embedding"], b["embedding"]):
            worst = max(worst, max(abs(x - y) for x, y in zip(row_a, row_b)))
    return worst


# ------------------------------------------------------------------ repository, oracles, task specs and scripted worker

def no_detection_schedule() -> dict:
    return {"min_tick": 100, "cooldown": 0}


TEXTS = {"data/stream.json": text(stream_dataset()), "data/detection_query.json": text(detection_dataset()),
         "data/detection_query_none.json": text(detection_dataset(schedule=no_detection_schedule())),
         "data/stream_bad.json": text(stream_dataset(prof=profile(carriers=0)))}


def build_repo(path: Path) -> str:
    path = Path(path)
    (path / "data").mkdir(parents=True)
    for relative, content in TEXTS.items():
        (path / relative).write_text(content)
    (path / "README.md").write_text("# Declared observation streams\n\nEach observation declares its entity, phase in [0, 2pi) and amplitude in [0, 1] as binary64 bits; "
                                    "the profile declares carriers, coherence parameters, normalization and thresholds.\n")
    env = dict(os.environ, GIT_AUTHOR_NAME="fixture", GIT_AUTHOR_EMAIL="fixture@invalid", GIT_COMMITTER_NAME="fixture", GIT_COMMITTER_EMAIL="fixture@invalid")
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True, env=env)
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True, env=env)
    subprocess.run(["git", "-C", str(path), "commit", "-q", "-m", "seed observation streams"], check=True, env=env)
    return subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()


def readout_oracle(stream=STREAM, prof: dict | None = None, output_path: str = OUTPUTS["graph.state_readout"]) -> dict:
    prof = prof or profile()
    steps = reference_readout(stream, decoded_profile(prof))
    return {"operation": "graph.state_readout", "output_path": output_path, "units": None, "tolerance_micro": 1,
            "readout": [{"tick": s["tick"], "vertices": s["vertices"], "edges": s["edges"], "admissible_carriers": s["admissible_carriers"], "kairos": s["kairos"],
                         "metrics": s["metrics"]} for s in steps]}


def detections_oracle(stream=STREAM, prof: dict | None = None, schedule: dict | None = None, output_path: str = OUTPUTS["graph.detections"]) -> dict:
    prof = prof or profile()
    schedule = dict(schedule or SCHEDULE)
    steps = reference_readout(stream, decoded_profile(prof))
    ticks = reference_detection_ticks(steps, schedule)
    return {"operation": "graph.detections", "output_path": output_path, "units": None, "detection_ticks": ticks,
            "detection_vertices": [steps[t - 1]["vertices"] for t in ticks]}


def write_oracle(path: Path, operation: str = "graph.state_readout", **over) -> Path:
    path = Path(path)
    oracle = readout_oracle(**over) if operation == "graph.state_readout" else detections_oracle(**over)
    path.write_text(json.dumps(oracle, indent=1) + "\n")
    return path


def task_spec(repo: Path, base_commit: str, oracle_path: Path, provider: dict, operation: str = "graph.state_readout", **over) -> dict:
    spec = {"domain": "numerical", "goal": GOALS[operation], "repository": str(repo), "base_commit": base_commit, "allowed_paths": ["out/"],
            "checks": [{"check_id": "reference", "kind": "numerical/reference_contract", "independent": True, "role": "acceptance_only",
                        "oracle_files": [{"path": "oracle/expected.json", "source": str(oracle_path)}]}],
            "provider": provider, "budget": {"model_tokens_total": 200000, "model_requests": 12}}
    spec.update(over)
    return spec


def _job(operation, input_path, output_path, parameters=None, rationale="run the declared native readout"):
    return {"kind": "text", "value": {"operation": operation, "input_path": input_path, "expected_sha256": sha(TEXTS[input_path]),
                                      "output_path": output_path, "parameters": parameters or {}, "rationale": rationale}}


def script(variant: str = "graph.state_readout") -> dict:
    planner = [{"kind": "echo_reference"}]
    if variant in OUTPUTS:
        worker = [_job(variant, INPUTS[variant], OUTPUTS[variant])]
    elif variant == "detections_none":
        worker = [_job("graph.detections", "data/detection_query_none.json", OUTPUTS["graph.detections"], rationale="a schedule that admits nothing")]
    elif variant == "bad_profile":
        worker = [_job("graph.state_readout", "data/stream_bad.json", OUTPUTS["graph.state_readout"], rationale="a profile without carriers")]
    elif variant == "wrong_input_kind":
        worker = [_job("graph.detections", "data/stream.json", OUTPUTS["graph.detections"], rationale="detections without a schedule")]
    else:
        raise ValueError("unknown variant " + variant)
    return {"by_step": {"plan-request": planner, "propose": worker}, "by_role": {"planner": planner, "worker": worker}}
