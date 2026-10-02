#!/usr/bin/env python3
"""Independently verify archived phase-engine measurements and write tables.

No Rust build or timing is performed.  The benchmark's reproduce.py is neither
imported nor executed.  Run only after its executed/ directory is complete.
Regenerable target/ binaries are checked if present but need not be packaged.
All verification gates remain active under python -O.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import statistics
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "native_pse"
BENCH = NATIVE / "benchmark-results/phase_engine"
VARIANTS = ["indexed", "hoisted", "shared", "memoized"]
ENTITIES = [3, 5, 7, 8, 16]
WORKLOADS = ["repeated_path", "cold_acquisition"]
COUNTERS = ["hits", "misses", "bypasses", "evictions", "entries"]


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def object_without_duplicates(pairs):
    out = {}
    for key, value in pairs:
        require(key not in out, f"Duplicate JSON key: {key}")
        out[key] = value
    return out


def decode(raw):
    return json.loads(raw, object_pairs_hook=object_without_duplicates,
                      parse_constant=lambda value: (_ for _ in ()).throw(
                          RuntimeError("Nonstandard JSON number: " + value)))


def read(path):
    return decode(path.read_bytes())


def integer(value, label, minimum=0):
    require(type(value) is int and value >= minimum, f"Invalid integer {label}: {value!r}")
    return value


def close(actual, expected, label):
    require(type(actual) in (int, float) and math.isfinite(actual), f"Nonfinite {label}")
    require(math.isclose(actual, expected, rel_tol=2e-15, abs_tol=0.0),
            f"Numeric mismatch {label}: {actual!r} vs {expected!r}")


def current_sources():
    files = {NATIVE / "Cargo.toml", NATIVE / "Cargo.lock"}
    for base in [NATIVE / "crates", NATIVE / "src"]:
        files.update(path for path in base.rglob("*") if path.is_file()
                     and path.suffix in {".rs", ".toml", ".lock", ".bin"})
    files.update(BENCH / name for name in ["Cargo.toml", "Cargo.lock", "protocol.json",
                 "inputs.json", "freeze_inputs.py", "reproduce.py", "README.md"])
    files.update((BENCH / "src").rglob("*.rs"))
    return {str(path.relative_to(NATIVE)): digest(path.read_bytes()) for path in sorted(files)}


def protocol_checks(protocol, inputs):
    require(protocol["schema"] == 1 and protocol["toolchain"] == "1.95.0", "Unexpected protocol")
    require(protocol["variants"] == VARIANTS, "Variant sequence changed")
    engine = protocol["engine"]
    require(engine["entities"] == ENTITIES and engine["workloads"] == WORKLOADS, "Case grid changed")
    require(engine["inner_repetitions"] == 12 and engine["external_pairs"] == 5
            and engine["warmup_episodes_per_case"] == 1, "Sampling protocol changed")
    expected_comparisons = [("hoisted_vs_indexed", ["indexed", "hoisted"]),
                           ("shared_vs_hoisted", ["hoisted", "shared"]),
                           ("memoized_vs_shared", ["shared", "memoized"])]
    require(len(protocol["comparisons"]) == 3, "Comparison count changed")
    for comparison, (name, variants) in zip(protocol["comparisons"], expected_comparisons):
        require(comparison["name"] == name and comparison["variants"] == variants, "Comparison changed")
        require(comparison["orders"] == [variants if i % 2 == 0 else list(reversed(variants))
                                          for i in range(5)], "Alternating order changed")
    cases = inputs["cases"]
    require([(c["entities"], c["workload"]) for c in cases]
            == [(n, w) for n in ENTITIES for w in WORKLOADS], "Frozen input case grid changed")
    for case in cases:
        n, workload = case["entities"], case["workload"]
        require(len(case["measured"]) == (12 if workload == "repeated_path" else min(16, n * (n-1)//2)),
                "Measured interval changed")
        require(len(case["bootstrap"]) == (2*n-1 if workload == "repeated_path" else n),
                "Bootstrap interval changed")
    return {(c["entities"], c["workload"]): c for c in cases}


def verify_captures(executed, protocol, binary_records):
    aggregate_raw = (executed / "commands.json").read_bytes()
    aggregate, captures = decode(aggregate_raw), read(executed / "captured_records.json")
    names = ["compiler", "cargo"] + ["build_" + v for v in VARIANTS]
    names += ["configuration_" + v for v in VARIANTS] + ["golden_" + v for v in VARIANTS]
    engine_names = []
    for comparison in protocol["comparisons"]:
        for pair, order in enumerate(comparison["orders"]):
            engine_names.extend((f"engine_{comparison['name']}_{pair}_{variant}",
                                 comparison["name"], pair, variant) for variant in order)
    names += [item[0] for item in engine_names]
    require(len(captures) == len(names) == 44, "Missing/duplicate captured command")
    require([record["name"] for record in captures] == names, "Capture sequence changed")
    require({p.name for p in executed.glob("*.command.json")} == {n + ".command.json" for n in names},
            "Unexpected/missing per-command records")
    # The per-command records are original wrapper outputs and primary here.
    # The observed run retained all 44 originals but a 43-record aggregate.
    # Recognize only this exact missing-final-index condition; preserve the
    # original aggregate and disclose it rather than invent historical metadata.
    commands, indexed_records = [], []
    for name in names:
        filename = name + ".command.json"
        original = (executed / filename).read_bytes()
        command = decode(original)
        commands.append(command)
        indexed_records.append({"source_file": filename, "source_sha256": digest(original), "record": command})
    require(len(aggregate) in (43, 44) and aggregate == commands[:len(aggregate)],
            "Aggregate is neither complete nor the recognized exact prefix missing its final index entry")
    require(len({record["cwd"] for record in commands}) == 1
            and Path(commands[0]["cwd"]).name == "phase_engine", "Command working directory differs")
    provenance = {"original_individual_command_records": len(commands),
                  "original_aggregate_index_records": len(aggregate),
                  "original_aggregate_index_complete": len(aggregate) == len(commands),
                  "original_aggregate_index_is_exact_prefix": True,
                  "original_aggregate_index_sha256": digest(aggregate_raw),
                  "missing_aggregate_index_names": names[len(aggregate):],
                  "individual_command_records_complete": True,
                  "aggregate_incompleteness_cause": "Undetermined" if len(aggregate) != len(commands) else None,
                  "original_aggregate_index_modified_by_reporter": False}
    raw_by_name = {}
    for name, command, capture in zip(names, commands, captures):
        require(read(executed / (name + ".command.json")) == command, "Redundant command differs: " + name)
        require(command["returncode"] == 0 and command["failure"] is None, "Command failed: " + name)
        require(command["wrapper_wall_is_benchmark_metric"] is False, "Wrapper time used as metric")
        require(math.isfinite(command["wrapper_wall_seconds"]) and command["wrapper_wall_seconds"] >= 0,
                "Invalid wrapper interval")
        for stream in ["stdout", "stderr"]:
            filename = name + "." + stream
            require(command[stream] == filename, "Capture path mismatch")
            raw = (executed / filename).read_bytes()
            original = base64.b64decode(capture[stream + "_base64"], validate=True)
            require(raw == original, "Redundant capture bytes differ: " + filename)
            require(digest(raw) == command[stream + "_sha256"] == capture[stream + "_sha256"],
                    "Capture hash mismatch: " + filename)
            require(len(raw) == command[stream + "_bytes"], "Capture size mismatch: " + filename)
            if stream == "stdout":
                require(bool(raw) or name.startswith("build_"), "Required stdout empty: " + name)
                raw_by_name[name] = raw
        argv = command["command"]
        if name == "compiler":
            require(argv == ["rustc", "--version", "--verbose"], "Compiler command differs")
            require(raw_by_name[name].startswith(b"rustc 1.95.0 "), "Compiler version differs")
        elif name == "cargo":
            require(argv == ["cargo", "--version", "--verbose"], "Cargo command differs")
        elif name.startswith("build_"):
            variant = name.removeprefix("build_")
            expected = ["cargo", "build", "--locked", "--release", "--jobs", str(protocol["build_jobs"]),
                        "--manifest-path", str(Path(command["cwd"]) / "Cargo.toml"), "--target-dir",
                        str(Path(binary_records[variant]["path"]).parents[1] / "build"),
                        "--features", ",".join(protocol["features"][variant])]
            require(argv == expected, "Build command differs: " + name)
        else:
            variant = next((v for v in VARIANTS if name.endswith("_" + v)), None)
            mode = "engine" if name.startswith("engine_") else name.split("_", 1)[0]
            require(argv == [binary_records[variant]["path"], mode], "Executable command differs: " + name)
    derived_index = {"schema": 1,
                     "status": "DERIVED index of original individually captured command records; not a historical wrapper output",
                     "provenance": provenance, "commands": indexed_records}
    return raw_by_name, engine_names, provenance, derived_index


def verify_equal_outputs(executed, raw, prefix):
    records = {v: raw[prefix + "_" + v] for v in VARIANTS}
    require(len(set(records.values())) == 1, "Four-way " + prefix + " bytes differ")
    calculated = {"bytes_identical": True, "bytes": {v: len(b) for v, b in records.items()},
                  "sha256": {v: digest(b) for v, b in records.items()}}
    require(read(executed / (prefix + "_comparison.json")) == calculated, "Comparison record differs")
    if prefix == "configuration":
        require((executed / "configuration.json").read_bytes() == records["indexed"], "Configuration bytes differ")
    return calculated


def verify_golden(golden, cases):
    require(golden["schema"] == 1 and len(golden["cases"]) == len(cases), "Golden schema/count differs")
    diagnostics, total_traces = [], 0
    for row, fixture in zip(golden["cases"], cases.values()):
        n, workload = fixture["entities"], fixture["workload"]
        require((row["entities"], row["workload"]) == (n, workload), "Golden case order differs")
        expected = [("bootstrap", s) for s in fixture["bootstrap"]] + [("measured", s) for s in fixture["measured"]]
        require(len(row["traces"]) == len(expected), "Golden trace count differs")
        keys, measured, entity_ids, expected_edges = [], [], {}, set()
        for tick, (trace, (stage, step)) in enumerate(zip(row["traces"], expected), 1):
            total_traces += 1
            crystal, topology, state = trace["crystal"], trace["topology"], trace["state"]
            size, edge_count = step["vertices"], step["edges"]
            require(trace["stage"] == stage and trace["commits"] == state["tick"] == tick, "Golden commit count differs")
            require(len(state["archive"]) == tick and state["archive"][-1] == crystal, "Golden archive/crystal differs")
            nodes, edges = state["graph"]["nodes"], state["graph"]["edges"]
            ids = [node[0] for node in nodes]
            require(len(ids) == len(set(ids)) == size and len(edges) == edge_count, "Snapshot graph size differs")
            require(topology["n"] == topology["vertices"] == size and topology["edges"] == edge_count,
                    "Topology size differs")
            region = crystal["region"]
            require(len(region) == size and set(region) == set(ids) and topology["region"] == region,
                    "Full induced region differs")
            payload_entities = [decode(payload)["entity"] for payload in step["batch"]]
            if len(payload_entities) == 1:
                unseen = set(ids) - set(entity_ids.values())
                require(len(unseen) == 1 and payload_entities[0] not in entity_ids, "Singleton insertion differs")
                entity_ids[payload_entities[0]] = unseen.pop()
            else:
                require(len(payload_entities) == 2 and all(e in entity_ids for e in payload_entities), "Pair input differs")
                expected_edges.add(frozenset(entity_ids[e] for e in payload_entities))
            actual_edges = set()
            for edge in edges:
                left, right = edge[:2]
                require(type(left) is int and type(right) is int and 0 <= left < size and 0 <= right < size
                        and left != right, "Invalid snapshot edge indices")
                actual_edges.add(frozenset([ids[left], ids[right]]))
            require(actual_edges == expected_edges and len(actual_edges) == edge_count,
                    "Observed graph differs from public pair inputs")
            expected_bits = "".join("1" if frozenset([region[i], region[j]]) in actual_edges else "0"
                                    for j in range(1, size) for i in range(j))
            require(topology["labelled_upper_bits_lsb_first"] == expected_bits, "Induced bits differ from snapshot")
            if size <= 7:
                word = sum(int(bit) << i for i, bit in enumerate(expected_bits))
                signature = crystal.get("metatron_signature")
                require(topology["labelled_word"] == word and signature is not None
                        and signature["n"] == size and signature["m"] == edge_count, "Eligible signature differs")
                keys.append([size, word])
                if stage == "measured":
                    measured.append([size, word])
            else:
                require(topology["labelled_word"] is None and crystal.get("metatron_signature") is None,
                        "Ineligible signature present")
        distinct = lambda values: len({tuple(value) for value in values})
        if n <= 7:
            require(distinct(measured) == (1 if workload == "repeated_path" else len(fixture["measured"])),
                    "Observed labelled-key regime differs")
        diagnostics.append({"entities": n, "workload": workload,
                            "bootstrap_ticks": len(fixture["bootstrap"]), "measured_ticks": len(fixture["measured"]),
                            "all_eligible_labelled_keys": keys, "measured_eligible_labelled_keys": measured,
                            "distinct_all_eligible_keys": distinct(keys), "distinct_measured_eligible_keys": distinct(measured),
                            "measured_edge_counts": [s["edges"] for s in fixture["measured"]]})
    return diagnostics, total_traces


def cache_check(row, variant, expected_cold_entries):
    before, after = row["memo_cache_before"], row["memo_cache_after"]
    if variant != "memoized":
        require(before is None and after is None, "Cache counters present in uncached variant")
        return None
    require(set(before) == set(after) == set(COUNTERS), "Cache counter fields differ")
    for counter in COUNTERS:
        integer(before[counter], "cache before " + counter)
        integer(after[counter], "cache after " + counter)
        require(after[counter] >= before[counter], "Cache counter decreased inside timed interval")
    require(after["entries"] <= 256, "Cache capacity exceeded")
    delta = {counter: after[counter] - before[counter] for counter in COUNTERS}
    require(delta["entries"] == delta["misses"] - delta["evictions"], "Cache occupancy accounting differs")
    require(delta["bypasses"] == 0, "Unexpected cache bypass")
    n, workload, ticks = row["entities"], row["workload"], row["ticks"]
    if n > 7:
        require(all(value == 0 for value in delta.values()), "Ineligible graph accessed memoizer")
    elif workload == "repeated_path":
        require(delta["hits"] == ticks and all(delta[c] == 0 for c in COUNTERS if c != "hits"),
                "Repeated path did not produce exclusively cache hits")
    else:
        require(all(value == 0 for value in before.values()), "Cold acquisition did not reset cache")
        require(delta["hits"] == 0 and delta["misses"] == ticks, "Cold acquisition did not produce exclusively misses")
        require(after["entries"] == expected_cold_entries[n]
                and after["evictions"] == ticks - expected_cold_entries[n],
                "Cold cache occupancy/evictions differ from independently computed labelled-key slots")
    return delta


def verify_runs(raw, engine_names, cases, archived, diagnostics):
    require(len(archived) == len(engine_names) == 30, "Engine process count differs")
    runs, cache_totals = [], {}
    # Independent integer calculation of the documented 256-slot mapping.
    # Full keys are distinct in each cold corpus, so every repeated slot evicts.
    expected_cold_entries = {}
    for diagnostic in diagnostics:
        if diagnostic["entities"] <= 7 and diagnostic["workload"] == "cold_acquisition":
            slots = set()
            for n, bits in diagnostic["measured_eligible_labelled_keys"]:
                mixed = ((bits | (n << 21)) * 0x9e3779b1) & 0xffffffff
                slots.add((mixed ^ (mixed >> 16)) & 255)
            expected_cold_entries[diagnostic["entities"]] = len(slots)
    for (name, comparison, pair, variant), stored in zip(engine_names, archived):
        result = decode(raw[name])
        reconstructed = {"comparison": comparison, "pair": pair, "variant": variant, "raw": result}
        require(stored == reconstructed, "Results do not match original engine stdout: " + name)
        require(result["schema"] == 1 and result["variant"] == variant, "Engine variant/schema differs")
        rows = result["measurements"]
        require(len(rows) == 120, "Individual sample count differs")
        sequence = [(repetition, n, workload) for repetition in range(12) for n, workload in cases]
        for row, expected in zip(rows, sequence):
            require((row["repetition"], row["entities"], row["workload"]) == expected, "Sample order/identity differs")
            case = cases[(row["entities"], row["workload"])]
            ticks = len(case["measured"])
            require(row["ticks"] == row["measured_commits"] == ticks, "Timed commit count differs")
            require(row["bootstrap_commits"] == len(case["bootstrap"]), "Bootstrap commit count differs")
            require(row["vertices"] == case["entities"] and row["edges"] == case["measured"][-1]["edges"],
                    "Measured final graph size differs")
            elapsed = integer(row["elapsed_ns"], "elapsed_ns", minimum=1)
            close(row["ns_per_tick"], elapsed / ticks, "ns_per_tick")
            close(row["ticks_per_s"], ticks * 1e9 / elapsed, "ticks_per_s")
            delta = cache_check(row, variant, expected_cold_entries)
            if delta is not None:
                key = (row["entities"], row["workload"])
                total = cache_totals.setdefault(key, {"entities": key[0], "workload": key[1], "samples": 0,
                                                       "timed_ticks": 0, **{c: 0 for c in COUNTERS}})
                total["samples"] += 1
                total["timed_ticks"] += ticks
                for counter in COUNTERS:
                    total[counter] += delta[counter]
        runs.append(reconstructed)
    return runs, list(cache_totals.values())


def independent_summary(protocol, runs):
    lookup = {(r["comparison"], r["pair"], r["variant"]): r["raw"]["measurements"] for r in runs}
    require(len(lookup) == len(runs), "Duplicate process identity")
    summaries = []
    for comparison in protocol["comparisons"]:
        reference, candidate = comparison["variants"]
        for n in ENTITIES:
            for workload in WORKLOADS:
                pairs = []
                for pair in range(5):
                    rates, latencies = {}, {}
                    for variant in [reference, candidate]:
                        samples = [m for m in lookup[(comparison["name"], pair, variant)]
                                   if (m["entities"], m["workload"]) == (n, workload)]
                        rates[variant] = statistics.median(m["ticks_per_s"] for m in samples)
                        latencies[variant] = statistics.median(m["ns_per_tick"] for m in samples)
                    pairs.append({"pair": pair, "median_ticks_per_s": rates,
                                  "median_ns_per_tick": latencies, "ratio": rates[candidate] / rates[reference]})
                ratios = [pair["ratio"] for pair in pairs]
                summaries.append({"comparison": comparison["name"], "entities": n, "workload": workload,
                                  "pairs": pairs, "median_paired_ratio": statistics.median(ratios),
                                  "min_paired_ratio": min(ratios), "max_paired_ratio": max(ratios)})
    require(len(summaries) == 30, "Summary row count differs")
    return summaries


def latex_tables(summary):
    lookup = {(r["comparison"], r["entities"], r["workload"]): r for r in summary}
    lines = []
    for workload, label in [("repeated_path", "Repeated sparse path"), ("cold_acquisition", "Cold edge acquisition")]:
        lines.extend([r"\begin{table}[H]\centering\small",
                      r"\caption{" + label + r": complete native macrostep throughput. Entries are median paired candidate/reference ratios with observed minimum and maximum over five alternating process pairs. Each process contains 12 fresh-engine episodes per case. Indexed time is the median of the five per-process median times in the first comparison; it is descriptive, not the denominator of every ratio.}",
                      r"\label{tab:phase" + workload.replace("_", "") + "}",
                      r"\resizebox{\textwidth}{!}{\begin{tabular}{rrrrr}\toprule",
                      r"$n$ & Indexed ($\mu$s/tick) & Hoisted / indexed & Shared / hoisted & Memoized / shared \\\midrule"])
        for n in ENTITIES:
            first = lookup[("hoisted_vs_indexed", n, workload)]
            baseline_us = statistics.median(p["median_ns_per_tick"]["indexed"] for p in first["pairs"]) / 1000
            cells = []
            for comparison in ["hoisted_vs_indexed", "shared_vs_hoisted", "memoized_vs_shared"]:
                row = lookup[(comparison, n, workload)]
                cells.append(r"$%.3f\,[%.3f,\,%.3f]$" % tuple(row[key] for key in
                             ["median_paired_ratio", "min_paired_ratio", "max_paired_ratio"]))
            lines.append(f"{n} & {baseline_us:.3f} & " + " & ".join(cells) + r" \\")
        lines.extend([r"\bottomrule\end{tabular}}", r"\end{table}", ""])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executed", type=Path, default=BENCH / "executed")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "results")
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    executed = args.executed.resolve()
    protocol, inputs = read(BENCH / "protocol.json"), read(BENCH / "inputs.json")
    cases = protocol_checks(protocol, inputs)
    guards = [read(executed / name) for name in ["source_hashes_before.json", "source_hashes_before_timing.json", "source_hashes_after.json"]]
    current = current_sources()
    require(guards[0] == guards[1] == guards[2], "Sources changed during historical measurement")
    current_matches_measured = current == guards[0]
    measured_snapshot_verified = False
    if not current_matches_measured:
        # Later additive APIs/corrections do not turn old timings into new ones.
        # Verify the exact measured sources retained before those later edits.
        snapshot = ROOT / "audit/native_phase_measured_sources.zip"
        with zipfile.ZipFile(snapshot) as archive:
            require(archive.testzip() is None, "Corrupt measured-source snapshot")
            require(set(archive.namelist()) == set(guards[0]), "Measured-source inventory differs")
            for name, expected in guards[0].items():
                require(digest(archive.read(name)) == expected, "Measured-source snapshot differs: " + name)
        measured_snapshot_verified = True
    for name in ["Cargo.toml", "Cargo.lock", "protocol.json", "inputs.json", "freeze_inputs.py", "reproduce.py", "README.md"]:
        require((executed / ("frozen_" + name)).read_bytes() == (BENCH / name).read_bytes(), "Frozen file differs: " + name)
    for source in (BENCH / "src").glob("*.rs"):
        require((executed / ("frozen_" + source.name)).read_bytes() == source.read_bytes(), "Frozen harness differs")
    binaries = read(executed / "binaries.json")
    require(set(binaries) == set(VARIANTS), "Binary record variants differ")
    checked_binaries, absent_binaries = [], []
    for variant, record in binaries.items():
        require(len(record["sha256"]) == 64 and set(record["sha256"]) <= set("0123456789abcdef"), "Invalid executable hash")
        integer(record["bytes"], "executable bytes", minimum=1)
        local = executed / "target/binaries" / Path(record["path"]).name
        if local.is_file():
            require(local.stat().st_size == record["bytes"] and digest(local.read_bytes()) == record["sha256"], "Executable hash differs")
            checked_binaries.append(variant)
        else:
            absent_binaries.append(variant)
    raw, engine_names, command_provenance, derived_index = verify_captures(executed, protocol, binaries)
    configuration_comparison = verify_equal_outputs(executed, raw, "configuration")
    golden_comparison = verify_equal_outputs(executed, raw, "golden")
    diagnostics, traces = verify_golden(decode(raw["golden_indexed"]), cases)
    require(read(executed / "topology_diagnostics.json") == diagnostics, "Recomputed topology diagnostics differ")
    results = read(executed / "results.json")
    require(results["schema"] == 1 and all(results[key] is True for key in
            ["source_unchanged", "binary_unchanged", "all_capture_files_verified"]), "Wrapper acceptance flags absent")
    require(results["engine_golden"] == golden_comparison and results["topology_diagnostics"] == diagnostics,
            "Redundant results evidence differs")
    runs, cache_totals = verify_runs(raw, engine_names, cases, results["engine_runs"], diagnostics)
    summary = independent_summary(protocol, runs)
    require(summary == results["summary"] == read(executed / "summary.json"), "Independently recomputed summaries differ")
    environment = read(executed / "environment.json")
    require(environment["profile"] == protocol["profile"] and environment["effective_rustup_toolchain"] == "1.95.0"
            and environment["effective_cargo_build_jobs"] == str(protocol["build_jobs"]), "Recorded build environment differs")
    samples = [sample for run in runs for sample in run["raw"]["measurements"]]
    timed_ticks = sum(sample["ticks"] for sample in samples)
    bootstrap_ticks = sum(sample["bootstrap_commits"] for sample in samples)
    warmup_ticks = len(runs) * sum(len(c["bootstrap"]) + len(c["measured"]) for c in cases.values())
    evidence = {"schema": 1, "reporter": "Independent Python validator; benchmark wrapper not imported",
                "every_stdout_and_stderr_matches_original_base64_and_two_hash_records": True,
                "commands_verified": len(raw), "capture_streams_verified": 2*len(raw),
                "command_index_provenance": command_provenance,
                "source_before_before_timing_after_and_current_match": current_matches_measured,
                "historical_measured_sources_verified_in_snapshot": measured_snapshot_verified,
                "historical_source_guards_match": True,
                "guarded_source_files": len(guards[0]),
                "frozen_harness_protocol_inputs_verified": True, "four_way_configuration": configuration_comparison,
                "four_way_complete_crystal_and_selected_state_golden": golden_comparison,
                "actual_induced_graphs_independently_reconstructed_from_snapshot_and_public_inputs": True,
                "golden_traces_per_variant": traces, "golden_committed_ticks_all_variants": traces * len(VARIANTS),
                "engine_processes": len(runs), "individual_timed_episode_samples": len(samples),
                "summary_rows_independently_recomputed": len(summary), "external_pairs_per_row": 5,
                "episodes_per_process_per_case": 12, "timed_samples_per_summary_row": 120,
                "timed_committed_macrosteps": timed_ticks, "sampled_untimed_bootstrap_commits": bootstrap_ticks,
                "untimed_warmup_commits_derived_from_successful_harness_execution": warmup_ticks,
                "all_engine_commits_including_untimed_setup": timed_ticks + bootstrap_ticks + warmup_ticks,
                "all_captured_execution_commits_including_goldens": timed_ticks + bootstrap_ticks + warmup_ticks + traces*len(VARIANTS),
                "binary_hashes_checked_present": checked_binaries,
                "binary_artifacts_absent_regenerable_not_reverified": absent_binaries,
                "binary_preservation_scope": "Actual present files checked; archived hashes alone are not a new binary verification",
                "cache_accounting_all_individual_samples_verified": True, "memoized_cache_totals": cache_totals,
                "cold_cache_occupancy_and_evictions_recomputed_from_labelled_keys": True,
                "cache_entries_totals_are_sums_of_episode_deltas_not_global_residency": True,
                "no_build_or_benchmark_executed_by_reporter": True,
                "scope": protocol["scope"], "population_confidence_interval_claimed": False}
    require(len(samples) == 3600 and timed_ticks == 43560 and bootstrap_ticks == 40320
            and warmup_ticks == 6990 and traces == 233, "Unexpected total execution counts")
    if not args.check_only:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        for name, content in [("native_phase_tables.tex", latex_tables(summary)),
                              ("native_phase_command_index.json", json.dumps(derived_index, indent=2) + "\n"),
                              ("native_phase_reporting_checks.json", json.dumps(evidence, indent=2) + "\n"),
                              ("native_phase_summary.json", json.dumps(summary, indent=2) + "\n")]:
            (args.output_dir / name).write_text(content)
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
