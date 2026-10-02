"""Small local CLI with explicit owner selection; no external actuation.

From the project directory: ``python -m gabriel_runtime demo --out demo_run``.
The demo is synthetic and uses both unchanged research adapters in one store.
"""
import argparse
from pathlib import Path
import sqlite3
import sys

from .adapters import default_registry
from .canonical import canonical, loads
from .engine import Store


def _input(value):
    """Accept either inline JSON or a UTF-8 JSON filename, strictly parsed."""
    text = value if value.lstrip().startswith("{") else Path(value).read_text(encoding="utf-8")
    return loads(text)


def _write(path, value):
    # Refuse silent replacement of an earlier run or export.
    with Path(path).open("x", encoding="ascii") as stream:
        stream.write(canonical(value) + "\n")


def _emit(value):
    sys.stdout.write(canonical(value) + "\n")


def _registry_for_profile(profile):
    """Select one fixed local registry explicitly, never infer it from a DB."""
    if profile == "legacy":
        return default_registry()
    if profile == "stream":
        from .stream import extended_registry
        return extended_registry()
    if profile == "incremental":
        from .incremental import incremental_registry
        return incremental_registry()
    raise ValueError("unsupported registry profile")


def _owner_for_choice(owner):
    """Execution choice is independent of the immutable adapter profile."""
    if owner == "reference":
        return Store
    if owner == "fast":
        from .fast_owner import FastStore
        return FastStore
    if owner == "replay":
        from .replay_owner import ReplayStore
        return ReplayStore
    raise ValueError("unsupported owner")


def _demo(directory, with_conflict=False, *, store_class=Store):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    commands = []
    snapshots = {}
    finite_config = {
        "contract_id": "synthetic-two-query-catalogue",
        "query_names": ["q0", "q1"], "costs": [1, 1],
        "rows": [["0", "0"], ["0", "1"], ["1", "0"], ["1", "1"]],
        "labels": [0, 0, 0, 1], "weights": []}
    risk_config = {
        "scoring_rule_id": "binary64-upper-loss-hit-primary-v1",
        "availability_mode": "declared_observed_receipts",
        "initial_states": {"0": {"theta_units": 0, "updates": 0}}}
    with store_class.create(directory / "owner.sqlite", default_registry()) as store:
        def submit(contract, op, at, payload):
            command = {"id": "demo-" + str(len(commands) + 1), "contract": contract,
                       "op": op, "at": at, "expected_head": store.head, "payload": payload}
            receipt = store.submit(command)
            commands.append(command)
            return receipt

        first = submit("perception", "bind", 0,
                       {"adapter": "finite-observation/v1", "config": finite_config})
        submit("risk", "bind", 0, {"adapter": "maturity-risk/v1", "config": risk_config})
        submit("risk", "issue", 0, {
            "forecast_id": "synthetic-f0", "origin": 0, "target_end": 2,
            "issued_at": 0, "requirements": [
                {"source_id": "synthetic-price", "record_id": "p0", "event_start": 0, "event_end": 0},
                {"source_id": "synthetic-price", "record_id": "p2", "event_start": 2, "event_end": 2}],
            "prediction": {"var_hex": (1.0).hex(), "es_hex": (2.0).hex()},
            "lane_id": "0", "provenance": {"purpose": "synthetic-runtime-demonstration"}})

        def observe(contract, query, outcome, source, at):
            return submit(contract, "observe", at, {
                "query": query, "outcome": outcome, "source_id": source,
                "event_interval": [0, 0], "received_at": at,
                "status": "observed", "kind": "passive", "cutoff": at})

        def endpoint(record, event, revision, at, rate):
            return submit("risk", "outcome", at, {
                "source_id": "synthetic-price", "record_id": record,
                "revision": revision, "event_interval": [event, event],
                "received_at": at, "vintage_id": "v" + str(revision),
                "payload": {"rate_hex": rate.hex()}})

        observe("perception", 0, "1", "synthetic-q0", 1)
        snapshots["finite_after_first_query"] = store.view("perception")
        endpoint("p0", 0, 0, 1, 100.0)
        snapshots["risk_pending"] = store.view("risk")
        observe("perception", 1, "0", "synthetic-q1", 2)
        snapshots["finite_after_second_query"] = store.view("perception")
        endpoint("p2", 2, 0, 3, 104.0)
        snapshots["risk_after_first_maturity"] = store.view("risk")
        endpoint("p2", 2, 1, 4, 100.5)
        snapshots["risk_after_correction"] = store.view("risk")
        submit("risk", "query", 4,
               {"event_cutoff": 2, "receipt_cutoff": 3, "operation_cutoff": None})
        snapshots["risk_as_of_first_maturity"] = store.view("risk")
        if with_conflict:
            submit("conflict-example", "bind", 4,
                   {"adapter": "finite-observation/v1", "config": finite_config})
            observe("conflict-example", 0, "0", "conflict-source-a", 4)
            observe("conflict-example", 0, "1", "conflict-source-b", 4)
            snapshots["finite_separate_conflict"] = store.view("conflict-example")
        before_retry = store.budget
        retry = store.submit(commands[0])
        if canonical(retry) != canonical(first) or store.budget != before_retry:
            raise ValueError("demo retry invariant failed")
        anchor = {"head": store.head, "events": store.budget["events"]}
        audit = store.audit(expected_head=anchor["head"], expected_events=anchor["events"])
        journal = store.export()
        summary = {"status": "passed", "example_kind": "synthetic",
                   "claim": "local operational trace; no predictive performance experiment",
                   "anchor": anchor, "audit": audit,
                   "identical_retry_without_new_charge": True, "snapshots": snapshots}
    _write(directory / "commands.json", commands)
    _write(directory / "journal.json", journal)
    _write(directory / "anchor.json", anchor)
    _write(directory / "summary.json", summary)
    return {"status": "passed", "example_kind": "synthetic", "events": anchor["events"],
            "head": anchor["head"], "finite_result": snapshots["finite_after_second_query"]["result"],
            "risk_after_maturity": snapshots["risk_after_first_maturity"]["controller_states"],
            "risk_after_correction": snapshots["risk_after_correction"]["controller_states"],
            "risk_as_of_first_maturity": snapshots["risk_as_of_first_maturity"]["controller_states"],
            "separate_conflict_included": with_conflict}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Gabriel local transactional runtime")
    commands = parser.add_subparsers(dest="action", required=True)
    demo = commands.add_parser("demo", help="create a new synthetic two-adapter run")
    demo.add_argument("--out", required=True, metavar="DIR", help="new directory (must not exist)")
    demo.add_argument("--with-conflict", action="store_true", help="include a separate contradictory evidence contract")
    stream_demo = commands.add_parser("stream-demo", help="create a synthetic raw-price forecasting run")
    stream_demo.add_argument("--out", required=True, metavar="DIR", help="new directory (must not exist)")
    incremental_demo = commands.add_parser("incremental-demo", help="run the same synthetic stream with incremental execution")
    incremental_demo.add_argument("--out", required=True, metavar="DIR", help="new directory (must not exist)")
    inspect = commands.add_parser("inspect", help="replay-check a store and display one contract")
    inspect.add_argument("database", metavar="DB")
    inspect.add_argument("--contract", required=True, metavar="ID")
    audit = commands.add_parser("audit", help="replay-check a store, optionally against a retained anchor")
    audit.add_argument("database", metavar="DB")
    audit.add_argument("--anchor", metavar="JSON", help="JSON file or inline object with exactly head and events")
    export = commands.add_parser("export", help="export replay-checked canonical journal")
    export.add_argument("database", metavar="DB")
    export.add_argument("--out", required=True, metavar="JSON", help="new output JSON file")
    submit = commands.add_parser("submit", help="submit one strict command without automatic retry")
    submit.add_argument("database", metavar="DB")
    submit.add_argument("--command", required=True, metavar="JSON", help="JSON file or inline command object")
    for command_parser in (inspect, audit, export, submit):
        command_parser.add_argument("--profile", choices=("legacy", "stream", "incremental"), default="legacy",
                                    help="fixed registry profile; legacy is the original two-adapter profile")
    for command_parser in (demo, stream_demo, incremental_demo, inspect, audit, export, submit):
        command_parser.add_argument("--owner", choices=("reference", "fast", "replay"), default="reference",
                                    help="execution owner; all use the same journal format and adapter fingerprints")
    args = parser.parse_args(argv)
    try:
        store_class = _owner_for_choice(args.owner)
        if args.action == "demo":
            _emit(_demo(args.out, args.with_conflict, store_class=store_class))
            return 0
        if args.action == "stream-demo":
            from .stream_demo import run_demo
            _emit(run_demo(args.out, store_class=store_class))
            return 0
        if args.action == "incremental-demo":
            from .incremental import incremental_registry
            from .stream_demo import run_demo
            _emit(run_demo(args.out, registry_factory=incremental_registry,
                           profile="incremental", store_class=store_class))
            return 0
        anchors = {}
        if args.action == "audit" and args.anchor:
            anchor = _input(args.anchor)
            if type(anchor) is not dict or set(anchor) != {"head", "events"}:
                raise ValueError("anchor requires exactly head and events")
            anchors = {"expected_head": anchor["head"], "expected_events": anchor["events"]}
        with store_class.open(args.database, _registry_for_profile(args.profile), **anchors) as store:
            if args.action == "inspect":
                _emit(store.view(args.contract))
            elif args.action == "audit":
                _emit(store.audit(**anchors))
            elif args.action == "export":
                value = store.export()
                _write(args.out, value)
                _emit({"status": "exported", "events": len(value["records"])})
            else:
                _emit(store.submit(_input(args.command)))
        return 0
    except (ValueError, OSError, sqlite3.Error) as exc:
        sys.stderr.write("Gabriel runtime: " + str(exc) + "\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
