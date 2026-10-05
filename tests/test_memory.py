"""WP09: temporal evidence and memory (AT14, AT15, AT25) and the memory part of AT22."""
import hashlib
import json
from pathlib import Path

import pytest

from gabriel_agent.agent.backup import backup, restore
from gabriel_agent.agent.workspace import Workspace, build_registry
from gabriel_agent.artifacts import ObjectStore
from gabriel_agent.contracts import GabrielError
from gabriel_agent.contracts.codec import canonical
from gabriel_agent.memory import Frontier, MemoryService, source_key

EXTRACTION = hashlib.sha256(b"test-extractor-v1").hexdigest()
SCOPE = {"principals": ["alice"], "source_kind": "document"}


def fresh(tmp_path, name="mem"):
    store = ObjectStore.create(tmp_path / (name + "-objects"))
    clock = {"owner": 10}
    memory = MemoryService.create(tmp_path / (name + ".sqlite"), store, "ws-test", lambda: clock["owner"])
    return memory, store, clock


def ingest(memory, source_id, revision, text, received=1000, supersedes=None, **over):
    return memory.ingest(source_id=source_id, source_object_id="doc", source_revision=revision, content=text.encode("utf8"),
                         received_at_unix_ms=received, extraction_digest=EXTRACTION, scope=SCOPE, supersedes=supersedes, **over)


# ------------------------------------------------------------------ AT14 availability and correction

def test_issued_decision_keeps_its_frontier_and_correction_is_selected_once(tmp_path):
    memory, store, clock = fresh(tmp_path)
    first = ingest(memory, "policy", 1, "The notice period is thirty days.")
    frontier_at_decision = memory.frontier()
    manifest_then = memory.retrieve(principal_id="alice", task_id="t1", frontier=frontier_at_decision, query=b"notice period", allowed_source_kinds=["document"])
    assert [i["observation_id"] for i in manifest_then["items"]] == [first["observation_id"]]
    # Late evidence: older event time, ingested now. A correction: a new version linked to its predecessor.
    clock["owner"] += 5
    late = ingest(memory, "memo", 1, "Historic memo about notice periods.", event_kind="completed_observation", event_start_unix_ms=1, event_end_unix_ms=2)
    corrected = ingest(memory, "policy", 2, "The notice period is sixty days.", supersedes=first["observation_id"])
    assert late["availability_sequence"] > first["availability_sequence"] and corrected["supersedes"] == first["observation_id"]
    # Historical view: the frontier of the issued decision is unchanged, nothing leaks into it.
    historical = memory.retrieve(principal_id="alice", task_id="t1", frontier=frontier_at_decision, query=b"notice period", allowed_source_kinds=["document"])
    assert [i["observation_id"] for i in historical["items"]] == [first["observation_id"]]
    assert historical["cached"] is True and all(e["observation_id"] not in (late["observation_id"], corrected["observation_id"]) for e in historical["excluded"])
    assert memory.effective(source_key("policy", "doc"), frontier_at_decision)["observation"]["observation_id"] == first["observation_id"]
    # Current view: the correction is selected exactly once, the predecessor is excluded as superseded.
    current = memory.retrieve(principal_id="alice", task_id="t1", frontier=memory.frontier(), query=b"notice period", allowed_source_kinds=["document"])
    ids = [i["observation_id"] for i in current["items"]]
    assert ids.count(corrected["observation_id"]) == 1 and first["observation_id"] not in ids and late["observation_id"] in ids
    assert {"observation_id": first["observation_id"], "reason": "superseded"} in current["excluded"]
    assert memory.effective(source_key("policy", "doc"), memory.frontier())["observation"]["observation_id"] == corrected["observation_id"]
    # Observation records are retained unchanged (no overwrite): the issued record still resolves.
    assert memory.observation(first["observation_id"])["content_ref"] == first["content_ref"]
    # Future event time is not a reason to reject a planned observation.
    planned = ingest(memory, "calendar", 1, "Board meeting scheduled.", event_kind="future_claim", event_start_unix_ms=10**12, event_end_unix_ms=10**12 + 1)
    assert planned["event_kind"] == "future_claim" and memory.observation(planned["observation_id"]) is not None


def test_contested_and_contradictory_revisions_are_not_silently_resolved(tmp_path):
    memory, store, clock = fresh(tmp_path)
    a = ingest(memory, "policy", 3, "version A")
    b = ingest(memory, "policy", 3, "version B")
    choice = memory.effective(source_key("policy", "doc"), memory.frontier())
    assert choice["status"] == "contested" and choice["observation"] is None
    manifest = memory.retrieve(principal_id="alice", task_id=None, frontier=memory.frontier(), query=b"version", allowed_source_kinds=["document"])
    assert manifest["items"] == [] and {e["reason"] for e in manifest["excluded"]} == {"contested"}
    # a "correction" that supersedes a higher revision is contradictory
    with pytest.raises(GabrielError):
        memory.ingest(source_id="other", source_object_id="doc", source_revision=1, content=b"x", received_at_unix_ms=1, extraction_digest=EXTRACTION,
                      scope=SCOPE, supersedes=a["observation_id"])  # different source key
    c = ingest(memory, "policy", 1, "older revision claiming to supersede", supersedes=b["observation_id"])
    assert memory.effective(source_key("policy", "doc"), memory.frontier())["status"] == "unresolved"


# ------------------------------------------------------------------ AT15 retrieval conflict and access revoke

def test_retrieval_conflict_provenance_revocation_and_unassessed_claims(tmp_path):
    memory, store, clock = fresh(tmp_path)
    policy = ingest(memory, "policy", 1, "Approval threshold is 500 EUR.\n\nSecond paragraph about fees.")
    memo = ingest(memory, "memo", 1, "Approval threshold is 400 EUR according to the old memo.")
    summary = memory.ingest(source_id="summary", source_object_id="derived", source_revision=1, content=b"Derived summary: threshold 500 EUR",
                            received_at_unix_ms=1, extraction_digest=EXTRACTION, scope={"principals": ["alice"], "source_kind": "derived"})
    secret = memory.ingest(source_id="hr", source_object_id="salaries", source_revision=1, content=b"salary table", received_at_unix_ms=1,
                           extraction_digest=EXTRACTION, scope={"principals": ["bob"], "source_kind": "document"})
    manifest = memory.retrieve(principal_id="alice", task_id="t", frontier=memory.frontier(), query=b"approval threshold EUR", allowed_source_kinds=["document"])
    ids = [i["observation_id"] for i in manifest["items"]]
    # conflicting sources are both retained with provenance; the derived summary is excluded by kind; bob's source is out of scope
    assert policy["observation_id"] in ids and memo["observation_id"] in ids
    assert {"observation_id": summary["observation_id"], "reason": "kind_not_allowed"} in manifest["excluded"]
    assert {"observation_id": secret["observation_id"], "reason": "out_of_scope"} in manifest["excluded"]
    top = manifest["items"][0]
    assert top["span_end"] > top["span_start"] and store.get(top["artifact_ref"])[top["span_start"]:top["span_end"]]
    # a generated assertion is unresolved until a named verifier assesses it
    claim = memory.assert_claim(task_id="t", proposition=b"The approval threshold is 500 EUR.", scope={"principals": ["alice"]},
                                supporting=[policy["observation_id"]], refuting=[memo["observation_id"]])
    assert claim["assessment_status"] == "unresolved" and claim["assessment_id"] is None
    check = memory.verify_citations([{"observation_id": policy["observation_id"], "quote": "threshold is 500 EUR"},
                                     {"observation_id": policy["observation_id"], "quote": "threshold is 999 EUR"}], frontier=memory.frontier(), principal_id="alice")
    assert check["citations"][0]["resolved"] and check["citations"][0]["span_start"] > 0 and not check["citations"][1]["resolved"]
    assessed = memory.assess(claim["claim_id"], verifier_id="document.citations_bound", verifier_digest="0" * 64, status="contested",
                             evidence={"supporting": 1, "refuting": 1}, frontier=memory.frontier(), reason="sources disagree")
    assert memory.claim(claim["claim_id"])["assessment_status"] == "contested" and memory.claim(claim["claim_id"])["assessment_id"] == assessed["assessment_id"]
    # revocation: the item is absent from new retrieval (the cached manifest is not reused), bytes stay for audit
    revision_before = memory.access_policy_revision()
    outcome = memory.retract(memo["observation_id"], principal_id="alice", reason="memo withdrawn")
    assert memory.access_policy_revision() == revision_before + 1 and outcome["affected_claims"] == [claim["claim_id"]]
    after = memory.retrieve(principal_id="alice", task_id="t", frontier=memory.frontier(), query=b"approval threshold EUR", allowed_source_kinds=["document"])
    assert after["cached"] is False and memo["observation_id"] not in [i["observation_id"] for i in after["items"]]
    assert {"observation_id": memo["observation_id"], "reason": "revoked"} in after["excluded"]
    assert memory.content(memo) == b"Approval threshold is 400 EUR according to the old memo."
    assert memory.claim(claim["claim_id"])["assessment_status"] == "unresolved" and memory.work_items()[0]["subject"] == claim["claim_id"]
    denied = memory.verify_citations([{"observation_id": memo["observation_id"], "quote": "400 EUR"}], frontier=memory.frontier(), principal_id="alice")
    assert not denied["all_resolved"] and denied["citations"][0]["reason"] == "revoked"


# ------------------------------------------------------------------ AT25 outcome deduplication, promotion and compaction

def test_unique_outcomes_corrections_and_held_out_promotion(tmp_path):
    memory, store, clock = fresh(tmp_path)
    maturity = {"condition": "oracle executed", "window_ms": 0}
    for _ in range(3):  # repeated delivery of the same outcome counts once
        memory.record_outcome(issue_id="issue-1", run_id="run-1", source_id="proc-a", maturity_condition=maturity, outcome="success", status_kind="production")
    memory.record_outcome(issue_id="issue-2", run_id="run-2", source_id="proc-a", maturity_condition=maturity, outcome="success", status_kind="production")
    memory.record_outcome(issue_id="issue-3", run_id="run-3", source_id="proc-a", maturity_condition=maturity, outcome="failure", status_kind="production")
    memory.record_outcome(issue_id="issue-4", run_id="run-4", source_id="proc-a", maturity_condition=maturity, outcome="success", status_kind="dry_run")
    memory.record_outcome(issue_id="issue-5", run_id="run-5", source_id="proc-a", maturity_condition=maturity, outcome="success", status_kind="skipped")
    memory.record_outcome(issue_id="issue-6", run_id="run-6", source_id="proc-a", maturity_condition=maturity, outcome="success", status_kind="unreconciled")
    support = memory.effective_support("proc-a")
    assert support["support"] == 2 and support["refute"] == 1 and support["unique_outcomes"] == ["issue-1", "issue-2", "issue-3"]
    assert support["excluded"] == {"dry_run": 1, "skipped": 1, "unreconciled": 1} and support["label_records"] == 6
    assert len([e for e in memory.entries() if e["kind"] == "outcome_label"]) == 6  # the repeats never entered the chain
    with pytest.raises(GabrielError):  # the same issued outcome cannot be re-delivered with another value without a correction
        memory.record_outcome(issue_id="issue-1", run_id="run-1", source_id="proc-a", maturity_condition=maturity, outcome="failure", status_kind="production")
    # a corrected label replaces the earlier contribution and keeps the refutation history
    corrected = memory.record_outcome(issue_id="issue-2", run_id="run-2", source_id="proc-a", maturity_condition=maturity, outcome="failure",
                                      status_kind="production", supersedes="label-issue-2-r0")
    assert corrected["revision"] == 1 and corrected["supersedes"] == "label-issue-2-r0"
    support = memory.effective_support("proc-a")
    assert support["support"] == 1 and support["refute"] == 2 and len(support["unique_outcomes"]) == 3
    with pytest.raises(GabrielError):
        memory.record_outcome(issue_id="issue-9", run_id="run-9", source_id="proc-a", maturity_condition=maturity, outcome="success", status_kind="production",
                              supersedes="label-issue-2-r0")  # a correction must refer to the same issued outcome
    # promotion needs held-out evidence with disjoint families
    candidate = {"candidate_id": "policy-cand-1", "policy_kind": "retrieval-ranker", "training_manifest_ref": store.put(b"{}", "application/json"),
                 "code_identity": "a" * 64, "config_ref": store.put(b"{}", "application/json"), "metrics_ref": store.put(b"{}", "application/json"),
                 "training_families": ["text_parsing", "collections"]}
    assert memory.promote(candidate, held_out=None)["promotion"]["decision"] == "rejected"
    assert memory.promote(candidate, held_out={"source_id": "proc-a", "families": ["collections"]})["promotion"]["decision"] == "rejected"
    for n in range(3):
        memory.record_outcome(issue_id="held-%d" % n, run_id="run-h%d" % n, source_id="proc-heldout", maturity_condition=maturity, outcome="success", status_kind="production")
    promoted = memory.promote(candidate, held_out={"source_id": "proc-heldout", "families": ["validation"]})
    assert promoted["promotion"]["decision"] == "promoted" and promoted["held_out_families"] == ["validation"]


def test_compaction_keeps_required_bytes_and_missing_blob_is_a_storage_fault(tmp_path):
    memory, store, clock = fresh(tmp_path)
    obs = ingest(memory, "policy", 1, "Compaction keeps me.")
    memory.retrieve(principal_id="alice", task_id="t", frontier=memory.frontier(), query=b"keeps", allowed_source_kinds=["document"])
    memory.summarize("t", b"derived summary")
    record = memory.compact()
    assert record["status"] == "compacted" and record["required_bytes_verified"] and record["removed_derived"] == {"cache_entries": 1, "summaries": 1}
    assert record["anchors"][-1]["head"] == memory.anchor()["head"] or record["anchors"][-1]["memory_sequence"] == record["memory_sequence"]
    assert memory.verify()["status"] == "passed"
    # remove a referenced durable blob while its digest and the frontier stay declared
    Path(store.path_for(obs["content_ref"]["sha256"])).unlink()
    check = memory.verify()
    assert check["status"] == "storage_fault" and {"sha256": obs["content_ref"]["sha256"], "fault": "missing"} in check["faults"]
    with pytest.raises(GabrielError) as excinfo:
        memory.compact()
    assert excinfo.value.details["status"] == "storage_fault" and not excinfo.value.details["required_bytes_verified"]


def test_verification_reports_a_missing_chain_record_whether_or_not_it_was_loaded_before(tmp_path):
    """ADR-25: the service caches decoded records in process, and the cache never answers whether
    a record's bytes are present. A chain record whose object is gone is reported as `missing` by
    verify() and recorded as a storage fault by compact(), by the service that loaded it before
    and by a fresh service alike."""
    memory, store, clock = fresh(tmp_path)
    ingest(memory, "policy", 1, "Compaction keeps me.")
    first = memory.compact()
    assert first["status"] == "compacted"
    memory.compact()  # loads the first compaction record (now cached) to carry its anchor
    entry = memory.entries()[1]
    assert entry["kind"] == "compaction"
    sha = entry["record_sha"]
    Path(store.path_for(sha)).unlink()
    cached = memory.verify()
    assert cached["status"] == "storage_fault" and {"sha256": sha, "fault": "missing"} in cached["faults"]
    with pytest.raises(GabrielError) as excinfo:
        memory.compact()
    assert excinfo.value.details["status"] == "storage_fault" and {"sha256": sha, "fault": "missing"} in excinfo.value.details["faults"]
    memory.close()
    reopened = MemoryService.open(tmp_path / "mem.sqlite", store, lambda: clock["owner"])
    fresh_check = reopened.verify()
    assert fresh_check["status"] == "storage_fault" and fresh_check["faults"] == cached["faults"]
    reopened.close()


def test_workspace_backup_restores_memory_and_refuses_a_missing_memory_blob(tmp_path):
    ws = Workspace.create(tmp_path / "ws", backend="trusted_local", allow_trusted_local=True)
    obs = ws.memory.ingest(source_id="policy", source_object_id="doc", source_revision=1, content=b"restore me", received_at_unix_ms=1,
                           extraction_digest=EXTRACTION, scope={"principals": [ws.config["principal_id"]], "source_kind": "document"})
    anchor = ws.memory.anchor()
    manifest = backup(ws, tmp_path / "bk")
    assert manifest["memory_anchor"]["head"] == anchor["head"] and obs["content_ref"]["sha256"] in manifest["objects"]
    report = restore(tmp_path / "bk", tmp_path / "restored", catalog=build_registry(lambda: None).catalog())
    assert report["status"] == "passed" and report["memory"]["status"] == "passed" and report["memory"]["anchor_match"]
    ws.close()
    # the same backup with one memory blob removed: restore is a storage fault, not a successful compacted record
    Path(tmp_path / "bk" / "objects" / obs["content_ref"]["sha256"][:2] / obs["content_ref"]["sha256"]).unlink()
    with pytest.raises(GabrielError) as excinfo:
        restore(tmp_path / "bk", tmp_path / "restored2", catalog=build_registry(lambda: None).catalog())
    assert excinfo.value.details["object_faults"][0]["sha256"] == obs["content_ref"]["sha256"]
