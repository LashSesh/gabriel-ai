"""Vector resource ledger: admission requires S + R + d <= B componentwise.

``elapsed_ms`` is a run wall-clock deadline checked against trusted owner
time; it never enters the additive ledger. Unknown usage keeps a conservative
charge; overruns are retained and suspend further admission.
"""
from __future__ import annotations

from ..contracts.errors import Code, GabrielError
from ..contracts.rules import BUDGET_DIMENSIONS, CEILING_MAP

DIMS = BUDGET_DIMENSIONS


def zero() -> dict:
    return {d: 0 for d in DIMS}


def ceiling_vector(budget: dict) -> dict:
    return {u: budget[c] for c, u in CEILING_MAP.items()}


def usage_vector(usage: dict) -> dict:
    return {d: usage[d] for d in DIMS}


def add(a: dict, b: dict) -> dict:
    return {d: a[d] + b[d] for d in DIMS}


def sub(a: dict, b: dict) -> dict:
    return {d: a[d] - b[d] for d in DIMS}


def admit(spent: dict, reserved: dict, demand: dict, ceiling: dict) -> dict:
    """Return the new reserved vector or raise BUDGET_EXHAUSTED."""
    short = {}
    for d in DIMS:
        if demand[d] < 0:
            raise GabrielError(Code.INVALID_SCHEMA, "negative demand in " + d)
        if spent[d] + reserved[d] + demand[d] > ceiling[d]:
            short[d] = {"spent": spent[d], "reserved": reserved[d], "demand": demand[d], "ceiling": ceiling[d]}
    if short:
        raise GabrielError(Code.BUDGET_EXHAUSTED, "reservation exceeds ceiling in " + ", ".join(sorted(short)),
                           details={"dimensions": short})
    return add(reserved, demand)


def confirm(spent: dict, reserved: dict, demand: dict, actual: dict, accounting_status: str):
    """Replace a reservation by accounted consumption.

    Confirmed usage charges the actual vector even when it exceeds the
    reservation (the overrun is retained, never clipped). Usage that is still
    unknown charges max(actual, demand) per dimension and stays pending.
    """
    new_reserved = sub(reserved, demand)
    for d in DIMS:
        if new_reserved[d] < 0:
            raise GabrielError(Code.INVALID_SCHEMA, "reservation release exceeds reserved amount in " + d)
    if accounting_status == "confirmed":
        charge = actual
        pending = False
    elif accounting_status == "conservative_pending_reconciliation":
        charge = {d: max(actual[d], demand[d]) for d in DIMS}
        pending = True
    else:
        raise GabrielError(Code.INVALID_SCHEMA, "unknown accounting status " + str(accounting_status))
    overrun = {d: actual[d] - demand[d] for d in DIMS if actual[d] > demand[d]}
    return add(spent, charge), new_reserved, overrun, pending


def release(reserved: dict, demand: dict) -> dict:
    new_reserved = sub(reserved, demand)
    for d in DIMS:
        if new_reserved[d] < 0:
            raise GabrielError(Code.INVALID_SCHEMA, "reservation release exceeds reserved amount in " + d)
    return new_reserved


def deadline_exceeded(started_owner_time_ms, elapsed_allowance_ms: int, owner_time_ms: int) -> bool:
    if started_owner_time_ms is None:
        return False
    return owner_time_ms - started_owner_time_ms > elapsed_allowance_ms


def remaining(spent: dict, reserved: dict, ceiling: dict) -> dict:
    return {d: ceiling[d] - spent[d] - reserved[d] for d in DIMS}
