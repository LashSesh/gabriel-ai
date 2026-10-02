"""Local schema registry with a strict integer type checker.

Schema identifiers under ``https://gabriel.invalid`` are local names; nothing
is fetched. ``validate`` first checks the exact envelope (ASCII, no floats,
no duplicate keys when parsed from bytes) and then the closed Draft 2020-12
schema. Boolean values are never accepted where integers are declared.
"""
from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator, validators
from jsonschema.exceptions import ValidationError
from referencing import Registry, Resource

from .codec import CodecError, canonical, loads, _check
from .errors import Code, GabrielError

SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"
BASE = "https://gabriel.invalid/spec/1/"

OPS = ["admit_task", "accept_plan", "issue_intent", "accept_result", "accept_assessment",
       "amend_task", "cancel_task", "record_observation", "reconcile_effect",
       "request_pause", "resume_run", "start_run", "mark_dispatch", "record_hold"]
OP_TO_EVENT = {
    "admit_task": "TaskAdmitted", "accept_plan": "PlanAccepted", "issue_intent": "IntentIssued",
    "accept_result": "ResultAccepted", "accept_assessment": "AssessmentAccepted",
    "amend_task": "TaskAmended", "cancel_task": "TaskCancelled",
    "record_observation": "ObservationRecorded", "reconcile_effect": "EffectReconciled",
    "request_pause": "PauseRequested", "resume_run": "RunResumed", "start_run": "RunStarted",
    "mark_dispatch": "DispatchAttemptMarked", "record_hold": "HoldRecorded",
}
EVENT_KINDS = list(OP_TO_EVENT.values())
# Payload record schema per operation: the referenced payload bytes must parse
# to a record of that schema.
_OP_PAYLOAD = {
    "admit_task": "task-admission", "accept_plan": "plan", "issue_intent": "intent",
    "accept_result": "result", "accept_assessment": "assessment", "amend_task": "task-amendment",
    "cancel_task": "cancellation", "record_observation": "observation",
    "reconcile_effect": "effect-reconciliation", "request_pause": "pause-request",
    "resume_run": "resume", "start_run": "run-start", "mark_dispatch": "dispatch-marker",
    "record_hold": "hold",
}
# Schema constant -> schema name, for payload dispatch on the "schema" field.
_SCHEMA_CONST = {
    "gabriel.task/1": "task", "gabriel.run/1": "run", "gabriel.command/1": "command",
    "gabriel.event/1": "event", "gabriel.grant/1": "grant", "gabriel.plan/1": "plan",
    "gabriel.model-request/1": "model-request", "gabriel.intent/1": "intent",
    "gabriel.dispatch-marker/1": "dispatch-marker", "gabriel.result/1": "result",
    "gabriel.assessment/1": "assessment", "gabriel.observation/1": "observation",
    "gabriel.claim/1": "claim", "gabriel.outcome-label/1": "outcome-label",
    "gabriel.domain-pack/1": "domain-pack", "gabriel.task-admission/1": "task-admission",
    "gabriel.run-start/1": "run-start", "gabriel.task-amendment/1": "task-amendment",
    "gabriel.cancellation/1": "cancellation", "gabriel.effect-reconciliation/1": "effect-reconciliation",
    "gabriel.pause-request/1": "pause-request", "gabriel.resume/1": "resume", "gabriel.hold/1": "hold",
    "gabriel.goal-spec/1": "goal-spec", "gabriel.compilation-report/1": "compilation-report",
    "gabriel.context-manifest/1": "context-manifest", "gabriel.proposal-envelope/1": "proposal-envelope",
    "gabriel.check-evidence/1": "check-evidence", "gabriel.read-back/1": "read-back",
    "gabriel.receipt/1": "receipt", "gabriel.checkpoint/1": "checkpoint", "gabriel.anchor/1": "anchor",
    "gabriel.tool-descriptor/1": "tool-descriptor", "gabriel.catalog/1": "catalog",
    "gabriel.task-binding/1": "task-binding", "gabriel.provider-profile/1": "provider-profile",
    "gabriel.workspace-config/1": "workspace-config", "gabriel.run-witness/1": "run-witness",
    "gabriel.export-manifest/1": "export-manifest",
}


def _strict_validator_class():
    strict_integer = Draft202012Validator.TYPE_CHECKER.redefine(
        "integer", lambda checker, value: type(value) is int)
    return validators.extend(Draft202012Validator, type_checker=strict_integer)


@lru_cache(maxsize=1)
def _registry():
    schemas = {}
    for path in sorted(SCHEMA_DIR.glob("*.schema.json")):
        schemas[path.name[:-len(".schema.json")]] = loads(path.read_bytes())
    registry = Registry()
    for name, schema in schemas.items():
        Draft202012Validator.check_schema(schema)
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    return schemas, registry


@lru_cache(maxsize=None)
def _validator(name):
    schemas, registry = _registry()
    if name not in schemas:
        raise GabrielError(Code.UNKNOWN_OBJECT, "unknown schema: " + name)
    return _strict_validator_class()(schemas[name], registry=registry)


def schema_names():
    return sorted(_registry()[0])


def schema_digest(name) -> str:
    """Digest of the canonical schema bytes: the output/input schema identity."""
    return hashlib.sha256(canonical(_registry()[0][name])).hexdigest()


@lru_cache(maxsize=1)
def registry_digest() -> str:
    schemas = _registry()[0]
    return hashlib.sha256(canonical({k: schemas[k] for k in sorted(schemas)})).hexdigest()


def payload_schema_for_op(op: str) -> str:
    if op not in _OP_PAYLOAD:
        raise GabrielError(Code.INVALID_SCHEMA, "unknown operation: " + str(op))
    return _OP_PAYLOAD[op]


def record_schema_for_payload(value) -> str:
    if type(value) is not dict or value.get("schema") not in _SCHEMA_CONST:
        raise GabrielError(Code.INVALID_SCHEMA, "record carries no known schema constant")
    return _SCHEMA_CONST[value["schema"]]


def validate(value, name: str):
    """Validate an in-memory value against the named closed schema."""
    try:
        _check(value)
    except CodecError as exc:
        raise GabrielError(Code.INVALID_SCHEMA, str(exc), obj=name) from exc
    try:
        _validator(name).validate(value)
    except ValidationError as exc:
        path = "/".join(str(p) for p in exc.absolute_path)
        raise GabrielError(Code.INVALID_SCHEMA, "%s: %s" % (name, exc.message),
                           obj=name, details={"path": path}) from exc
    return value


def validate_bytes(raw: bytes, name: str):
    """Strictly parse exact JSON bytes and validate them."""
    try:
        value = loads(raw)
    except CodecError as exc:
        raise GabrielError(Code.INVALID_SCHEMA, str(exc), obj=name) from exc
    return validate(value, name)


def dumps_pretty(value) -> str:
    _check(value)
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
