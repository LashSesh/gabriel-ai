#!/usr/bin/env python3
"""Measure the native PSE graph worker (ADR-18) with the costs kept separate:

* cold start: the first native process after the executables were installed, then warm repeats;
* identity validation: the SHA-256 checks of the executables before and after every process;
* query time: the native process for the fixture query and for the declared caps (64 nodes,
  256 times, 128 batches);
* certificate time: the dedicated exact-arithmetic host process (stage two);
* total task latency through the owner per backend, with the job's own elapsed time, the
  worker's internal time and the stage times taken from the retained diagnostics.

Nothing here feeds back into a result: timings live in the evidence only. Usage:

    .venv/bin/python scripts/pse_measure.py --output evidence/pse/measurements.json [--backends trusted_local,linux_namespace] [--repeats 7]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gabriel_agent.adapters import native_graph  # noqa: E402
from gabriel_agent.agent import TaskRunner, Workspace  # noqa: E402
from gabriel_agent.contracts.codec import loads  # noqa: E402
from gabriel_agent.evaluation.fixtures import graph_walk as gw  # noqa: E402


def summary(samples_us: list) -> dict:
    values = sorted(int(v) for v in samples_us)
    return {"n": len(values), "min_us": values[0], "median_us": int(statistics.median(values)), "max_us": values[-1], "samples_us": values}


def native_process(binaries: dict, operation: str, dataset: dict, repeats: int) -> dict:
    """Stage one in-process (no worker start): identity validation and native process time separately."""
    raw = gw.text(dataset).encode("utf8")
    identity, native, first = [], [], None
    for index in range(repeats):
        result = native_graph.run_job(operation, {}, raw, binaries)
        assert result["verdict"] == "computed", result["diagnostics"]
        timings = result["diagnostics"]["timings"]
        if first is None:
            first = dict(timings)
        identity.append(timings["identity_validation_us"])
        native.append(timings["native_process_us"])
    return {"wire_bytes": first["wire_bytes"], "first_native_process_us": first["native_process_us"], "identity_validation": summary(identity), "native_process": summary(native)}


def certificate_process(repeats: int) -> dict:
    """Stage two: the dedicated host process over the fixture's clique snapshot."""
    binaries = native_graph.binaries()
    stage_one = native_graph.run_job("graph.window_reachability", {}, gw.WINDOW_TEXT.encode("utf8"), binaries)
    payload = json.dumps({"output": stage_one["output"]}).encode("utf8")
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
    samples, statuses = [], None
    for _ in range(repeats):
        clock = time.monotonic_ns()
        process = subprocess.run([sys.executable, "-m", "gabriel_agent.adapters.native_graph", "certify"], input=payload, capture_output=True, env=env, check=True)
        samples.append((time.monotonic_ns() - clock) // 1000)
        statuses = json.loads(process.stdout)["statuses"]
    in_process = []
    for _ in range(repeats):
        clock = time.monotonic_ns()
        native_graph.certify(stage_one["output"])
        in_process.append((time.monotonic_ns() - clock) // 1000)
    return {"statuses": statuses, "host_process": summary(samples), "arithmetic_only": summary(in_process)}


def through_owner(backend: str, repeats: int, operations: tuple) -> dict:
    """Total task latency per operation through the owner (observe, propose with the scripted
    provider, run the job in a fresh contained worker, read back, verify, review). Every repeat
    uses a fresh workspace, so every run is a fresh worker; the same task is then run once more in
    that workspace to measure a hit on the complete job key separately."""
    out = {}
    tmp = Path(tempfile.mkdtemp(prefix="pse-measure-"))
    try:
        repo = tmp / "repo"
        base = gw.build_repo(repo)
        for operation in operations:
            oracle = gw.write_oracle(tmp / ("oracle_%s.json" % operation), operation)
            task_wall, job_elapsed, worker_internal, stage_one, stage_two, verdicts, hit_wall, replays = [], [], [], [], [], [], [], []
            for index in range(repeats):
                ws = Workspace.create(tmp / ("ws-%s-%d" % (operation, index)), backend=backend, allow_trusted_local=(backend == "trusted_local"))
                try:
                    spec = gw.task_spec(repo, base, oracle, {"kind": "scripted", "script": gw.script(operation), "provider_id": "scripted-domains"}, operation)
                    created = ws.create_task(spec)
                    clock = time.monotonic_ns()
                    result = TaskRunner(ws, created["task_id"]).run()
                    task_wall.append((time.monotonic_ns() - clock) // 1000)
                    node = ws.owner.projection(created["run_id"])["nodes"]["run-job"]
                    job = loads(ws.store.get(node["outputs"]["job_result"]))
                    assert not job["cache"]["hit"]
                    diagnostics = json.loads(ws.store.get(job["diagnostics_ref"]).decode("utf8"))
                    verdicts.append((result["state"], job["verdict"], job["containment"]))
                    job_elapsed.append(job["elapsed_ms"] * 1000)
                    worker_internal.append(diagnostics["worker"]["worker_us"])
                    stage_one.append(diagnostics["stage_one_us"])
                    if diagnostics.get("stage_two"):
                        stage_two.append(diagnostics["stage_two"]["elapsed_us"])
                    # the same job again in the same workspace: a hit on the complete job key re-issues the retained result and witness
                    created = ws.create_task(spec)
                    clock = time.monotonic_ns()
                    result = TaskRunner(ws, created["task_id"]).run()
                    hit_wall.append((time.monotonic_ns() - clock) // 1000)
                    node = ws.owner.projection(created["run_id"])["nodes"]["run-job"]
                    job = loads(ws.store.get(node["outputs"]["job_result"]))
                    assert result["state"] == "succeeded" and job["cache"]["hit"], (result["state"], job["cache"])
                    replays.append(ws.owner.replay()["status"])
                finally:
                    ws.close()
            out[operation] = {"outcomes": sorted(set(verdicts)), "task_wall": summary(task_wall), "job_elapsed": summary(job_elapsed),
                              "stage_one_worker_process": summary(stage_one), "worker_internal": summary(worker_internal),
                              "stage_two_certificate_process": summary(stage_two) if stage_two else None,
                              "cache_hit_task_wall": summary(hit_wall), "replays": sorted(set(replays))}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--backends", default="trusted_local")
    parser.add_argument("--repeats", type=int, default=7)
    args = parser.parse_args()
    binaries = native_graph.binaries()
    if set(binaries) != set(native_graph.BINARIES):
        print("native executables not built", file=sys.stderr)
        return 2
    build_identity = json.loads((ROOT / "evidence" / "pse" / "build_identity.json").read_text())
    record = {"schema": "gabriel.evidence.pse-measurements/1", "platform": platform.platform(), "machine": platform.machine(), "python": platform.python_version(),
              "cpu_count": os.cpu_count(), "repeats": args.repeats, "profile": native_graph.PROFILE_ID, "model": native_graph.MODEL,
              "executables": {name: {"sha256": entry["sha256"], "bytes": entry["bytes"]} for name, entry in sorted(binaries.items())},
              "build_matches_recorded_identity": binaries["engine_observer"]["sha256"] == build_identity["engine_observer_sha256"],
              "worker_build": native_graph.worker_build(binaries), "worker_source_sha256": hashlib.sha256(Path(native_graph.__file__).read_bytes()).hexdigest(),
              "notes": ["timings are wall-clock microseconds on a shared cloud container: evidence of magnitude, not a benchmark",
                        "identity validation hashes both executables (about 2.6 MiB) before and after each native process",
                        "cold start is the first native process in this measurement session; warm repeats follow in the same process",
                        "task latency includes observe, scripted propose, the fresh contained worker, read-back, verification and review through the owner"]}
    # cold start: copy the executables to a fresh directory so the first process starts from newly written files
    staging = Path(tempfile.mkdtemp(prefix="pse-cold-"))
    try:
        cold = {}
        for name, entry in binaries.items():
            target = staging / name
            target.write_bytes(Path(entry["path"]).read_bytes())
            target.chmod(0o755)
            cold[name] = {"path": str(target), "sha256": entry["sha256"]}
        record["cold_start"] = {"region_mass_first_process_us": native_graph.run_job("graph.region_mass", {}, gw.QUERY_TEXT.encode("utf8"), cold)["diagnostics"]["timings"]["native_process_us"],
                                "snapshot_first_process_us": native_graph.run_job("graph.window_reachability", {}, gw.WINDOW_TEXT.encode("utf8"), cold)["diagnostics"]["timings"]["native_process_us"]}
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    full = list(range(64))
    record["native"] = {
        "region_mass_fixture": native_process(binaries, "graph.region_mass", gw.query_dataset(), args.repeats),
        "snapshot_fixture": native_process(binaries, "graph.snapshot", gw.batches_dataset(), args.repeats),
        "exact_snapshot_fixture": native_process(binaries, "graph.window_reachability", gw.window_dataset(), args.repeats),
        "region_mass_caps_64_nodes_256_times": native_process(binaries, "graph.region_mass", gw.query_dataset(
            batches=[full], source=[(e, 1.0 if e == 0 else 0.0, 0.0) for e in full], targets=[63], times=[0.01 * k for k in range(256)]), args.repeats),
        "region_mass_caps_128_batches": native_process(binaries, "graph.region_mass", gw.query_dataset(
            batches=[[k % 64, (k + 1) % 64, (k + 2) % 64] for k in range(128)], source=[(e, 1.0 if e == 0 else 0.0, 0.0) for e in full], targets=[63], times=[1.0]), args.repeats),
        "spectral_full_caps_64_nodes_256_times": native_process(binaries, "graph.region_mass", gw.query_dataset(
            batches=[full], backend="spectral_full", source=[(e, 1.0 if e == 0 else 0.0, 0.0) for e in full], targets=[63], times=[0.01 * k for k in range(256)]), args.repeats)}
    record["certificate"] = certificate_process(args.repeats)
    record["through_owner"] = {}
    for backend in [b for b in args.backends.split(",") if b]:
        record["through_owner"][backend] = through_owner(backend, args.repeats, ("graph.snapshot", "graph.region_mass", "graph.window_reachability"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, indent=1, sort_keys=True) + "\n")
    print(json.dumps({k: v for k, v in record.items() if k in ("cold_start", "build_matches_recorded_identity")}, indent=1))
    for name, entry in record["native"].items():
        print("%-42s identity %6d us  native %6d us (first %6d us)  wire %d B" % (name, entry["identity_validation"]["median_us"], entry["native_process"]["median_us"], entry["first_native_process_us"], entry["wire_bytes"]))
    print("certificate host process median %d us (arithmetic only %d us) statuses %s" % (record["certificate"]["host_process"]["median_us"], record["certificate"]["arithmetic_only"]["median_us"], record["certificate"]["statuses"]))
    for backend, entries in record["through_owner"].items():
        for operation, entry in entries.items():
            print("%-16s %-26s task %7d us  job %7d us  stage one %7d us  worker %6d us  stage two %s  hit %7d us  %s %s" % (
                backend, operation, entry["task_wall"]["median_us"], entry["job_elapsed"]["median_us"], entry["stage_one_worker_process"]["median_us"],
                entry["worker_internal"]["median_us"], entry["stage_two_certificate_process"]["median_us"] if entry["stage_two_certificate_process"] else "-",
                entry["cache_hit_task_wall"]["median_us"], entry["outcomes"], entry["replays"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
