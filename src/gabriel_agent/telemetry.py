"""Operational telemetry (blueprint: operations, observability and release discipline).

Spans carry task/run/step/attempt identifiers and separate queue time, provider latency, tool
execution, verification, journal commit and artifact I/O. The exporter is best effort: a span
that cannot be written is counted as dropped and never affects the owner's audit events, which
stay authoritative. Spans hold identifiers, kinds, durations and counters only: never prompt
bytes, artifact contents or credentials.
"""
from __future__ import annotations

import contextlib
import json
import secrets
import threading
import time
from pathlib import Path

KINDS = ("run", "queue_wait", "provider", "tool_execution", "verification", "journal_commit", "artifact_io")


class Tracer:
    """JSONL span exporter with a per-thread span stack for parent identities."""

    def __init__(self, path, *, trace_id: str):
        self.path = Path(path) if path is not None else None
        self.trace_id = trace_id
        self.dropped = 0
        self.written = 0
        self._local = threading.local()
        self._lock = threading.Lock()

    # ------------------------------------------------------------ span stack
    def _stack(self) -> list:
        if not hasattr(self._local, "stack"):
            self._local.stack = []
        return self._local.stack

    def current(self) -> dict | None:
        stack = self._stack()
        return stack[-1] if stack else None

    @contextlib.contextmanager
    def span(self, kind: str, **ids):
        """A span that encloses the body; nested spans and recorded spans name it as their parent."""
        record = self._new(kind, ids)
        started = time.monotonic()
        self._stack().append(record)
        try:
            yield record["attributes"]
            record["status"] = "ok"
        except BaseException as exc:
            record["status"] = "failed"
            record["attributes"]["error"] = type(exc).__name__
            raise
        finally:
            record["duration_ms"] = int((time.monotonic() - started) * 1000)
            self._stack().pop()
            self._write(record)

    def record(self, kind: str, duration_ms: int, *, status: str = "ok", start_unix_ms: int | None = None, **ids) -> dict:
        """A completed span measured by the caller (queue wait, tool execution, provider latency)."""
        attributes = ids.pop("attributes", None) or {}
        record = self._new(kind, ids)
        if start_unix_ms is not None:
            record["start_unix_ms"] = int(start_unix_ms)
        record["duration_ms"] = int(duration_ms)
        record["status"] = status
        record["attributes"].update(attributes)
        self._write(record)
        return record

    def add(self, key: str, value: int) -> None:
        """Accumulate a counter (artifact bytes, calls) on the innermost open span."""
        current = self.current()
        if current is not None:
            current["attributes"][key] = int(current["attributes"].get(key, 0)) + int(value)

    def _new(self, kind: str, ids: dict) -> dict:
        parent = self.current()
        record = {"schema": "gabriel.span/1", "trace_id": self.trace_id, "span_id": secrets.token_hex(8),
                  "parent_span_id": parent["span_id"] if parent else None, "kind": kind,
                  "task_id": ids.get("task_id") or (parent or {}).get("task_id"), "run_id": ids.get("run_id") or (parent or {}).get("run_id"),
                  "step_id": ids.get("step_id"), "attempt_id": ids.get("attempt_id"),
                  "start_unix_ms": int(time.time() * 1000), "duration_ms": None, "status": None, "attributes": {}}
        for key, value in ids.items():
            if key not in ("task_id", "run_id", "step_id", "attempt_id") and value is not None:
                record["attributes"][key] = value
        return record

    # ------------------------------------------------------------ exporter (best effort)
    def _write(self, record: dict) -> None:
        if self.path is None:
            return
        try:
            line = json.dumps(record, sort_keys=True, separators=(",", ":"), default=str) + "\n"
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.path, "a", encoding="utf8") as stream:
                    stream.write(line)
            self.written += 1
        except (OSError, TypeError, ValueError):
            self.dropped += 1


def read_spans(path, run_id: str | None = None) -> list:
    path = Path(path)
    if not path.is_file():
        return []
    spans = []
    for line in path.read_text(encoding="utf8").splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if run_id is None or record.get("run_id") == run_id:
            spans.append(record)
    return spans


def summarize(spans: list) -> dict:
    """Totals per kind: count, total and maximum duration, artifact I/O counters."""
    per_kind = {}
    for span in spans:
        entry = per_kind.setdefault(span["kind"], {"count": 0, "total_ms": 0, "max_ms": 0, "failed": 0})
        entry["count"] += 1
        duration = int(span.get("duration_ms") or 0)
        entry["total_ms"] += duration
        entry["max_ms"] = max(entry["max_ms"], duration)
        entry["failed"] += int(span.get("status") == "failed")
    io = {"put_calls": 0, "put_bytes": 0, "get_calls": 0, "get_bytes": 0, "io_ms": 0}
    for span in spans:
        for key in io:
            io[key] += int(span.get("attributes", {}).get(key, 0))
    return {"spans": len(spans), "per_kind": per_kind, "artifact_io": io}
