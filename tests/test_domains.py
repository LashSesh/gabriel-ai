"""WP10: document and numerical DomainPacks, the contained analytical worker (AT16) and one core
across three real domain adapters (AT23)."""
import hashlib
import json
import os
from pathlib import Path

import pytest

from gabriel_agent.adapters import analytical
from gabriel_agent.agent import TaskRunner, Workspace, export_task
from gabriel_agent.agent.workspace import build_registry
from gabriel_agent.contracts import GabrielError
from gabriel_agent.contracts.codec import canonical, loads
from gabriel_agent.domains.numerical import pack as numerical
from gabriel_agent.evaluation.fixtures import document_amendment, numerical_series, parser_bug
from gabriel_agent.workers import TrustedLocalBackend
from gabriel_agent.workers.isolation import RunSpec

CONTAINMENT = os.environ.get("GABRIEL_CONTAINMENT_TESTS") == "1"


def scripted(script):
    return {"kind": "scripted", "script": script, "provider_id": "scripted-domains"}


def run_task(ws, spec, **extras):
    created = ws.create_task(spec)
    summary = TaskRunner(ws, created["task_id"], extras=extras).run()
    return created, summary


# ------------------------------------------------------------------ AT16 direct/hosted equivalence and scope

def test_direct_and_hosted_worker_agree_and_unsupported_inputs_abstain(tmp_path):
    raw = numerical_series.SERIES_TEXT.encode("utf8")
    direct = analytical.run_job("units.convert", {"to_units": "K"}, raw)
    assert direct["verdict"] == "computed" and direct["output_units"] == "K"
    assert direct["output"]["values"] == numerical_series.reference_kelvin(numerical_series.SERIES["values"])
    # hosted: the same file as a fresh worker process through a containment backend
    work = tmp_path / "work"
    (work / "data").mkdir(parents=True)
    (work / "data" / "series.json").write_bytes(raw)
    (work / ".gabriel_worker").mkdir()
    (work / ".gabriel_worker" / "worker.py").write_bytes(Path(analytical.__file__).read_bytes())
    (work / ".gabriel_worker" / "job.json").write_text(json.dumps({"operation": "units.convert", "parameters": {"to_units": "K"}, "input_path": "data/series.json",
                                                                   "output_path": "out/series_kelvin.json", "result_path": ".gabriel_worker/result.json"}))
    backend = TrustedLocalBackend()
    witness = backend.run(RunSpec(argv=["python3", ".gabriel_worker/worker.py", ".gabriel_worker/job.json"], worktree=str(work), timeout_ms=60000,
                                  max_output_bytes=1 << 20, marker="t-hosted"))
    assert witness.exit_code == 0, witness.stderr.captured
    hosted = json.loads((work / ".gabriel_worker" / "result.json").read_text())
    hosted_output = (work / "out" / "series_kelvin.json").read_bytes()
    assert hosted["verdict"] == "computed" and hosted_output == analytical.dumps(direct["output"])
    assert hosted["output_sha256"] == hashlib.sha256(analytical.dumps(direct["output"])).hexdigest()
    assert hosted["worker_build"] == numerical.worker_build() == hashlib.sha256(Path(analytical.__file__).read_bytes()).hexdigest()
    # unsupported inputs abstain or reject; none is a success and none is a transport failure
    assert analytical.run_job("units.convert", {"to_units": "km"}, raw)["verdict"] == "out_of_scope"
    assert analytical.run_job("units.convert", {"to_units": "furlong"}, raw)["verdict"] == "invalid_input"
    assert analytical.run_job("series.magic", {}, raw)["verdict"] == "invalid_input"
    assert analytical.run_job("graph.small_signature", {}, raw)["verdict"] == "out_of_scope"
    big = json.dumps({"kind": "graph", "vertices": 8, "edges": [[0, 1]]}).encode()
    assert analytical.run_job("graph.small_signature", {}, big)["verdict"] == "out_of_scope"
    nan = b'{"kind": "series", "units": "degC", "time_basis": "unix_ms", "values": [[0, "nan"]]}'
    assert analytical.run_job("units.convert", {"to_units": "K"}, nan)["verdict"] == "invalid_input"
    assert analytical.run_job("units.convert", {"to_units": "K"}, b"\x00\xff")["verdict"] == "invalid_input"


def test_signature_collision_cannot_authorize_cache_reuse():
    small = json.dumps({"kind": "graph", "vertices": 3, "edges": [[0, 1]]}).encode()
    larger = json.dumps({"kind": "graph", "vertices": 4, "edges": [[0, 1]]}).encode()
    a, b = analytical.run_job("graph.small_signature", {}, small), analytical.run_job("graph.small_signature", {}, larger)
    assert a["verdict"] == b["verdict"] == "computed"
    # the inherited padded signature collides across sizes; the retained signature keeps the vertex count
    assert a["diagnostics"]["legacy_padded_signature"] == b["diagnostics"]["legacy_padded_signature"]
    assert a["output"]["signature"] != b["output"]["signature"] and a["output"]["vertices"] != b["output"]["vertices"]
    build, env = numerical.worker_build(), analytical.numerical_environment()
    key_a = numerical.cache_key(hashlib.sha256(small).hexdigest(), "graph.small_signature", {}, build, env)
    key_b = numerical.cache_key(hashlib.sha256(larger).hexdigest(), "graph.small_signature", {}, build, env)
    assert key_a != key_b
    # the same bytes with a different build or environment do not share a key either
    assert key_a != numerical.cache_key(hashlib.sha256(small).hexdigest(), "graph.small_signature", {}, "f" * 64, env)
    assert key_a != numerical.cache_key(hashlib.sha256(small).hexdigest(), "graph.small_signature", {}, build, dict(env, python="0.0"))
    # isomorphic graphs do share the canonical signature (the structural index), with the vertex count retained
    iso = json.dumps({"kind": "graph", "vertices": 3, "edges": [[1, 2]]}).encode()
    assert analytical.run_job("graph.small_signature", {}, iso)["output"]["signature"] == a["output"]["signature"]


# ------------------------------------------------------------------ numerical slice through the owner

def test_numerical_task_runs_through_the_core_and_rejects_bad_jobs(tmp_path):
    repo = tmp_path / "repo"
    base = numerical_series.build_repo(repo)
    oracle = numerical_series.write_oracle(tmp_path / "expected.json")
    ws = Workspace.create(tmp_path / "ws", backend="trusted_local", allow_trusted_local=True)
    try:
        created, summary = run_task(ws, numerical_series.task_spec(repo, base, oracle, scripted(numerical_series.script("correct"))))
        assert summary["state"] == "succeeded", summary["log"]
        assert summary["domain"] == "numerical"
        outcomes = {a["check_id"]: a["outcome"] for a in summary["assessments"] if a["eligible"]}
        assert outcomes["reference"] == "passed" and outcomes["scope"] == "passed" and outcomes["base-commit"] == "passed"
        written = json.loads((Path(created["worktree"]) / numerical_series.OUTPUT_PATH).read_text())
        assert written["units"] == "K" and written["values"] == numerical_series.reference_kelvin(numerical_series.SERIES["values"])
        assert not (Path(created["worktree"]) / ".gabriel_worker").exists()
        manifest = export_task(ws, created["task_id"], tmp_path / "delivery")
        assert manifest["run_state"] == "succeeded" and manifest["unresolved_issues"] == []
        # a dimension mismatch is a retained out_of_scope verdict: the run fails, nothing claims success
        created2, summary2 = run_task(ws, numerical_series.task_spec(repo, base, oracle, scripted(numerical_series.script("dimension_mismatch")), max_plan_versions=1, max_repairs=0))
        assert summary2["state"] == "failed"
        failed = [a for a in summary2["assessments"] if a["check_id"] == "reference"]
        assert failed and failed[-1]["outcome"] == "failed"
        projection = ws.owner.projection(created2["run_id"])
        job_result = loads(ws.store.get(projection["nodes"]["run-job"]["outputs"]["job_result"]))
        assert job_result["status"] == "completed" and job_result["verdict"] == "out_of_scope" and job_result["output_ref"] is None
        # an undeclared operation and an out-of-scope output path are rejected before any execution
        for variant in ("unknown_operation", "out_of_scope_path", "wrong_input_kind"):
            created3, summary3 = run_task(ws, numerical_series.task_spec(repo, base, oracle, scripted(numerical_series.script(variant)), max_plan_versions=1, max_repairs=0))
            assert summary3["state"] != "succeeded", variant
            if variant != "wrong_input_kind":
                assert "run-job" not in {nid for nid, s in ws.owner.projection(created3["run_id"])["nodes"].items() if s["status"] in ("completed", "verified")}
    finally:
        ws.close()


# ------------------------------------------------------------------ document slice through the owner

def test_document_task_binds_citations_through_memory_and_rejects_unbound_claims(tmp_path):
    repo = tmp_path / "repo"
    base = document_amendment.build_repo(repo)
    oracle = document_amendment.write_oracle(tmp_path / "claims.json")
    ws = Workspace.create(tmp_path / "ws", backend="trusted_local", allow_trusted_local=True)
    try:
        created, summary = run_task(ws, document_amendment.task_spec(repo, base, oracle, scripted(document_amendment.script("correct"))))
        assert summary["state"] == "succeeded", summary["log"]
        outcomes = {a["check_id"]: a["outcome"] for a in summary["assessments"] if a["eligible"]}
        assert outcomes["citations"] == "passed" and outcomes["claims"] == "passed"
        text = (Path(created["worktree"]) / "doc" / "summary.md").read_text()
        assert "[[cite:obs-" in text and "30 days" in text
        # the worker request retained the selected observation ids and the retrieval manifest at the frontier
        projection = ws.owner.projection(created["run_id"])
        request = loads(ws.store.get(projection["nodes"]["propose"]["outputs"]["request"]))
        assert len(request["observation_ids"]) == 2
        snapshot = loads(ws.store.get(projection["run_meta"]["observed_snapshot_ref"]))
        assert snapshot["schema"] == "gabriel.document-snapshot/1" and all(s["observation_id"] for s in snapshot["sources"])
        assert ws.memory.observation(snapshot["sources"][0]["observation_id"])["source_id"] == "policy"
        # sources ingested after the run's frontier are invisible to it: a later correction does not change the issued result
        ws.memory.ingest(source_id="policy", source_object_id="sources:policy.md", source_revision=2, content=b"The notice period for members is ten (10) days.",
                         received_at_unix_ms=5, extraction_digest=hashlib.sha256(b"x").hexdigest(), scope={"principals": ["local-user"], "source_kind": "document"})
        frontier = snapshot["frontier"]
        check = ws.memory.verify_citations(document_amendment_citations(text), frontier=frontier, principal_id="local-user")
        assert check["all_resolved"]
        for variant, failing in (("uncited", "citations"), ("fabricated", "citations"), ("wrong_source", "claims")):
            created2, summary2 = run_task(ws, document_amendment.task_spec(repo, base, oracle, scripted(document_amendment.script(variant)), max_plan_versions=1, max_repairs=0))
            assert summary2["state"] == "failed", (variant, summary2["log"])
            outcomes = {a["check_id"]: a["outcome"] for a in summary2["assessments"] if a["eligible"]}
            assert outcomes.get(failing) == "failed", (variant, outcomes)
        created3, summary3 = run_task(ws, document_amendment.task_spec(repo, base, oracle, scripted(document_amendment.script("out_of_scope")), max_plan_versions=1, max_repairs=0))
        assert summary3["state"] == "failed" and (Path(created3["worktree"]) / "sources" / "policy.md").read_text() == document_amendment.POLICY
    finally:
        ws.close()


def document_amendment_citations(text):
    from gabriel_agent.domains.document.pack import parse_citations
    return parse_citations(text)


# ------------------------------------------------------------------ AT23 one core across three real domain adapters

def test_one_core_serves_three_domains_with_identical_registry(tmp_path):
    ws = Workspace.create(tmp_path / "ws", backend="trusted_local", allow_trusted_local=True)
    try:
        catalog_digest = ws.owner.catalog_digest
        assert catalog_digest == build_registry(lambda: None).catalog_digest()
        results, bindings = {}, {}
        # software
        repo_s = tmp_path / "repo-software"
        base_s = parser_bug.build_repo(repo_s)
        oracle_s = parser_bug.write_oracle(tmp_path / "oracle_kvparse.py")
        created, summary = run_task(ws, parser_bug.task_spec(repo_s, base_s, oracle_s, scripted(parser_bug.script("correct"))))
        results["software"] = summary
        bindings["software"] = loads(ws.store.get(ws.owner.projection(created["run_id"])["binding_ref"]))
        # document
        repo_d = tmp_path / "repo-document"
        base_d = document_amendment.build_repo(repo_d)
        oracle_d = document_amendment.write_oracle(tmp_path / "claims.json")
        created, summary = run_task(ws, document_amendment.task_spec(repo_d, base_d, oracle_d, scripted(document_amendment.script("correct"))))
        results["document"] = summary
        bindings["document"] = loads(ws.store.get(ws.owner.projection(created["run_id"])["binding_ref"]))
        # numerical
        repo_n = tmp_path / "repo-numerical"
        base_n = numerical_series.build_repo(repo_n)
        oracle_n = numerical_series.write_oracle(tmp_path / "expected.json")
        created, summary = run_task(ws, numerical_series.task_spec(repo_n, base_n, oracle_n, scripted(numerical_series.script("correct"))))
        results["numerical"] = summary
        bindings["numerical"] = loads(ws.store.get(ws.owner.projection(created["run_id"])["binding_ref"]))
        for domain, summary in results.items():
            assert summary["state"] == "succeeded", (domain, summary["log"])
            assert summary["domain"] == domain and summary["port_calls"] >= 1
        assert {b["domain_namespace"] for b in bindings.values()} == {"software", "document", "numerical"}
        assert len({b["pack_id"] for b in bindings.values()}) == 3
        # one journal, one catalog identity, replay without ports for every run
        replay = ws.owner.replay()
        assert replay["status"] == "passed" and replay["external_calls"] == 0
        assert ws.owner.catalog_digest == catalog_digest
        # invalid and out-of-scope inputs per domain fail through the same machinery and stay retained
        failures = {}
        _, failures["software"] = run_task(ws, dict(parser_bug.task_spec(repo_s, base_s, oracle_s, scripted(parser_bug.script("wrong_then_weaken"))), max_plan_versions=2))
        _, failures["document"] = run_task(ws, document_amendment.task_spec(repo_d, base_d, oracle_d, scripted(document_amendment.script("fabricated")), max_plan_versions=1, max_repairs=0))
        _, failures["numerical"] = run_task(ws, numerical_series.task_spec(repo_n, base_n, oracle_n, scripted(numerical_series.script("dimension_mismatch")), max_plan_versions=1, max_repairs=0))
        for domain, summary in failures.items():
            assert summary["state"] != "succeeded", domain
        with pytest.raises(GabrielError):
            ws.create_task(dict(numerical_series.task_spec(repo_n, base_n, oracle_n, scripted({})), domain="astrology"))
        assert ws.owner.replay()["status"] == "passed"
    finally:
        ws.close()


@pytest.mark.containment
@pytest.mark.skipif(not CONTAINMENT, reason="set GABRIEL_CONTAINMENT_TESTS=1 to run the numerical worker inside the namespace jail")
def test_numerical_worker_runs_inside_the_namespace_jail(tmp_path):
    repo = tmp_path / "repo"
    base = numerical_series.build_repo(repo)
    oracle = numerical_series.write_oracle(tmp_path / "expected.json")
    ws = Workspace.create(tmp_path / "ws", backend="linux_namespace")
    try:
        created, summary = run_task(ws, numerical_series.task_spec(repo, base, oracle, scripted(numerical_series.script("correct"))))
        assert summary["state"] == "succeeded", summary["log"]
        projection = ws.owner.projection(created["run_id"])
        job_result = loads(ws.store.get(projection["nodes"]["run-job"]["outputs"]["job_result"]))
        assert job_result["containment"] is True and job_result["backend_kind"] == "linux_namespace" and job_result["verdict"] == "computed"
    finally:
        ws.close()
