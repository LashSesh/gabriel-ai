"""Numerical fixture: a declared unit conversion with an independent reference contract.

The dataset declares its units and time basis. The oracle (kept outside the repository) is
computed here by a separate reference implementation, not by the adapter, and declares the
expected operation, output path, units, tolerance and values. Variants of the scripted worker
exercise a valid job, a dimension mismatch (out of scope), an unknown operation and an output
path outside the admitted scope.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

SERIES = {"kind": "series", "units": "degC", "time_basis": "unix_ms",
          "values": [[0, 20.0], [1000, 21.5], [2000, 19.25], [3500, 22.0], [4000, -3.5]]}
SERIES_TEXT = json.dumps(SERIES, indent=1) + "\n"
GRAPH = {"kind": "graph", "vertices": 4, "edges": [[0, 1], [1, 2], [2, 3]]}
GRAPH_TEXT = json.dumps(GRAPH, indent=1) + "\n"
OUTPUT_PATH = "out/series_kelvin.json"


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf8")).hexdigest()


def reference_kelvin(values) -> list:
    """Independent reference: degrees Celsius to kelvin, computed without the adapter."""
    return [[t, v + 273.15] for t, v in values]


def build_repo(path: Path) -> str:
    path = Path(path)
    (path / "data").mkdir(parents=True)
    (path / "data" / "series.json").write_text(SERIES_TEXT)
    (path / "data" / "graph.json").write_text(GRAPH_TEXT)
    (path / "README.md").write_text("# Sensor series\n\nTemperatures in degrees Celsius on the unix_ms time basis.\n")
    env = dict(os.environ, GIT_AUTHOR_NAME="fixture", GIT_AUTHOR_EMAIL="fixture@invalid", GIT_COMMITTER_NAME="fixture", GIT_COMMITTER_EMAIL="fixture@invalid")
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True, env=env)
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True, env=env)
    subprocess.run(["git", "-C", str(path), "commit", "-q", "-m", "seed sensor series"], check=True, env=env)
    return subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()


def write_oracle(path: Path) -> Path:
    path = Path(path)
    path.write_text(json.dumps({"operation": "units.convert", "output_path": OUTPUT_PATH, "units": "K", "tolerance_micro": 1,
                                "values": reference_kelvin(SERIES["values"])}, indent=1))
    return path


def task_spec(repo: Path, base_commit: str, oracle_path: Path, provider: dict, **over) -> dict:
    spec = {"domain": "numerical",
            "goal": "Convert the temperature series in data/series.json from degrees Celsius to kelvin using the declared units and write the "
                    "converted series to out/series_kelvin.json. Keep the time stamps unchanged.",
            "repository": str(repo), "base_commit": base_commit, "allowed_paths": ["out/"],
            "checks": [{"check_id": "reference", "kind": "numerical/reference_contract", "independent": True, "role": "acceptance_only",
                        "oracle_files": [{"path": "oracle/expected.json", "source": str(oracle_path)}]}],
            "provider": provider, "budget": {"model_tokens_total": 200000, "model_requests": 12}}
    spec.update(over)
    return spec


def _job(operation="units.convert", input_path="data/series.json", expected=None, output_path=OUTPUT_PATH, parameters=None, rationale="convert to kelvin"):
    return {"kind": "text", "value": {"operation": operation, "input_path": input_path, "expected_sha256": sha(SERIES_TEXT) if expected is None else expected,
                                      "output_path": output_path, "parameters": {"to_units": "K"} if parameters is None else parameters, "rationale": rationale}}


def script(variant: str = "correct") -> dict:
    planner = [{"kind": "echo_reference"}]
    if variant == "correct":
        worker = [_job()]
    elif variant == "dimension_mismatch":
        worker = [_job(parameters={"to_units": "km"}, rationale="convert temperatures to kilometres")]
    elif variant == "unknown_operation":
        worker = [_job(operation="series.magic", parameters={}, rationale="use an undeclared operation")]
    elif variant == "out_of_scope_path":
        worker = [_job(output_path="data/series_kelvin.json", rationale="write next to the input")]
    elif variant == "wrong_input_kind":
        worker = [_job(input_path="data/graph.json", expected=sha(GRAPH_TEXT), rationale="convert the graph")]
    else:
        raise ValueError("unknown variant " + variant)
    return {"by_step": {"plan-request": planner, "propose": worker}, "by_role": {"planner": planner, "worker": worker}}
