"""Domain-independent goal and evidence kernel (``gabriel.kernel/1``).

Ported from the blueprint's executed reference (``gabriel.kernel-reference/1``)
with the same invariants: categorical completion over mandatory obligations,
eligibility checked by identity and context rather than status labels,
assessment identity binding the sorted multiset of every inspected evidence
ID, candidate identity binding action kind/target/payload/snapshot, and
eligibility filtering before ranking.

Hashes bind bytes; they do not authenticate an oracle, prove an observation,
authorize an effect or implement a sandbox. The owner supplies trusted
verifier receipts and gate decisions.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib

from ..contracts.codec import (MAX_INT, CodecError, canonical, loads, is_digest, is_identifier)

CONTRACT = "gabriel.kernel/1"
OUTCOMES = {"passed", "failed", "inconclusive", "not_run"}
SCOPES = {"supported", "out_of_scope", "invalid"}
EXECUTIONS = {"observed", "synthetic", "dry_run"}


@dataclass(frozen=True)
class Artifact:
    """Immutable bytes; JSON access returns a fresh mutable copy."""
    raw: bytes
    media_type: str = "application/octet-stream"

    def __post_init__(self):
        if type(self.raw) is not bytes:
            raise ValueError("artifact must own immutable bytes")
        if type(self.media_type) is not str or not self.media_type or not self.media_type.isascii():
            raise ValueError("expected nonempty ASCII media type")

    @property
    def id(self):
        return hashlib.sha256(self.raw).hexdigest()

    def ref(self):
        return {"sha256": self.id, "bytes": len(self.raw), "media_type": self.media_type}

    def json(self):
        try:
            return loads(self.raw)
        except CodecError as exc:
            raise ValueError(str(exc)) from exc


def record(kind, **content):
    try:
        return Artifact(canonical({"contract": CONTRACT, "kind": kind, **content}), "application/json")
    except CodecError as exc:
        raise ValueError(str(exc)) from exc


def digest(value):
    if not is_digest(value):
        raise ValueError("expected lowercase SHA-256 identity")
    return value


def name(value):
    if not is_identifier(value):
        raise ValueError("expected identifier matching [A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
    return value


def natural(value):
    if type(value) is not int or not 0 <= value <= MAX_INT:
        raise ValueError("expected nonnegative safe integer")
    return value


def blob_ref(value):
    if type(value) is not dict or set(value) != {"sha256", "bytes", "media_type"}:
        raise ValueError("invalid artifact reference")
    digest(value["sha256"])
    natural(value["bytes"])
    if type(value["media_type"]) is not str or not value["media_type"] or not value["media_type"].isascii():
        raise ValueError("expected nonempty ASCII media type")
    return value


def body(artifact, kind, fields):
    value = artifact.json()
    if type(value) is not dict or set(value) != set(fields) | {"contract", "kind"}:
        raise ValueError("unexpected contract fields")
    if value["contract"] != CONTRACT or value["kind"] != kind:
        raise ValueError("wrong contract or record kind")
    if canonical(value) != artifact.raw:
        raise ValueError("record is not canonically encoded")
    return value


def goal(domain, profile, parameters, obligations):
    """Obligations map unique IDs to immutable registered oracle identities.
    Every listed obligation is mandatory; optional work is not an obligation."""
    name(domain); digest(profile); blob_ref(parameters)
    if type(obligations) is not dict or not obligations:
        raise ValueError("a goal requires at least one obligation")
    for obligation, oracle in obligations.items():
        name(obligation); digest(oracle)
    return record("goal", domain=domain, profile=profile, parameters=parameters, obligations=obligations)


def goal_body(item):
    value = body(item, "goal", ("domain", "profile", "parameters", "obligations"))
    if goal(value["domain"], value["profile"], value["parameters"], value["obligations"]).id != item.id:
        raise ValueError("invalid goal")
    return value


def snapshot(domain, profile, inputs, observed_frontier, state="observed"):
    name(domain); digest(profile); natural(observed_frontier)
    if state not in {"observed", "proposed"} or type(inputs) is not dict:
        raise ValueError("invalid snapshot")
    for key, value in inputs.items():
        name(key); blob_ref(value)
    return record("snapshot", domain=domain, profile=profile, inputs=inputs,
                  observed_frontier=observed_frontier, state=state)


def snapshot_body(item):
    value = body(item, "snapshot", ("domain", "profile", "inputs", "observed_frontier", "state"))
    snapshot(value["domain"], value["profile"], value["inputs"], value["observed_frontier"], value["state"])
    return value


def check_evidence(goal_id, obligation, snapshot_id, oracle, profile, outcome, scope, execution, result):
    digest(goal_id); name(obligation); digest(snapshot_id); digest(profile)
    if oracle is not None:
        digest(oracle)
    if outcome not in OUTCOMES or scope not in SCOPES or execution not in EXECUTIONS:
        raise ValueError("invalid evidence category")
    blob_ref(result)
    return record("check", goal=goal_id, obligation=obligation, snapshot=snapshot_id, oracle=oracle,
                  profile=profile, outcome=outcome, scope=scope, execution=execution, result=result)


def assess_goal(goal_spec, current_snapshot, evidence):
    """Categorical conjunction over the selected current evidence set.

    No score, distance or priority is accepted. Duplicate or foreign records
    make the selected set invalid, never complete. The assessment identity
    binds the sorted multiset of every inspected evidence ID.
    """
    g = goal_body(goal_spec)
    s = snapshot_body(current_snapshot)
    issues, selected = [], {}
    inspected = sorted(tuple(evidence), key=lambda item: item.id)
    evidence_ids = [item.id for item in inspected]
    current = (s["state"] == "observed" and s["domain"] == g["domain"] and s["profile"] == g["profile"])
    if not current:
        issues.append("snapshot_context_invalid")
    for item in inspected:
        e = body(item, "check", ("goal", "obligation", "snapshot", "oracle", "profile", "outcome",
                                 "scope", "execution", "result"))
        check_evidence(e["goal"], e["obligation"], e["snapshot"], e["oracle"], e["profile"], e["outcome"],
                       e["scope"], e["execution"], e["result"])
        key = e["obligation"]
        if key not in g["obligations"]:
            issues.append("unknown_obligation:" + key)
        elif key in selected:
            issues.append("duplicate_evidence:" + key)
        else:
            selected[key] = e
    checks, scopes = {}, []
    for key, oracle in g["obligations"].items():
        e = selected.get(key)
        if e is None:
            checks[key] = "not_run"
            continue
        bound = (e["goal"] == goal_spec.id and e["snapshot"] == current_snapshot.id
                 and e["profile"] == g["profile"] and e["oracle"] == oracle)
        if not bound:
            issues.append("binding_invalid:" + key)
            checks[key] = "inconclusive"
        elif e["execution"] != "observed":
            checks[key] = "not_run"
        elif e["scope"] != "supported":
            checks[key] = "inconclusive"
        else:
            checks[key] = e["outcome"]
        scopes.append(e["scope"])
    scope = ("invalid" if issues or "invalid" in scopes else "out_of_scope" if "out_of_scope" in scopes else "supported")
    if issues:
        outcome = "inconclusive"
    else:
        outcome = next((x for x in ("failed", "inconclusive", "not_run") if x in checks.values()), "passed")
    satisfied = current and scope == "supported" and outcome == "passed"
    return record("assessment", goal=goal_spec.id, snapshot=current_snapshot.id, outcome=outcome, scope=scope,
                  satisfied=satisfied, checks=checks, issues=sorted(issues), evidence_ids=evidence_ids)


def progress_vector(assessment) -> dict:
    """Diagnostic counts only; never a completion authority."""
    a = assessment.json()
    counts = {"passed": 0, "failed": 0, "inconclusive": 0, "not_run": 0}
    for verdict in a["checks"].values():
        counts[verdict] += 1
    counts["issues"] = len(a["issues"])
    return counts


def complete(assessment, artifacts_verified: bool, effects_reconciled: bool) -> bool:
    """complete = (all mandatory obligations eligible-passed) and A and F."""
    if type(artifacts_verified) is not bool or type(effects_reconciled) is not bool:
        raise ValueError("A and F must be Boolean inputs")
    return bool(assessment.json()["satisfied"]) and artifacts_verified and effects_reconciled


def candidate(goal_id, snapshot_id, action_kind, target, payload, proposed_state=None):
    digest(goal_id); digest(snapshot_id); name(action_kind)
    blob_ref(target); blob_ref(payload)
    if proposed_state is not None:
        digest(proposed_state)
    return record("candidate", goal=goal_id, snapshot=snapshot_id, action_kind=action_kind, target=target,
                  payload=payload, proposed_state=proposed_state)


def gate_decision(candidate_id, goal_id, snapshot_id, policy, decision):
    for value in (candidate_id, goal_id, snapshot_id, policy):
        digest(value)
    if decision not in {"permit", "reject", "inconclusive"}:
        raise ValueError("invalid gate decision")
    return record("gate", candidate=candidate_id, goal=goal_id, snapshot=snapshot_id, policy=policy, decision=decision)


def select_candidate(candidates, gates, ranks, goal_spec, current_snapshot, policy):
    """Rank only independently eligible candidates; never infer permission from rank."""
    g = goal_body(goal_spec); s = snapshot_body(current_snapshot); digest(policy)
    if s["state"] != "observed" or s["domain"] != g["domain"] or s["profile"] != g["profile"]:
        raise ValueError("candidate selection requires current observed context")
    decisions, ids, eligible = {}, set(), []
    for receipt in gates:
        d = body(receipt, "gate", ("candidate", "goal", "snapshot", "policy", "decision"))
        gate_decision(d["candidate"], d["goal"], d["snapshot"], d["policy"], d["decision"])
        if d["candidate"] in decisions:
            raise ValueError("duplicate gate receipt")
        decisions[d["candidate"]] = d
    for item in candidates:
        c = body(item, "candidate", ("goal", "snapshot", "action_kind", "target", "payload", "proposed_state"))
        candidate(c["goal"], c["snapshot"], c["action_kind"], c["target"], c["payload"], c["proposed_state"])
        if item.id in ids:
            raise ValueError("duplicate candidate")
        ids.add(item.id)
        rank = ranks.get(item.id)
        if type(rank) is not int or not -MAX_INT <= rank <= MAX_INT:
            raise ValueError("each candidate needs a safe integer rank")
        d = decisions.get(item.id)
        if (c["goal"] == goal_spec.id and c["snapshot"] == current_snapshot.id and d and d["decision"] == "permit"
                and d["goal"] == goal_spec.id and d["snapshot"] == current_snapshot.id and d["policy"] == policy):
            eligible.append((rank, item.id, item))
    if set(ranks) != ids or set(decisions) - ids:
        raise ValueError("rank or gate refers to an unknown candidate")
    eligible.sort(key=lambda x: (-x[0], x[1]))
    return eligible[0][2] if eligible else None
