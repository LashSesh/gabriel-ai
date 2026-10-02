"""AT10 scheduler ordering and bounds (plan validation lives in test_contracts)."""
import copy
from pathlib import Path

from gabriel_agent.contracts import loads
from gabriel_agent.planning import ready_nodes, order_nodes
from gabriel_agent.planning.scheduler import writer_conflict

EXAMPLES = Path(__file__).resolve().parents[1] / "contracts" / "examples"


def make_plan(n, priority=0):
    plan = loads((EXAMPLES / "plan.json").read_bytes())
    template = plan["nodes"][0]
    plan["nodes"] = []
    for i in range(n):
        node = copy.deepcopy(template)
        node["node_id"] = "n%02d" % i
        node["priority"] = priority
        node["effect_class"] = "read"
        plan["nodes"].append(node)
    return plan


def test_equal_priority_uses_node_id_tie_break():
    plan = make_plan(5)
    plan["nodes"].reverse()
    plan["nodes"][0]["priority"] = 3
    ordered = order_nodes(plan["nodes"])
    assert [n["node_id"] for n in ordered] == ["n04", "n00", "n01", "n02", "n03"]


def test_dependencies_and_pause_and_read_worker_bound():
    plan = make_plan(6)
    plan["nodes"][5]["depends_on"] = ["n00"]
    states = {}
    ready = ready_nodes(plan, states, {}, concurrent_reads=4, paused=False)
    assert [n["node_id"] for n in ready] == ["n00", "n01", "n02", "n03"]
    assert ready_nodes(plan, states, {}, concurrent_reads=4, paused=True) == []
    states = {"n00": {"status": "verified"}, "n01": {"status": "active"}}
    active = {"worktree-01": {"reads": 1, "writes": 0}}
    ready = ready_nodes(plan, states, active, concurrent_reads=4, paused=False)
    assert [n["node_id"] for n in ready] == ["n02", "n03", "n04"]  # n05 unlocked but only 3 slots remain


def test_single_writer_per_resource():
    assert writer_conflict("wt", "local_reversible_write", {"wt": {"reads": 2, "writes": 1}})
    assert not writer_conflict("wt", "read", {"wt": {"reads": 2, "writes": 1}})
    assert not writer_conflict("wt", "local_reversible_write", {"other": {"reads": 0, "writes": 1}})
