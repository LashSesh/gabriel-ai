#!/usr/bin/env python3
"""Build and reproduce all frozen same-tree native benchmark comparisons.

Requires Rust/Cargo 1.95.0, Python 3.10+, and a linker. This default path builds
all three variants itself, compares exact golden bytes, then measures them.
Run native correctness tests before this command; do not compile other work
concurrently with its timing phase. --output must name a new directory.
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
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
NATIVE = HERE.parents[1]


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def sha256(value):
    return hashlib.sha256(value).hexdigest()


def source_hashes():
    files = {NATIVE / "Cargo.toml", NATIVE / "Cargo.lock"}
    for directory in [NATIVE / "crates", NATIVE / "src"]:
        files.update(p for p in directory.rglob("*") if p.is_file()
                     and p.suffix in {".rs", ".toml", ".lock", ".bin"})
    files.update(HERE / name for name in ["Cargo.toml", "Cargo.lock", "protocol.json",
                                         "inputs.json", "freeze_inputs.py", "reproduce.py"])
    files.update((HERE / "src").rglob("*.rs"))
    return {str(p.relative_to(NATIVE)): sha256(p.read_bytes()) for p in sorted(files)}


def execute(command, cwd, env, prefix, commands, timeout=1800):
    start = time.perf_counter()
    failure = None
    returncode = None
    with prefix.with_suffix(".stdout").open("wb") as out, prefix.with_suffix(".stderr").open("wb") as err:
        try:
            cp = subprocess.run(command, cwd=cwd, env=env, stdout=out, stderr=err, timeout=timeout)
            returncode = cp.returncode
        except (subprocess.TimeoutExpired, OSError) as error:
            failure = repr(error)
    record = {"command": command, "cwd": str(cwd), "returncode": returncode, "failure": failure,
              "wrapper_wall_seconds": time.perf_counter() - start,
              "wrapper_wall_is_benchmark_metric": False,
              "stdout": str(prefix.with_suffix(".stdout")),
              "stderr": str(prefix.with_suffix(".stderr"))}
    write_json(prefix.with_suffix(".command.json"), record)
    commands.append(record)
    write_json(prefix.parent / "commands.json", commands)
    if failure or returncode:
        raise RuntimeError(f"Command failed; inspect {prefix.with_suffix('.stderr')}")
    return prefix.with_suffix(".stdout").read_bytes()


def compare_golden(name, records, output):
    equal = len(set(records.values())) == 1
    result = {"bytes_identical": equal,
              "bytes": {v: len(raw) for v, raw in records.items()},
              "sha256": {v: sha256(raw) for v, raw in records.items()}}
    write_json(output / f"{name}_comparison.json", result)
    if not equal:
        raise RuntimeError(f"{name} mismatch; all timing halted")
    return result


def assert_engine_shape(raw, entities_list):
    result = json.loads(raw)
    assert [c["entities"] for c in result["cases"]] == entities_list
    for case in result["cases"]:
        n = case["entities"]
        assert len(case["traces"]) == 8
        for tick, trace in enumerate(case["traces"], 1):
            assert trace["commits"] == tick
            crystal = trace["crystal"]
            assert crystal is not None and len(crystal["region"]) == n
            signature = crystal.get("metatron_signature")
            assert (signature is not None and signature["n"] == n) if n <= 7 else signature is None


def ratio_summary(pairs):
    ratios = [p["ratio"] for p in pairs]
    return {"pairs": pairs, "median_paired_ratio": statistics.median(ratios),
            "min_paired_ratio": min(ratios), "max_paired_ratio": max(ratios)}


def summarize(protocol, engine_runs, first_runs, micro):
    summary = {"engine": [], "first_macrostep": [], "micro": []}
    for comparison in protocol["comparisons"]:
        name = comparison["name"]
        reference, candidate = comparison["variants"]
        for n in protocol["engine"]["entities"]:
            pairs = []
            for pair in range(5):
                rates = {}
                for variant in comparison["variants"]:
                    run = next(r for r in engine_runs if r["comparison"] == name and r["pair"] == pair and r["variant"] == variant)
                    rows = [m for m in run["raw"]["measurements"] if m["entities"] == n]
                    assert len(rows) == 25 and all(m["commits"] == 8 for m in rows)
                    rates[variant] = statistics.median(m["obs_per_s"] for m in rows)
                pairs.append({"pair": pair, "median_obs_per_s": rates, "ratio": rates[candidate] / rates[reference]})
            summary["engine"].append({"comparison": name, "entities": n, **ratio_summary(pairs)})
            pairs = []
            for pair in range(5):
                times = {}
                for variant in comparison["variants"]:
                    run = next(r for r in first_runs if r["comparison"] == name and r["pair"] == pair and r["variant"] == variant and r["raw"]["entities"] == n)
                    assert run["raw"]["commits"] == 1
                    times[variant] = run["raw"]["elapsed_ns"]
                pairs.append({"pair": pair, "elapsed_ns": times, "ratio": times[reference] / times[candidate]})
            summary["first_macrostep"].append({"comparison": name, "entities": n, **ratio_summary(pairs)})
        for n in protocol["micro"]["n"]:
            for workload in protocol["micro"]["workloads"]:
                if n not in protocol["micro"]["workload_n"][workload]:
                    continue
                pairs = []
                for pair in range(7):
                    times = {}
                    for variant in comparison["variants"]:
                        row = next(m for m in micro["measurements"] if m["comparison"] == name and m["n"] == n and m["workload"] == workload and m["pair"] == pair and m["variant"] == variant)
                        assert row["calls"] == 512
                        times[variant] = row["elapsed_ns"]
                    pairs.append({"pair": pair, "elapsed_ns": times, "ratio": times[reference] / times[candidate]})
                summary["micro"].append({"comparison": name, "n": n, "workload": workload, **ratio_summary(pairs)})
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New output directory; must not exist")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    protocol = json.loads((HERE / "protocol.json").read_text())
    for name in ["protocol.json", "inputs.json", "Cargo.toml", "Cargo.lock", "reproduce.py", "freeze_inputs.py"]:
        shutil.copy2(HERE / name, output / ("frozen_" + name))
    shutil.copy2(HERE / "src/main.rs", output / "frozen_main.rs")
    frozen = source_hashes()
    write_json(output / "source_hashes_before.json", frozen)
    env = os.environ.copy()
    removed = {key: env.pop(key) for key in list(env)
               if key.startswith("CARGO_PROFILE_") or key in {"RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS", "RUSTDOCFLAGS", "RUSTC_WRAPPER", "RUSTC_WORKSPACE_WRAPPER"}}
    env["RUSTUP_TOOLCHAIN"] = protocol["toolchain"]
    env["CARGO_BUILD_JOBS"] = str(protocol["build_jobs"])
    commands = []

    def run(command, prefix, timeout=1800):
        return execute(command, HERE, env, output / prefix, commands, timeout)

    compiler = run(["rustc", "--version", "--verbose"], "compiler")
    if not compiler.startswith(b"rustc 1.95.0 "):
        raise RuntimeError("Protocol requires Rust 1.95.0")
    run(["cargo", "--version", "--verbose"], "cargo")
    cpu_model = None
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.exists():
        cpu_model = next((line.partition(":")[2].strip() for line in cpuinfo.read_text().splitlines() if line.startswith("model name")), None)
    write_json(output / "environment.json", {
        "platform": platform.platform(), "python": platform.python_version(),
        "machine": platform.machine(), "logical_cpus": os.cpu_count(), "cpu_model": cpu_model,
        "affinity": sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None,
        "profile": protocol["profile"], "removed_build_override_names": sorted(removed),
        "effective_rustup_toolchain": env["RUSTUP_TOOLCHAIN"],
        "effective_cargo_build_jobs": env["CARGO_BUILD_JOBS"],
        "profile_rationale": protocol["profile_rationale"],
        "cargo_home": env.get("CARGO_HOME"), "rustup_home": env.get("RUSTUP_HOME"),
        "process_startup_is_timed": False, "cpu_and_rss_counters_measured": False,
    })
    binaries = {}
    target = output / "target" / "build"
    preserved = output / "target" / "binaries"
    preserved.mkdir(parents=True)
    for variant in protocol["variants"]:
        command = ["cargo", "build", "--locked", "--release", "--jobs", str(protocol["build_jobs"]), "--manifest-path", str(HERE / "Cargo.toml"), "--target-dir", str(target)]
        features = protocol["features"][variant]
        if features:
            command += ["--features", ",".join(features)]
        run(command, "build_" + variant)
        suffix = ".exe" if os.name == "nt" else ""
        built = target / "release" / ("pse-indexed-engine-benchmark" + suffix)
        binaries[variant] = preserved / (variant + suffix)
        shutil.copy2(built, binaries[variant])
        if sha256(built.read_bytes()) != sha256(binaries[variant].read_bytes()):
            raise RuntimeError(f"Preserved executable copy differs: {variant}")
        print(f"Built and preserved {variant}", flush=True)
    write_json(output / "binaries.json", {v: {"path": str(p), "sha256": sha256(p.read_bytes()), "bytes": p.stat().st_size} for v, p in binaries.items()})
    configs = {v: run([str(b), "configuration"], "configuration_" + v) for v, b in binaries.items()}
    compare_golden("configuration", configs, output)
    (output / "configuration.json").write_bytes(configs["packed"])
    engine_goldens = {v: run([str(b), "golden"], "golden_engine_" + v) for v, b in binaries.items()}
    engine_equality = compare_golden("golden_engine", engine_goldens, output)
    for raw in engine_goldens.values():
        assert_engine_shape(raw, protocol["engine"]["entities"])
    micro_binary = binaries["memoized"]
    micro_goldens = {v: run([str(micro_binary), "micro-golden", v], "golden_micro_" + v) for v in protocol["variants"]}
    micro_equality = compare_golden("golden_micro", micro_goldens, output)
    diagnostics = json.loads(run([str(micro_binary), "micro-diagnostics"], "micro_diagnostics"))
    before_timing = source_hashes()
    write_json(output / "source_hashes_before_timing.json", before_timing)
    if before_timing != frozen:
        raise RuntimeError("Source/input/protocol changed during setup; timing halted")
    print("Exact three-way engine and complete-signature golden bytes match; starting frozen timing sequence", flush=True)
    first_runs = []
    for comparison in protocol["comparisons"]:
        for pair, order in enumerate(comparison["first_orders"]):
            for n in protocol["first_macrostep"]["entities"]:
                for variant in order:
                    prefix = f"first_{comparison['name']}_{pair}_n{n}_{variant}"
                    raw = json.loads(run([str(binaries[variant]), "first", str(n)], prefix))
                    first_runs.append({"comparison": comparison["name"], "pair": pair, "variant": variant, "raw": raw})
        print(f"First macrostep pairs complete: {comparison['name']}", flush=True)
    engine_runs = []
    for comparison in protocol["comparisons"]:
        for pair, order in enumerate(comparison["engine_orders"]):
            for variant in order:
                prefix = f"engine_{comparison['name']}_{pair}_{variant}"
                raw = json.loads(run([str(binaries[variant]), "engine"], prefix))
                engine_runs.append({"comparison": comparison["name"], "pair": pair, "variant": variant, "raw": raw})
            print(f"Engine pair {pair+1}/5 complete: {comparison['name']}", flush=True)
    micro = json.loads(run([str(micro_binary), "micro"], "micro"))
    after = source_hashes()
    write_json(output / "source_hashes_after.json", after)
    write_json(output / "commands.json", commands)
    if after != frozen:
        raise RuntimeError("Source/input/protocol changed during measurement; results invalid")
    summary = summarize(protocol, engine_runs, first_runs, micro)
    write_json(output / "results.json", {
        "schema": 1, "source_unchanged": True, "engine_golden": engine_equality,
        "micro_golden": micro_equality, "micro_diagnostics": diagnostics, "engine_runs": engine_runs,
        "first_runs": first_runs, "micro_run": micro, "summary": summary,
    })
    write_json(output / "summary.json", summary)
    print(f"Complete: {output / 'summary.json'}", flush=True)


if __name__ == "__main__":
    main()
