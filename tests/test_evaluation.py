"""WP11: corpus soundness, comparators under the scripted provider, metrics with explicit denominators."""
import json
from pathlib import Path

import pytest

from gabriel_agent.contracts import GabrielError
from gabriel_agent.evaluation import corpus, comparators, harness
from gabriel_agent.evaluation.fixtures import parser_bug as fixture


def test_corpus_is_sound_and_frozen_by_digest():
    report = corpus.check_all()
    assert report["all_sound"], [t for t in report["tasks"] if not t["sound"]]
    assert len(report["tasks"]) == 84 and len(report["families"]) == 31
    assert report["tiers"] == {"standard": 15, "hard": 9, "document": 9, "numerical": 19, "graph": 10, "association": 22}
    assert all(2 <= len(ids) <= 5 for ids in report["families"].values())
    assert all(len(ids) == 3 for family, ids in report["families"].items() if not family.startswith(("graph-", "association-", "numerical-")))
    assert report["corpus_digest"] == corpus.corpus_digest()
    assert all(t.family in ("text_parsing", "numeric_logic", "collections", "validation", "encoding") for t in corpus.tasks("standard"))
    assert all(t.family in ("multi_file", "trap", "stateful") and t.naive for t in corpus.tasks("hard"))
    # the hard tier's trap invariant is executed: the plausible wrong fix passes the visible tests and fails the oracle
    assert all(t["trap_holds"] for t in report["tasks"] if t["tier"] == "hard")
    assert all(t["trap_holds"] is None for t in report["tasks"] if t["tier"] == "standard")


def test_worker_prompt_contains_retained_sources(tmp_path):
    """Run-2 failure analysis: the first observation did not retain the in-scope sources, so the
    worker prompt listed digests only and the model rewrote files blind. The prompt must carry
    the content of every in-scope text file, and never omit one silently."""
    task = next(t for t in corpus.tasks() if t.task_id == "nl-median")
    budget = comparators.Budget(model_requests=2, model_tokens_total=60000, max_input_tokens=20000, max_output_tokens=2000)
    ctx = comparators.EvalContext(task, tmp_path / "ctx", scripted_provider(), budget, "trusted_local")
    prompt, snapshot, manifest = ctx.prompt(ctx.worktree("probe"), [], 0)
    text = prompt.decode("utf8")
    assert "=== src/stats.py (sha256 %s) ===" % manifest["src/stats.py"]["sha256"] in text
    assert "def mean(" in text and "def median(" in text
    assert "CONTENT NOT RETAINED" not in text
    assert "tests/test_stats.py" in text and "class" not in text.split("Source files in scope:")[1].split("def median(")[0]


def scripted_provider(variant="correct"):
    script = fixture.script(variant)
    return {"kind": "scripted", "script": script, "provider_id": "scripted-eval"}


def test_comparators_under_scripted_provider(tmp_path):
    task = next(t for t in corpus.tasks() if t.task_id == "tp-kvparse")
    budget = comparators.Budget(model_requests=4, model_tokens_total=60000, max_input_tokens=20000, max_output_tokens=2000)
    outcomes = {}
    for system in ("provider_only", "simple_loop", "gabriel", "gabriel_no_repair"):
        ctx = comparators.EvalContext(task, tmp_path / system, scripted_provider(), budget, "trusted_local")
        outcome = comparators.RUNNERS[system](ctx, 0)
        verification = comparators.verify(ctx, outcome.worktree, "t-" + system)
        outcomes[system] = (outcome, verification)
        assert outcome.declared and verification["verified"], (system, outcome.declared_reason, verification)
        assert outcome.model_requests >= 1 and outcome.model_tokens > 0
        assert verification["changed_paths"] == ["src/kvparse.py"] and verification["head_is_base"]
    assert outcomes["provider_only"][0].model_requests == 1
    assert outcomes["simple_loop"][0].model_requests == 1 and "own check runs passed" in outcomes["simple_loop"][0].declared_reason
    assert outcomes["gabriel"][0].gabriel["replay"] == "passed" and outcomes["gabriel"][0].model_requests == 2
    assert outcomes["gabriel_no_repair"][0].plan_versions == 1


def test_false_completion_is_measured_not_hidden(tmp_path):
    """provider_only declares success on an applied patch; the fresh oracle disagrees."""
    task = next(t for t in corpus.tasks() if t.task_id == "tp-kvparse")
    budget = comparators.Budget(model_requests=2, model_tokens_total=60000, max_input_tokens=20000, max_output_tokens=2000)
    ctx = comparators.EvalContext(task, tmp_path / "po", scripted_provider("wrong_then_weaken"), budget, "trusted_local")
    outcome = comparators.run_provider_only(ctx, 0)
    verification = comparators.verify(ctx, outcome.worktree, "t-fc")
    assert outcome.declared and not verification["verified"]
    assert verification["oracle"]["exit_code"] != 0 and verification["visible"]["exit_code"] == 0


def test_protocol_freeze_and_metrics(tmp_path):
    protocol = harness.freeze(harness.default_protocol({"kind": "scripted", "model": "fixture-v1"}, repetitions=1,
                                                       systems=("provider_only", "gabriel"), backend="trusted_local"),
                              tmp_path / "protocol.json")
    assert harness.check_frozen(protocol)["frozen_digest"] == protocol["frozen_digest"]
    tampered = dict(protocol, repetitions=5)
    with pytest.raises(GabrielError):
        harness.check_frozen(tampered)
    records = []
    for task_id, family in (("a", "f1"), ("b", "f1"), ("c", "f2")):
        records.append({"task_id": task_id, "family": family, "system": "gabriel", "rep": 0, "V": 1, "D": 1, "false_completion": 0,
                        "outcome": {"model_requests": 2, "model_tokens": 1000, "wall_ms": 100, "timed_out": False, "repairs_used": 0, "plan_versions": 1, "declared_reason": "ok", "provider_statuses": []},
                        "verification": {"oracle": {"exit_code": 0}, "visible": {"exit_code": 0}, "out_of_scope_paths": []}})
        records.append({"task_id": task_id, "family": family, "system": "provider_only", "rep": 0, "V": int(task_id == "a"), "D": 1,
                        "false_completion": int(task_id != "a"),
                        "outcome": {"model_requests": 1, "model_tokens": 400, "wall_ms": 50, "timed_out": False, "repairs_used": 0, "plan_versions": 0, "declared_reason": "patched", "provider_statuses": ["completed"]},
                        "verification": {"oracle": {"exit_code": 1}, "visible": {"exit_code": 0}, "out_of_scope_paths": []}})
    results = {"records": records, "frozen_check": {"harness_amended": False}}
    rep = harness.report(results, protocol)
    g, p = rep["per_system"]["gabriel"], rep["per_system"]["provider_only"]
    assert g["p_success"] == 1.0 and g["false_completions"] == 0
    assert p["p_success"] == pytest.approx(1 / 3) and p["p_false_completion"] == pytest.approx(2 / 3)
    assert p["conditional_false_completion"] == pytest.approx(2 / 3) and p["conditional_denominator"] == 3
    assert rep["paired_differences"]["gabriel_minus_provider_only"]["mean"] == pytest.approx(2 / 3)
    assert rep["paired_differences"]["gabriel_minus_provider_only"]["ci95_by_family"]["clusters"] == 2
    assert len(rep["failures"]) == 2
    markdown = harness.render_markdown(rep, protocol)
    assert "p_success" in markdown and "provider_only" in markdown
