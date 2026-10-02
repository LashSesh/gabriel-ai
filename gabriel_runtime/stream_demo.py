"""Synthetic raw-price demonstration for the explicitly selected stream profile.

Input prices are finite dyadic values. All submitted representations are retained
as hexadecimal binary64 strings; no data service or random generator is used.
"""
from pathlib import Path

from .canonical import canonical
from .engine import Store
from .stream import extended_registry


def _write(path, value):
    with Path(path).open("x", encoding="ascii") as stream:
        stream.write(canonical(value) + "\n")


def _price(index):
    return 100.0 + (((index * 37) % 97) - 48) / 32.0 + (((index * 13) % 17) - 8) / 64.0


def run_demo(directory, *, registry_factory=extended_registry, profile="stream", store_class=Store):
    """Create the shared synthetic trace under one explicitly selected registry.

    The default preserves the original stream demo. The incremental CLI supplies
    its fixed registry factory; the underlying input sequence is unchanged.
    Owner selection changes execution only, not the retained trace or metadata.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    commands = []
    issues = []
    config = {"source_id": "synthetic-dyadic-prices", "horizon": 1,
              "risk_budget": "10", "unit_exposure": "100", "max_units": 100}
    with store_class.create(directory / "owner.sqlite", registry_factory()) as store:
        def submit(operation, at, payload):
            command = {"id": "stream-demo-" + str(len(commands) + 1),
                       "contract": "stream", "op": operation, "at": at,
                       "expected_head": store.head, "payload": payload}
            receipt = store.submit(command)
            commands.append(command)
            if operation == "record" and receipt["result"]["issued"] is not None:
                issues.append(receipt["result"]["issued"])
            return receipt

        first_receipt = submit("bind", 0, {"adapter": "stream-risk/v1", "config": config})
        for index in range(319):
            submit("record", index, {"index": index, "event_at": index,
                                     "received_at": index, "revision": 0,
                                     "rate_hex": _price(index).hex()})
        before_view = store.view("stream")
        before_records = store.export()["records"]
        old_issue_count = len(issues)
        if old_issue_count < 2:
            raise ValueError("synthetic fixture failed to reach forecast and feedback stages")
        correction = submit("record", 319, {
            "index": 316, "event_at": 316, "received_at": 319,
            "revision": 1, "rate_hex": (_price(316) * (33.0 / 32.0)).hex()})
        corrected_view = store.view("stream")
        after_records = store.export()["records"]
        preserved = canonical(after_records[:len(before_records)]) == canonical(before_records)
        no_historical_reissue = (correction["result"]["issued"] is None
                                 and corrected_view["issued_count"] == before_view["issued_count"]
                                 and corrected_view["last_issued_digest"] == before_view["last_issued_digest"])
        feedback_changed = canonical(before_view["learner"]) != canonical(corrected_view["learner"])
        if not preserved or not no_historical_reissue or not feedback_changed:
            raise ValueError("correction demonstration invariants failed")
        new_receipt = submit("record", 320, {
            "index": 319, "event_at": 319, "received_at": 320,
            "revision": 0, "rate_hex": _price(319).hex()})
        new_issue = new_receipt["result"]["issued"]
        if new_issue is None or len(issues) != old_issue_count + 1:
            raise ValueError("new source slot failed to produce its current forecast")
        final_view = store.view("stream")
        before_retry = store.budget
        same_receipt = canonical(store.submit(commands[0])) == canonical(first_receipt)
        if not same_receipt or store.budget != before_retry:
            raise ValueError("identical retry altered the stream run")
        anchor = {"head": store.head, "events": store.budget["events"]}
        audit = store.audit(expected_head=anchor["head"], expected_events=anchor["events"])
        journal = store.export()
        summary = {
            "status": "passed", "profile": profile, "example_kind": "synthetic",
            "claim": "raw observations, issued forecasts and revised feedback; no predictive performance experiment",
            "fixture": {"formula": "100 + (((i*37)%97)-48)/32 + (((i*13)%17)-8)/64",
                        "initial_indexes": [0, 318], "corrected_index": 316,
                        "correction_factor": "33/32", "subsequent_index": 319},
            "config": config, "anchor": anchor, "audit": audit,
            "source_bindings": journal["header"]["registry"],
            "published_prefix_unchanged_after_correction": preserved,
            "correction_without_historical_reissue": no_historical_reissue,
            "current_feedback_changed": feedback_changed,
            "identical_retry_without_new_charge": True,
            "snapshots": {"before_correction": before_view,
                          "after_correction": corrected_view, "after_new_slot": final_view},
            "issued_forecasts": issues}
    _write(directory / "commands.json", commands)
    _write(directory / "journal.json", journal)
    _write(directory / "anchor.json", anchor)
    _write(directory / "summary.json", summary)
    return {"status": "passed", "profile": profile, "example_kind": "synthetic",
            "prediction_basis": final_view["prediction_basis"],
            "events": anchor["events"], "head": anchor["head"],
            "source_count": final_view["source_count"],
            "revision_count": final_view["revision_count"],
            "issued_count": final_view["issued_count"],
            "pending_count": final_view["pending_count"],
            "published_prefix_unchanged_after_correction": preserved,
            "correction_without_historical_reissue": no_historical_reissue,
            "current_feedback_changed": feedback_changed,
            "last_issued_digest": final_view["last_issued_digest"],
            "proposal": new_issue["proposal"]}
