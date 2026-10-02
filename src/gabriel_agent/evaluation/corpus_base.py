"""Shared task representation of the evaluation corpus."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from ..contracts.codec import canonical


@dataclass(frozen=True)
class EvalTask:
    task_id: str
    family: str
    module: str
    goal: str
    buggy: str
    fixed: str
    visible_tests: str
    oracle: str
    allowed_paths: tuple = ("src/",)
    tier: str = "standard"
    extra_files: tuple = ()      # ((path, content), ...): further repository files, identical in every variant
    naive: tuple | None = None   # ((path, content), ...): the plausible wrong fix (passes visible tests, fails the oracle)

    def files(self) -> dict:
        files = {"src/%s.py" % self.module: self.buggy, "tests/test_%s.py" % self.module: self.visible_tests,
                 "README.md": "# %s\n\nSmall library used in the Gabriel evaluation corpus.\n" % self.module}
        for path, content in self.extra_files:
            files[path] = content
        return files

    def digest(self) -> str:
        return hashlib.sha256(canonical({"task_id": self.task_id, "family": self.family, "module": self.module, "goal": self.goal,
                                         "buggy": self.buggy, "visible_tests": self.visible_tests, "oracle": self.oracle,
                                         "allowed_paths": list(self.allowed_paths), "tier": self.tier,
                                         "extra_files": [list(pair) for pair in self.extra_files],
                                         "naive": [list(pair) for pair in self.naive] if self.naive else None})).hexdigest()


VISIBLE_HEADER = '''import unittest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
'''
ORACLE_HEADER = '''import unittest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
'''


def task(task_id, family, module, goal, buggy, fixed, visible, oracle, *, tier="standard", extra_files=(), naive=None):
    return EvalTask(task_id, family, module, goal, buggy, fixed, VISIBLE_HEADER + visible, ORACLE_HEADER + oracle,
                    tier=tier, extra_files=tuple(extra_files), naive=tuple(naive) if naive else None)
