"""Actual subprocess checks for owner/profile independence and interchange.

Inputs are the three synthetic CLI demos. Reference remains the default. Every
owner opens through full semantic replay; no database or journal is synthesized.
The saved report is functional evidence, not a performance measurement.
"""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
STEPS = []
RUN_ROOT = None


def canon(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def run(*arguments, expected=0):
    env = os.environ.copy()
    env.update(PYTHONPATH="", PYTHONDONTWRITEBYTECODE="1",
               OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    args = list(map(str, arguments))
    result = subprocess.run([sys.executable, "-m", "gabriel_runtime", *args],
                            cwd=ROOT, env=env, capture_output=True, text=True, timeout=180)
    entry = {"arguments": [arg.replace(str(RUN_ROOT), "$RUN") for arg in args],
             "returncode": result.returncode,
             "stdout_sha256": digest(result.stdout.encode()),
             "stderr": result.stderr.replace(str(RUN_ROOT), "$RUN")}
    STEPS.append(entry)
    if result.returncode != expected:
        raise AssertionError({**entry, "stdout": result.stdout})
    return json.loads(result.stdout) if result.stdout else result.stderr


def bundle(directory):
    return {name: json.loads((directory / (name + ".json")).read_text())
            for name in ("commands", "journal", "anchor", "summary")}


def same(left, right):
    assert canon(left) == canon(right)


def main():
    global RUN_ROOT
    started = time.monotonic()
    comparisons = []
    retained = {}
    with tempfile.TemporaryDirectory(prefix="gabriel-replay-owner-cli-") as directory:
        RUN_ROOT = Path(directory)
        for profile, demo_action, retained_name in (
                ("legacy", "demo", "runtime_demo"),
                ("stream", "stream-demo", "stream_demo"),
                ("incremental", "incremental-demo", "incremental_demo")):
            paths = {owner: RUN_ROOT / (profile + "-" + owner)
                     for owner in ("reference", "replay")}
            demos, bundles = {}, {}
            for owner, path in paths.items():
                arguments = [demo_action, "--out", path]
                if profile == "legacy":
                    arguments.append("--with-conflict")
                # Omission tests the preserved default; replay is always explicit.
                if owner == "replay":
                    arguments.extend(("--owner", "replay"))
                demos[owner] = run(*arguments)
                bundles[owner] = bundle(path)
            same(demos["reference"], demos["replay"])
            same(bundles["reference"], bundles["replay"])
            original = json.loads((ROOT / "results" / (retained_name + ".json")).read_text())
            same(bundles["reference"], {key: original[key] for key in bundles["reference"]})
            retained[profile] = {"demo": demos["replay"], "bundle": bundles["replay"]}
            contract = "risk" if profile == "legacy" else "stream"
            snapshot = (bundles["reference"]["summary"]["snapshots"]["risk_as_of_first_maturity"]
                        if profile == "legacy" else
                        bundles["reference"]["summary"]["snapshots"]["after_new_slot"])
            anchor = bundles["reference"]["anchor"]
            for creator, path in paths.items():
                for opener in ("reference", "replay"):
                    args = [path / "owner.sqlite", "--profile", profile, "--owner", opener]
                    check = run("audit", *args, "--anchor", path / "anchor.json")
                    assert check["external_anchor_checked"] and check["events"] == anchor["events"]
                    same(run("inspect", *args, "--contract", contract), snapshot)
                    exported = RUN_ROOT / (profile + "-" + creator + "-" + opener + ".json")
                    run("export", *args, "--out", exported)
                    assert exported.read_bytes() == (path / "journal.json").read_bytes()
                # Cross-owner retry is physically executed on both stores.
                opposite = "replay" if creator == "reference" else "reference"
                receipt = run("submit", path / "owner.sqlite", "--profile", profile,
                              "--owner", opposite, "--command", canon(bundles[creator]["commands"][0]))
                assert receipt["sequence"] == 1
            current = dict(anchor)
            writes = []
            for step in range(2):
                if profile == "legacy":
                    payload = {"event_cutoff": 2, "receipt_cutoff": 3 + step,
                               "operation_cutoff": None}
                    op, at = "query", 5 + step
                else:
                    index = 320 + step
                    price = 100.0 + (((index * 37) % 97) - 48) / 32.0 + (((index * 13) % 17) - 8) / 64.0
                    payload = {"index": index, "event_at": index, "received_at": index + 1,
                               "revision": 0, "rate_hex": price.hex()}
                    op, at = "record", index + 1
                command = {"id": "cross-owner-new-" + str(step), "contract": contract,
                           "op": op, "at": at, "expected_head": current["head"],
                           "payload": payload}
                receipts = []
                for creator, path in paths.items():
                    owner = ("replay" if creator == "reference" else "reference") if step == 0 else creator
                    receipts.append(run("submit", path / "owner.sqlite", "--profile", profile,
                                        "--owner", owner, "--command", canon(command)))
                same(*receipts)
                current = {"head": receipts[0]["head"], "events": receipts[0]["sequence"]}
                writes.append({"command": command, "receipt": receipts[0]})
            exports = []
            for creator, path in paths.items():
                opposite = "replay" if creator == "reference" else "reference"
                args = [path / "owner.sqlite", "--profile", profile, "--owner", opposite]
                assert run("audit", *args, "--anchor", canon(current))["events"] == anchor["events"] + 2
                exported = RUN_ROOT / (profile + "-" + creator + "-updated.json")
                run("export", *args, "--out", exported)
                exports.append(exported.read_bytes())
                bad = dict(writes[-1]["command"])
                bad["id"] = "new-command-with-stale-head"
                assert "stale expected" in run("submit", *args, "--command", canon(bad), expected=2)
                bad = json.loads(canon(writes[-1]["command"]))
                bad["at"] += 1
                assert "conflicting command id" in run("submit", *args, "--command", canon(bad), expected=2)
                assert "duplicate" in run("submit", *args, "--command", '{"id":1,"id":2}', expected=2)
                wrong = "incremental" if profile != "incremental" else "stream"
                assert "fingerprint mismatch" in run("audit", path / "owner.sqlite", "--owner", opposite,
                                                     "--profile", wrong, expected=2)
                assert run("audit", *args, "--anchor", canon(current))["events"] == current["events"]
            assert exports[0] == exports[1]
            comparisons.append({"profile": profile, "demo_bundle_exact": True,
                                "retained_demo_exact": True, "cross_owner_open_combinations": 4,
                                "cross_owner_retry_pairs": 1, "accepted_write_pairs": 2,
                                "final_journal_sha256": digest(exports[0]),
                                "final_anchor": current, "rejected_commands_per_store": 3,
                                "wrong_profile_rejected_by_both_owners": True})
            retained[profile]["continued_commands"] = writes
        assert "invalid choice" in run("demo", "--out", RUN_ROOT / "invalid",
                                       "--owner", "guess", expected=2)
    sources = [ROOT / "gabriel_runtime/__main__.py", ROOT / "gabriel_runtime/stream_demo.py",
               ROOT / "gabriel_runtime/replay_owner.py", ROOT / "gabriel_runtime/engine.py",
               Path(__file__).resolve()]
    demo_file = ROOT / "results/replay_owner_demo.json"
    demo_file.write_text(json.dumps(retained, sort_keys=True, indent=2) + "\n")
    report = {"schema": "gabriel.replay-owner.executed-cli-checks.v1", "status": "passed",
              "elapsed_seconds": round(time.monotonic() - started, 3),
              "subprocess_commands": len(STEPS), "example_kind": "synthetic",
              "equality": "exact canonical JSON and exported canonical bytes",
              "default_owner": "reference", "reference_demos_unchanged": True,
              "owner_independent_profile_fingerprints": True, "profiles": comparisons,
              "source_sha256": {str(p.relative_to(ROOT)): digest(p.read_bytes()) for p in sources},
              "demo_sha256": digest(demo_file.read_bytes()),
              "scope": "CLI interchange and rejection behavior; no timing or predictive-performance claim.",
              "steps": STEPS}
    (ROOT / "results/replay_owner_cli_checks.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: report[key] for key in ("status", "elapsed_seconds", "subprocess_commands")}))


if __name__ == "__main__":
    main()
