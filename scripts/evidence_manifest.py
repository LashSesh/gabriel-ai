#!/usr/bin/env python3
"""Regenerate the machine-readable evidence manifests from the recorded pytest log.

Usage:
    GABRIEL_CONTAINMENT_TESTS=1 .venv/bin/python -m pytest tests -vv -rs | tee evidence/test_results.txt
    scripts/evidence_manifest.py

Writes ``evidence/test_run.json`` (counts, per-module results, source and test digests) and
``evidence/work_packages.json`` (per work package: status, tests, evidence files, acceptance
cases, what was not executed, and the recorded result of every test the package names).
A package counts as done only with actual code and recorded test output; privileged and paid
runs are listed under ``not_executed`` when they did not run.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "evidence" / "test_results.txt"
COMMAND = "GABRIEL_CONTAINMENT_TESTS=1 .venv/bin/python -m pytest tests -vv -rs"
RESULT_LINE = re.compile(r"^(tests/[^\s:]+\.py)::(\S+) (PASSED|FAILED|SKIPPED|ERROR|XFAIL|XPASS)\b")

PACKAGES = {
    "WP01": {"status": "DONE", "tests": [], "acceptance": ["AT01"],
             "evidence": ["evidence/wp01/baseline_manifest.json", "evidence/wp01/legacy_check_runtime.log", "evidence/wp01/legacy_runtime_checks_rerun.json"]},
    "WP02": {"status": "DONE", "tests": ["tests/test_contracts.py"], "evidence": ["evidence/wp02/spec_validation.json"],
             "acceptance": ["AT02", "AT19(representation)", "AT20(representation)", "AT21(representation)"]},
    "WP03": {"status": "DONE", "tests": ["tests/test_artifacts.py", "tests/test_owner.py"], "evidence": [], "acceptance": ["AT03", "AT04", "AT05", "AT18(partial)"]},
    "WP04": {"status": "DONE", "tests": ["tests/test_policy.py", "tests/test_owner.py"], "evidence": [], "acceptance": ["AT06", "AT07"]},
    "WP05": {"status": "DONE", "tests": ["tests/test_workers.py"], "acceptance": ["AT08", "AT12", "AT13", "AT24"], "not_executed": [],
             "evidence": ["evidence/doctor_linux_namespace_selftest.json", "evidence/test_results.txt (test_namespace_jail_isolation_selftest PASSED)"]},
    "WP06": {"status": "DONE", "tests": ["tests/test_models.py"], "evidence": ["evidence/live/summary.json"], "acceptance": ["AT09"], "not_executed": []},
    "WP07": {"status": "DONE", "tests": ["tests/test_kernel.py", "tests/test_scheduler.py", "tests/test_owner.py", "tests/test_workers.py"], "evidence": [],
             "acceptance": ["AT10", "AT12", "AT13", "AT20", "AT22"]},
    "WP08": {"status": "DONE", "tests": ["tests/test_slice.py"], "evidence": ["evidence/live/summary.json", "evidence/test_results.txt"],
             "acceptance": ["AT11", "AT19", "AT22", "AT24"], "not_executed": []},
    "WP11": {"status": "DONE_EXECUTED_ADVANTAGE_NOT_SHOWN", "tests": ["tests/test_evaluation.py"], "acceptance": ["AT17"],
             "evidence": ["evidence/wp11/protocol.frozen.json", "evidence/wp11/run-gpt-4.1-mini/report.md",
                          "evidence/wp11/protocol2.frozen.json", "evidence/wp11/run2-gpt-4.1-mini/report.md",
                          "evidence/wp11/protocol3.frozen.json", "evidence/wp11/run3-gpt-4.1-mini/report.md",
                          "evidence/wp11/*/final_diffs/index.json", "docs/EVALUATION_PROTOCOL.md"],
             "not_executed": []},
    "WP09": {"status": "DONE", "tests": ["tests/test_memory.py"], "acceptance": ["AT14", "AT15", "AT22(memory)", "AT25"],
             "evidence": ["evidence/test_results.txt", "evidence/wp10/at23/summary.json (memory chain check)", "docs/adr/ADR-14-memory-chain.md"],
             "not_executed": ["policy adaptation beyond the promotion rule (the G3 route trained no router or retrieval policy; see G3-route)"]},
    "WP10": {"status": "DONE", "tests": ["tests/test_domains.py"], "acceptance": ["AT16", "AT23"],
             "evidence": ["evidence/wp10/at23/summary.json", "evidence/wp10/at23/report.md", "docs/adr/ADR-13-domain-pack-ports.md"],
             "not_executed": ["native PSE worker (optional; the analytical adapter is the stdlib worker)",
                              "recurrent routing feature experiment in the document and numerical packs (executed in the software pack only; see G3-route)"]},
    "G3-route": {"status": "DONE_EXECUTED_NOT_ESTABLISHED", "tests": ["tests/test_policy_route.py", "tests/test_evaluation.py"], "acceptance": ["AT17(hard tier)", "AT25(promotion)"],
                 "evidence": ["evidence/wp13/protocol4a-train.frozen.json", "evidence/wp13/run4a-train/report.md", "evidence/wp13/policies/metrics.json",
                              "evidence/wp13/protocol4b-eval.frozen.json", "evidence/wp13/run4b-eval/report.md", "evidence/wp13/promotion/promotion.json",
                              "evidence/wp13/*/final_diffs/index.json", "docs/RELEASE_G3.md", "docs/adr/ADR-15-readout-router.md"],
                 "not_executed": ["readout training on real task outcomes (no failed verification in 54 training runs, so no labeled decision of either class)",
                                  "evaluation of a readout policy in protocol 4b (no candidate existed)",
                                  "weight training (outside G1-G3 by the blueprint)", "native PSE worker"]},
    "WP12": {"status": "DONE", "tests": ["tests/test_release.py"], "acceptance": ["AT18"],
             "evidence": ["evidence/wp12/smoke_linux_namespace.log", "evidence/wp12/release_manifest_smoke.json",
                          "evidence/wp12/smoke_restore_report.json", "LICENSE", "docs/RELEASE_G1.md"],
             "not_executed": []},
}

RELEASE_SCOPE_G2 = {
    "established_on_this_host": True,
    "evidence": ["evidence/wp10/at23/summary.json", "evidence/wp10/at23/report.md", "evidence/test_results.txt"],
    "scope": "one owner/scheduler/policy build served repository repair, source-grounded document amendment and numerical transformation "
             "(fixture tasks, real provider for the valid tasks, scripted invalid and out-of-scope controls) with registered domain observers, "
             "independent oracles and recorded replay; the analytical worker is the standard-library adapter, native PSE remains optional and unbuilt",
}

RELEASE_SCOPE_G3 = {
    "established_on_this_host": False,
    "evidence": ["evidence/wp13/run4b-eval/report.md", "evidence/wp13/promotion/promotion.json", "evidence/wp13/policies/metrics.json"],
    "scope": "not established: the routing feature experiment ran under frozen protocols on the hard tier (54 training runs with two providers, "
             "72 evaluation runs with gpt-4.1-mini, stateful family held out) but no first patch failed verification, so no labeled router "
             "decision exists and no readout candidate could be trained or evaluated; the episodic-retrieval ablation reached equal verified "
             "success on the held-out family with no false completion at 68 percent more model tokens and failed its declared criterion; "
             "the rule-based policy without episodes remains the pinned default",
}

RELEASE_SCOPE_G1 = {
    "established_on_this_host": True,
    "evidence": ["evidence/live/summary.json", "evidence/doctor_linux_namespace_selftest.json", "evidence/test_results.txt",
                 "evidence/wp01/baseline_manifest.json", "evidence/wp02/spec_validation.json",
                 "evidence/wp11/run3-gpt-4.1-mini/report.md", "evidence/wp12/release_manifest_smoke.json"],
    "scope": "single host (Linux 6.18 x86_64, uid 0, util-linux unshare/setpriv), one real provider (gpt-4.1-mini), "
             "fifteen synthetic repository-repair tasks in five families; AT17 executed under three frozen protocols without "
             "an established advantage over the simple verification loop; AT18 restore bundle executed; Apache-2.0 root license",
}


def _sha256_map(pattern: str) -> dict:
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(ROOT.glob(pattern)) if p.is_file() and "__pycache__" not in p.parts}


def parse_log(text: str) -> tuple[dict, dict]:
    by_module, meta = {}, {"summary_line": None, "skipped": [], "counts": {}}
    for line in text.splitlines():
        match = RESULT_LINE.match(line)
        if match:
            by_module.setdefault(match.group(1), []).append({"test": match.group(2), "result": match.group(3)})
        elif line.startswith("SKIPPED ["):
            meta["skipped"].append(line.strip())
        elif line.startswith("=") and (" passed" in line or " failed" in line or " error" in line):
            meta["summary_line"] = line.strip()
    if meta["summary_line"]:
        for count, word in re.findall(r"(\d+) (passed|failed|skipped|error|errors|xfailed|xpassed)", meta["summary_line"]):
            meta["counts"][word] = int(count)
    return by_module, meta


def main() -> int:
    if not LOG.is_file():
        sys.stderr.write("missing %s; run the test command first\n" % LOG)
        return 2
    by_module, meta = parse_log(LOG.read_text())
    test_run = {"schema": "gabriel.evidence.tests/1", "command": COMMAND, "log": "evidence/test_results.txt",
                "summary_line": meta["summary_line"], "counts": meta["counts"], "skipped": meta["skipped"],
                "test_sha256": _sha256_map("tests/*.py"), "results_by_module": by_module,
                "source_sha256": _sha256_map("src/gabriel_agent/**/*.py")}
    (ROOT / "evidence" / "test_run.json").write_text(json.dumps(test_run, indent=1) + "\n")
    packages = {}
    for wp, static in PACKAGES.items():
        entry = dict(static)
        entry["test_results"] = {module: by_module.get(module, []) for module in static["tests"]}
        packages[wp] = entry
    work = {"schema": "gabriel.evidence.work-packages/1", "produced_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "rule": "A package counts as done only with actual code and recorded test output; privileged and paid runs are listed under not_executed.",
            "packages": packages, "release_scope_G1": RELEASE_SCOPE_G1, "release_scope_G2": RELEASE_SCOPE_G2, "release_scope_G3": RELEASE_SCOPE_G3}
    (ROOT / "evidence" / "work_packages.json").write_text(json.dumps(work, indent=2) + "\n")
    failed = [t for tests in by_module.values() for t in tests if t["result"] in ("FAILED", "ERROR")]
    print("test_run.json: %s; work_packages.json: %d packages; failed tests: %d" % (meta["summary_line"], len(packages), len(failed)))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
