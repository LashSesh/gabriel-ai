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
import os
import re
import secrets
import threading
import time
from pathlib import Path

KINDS = ("run", "queue_wait", "provider", "tool_execution", "verification", "journal_commit", "artifact_io")


ROTATE_BYTES = 8 * 1024 * 1024  # ADR-26: the live spans file is rotated once it reaches this size


class Tracer:
    """JSONL span exporter with a per-thread span stack for parent identities. The live file
    is rotated once it reaches ``rotate_bytes`` (ADR-26) into ``<stem>.<unix_ms>-<pid>-<n>.jsonl``
    beside it (the name cannot collide across processes writing the same workspace); readers
    see every part in order of their rotation time."""

    def __init__(self, path, *, trace_id: str, rotate_bytes: int = ROTATE_BYTES):
        self.path = Path(path) if path is not None else None
        self.trace_id = trace_id
        self.rotate_bytes = int(rotate_bytes)
        self.rotated = 0
        self.rotation_failures = 0
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
                    size = stream.tell()
                self.written += 1
                if size >= self.rotate_bytes:
                    # the full part keeps its lines under a name that sorts after every earlier part; a failed rename leaves
                    # the live file as it is (the span is on disk, so it is not dropped) and is counted as a rotation failure
                    try:
                        self.path.rename(rotated_part_path(self.path, int(time.time() * 1000), os.getpid(), self.rotated))
                        self.rotated += 1
                    except OSError:
                        self.rotation_failures += 1
        except (OSError, TypeError, ValueError):
            self.dropped += 1


_PART = re.compile(r"^(?P<stem>.+)\.(?P<ms>\d{13})-(?P<pid>\d+)-(?P<index>\d+)$")


def rotated_part_path(path, unix_ms: int, pid: int, index: int) -> Path:
    path = Path(path)
    return path.with_name("%s.%013d-%d-%06d%s" % (path.stem, int(unix_ms), int(pid), int(index), path.suffix))


def span_files(path) -> list:
    """Every retained part of the spans file in writing order: the rotated parts by their rotation time, then the live file.
    Only parts the tracer named are parts; another file beside the live one is not read."""
    path = Path(path)
    parts = []
    if path.parent.is_dir():
        for candidate in path.parent.iterdir():
            if candidate.suffix != path.suffix or not candidate.is_file():
                continue
            match = _PART.match(candidate.stem)
            if match and match.group("stem") == path.stem:
                parts.append((int(match.group("ms")), int(match.group("pid")), int(match.group("index")), candidate))
    ordered = [candidate for _, _, _, candidate in sorted(parts)]
    if path.is_file():
        ordered.append(path)
    return ordered


def read_spans(path, run_id: str | None = None) -> list:
    spans = []
    for part in span_files(path):
        try:
            text = part.read_text(encoding="utf8")
        except OSError:
            continue  # the live file was rotated between the listing and the read; its lines are in the part just listed
        for line in text.splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if run_id is None or record.get("run_id") == run_id:
                spans.append(record)
    return spans


def spans_by_run(path) -> dict:
    """One pass over every part: run id to its spans in writing order (spans without a run under None)."""
    grouped = {}
    for span in read_spans(path):
        grouped.setdefault(span.get("run_id"), []).append(span)
    return grouped


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
