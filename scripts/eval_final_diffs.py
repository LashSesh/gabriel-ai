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


def _git_dir(worktree: Path) -> list:
    """Extra git arguments for a worktree whose ``.git`` link dangles because the run directory was
    moved after the run: the unit's seeded base repository (``<unit>/repo``) then serves as the git
    directory, which is equivalent because the agent never commits (the worktree head is the base
    commit, verified against the retained index of unmoved runs)."""
    link = worktree / ".git"
    if link.is_file():
        target = link.read_text().strip().removeprefix("gitdir:").strip()
        if not Path(target).is_dir():
            unit = worktree.resolve().parent.parent.parent  # <unit>/<ws>/worktrees/<run>
            repo = unit / "repo" / ".git"
            if repo.is_dir():
                return ["--git-dir=" + str(repo), "--work-tree=" + str(worktree.resolve())]
    return []


def _git(worktree: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(worktree), *_git_dir(worktree), *args], capture_output=True, text=True, check=True).stdout


def unit_diff(worktree: Path) -> str:
    parts = [_git(worktree, "-c", "core.quotepath=false", "diff", "--no-color", "HEAD", "--")]
    untracked = [p for p in _git(worktree, "ls-files", "--others", "--exclude-standard").splitlines()
                 if p and not any(marker in p for marker in IGNORED_UNTRACKED)]
    for path in sorted(untracked):
        proc = subprocess.run(["git", "-C", str(worktree), *_git_dir(worktree), "-c", "core.quotepath=false", "diff", "--no-color", "--no-index", "--",
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
        if not worktree.is_dir():
            # The run directory was moved or renamed after the run: rebase the recorded absolute
            # path onto the unit directory the record now lives in.
            try:
                worktree = record_path.parent / worktree.relative_to(Path(record["run_dir"]))
            except ValueError:
                pass
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
