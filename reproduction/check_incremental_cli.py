"""Execute all three explicit CLI profiles and retain the incremental demo.

The generated inputs are synthetic. Subprocesses use this delivered project's
local sources with PYTHONPATH cleared. No network or historical data is read.
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


def canon(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def run(*arguments, expected=0):
    env = os.environ.copy()
    env["PYTHONPATH"] = ""
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    args = list(map(str, arguments))
    result = subprocess.run([sys.executable, "-m", "gabriel_runtime", *args],
                            cwd=ROOT, env=env, capture_output=True, text=True, timeout=180)
    STEPS.append({"arguments": args, "returncode": result.returncode,
                  "stdout": result.stdout, "stderr": result.stderr})
    if result.returncode != expected:
        raise AssertionError(STEPS[-1])
    return json.loads(result.stdout) if result.stdout else result.stderr


def bundle(directory):
    return {name: json.loads((directory / (name + ".json")).read_text())
            for name in ("commands", "journal", "anchor", "summary")}


def main():
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="gabriel-incremental-cli-") as directory:
        temp = Path(directory)
        inc = temp / "incremental"
        demo = run("incremental-demo", "--out", inc)
        assert demo["profile"] == "incremental"
        assert demo["prediction_basis"] == "next_unreceived_observation"
        assert demo["current_feedback_changed"]
        assert demo["published_prefix_unchanged_after_correction"]
        assert demo["correction_without_historical_reissue"]
        db = inc / "owner.sqlite"
        audit = run("audit", db, "--profile", "incremental", "--anchor", inc / "anchor.json")
        assert audit["external_anchor_checked"] and audit["events"] == demo["events"]
        view = run("inspect", db, "--profile", "incremental", "--contract", "stream")
        assert view["source_count"] == 320 and view["issued_count"] == demo["issued_count"]
        export = temp / "incremental_export.json"
        run("export", db, "--profile", "incremental", "--out", export)
        assert export.read_bytes() == (inc / "journal.json").read_bytes()
        inc_bundle = bundle(inc)
        first = inc_bundle["commands"][0]
        receipt = run("submit", db, "--profile", "incremental", "--command", canon(first))
        assert receipt["sequence"] == 1
        assert run("audit", db, "--profile", "incremental", "--anchor", inc / "anchor.json")["events"] == demo["events"]
        for profile in ("legacy", "stream"):
            error = run("audit", db, "--profile", profile, expected=2)
            assert "fingerprint mismatch" in error
        changed = json.loads(canon(first))
        changed["payload"]["config"]["max_units"] += 1
        error = run("submit", db, "--profile", "incremental", "--command", canon(changed), expected=2)
        assert "conflicting command id" in error
        stale = json.loads(canon(first))
        stale["id"] = "new-command-with-old-head"
        error = run("submit", db, "--profile", "incremental", "--command", canon(stale), expected=2)
        assert "stale expected" in error
        anchor = dict(inc_bundle["anchor"])
        anchor["events"] += 1
        error = run("audit", db, "--profile", "incremental", "--anchor", canon(anchor), expected=2)
        assert "event count mismatch" in error
        assert "exists" in run("incremental-demo", "--out", inc, expected=2)
        error = run("submit", db, "--profile", "incremental", "--command", '{"id":1,"id":2}', expected=2)
        assert "duplicate" in error
        legacy = temp / "legacy"
        run("demo", "--out", legacy, "--with-conflict")
        legacy_db = legacy / "owner.sqlite"
        assert run("audit", legacy_db, "--anchor", legacy / "anchor.json")["events"] == 12
        assert run("inspect", legacy_db, "--contract", "conflict-example")["result"]["status"] == "conflict"
        assert "fingerprint mismatch" in run("audit", legacy_db, "--profile", "incremental", expected=2)
        stream = temp / "stream"
        run("stream-demo", "--out", stream)
        stream_db = stream / "owner.sqlite"
        assert run("audit", stream_db, "--profile", "stream", "--anchor", stream / "anchor.json")["events"] == demo["events"]
        assert "fingerprint mismatch" in run("audit", stream_db, "--profile", "incremental", expected=2)
        stream_bundle = bundle(stream)
        assert canon(inc_bundle["summary"]["issued_forecasts"]) == canon(stream_bundle["summary"]["issued_forecasts"])
        assert canon(inc_bundle["summary"]["snapshots"]) == canon(stream_bundle["summary"]["snapshots"])
        old = ROOT / "results/stream_demo.json"
        if not old.is_file():
            raise AssertionError("retained original stream demo required for CLI compatibility check")
        original_bundle = json.loads(old.read_text())
        assert canon(stream_bundle) == canon(original_bundle)
        inc_fingerprints = inc_bundle["journal"]["header"]["registry"]
        old_fingerprints = stream_bundle["journal"]["header"]["registry"]
        assert set(inc_fingerprints) == set(old_fingerprints)
        assert canon(inc_fingerprints["stream-risk/v1"]) != canon(old_fingerprints["stream-risk/v1"])
        for key in set(old_fingerprints) - {"stream-risk/v1"}:
            assert canon(inc_fingerprints[key]) == canon(old_fingerprints[key])
    output = ROOT / "results"
    (output / "incremental_demo.json").write_text(json.dumps(inc_bundle, sort_keys=True, indent=2) + "\n")
    sources = [ROOT / "gabriel_runtime/__main__.py", ROOT / "gabriel_runtime/stream_demo.py",
               ROOT / "gabriel_runtime/incremental.py", Path(__file__).resolve()]
    report = {"schema": "gabriel.incremental.executed-cli-checks.v1", "status": "passed",
              "elapsed_seconds": round(time.monotonic() - started, 3),
              "subprocess_commands": len(STEPS), "example_kind": "synthetic",
              "incremental_demo": demo, "issued_forecast_equality": "exact canonical JSON",
              "snapshot_equality": "exact canonical JSON",
              "original_stream_demo_unchanged": True,
              "explicit_distinct_fingerprint": True,
              "source_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
              "demo_sha256": hashlib.sha256((output / "incremental_demo.json").read_bytes()).hexdigest(),
              "scope": "CLI and domain-output preservation; not a performance benchmark or predictive superiority test.",
              "steps": STEPS}
    (output / "incremental_cli_checks.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: report[key] for key in ("status", "elapsed_seconds", "subprocess_commands", "original_stream_demo_unchanged")}))


if __name__ == "__main__":
    main()
