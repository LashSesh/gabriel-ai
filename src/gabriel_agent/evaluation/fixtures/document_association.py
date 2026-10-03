"""Association fixture (ADR-20): a source that only association history can bring into a budgeted
retrieval.

The charter (source ``charter``) says that the yearly contribution is fixed in the annex; the
annex (source ``annex``) states the amount in words that share no token with the summary goal.
Thirty-six distractor notes each share two tokens with the goal, so under the pack's budget of
32 retrieved items the annex, with a lexical score of zero, is never retrieved by the provenance
view. The history task cites charter and annex together in a verified deliverable; after it, the
summary task's associative view carries the annex into the prompt by the engine's walk from the
charter, and the scripted worker can cite it.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

CHARTER = ("# Club charter\n\n## Membership fee\n\nEach member pays a yearly contribution; the amount is fixed in the annex of this charter.\n")
ANNEX = "# Annex\n\nOrdinary contributions: one hundred twenty (120) EUR, payable within January.\n"
DISTRACTORS = 36
NOTES_TARGET = "doc/notes.md"
SUMMARY_TARGET = "doc/summary.md"
NOTES_SEED = "# Notes\n\n(to be completed: the contribution rule and the annex amount)\n"
SUMMARY_SEED = "# Membership summary\n\n(to be completed: what the charter says about the membership fee and the amount a member pays each year)\n"
HISTORY_GOAL = ("Amend doc/notes.md so that it records the yearly contribution rule of the charter and, from the annex, the ordinary contributions of "
                "one hundred twenty EUR payable within January. Every statement must be followed by a citation of the exact source span that supports it. "
                "Do not change the sources.")
SUMMARY_GOAL = ("Amend doc/summary.md so that it states what the charter says about the membership fee and the amount a member pays each year. "
                "Every statement must be followed by a citation of the exact source span that supports it. Do not change the sources.")


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf8")).hexdigest()


def distractor(index: int) -> str:
    # the corpus tier's distractor (corpus_domains._association_distractor): scored by the goal's function words, naming no source
    return "# Note %d\n\nMinutes of the committee meeting held on the %s Tuesday: quorum reached, no resolutions.\n" % (index, ("first", "second", "third", "fourth")[index % 4])


def files() -> dict:
    out = {"sources/charter.md": CHARTER, "sources/annex.md": ANNEX, NOTES_TARGET: NOTES_SEED, SUMMARY_TARGET: SUMMARY_SEED,
           "README.md": "# Club documents\n\nThe charter, its annex and the committee notes.\n"}
    for index in range(DISTRACTORS):
        out["sources/note-%02d.md" % index] = distractor(index)
    return out


def build_repo(path: Path) -> str:
    path = Path(path)
    for relative, content in files().items():
        target = path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    env = dict(os.environ, GIT_AUTHOR_NAME="fixture", GIT_AUTHOR_EMAIL="fixture@invalid", GIT_COMMITTER_NAME="fixture", GIT_COMMITTER_EMAIL="fixture@invalid")
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True, env=env)
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True, env=env)
    subprocess.run(["git", "-C", str(path), "commit", "-q", "-m", "seed club documents"], check=True, env=env)
    return subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()


def sources(with_distractors: bool = True) -> list:
    out = [{"path": "sources/charter.md", "source_id": "charter", "revision": 1, "event_kind": "timeless_document"},
           {"path": "sources/annex.md", "source_id": "annex", "revision": 1, "event_kind": "timeless_document"}]
    if with_distractors:
        out += [{"path": "sources/note-%02d.md" % index, "source_id": "note%02d" % index, "revision": 1, "event_kind": "timeless_document"} for index in range(DISTRACTORS)]
    return out


def history_oracle(path: Path) -> Path:
    path = Path(path)
    path.write_text(json.dumps({"claims": [{"path": NOTES_TARGET, "must_contain": ["annex"], "cited_source_id": "charter", "quote_must_include": "fixed in the annex"},
                                           {"path": NOTES_TARGET, "must_contain": ["120 EUR", "120"], "cited_source_id": "annex", "quote_must_include": "one hundred twenty (120) EUR"}],
                                "forbidden": []}, indent=1))
    return path


def summary_oracle(path: Path) -> Path:
    path = Path(path)
    path.write_text(json.dumps({"claims": [{"path": SUMMARY_TARGET, "must_contain": ["annex"], "cited_source_id": "charter", "quote_must_include": "fixed in the annex"},
                                           {"path": SUMMARY_TARGET, "must_contain": ["120 EUR", "120"], "cited_source_id": "annex", "quote_must_include": "one hundred twenty (120) EUR"}],
                                "forbidden": []}, indent=1))
    return path


def _spec(goal, repo, base_commit, oracle_path, provider, target, declared, **over) -> dict:
    spec = {"domain": "document", "goal": goal, "repository": str(repo), "base_commit": base_commit, "allowed_paths": ["doc/"], "sources": declared,
            "targets": [target],
            "checks": [{"check_id": "citations", "kind": "document/citations_bound", "independent": True, "role": "acceptance_only"},
                       {"check_id": "claims", "kind": "document/required_claims", "independent": True, "role": "acceptance_only",
                        "oracle_files": [{"path": "oracle/required_claims.json", "source": str(oracle_path)}]}],
            "provider": provider, "budget": {"model_tokens_total": 400000, "model_requests": 12}}
    spec.update(over)
    return spec


def history_spec(repo, base_commit, oracle_path, provider, **over) -> dict:
    """The history task: its goal reaches charter and annex lexically; the deliverable cites both."""
    return _spec(HISTORY_GOAL, repo, base_commit, oracle_path, provider, NOTES_TARGET, sources(with_distractors=False), **over)


def summary_spec(repo, base_commit, oracle_path, provider, view: str = "associative", **over) -> dict:
    """The evaluated task: the annex is lexically invisible to its goal and competes with 36 scored distractors."""
    return _spec(SUMMARY_GOAL, repo, base_commit, oracle_path, provider, SUMMARY_TARGET, sources(with_distractors=True), retrieval_view=view, **over)


def _amendment(target: str, content: str, rationale: str) -> dict:
    return {"kind": "template", "value": {"operations": [{"kind": "modify", "path": target, "expected_sha256": "{{sha:%s}}" % target, "content": content}],
                                          "rationale": rationale}}


HISTORY_CONTENT = ('# Notes\n\nThe amount of the yearly contribution is fixed in the annex. [[cite:{{obs:charter}} "fixed in the annex"]]\n\n'
                   'Ordinary contributions are one hundred twenty (120) EUR, payable within January. [[cite:{{obs:annex}} "one hundred twenty (120) EUR"]]\n')
SUMMARY_CONTENT = ('# Membership summary\n\nThe charter fixes the amount of the yearly contribution in the annex. [[cite:{{obs:charter}} "fixed in the annex"]]\n\n'
                   'A member pays 120 EUR each year. [[cite:{{obs:annex}} "one hundred twenty (120) EUR"]]\n')


def script(variant: str = "history") -> dict:
    planner = [{"kind": "echo_reference"}]
    if variant == "history":
        worker = [_amendment(NOTES_TARGET, HISTORY_CONTENT, "record both facts with cited spans")]
    elif variant == "summary":
        worker = [_amendment(SUMMARY_TARGET, SUMMARY_CONTENT, "state both facts with cited spans")]
    else:
        raise ValueError("unknown variant " + variant)
    return {"by_step": {"plan-request": planner, "propose": worker}, "by_role": {"planner": planner, "worker": worker}}


def provider(variant: str) -> dict:
    return {"kind": "scripted", "script": script(variant), "provider_id": "scripted-association"}
