"""G3 route: progress channels, the reference recurrent map, the readout router, episodic
retrieval and the per-task policy pin (blueprint routing feature experiment, ADR-15)."""
import json
from pathlib import Path

import pytest

from gabriel_agent.agent import TaskRunner, Workspace
from gabriel_agent.contracts import GabrielError
from gabriel_agent.contracts.codec import loads
from gabriel_agent.evaluation.fixtures import parser_bug
from gabriel_agent.policy import features as progress
from gabriel_agent.policy import recurrent, router


def scripted(script):
    return {"kind": "scripted", "script": script, "provider_id": "scripted-policy"}


# ------------------------------------------------------------------ channels and recurrent map

def test_recurrent_reference_map_is_bounded_and_rejects_bad_inputs():
    config = recurrent.default_config(units=8, parents=3, channels=4, seed=7)
    events = [[0.5, 0.1, 0.9, 0.0], [1.0, 1.0, 1.0, 1.0], [0.0, 0.2, 0.4, 0.6]] * 20
    out = recurrent.extract(config, events)
    assert out["bounded"] and out["steps"] == 60 and len(out["features"]) == 8 + 1 + 1
    assert out["config_digest"] == recurrent.config_digest(config)
    again = recurrent.extract(config, events)
    assert again["features_milli"] == out["features_milli"]  # deterministic from the known initial state
    trace_only = recurrent.extract(recurrent.default_config(units=8, parents=3, channels=4, seed=7, profile="trace_only"), events)
    assert trace_only["config_digest"] != out["config_digest"] and trace_only["bounded"]
    with pytest.raises(GabrielError):
        recurrent.extract(config, events, expected_config_digest="0" * 64)
    with pytest.raises(GabrielError):
        recurrent.extract(config, events + [None])
    with pytest.raises(GabrielError):
        recurrent.extract(config, events + [[0.1, 0.2, 0.3]])
    with pytest.raises(GabrielError):
        recurrent.extract(config, events + [[float("nan"), 0.0, 0.0, 0.0]])
    assert isinstance(recurrent.contraction_load(config)["holds"], bool)


def test_training_reduces_decision_loss_and_router_decides():
    # synthetic explicit outcomes: repairs succeed when enough budget remains and failures were few
    samples = []
    for i in range(60):
        remaining = (i % 10) / 10.0
        failures = ((i * 7) % 10) / 10.0
        label = 1 if remaining > 0.5 and failures < 0.6 else 0
        vector = [0.0] * 24
        vector[progress.CHANNELS.index("requests_remaining")] = remaining
        vector[progress.CHANNELS.index("recent_failure_fraction")] = failures
        samples.append((vector, label))
    fit = router.train_logistic(samples, iterations=300)
    rule = router.rule_based()
    loss_rule = router.log_loss(rule, samples)
    loss_fit = router.log_loss((fit["weights"], fit["bias"]), samples)
    assert loss_fit["log_loss"] < loss_rule["log_loss"] and loss_fit["accuracy"] > loss_rule["accuracy"]
    policy = router.readout_policy("readout-test", feature_source="channels", weights=fit["weights"], bias=fit["bias"], threshold_milli=500)
    good = {"schema": "gabriel.progress-channels/1", "channel_schema_id": progress.CHANNEL_SCHEMA_ID, "names": list(progress.CHANNELS),
            "values_milli": [900, 900, 900, 100, 0, 500, 500, 250, 50, 0, 0, 100], "missing": [False] * 12, "owner_sequence": 1, "plan_versions": 1, "repair_count": 1}
    bad = dict(good, values_milli=[50, 50, 50, 950, 1000, 1000, 1000, 1000, 50, 500, 0, 100])
    assert router.decide(policy, good, [])["action"] == "repair"
    assert router.decide(policy, bad, [])["action"] == "stop"
    assert router.decide(rule, bad, [])["action"] == "repair"
    assert router.policy_digest(policy) != router.policy_digest(rule)


# ------------------------------------------------------------------ runner integration

def _hard_task_spec(tmp_path, provider, **over):
    repo = tmp_path / "repo"
    base = parser_bug.build_repo(repo)
    oracle = parser_bug.write_oracle(tmp_path / "oracle_kvparse.py")
    return dict(parser_bug.task_spec(repo, base, oracle, provider), **over)


def test_pinned_readout_policy_stops_a_repair_and_records_its_decision(tmp_path):
    """The wrong patch fails the oracle; the rule repairs, a readout that predicts failure stops.
    Both decisions are retained with their channels; the stop is a documented hold, not a success."""
    ws = Workspace.create(tmp_path / "ws", backend="trusted_local", allow_trusted_local=True)
    try:
        stop_policy = router.readout_policy("readout-always-stop", feature_source="channels", weights=[0.0] * 24, bias=-5.0, threshold_milli=500)
        spec = _hard_task_spec(tmp_path, scripted(parser_bug.script("wrong_then_weaken")), policy=stop_policy)
        created = ws.create_task(spec)
        task = ws.owner.projection(created["run_id"])["task"]
        assert ws.policy_for(task)["policy_id"] == "readout-always-stop"
        summary = TaskRunner(ws, created["task_id"]).run()
        assert summary["state"] == "failed" and summary["hold"]["reason_code"] == "router_stop"
        assert summary["repair_count"] == 1 and summary["plan_versions"] == 1  # the repair cycle was opened by the owner, then stopped
        decisions = ws.memory.eligible("router/decisions:" + created["run_id"], ws.memory.frontier())
        assert len(decisions) == 1
        record = loads(ws.memory.content(decisions[0]), ascii_only=False)
        assert record["schema"] == "gabriel.router-decision/1" and record["action"] == "stop" and record["policy_id"] == "readout-always-stop"
        assert record["channels"]["channel_schema_id"] == progress.CHANNEL_SCHEMA_ID and record["channels"]["values_milli"][5] > 0
        support = ws.memory.effective_support("readout-always-stop")
        assert support["refute"] == 1 and support["support"] == 0
        assert ws.owner.replay()["status"] == "passed"
    finally:
        ws.close()
    # the same task under the rule-based policy proceeds into the repair round (fresh workspace:
    # scripted provider cursors are per process and per profile)
    ws = Workspace.create(tmp_path / "ws2", backend="trusted_local", allow_trusted_local=True)
    try:
        spec2 = _hard_task_spec(tmp_path / "second", scripted(parser_bug.script("wrong_then_weaken")), max_plan_versions=2)
        created2 = ws.create_task(spec2)
        summary2 = TaskRunner(ws, created2["task_id"]).run()
        # the rule repairs; the scripted planner then offers a weakened plan, which the owner rejects (not the router)
        assert summary2["repair_count"] == 1 and (summary2["hold"] or {}).get("reason_code") != "router_stop", summary2["log"]
        rule_decisions = ws.memory.eligible("router/decisions:" + created2["run_id"], ws.memory.frontier())
        assert rule_decisions and loads(ws.memory.content(rule_decisions[0]), ascii_only=False)["action"] == "repair"
    finally:
        ws.close()
    # a recurrent-feature readout runs the reference map over the decision history
    ws = Workspace.create(tmp_path / "ws3", backend="trusted_local", allow_trusted_local=True)
    try:
        recurrent_policy = router.readout_policy("readout-recurrent", feature_source="recurrent", weights=[0.0] * 18, bias=5.0,
                                                 recurrent_config=recurrent.default_config(units=16, parents=4, channels=24))
        spec3 = _hard_task_spec(tmp_path / "third", scripted(parser_bug.script("wrong_then_weaken")), policy=recurrent_policy, max_plan_versions=2)
        created3 = ws.create_task(spec3)
        TaskRunner(ws, created3["task_id"]).run()
        rec = loads(ws.memory.content(ws.memory.eligible("router/decisions:" + created3["run_id"], ws.memory.frontier())[0]), ascii_only=False)
        assert rec["feature_source"] == "recurrent" and len(rec["features_milli"]) == 18 and rec["action"] == "repair"
        assert ws.owner.replay()["status"] == "passed"
    finally:
        ws.close()


def test_episodes_enter_the_prompt_and_are_recorded(tmp_path):
    ws = Workspace.create(tmp_path / "ws", backend="trusted_local", allow_trusted_local=True)
    try:
        spec = _hard_task_spec(tmp_path, scripted(parser_bug.script("correct")))
        created = ws.create_task(spec)
        assert TaskRunner(ws, created["task_id"]).run()["state"] == "succeeded"
        episodes = ws.memory.retrieve(principal_id="local-user", task_id=None, frontier=ws.memory.frontier(), query=b"kvparse parse_pairs empty input",
                                      allowed_source_kinds=["episode"])
        assert len(episodes["items"]) == 1
        episode = json.loads(ws.store.get(episodes["items"][0]["artifact_ref"]).decode("utf8"))
        assert episode["outcome"] == "success" and "parse_pairs" in episode["final_diff"]
        # a second task with an episode-retrieving policy sees the episode and records its id
        spec2 = _hard_task_spec(tmp_path / "second", scripted(parser_bug.script("correct")), policy=router.rule_based(episodes=2))
        created2 = ws.create_task(spec2)
        assert TaskRunner(ws, created2["task_id"]).run()["state"] == "succeeded"
        projection = ws.owner.projection(created2["run_id"])
        request = loads(ws.store.get(projection["nodes"]["propose"]["outputs"]["request"]))
        assert request["observation_ids"] == [episodes["items"][0]["observation_id"]]
        prompt = ws.store.get(request["prompt_ref"]).decode("utf8")
        assert "Past episodes retrieved as evidence" in prompt and "=== episode obs-" in prompt
        assert ws.memory.effective_support("rule-based-episodes2-v1")["support"] == 1
    finally:
        ws.close()


# ------------------------------------------------------------------ ADR-22: domain-declared channels on document runs

def test_document_decisions_carry_the_packs_declared_channels_and_bind_the_readout_to_their_layout(tmp_path):
    """A document task whose required source the budgeted retrieval cannot carry fails its first
    verification. The retained decision carries the document pack's channels beside the generic
    ones (expected_source_absent = 1: the unmet claim expects a source the retrieval did not
    carry), a readout bound to the generic layout is refused rather than scored, and a readout
    bound to the composed layout that reads expected_source_absent stops the hopeless repair."""
    from gabriel_agent.domains.document import pack as document
    from gabriel_agent.evaluation.fixtures import document_association as da
    repo = tmp_path / "repo"
    base = da.build_repo(repo)
    ws = Workspace.create(tmp_path / "ws", backend="trusted_local", allow_trusted_local=True)
    try:
        # the rule-based policy pinned explicitly: since ADR-22 a document task pins the pack's promoted readout by default
        created = ws.create_task(da.summary_spec(repo, base, da.summary_oracle(tmp_path / "s.json"), da.provider("visible_only"), view="provenance",
                                                 max_repairs=1, max_plan_versions=2, policy=router.rule_based()))
        summary = TaskRunner(ws, created["task_id"]).run()
        assert summary["state"] == "failed" and summary["repair_count"] == 1, summary["log"]
        decisions = ws.memory.eligible("router/decisions:" + created["run_id"], ws.memory.frontier())
        record = loads(ws.memory.content(decisions[0]), ascii_only=False)
        channels = record["channels"]
        assert record["action"] == "repair" and channels["channel_schema_id"] == "progress-channels-v1.document-progress-v1"
        assert channels["names"] == list(progress.CHANNELS) + list(document.PROGRESS_CHANNELS) and len(progress.as_vector(channels)) == 36
        value = dict(zip(channels["names"], channels["values_milli"]))
        assert value["expected_source_absent"] == 1000 and value["forbidden_present"] == 0 and value["carried_sources"] == 0
        assert value["required_missing"] + value["required_uncited"] == 500 and value["citations_unbound"] is not None
        rule_attempts = sum(1 for a in ws.owner.projection(created["run_id"])["attempts"].values() if a["capability_id"] == "model.generate")
        assert ws.owner.replay()["status"] == "passed"
    finally:
        ws.close()
    # a readout trained on the generic layout is refused on a document run, not scored
    ws = Workspace.create(tmp_path / "ws2", backend="trusted_local", allow_trusted_local=True)
    try:
        generic = router.readout_policy("readout-generic", feature_source="channels", weights=[0.0] * 24, bias=5.0, threshold_milli=500)
        created = ws.create_task(da.summary_spec(repo, base, da.summary_oracle(tmp_path / "s2.json"), da.provider("visible_only"), view="provenance",
                                                 max_repairs=1, max_plan_versions=2, policy=generic))
        with pytest.raises(GabrielError):
            TaskRunner(ws, created["task_id"]).run()
    finally:
        ws.close()
    # a readout bound to the composed layout stops where the expected source is absent and repairs otherwise
    ws = Workspace.create(tmp_path / "ws3", backend="trusted_local", allow_trusted_local=True)
    try:
        weights = [0.0] * 36
        weights[progress.vector_names(channels).index("expected_source_absent")] = -10.0
        bound = router.readout_policy("readout-document-test", feature_source="channels", weights=weights, bias=5.0, threshold_milli=500,
                                      channel_schema_id="progress-channels-v1.document-progress-v1")
        assert router.decide(bound, channels, [])["action"] == "stop"
        present = dict(channels, values_milli=[0 if n == "expected_source_absent" else v for n, v in zip(channels["names"], channels["values_milli"])])
        assert router.decide(bound, present, [])["action"] == "repair"
        created = ws.create_task(da.summary_spec(repo, base, da.summary_oracle(tmp_path / "s3.json"), da.provider("visible_only"), view="provenance",
                                                 max_repairs=1, max_plan_versions=2, policy=bound))
        summary = TaskRunner(ws, created["task_id"]).run()
        assert summary["state"] == "failed" and summary["hold"]["reason_code"] == "router_stop" and summary["repair_count"] == 1
        attempts = ws.owner.projection(created["run_id"])["attempts"].values()
        assert sum(1 for a in attempts if a["capability_id"] == "model.generate") < rule_attempts  # the hopeless repair (its plan and its proposal) was never requested
        stop = loads(ws.memory.content(ws.memory.eligible("router/decisions:" + created["run_id"], ws.memory.frontier())[0]), ascii_only=False)
        assert stop["action"] == "stop" and stop["policy_id"] == "readout-document-test" and stop["channels"]["channel_schema_id"] == bound["channel_schema_id"]
        assert ws.owner.replay()["status"] == "passed"
    finally:
        ws.close()


def test_a_layout_bound_readout_abstains_where_the_packs_channels_are_missing(tmp_path):
    """When another check fails before the claims check ran (here an unbound citation), the pack's
    channels are missing; a readout bound to the document layout then abstains and the rule
    repairs, with the reason retained in the decision record (ADR-22)."""
    from gabriel_agent.evaluation.fixtures import document_association as da
    repo = tmp_path / "repo"
    base = da.build_repo(repo)
    ws = Workspace.create(tmp_path / "ws", backend="trusted_local", allow_trusted_local=True)
    try:
        always_stop = router.readout_policy("readout-document-stop", feature_source="channels", weights=[0.0] * 36, bias=-5.0, threshold_milli=500,
                                            channel_schema_id="progress-channels-v1.document-progress-v1")
        # the scripted summary cites the annex, which the provenance view did not carry: the citations check fails first
        created = ws.create_task(da.summary_spec(repo, base, da.summary_oracle(tmp_path / "s.json"), da.provider("summary"), view="provenance",
                                                 max_repairs=1, max_plan_versions=2, policy=always_stop))
        summary = TaskRunner(ws, created["task_id"]).run()
        assert summary["state"] == "failed" and (summary["hold"] or {}).get("reason_code") != "router_stop" and summary["repair_count"] == 1
        decisions = [loads(ws.memory.content(o), ascii_only=False) for o in ws.memory.eligible("router/decisions:" + created["run_id"], ws.memory.frontier())]
        assert decisions and all(d["action"] == "repair" and d["reason"].startswith("readout abstains: pack channel(s)") for d in decisions)
        assert "expected_source_absent" in decisions[0]["reason"] and decisions[0]["policy_id"] == "readout-document-stop"
    finally:
        ws.close()


def test_document_tasks_pin_the_packs_promoted_readout_by_default_and_software_tasks_the_rule(tmp_path):
    """ADR-22: a document task whose spec names no policy pins the readout promoted under protocol 8
    (digest-bound, with its provenance shipped beside it); a software task pins nothing and runs
    under the rule-based policy; an explicit policy in the spec still wins."""
    from gabriel_agent.domains.document import pack as document
    from gabriel_agent.evaluation.fixtures import document_association as da
    repo = tmp_path / "repo"
    base = da.build_repo(repo)
    ws = Workspace.create(tmp_path / "ws", backend="trusted_local", allow_trusted_local=True)
    try:
        shipped = ws.pack_for("document").default_policy()
        provenance = json.loads((Path(document.__file__).parent / "policies" / "readout-channels-v2.provenance.json").read_text())
        assert shipped["policy_id"] == "readout-channels-v2" and router.policy_digest(shipped) == provenance["policy_digest"]
        assert shipped["channel_schema_id"] == "progress-channels-v1.document-progress-v1" and provenance["promotion"]["decision"] == "promoted"
        created = ws.create_task(da.summary_spec(repo, base, da.summary_oracle(tmp_path / "s.json"), da.provider("summary")))
        task = ws.owner.projection(created["run_id"])["task"]
        assert ws.policy_for(task)["policy_id"] == "readout-channels-v2" and router.policy_digest(ws.policy_for(task)) == provenance["policy_digest"]
        explicit = ws.create_task(da.summary_spec(repo, base, da.summary_oracle(tmp_path / "s2.json"), da.provider("summary"), policy=router.rule_based()))
        assert ws.policy_for(ws.owner.projection(explicit["run_id"])["task"])["policy_id"] == "rule-based-v1"
        software = ws.create_task(_hard_task_spec(tmp_path, scripted(parser_bug.script("wrong_then_weaken"))))
        assert ws.policy_for(ws.owner.projection(software["run_id"])["task"])["policy_id"] == "rule-based-v1"
    finally:
        ws.close()
