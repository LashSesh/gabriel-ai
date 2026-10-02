"""AT06/AT07 pure policy rules: grants, approvals, reservations."""
import copy
from pathlib import Path

import pytest

from gabriel_agent.contracts import GabrielError, Code, loads
from gabriel_agent.contracts.rules import approval_digest
from gabriel_agent.policy import budget, grants, principals

EXAMPLES = Path(__file__).resolve().parents[1] / "contracts" / "examples"


def example(name):
    return loads((EXAMPLES / (name + ".json")).read_bytes())


TOOL = {"tool_id": "tool.test", "effect_class": "local_reversible_write", "reconciliation": "read_back",
        "requires_approval": False}
POLICY = "a" * 64


def test_reservation_inequality_and_overrun_retention():
    ceiling = budget.ceiling_vector(example("task")["budget_ceiling"])
    spent, reserved = budget.zero(), budget.zero()
    demand = dict(budget.zero(), model_tokens=15000, model_requests=1)
    reserved = budget.admit(spent, reserved, demand, ceiling)
    with pytest.raises(GabrielError) as info:
        budget.admit(spent, reserved, dict(budget.zero(), model_tokens=6000), ceiling)
    assert info.value.code is Code.BUDGET_EXHAUSTED and "model_tokens" in info.value.details["dimensions"]
    actual = dict(budget.zero(), model_tokens=16000, model_requests=1)  # overran its reservation
    spent, reserved, overrun, pending = budget.confirm(spent, reserved, demand, actual, "confirmed")
    assert spent["model_tokens"] == 16000 and overrun == {"model_tokens": 1000} and not pending
    assert reserved == budget.zero()
    # unknown usage keeps the conservative charge
    spent2, reserved2, overrun2, pending2 = budget.confirm(budget.zero(), demand, demand,
                                                           budget.zero(), "conservative_pending_reconciliation")
    assert spent2["model_tokens"] == 15000 and pending2 and overrun2 == {}
    with pytest.raises(GabrielError):
        budget.confirm(budget.zero(), budget.zero(), demand, actual, "confirmed")  # releasing more than reserved
    with pytest.raises(GabrielError):
        budget.admit(spent, reserved, dict(budget.zero(), cpu_ms=-1), ceiling)


def test_deadline_is_separate_from_additive_ledger():
    assert not budget.deadline_exceeded(1000, 30000, 31000)
    assert budget.deadline_exceeded(1000, 30000, 31001)
    assert not budget.deadline_exceeded(None, 30000, 10 ** 9)


def test_grant_expiry_and_revocation_use_owner_time():
    grant = example("grant")
    assert grants.active(grant, None, grant["expires_at_unix_ms"] - 1) == (True, "active")
    assert grants.active(grant, None, grant["expires_at_unix_ms"]) == (False, "expired")
    assert grants.active(grant, 500, 600) == (False, "revoked")
    assert grants.active(grant, 700, 600) == (True, "active")


def test_intent_admission_rules():
    grant, intent = example("grant"), example("intent")
    ok = dict(approvals=set(), revoked_at=None, owner_time_unix_ms=1000, policy_digest=POLICY)
    grants.check_intent(intent, grant, TOOL, **ok)
    for mutate, text in [(lambda i: i.update(capability_id="tool.other"), "capability"),
                         (lambda i: i.update(target_id="other"), "target"),
                         (lambda i: i.update(effect_class="read"), "effect class"),
                         (lambda i: i.update(policy_digest="b" * 64), "policy"),
                         (lambda i: i.update(expires_at_unix_ms=999), "expired"),
                         (lambda i: i.update(reconciliation="manual_review"), "reconciliation")]:
        bad = copy.deepcopy(intent); mutate(bad)
        with pytest.raises(GabrielError) as info:
            grants.check_intent(bad, grant, TOOL, **ok)
        assert info.value.code is Code.POLICY_DENIED, text
    with pytest.raises(GabrielError):
        grants.check_intent(intent, grant, TOOL, **dict(ok, revoked_at=900))
    with pytest.raises(GabrielError):
        grants.check_intent(intent, grant, TOOL, **dict(ok, owner_time_unix_ms=grant["expires_at_unix_ms"]))
    # approvals bind the exact intent digest; editing args invalidates
    needs = dict(TOOL, requires_approval=True)
    with pytest.raises(GabrielError):
        grants.check_intent(intent, grant, needs, **ok)
    approved = copy.deepcopy(intent); approved["approval_digest"] = approval_digest(intent)
    grants.check_intent(approved, grant, needs, **dict(ok, approvals={approval_digest(intent)}))
    edited = copy.deepcopy(approved); edited["args_ref"] = dict(intent["args_ref"], sha256="c" * 64)
    with pytest.raises(GabrielError):
        grants.check_intent(edited, grant, needs, **dict(ok, approvals={approval_digest(intent)}))
    external = dict(TOOL, effect_class="external_non_idempotent_effect")
    ext_intent = dict(intent, effect_class="external_non_idempotent_effect")
    with pytest.raises(GabrielError):  # not in grant effect classes, and no approval
        grants.check_intent(ext_intent, grant, external, **ok)


def test_child_grant_must_be_subset():
    parent = example("grant")
    child = copy.deepcopy(parent); child.update(grant_id="grant-02", parent_grant_id="grant-01")
    grants.check_child_subset(parent, child)
    wider = copy.deepcopy(child); wider["tool_ids"] = ["tool.test", "tool.other"]
    with pytest.raises(GabrielError):
        grants.check_child_subset(parent, wider)
    longer = copy.deepcopy(child); longer["expires_at_unix_ms"] += 1
    with pytest.raises(GabrielError):
        grants.check_child_subset(parent, longer)


def test_principal_authentication():
    secret = principals.new_secret()
    registry = {"principal-01": principals.secret_digest(secret)}
    assert principals.authenticate(registry, principals.Credential("principal-01", secret)) == "principal-01"
    with pytest.raises(GabrielError):
        principals.authenticate(registry, principals.Credential("principal-01", "wrong"))
    with pytest.raises(GabrielError):
        principals.authenticate(registry, principals.Credential("nobody", secret))
    assert "wrong" not in repr(principals.Credential("principal-01", "wrong"))
