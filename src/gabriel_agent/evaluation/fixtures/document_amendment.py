"""Document fixture: a source-grounded amendment with an independent required-claims oracle.

Two declared sources (a policy and a memo) and one target summary. The oracle, kept outside
the repository, requires two statements, each cited from the right source with a quote that
includes the decisive text. Variants of the scripted worker exercise valid, uncited, wrongly
sourced, fabricated and out-of-scope proposals.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

POLICY = """# Membership policy (revision 1)

## Termination

Members may terminate their membership in writing. The notice period for members is
thirty (30) days, counted from the day the written notice is received.

## Fees

Annual fees are invoiced in January and are due within fourteen days.
"""

MEMO = """# Finance memo, September 2026

With effect from 1 October 2026 the expense approval threshold is 500 EUR per
single expense. Expenses above the threshold need written approval by the treasurer
before they are incurred.
"""

TARGET = """# Membership summary

(to be completed: notice period and expense approval threshold)
"""

# A claim may be phrased in several ways; what the oracle fixes is the fact and the source span
# that must be cited for it (the first AT23 run failed on an over-literal "30 days").
ORACLE = {"claims": [
    {"path": "doc/summary.md", "must_contain": ["30 days", "thirty (30) days", "(30) days", "30-day", "thirty days"],
     "cited_source_id": "policy", "quote_must_include": "thirty (30) days"},
    {"path": "doc/summary.md", "must_contain": ["500 EUR", "EUR 500", "500 euro", "500 Euro"], "cited_source_id": "memo", "quote_must_include": "500 EUR"},
]}


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf8")).hexdigest()


def build_repo(path: Path) -> str:
    path = Path(path)
    (path / "sources").mkdir(parents=True)
    (path / "doc").mkdir()
    (path / "sources" / "policy.md").write_text(POLICY)
    (path / "sources" / "memo.md").write_text(MEMO)
    (path / "doc" / "summary.md").write_text(TARGET)
    env = dict(os.environ, GIT_AUTHOR_NAME="fixture", GIT_AUTHOR_EMAIL="fixture@invalid", GIT_COMMITTER_NAME="fixture", GIT_COMMITTER_EMAIL="fixture@invalid")
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True, env=env)
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True, env=env)
    subprocess.run(["git", "-C", str(path), "commit", "-q", "-m", "seed membership sources and summary"], check=True, env=env)
    return subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()


def write_oracle(path: Path) -> Path:
    path = Path(path)
    path.write_text(json.dumps(ORACLE, indent=1))
    return path


def task_spec(repo: Path, base_commit: str, oracle_path: Path, provider: dict, **over) -> dict:
    spec = {"domain": "document",
            "goal": "Amend doc/summary.md so that it states the notice period for members and the expense approval threshold. "
                    "Every statement must be followed by a citation of the exact source span that supports it. Do not change the sources.",
            "repository": str(repo), "base_commit": base_commit, "allowed_paths": ["doc/"],
            "sources": [{"path": "sources/policy.md", "source_id": "policy", "revision": 1, "event_kind": "timeless_document"},
                        {"path": "sources/memo.md", "source_id": "memo", "revision": 1, "event_kind": "completed_observation",
                         "event_start_unix_ms": 1759276800000, "event_end_unix_ms": 1759276800000}],
            "targets": ["doc/summary.md"],
            "checks": [{"check_id": "citations", "kind": "document/citations_bound", "independent": True, "role": "acceptance_only"},
                       {"check_id": "claims", "kind": "document/required_claims", "independent": True, "role": "acceptance_only",
                        "oracle_files": [{"path": "oracle/required_claims.json", "source": str(oracle_path)}]}],
            "provider": provider, "budget": {"model_tokens_total": 200000, "model_requests": 12}}
    spec.update(over)
    return spec


def _amendment(content: str, rationale: str, path: str = "doc/summary.md", expected: str | None = None) -> dict:
    return {"kind": "template", "value": {"operations": [{"kind": "modify", "path": path, "expected_sha256": sha(TARGET) if expected is None else expected,
                                                           "content": content}], "rationale": rationale}}


CORRECT = """# Membership summary

Members have a notice period of 30 days. [[cite:{{obs:policy}} "thirty (30) days, counted from the day the written notice is received"]]

The expense approval threshold is 500 EUR per single expense. [[cite:{{obs:memo}} "the expense approval threshold is 500 EUR"]]
"""

UNCITED = """# Membership summary

Members have a notice period of 30 days.

The expense approval threshold is 500 EUR per single expense.
"""

WRONG_SOURCE = """# Membership summary

Members have a notice period of 30 days. [[cite:{{obs:memo}} "expense approval threshold"]]

The expense approval threshold is 500 EUR per single expense. [[cite:{{obs:memo}} "the expense approval threshold is 500 EUR"]]
"""

FABRICATED = """# Membership summary

Members have a notice period of 30 days. [[cite:obs-00000000000000000000000000000000deadbeef "thirty (30) days"]]

The expense approval threshold is 500 EUR per single expense. [[cite:{{obs:memo}} "the expense approval threshold is 500 EUR"]]
"""


def script(variant: str = "correct") -> dict:
    planner = [{"kind": "echo_reference"}]
    if variant == "correct":
        worker = [_amendment(CORRECT, "State both facts with exact cited spans.")]
    elif variant == "uncited":
        worker = [_amendment(UNCITED, "State both facts.")]
    elif variant == "wrong_source":
        worker = [_amendment(WRONG_SOURCE, "Cite the memo for everything.")]
    elif variant == "fabricated":
        worker = [_amendment(FABRICATED, "Cite an invented observation for the notice period.")]
    elif variant == "out_of_scope":
        worker = [_amendment(POLICY.replace("thirty (30) days", "ten (10) days"), "Edit the policy source instead of the summary.",
                             path="sources/policy.md", expected=sha(POLICY))]
    else:
        raise ValueError("unknown variant " + variant)
    return {"by_step": {"plan-request": planner, "propose": worker}, "by_role": {"planner": planner, "worker": worker}}
