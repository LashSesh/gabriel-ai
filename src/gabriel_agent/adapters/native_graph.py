"""Native PSE graph worker (blueprint: native PSE and analytical worker contracts; ADR-18).

Exposes specific, bounded operations of the inherited Rust engine through the same worker
protocol as the standard-library analytical adapter:

* ``graph.snapshot``: the engine's conditioned graph snapshot after an ordered batch history
  (identity, vertices, walk backend, model string, engine statistics).
* ``graph.region_mass``: the normalized source-conditioned continuous-time walk
  ``exp(-itL)``, ``L = D - A`` on the symmetrized adjacency, read out as regional mass at
  declared times with the declared threshold and deadband decision rule
  (``above`` / ``below`` / ``ambiguous``). A mass is a model readout, not a probability.
* ``graph.window_reachability``: the exact closed-window certificate of
  ``exists t in [start, end]: mass(t) > threshold`` over the represented binary64 Laplacian,
  with verdicts ``reachable``, ``excluded``, ``unknown`` and ``out_of_scope``; the arithmetic
  runs in a dedicated host process (python-flint/Arb), the native snapshot in the contained
  worker.

The native executables (``engine_observer``, ``engine_snapshot``: Cargo examples of
``native_pse``) are trusted local code bound by their SHA-256; the reviewed profile disables
decay and crystal commits, so no crystal, resonance or "learning" claim is attached to any
result. Every job binds the complete input bytes, operation, parameters, this file, the
executable digests and the numerical environment. Inputs outside the declared bounds yield
``invalid_input`` or ``out_of_scope``; an exhausted certificate ladder yields ``unknown``.
None of them is a success.

This file is also the worker installed into the worktree and run by ``python3`` inside the
containment backend, so it depends on the standard library only.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import struct
import subprocess
import sys
import time
from pathlib import Path

PROFILE_ID = "native-pse-graph-v1"
OBSERVER_SCHEMA = "gabriel-engine-observer/v1"
SNAPSHOT_SCHEMA = "gabriel-engine-snapshot/v1"
MODEL = "exp(-itL);L=D-A;(W+W^T)/2;inactive-included;selfloops-ignored"
BACKENDS = ("spectral_full", "auto_full", "auto_region")
CAPS = {"max_nodes": 64, "max_batches": 128, "max_queries": 256, "max_windows": 32}
MAX_WIRE_BYTES = 4 * 1024 * 1024
MAX_INPUT_BYTES = 1 << 20
TIMEOUT_SECONDS = 30
BINARIES = ("engine_observer", "engine_snapshot", "engine_readout")
LAST_TIMINGS = {}  # of the most recent invoke(): diagnostics only, never part of an output or key
KINDS = ("observation_batches", "graph_query", "graph_window_query", "observation_stream", "detection_query")
READOUT_SCHEMA = "gabriel-engine-readout/v1"
READOUT_MODEL = "half-turn-carriers;no-decay;no-commit;embedding(p,rho,omega,chi,eta);helix(circular-mean,mean-amplitude);gate(d,q,r,g,j,p,n,k)"
ARITHMETIC = "pure-rust-libm"
MAX_CARRIERS = 64
MAX_SCHEDULE = 128
PROFILE_FIELDS = "carriers adaptive_carrier lambda_bits mu_r_bits eta_r_bits dt2_bits normalization thresholds"
NORMALIZATION_FIELDS = "mu_d mu_j lambda_r lambda_p lambda_seam gamma_d gamma_q gamma_r lambda_c lambda_e"
METRICS = "dqrgjpnk"
TAU = 2.0 * math.pi

OPERATIONS = {
    "graph.snapshot": {"input_kind": "observation_batches", "parameters": {}, "required": [],
                       "description": "conditioned graph snapshot of the ordered batch history (identity, vertices, walk backend, engine statistics); no crystal, no decay",
                       "output_units": None, "binary": "engine_observer", "certificate": False},
    "graph.region_mass": {"input_kind": "graph_query", "parameters": {}, "required": [],
                          "description": "normalized source-conditioned walk exp(-itL) read out as regional mass at the declared times with the declared threshold and deadband rule",
                          "output_units": None, "binary": "engine_observer", "certificate": False},
    "graph.window_reachability": {"input_kind": "graph_window_query", "parameters": {}, "required": [],
                                  "description": "exact closed-window certificate of exists t in [start,end]: mass(t) > threshold over the represented Laplacian; verdicts reachable, excluded, unknown, out_of_scope",
                                  "output_units": None, "binary": "engine_snapshot", "certificate": True},
    "graph.state_readout": {"input_kind": "observation_stream", "parameters": {}, "required": [],
                            "description": "specified state readout of the engine over a declared observation stream (embedding, data helix, active carrier, gate metrics d,q,r,g,j,p,n,k and gate verdict per step); no decay, no commit",
                            "output_units": None, "binary": "engine_readout", "certificate": False},
    "graph.detections": {"input_kind": "detection_query", "parameters": {}, "required": [],
                         "description": "gate crossings of the specified readout admitted by the declared schedule (min_tick, cooldown), each with an identity over its complete content; an empty list is a computed result",
                         "output_units": None, "binary": "engine_readout", "certificate": False},
}


# ===================================================================== binary64 bit strings (exact wire encoding)

def bits(value: float) -> str:
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("nonfinite binary64 quantity")
    return struct.pack(">d", value).hex()


def number(value) -> float:
    if type(value) is not str or len(value) != 16 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("binary64 requires sixteen lowercase hexadecimal bit digits")
    result = struct.unpack(">d", bytes.fromhex(value))[0]
    if not math.isfinite(result):
        raise ValueError("nonfinite binary64 quantity")
    return result


def canonical(value) -> bytes:
    """Compact, sorted-key, ASCII JSON: what the native bridges require on stdin."""
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return text.encode("ascii")


def dumps(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("ascii") + b"\n"


# ===================================================================== dataset description (no computation)

def _integer(value, minimum, maximum):
    if type(value) is not int or isinstance(value, bool) or not minimum <= value <= maximum:
        raise ValueError("integer outside declared bounds")
    return value


def _entities(value, maximum, nonempty=False):
    if type(value) is not list or not int(nonempty) <= len(value) <= maximum:
        raise ValueError("entity list outside declared bounds")
    for entity in value:
        _integer(entity, 0, CAPS["max_nodes"] - 1)
    if len(set(value)) != len(value):
        raise ValueError("duplicate entity")
    return set(value)


def _batches(value) -> set:
    if type(value) is not list or not 1 <= len(value) <= CAPS["max_batches"]:
        raise ValueError("batch history outside bounds (1..%d batches)" % CAPS["max_batches"])
    entities = set()
    for batch in value:
        entities |= _entities(batch, CAPS["max_nodes"], nonempty=True)
    if len(entities) > CAPS["max_nodes"]:
        raise ValueError("total entity capacity exceeded")
    return entities


def _source(value, entities: set) -> None:
    if type(value) is not list or len(value) != len(entities):
        raise ValueError("source must cover every entity exactly once")
    seen, nonzero = set(), False
    for entry in value:
        if type(entry) is not dict or set(entry) != {"entity", "re_bits", "im_bits"}:
            raise ValueError("source entry fields must be exactly entity, re_bits, im_bits")
        entity = _integer(entry["entity"], 0, CAPS["max_nodes"] - 1)
        if entity not in entities or entity in seen:
            raise ValueError("duplicate or unknown source entity")
        seen.add(entity)
        re, im = number(entry["re_bits"]), number(entry["im_bits"])
        nonzero = nonzero or re != 0.0 or im != 0.0
    if not nonzero:
        raise ValueError("zero source is not a normalized observation")


def describe(raw: bytes) -> dict:
    """Kind, bounds and problems of a native graph dataset; never computes anything."""
    base = {"format": "json", "kind": "unknown", "units": None, "time_basis": None, "rows": None, "problems": []}
    if len(raw) > MAX_INPUT_BYTES:
        return dict(base, format="unsupported", problems=["input exceeds %d bytes" % MAX_INPUT_BYTES])
    try:
        data = json.loads(raw.decode("utf8"))
    except (ValueError, UnicodeDecodeError) as exc:
        return dict(base, format="unsupported", problems=["not JSON: " + str(exc)[:120]])
    if type(data) is not dict or data.get("kind") not in KINDS:
        return dict(base, problems=["kind is not one of " + ", ".join(KINDS)])
    kind = data["kind"]
    problems = []
    if kind in ("observation_stream", "detection_query"):
        return _describe_stream(data, base)
    try:
        entities = _batches(data.get("batches"))
        backend = data.get("backend", "auto_region")
        if backend not in BACKENDS:
            problems.append("backend must be one of " + ", ".join(BACKENDS))
        if kind in ("graph_query", "graph_window_query"):
            _source(data.get("source"), entities)
            if not _entities(data.get("targets"), CAPS["max_nodes"]) <= entities:
                problems.append("unknown target entity")
            threshold = number(data.get("threshold_bits"))
            if not 0 <= threshold <= 1:
                problems.append("threshold outside [0,1]")
        if kind == "graph_query":
            times = data.get("times_bits")
            if type(times) is not list or not 1 <= len(times) <= CAPS["max_queries"]:
                problems.append("times_bits needs 1..%d entries" % CAPS["max_queries"])
            else:
                for value in times:
                    number(value)
            deadband = number(data.get("deadband_bits"))
            if not 0 <= deadband <= 1:
                problems.append("deadband outside [0,1]")
            expected = {"kind", "batches", "backend", "source", "targets", "times_bits", "threshold_bits", "deadband_bits"}
        elif kind == "graph_window_query":
            windows = data.get("windows")
            if type(windows) is not list or not 1 <= len(windows) <= CAPS["max_windows"]:
                problems.append("windows needs 1..%d entries" % CAPS["max_windows"])
            else:
                for window in windows:
                    if type(window) is not dict or set(window) != {"start_bits", "end_bits"}:
                        raise ValueError("window fields must be exactly start_bits, end_bits")
                    if number(window["start_bits"]) > number(window["end_bits"]):
                        problems.append("reversed closed window")
            expected = {"kind", "batches", "source", "targets", "windows", "threshold_bits"}
        else:
            expected = {"kind", "batches", "backend"}
        extra = set(data) - expected
        if extra:
            problems.append("unknown fields: " + ", ".join(sorted(extra)))
        if kind != "observation_batches" and "backend" in data and kind == "graph_window_query":
            problems.append("a window query declares no backend (the snapshot's walk backend is automatic)")
        rows = len(data["batches"])
    except (ValueError, TypeError, AttributeError) as exc:
        problems.append(str(exc)[:200])
        rows = None
    return dict(base, kind=kind, rows=rows, problems=problems[:16])


def _stream_batches(value) -> tuple:
    """Entities in first-observation order and the distinct co-observed pairs of a declared stream."""
    if type(value) is not list or not 1 <= len(value) <= CAPS["max_batches"]:
        raise ValueError("batch history outside bounds (1..%d batches)" % CAPS["max_batches"])
    order, pairs = [], set()
    for batch in value:
        if type(batch) is not list or not 1 <= len(batch) <= CAPS["max_nodes"]:
            raise ValueError("batch outside bounds (1..%d observations)" % CAPS["max_nodes"])
        seen = []
        for item in batch:
            if type(item) is not dict or set(item) != {"entity", "phase_bits", "amplitude_bits"}:
                raise ValueError("observation fields must be exactly entity, phase_bits, amplitude_bits")
            entity = _integer(item["entity"], 0, CAPS["max_nodes"] - 1)
            if entity in seen:
                raise ValueError("duplicate entity in a batch")
            seen.append(entity)
            if not 0.0 <= number(item["phase_bits"]) < TAU:
                raise ValueError("phase outside [0,2pi)")
            if not 0.0 <= number(item["amplitude_bits"]) <= 1.0:
                raise ValueError("amplitude outside [0,1]")
            if entity not in order:
                order.append(entity)
        for i in range(len(seen)):
            for j in range(i + 1, len(seen)):
                pairs.add((min(seen[i], seen[j]), max(seen[i], seen[j])))
    if len(order) > CAPS["max_nodes"]:
        raise ValueError("total entity capacity exceeded")
    return order, pairs


def _profile(value) -> dict:
    """The declared readout profile, decoded; raises on any deviation from the contract."""
    if type(value) is not dict or set(value) != set(PROFILE_FIELDS.split()):
        raise ValueError("profile fields must be exactly: " + PROFILE_FIELDS)
    carriers = _integer(value["carriers"], 1, MAX_CARRIERS)
    if type(value["adaptive_carrier"]) is not bool:
        raise ValueError("adaptive_carrier must be a boolean")
    decoded = {"carriers": carriers, "adaptive_carrier": value["adaptive_carrier"]}
    for name in ("lambda", "mu_r", "eta_r"):
        decoded[name] = number(value[name + "_bits"])
        if decoded[name] < 0:
            raise ValueError(name + " must be non-negative")
    decoded["dt2"] = number(value["dt2_bits"])
    if decoded["dt2"] <= 0:
        raise ValueError("dt2 must be positive")
    normalization = value["normalization"]
    if type(normalization) is not dict or set(normalization) != set(NORMALIZATION_FIELDS.split()):
        raise ValueError("normalization fields must be exactly: " + NORMALIZATION_FIELDS)
    decoded["normalization"] = {name: number(normalization[name]) for name in NORMALIZATION_FIELDS.split()}
    for name, x in decoded["normalization"].items():
        if (name in ("mu_d", "mu_j") and x <= 0) or x < 0:
            raise ValueError("normalization %s outside its domain" % name)
    thresholds = value["thresholds"]
    if type(thresholds) is not dict or set(thresholds) != set(METRICS):
        raise ValueError("threshold fields must be exactly d, q, r, g, j, p, n, k")
    decoded["thresholds"] = {name: number(thresholds[name]) for name in METRICS}
    if any(not 0.0 <= x <= 1.0 for x in decoded["thresholds"].values()):
        raise ValueError("thresholds outside [0,1]")
    return decoded


def _schedule(value) -> dict:
    if type(value) is not dict or set(value) != {"min_tick", "cooldown"}:
        raise ValueError("schedule fields must be exactly min_tick, cooldown")
    return {"min_tick": _integer(value["min_tick"], 0, MAX_SCHEDULE), "cooldown": _integer(value["cooldown"], 0, MAX_SCHEDULE)}


def _describe_stream(data: dict, base: dict) -> dict:
    kind = data["kind"]
    problems, rows = [], None
    try:
        expected = {"kind", "batches", "profile"} | ({"schedule"} if kind == "detection_query" else set())
        extra = set(data) - expected
        if extra:
            problems.append("unknown fields: " + ", ".join(sorted(extra)))
        _stream_batches(data.get("batches"))
        _profile(data.get("profile"))
        if kind == "detection_query":
            _schedule(data.get("schedule"))
        rows = len(data["batches"])
    except (ValueError, TypeError, AttributeError) as exc:
        problems.append(str(exc)[:200])
    return dict(base, kind=kind, rows=rows, problems=problems[:16])


# ===================================================================== native bridges

def binaries(directory=None) -> dict:
    """The native executables and their digests. Directory: GABRIEL_NATIVE_PSE_DIR, else the
    repository's native_pse/target/release/examples. Missing executables are reported, never
    substituted."""
    if directory is None:
        directory = os.environ.get("GABRIEL_NATIVE_PSE_DIR")
    if directory is None:
        here = Path(__file__).resolve()
        for parent in here.parents:
            candidate = parent / "native_pse" / "target" / "release" / "examples"
            if candidate.is_dir():
                directory = candidate
                break
    found = {}
    if directory is None:
        return found
    for name in BINARIES:
        path = Path(directory) / name
        if path.is_file():
            found[name] = {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size}
    return found


def available() -> bool:
    return set(binaries()) == set(BINARIES)


def _check_executable(path: str, expected_sha256: str) -> None:
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("native executable identity mismatch: " + str(path))


def invoke(executable: str, expected_sha256: str, job: dict) -> dict:
    """Run one fresh native process on compact canonical JSON; identity checked before and after."""
    clock = time.monotonic_ns()
    _check_executable(executable, expected_sha256)
    identity_ns = time.monotonic_ns() - clock
    wire = canonical(job)
    if len(wire) > MAX_WIRE_BYTES:
        raise ValueError("native input byte cap exceeded")
    clock = time.monotonic_ns()
    try:
        process = subprocess.run([os.path.abspath(executable)], input=wire, capture_output=True, timeout=TIMEOUT_SECONDS, check=False)
    except subprocess.TimeoutExpired as exc:
        raise ValueError("native process timeout") from exc
    native_ns = time.monotonic_ns() - clock
    clock = time.monotonic_ns()
    _check_executable(executable, expected_sha256)
    identity_ns += time.monotonic_ns() - clock
    LAST_TIMINGS.clear()
    LAST_TIMINGS.update({"identity_validation_us": identity_ns // 1000, "native_process_us": native_ns // 1000, "wire_bytes": len(wire)})
    if process.returncode:
        raise ValueError("native process rejected the request: " + process.stderr[:4096].decode("ascii", errors="replace").strip())
    if len(process.stdout) > MAX_WIRE_BYTES:
        raise ValueError("native output byte cap exceeded")
    text = process.stdout.decode("ascii").strip()
    response = json.loads(text)
    if json.dumps(response, sort_keys=True, separators=(",", ":")) != text:
        raise ValueError("native response is not compact canonical JSON")
    return response


def _fields(value, names: str) -> None:
    if type(value) is not dict or set(value) != set(names.split()):
        raise ValueError("fields must be exactly: " + names)


def validate_observer_response(response: dict, job: dict) -> None:
    """The response contract of engine_observer, re-checked independently (decision rule included)."""
    _fields(response, "schema backend engine snapshot query_results")
    if response["schema"] != OBSERVER_SCHEMA or response["backend"] != job["backend"]:
        raise ValueError("native response contract mismatch")
    engine = response["engine"]
    _fields(engine, "ticks commits vertices edges observations faulted")
    if engine["faulted"] or engine["commits"] != 0:
        raise ValueError("native engine faulted or committed a crystal under the reviewed profile")
    snapshot = response["snapshot"]
    _fields(snapshot, "identity tick vertices walk_backend model")
    if snapshot["model"] != MODEL:
        raise ValueError("native model mismatch")
    if type(snapshot["identity"]) is not str or len(snapshot["identity"]) != 64:
        raise ValueError("invalid snapshot identity")
    if type(response["query_results"]) is not list or len(response["query_results"]) != len(job["queries"]):
        raise ValueError("native response query count mismatch")
    for query, result in zip(job["queries"], response["query_results"]):
        _fields(result, "region_backend values")
        if result["region_backend"] not in ("state_readout", "complete_graph_region"):
            raise ValueError("unknown native region backend")
        if type(result["values"]) is not list or len(result["values"]) != len(query["times_bits"]):
            raise ValueError("native response time count mismatch")
        threshold, deadband = number(query["threshold_bits"]), number(query["deadband_bits"])
        for time_bits, item in zip(query["times_bits"], result["values"]):
            _fields(item, "time_bits mass_bits decision")
            if item["time_bits"] != time_bits:
                raise ValueError("native time identity mismatch")
            mass = number(item["mass_bits"])
            if not 0 <= mass <= 1 + 1e-9:
                raise ValueError("native mass outside [0,1]")
            decision = "above" if mass > threshold + deadband else "below" if mass < threshold - deadband else "ambiguous"
            if item["decision"] != decision:
                raise ValueError("native decision does not match the declared rule")


def validate_readout_response(response: dict, job: dict) -> None:
    """The response contract of engine_readout, re-checked independently: arithmetic profile, zero
    commits, history counts, first-observation vertex order, co-observation edge counts, metric
    ranges, the gate rule and the identity over the complete readout."""
    _fields(response, "schema arithmetic engine identity ticks")
    if response["schema"] != READOUT_SCHEMA:
        raise ValueError("native readout schema mismatch")
    if response["arithmetic"] != ARITHMETIC:
        raise ValueError("native arithmetic profile %r is not the declared platform-independent one" % (response["arithmetic"],))
    engine = response["engine"]
    _fields(engine, "ticks commits vertices edges observations faulted")
    if engine["faulted"] is not False or engine["commits"] != 0:
        raise ValueError("native engine faulted or committed under the readout profile")
    batches, profile = job["batches"], _profile(job["profile"])
    order, pairs = _stream_batches(batches)
    if engine["ticks"] != len(batches) or engine["observations"] != sum(map(len, batches)) or engine["vertices"] != len(order) or engine["edges"] != len(pairs):
        raise ValueError("native history statistics mismatch")
    ticks = response["ticks"]
    if type(ticks) is not list or len(ticks) != len(batches):
        raise ValueError("native tick count mismatch")
    seen, seen_pairs = [], set()
    for index, (item, batch) in enumerate(zip(ticks, batches), start=1):
        _fields(item, "tick vertices edges helix carrier metrics kairos embedding")
        entities = [o["entity"] for o in batch]
        for entity in entities:
            if entity not in seen:
                seen.append(entity)
        for i in range(len(entities)):
            for j in range(i + 1, len(entities)):
                seen_pairs.add((min(entities[i], entities[j]), max(entities[i], entities[j])))
        if item["tick"] != index or item["vertices"] != seen or item["edges"] != len(seen_pairs):
            raise ValueError("native vertex order or edge count mismatch at tick %d" % index)
        _fields(item["helix"], "phi_bits r_bits")
        if not 0.0 <= number(item["helix"]["phi_bits"]) < TAU or not 0.0 <= number(item["helix"]["r_bits"]) <= 1.0:
            raise ValueError("native data helix outside its domain")
        _fields(item["carrier"], "index phi_bits kappa_bits delta_phi_bits")
        _integer(item["carrier"]["index"], 0, profile["carriers"] - 1)
        for key in ("phi_bits", "kappa_bits", "delta_phi_bits"):
            number(item["carrier"][key])
        _fields(item["metrics"], " ".join(METRICS))
        values = {name: number(item["metrics"][name]) for name in METRICS}
        if any(not 0.0 <= x <= 1.0 for x in values.values()):
            raise ValueError("native metric outside [0,1]")
        if item["kairos"] is not all(values[name] >= profile["thresholds"][name] for name in METRICS):
            raise ValueError("native gate verdict does not match the declared thresholds at tick %d" % index)
        embedding = item["embedding"]
        if type(embedding) is not list or len(embedding) != len(seen):
            raise ValueError("native embedding count mismatch")
        for row in embedding:
            if type(row) is not list or len(row) != 5 or any(not 0.0 <= number(x) <= 1.0 for x in row):
                raise ValueError("native embedding outside its domain")
    identity = response["identity"]
    bound = canonical({"batches": batches, "profile": job["profile"], "ticks": ticks})
    if type(identity) is not str or identity != hashlib.sha256(bound).hexdigest():
        raise ValueError("native readout identity does not cover the readout")


def detections(ticks: list, thresholds_bits: dict, schedule: dict, readout_identity: str) -> list:
    """Gate crossings admitted by the schedule: tick at least min_tick and more than cooldown ticks
    after the previous detection. Each detection's identity covers its complete content."""
    out, last = [], None
    for item in ticks:
        if not item["kairos"] or item["tick"] < schedule["min_tick"]:
            continue
        if last is not None and item["tick"] <= last + schedule["cooldown"]:
            continue
        record = {"readout_identity": readout_identity, "tick": item["tick"], "vertices": item["vertices"], "metrics": item["metrics"],
                  "thresholds": thresholds_bits, "schedule": schedule}
        record["identity"] = hashlib.sha256(canonical(record)).hexdigest()
        out.append(record)
        last = item["tick"]
    return out


def _sensor_vertex_id(entity: int) -> int:
    value = 0xcbf29ce484222325
    for byte in ("sensor-" + str(entity)).encode("ascii"):
        value = ((value ^ byte) * 0x100000001b3) & ((1 << 64) - 1)
    return value


def laplacian_for_certificate(response: dict, batches: list) -> dict:
    """Validate the exported exact snapshot of engine_snapshot and reconstruct the represented
    dense matrix (preserved from the inherited reachability profile; the digest is recomputed)."""
    _fields(response, "schema engine snapshot")
    if response["schema"] != SNAPSHOT_SCHEMA:
        raise ValueError("native snapshot schema mismatch")
    engine = response["engine"]
    _fields(engine, "ticks commits vertices edges observations faulted")
    for key in ("ticks", "commits", "vertices", "edges", "observations"):
        _integer(engine[key], 0, 2 ** 53 - 1)
    if type(engine["faulted"]) is not bool or engine["faulted"] or engine["commits"] != 0:
        raise ValueError("native snapshot unexpectedly faulted or committed")
    snapshot = response["snapshot"]
    _fields(snapshot, "identity tick vertices degree_bits adjacency model")
    if snapshot["model"] != MODEL:
        raise ValueError("native model mismatch")
    identity = snapshot["identity"]
    if type(identity) is not str or len(identity) != 64 or any(c not in "0123456789abcdef" for c in identity):
        raise ValueError("invalid snapshot identity")
    _integer(snapshot["tick"], 1, CAPS["max_batches"])
    vertices = snapshot["vertices"]
    if type(vertices) is not list or not 1 <= len(vertices) <= CAPS["max_nodes"]:
        raise ValueError("native vertex count exceeds cap")
    labels, vertex_ids = [], []
    for vertex in vertices:
        _fields(vertex, "entity vertex_id")
        labels.append(_integer(vertex["entity"], 0, 63))
        value = vertex["vertex_id"]
        if type(value) is not str or not value.isascii() or not value.isdecimal() or str(int(value)) != value or not 0 <= int(value) < 2 ** 64:
            raise ValueError("noncanonical native vertex identifier")
        if int(value) != _sensor_vertex_id(vertex["entity"]):
            raise ValueError("native entity label does not match sensor vertex identifier")
        vertex_ids.append(int(value))
    if len(set(labels)) != len(labels) or len(set(vertex_ids)) != len(vertex_ids):
        raise ValueError("duplicate native vertex")
    n = len(labels)
    if engine["vertices"] != n or engine["ticks"] != snapshot["tick"]:
        raise ValueError("native snapshot statistics mismatch")
    entities = {entity for batch in batches for entity in batch}
    if engine["ticks"] != len(batches) or engine["observations"] != sum(map(len, batches)) or set(labels) != entities:
        raise ValueError("native history mismatch")
    degrees = snapshot["degree_bits"]
    if type(degrees) is not list or len(degrees) != n:
        raise ValueError("native degree count mismatch")
    matrix = [[bits(0)] * n for _ in range(n)]
    for i, value in enumerate(degrees):
        if number(value) < 0:
            raise ValueError("negative native degree")
        matrix[i][i] = value
    adjacency = snapshot["adjacency"]
    if type(adjacency) is not list or len(adjacency) > n * (n - 1):
        raise ValueError("native adjacency exceeds cap")
    seen, previous = {}, None
    for edge in adjacency:
        _fields(edge, "from to weight_bits")
        i, j = (_integer(edge[k], 0, n - 1) for k in ("from", "to"))
        if i == j or (i, j) in seen or (previous is not None and (i, j) <= previous):
            raise ValueError("invalid native adjacency order")
        weight = number(edge["weight_bits"])
        if weight < 0:
            raise ValueError("negative native weight")
        seen[i, j] = edge["weight_bits"]
        previous = (i, j)
        matrix[i][j] = "%016x" % (int(edge["weight_bits"], 16) ^ (1 << 63))  # -w as exact binary64 bits
    for (i, j), weight in seen.items():
        if (j, i) not in seen or number(seen[j, i]) != number(weight):
            raise ValueError("asymmetric native adjacency")
    encoded = bytearray(b"gabriel/conditioned-snapshot/v1;exp(-itL);L=D-A\0")
    encoded += snapshot["tick"].to_bytes(8, "little") + n.to_bytes(8, "little")
    for vertex_id, degree in zip(vertex_ids, degrees):
        encoded += vertex_id.to_bytes(8, "little") + int(degree, 16).to_bytes(8, "little")
    encoded += len(adjacency).to_bytes(8, "little")
    for edge in adjacency:
        for value in (edge["from"], edge["to"], int(edge["weight_bits"], 16)):
            encoded += value.to_bytes(8, "little")
    if hashlib.sha256(encoded).hexdigest() != identity:
        raise ValueError("native snapshot identity does not cover exported graph")
    return {"identity": identity, "entities": labels, "laplacian_bits": matrix}


# ===================================================================== jobs

def _verdict(verdict, diagnostics, output=None, rows=None):
    return {"verdict": verdict, "diagnostics": diagnostics, "output": output, "output_units": None, "rows": rows}


def run_job(operation: str, parameters: dict, raw: bytes, binaries_bound: dict) -> dict:
    """Stage one of a native job: the contained part. Pure in (operation, parameters, input
    bytes, executable bytes). ``binaries_bound``: {name: {"path", "sha256"}}. Never raises for
    input problems; a certificate job returns the validated snapshot for stage two."""
    spec = OPERATIONS.get(operation)
    if spec is None:
        return _verdict("invalid_input", {"reason": "unknown operation %r (no default)" % operation})
    if parameters:
        return _verdict("invalid_input", {"reason": "native graph operations take no free parameters: the query is declared data"})
    description = describe(raw)
    if description["format"] != "json":
        return _verdict("invalid_input", {"reason": "; ".join(description["problems"])[:500]})
    if description["kind"] != spec["input_kind"]:
        return _verdict("out_of_scope", {"reason": "operation %s supports %s inputs, got %s" % (operation, spec["input_kind"], description["kind"]), "input": description})
    if description["problems"]:
        return _verdict("invalid_input", {"reason": "; ".join(description["problems"])[:500], "input": description})
    binary = binaries_bound.get(spec["binary"])
    if binary is None:
        return _verdict("unknown", {"reason": "native executable %s is not bound to this worker" % spec["binary"], "unavailable": True})
    data = json.loads(raw.decode("utf8"))
    try:
        if operation in ("graph.state_readout", "graph.detections"):
            job = {"schema": READOUT_SCHEMA, "batches": data["batches"], "profile": data["profile"]}
            response = invoke(binary["path"], binary["sha256"], job)
            validate_readout_response(response, job)
            diagnostics = {"engine": response["engine"], "arithmetic": response["arithmetic"], "executable_sha256": binary["sha256"], "timings": dict(LAST_TIMINGS),
                           "note": "a readout is a specified function of the declared stream and profile; it is not a measurement of anything outside the model"}
            if operation == "graph.state_readout":
                output = {"kind": "state_readout", "identity": response["identity"], "arithmetic": response["arithmetic"], "engine": response["engine"],
                          "profile": data["profile"], "ticks": response["ticks"], "model": READOUT_MODEL, "profile_id": PROFILE_ID}
                return _verdict("computed", diagnostics, output, len(response["ticks"]))
            schedule = _schedule(data["schedule"])
            found = detections(response["ticks"], data["profile"]["thresholds"], schedule, response["identity"])
            output = {"kind": "detections", "readout_identity": response["identity"], "arithmetic": response["arithmetic"], "engine": response["engine"],
                      "schedule": schedule, "thresholds": data["profile"]["thresholds"], "detections": found, "ticks_evaluated": len(response["ticks"]),
                      "model": READOUT_MODEL, "profile_id": PROFILE_ID}
            diagnostics["detections"] = [d["tick"] for d in found]
            return _verdict("computed", diagnostics, output, len(found))
        if operation in ("graph.snapshot", "graph.region_mass"):
            queries = []
            if operation == "graph.region_mass":
                queries = [{"source": data["source"], "targets": data["targets"], "times_bits": data["times_bits"],
                            "threshold_bits": data["threshold_bits"], "deadband_bits": data["deadband_bits"]}]
            job = {"schema": OBSERVER_SCHEMA, "backend": data.get("backend", "auto_region"), "batches": data["batches"], "queries": queries}
            response = invoke(binary["path"], binary["sha256"], job)
            validate_observer_response(response, job)
            output = {"kind": "graph_snapshot" if operation == "graph.snapshot" else "region_mass", "backend": job["backend"],
                      "engine": response["engine"], "snapshot": response["snapshot"], "model": MODEL, "profile": PROFILE_ID}
            if queries:
                result = response["query_results"][0]
                output.update({"region_backend": result["region_backend"], "targets": sorted(data["targets"]),
                               "threshold_bits": data["threshold_bits"], "deadband_bits": data["deadband_bits"], "values": result["values"]})
            diagnostics = {"engine": response["engine"], "walk_backend": response["snapshot"]["walk_backend"], "executable_sha256": binary["sha256"],
                           "timings": dict(LAST_TIMINGS), "note": "regional mass is a model readout of the conditioned walk, not a calibrated probability"}
            return _verdict("computed", diagnostics, output, len(response["query_results"][0]["values"]) if queries else response["engine"]["vertices"])
        # graph.window_reachability: stage one exports the exact represented Laplacian
        job = {"schema": SNAPSHOT_SCHEMA, "batches": data["batches"]}
        response = invoke(binary["path"], binary["sha256"], job)
        snapshot = laplacian_for_certificate(response, data["batches"])
        output = {"kind": "window_reachability", "stage": "snapshot", "engine": response["engine"], "native_snapshot": response["snapshot"],
                  "represented": snapshot, "request": {"source": data["source"], "targets": sorted(data["targets"]), "windows": data["windows"],
                                                       "threshold_bits": data["threshold_bits"]}, "certificates": None, "model": MODEL, "profile": PROFILE_ID}
        return _verdict("computed", {"engine": response["engine"], "executable_sha256": binary["sha256"], "stage": "snapshot", "timings": dict(LAST_TIMINGS),
                                     "note": "certificates are computed in a dedicated host process with exact arithmetic (stage two)"}, output, len(data["windows"]))
    except ValueError as exc:
        return _verdict("invalid_input", {"reason": str(exc)[:500]})


def worker_build(binaries_bound: dict) -> str:
    """Identity of this worker: this file's bytes plus the bound executable digests."""
    with open(__file__, "rb") as stream:
        source = hashlib.sha256(stream.read()).hexdigest()
    parts = [source] + ["%s:%s" % (name, binaries_bound[name]["sha256"]) for name in sorted(binaries_bound)]
    return hashlib.sha256("|".join(parts).encode("ascii")).hexdigest()


def numerical_environment() -> dict:
    """The declared environment fields of a job (profile and model are bound by the job's profile id and this file)."""
    return {"python": platform.python_version(), "platform": "%s-%s" % (platform.system().lower(), platform.machine()), "float_model": "ieee754-binary64"}


# ===================================================================== stage two: exact certificates (dedicated host process)

def certify(output: dict, precisions=(128, 256, 512)) -> dict:
    """Exact window certificates over the validated snapshot (python-flint/Arb). Runs in a
    dedicated process; the Arb context is never shared with unrelated work."""
    try:
        from . import window_certificate  # vendored, bound by its source hash
    except ImportError:
        from gabriel_agent.adapters import window_certificate
    represented, request = output["represented"], output["request"]
    certificates = []
    for window in request["windows"]:
        certificates.append(window_certificate.certify_window(represented, request["source"], request["targets"], window["start_bits"], window["end_bits"],
                                                              request["threshold_bits"], precisions=precisions))
    text = json.dumps(certificates, sort_keys=True, allow_nan=False)
    return {"certificates": json.loads(text), "statuses": [c["status"] for c in certificates],
            "arithmetic": window_certificate.implementation_identity() if hasattr(window_certificate, "implementation_identity") else None}


# ===================================================================== worker entry point (inside the containment backend)

def main(argv) -> int:
    clock = time.monotonic_ns()
    job = json.loads(Path(argv[1]).read_text())
    raw = Path(job["input_path"]).read_bytes()
    if len(raw) > int(job.get("max_input_bytes", MAX_INPUT_BYTES)):
        result = _verdict("invalid_input", {"reason": "input exceeds the declared byte limit"})
    else:
        bound = {name: {"path": entry["path"], "sha256": entry["sha256"]} for name, entry in job.get("binaries", {}).items()}
        result = run_job(job["operation"], job.get("parameters") or {}, raw, bound)
    record = {"verdict": result["verdict"], "diagnostics": result["diagnostics"], "output_units": result["output_units"], "rows": result["rows"],
              "worker_build": worker_build({n: {"sha256": e["sha256"]} for n, e in job.get("binaries", {}).items()}),
              "numerical_environment": numerical_environment(), "output_sha256": None, "operation": job["operation"],
              "input_sha256": hashlib.sha256(raw).hexdigest(), "worker_us": None}
    if result["output"] is not None:
        out = dumps(result["output"])
        path = Path(job["output_path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(out)
        record["output_sha256"] = hashlib.sha256(out).hexdigest()
    record["worker_us"] = (time.monotonic_ns() - clock) // 1000
    Path(job["result_path"]).write_text(json.dumps(record, sort_keys=True))
    return 0


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "certify":
        payload = json.loads(sys.stdin.read())
        sys.stdout.write(json.dumps(certify(payload["output"], tuple(payload.get("precisions", (128, 256, 512)))), sort_keys=True))
        raise SystemExit(0)
    raise SystemExit(main(sys.argv))
