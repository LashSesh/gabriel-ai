"""Structured errors with stable codes and a retryability classification."""
from __future__ import annotations

from enum import Enum


class Code(str, Enum):
    INVALID_SCHEMA = "INVALID_SCHEMA"
    STALE_REVISION = "STALE_REVISION"
    ID_REUSE = "ID_REUSE"
    POLICY_DENIED = "POLICY_DENIED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    ARTIFACT_MISSING = "ARTIFACT_MISSING"
    WORKER_UNAVAILABLE = "WORKER_UNAVAILABLE"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"
    STORAGE_FAULT = "STORAGE_FAULT"
    INVALID_TRANSITION = "INVALID_TRANSITION"
    STALE_EVIDENCE = "STALE_EVIDENCE"
    UNKNOWN_OBJECT = "UNKNOWN_OBJECT"
    UNSUPPORTED = "UNSUPPORTED"


# A safe retry requires the operation's retry class; these flags only say
# whether the same request can ever become admissible without a new decision.
_RETRYABLE = {
    Code.WORKER_UNAVAILABLE: True,
    Code.STORAGE_FAULT: False,
    Code.STALE_REVISION: False,   # reread state and submit a new decision
    Code.ID_REUSE: False,
    Code.INVALID_SCHEMA: False,
    Code.POLICY_DENIED: False,
    Code.BUDGET_EXHAUSTED: False,
    Code.ARTIFACT_MISSING: False,
    Code.OUTCOME_UNKNOWN: False,
    Code.INVALID_TRANSITION: False,
    Code.STALE_EVIDENCE: False,
    Code.UNKNOWN_OBJECT: False,
    Code.UNSUPPORTED: False,
}


class GabrielError(Exception):
    """Owner/API error: stable code, retryability, related object and message."""

    def __init__(self, code: Code, message: str, *, obj: str | None = None,
                 revision: int | None = None, details: dict | None = None):
        super().__init__(f"{code.value}: {message}")
        self.code = Code(code)
        self.message = message
        self.obj = obj
        self.revision = revision
        self.details = details or {}

    @property
    def retryable(self) -> bool:
        return _RETRYABLE[self.code]

    def to_record(self) -> dict:
        record = {"code": self.code.value, "message": self.message,
                  "retryable": self.retryable}
        if self.obj is not None:
            record["object"] = self.obj
        if self.revision is not None:
            record["revision"] = self.revision
        if self.details:
            record["details"] = self.details
        return record
