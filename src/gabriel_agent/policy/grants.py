"""Scoped authority: grant validity, intent admission and approvals."""
from __future__ import annotations

from ..contracts.errors import Code, GabrielError
from ..contracts.rules import CEILING_MAP, approval_digest

EFFECT_RANK = {"read": 0, "local_reversible_write": 1, "external_idempotent_effect": 2,
               "external_non_idempotent_effect": 3}


def active(grant: dict, revoked_at: int | None, owner_time_unix_ms: int) -> tuple[bool, str]:
    """Trusted owner time decides expiry; worker time never does."""
    if revoked_at is not None and revoked_at <= owner_time_unix_ms:
        return False, "revoked"
    if grant["expires_at_unix_ms"] <= owner_time_unix_ms:
        return False, "expired"
    return True, "active"


def check_scope(grant: dict, *, workspace_id: str, task_id: str, principal_id: str) -> None:
    if grant["workspace_id"] != workspace_id:
        raise GabrielError(Code.POLICY_DENIED, "grant belongs to another workspace", obj=grant["grant_id"])
    if grant["task_id"] != task_id:
        raise GabrielError(Code.POLICY_DENIED, "grant belongs to another task", obj=grant["grant_id"])
    if grant["principal_id"] != principal_id:
        raise GabrielError(Code.POLICY_DENIED, "grant principal does not match the task principal", obj=grant["grant_id"])


def check_child_subset(parent: dict, child: dict) -> None:
    """A delegated grant carries a strict subset of its parent's rights."""
    if child["parent_grant_id"] != parent["grant_id"]:
        raise GabrielError(Code.POLICY_DENIED, "child grant does not name its parent", obj=child["grant_id"])
    for field in ("tool_ids", "resource_ids", "effect_classes"):
        if not set(child[field]) <= set(parent[field]):
            raise GabrielError(Code.POLICY_DENIED, "child grant widens " + field, obj=child["grant_id"])
    if child["expires_at_unix_ms"] > parent["expires_at_unix_ms"]:
        raise GabrielError(Code.POLICY_DENIED, "child grant outlives its parent", obj=child["grant_id"])
    for cfield in CEILING_MAP:
        if child["budget_ceiling"][cfield] > parent["budget_ceiling"][cfield]:
            raise GabrielError(Code.POLICY_DENIED, "child grant exceeds parent ceiling in " + cfield, obj=child["grant_id"])


def check_intent(intent: dict, grant: dict, tool: dict, *, approvals: set, revoked_at, owner_time_unix_ms: int,
                 policy_digest: str) -> None:
    """Admission and dispatch recheck share this exact rule set."""
    ok, reason = active(grant, revoked_at, owner_time_unix_ms)
    if not ok:
        raise GabrielError(Code.POLICY_DENIED, "grant is " + reason, obj=grant["grant_id"])
    if intent["grant_id"] != grant["grant_id"]:
        raise GabrielError(Code.POLICY_DENIED, "intent names a different grant", obj=intent["intent_id"])
    if intent["policy_digest"] != policy_digest or grant["policy_digest"] != policy_digest:
        raise GabrielError(Code.POLICY_DENIED, "policy identity mismatch", obj=intent["intent_id"])
    if intent["capability_id"] not in grant["tool_ids"]:
        raise GabrielError(Code.POLICY_DENIED, "capability not granted: " + intent["capability_id"], obj=intent["intent_id"])
    if intent["target_id"] not in grant["resource_ids"]:
        raise GabrielError(Code.POLICY_DENIED, "target not granted: " + intent["target_id"], obj=intent["intent_id"])
    if intent["effect_class"] != tool["effect_class"]:
        raise GabrielError(Code.POLICY_DENIED, "intent effect class disagrees with registered tool", obj=intent["intent_id"])
    if intent["effect_class"] not in grant["effect_classes"]:
        raise GabrielError(Code.POLICY_DENIED, "effect class not granted: " + intent["effect_class"], obj=intent["intent_id"])
    if intent["reconciliation"] != tool["reconciliation"]:
        raise GabrielError(Code.POLICY_DENIED, "reconciliation class disagrees with registered tool", obj=intent["intent_id"])
    if intent["expires_at_unix_ms"] <= owner_time_unix_ms:
        raise GabrielError(Code.POLICY_DENIED, "intent lease already expired", obj=intent["intent_id"])
    needs_approval = tool["requires_approval"] or intent["effect_class"] == "external_non_idempotent_effect"
    if needs_approval:
        expected = approval_digest(intent)
        if intent["approval_digest"] != expected or expected not in approvals:
            raise GabrielError(Code.POLICY_DENIED, "approval digest missing or does not bind this exact intent",
                               obj=intent["intent_id"])
    elif intent["approval_digest"] is not None and intent["approval_digest"] != approval_digest(intent):
        raise GabrielError(Code.POLICY_DENIED, "approval digest does not bind this intent", obj=intent["intent_id"])
