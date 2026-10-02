"""Cross-record rules that JSON Schema cannot express.

These are pure functions over already schema-valid values. They raise
``GabrielError`` with the relevant code; they never touch storage.
"""
from __future__ import annotations

from .codec import canonical, digest
from .errors import Code, GabrielError

PLAN_LIMITS = {"max_nodes": 64, "max_depth": 12, "max_repair_attempts": 2}
BUDGET_DIMENSIONS = ("model_tokens", "model_requests", "tool_attempts", "cpu_ms",
                     "artifact_bytes", "currency_micro_units")
# budget record field -> usage/reservation field
CEILING_MAP = {"model_tokens_total": "model_tokens", "model_requests": "model_requests",
               "tool_attempts": "tool_attempts", "cpu_ms": "cpu_ms",
               "artifact_bytes": "artifact_bytes", "currency_micro_units": "currency_micro_units"}


def plan_dag(plan: dict, limits: dict | None = None) -> dict:
    """Validate acyclicity, identities, depth and output bindings. Returns depths."""
    limits = dict(PLAN_LIMITS, **(limits or {}))
    nodes = plan["nodes"]
    if len(nodes) > limits["max_nodes"]:
        raise GabrielError(Code.INVALID_SCHEMA, "plan exceeds %d nodes" % limits["max_nodes"], obj=plan["plan_id"])
    if plan["max_depth"] > limits["max_depth"]:
        raise GabrielError(Code.INVALID_SCHEMA, "plan max_depth exceeds %d" % limits["max_depth"], obj=plan["plan_id"])
    indexed = {}
    for node in nodes:
        if node["node_id"] in indexed:
            raise GabrielError(Code.INVALID_SCHEMA, "duplicate node id " + node["node_id"], obj=plan["plan_id"])
        if node["max_repair_attempts"] > limits["max_repair_attempts"]:
            raise GabrielError(Code.INVALID_SCHEMA, "node repair attempts exceed limit", obj=node["node_id"])
        indexed[node["node_id"]] = node
    depths, active, visited = {}, set(), set()

    def visit(identity):
        if identity not in indexed:
            raise GabrielError(Code.INVALID_SCHEMA, "unknown dependency " + identity, obj=plan["plan_id"])
        if identity in active:
            raise GabrielError(Code.INVALID_SCHEMA, "plan contains a cycle through " + identity, obj=plan["plan_id"])
        if identity in visited:
            return depths[identity]
        active.add(identity)
        depth = 1 + max((visit(dep) for dep in indexed[identity]["depends_on"]), default=0)
        active.remove(identity)
        visited.add(identity)
        depths[identity] = depth
        return depth

    for identity in indexed:
        visit(identity)
    if max(depths.values()) > plan["max_depth"]:
        raise GabrielError(Code.INVALID_SCHEMA, "plan depth exceeds its admitted maximum", obj=plan["plan_id"])

    def ancestors(identity):
        found = set()
        for dep in indexed[identity]["depends_on"]:
            found.add(dep)
            found |= ancestors(dep)
        return found

    for node in nodes:
        slots = [o["output_slot"] for o in node["outputs"]]
        if len(slots) != len(set(slots)):
            raise GabrielError(Code.INVALID_SCHEMA, "duplicate output slot", obj=node["node_id"])
        for item in node["inputs"]:
            if "producer_node" not in item:
                continue
            producer = item["producer_node"]
            if producer not in ancestors(node["node_id"]):
                raise GabrielError(Code.INVALID_SCHEMA, "future output must come from a declared prerequisite", obj=node["node_id"])
            declared = {o["output_slot"]: o["schema_digest"] for o in indexed[producer]["outputs"]}
            if declared.get(item["output_slot"]) != item["required_schema"]:
                raise GabrielError(Code.INVALID_SCHEMA, "unavailable output slot or mismatched schema", obj=node["node_id"])
    return depths


def plan_authority(plan: dict, task: dict, grant: dict, catalog_tools: dict) -> None:
    """Capabilities, checks and effect classes must exist and be granted."""
    known_checks = {c["check_id"] for c in task["checks"]}
    for node in plan["nodes"]:
        tool = catalog_tools.get(node["capability_id"])
        if tool is None:
            raise GabrielError(Code.POLICY_DENIED, "unknown capability " + node["capability_id"], obj=node["node_id"])
        if node["capability_id"] not in grant["tool_ids"]:
            raise GabrielError(Code.POLICY_DENIED, "capability not granted: " + node["capability_id"], obj=node["node_id"])
        if node["effect_class"] != tool["effect_class"]:
            raise GabrielError(Code.POLICY_DENIED, "node effect class disagrees with registered tool", obj=node["node_id"])
        if node["effect_class"] not in grant["effect_classes"]:
            raise GabrielError(Code.POLICY_DENIED, "effect class not granted: " + node["effect_class"], obj=node["node_id"])
        if not set(node["check_ids"]) <= known_checks:
            raise GabrielError(Code.INVALID_SCHEMA, "node names an unknown check", obj=node["node_id"])


def plan_budget_feasible(plan: dict, ceiling: dict) -> None:
    """Every single node reservation must fit the task ceiling (not the sum:
    reservations are admitted one by one at dispatch under the live ledger)."""
    for node in plan["nodes"]:
        for cfield, ufield in CEILING_MAP.items():
            if node["reservation"][ufield] > ceiling[cfield]:
                raise GabrielError(Code.BUDGET_EXHAUSTED, "node reservation exceeds ceiling in " + ufield, obj=node["node_id"])
        if node["reservation"]["currency"] != ceiling["currency"]:
            raise GabrielError(Code.INVALID_SCHEMA, "reservation currency differs from ceiling", obj=node["node_id"])


def mandatory_check_ids(task: dict) -> set:
    return {c["check_id"] for c in task["checks"] if c["mandatory"]}


def amendment_weakens(old_task: dict, new_task: dict) -> bool:
    """True when a mandatory check disappears, becomes optional or changes spec."""
    old = {c["check_id"]: c for c in old_task["checks"] if c["mandatory"]}
    new = {c["check_id"]: c for c in new_task["checks"]}
    for cid, check in old.items():
        if cid not in new or not new[cid]["mandatory"]:
            return True
        if canonical(new[cid]["spec_ref"]) != canonical(check["spec_ref"]) or new[cid]["version"] != check["version"]:
            return True
    for cfield in CEILING_MAP:
        if new_task["budget_ceiling"][cfield] > old_task["budget_ceiling"][cfield]:
            return True
    return False


def approval_digest(intent: dict) -> str:
    """The exact intent digest that an approval binds."""
    bound = {k: intent[k] for k in ("intent_id", "task_id", "run_id", "capability_id", "target_id",
                                    "args_ref", "precondition_ref", "effect_class", "policy_digest")}
    return digest({"approval": "gabriel.approval/1", "intent": bound})


def event_hash(envelope: dict) -> str:
    """SHA-256 over the ASCII domain prefix followed by canonical envelope bytes."""
    import hashlib
    return hashlib.sha256(b"gabriel.event/1:" + canonical(envelope)).hexdigest()
