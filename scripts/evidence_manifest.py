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
             "not_executed": ["native PSE worker at the time of WP10 (built and integrated afterwards; see PSE)",
                              "recurrent routing feature experiment in the document and numerical packs (executed in the software pack only; see G3-route)"]},
    "G3-route": {"status": "DONE_EXECUTED_NOT_ESTABLISHED_BY_PROTOCOL_4_SEE_P8", "tests": ["tests/test_policy_route.py", "tests/test_evaluation.py"], "acceptance": ["AT17(hard tier)", "AT25(promotion)"],
                 "evidence": ["evidence/wp13/protocol4a-train.frozen.json", "evidence/wp13/run4a-train/report.md", "evidence/wp13/policies/metrics.json",
                              "evidence/wp13/protocol4b-eval.frozen.json", "evidence/wp13/run4b-eval/report.md", "evidence/wp13/promotion/promotion.json",
                              "evidence/wp13/*/final_diffs/index.json", "docs/RELEASE_G3.md", "docs/adr/ADR-15-readout-router.md"],
                 "not_executed": ["readout training on real task outcomes (no failed verification in 54 training runs, so no labeled decision of either class)",
                                  "evaluation of a readout policy in protocol 4b (no candidate existed)",
                                  "weight training (outside G1-G3 by the blueprint)", "native PSE worker in the routing experiment (integrated afterwards; see PSE)"]},
    "P5-advantage": {"status": "DONE_EXECUTED_ADVANTAGE_NOT_SHOWN", "tests": ["tests/test_evaluation_domains.py", "tests/test_evaluation.py"],
                     "acceptance": ["AT17(document and numerical families)"],
                     "evidence": ["evidence/wp14/pilot_declaration.md", "evidence/wp14/pilot1.frozen.json", "evidence/wp14/pilot1-run/report.md",
                                  "evidence/wp14/pilot2.frozen.json", "evidence/wp14/pilot2-run/report.md", "evidence/wp14/protocol5.frozen.json",
                                  "evidence/wp14/run5/report.md", "evidence/wp14/*/final_diffs/index.json", "docs/EVALUATION_PROTOCOL.md",
                                  "docs/adr/ADR-16-advantage-gate-document-numerical.md"],
                     "not_executed": ["a second provider", "a real-world document or numerical corpus",
                                      "native analytical worker ablation (the worker was integrated after protocol 5; the graph tier is in no frozen protocol)"]},
    "PSE": {"status": "DONE", "tests": ["tests/test_native_pse.py"], "acceptance": ["blueprint: native PSE and analytical worker contracts", "AT16(native worker)"],
            "evidence": ["evidence/pse/build_identity.json", "evidence/pse/equivalence_fresh_vs_shipped.json", "evidence/pse/functional_fresh_build/results.json",
                         "evidence/pse/measurements.json", "evidence/pse/graph_tier_check.json", "docs/adr/ADR-18-native-pse-graph-worker.md", "evidence/test_results.txt",
                         "evidence/pse/determinism/summary.json", "evidence/pse/determinism/linux_trace_platform_libm.json", "evidence/pse/determinism/linux_trace_pure_libm.json",
                         "evidence/pse/determinism/linux_trace_pure_libm_sin_plus_one_ulp.json", "evidence/pse/determinism/observer_pure_libm_vs_retained.json",
                         "native_pse/tests/fixtures/pure_libm.json", "docs/adr/ADR-19-native-pse-determinism-and-readout.md"],
            "not_executed": ["a provider-driven run of the graph tier (deterministic computations a model cannot perform itself; no frozen protocol includes the tier)",
                             "exact certificates outside the uniform-clique profile (declared out_of_scope by the vendored certificate)",
                             "an executed cross-platform identity check of the pure-Rust arithmetic (no second platform here; the property holds by construction)",
                             "the engine's crystal, consensus, cascade, falsification and morphogenic paths (quarantined with the review's reasons; the readout and "
                             "detections are specified gate crossings, not crystals)"]},
    "P6-association": {"status": "DONE_EXECUTED_MECHANISM_SHOWN_HARM_BOUND_EXCEEDED", "tests": ["tests/test_association.py", "tests/test_evaluation_domains.py", "tests/test_evaluation.py"],
                       "acceptance": ["ADR-20: the associative memory layer under a frozen protocol with a held-out family and negative controls"],
                       "evidence": ["evidence/wp15/protocol6_declaration.md", "evidence/wp15/protocol6.frozen.json", "evidence/wp15/run6/report.md",
                                    "evidence/wp15/run6/retrieval_analysis.json", "evidence/wp15/protocol6b.frozen.json", "evidence/wp15/run6b/report.md",
                                    "evidence/wp15/run6b/retrieval_analysis.json", "evidence/wp15/*/final_diffs/index.json", "docs/EVALUATION_PROTOCOL.md",
                                    "docs/adr/ADR-20-associative-memory-layer.md"],
                       "not_executed": ["a second provider", "a history produced by model-written deliverables (the history runs use the scripted correct deliverable through the real run)",
                                        "a real-world document corpus", "the associative view as a default (it stays a declared per-task view)"]},
    "P7-association-provenance": {"status": "DONE_EXECUTED_RULES_MET_DEFAULT_VIEW", "tests": ["tests/test_association.py", "tests/test_evaluation_domains.py"],
                                  "acceptance": ["ADR-21: carried sources say why they are in the prompt; protocol 7 with the matched unlabeled control"],
                                  "evidence": ["evidence/wp15/protocol7_declaration.md", "evidence/wp15/protocol7.frozen.json", "evidence/wp15/run7/report.md",
                                               "evidence/wp15/run7/retrieval_analysis.json", "evidence/wp15/run7/final_diffs/index.json", "docs/EVALUATION_PROTOCOL.md",
                                               "docs/adr/ADR-21-association-provenance-in-the-prompt.md"],
                                  "not_executed": ["a second provider", "a presentation study beyond the one labeled form and its unlabeled control",
                                                   "the default view on the protocol 5 corpora with a real provider (no history exists there, so the view ranks like provenance by construction)"]},
    "P8-g3-association": {"status": "DONE_EXECUTED_CRITERION_MET_PROMOTED", "tests": ["tests/test_policy_route.py", "tests/test_evaluation_domains.py", "tests/test_evaluation.py"],
                          "acceptance": ["AT17(G3: declared held-out criterion met by a versioned routing policy)", "AT25(promotion on disjoint held-out evidence)"],
                          "evidence": ["evidence/wp15/protocol8_declaration.md", "evidence/wp15/protocol8a-train.frozen.json", "evidence/wp15/run8a-train/report.md",
                                       "evidence/wp15/policies8/training_manifest.json", "evidence/wp15/policies8/metrics.json", "evidence/wp15/policies8/policy-channels.json",
                                       "evidence/wp15/protocol8b-eval.frozen.json", "evidence/wp15/run8b-eval/report.md", "evidence/wp15/run8b-eval/retrieval_analysis.json",
                                       "evidence/wp15/promotion8/promotion.json", "evidence/wp15/*/final_diffs/index.json",
                                       "src/gabriel_agent/domains/document/policies/readout-channels-v2.provenance.json", "docs/RELEASE_G3.md",
                                       "docs/adr/ADR-22-domain-declared-channels-g3.md", "docs/EVALUATION_PROTOCOL.md"],
                          "not_executed": ["a second provider", "a second pack with declared channels (the software and numerical packs declare none)",
                                           "a held-out decision of the recoverable class (every held-out decision was a hopeless repair)",
                                           "episodic retrieval in the promoted policy (episodes 0)"]},
    "P9-second-provider": {"status": "DONE_EXECUTED_RULES_MET", "tests": ["tests/test_association.py", "tests/test_policy_route.py"],
                           "acceptance": ["replication of ADR-20 and ADR-21 and transfer of the ADR-22 readout under a second provider, declared before the run"],
                           "evidence": ["evidence/wp15/protocol9_declaration.md", "evidence/wp15/pilot9.frozen.json", "evidence/wp15/pilot9-run/report.md",
                                        "evidence/wp15/protocol9.frozen.json", "evidence/wp15/run9/report.md", "evidence/wp15/run9/retrieval_analysis.json",
                                        "evidence/wp15/run9/decision_analysis.json", "evidence/wp15/run9/final_diffs/index.json", "docs/EVALUATION_PROTOCOL.md"],
                           "not_executed": ["a provider of another vendor (the Anthropic provider is implemented and tested against a local fake endpoint; no credential here)",
                                            "a readout trained on gpt-5-mini's own decisions", "a second pack or a real-world corpus"]},
    "ADR23-association-erosion": {"status": "DONE_EXECUTED", "tests": ["tests/test_association.py", "tests/test_memory.py"],
                                  "acceptance": ["ADR-23: the walk runs over the retrieval's own candidates only; a declared withdrawal erodes the history "
                                                 "through the owner; every retained retrieval manifest reproduces from the chain at its own frontier and "
                                                 "access policy revision"],
                                  "evidence": ["evidence/wp16/witness.json", "evidence/wp16/report.md", "evidence/wp16/manifest-summary_associative.json",
                                               "evidence/wp16/manifest-summary_annex_withdrawn.json", "docs/adr/ADR-23-association-erosion.md"],
                                  "not_executed": ["a provider run after an erosion (mechanism witness with the scripted provider only)",
                                                   "erosion by time (not designed: a claim contributes or not)",
                                                   "a key-level withdrawal that survives a later task declaring the source available"]},
    "OPS": {"status": "DONE", "tests": ["tests/test_ops.py"], "acceptance": ["blueprint: operations, observability and release discipline"],
            "evidence": ["evidence/ops/migration_at23.json", "evidence/ops/migration_run5_dr-notice.json", "evidence/ops/smoke_metrics.json",
                         "evidence/ops/smoke_trace_summary.json", "evidence/ops/smoke_gc_dry_run.json", "evidence/ops/smoke_doctor_deep.json",
                         "docs/adr/ADR-17-operations.md", "evidence/test_results.txt"],
            "not_executed": ["cooperative cancellation of a tool run inside the containment backend (stop takes effect at the next boundary)",
                             "a successful migration of a journal created before catalog records existed (refused by rule when verifiers changed)"]},
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
             "independent oracles and recorded replay; the analytical workers are the standard-library adapter and, since ADR-18, the native PSE graph "
             "engine built from the locked sources and run as a contained worker with independent references (evidence/pse); "
             "the advantage gate was executed on the document and numerical families under protocol 5 (evidence/wp14) and not passed, with the "
             "declared ablations of provenance-aware retrieval and the revision rule below the declared minimum relevant effect",
}

RELEASE_SCOPE_G3 = {
    "established_on_this_host": True,
    "evidence": ["evidence/wp15/protocol8_declaration.md", "evidence/wp15/run8a-train/report.md", "evidence/wp15/policies8/metrics.json",
                 "evidence/wp15/run8b-eval/report.md", "evidence/wp15/promotion8/promotion.json",
                 "src/gabriel_agent/domains/document/policies/readout-channels-v2.provenance.json",
                 "evidence/wp13/run4b-eval/report.md", "evidence/wp13/promotion/promotion.json"],
    "scope": "established in the blueprint's scoped sense: one versioned routing policy (a logistic readout over the generic progress channels and "
             "the document pack's declared channels, ADR-22) trained on 48 retained decisions of the system's own runs on three topics met the "
             "declared held-out criterion on two unseen topics under protocol 8 (equal verified success 8/12, 2836 against 5425 mean tokens, no "
             "false completion), with held-out decision loss 0.045 against the rule's 6.91, and was promoted by the memory service's rule on "
             "disjoint held-out families; it ships pinned as the document pack's default routing policy with its provenance, the rule-based policy "
             "stays the default of every other pack; the claim is bounded to one provider, one pack and one constructed distribution, the readout "
             "learned one legible fact and can only stop a repair earlier than the rule; protocol 4 on the hard tier (evidence/wp13) trained no "
             "readout and rejected the episodic-retrieval ablation",
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
