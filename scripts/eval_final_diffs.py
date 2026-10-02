#!/usr/bin/env python3
"""Retain the final worktree diff of every evaluation unit as evidence.

The materialized task repositories and the per-system worktrees are git repositories of
their own and are not committed with the evidence (they are reproducible from the frozen
corpus). What the system-independent verification actually judged is the final content of
each worktree; this script records it as ``<run>/final_diffs/<unit>.diff`` (diff against the
seeded base commit, untracked files included) plus ``final_diffs/index.json`` with digests.

Usage: scripts/eval_final_diffs.py evidence/wp11/<run-dir> [...]
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

IGNORED_UNTRACKED = ("__pycache__/", ".pyc", "oracle_")


def _git(worktree: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(worktree), *args], capture_output=True, text=True, check=True).stdout


def unit_diff(worktree: Path) -> str:
    parts = [_git(worktree, "-c", "core.quotepath=false", "diff", "--no-color", "HEAD", "--")]
    untracked = [p for p in _git(worktree, "ls-files", "--others", "--exclude-standard").splitlines()
                 if p and not any(marker in p for marker in IGNORED_UNTRACKED)]
    for path in sorted(untracked):
        proc = subprocess.run(["git", "-C", str(worktree), "-c", "core.quotepath=false", "diff", "--no-color", "--no-index", "--",
                               "/dev/null", path], capture_output=True, text=True)
        parts.append(proc.stdout)  # --no-index exits 1 when the files differ
    return "".join(parts)


def collect(run_dir: Path) -> dict:
    out = run_dir / "final_diffs"
    out.mkdir(exist_ok=True)
    index = {}
    for record_path in sorted((run_dir / "runs").glob("*/record.json")):
        record = json.loads(record_path.read_text())
        unit = record_path.parent.name
        worktree = Path(record["outcome"]["worktree"])
        entry = {"task_id": record["task_id"], "system": record["system"], "rep": record["rep"], "verified": bool(record["V"]),
                 "worktree_present": worktree.is_dir()}
        if worktree.is_dir():
            text = unit_diff(worktree)
            entry["head"] = _git(worktree, "rev-parse", "HEAD").strip()
            (out / (unit + ".diff")).write_text(text)
            entry["diff_sha256"] = hashlib.sha256(text.encode("utf8")).hexdigest()
            entry["diff_bytes"] = len(text.encode("utf8"))
        index[unit] = entry
    (out / "index.json").write_text(json.dumps({"schema": "gabriel.evidence.final-diffs/1", "run_dir": str(run_dir), "units": index},
                                               indent=2, sort_keys=True) + "\n")
    return index


def main(argv: list) -> int:
    for arg in argv:
        index = collect(Path(arg))
        present = sum(1 for e in index.values() if e["worktree_present"])
        print("%s: %d units, %d diffs retained" % (arg, len(index), present))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
