"""Protocol 5 (ADR-16): document and numerical evaluation corpora with executed controls, the
declared memory ablations (revision rule, provenance filtering) and the matched comparators for
the two families, all with the scripted provider."""
import hashlib
import json
from pathlib import Path

import pytest

from gabriel_agent.agent import TaskRunner, Workspace
from gabriel_agent.contracts import GabrielError
from gabriel_agent.contracts.codec import loads
from gabriel_agent.evaluation import corpus_domains as cd
from gabriel_agent.memory import MemoryService
from gabriel_agent.artifacts import ObjectStore


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf8")).hexdigest()


def task_named(task_id: str) -> cd.DomainTask:
    return next(t for t in cd.DOMAIN_TASKS if t.task_id == task_id)


def cd_digest_of(tiers):
    from gabriel_agent.evaluation import corpus
    return corpus.corpus_digest(tiers)


def scripted(worker_steps, planner=None):
    planner = planner or [{"kind": "echo_reference"}]
    return {"kind": "scripted", "provider_id": "scripted-p5", "script": {"by_step": {"plan-request": planner}, "by_role": {"planner": planner, "worker": worker_steps}}}


def amendment(task: cd.DomainTask, content: str, rationale="scripted amendment") -> dict:
    target = task.targets[0]
    # the identity is resolved from the prompt at request time, so a repair round names the file as it then stands
    return {"kind": "template", "value": {"operations": [{"kind": "modify", "path": target, "expected_sha256": "{{sha:%s}}" % target, "content": content}],
                                          "rationale": rationale}}


def prompt_text(ws, run_id: str, node: str) -> str:
    projection = ws.owner.projection(run_id)
    request = loads(ws.store.get(projection["nodes"][node]["outputs"]["request"]))
    return ws.store.get(request["prompt_ref"]).decode("utf8")


def run_gabriel(tmp_path, name, task, worker_steps, *, view="provenance", max_repairs=0):
    repo = tmp_path / name / "repo"
    base = cd.materialize(task, repo)
    oracle = cd.write_oracle(task, tmp_path / name)
    ws = Workspace.create(tmp_path / name / "ws", backend="trusted_local", allow_trusted_local=True)
    try:
        spec = cd.task_spec(task, repo, base, oracle, scripted(worker_steps), {"model_tokens_total": 200000, "model_requests": 12},
                            planner_mode="reference", max_repairs=max_repairs, max_plan_versions=max_repairs + 1, retrieval_view=view)
        created = ws.create_task(spec)
        summary = TaskRunner(ws, created["task_id"]).run()
        return ws, created, summary
    except Exception:
        ws.close()
        raise


# ------------------------------------------------------------------ corpus invariants

def test_domain_corpus_controls_execute_and_tiers_are_complete():
    report = cd.check_all()
    assert len(report) == 43 and all(r["sound"] for r in report), [(r["task_id"], r["controls"]) for r in report if not r["sound"]]
    assert {t.family for t in cd.tasks("document")} == {"revision", "revoked", "conflict"}
    assert {t.family for t in cd.tasks("numerical")} == {"units", "resample", "graph"}
    assert {t.family for t in cd.tasks("graph")} == {"graph-snapshot", "graph-mass", "graph-window", "graph-readout", "graph-detections"} and len(cd.tasks("numerical")) == 9
    assert {t.family for t in cd.tasks("association")} == {"association-history", "association-needed", "association-needed-held-out", "association-unneeded", "association-none"}
    assert all(t.role == "history" for t in cd.tasks("association") if t.family == "association-history")
    assert all(t.history == ("dh-" + t.task_id[3:],) for t in cd.tasks("association") if t.family in ("association-needed", "association-needed-held-out", "association-unneeded"))
    # every task has at least one positive and one negative executed control
    for r in report:
        verdicts = {c["expected_verified"] for c in r["controls"].values()}
        assert verdicts == {True, False}
    # the reference computations are independent code: the graph signature agrees with the adapter on the same input
    from gabriel_agent.adapters import analytical
    task = task_named("ng-cycle")
    graph = json.loads(task.files_map()["data/graph.json"])
    direct = analytical.run_job("graph.small_signature", {}, task.files_map()["data/graph.json"].encode("utf8"))
    assert direct["output"]["signature"] == task.oracle["signature"] == cd.ref_signature(graph["vertices"], graph["edges"])
    assert cd.ref_signature(5, [[0, 1], [1, 2], [2, 3], [3, 4]]) != task.oracle["signature"]


def test_independent_document_verification_is_content_based(tmp_path):
    task = task_named("dr-notice")
    root = tmp_path / "root"
    cd.write_files(root, task.files_map())
    target = task.targets[0]
    # a citation whose quote only exists in the stale revision binds nowhere available for the claim and fails the forbidden rule
    stale = "# Membership summary\n\nThe notice period for members is 30 days. [[cite:obs-x \"thirty (30) days\"]]\n\n" \
            "The expense approval threshold is 500 EUR per single expense. [[cite:obs-y \"the expense approval threshold is 500 EUR\"]]\n"
    cd.write_files(root, {target: stale})
    outcome = cd.verify_document(task, root)
    assert not outcome["verified"] and any("forbidden" in p for p in outcome["problems"]) and any("not cited" in p for p in outcome["problems"])
    # observation ids are not interpreted: any id with a verbatim quote of an available source binds
    correct = stale.replace("30 days", "45 days").replace("thirty (30) days", "forty-five (45) days")
    cd.write_files(root, {target: correct})
    assert cd.verify_document(task, root)["verified"]
    # a change outside the scope fails even with a correct amendment
    cd.write_files(root, {"sources/memo.md": "edited"})
    outcome = cd.verify_document(task, root)
    assert not outcome["verified"] and outcome["out_of_scope_paths"] == ["sources/memo.md"]


# ------------------------------------------------------------------ memory: the revision rule is an explicit, declared ablation

def test_all_revisions_policy_is_a_declared_ablation_that_keeps_authorization(tmp_path):
    store = ObjectStore.create(tmp_path / "store")
    memory = MemoryService.create(tmp_path / "memory.sqlite", store, "ws-test", lambda: 7)
    scope = {"principals": ["p"], "source_kind": "document", "task_id": "t"}
    r1 = memory.ingest(source_id="policy", source_object_id="policy.md", source_revision=1, content=b"notice period thirty (30) days", received_at_unix_ms=1,
                       extraction_digest=sha("x"), scope=scope)
    r2 = memory.ingest(source_id="policy", source_object_id="policy.md", source_revision=2, content=b"notice period forty-five (45) days", received_at_unix_ms=2,
                       extraction_digest=sha("x"), scope=scope)
    draft = memory.ingest(source_id="draft", source_object_id="draft.md", source_revision=1, content=b"notice period ten (10) days", received_at_unix_ms=3,
                          extraction_digest=sha("x"), scope=scope)
    memory.revoke(draft["observation_id"], principal_id="p", reason="withdrawn")
    frontier = memory.frontier()
    effective = memory.retrieve(principal_id="p", task_id="t", frontier=frontier, query=b"notice period", allowed_source_kinds=["document"])
    assert [i["observation_id"] for i in effective["items"]] == [r2["observation_id"]]
    assert {(e["observation_id"], e["reason"]) for e in effective["excluded"]} == {(r1["observation_id"], "superseded"), (draft["observation_id"], "revoked")}
    everything = memory.retrieve(principal_id="p", task_id="t", frontier=frontier, query=b"notice period", allowed_source_kinds=["document"],
                                 version_policy="all_revisions")
    assert everything["version_policy"] == "all_revisions"
    assert {i["observation_id"] for i in everything["items"]} == {r1["observation_id"], r2["observation_id"]}
    assert {(e["observation_id"], e["reason"]) for e in everything["excluded"]} == {(draft["observation_id"], "revoked")}
    assert everything["cache_key"] != effective["cache_key"]
    with pytest.raises(GabrielError):
        memory.retrieve(principal_id="p", task_id="t", frontier=frontier, query=b"x", allowed_source_kinds=["document"], version_policy="latest_whatever")
    memory.close()


# ------------------------------------------------------------------ document pack: declared views and revocations

def test_provenance_view_hides_the_stale_revision_and_the_other_views_show_it(tmp_path):
    task = task_named("dr-notice")
    correct = ("# Membership summary\n\nThe notice period for members is 45 days. [[cite:{{obs:policy@2}} \"forty-five (45) days\"]]\n\n"
               "The expense approval threshold is 500 EUR per single expense. [[cite:{{obs:memo}} \"the expense approval threshold is 500 EUR\"]]\n")
    ws, created, summary = run_gabriel(tmp_path, "prov", task, [amendment(task, correct)])
    try:
        prompt = prompt_text(ws, created["run_id"], "propose")
        assert "source policy revision 2 observation" in prompt and "source policy revision 1 observation" not in prompt
        assert "thirty (30) days" not in prompt and "forty-five (45) days" in prompt
        assert "superseded" in prompt  # the exclusion is stated with its reason
        assert summary["state"] == "succeeded", summary["log"]
        assert cd.verify_document(task, Path(created["worktree"]))["verified"]
        snapshot = loads(ws.store.get(ws.owner.projection(created["run_id"])["run_meta"]["observed_snapshot_ref"]))
        assert snapshot["retrieval_view"] == "provenance" and all(s["access"] == "available" for s in snapshot["sources"])
    finally:
        ws.close()
    ws, created, summary = run_gabriel(tmp_path, "allrev", task, [amendment(task, correct)], view="all_revisions")
    try:
        prompt = prompt_text(ws, created["run_id"], "propose")
        assert "source policy revision 1 observation" in prompt and "source policy revision 2 observation" in prompt
        assert "thirty (30) days" in prompt and "forty-five (45) days" in prompt
        assert summary["state"] == "succeeded", summary["log"]
        manifest = loads(ws.store.get(loads(ws.store.get(ws.owner.projection(created["run_id"])["run_meta"]["observed_snapshot_ref"]))["retrieval_manifest_ref"]))
        assert manifest["version_policy"] == "all_revisions"
    finally:
        ws.close()
    plain_correct = correct.replace("{{obs:policy@2}}", "{{obs:file:sources/policy-2026.md}}").replace("{{obs:memo}}", "{{obs:file:sources/memo.md}}")
    ws, created, summary = run_gabriel(tmp_path, "plain", task, [amendment(task, plain_correct)], view="plain")
    try:
        prompt = prompt_text(ws, created["run_id"], "propose")
        assert "file sources/policy-2025.md observation" in prompt and "file sources/policy-2026.md observation" in prompt
        assert "source policy revision" not in prompt and "thirty (30) days" in prompt
        assert summary["state"] == "succeeded", summary["log"]
        assert cd.verify_document(task, Path(created["worktree"]))["verified"]
    finally:
        ws.close()


def test_revoked_source_is_excluded_by_provenance_and_caught_by_verification_in_the_plain_view(tmp_path):
    task = task_named("dv-retention")
    correct = ("# Records summary\n\nFinancial records are retained for 5 years after the end of the financial year. [[cite:{{obs:policy}} \"five (5) years\"]]\n\n"
               "Backups are taken weekly and verified by restore. [[cite:{{obs:audit}} \"taken weekly and verified by restore\"]]\n")
    ws, created, summary = run_gabriel(tmp_path, "prov", task, [amendment(task, correct)])
    try:
        prompt = prompt_text(ws, created["run_id"], "propose")
        assert "two (2) years" not in prompt and "is not available: revoked" in prompt
        assert summary["state"] == "succeeded", summary["log"]
        snapshot = loads(ws.store.get(ws.owner.projection(created["run_id"])["run_meta"]["observed_snapshot_ref"]))
        memo = next(s for s in snapshot["sources"] if s["source_id"] == "memo")
        assert memo["access"] == "revoked" and ws.memory.is_revoked(memo["observation_id"])
        assert ws.memory.observation(memo["observation_id"]) is not None  # retained for audit
    finally:
        ws.close()
    # plain view: the withdrawn memo is in the prompt; citing it fails the independent checks; the repair cycle recovers
    cites_memo = ("# Records summary\n\nFinancial records are retained for 2 years. [[cite:{{obs:file:sources/memo_2026-10-20.md}} \"reduced to two (2) years\"]]\n\n"
                  "Backups are taken weekly and verified by restore. [[cite:{{obs:file:sources/audit_note.md}} \"taken weekly and verified by restore\"]]\n")
    plain_correct = correct.replace("{{obs:policy}}", "{{obs:file:sources/records_policy.md}}").replace("{{obs:audit}}", "{{obs:file:sources/audit_note.md}}")
    ws, created, summary = run_gabriel(tmp_path, "plain0", task, [amendment(task, cites_memo), amendment(task, plain_correct)], view="plain", max_repairs=0)
    try:
        prompt = prompt_text(ws, created["run_id"], "propose")
        assert "two (2) years" in prompt and "not available" not in prompt
        assert summary["state"] == "failed", summary["log"]
        outcomes = {a["check_id"]: a["outcome"] for a in summary["assessments"] if a["eligible"]}
        assert outcomes["citations"] == "failed" and outcomes.get("claims") in (None, "failed")  # the owner may stop at the first failed mandatory check
        outcome = cd.verify_document(task, Path(created["worktree"]))
        assert not outcome["verified"] and any("revoked" in p for p in outcome["problems"])
    finally:
        ws.close()
    ws, created, summary = run_gabriel(tmp_path, "plain1", task, [amendment(task, cites_memo), amendment(task, plain_correct)], view="plain", max_repairs=1)
    try:
        assert summary["state"] == "succeeded" and summary["repair_count"] == 1, summary["log"]
        assert cd.verify_document(task, Path(created["worktree"]))["verified"]
        repair_prompt = prompt_text(ws, created["run_id"], "propose-r1")
        assert "revoked" in repair_prompt  # the diagnostic names the reason
    finally:
        ws.close()


# ------------------------------------------------------------------ matched comparators through the frozen harness

def _document_script():
    """One worker script for every system on dv-retention: the first response cites the withdrawn memo
    (plain file view, as the baselines and the plain ablation see it), the second is correct."""
    task = task_named("dv-retention")
    cites_memo = ("# Records summary\n\nFinancial records are retained for 2 years. [[cite:{{obs:file:sources/memo_2026-10-20.md}} \"reduced to two (2) years\"]]\n\n"
                  "Backups are taken weekly and verified by restore. [[cite:{{obs:file:sources/audit_note.md}} \"taken weekly and verified by restore\"]]\n")
    correct_plain = ("# Records summary\n\nFinancial records are retained for 5 years after the end of the financial year. "
                     "[[cite:{{obs:file:sources/records_policy.md}} \"five (5) years\"]]\n\nBackups are taken weekly and verified by restore. "
                     "[[cite:{{obs:file:sources/audit_note.md}} \"taken weekly and verified by restore\"]]\n")
    return task, [amendment(task, cites_memo), amendment(task, correct_plain)]


def test_document_comparators_run_through_the_frozen_harness(tmp_path):
    from gabriel_agent.evaluation import harness
    task, worker = _document_script()
    provider = scripted(worker)
    protocol = harness.default_protocol(provider, repetitions=1, systems=("provider_only", "simple_loop", "gabriel_plain_sources"), backend="trusted_local",
                                        task_ids=[task.task_id], tiers=["document"], note="scripted protocol 5 self-test")
    assert protocol["tiers"] == ["document"] and protocol["corpus_digest"] == cd_digest_of(["document"])
    frozen = harness.freeze(protocol, tmp_path / "protocol.json")
    results = harness.run(frozen, tmp_path / "run", provider, workers=1)
    by_system = {r["system"]: r for r in results["records"]}
    assert set(by_system) == {"provider_only", "simple_loop", "gabriel_plain_sources"}
    # provider only: applied the memo-citing amendment and declared done -> false completion under content verification
    po = by_system["provider_only"]
    assert po["D"] == 1 and po["V"] == 0 and po["false_completion"] == 1
    assert any("revoked" in p for p in po["verification"]["problems"])
    # simple loop: its own run of the independent checks rejects the first answer, the second passes
    sl = by_system["simple_loop"]
    assert sl["V"] == 1 and sl["D"] == 1 and sl["outcome"]["model_requests"] == 2
    # plain ablation of Gabriel: the owner's citation check fails the first round; the repair succeeds
    gp = by_system["gabriel_plain_sources"]
    assert gp["V"] == 1 and gp["D"] == 1 and gp["outcome"]["repairs_used"] == 1
    assert gp["outcome"]["gabriel"]["replay"] == "passed"
    rep = harness.report(results, frozen)
    assert rep["per_system"]["provider_only"]["false_completions"] == 1 and rep["per_system"]["simple_loop"]["p_success"] == 1.0
    text = harness.render_markdown(rep, frozen)
    assert "problems" in text and "provider_only" in text


def test_provenance_arm_solves_the_revoked_task_in_one_request_through_the_harness(tmp_path):
    from gabriel_agent.evaluation import harness
    task = task_named("dv-retention")
    correct = ("# Records summary\n\nFinancial records are retained for 5 years after the end of the financial year. [[cite:{{obs:policy}} \"five (5) years\"]]\n\n"
               "Backups are taken weekly and verified by restore. [[cite:{{obs:audit}} \"taken weekly and verified by restore\"]]\n")
    provider = scripted([amendment(task, correct)])
    protocol = harness.default_protocol(provider, repetitions=1, systems=("gabriel_reference_plan", "gabriel_all_revisions"), backend="trusted_local",
                                        task_ids=[task.task_id], tiers=["document"])
    frozen = harness.freeze(protocol, tmp_path / "protocol.json")
    results = harness.run(frozen, tmp_path / "run", provider, workers=1)
    for r in results["records"]:
        assert r["V"] == 1 and r["D"] == 1 and r["outcome"]["repairs_used"] == 0 and r["outcome"]["model_requests"] == 1, r["system"]
    # the view ablations are not applicable to numerical tasks: the harness runs no such unit
    numerical = task_named("nu-kelvin")
    protocol2 = harness.default_protocol(provider, repetitions=1, systems=("gabriel_reference_plan", "gabriel_plain_sources"), backend="trusted_local",
                                         task_ids=[numerical.task_id], tiers=["numerical"])
    frozen2 = harness.freeze(protocol2, tmp_path / "protocol2.json")
    assert harness.check_frozen(frozen2)["frozen_digest"] == frozen2["frozen_digest"]
    from gabriel_agent.evaluation import comparators_domains
    assert not comparators_domains.applicable("gabriel_plain_sources", numerical) and comparators_domains.applicable("gabriel_plain_sources", task)


def test_numerical_comparators_run_through_the_frozen_harness(tmp_path):
    from gabriel_agent.evaluation import harness
    task = task_named("nu-kelvin")
    data = task.files_map()["data/series.json"]
    job = {"kind": "value", "value": {"operation": "units.convert", "input_path": "data/series.json", "expected_sha256": sha(data),
                                      "output_path": "out/converted.json", "parameters": {"to_units": "K"}, "rationale": "convert to kelvin"}}
    wrong = {"kind": "value", "value": dict(job["value"], parameters={"to_units": "degF"}, rationale="wrong target unit")}
    provider = scripted([wrong, job])
    protocol = harness.default_protocol(provider, repetitions=1, systems=("provider_only", "simple_loop", "gabriel_reference_plan"), backend="trusted_local",
                                        task_ids=[task.task_id], tiers=["numerical"])
    frozen = harness.freeze(protocol, tmp_path / "protocol.json")
    results = harness.run(frozen, tmp_path / "run", provider, workers=1)
    by_system = {r["system"]: r for r in results["records"]}
    po, sl, gr = by_system["provider_only"], by_system["simple_loop"], by_system["gabriel_reference_plan"]
    assert po["D"] == 1 and po["V"] == 0 and po["false_completion"] == 1 and any("units" in p for p in po["verification"]["problems"])
    assert sl["V"] == 1 and sl["outcome"]["model_requests"] == 2
    assert gr["V"] == 1 and gr["outcome"]["repairs_used"] == 1 and gr["outcome"]["gabriel"]["replay"] == "passed"
    # the output written by the uncontained baseline and by the contained worker are the same bytes
    assert (Path(sl["outcome"]["worktree"]) / "out" / "converted.json").read_bytes() == (Path(gr["outcome"]["worktree"]) / "out" / "converted.json").read_bytes()
    rep = harness.report(results, frozen)
    pair = rep["paired_differences"]["gabriel_reference_plan_minus_provider_only"]
    assert pair["mean"] == 1.0 and pair["mean_requests"] == 1.0
