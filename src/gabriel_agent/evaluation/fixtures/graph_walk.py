"""Native graph fixture (ADR-18): an observation-batch history, a region-mass query over it and
closed-window queries over a uniform clique history, with references computed independently of
the native engine.

The reference reconstructs the represented model from the declared construction rule (every pair
of entities co-observed in a batch is joined by an edge of symmetrized weight 1/2 whatever the
number of co-observations; the degree is the sum of incident weights; vertices are ordered by
first observation), evaluates the walk ``exp(-itL)`` with scipy's matrix exponential on the
normalized source and recomputes the snapshot identity from the reconstruction. The window
statuses come from the closed-form harmonic model of a uniform clique, accepted only with a
declared margin far above floating-point error. None of it calls the native code.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import struct
import subprocess
from pathlib import Path

BATCHES = [[0, 1, 2], [2, 3], [0, 3], [0, 1, 2]]          # four entities; not a uniform clique
CLIQUE_BATCHES = [[0, 1, 2, 3], [0, 1, 2, 3]]              # uniform clique: exact window certificates apply
SOURCE = [(0, 1.0, 0.0), (1, 0.0, 0.0), (2, 0.0, 0.0), (3, 0.0, 0.0)]
TARGETS = [3]
TIMES = [0.0, 0.5, 1.0, 2.0, 4.0]
THRESHOLD, DEADBAND = 0.2, 0.01
WINDOWS = [(0.0, 1.0), (1.0, 2.0)]                         # clique at threshold 0.2: excluded, then reachable
MARGIN = 1e-6
OUTPUTS = {"graph.snapshot": "out/snapshot.json", "graph.region_mass": "out/mass.json", "graph.window_reachability": "out/window.json"}
INPUTS = {"graph.snapshot": "data/batches.json", "graph.region_mass": "data/query.json", "graph.window_reachability": "data/window.json"}
GOALS = {"graph.snapshot": "Condition the native graph engine on the observation batches in data/batches.json and write its conditioned snapshot "
                           "(identity, vertices, walk backend, engine statistics) to out/snapshot.json.",
         "graph.region_mass": "Read out the regional mass of the source-conditioned walk declared in data/query.json at its declared times with its "
                              "threshold and deadband rule and write the result to out/mass.json.",
         "graph.window_reachability": "Certify, for every closed window declared in data/window.json, whether the regional mass of the declared walk "
                                      "exceeds the declared threshold somewhere in the window, and write the certificates to out/window.json."}


def bits(value: float) -> str:
    return struct.pack(">d", float(value)).hex()


def number(value: str) -> float:
    return struct.unpack(">d", bytes.fromhex(value))[0]


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf8")).hexdigest()


# ------------------------------------------------------------------ datasets

def source_entries(source=SOURCE) -> list:
    return [{"entity": e, "re_bits": bits(re), "im_bits": bits(im)} for e, re, im in source]


def batches_dataset(batches=BATCHES, backend="auto_region") -> dict:
    return {"kind": "observation_batches", "batches": batches, "backend": backend}


def query_dataset(batches=BATCHES, backend="auto_region", source=SOURCE, targets=TARGETS, times=TIMES, threshold=THRESHOLD, deadband=DEADBAND) -> dict:
    return {"kind": "graph_query", "batches": batches, "backend": backend, "source": source_entries(source), "targets": list(targets),
            "times_bits": [bits(t) for t in times], "threshold_bits": bits(threshold), "deadband_bits": bits(deadband)}


def window_dataset(batches=CLIQUE_BATCHES, source=SOURCE, targets=TARGETS, windows=WINDOWS, threshold=THRESHOLD) -> dict:
    return {"kind": "graph_window_query", "batches": batches, "source": source_entries(source), "targets": list(targets),
            "windows": [{"start_bits": bits(a), "end_bits": bits(b)} for a, b in windows], "threshold_bits": bits(threshold)}


def text(dataset: dict) -> str:
    return json.dumps(dataset, indent=1) + "\n"


BATCHES_TEXT = text(batches_dataset())
QUERY_TEXT = text(query_dataset())
WINDOW_TEXT = text(window_dataset())
WINDOW_MIXED_TEXT = text(window_dataset(batches=BATCHES))  # not a uniform clique: the exact certificate profile declares out_of_scope
TEXTS = {"data/batches.json": BATCHES_TEXT, "data/query.json": QUERY_TEXT, "data/window.json": WINDOW_TEXT, "data/window_mixed.json": WINDOW_MIXED_TEXT}


# ------------------------------------------------------------------ independent reference model

def vertex_order(batches) -> list:
    order = []
    for batch in batches:
        for entity in batch:
            if entity not in order:
                order.append(entity)
    return order


def reference_laplacian(batches) -> tuple:
    """Vertex order and the dense Laplacian L = D - A of the reconstructed model (floats)."""
    order = vertex_order(batches)
    index = {e: i for i, e in enumerate(order)}
    n = len(order)
    adjacency = [[0.0] * n for _ in range(n)]
    for batch in batches:
        for a in batch:
            for b in batch:
                if a != b:
                    adjacency[index[a]][index[b]] = 0.5
    laplacian = [[(sum(adjacency[i]) if i == j else 0.0) - adjacency[i][j] for j in range(n)] for i in range(n)]
    return order, laplacian


def sensor_vertex_id(entity: int) -> int:
    """FNV-1a of the sensor label, as the engine's sensor adapter declares it."""
    value = 0xcbf29ce484222325
    for byte in ("sensor-%d" % entity).encode("ascii"):
        value = ((value ^ byte) * 0x100000001b3) & ((1 << 64) - 1)
    return value


def reference_identity(batches) -> str:
    """The snapshot identity recomputed from the reconstruction (declared digest layout)."""
    order, laplacian = reference_laplacian(batches)
    n = len(order)
    encoded = bytearray(b"gabriel/conditioned-snapshot/v1;exp(-itL);L=D-A\0")
    encoded += len(batches).to_bytes(8, "little") + n.to_bytes(8, "little")
    for i, entity in enumerate(order):
        encoded += sensor_vertex_id(entity).to_bytes(8, "little") + struct.pack("<d", laplacian[i][i])
    edges = [(i, j) for i in range(n) for j in range(n) if i != j and laplacian[i][j] != 0.0]
    encoded += len(edges).to_bytes(8, "little")
    for i, j in edges:
        encoded += i.to_bytes(8, "little") + j.to_bytes(8, "little") + struct.pack("<d", -laplacian[i][j])
    return hashlib.sha256(encoded).hexdigest()


def jacobi_eigen(matrix: list, sweeps: int = 100) -> tuple:
    """Eigenvalues and orthonormal eigenvectors (columns) of a real symmetric matrix by cyclic
    Jacobi rotations; standard library only."""
    n = len(matrix)
    a = [list(map(float, row)) for row in matrix]
    v = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
    for _ in range(sweeps):
        off = sum(a[i][j] ** 2 for i in range(n) for j in range(n) if i != j)
        if off < 1e-300:
            break
        for p in range(n - 1):
            for q in range(p + 1, n):
                if a[p][q] == 0.0:
                    continue
                theta = (a[q][q] - a[p][p]) / (2.0 * a[p][q])
                t = (1.0 if theta >= 0 else -1.0) / (abs(theta) + math.sqrt(theta * theta + 1.0))
                c = 1.0 / math.sqrt(t * t + 1.0)
                s = t * c
                for k in range(n):
                    akp, akq = a[k][p], a[k][q]
                    a[k][p], a[k][q] = c * akp - s * akq, s * akp + c * akq
                for k in range(n):
                    apk, aqk = a[p][k], a[q][k]
                    a[p][k], a[q][k] = c * apk - s * aqk, s * apk + c * aqk
                for k in range(n):
                    vkp, vkq = v[k][p], v[k][q]
                    v[k][p], v[k][q] = c * vkp - s * vkq, s * vkp + c * vkq
    return [a[i][i] for i in range(n)], v


def reference_masses(batches, source, targets, times, method: str = "stdlib") -> list:
    """Regional mass sum_{j in targets} |(exp(-itL) psi)_j|^2 of the normalized source.

    ``stdlib``: spectral decomposition of the symmetric Laplacian by Jacobi rotations (no third
    party code); ``scipy``: scipy's matrix exponential. Two independent references for tests."""
    order, laplacian = reference_laplacian(batches)
    index = {e: i for i, e in enumerate(order)}
    n = len(order)
    if method == "scipy":
        import numpy as np
        from scipy.linalg import expm
        psi = np.zeros(n, dtype=complex)
        for entity, re, im in source:
            psi[index[entity]] = complex(re, im)
        psi = psi / np.linalg.norm(psi)
        matrix = np.array(laplacian, dtype=float)
        return [float(sum(abs((expm(-1j * float(t) * matrix) @ psi)[index[e]]) ** 2 for e in targets)) for t in times]
    if method != "stdlib":
        raise ValueError(method)
    psi = [0j] * n
    for entity, re, im in source:
        psi[index[entity]] = complex(re, im)
    norm = math.sqrt(sum(abs(x) ** 2 for x in psi))
    psi = [x / norm for x in psi]
    values, vectors = jacobi_eigen(laplacian)
    coefficients = [sum(vectors[i][k] * psi[i] for i in range(n)) for k in range(n)]  # Q^T psi
    masses = []
    for t in times:
        phases = [complex(math.cos(-lam * t), math.sin(-lam * t)) for lam in values]
        state = [sum(vectors[i][k] * phases[k] * coefficients[k] for k in range(n)) for i in range(n)]
        masses.append(float(sum(abs(state[index[e]]) ** 2 for e in targets)))
    return masses


def decision(mass: float, threshold: float = THRESHOLD, deadband: float = DEADBAND) -> str:
    return "above" if mass > threshold + deadband else "below" if mass < threshold - deadband else "ambiguous"


def reference_mass_rows(batches=BATCHES, source=SOURCE, targets=TARGETS, times=TIMES, threshold=THRESHOLD, deadband=DEADBAND) -> list:
    return [[bits(t), m, decision(m, threshold, deadband)] for t, m in zip(times, reference_masses(batches, source, targets, times))]


def harmonic_coefficients(batches, source, targets) -> tuple:
    """For a uniform clique on n vertices with weight w: psi(t) = m + exp(-i n w t)(psi - m), so the
    regional mass is a + b cos(omega t) + c sin(omega t) with omega = n w (derived here, not read
    from the certificate code)."""
    order, laplacian = reference_laplacian(batches)
    n = len(order)
    weight = -laplacian[0][1] if n > 1 else 0.0
    for i in range(n):
        for j in range(n):
            if not math.isclose(laplacian[i][j], (n - 1) * weight if i == j else -weight, abs_tol=0.0):
                raise ValueError("not a uniform clique")
    index = {e: i for i, e in enumerate(order)}
    psi = [0j] * n
    for entity, re, im in source:
        psi[index[entity]] = complex(re, im)
    norm = math.sqrt(sum(abs(x) ** 2 for x in psi))
    psi = [x / norm for x in psi]
    mean = sum(psi) / n
    a = b = c = 0.0
    for entity in targets:
        d = psi[index[entity]] - mean
        a += abs(mean) ** 2 + abs(d) ** 2
        b += 2 * (mean * d.conjugate()).real
        c += 2 * (mean * d.conjugate()).imag  # Im(m conj(d)): the e^{-i omega t} phase convention
    return a, b, c, n * weight


def reference_window_statuses(batches=CLIQUE_BATCHES, source=SOURCE, targets=TARGETS, windows=WINDOWS, threshold=THRESHOLD, margin=MARGIN) -> list:
    """Closed-form maximum of a + R cos(omega t - phi) over each closed window; a status is issued
    only when the maximum clears the threshold by the declared margin."""
    a, b, c, omega = harmonic_coefficients(batches, source, targets)
    amplitude, phase = math.hypot(b, c), math.atan2(c, b)
    statuses = []
    for start, end in windows:
        candidates = [start, end]
        if omega > 0 and amplitude > 0:
            k = math.ceil((omega * start - phase) / (2 * math.pi))
            while True:
                t = (phase + 2 * math.pi * k) / omega
                if t > end:
                    break
                if t >= start:
                    candidates.append(t)
                k += 1
        maximum = max(a + amplitude * math.cos(omega * t - phase) for t in candidates)
        if maximum > threshold + margin:
            statuses.append("reachable")
        elif maximum < threshold - margin:
            statuses.append("excluded")
        else:
            raise ValueError("window maximum within the declared margin of the threshold: fixture must not depend on rounding")
    return statuses


# ------------------------------------------------------------------ repository, oracle, task and scripted worker

def build_repo(path: Path) -> str:
    path = Path(path)
    (path / "data").mkdir(parents=True)
    for relative, content in TEXTS.items():
        (path / relative).write_text(content)
    (path / "README.md").write_text("# Observation batches\n\nEntities co-observed per batch; queries declare their source, targets, times and thresholds as binary64 bits.\n")
    env = dict(os.environ, GIT_AUTHOR_NAME="fixture", GIT_AUTHOR_EMAIL="fixture@invalid", GIT_COMMITTER_NAME="fixture", GIT_COMMITTER_EMAIL="fixture@invalid")
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True, env=env)
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True, env=env)
    subprocess.run(["git", "-C", str(path), "commit", "-q", "-m", "seed observation batches"], check=True, env=env)
    return subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()


def oracle(operation: str) -> dict:
    if operation == "graph.snapshot":
        return {"operation": operation, "output_path": OUTPUTS[operation], "units": None, "identity": reference_identity(BATCHES), "vertices": len(vertex_order(BATCHES))}
    if operation == "graph.region_mass":
        return {"operation": operation, "output_path": OUTPUTS[operation], "units": None, "tolerance_micro": 1, "masses": reference_mass_rows()}
    if operation == "graph.window_reachability":
        return {"operation": operation, "output_path": OUTPUTS[operation], "units": None, "statuses": reference_window_statuses()}
    raise ValueError(operation)


def write_oracle(path: Path, operation: str = "graph.region_mass") -> Path:
    path = Path(path)
    path.write_text(json.dumps(oracle(operation), indent=1) + "\n")
    return path


def task_spec(repo: Path, base_commit: str, oracle_path: Path, provider: dict, operation: str = "graph.region_mass", **over) -> dict:
    spec = {"domain": "numerical", "goal": GOALS[operation], "repository": str(repo), "base_commit": base_commit, "allowed_paths": ["out/"],
            "checks": [{"check_id": "reference", "kind": "numerical/reference_contract", "independent": True, "role": "acceptance_only",
                        "oracle_files": [{"path": "oracle/expected.json", "source": str(oracle_path)}]}],
            "provider": provider, "budget": {"model_tokens_total": 200000, "model_requests": 12}}
    spec.update(over)
    return spec


def _job(operation, input_path, output_path, parameters=None, rationale="run the declared native operation"):
    return {"kind": "text", "value": {"operation": operation, "input_path": input_path, "expected_sha256": sha(TEXTS[input_path]),
                                      "output_path": output_path, "parameters": parameters or {}, "rationale": rationale}}


def script(variant: str = "graph.region_mass") -> dict:
    planner = [{"kind": "echo_reference"}]
    if variant in OUTPUTS:
        worker = [_job(variant, INPUTS[variant], OUTPUTS[variant])]
    elif variant == "window_mixed":
        worker = [_job("graph.window_reachability", "data/window_mixed.json", OUTPUTS["graph.window_reachability"], rationale="certify windows on the mixed history")]
    elif variant == "wrong_input_kind":
        worker = [_job("graph.region_mass", "data/batches.json", OUTPUTS["graph.region_mass"], rationale="read masses from a batch history")]
    elif variant == "with_parameters":
        worker = [_job("graph.region_mass", "data/query.json", OUTPUTS["graph.region_mass"], parameters={"backend": "spectral_full"}, rationale="choose the backend")]
    elif variant == "stdlib_on_native":
        worker = [_job("graph.small_signature", "data/query.json", "out/signature.json", rationale="sign the query graph")]
    else:
        raise ValueError("unknown variant " + variant)
    return {"by_step": {"plan-request": planner, "propose": worker}, "by_role": {"planner": planner, "worker": worker}}
