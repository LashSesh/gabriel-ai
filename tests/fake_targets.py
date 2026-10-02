"""Fake external targets and tools for crash-window tests (AT12/AT13)."""
from __future__ import annotations

from gabriel_agent.contracts.codec import canonical
from gabriel_agent.tools import ToolRegistry
from gabriel_agent.workers import ToolOutcome


class IdempotentTarget:
    """Enforces one logical effect per idempotency key and supports status queries."""

    def __init__(self):
        self.log = {}
        self.calls = []

    def apply(self, key, value):
        self.calls.append(("apply", key))
        if key in self.log:
            return self.log[key]
        self.log[key] = value
        return value

    def status(self, key):
        self.calls.append(("status", key))
        return self.log.get(key)


class NonIdempotentTarget:
    """A counter with no status query: every call is a new effect."""

    def __init__(self):
        self.count = 0
        self.calls = []

    def apply(self):
        self.calls.append("apply")
        self.count += 1
        return self.count


class IdempotentWriteTool:
    def __init__(self, target: IdempotentTarget, crash_after_io=None):
        self.target = target
        self.crash_after_io = crash_after_io

    def __call__(self, intent, args, ctx):
        value = self.target.apply(intent["idempotency_key"], args.get("value", "x"))
        if self.crash_after_io:
            self.crash_after_io()
        return ToolOutcome(outputs=[("output", canonical({"value": value}), "application/json", ctx.registry.tool(intent["capability_id"])[0]["output_schema_digest"])],
                           effect_outcome="acknowledged_success")

    def reconcile(self, intent, attempt, ctx):
        found = self.target.status(intent["idempotency_key"])
        if found is None:
            return "confirmed_not_executed", canonical({"status_by_key": None})
        return "confirmed_success", canonical({"status_by_key": found})


class NonIdempotentTool:
    def __init__(self, target: NonIdempotentTarget, crash_after_io=None):
        self.target = target
        self.crash_after_io = crash_after_io

    def __call__(self, intent, args, ctx):
        count = self.target.apply()
        if self.crash_after_io:
            self.crash_after_io()
        return ToolOutcome(outputs=[("output", canonical({"count": count}), "application/json", ctx.registry.tool(intent["capability_id"])[0]["output_schema_digest"])],
                           effect_outcome="acknowledged_success")


class ReadTool:
    def __call__(self, intent, args, ctx):
        snapshot = canonical({"snapshot": "fixture", "attempt": intent["attempt_id"]})
        return ToolOutcome(outputs=[("snapshot", snapshot, "application/json", ctx.registry.tool(intent["capability_id"])[0]["output_schema_digest"])])

    def reconcile(self, intent, attempt, ctx):
        return "confirmed_not_executed", canonical({"read": "no effect"})


def fake_registry(idempotent: IdempotentTarget, non_idempotent: NonIdempotentTarget, crash_after_io=None):
    from .harness import tool, sha
    registry = ToolRegistry()
    registry.register_tool(tool("fixture.read", "read", observation_slot="snapshot"), ReadTool())
    registry.register_tool(tool("fixture.write", "local_reversible_write", concurrency_key="writer"),
                           IdempotentWriteTool(idempotent, crash_after_io))
    registry.register_tool(tool("fixture.external", "external_non_idempotent_effect", "manual_review", True),
                           NonIdempotentTool(non_idempotent, crash_after_io))
    registry.register_tool(tool("fixture.keyed", "external_idempotent_effect", "target_status_by_key", concurrency_key="model"),
                           IdempotentWriteTool(idempotent, crash_after_io))
    registry.register_verifier({"verifier_id": "fixture.oracle", "version": "v1", "predicate_kind": "fixture/passed",
                                "implementation_fingerprint": sha("x"), "profile_digest": sha("profile"), "independent": True,
                                "description": "fixture oracle"}, ReadTool())
    registry.register_verifier({"verifier_id": "owner.output_valid", "version": "v1", "predicate_kind": "owner/output_valid",
                                "implementation_fingerprint": sha("x"), "profile_digest": sha("profile"), "independent": False,
                                "description": "owner structural check"}, ReadTool())
    return registry
