"""ADR-20: the associative memory layer. The native engine's walk over the co-citation graph of
supported claims re-ranks retrieval; it never adds a source the principal could not retrieve,
and without history it changes nothing."""
import hashlib
import json
import os
from pathlib import Path

import pytest

from gabriel_agent.adapters import native_graph
from gabriel_agent.agent import TaskRunner, Workspace
from gabriel_agent.artifacts import ObjectStore
from gabriel_agent.contracts.codec import loads
from gabriel_agent.evaluation.fixtures import document_association as da
from gabriel_agent.evaluation.fixtures import graph_walk as gw
from gabriel_agent.memory import MemoryService, association

NATIVE = native_graph.available()
needs_native = pytest.mark.skipif(not NATIVE, reason="native PSE executables not built")
CONTAINMENT = os.environ.get("GABRIEL_CONTAINMENT_TESTS") == "1"


def memory_with(tmp_path, sources: dict, principal="local-user"):
    store = ObjectStore.create(tmp_path / "store")
    memory = MemoryService.create(tmp_path / "index.sqlite", store, "ws-test", lambda: 0)
    ids = {}
    for source_id, text in sources.items():
        record = memory.ingest(source_id=source_id, source_object_id="sources:" + source_id, source_revision=1, content=text.encode("utf8"),
                               received_at_unix_ms=1, extraction_digest=hashlib.sha256(b"x").hexdigest(), scope={"principals": [principal], "source_kind": "document"})
        ids[source_id] = record["observation_id"]
    return store, memory, ids


def support(memory, task_id, supporting, status="supported"):
    record = memory.assert_claim(task_id=task_id, proposition=b"established in a verified run", scope={"principals": ["local-user"], "source_kind": "document"},
                                 supporting=supporting, refuting=[])
    memory.assess(record["claim_id"], verifier_id="document.citations_bound", verifier_digest="0" * 64, status=status, evidence={}, frontier=memory.frontier(), reason="test")
    return record


def retrieve(memory, query, **over):
    kwargs = dict(principal_id="local-user", task_id="t", frontier=memory.frontier(), query=query.encode("utf8"), allowed_source_kinds=["document"],
                  max_bytes=65536, max_items=16)
    kwargs.update(over)
    return memory.retrieve(**kwargs)


@needs_native
def test_history_brings_a_lexically_invisible_source_into_a_budgeted_retrieval_and_matches_the_reference(tmp_path):
    sources = {"charter": da.CHARTER, "annex": da.ANNEX}
    sources.update({"note%02d" % i: da.distractor(i) for i in range(da.DISTRACTORS)})
    store, memory, ids = memory_with(tmp_path, sources)
    try:
        plain = retrieve(memory, da.SUMMARY_GOAL, max_items=16)
        assert "annex" not in {i["source_id"] for i in plain["items"]} and "association" not in plain
        lexical_annex = next((e for e in plain["excluded"] if e["observation_id"] == ids["annex"]), None)
        assert lexical_annex is not None and lexical_annex["reason"] == "budget"
        # no history yet: the associative retrieval records that and ranks exactly like the provenance view
        empty = retrieve(memory, da.SUMMARY_GOAL, max_items=16, association=association.PROFILE)
        assert empty["association"]["status"] == "no_history" and [i["observation_id"] for i in empty["items"]] == [i["observation_id"] for i in plain["items"]]
        assert empty["cache_key"] != plain["cache_key"] and all(i["structural_milli"] == 0 for i in empty["items"])
        # a supported claim cites charter and annex together
        support(memory, "history", [ids["charter"], ids["annex"]])
        linked = retrieve(memory, da.SUMMARY_GOAL, max_items=16, association=association.PROFILE)
        record = linked["association"]
        assert record["status"] == "computed" and record["seeds"] == ["charter/sources:charter"] and set(record["entities"]) == {"charter/sources:charter", "annex/sources:annex"}
        assert record["executable_sha256"] == native_graph.binaries()["engine_observer"]["sha256"] and len(record["snapshot_identity"]) == 64
        annex = next(i for i in linked["items"] if i["source_id"] == "annex")
        # the structural score is the reference walk's mass from the charter to the annex over the co-citation graph
        batches = [[0, 1]]  # charter, annex
        mass = gw.reference_masses(batches, [(0, 1.0, 0.0), (1, 0.0, 0.0)], [1], [1.0])[0]
        assert abs(annex["structural_milli"] - association.milli(mass)) <= 1 and annex["score_milli"] == annex["structural_milli"] > 0
        assert record["masses_milli"]["annex/sources:annex"] == annex["structural_milli"]
        # distractors keep their lexical scores, and the annex now outranks them
        notes = [i for i in linked["items"] if i["source_id"].startswith("note")]
        assert notes and all(i["structural_milli"] == 0 and i["score_milli"] < annex["score_milli"] for i in notes)
        assert linked["items"][0]["source_id"] == "charter"
        # retrieval at a frontier before the claim ignores it
        before = retrieve(memory, da.SUMMARY_GOAL, max_items=16, association=association.PROFILE, frontier=plain["frontier"])
        assert before["association"]["status"] == "no_history" and "annex" not in {i["source_id"] for i in before["items"]}
    finally:
        memory.close()


@needs_native
def test_association_never_reaches_what_the_principal_cannot_retrieve(tmp_path):
    store, memory, ids = memory_with(tmp_path, {"charter": da.CHARTER, "annex": da.ANNEX, "secret": "# Private\n\nBoard remuneration: 5000 EUR.\n"})
    try:
        other = memory.ingest(source_id="foreign", source_object_id="sources:foreign", source_revision=1, content=b"# Foreign\n\nAnother principal's note.\n",
                              received_at_unix_ms=2, extraction_digest=hashlib.sha256(b"x").hexdigest(), scope={"principals": ["someone-else"], "source_kind": "document"})
        support(memory, "history", [ids["charter"], ids["annex"], ids["secret"], other["observation_id"]])
        memory.revoke(ids["secret"], principal_id="local-user", reason="declared private")
        manifest = retrieve(memory, da.SUMMARY_GOAL, association=association.PROFILE)
        retrieved = {i["source_id"] for i in manifest["items"]}
        assert "annex" in retrieved and "secret" not in retrieved and "foreign" not in retrieved
        reasons = {e["observation_id"]: e["reason"] for e in manifest["excluded"]}
        assert reasons[ids["secret"]] == "revoked" and reasons[other["observation_id"]] == "out_of_scope"
        # the walk ran over the history (four entities) but mass was read out for retrievable candidates only
        record = manifest["association"]
        assert len(record["entities"]) == 4 and set(record["masses_milli"]) <= {"charter/sources:charter", "annex/sources:annex"}
        # an unsupported claim is not history
        memory2_store, memory2, ids2 = memory_with(tmp_path / "two", {"charter": da.CHARTER, "annex": da.ANNEX})
        try:
            support(memory2, "history", [ids2["charter"], ids2["annex"]], status="unresolved")
            assert retrieve(memory2, da.SUMMARY_GOAL, association=association.PROFILE)["association"]["status"] == "no_history"
        finally:
            memory2.close()
    finally:
        memory.close()


def test_structural_scores_declare_their_limits():
    profile = dict(association.PROFILE, max_entities=4)
    masses, record = association.structural_scores([], ["a"], ["a"], profile)
    assert masses == {} and record["status"] == "no_history"
    masses, record = association.structural_scores([["a", "b"]], [], ["a", "b"], profile)
    assert record["status"] == "no_seeds"
    masses, record = association.structural_scores([["a", "b"]], ["z"], ["a", "b"], profile)
    assert record["status"] == "no_seeds_in_history" and record["entities"] == ["a", "b"]
    big = [["a", "b"], ["c", "d"], ["e", "f"]]
    masses, record = association.structural_scores(big, ["a"], ["a", "b", "f"], profile, binaries={})
    assert record["status"] == "unavailable" and record["entities"] == ["a", "b"]  # one hop around the seed keeps it within the cap
    masses, record = association.structural_scores([["a", "b", "c", "d", "e"]], ["a"], ["a"], profile, binaries={})
    assert record["status"] == "capacity_exceeded"


@needs_native
def test_verified_run_history_carries_the_annex_into_the_associative_view_through_the_owner(tmp_path):
    repo = tmp_path / "repo"
    base = da.build_repo(repo)
    ws = Workspace.create(tmp_path / "ws", backend="trusted_local", allow_trusted_local=True)
    try:
        # without history the associative view behaves like provenance: the annex is not retrieved and the scripted citation cannot resolve
        created, summary = run(ws, da.summary_spec(repo, base, da.summary_oracle(tmp_path / "summary.json"), da.provider("summary"), view="associative",
                                                   max_plan_versions=1, max_repairs=0))
        assert summary["state"] == "failed"
        manifest = retrieval_manifest(ws, created)
        assert manifest["association"]["status"] in ("no_history", "no_seeds_in_history") and "annex" not in {i["source_id"] for i in manifest["items"]}
        # the history task: a verified deliverable citing charter and annex becomes a supported claim
        created_h, summary_h = run(ws, da.history_spec(repo, base, da.history_oracle(tmp_path / "history.json"), da.provider("history")))
        assert summary_h["state"] == "succeeded", summary_h["log"]
        claims = [row for row in ws.memory._db.execute("SELECT status, supporting FROM claims").fetchall()]
        assert claims and all(status == "supported" for status, _ in claims)
        assert any("claim" in line for line in summary_h["log"])
        # now the associative view carries the annex and the summary task succeeds; the provenance view still cannot
        created_a, summary_a = run(ws, da.summary_spec(repo, base, da.summary_oracle(tmp_path / "summary.json"), da.provider("summary"), view="associative"))
        assert summary_a["state"] == "succeeded", summary_a["log"]
        manifest = retrieval_manifest(ws, created_a)
        assert manifest["association"]["status"] == "computed" and "annex" in {i["source_id"] for i in manifest["items"]}
        assert manifest["association"]["seeds"][0].startswith("charter/")
        text = (Path(created_a["worktree"]) / da.SUMMARY_TARGET).read_text()
        assert "120 EUR" in text and "[[cite:obs-" in text
        outcomes = {a["check_id"]: a["outcome"] for a in summary_a["assessments"] if a["eligible"]}
        assert outcomes["citations"] == "passed" and outcomes["claims"] == "passed"
        created_p, summary_p = run(ws, da.summary_spec(repo, base, da.summary_oracle(tmp_path / "summary.json"), da.provider("summary"), view="provenance",
                                                       max_plan_versions=1, max_repairs=0))
        assert summary_p["state"] == "failed"
        assert "annex" not in {i["source_id"] for i in retrieval_manifest(ws, created_p)["items"]}
        assert ws.owner.replay()["status"] == "passed" and ws.memory.verify()["status"] == "passed"
    finally:
        ws.close()


@needs_native
@pytest.mark.parametrize("name", ["fee", "parking", "archive", "library", "garden"])
def test_every_association_topic_meets_the_protocol_precondition_under_the_pack_budget(tmp_path, name):
    """For every topic of the corpus tier, under the document pack's budget of 32 items: the
    provenance view keeps the visible source first and drops the hidden one; with the history
    claim the associative view carries the hidden source to the second rank. This is the
    precondition protocol 6 relies on, executed through the service rather than assumed (run 6 of
    the protocol was lost to distractors that tied with the visible source; see corpus_domains)."""
    from gabriel_agent.evaluation import corpus_domains as cd
    topic = next(t for t in cd.ASSOCIATION_TOPICS if t[0] == name)
    _, (vid, _, vtext, _, _), (hid, htext, _, _), ask, _ = topic
    goal = cd._association_goal("doc/summary.md", ask)
    goal_u = cd._association_goal("doc/summary.md", "the %s's rule only, as written in the %s" % (vid, vid))
    sources = {vid: vtext, hid: htext}
    sources.update({"note%02d" % i: cd._association_distractor(i) for i in range(cd.ASSOCIATION_DISTRACTORS)})
    store, memory, ids = memory_with(tmp_path, sources)
    try:
        for query in (goal, goal_u):
            plain = retrieve(memory, query, max_items=32)
            assert plain["items"][0]["source_id"] == vid and len(plain["items"]) == 32
            assert hid not in {i["source_id"] for i in plain["items"]}
            assert plain["items"][0]["score_milli"] > max(i["score_milli"] for i in plain["items"][1:]) > 0
        support(memory, "history", [ids[vid], ids[hid]])
        for query in (goal, goal_u):
            linked = retrieve(memory, query, max_items=32, association=association.PROFILE)
            assert linked["association"]["status"] == "computed" and linked["association"]["seeds"][0].startswith(vid + "/")
            assert [i["source_id"] for i in linked["items"][:2]] == [vid, hid]
            assert linked["items"][1]["structural_milli"] > max(i["score_milli"] for i in linked["items"][2:])
    finally:
        memory.close()


def run(ws, spec):
    created = ws.create_task(spec)
    return created, TaskRunner(ws, created["task_id"]).run()


def retrieval_manifest(ws, created) -> dict:
    projection = ws.owner.projection(created["run_id"])
    snapshot = loads(ws.store.get(projection["run_meta"]["observed_snapshot_ref"]))
    return loads(ws.store.get(snapshot["retrieval_manifest_ref"]))


def test_association_tier_runs_through_the_frozen_harness_with_history(tmp_path):
    """The harness runs a task's history first; the associative arm then reaches the hidden source
    while the matched provenance arm cannot (scripted provider, same deliverable for both)."""
    pytest.importorskip("flint")
    if not NATIVE:
        pytest.skip("native PSE executables not built")
    from gabriel_agent.evaluation import corpus_domains as cd, harness
    task = cd.task_named("da-fee")
    assert task.history == ("dh-fee",) and cd.task_named("dh-fee").role == "history"
    provider = {"kind": "scripted", "provider_id": "scripted-association-harness",
                "script": {"by_step": {"plan-request": [{"kind": "echo_reference"}]}, "by_role": {"planner": [{"kind": "echo_reference"}], "worker": cd.history_worker_steps(task)}}}
    protocol = harness.default_protocol(provider, repetitions=1, systems=["gabriel_reference_plan", "gabriel_associative"], backend="trusted_local",
                                        task_ids=[task.task_id], tiers=["association"], note="scripted association self-test")
    assert [row["task_id"] for row in protocol["tasks"]] == ["da-fee"]  # history tasks are never units
    frozen = harness.freeze(protocol, tmp_path / "protocol.json")
    results = harness.run(frozen, tmp_path / "run", provider, workers=1)
    by_system = {r["system"]: r for r in results["records"]}
    assert by_system["gabriel_associative"]["V"] == 1 and by_system["gabriel_associative"]["D"] == 1
    # the provenance arm never sees the hidden source: its citation cannot resolve and the run fails (D = 0). The scripted
    # worker knows the hidden text, so the content-based verification may still pass; a real model has no such knowledge.
    assert by_system["gabriel_reference_plan"]["D"] == 0
    for record in by_system.values():
        assert any(line.startswith("history dh-fee: succeeded") for line in record["outcome"]["log"]), record["outcome"]["log"][:3]
    report = harness.report(results, frozen)
    assert report["per_system"]["gabriel_associative"]["declared_successes"] == 1 and report["per_system"]["gabriel_reference_plan"]["declared_successes"] == 0
