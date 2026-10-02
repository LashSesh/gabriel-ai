"""Worker supervisor: leases, dispatch markers, result delivery and recovery.

The supervisor is trusted local code without a writable database handle: it
only submits commands. It commits a dispatch-attempt marker before the
first external I/O, invokes the registered implementation outside any
transaction, installs the raw outputs and submits the result. On restart,
every marked attempt without a result is treated as possibly executed and
reconciled through the tool's registered reconciliation method; nothing is
blindly repeated.
"""
from __future__ import annotations

import time
import traceback
from dataclasses import dataclass, field

from ..contracts.codec import canonical
from ..contracts.errors import Code, GabrielError
from ..contracts.schemas import validate
from ..policy import budget


class SupervisorCrash(Exception):
    """Raised by test hooks to simulate a process loss at a named point."""


@dataclass
class ToolOutcome:
    status: str = "completed"
    exit_code: int | None = 0
    outputs: list = field(default_factory=list)   # [(slot, bytes, media_type, schema_digest)]
    usage: dict | None = None
    effect_outcome: str = "not_applicable"
    provider_request_id: str | None = None
    observations: list = field(default_factory=list)
    notes: list = field(default_factory=list)


@dataclass
class ToolContext:
    store: object
    owner: object
    registry: object
    intent: dict
    args: dict
    projection: dict
    backend: object = None
    worktree: object = None
    binding: dict | None = None
    deadline_unix_ms: int | None = None
    extras: dict = field(default_factory=dict)


def _default_usage(elapsed_ms: int, outputs_bytes: int, currency: str) -> dict:
    return {"model_tokens": 0, "model_requests": 0, "tool_attempts": 1, "cpu_ms": 0, "elapsed_ms": elapsed_ms,
            "artifact_bytes": outputs_bytes, "currency_micro_units": 0, "currency": currency, "accounting_status": "confirmed"}


class Supervisor:
    def __init__(self, owner, store, registry, credential, *, backend=None, hooks=None, extras=None):
        self.owner, self.store, self.registry, self.credential = owner, store, registry, credential
        self.backend = backend
        self.hooks = hooks or {}
        self.extras = extras or {}
        self.port_calls = 0

    def _hook(self, stage):
        hook = self.hooks.get(stage)
        if hook:
            hook(stage)

    def _submit(self, op, payload, task_id, run_id, command_id):
        payload_ref = self.store.put(canonical(payload), "application/json")
        command = {"schema": "gabriel.command/1", "command_id": command_id, "workspace_id": self.owner.workspace_id,
                   "task_id": task_id, "run_id": run_id,
                   "expected_revision": self.owner.run_record(run_id)["run_revision"], "op": op,
                   "payload_ref": payload_ref, "policy_digest": self.owner.projection(run_id)["task"]["policy_digest"]}
        return self.owner.submit(validate(command, "command"), credential=self.credential)

    # ------------------------------------------------------------ dispatch
    def dispatch(self, intent: dict, args: dict, *, worktree=None, binding=None) -> tuple:
        run_id, task_id = intent["run_id"], intent["task_id"]
        descriptor, implementation = self.registry.tool(intent["capability_id"])
        projection = self.owner.projection(run_id)
        attempt = projection["attempts"].get(intent["attempt_id"])
        if attempt is None or attempt["status"] != "issued":
            raise GabrielError(Code.INVALID_TRANSITION, "attempt is not issued", obj=intent["attempt_id"])
        owner_time = self.owner.owner_time()
        authorization = {"grant_id": intent["grant_id"], "owner_time_unix_ms": owner_time, "policy_digest": intent["policy_digest"],
                         "catalog_digest": self.owner.catalog_digest, "intent_id": intent["intent_id"],
                         "backend": getattr(self.backend, "kind", None), "pause_requested": projection["run"]["pause_requested"]}
        marker = {"schema": "gabriel.dispatch-marker/1", "run_id": run_id, "intent_id": intent["intent_id"],
                  "attempt_id": intent["attempt_id"], "lease_id": intent["lease_id"], "fencing_token": intent["fencing_token"],
                  "owner_time_unix_ms": owner_time,
                  "authorization_input_ref": self.store.put(canonical(authorization), "application/json")}
        self._hook("before_marker")
        self._submit("mark_dispatch", marker, task_id, run_id, "mark-" + intent["attempt_id"])
        self._hook("after_marker")
        # ---- external I/O outside any owner transaction ----
        context = ToolContext(self.store, self.owner, self.registry, intent, args, self.owner.projection(run_id),
                              backend=self.backend, worktree=worktree, binding=binding,
                              deadline_unix_ms=intent["expires_at_unix_ms"], extras=self.extras)
        started = time.monotonic()
        self.port_calls += 1
        try:
            outcome = implementation(intent, args, context)
        except GabrielError as exc:
            outcome = ToolOutcome(status="failed", exit_code=None, effect_outcome="acknowledged_failure" if descriptor["effect_class"] != "read" else "not_applicable",
                                  outputs=[("error", canonical(exc.to_record()), "application/json", descriptor["output_schema_digest"])])
        except Exception as exc:  # noqa: BLE001 - worker failure is an attempt outcome, never a crash of the owner
            detail = (type(exc).__name__ + ": " + str(exc) + "\n" + traceback.format_exc()[-2000:]).encode("utf8")
            outcome = ToolOutcome(status="failed", exit_code=None, effect_outcome="outcome_unknown" if descriptor["effect_class"] != "read" else "not_applicable",
                                  outputs=[("error", detail, "text/plain; charset=utf-8", descriptor["output_schema_digest"])])
        elapsed = int((time.monotonic() - started) * 1000)
        self._hook("after_io")
        result = self._result_record(intent, descriptor, outcome, elapsed, projection["run"]["budget"]["currency"])
        self._hook("before_result_commit")
        receipt = self._submit("accept_result", result, task_id, run_id, "result-" + intent["attempt_id"])
        self._hook("after_result_commit")
        for observation in outcome.observations:
            self._submit("record_observation", observation, task_id, run_id, "obs-" + observation["observation_id"])
        return result, receipt

    def _result_record(self, intent, descriptor, outcome: ToolOutcome, elapsed_ms, currency):
        outputs, total = [], 0
        for slot, raw, media, schema_digest in outcome.outputs:
            # Completed results bind exactly the declared slots (checked by the owner); failed
            # results retain their diagnostics under their own slots for inspection.
            ref = self.store.put(raw, media)
            total += len(raw)
            outputs.append({"output_slot": slot, "artifact_ref": ref, "schema_digest": schema_digest})
        usage = outcome.usage or _default_usage(elapsed_ms, total, currency)
        if outcome.status in ("timed_out",) and usage.get("accounting_status") == "confirmed" and descriptor["effect_class"] != "read":
            usage = dict(usage, accounting_status="conservative_pending_reconciliation")
        result = {"schema": "gabriel.result/1", "result_id": "result-" + intent["attempt_id"], "intent_id": intent["intent_id"],
                  "attempt_id": intent["attempt_id"], "lease_id": intent["lease_id"], "fencing_token": intent["fencing_token"],
                  "status": outcome.status, "exit_code": outcome.exit_code, "usage": usage, "duration_ms": elapsed_ms,
                  "effect_outcome": outcome.effect_outcome, "provider_request_id": outcome.provider_request_id,
                  "run_id": intent["run_id"], "task_id": intent["task_id"], "outputs": outputs}
        return validate(result, "result")

    # ------------------------------------------------------------ recovery
    def recover(self, run_id: str, *, worktree=None, binding=None) -> list:
        """Called after a restart. Issued-but-unmarked attempts are abandoned (no I/O can
        have happened: the marker precedes I/O). Marked attempts without a result are
        possibly executed: record an unknown outcome and reconcile through the tool."""
        actions = []
        projection = self.owner.projection(run_id)
        currency = projection["run"]["budget"]["currency"]
        for attempt_id in sorted(projection["attempts"]):
            attempt = projection["attempts"][attempt_id]
            intent = validate(self._load_json(attempt["intent_ref"]), "intent")
            if attempt["status"] == "issued":
                result = {"schema": "gabriel.result/1", "result_id": "abandon-" + attempt_id, "intent_id": intent["intent_id"],
                          "attempt_id": attempt_id, "lease_id": intent["lease_id"], "fencing_token": intent["fencing_token"],
                          "status": "cancelled", "exit_code": None, "usage": _default_usage(0, 0, currency), "duration_ms": 0,
                          "effect_outcome": "not_applicable", "provider_request_id": None, "run_id": run_id,
                          "task_id": intent["task_id"], "outputs": []}
                self._submit("accept_result", validate(result, "result"), intent["task_id"], run_id, "abandon-" + attempt_id)
                actions.append({"attempt_id": attempt_id, "action": "lease_abandoned_before_marker"})
                continue
            if attempt["status"] != "marked":
                continue
            unknown = {"schema": "gabriel.result/1", "result_id": "unknown-" + attempt_id, "intent_id": intent["intent_id"],
                       "attempt_id": attempt_id, "lease_id": intent["lease_id"], "fencing_token": intent["fencing_token"],
                       "status": "failed", "exit_code": None,
                       # unknown consumption: zero actuals under a conservative status keep the full reservation charged
                       "usage": dict(_default_usage(0, 0, currency), tool_attempts=0, accounting_status="conservative_pending_reconciliation"),
                       "duration_ms": 0, "effect_outcome": "outcome_unknown", "provider_request_id": None, "run_id": run_id,
                       "task_id": intent["task_id"], "outputs": []}
            self._submit("accept_result", validate(unknown, "result"), intent["task_id"], run_id, "unknown-" + attempt_id)
            actions.append({"attempt_id": attempt_id, "action": "marked_without_result_recorded_unknown"})
            actions.append(self.reconcile(intent, worktree=worktree, binding=binding))
        return actions

    def reconcile(self, intent: dict, *, worktree=None, binding=None) -> dict:
        """Ask the tool's registered reconciliation for evidence; never re-execute."""
        descriptor, implementation = self.registry.tool(intent["capability_id"])
        run_id = intent["run_id"]
        projection = self.owner.projection(run_id)
        attempt = projection["attempts"][intent["attempt_id"]]
        context = ToolContext(self.store, self.owner, self.registry, intent, self._load_json(intent["args_ref"]), projection,
                              backend=self.backend, worktree=worktree, binding=binding, extras=self.extras)
        reconcile = getattr(implementation, "reconcile", None)
        if reconcile is None or descriptor["reconciliation"] == "manual_review":
            outcome, evidence = "still_unknown", b'{"reconciliation":"manual_review_required"}'
            method = "manual_review"
        else:
            outcome, evidence = reconcile(intent, attempt, context)
            method = descriptor["reconciliation"]
        payload = {"schema": "gabriel.effect-reconciliation/1", "intent_id": intent["intent_id"], "attempt_id": intent["attempt_id"],
                   "method": method, "outcome": outcome, "evidence_ref": self.store.put(evidence, "application/json")}
        receipt = self._submit("reconcile_effect", validate(payload, "effect-reconciliation"), intent["task_id"], run_id,
                               "reconcile-" + intent["attempt_id"] + "-" + str(len(projection["reconciliations"]) + 1))
        return {"attempt_id": intent["attempt_id"], "action": "reconciled", "outcome": outcome, "method": method,
                "run_state": receipt["run_state"]}

    def _load_json(self, ref):
        from ..contracts.codec import loads
        return loads(self.store.get(ref))
