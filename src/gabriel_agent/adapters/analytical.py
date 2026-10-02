#!/usr/bin/env python3
"""Declared analytical operations with explicit units, time and scope semantics.

This file is deliberately self-contained (standard library only): the numerical DomainPack
copies it into the contained worktree and runs it as a fresh worker process per job, and the
tests call ``run_job`` in-process. Both paths are the same code, identified by the SHA-256 of
this file (``worker_build``).

Every operation declares the input kind it supports, its parameters and how output units are
derived. A supported input yields the verdict ``computed``. Inputs outside the declared scope
yield ``out_of_scope``; malformed inputs yield ``invalid_input``. Neither is a transport
failure, and neither can become a success claim: the acceptance verifier only accepts
``computed`` results that meet the independent reference contract.

The inherited padded graph hash of the recovered runtime collides across graph sizes
(``legacy_padded_signature``): it is reported for comparison only and never authorizes
anything. The cache key of a job binds the complete input bytes, operation, parameters,
profile, worker build and numerical environment instead.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import math
import os
import platform
import sys

PROFILE_ID = "analytical-stdlib-v1"
MAX_INPUT_BYTES = 1 << 20
MAX_ROWS = 100000
MAX_GRAPH_VERTICES = 7
FLOAT_MODEL = "ieee754-binary64"

UNITS = {
    "degC": ("temperature", 1.0, 273.15), "K": ("temperature", 1.0, 0.0), "degF": ("temperature", 5.0 / 9.0, 459.67 * 5.0 / 9.0),
    "m": ("length", 1.0, 0.0), "km": ("length", 1000.0, 0.0), "cm": ("length", 0.01, 0.0), "mm": ("length", 0.001, 0.0),
    "s": ("time", 1.0, 0.0), "ms": ("time", 0.001, 0.0), "min": ("time", 60.0, 0.0), "h": ("time", 3600.0, 0.0),
}

OPERATIONS = {
    "units.convert": {"input_kind": "series", "parameters": {"to_units": "string"}, "required": ["to_units"],
                      "description": "convert every value of a series to the target unit of the same dimension; time stamps unchanged",
                      "output_units": "parameters.to_units"},
    "series.resample_mean": {"input_kind": "series", "parameters": {"bucket_ms": "integer"}, "required": ["bucket_ms"],
                             "description": "arithmetic mean of the values per bucket of bucket_ms on the unix_ms time basis; empty buckets are omitted",
                             "output_units": "input.units"},
    "graph.small_signature": {"input_kind": "graph", "parameters": {}, "required": [],
                              "description": "canonical structural signature of a simple undirected graph with at most seven vertices; retains the vertex count",
                              "output_units": None},
}


def worker_build() -> str:
    with open(__file__, "rb") as stream:
        return hashlib.sha256(stream.read()).hexdigest()


def numerical_environment() -> dict:
    return {"python": platform.python_version(), "platform": "%s-%s" % (platform.system().lower(), platform.machine()), "float_model": FLOAT_MODEL}


def to_kelvin_like(value: float, unit: str) -> float:
    _, scale, offset = UNITS[unit]
    return value * scale + offset


def from_base(value: float, unit: str) -> float:
    _, scale, offset = UNITS[unit]
    return (value - offset) / scale


# ---------------------------------------------------------------- input contract

def describe(raw: bytes) -> dict:
    """Describe a dataset without computing anything: kind, units, time basis, rows, problems."""
    out = {"format": "unsupported", "kind": "unknown", "units": None, "time_basis": None, "rows": None, "problems": []}
    if len(raw) > MAX_INPUT_BYTES:
        out["problems"].append("input exceeds %d bytes" % MAX_INPUT_BYTES)
        return out
    try:
        data = json.loads(raw.decode("utf8"))
    except (UnicodeDecodeError, ValueError) as exc:
        out["problems"].append("not a JSON document: " + str(exc)[:120])
        return out
    if not isinstance(data, dict):
        out["problems"].append("top level is not an object")
        return out
    out["format"] = "json"
    kind = data.get("kind")
    if kind in ("series", "graph", "table"):
        out["kind"] = kind
    else:
        out["problems"].append("unknown dataset kind %r" % (kind,))
    units = data.get("units")
    if isinstance(units, str) and units.isascii() and len(units) <= 32:
        out["units"] = units
        if units not in UNITS:
            out["problems"].append("unit %r is not in the declared catalogue" % units)
    elif units is not None:
        out["problems"].append("units must be a short ASCII string")
    basis = data.get("time_basis")
    if basis in ("unix_ms", "index"):
        out["time_basis"] = basis
    elif basis is None:
        out["time_basis"] = "unknown" if kind == "series" else None
    else:
        out["problems"].append("unknown time basis %r" % (basis,))
    if kind == "series":
        values = data.get("values")
        if not isinstance(values, list):
            out["problems"].append("series needs a values list")
        else:
            out["rows"] = len(values)
            if len(values) > MAX_ROWS:
                out["problems"].append("series exceeds %d rows" % MAX_ROWS)
            for index, row in enumerate(values[:MAX_ROWS]):
                problem = _series_row_problem(row)
                if problem:
                    out["problems"].append("row %d: %s" % (index, problem))
                    if len(out["problems"]) >= 16:
                        break
    elif kind == "graph":
        n = data.get("vertices")
        edges = data.get("edges")
        if not isinstance(n, int) or isinstance(n, bool) or n < 0:
            out["problems"].append("graph needs a non-negative integer vertex count")
        if not isinstance(edges, list):
            out["problems"].append("graph needs an edge list")
        else:
            out["rows"] = len(edges)
    return out


def _series_row_problem(row):
    if not (isinstance(row, list) and len(row) == 2):
        return "row is not a [time, value] pair"
    t, v = row
    if not isinstance(t, int) or isinstance(t, bool):
        return "time stamp is not an integer"
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return "value is not a number"
    if isinstance(v, float) and not math.isfinite(v):
        return "value is not finite"
    return None


# ---------------------------------------------------------------- operations

def _verdict(verdict, diagnostics, output=None, output_units=None, rows=None):
    return {"verdict": verdict, "output": output, "output_units": output_units, "rows": rows, "diagnostics": diagnostics}


def run_job(operation: str, parameters: dict, raw: bytes) -> dict:
    """Pure function of (operation, parameters, input bytes). Never raises for input problems."""
    spec = OPERATIONS.get(operation)
    if spec is None:
        return _verdict("invalid_input", {"reason": "unknown operation %r (no default)" % operation})
    for name in spec["required"]:
        if name not in parameters:
            return _verdict("invalid_input", {"reason": "missing parameter " + name})
    for name, value in parameters.items():
        expected = spec["parameters"].get(name)
        if expected is None:
            return _verdict("invalid_input", {"reason": "unknown parameter " + name})
        if expected == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
            return _verdict("invalid_input", {"reason": "parameter %s must be an integer" % name})
        if expected == "string" and not isinstance(value, str):
            return _verdict("invalid_input", {"reason": "parameter %s must be a string" % name})
    description = describe(raw)
    if description["format"] != "json":
        return _verdict("invalid_input", {"reason": "; ".join(description["problems"])[:500]})
    if description["kind"] != spec["input_kind"]:
        return _verdict("out_of_scope", {"reason": "operation %s supports %s inputs, got %s" % (operation, spec["input_kind"], description["kind"]),
                                         "input": description})
    if description["problems"]:
        return _verdict("invalid_input", {"reason": "; ".join(description["problems"])[:500], "input": description})
    data = json.loads(raw.decode("utf8"))
    if operation == "units.convert":
        return _units_convert(data, parameters["to_units"], description)
    if operation == "series.resample_mean":
        return _resample_mean(data, parameters["bucket_ms"], description)
    return _small_signature(data, description)


def _units_convert(data, to_units, description):
    source = description["units"]
    if source is None:
        return _verdict("invalid_input", {"reason": "series declares no units"})
    if to_units not in UNITS:
        return _verdict("invalid_input", {"reason": "target unit %r is not in the declared catalogue" % to_units})
    if UNITS[source][0] != UNITS[to_units][0]:
        return _verdict("out_of_scope", {"reason": "cannot convert %s (%s) to %s (%s)" % (source, UNITS[source][0], to_units, UNITS[to_units][0])})
    values = [[t, from_base(to_kelvin_like(float(v), source), to_units)] for t, v in data["values"]]
    output = {"kind": "series", "units": to_units, "time_basis": data.get("time_basis", "unknown"), "values": values}
    return _verdict("computed", {"source_units": source, "target_units": to_units, "dimension": UNITS[source][0]}, output, to_units, len(values))


def _resample_mean(data, bucket_ms, description):
    if bucket_ms <= 0:
        return _verdict("invalid_input", {"reason": "bucket_ms must be positive"})
    if description["time_basis"] != "unix_ms":
        return _verdict("out_of_scope", {"reason": "resampling needs the unix_ms time basis, got %s" % description["time_basis"]})
    buckets = {}
    for t, v in data["values"]:
        start = (t // bucket_ms) * bucket_ms
        total, count = buckets.get(start, (0.0, 0))
        buckets[start] = (total + float(v), count + 1)
    values = [[start, buckets[start][0] / buckets[start][1]] for start in sorted(buckets)]
    output = {"kind": "series", "units": description["units"], "time_basis": "unix_ms", "values": values}
    return _verdict("computed", {"bucket_ms": bucket_ms, "input_rows": len(data["values"]), "buckets": len(values)}, output, description["units"], len(values))


def canonical_adjacency(n: int, edges) -> str:
    """Lexicographically minimal adjacency bit string over all vertex permutations (n <= 7)."""
    adjacency = [[0] * n for _ in range(n)]
    for a, b in edges:
        adjacency[a][b] = adjacency[b][a] = 1
    best = None
    for perm in itertools.permutations(range(n)):
        bits = "".join(str(adjacency[perm[i]][perm[j]]) for i in range(n) for j in range(n))
        if best is None or bits < best:
            best = bits
    return best or ""


def legacy_padded_signature(edges) -> str:
    """The inherited defect, reproduced for comparison: the input adjacency padded to 7x7 and
    hashed without the vertex count, so a graph and the same graph with extra isolated vertices
    share a signature. Reported in diagnostics only; never a cache key."""
    padded = [[0] * MAX_GRAPH_VERTICES for _ in range(MAX_GRAPH_VERTICES)]
    for a, b in edges:
        if a < MAX_GRAPH_VERTICES and b < MAX_GRAPH_VERTICES:
            padded[a][b] = padded[b][a] = 1
    bits = "".join(str(padded[i][j]) for i in range(MAX_GRAPH_VERTICES) for j in range(MAX_GRAPH_VERTICES))
    return hashlib.sha256(bits.encode("ascii")).hexdigest()


def _small_signature(data, description):
    n, edges = data["vertices"], data["edges"]
    if n > MAX_GRAPH_VERTICES:
        return _verdict("out_of_scope", {"reason": "small signature supports at most %d vertices, got %d" % (MAX_GRAPH_VERTICES, n)})
    seen = set()
    for edge in edges:
        if not (isinstance(edge, list) and len(edge) == 2 and all(isinstance(x, int) and not isinstance(x, bool) for x in edge)):
            return _verdict("invalid_input", {"reason": "edge is not a pair of integers: %r" % (edge,)})
        a, b = edge
        if a == b:
            return _verdict("invalid_input", {"reason": "self-loop at vertex %d (simple graphs only)" % a})
        if not (0 <= a < n and 0 <= b < n):
            return _verdict("invalid_input", {"reason": "edge %r names a vertex outside 0..%d" % (edge, n - 1)})
        key = (min(a, b), max(a, b))
        if key in seen:
            return _verdict("invalid_input", {"reason": "duplicate edge %r (simple graphs only)" % (edge,)})
        seen.add(key)
    bits = canonical_adjacency(n, sorted(seen))
    signature = hashlib.sha256(("n=%d;adj=%s" % (n, bits)).encode("ascii")).hexdigest()
    output = {"kind": "graph_signature", "vertices": n, "edges": len(seen), "canonical_adjacency": bits, "signature": signature}
    return _verdict("computed", {"vertices": n, "edges": len(seen), "legacy_padded_signature": legacy_padded_signature(sorted(seen)),
                                 "note": "legacy_padded_signature collides across sizes and is reported for comparison only"}, output, None, len(seen))


def dumps(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=True).encode("ascii")


def main(argv) -> int:
    if len(argv) != 2:
        sys.stderr.write("usage: worker.py job.json\n")
        return 2
    with open(argv[1], "rb") as stream:
        job = json.loads(stream.read().decode("utf8"))
    limit = int(job.get("max_input_bytes", MAX_INPUT_BYTES))
    with open(job["input_path"], "rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        result = _verdict("invalid_input", {"reason": "input exceeds the job limit of %d bytes" % limit})
    else:
        result = run_job(job["operation"], job.get("parameters") or {}, raw)
    output_sha = None
    if result["verdict"] == "computed":
        payload = dumps(result["output"])
        parent = os.path.dirname(job["output_path"])
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(job["output_path"], "wb") as stream:
            stream.write(payload)
        output_sha = hashlib.sha256(payload).hexdigest()
    record = {"verdict": result["verdict"], "output_sha256": output_sha, "output_units": result["output_units"], "rows": result["rows"],
              "diagnostics": result["diagnostics"], "worker_build": worker_build(), "numerical_environment": numerical_environment(),
              "operation": job["operation"], "input_sha256": hashlib.sha256(raw).hexdigest()}
    with open(job["result_path"], "wb") as stream:
        stream.write(dumps(record))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
