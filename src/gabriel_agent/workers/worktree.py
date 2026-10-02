"""Disposable git worktrees with pinned base commits and content manifests."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from ..contracts.codec import digest
from ..contracts.errors import Code, GabrielError
from ..tools.fs import ContainedRoot

GIT_ENV = {"GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "gabriel", "GIT_AUTHOR_EMAIL": "gabriel@invalid",
           "GIT_COMMITTER_NAME": "gabriel", "GIT_COMMITTER_EMAIL": "gabriel@invalid", "GIT_TERMINAL_PROMPT": "0"}


def git(args, cwd, check=True, timeout=120):
    env = dict(os.environ, **GIT_ENV)
    env.pop("GIT_DIR", None)
    env.pop("GIT_WORK_TREE", None)
    proc = subprocess.run(["git"] + list(args), cwd=str(cwd), env=env, capture_output=True, text=True, timeout=timeout)
    if check and proc.returncode != 0:
        raise GabrielError(Code.WORKER_UNAVAILABLE, "git %s failed: %s" % (" ".join(args), proc.stderr.strip()[:500]))
    return proc


class Worktree:
    def __init__(self, path: Path, base_commit: str, repository: Path):
        self.path = Path(path)
        self.base_commit = base_commit
        self.repository = Path(repository)

    @classmethod
    def create(cls, repository, base_commit: str, destination) -> "Worktree":
        repository, destination = Path(repository), Path(destination)
        if not (repository / ".git").exists() and git(["rev-parse", "--is-inside-work-tree"], repository, check=False).returncode != 0:
            raise GabrielError(Code.UNKNOWN_OBJECT, "not a git repository: " + str(repository))
        resolved = git(["rev-parse", "--verify", base_commit + "^{commit}"], repository).stdout.strip()
        if resolved != base_commit:
            raise GabrielError(Code.INVALID_SCHEMA, "base commit must be the full 40-character commit id")
        if destination.exists():
            raise GabrielError(Code.STORAGE_FAULT, "worktree destination already exists: " + str(destination))
        destination.parent.mkdir(parents=True, exist_ok=True)
        git(["worktree", "add", "--detach", str(destination), base_commit], repository)
        return cls(destination, base_commit, repository)

    @classmethod
    def open(cls, path, base_commit: str, repository) -> "Worktree":
        path = Path(path)
        if not path.is_dir():
            raise GabrielError(Code.STORAGE_FAULT, "worktree is missing: " + str(path))
        return cls(path, base_commit, repository)

    def head(self) -> str:
        return git(["rev-parse", "HEAD"], self.path).stdout.strip()

    def manifest(self) -> dict:
        with ContainedRoot(str(self.path)) as root:
            return root.manifest()

    def tree_digest(self) -> str:
        return digest(self.manifest())

    def changed_paths(self) -> list:
        out = git(["status", "--porcelain=v1", "--untracked-files=all"], self.path).stdout
        paths = []
        for line in out.splitlines():
            if len(line) < 4:
                continue
            entry = line[3:]
            if " -> " in entry:
                entry = entry.split(" -> ", 1)[1]
            entry = entry.strip('"')
            if "__pycache__" in entry or entry.endswith(".pyc"):
                continue
            paths.append(entry)
        return sorted(set(paths))

    def patch(self) -> bytes:
        """Binary diff of the whole working tree (including new files) against the base commit."""
        git(["add", "-A", "--", ".", ":(exclude,glob)**/__pycache__/**", ":(exclude,glob)**/*.pyc", ":(exclude,glob)**/.gabriel-tmp-*"], self.path)
        patch = git(["diff", "--cached", "--binary", "--no-color", self.base_commit], self.path).stdout
        git(["reset", "-q"], self.path)
        return patch.encode("utf8")

    def remove(self):
        git(["worktree", "remove", "--force", str(self.path)], self.repository, check=False)
