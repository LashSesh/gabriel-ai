"""AT02 representation controls and schema registry checks."""
import copy
import json
from pathlib import Path

import pytest

from gabriel_agent.contracts import (MAX_INT, CodecError, GabrielError, Code, canonical, loads,
                                     validate, validate_bytes, schema_names, artifact_ref,
                                     payload_schema_for_op, OPS, OP_TO_EVENT, EVENT_KINDS)
from gabriel_agent.contracts import rules
from gabriel_agent.contracts.schemas import schema_digest, registry_digest, record_schema_for_payload

EXAMPLES = Path(__file__).resolve().parents[1] / "contracts" / "examples"


def example(name):
    return loads((EXAMPLES / (name + ".json")).read_bytes())


def test_canonical_strictness():
    assert canonical({"b": 1, "a": False}) == b'{"a":false,"b":1}'
    assert canonical({"a": True}) != canonical({"a": 1})
    for bad in (1.0, float("nan"), MAX_INT + 1, -MAX_INT - 1, "ü", {1: "x"}, (1,), b"x", set()):
        with pytest.raises(CodecError):
            canonical(bad)
    for raw in (b'{"a":1,"a":2}', b'{"a":1.0}', b'{"a":NaN}', "{\"a\":\"ü\"}".encode("utf8"), b'[1e3]', b'{"a":Infinity}'):
        with pytest.raises(CodecError):
            loads(raw)
    deep = "[" * 70 + "]" * 70
    with pytest.raises(CodecError):
        loads(deep.encode())


def test_every_blueprint_example_validates_and_round_trips():
    for path in sorted(EXAMPLES.glob("*.json")):
        value = loads(path.read_bytes())
        name = record_schema_for_payload(value) if "schema" in value else "artifact-ref"
        validate(value, name)
        assert loads(canonical(value)) == value


def test_command_representation_controls_reject_before_admission():
    command = example("command")
    validate(command, "command")
    for field, value in [("arbitrary", "x"), ("expected_revision", True), ("expected_revision", -1),
                         ("expected_revision", MAX_INT + 1), ("task_id", "täsk"), ("op", "execute_unrestricted"),
                         ("policy_digest", "A" * 64)]:
        bad = copy.deepcopy(command)
        bad[field] = value
        with pytest.raises(GabrielError) as info:
            validate(bad, "command")
        assert info.value.code is Code.INVALID_SCHEMA
    with pytest.raises(GabrielError):
        validate_bytes(b'{"schema":"gabriel.command/1","expected_revision":7.0}', "command")
    with pytest.raises(GabrielError):
        validate_bytes(canonical(command).replace(b'"expected_revision":7', b'"expected_revision":7,"expected_revision":7'), "command")


def test_utf8_artifact_bytes_are_preserved_by_reference():
    raw = "Prüfung der Randfälle \U0001F600".encode("utf8")
    ref = artifact_ref(raw, "text/plain; charset=utf-8")
    validate(ref, "artifact-ref")
    assert ref["bytes"] == len(raw)
    with pytest.raises(CodecError):
        artifact_ref(raw.decode("utf8"))  # type: ignore[arg-type]
    with pytest.raises(CodecError):
        artifact_ref(raw, "text/ü")


def test_run_pause_is_a_flag_not_a_state():
    run = example("run")
    run["state"] = "paused"
    with pytest.raises(GabrielError):
        validate(run, "run")


def test_operation_and_event_enums_are_closed_and_aligned():
    assert set(OPS) == set(OP_TO_EVENT)
    assert len(EVENT_KINDS) == len(OPS)
    for op in OPS:
        payload_schema_for_op(op)
    with pytest.raises(GabrielError):
        payload_schema_for_op("execute_unrestricted")
    assert "record_hold" in OPS and "HoldRecorded" in EVENT_KINDS


def test_schema_registry_is_closed_and_identified():
    names = schema_names()
    assert {"task", "run", "command", "event", "plan", "intent", "result", "assessment", "goal-spec",
            "compilation-report", "context-manifest", "proposal-envelope", "check-evidence", "read-back",
            "hold", "receipt", "checkpoint", "anchor", "task-binding", "provider-profile", "run-witness"} <= set(names)
    assert len(schema_digest("plan")) == 64 and len(registry_digest()) == 64
    assert schema_digest("plan") != schema_digest("task")


def test_plan_dag_rules():
    plan = example("plan-future-output")
    rules.plan_dag(plan)
    bad = copy.deepcopy(plan); bad["nodes"][0]["depends_on"] = ["step-review"]
    with pytest.raises(GabrielError):
        rules.plan_dag(bad)
    bad = copy.deepcopy(plan); bad["nodes"][0]["depends_on"] = ["absent"]
    with pytest.raises(GabrielError):
        rules.plan_dag(bad)
    bad = copy.deepcopy(plan); bad["nodes"][1]["inputs"][0]["required_schema"] = "b" * 64
    with pytest.raises(GabrielError):
        rules.plan_dag(bad)
    bad = copy.deepcopy(plan); bad["nodes"][1]["depends_on"] = []
    with pytest.raises(GabrielError):
        rules.plan_dag(bad)
    # 65 nodes and depth 13 reject at the schema level as well as the rule level
    big = copy.deepcopy(plan)
    template = copy.deepcopy(plan["nodes"][0])
    big["nodes"] = []
    prev = None
    for i in range(65):
        node = copy.deepcopy(template); node["node_id"] = "n%02d" % i
        node["depends_on"] = [prev] if prev else []
        node["inputs"] = []
        big["nodes"].append(node); prev = node["node_id"]
    with pytest.raises(GabrielError):
        validate(big, "plan")
    big["nodes"] = big["nodes"][:13]
    validate(big, "plan")
    with pytest.raises(GabrielError):
        rules.plan_dag(big)


def test_amendment_weakening_detected():
    task = example("task")
    weaker = copy.deepcopy(task); weaker["checks"][0]["mandatory"] = False
    assert rules.amendment_weakens(task, weaker)
    removed = copy.deepcopy(task); removed["checks"] = [dict(task["checks"][0], check_id="other")]
    assert rules.amendment_weakens(task, removed)
    assert not rules.amendment_weakens(task, copy.deepcopy(task))
    larger = copy.deepcopy(task); larger["budget_ceiling"]["model_requests"] += 1
    assert rules.amendment_weakens(task, larger)


def test_approval_digest_binds_exact_intent_fields():
    intent = example("intent")
    base = rules.approval_digest(intent)
    changed = copy.deepcopy(intent); changed["args_ref"] = dict(intent["args_ref"], sha256="b" * 64)
    assert rules.approval_digest(changed) != base
    same = copy.deepcopy(intent); same["lease_id"] = "lease-99"
    assert rules.approval_digest(same) == base
