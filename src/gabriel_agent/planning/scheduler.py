"""Deterministic bounded scheduling over an admitted plan projection.

Node states: ``pending`` (not yet dispatched), ``active`` (an attempt is
issued or marked), ``completed`` (result accepted, checks pending),
``verified`` (every declared check passed), ``failed``.
"""
from __future__ import annotations

# Resource-exclusive classes. An idempotent provider call is an external disclosure,
# not a competing write on a workspace resource, so it is not serialized per target.
WRITE_CLASSES = {"local_reversible_write", "external_non_idempotent_effect"}


def node_dependencies_verified(node: dict, node_states: dict) -> bool:
    return all(node_states.get(dep, {}).get("status") == "verified" for dep in node["depends_on"])


def order_nodes(nodes):
    """Higher priority first; ASCII node_id breaks ties (documented tie-break)."""
    return sorted(nodes, key=lambda n: (-n["priority"], n["node_id"]))


def ready_nodes(plan: dict, node_states: dict, active_targets: dict, *, concurrent_reads: int,
                paused: bool) -> list:
    """Nodes that may be dispatched now, in dispatch order.

    ``active_targets`` maps target_id -> {"reads": n, "writes": n} for attempts
    in issued/marked state. One writer per resource; at most
    ``concurrent_reads`` concurrent read workers overall.
    """
    if paused:
        return []
    reads_active = sum(v.get("reads", 0) for v in active_targets.values())
    ready = []
    for node in order_nodes(plan["nodes"]):
        state = node_states.get(node["node_id"], {"status": "pending"})
        if state["status"] != "pending":
            continue
        if not node_dependencies_verified(node, node_states):
            continue
        ready.append(node)
    admitted, reads = [], reads_active
    for node in ready:
        if node["effect_class"] == "read":
            if reads >= concurrent_reads:
                continue
            reads += 1
            admitted.append(node)
        else:
            admitted.append(node)
    return admitted


def writer_conflict(target_id: str, effect_class: str, active_targets: dict) -> bool:
    """True when dispatching would create a second writer on the same resource."""
    active = active_targets.get(target_id, {"reads": 0, "writes": 0})
    if effect_class in WRITE_CLASSES:
        return active.get("writes", 0) >= 1
    return False
