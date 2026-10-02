"""Provider port: one request in, one retained response out."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

STATUSES = {"completed", "truncated", "invalid_output", "provider_refusal", "rate_limited", "timed_out", "failed"}


@dataclass
class ProviderResponse:
    status: str                          # one of STATUSES; "completed" means a complete text was returned
    raw_bytes: bytes                     # exact provider response bytes (or synthesized error record)
    text: str | None = None              # extracted output text when any
    input_tokens: int | None = None      # None means unknown usage
    output_tokens: int | None = None
    provider_request_id: str | None = None
    model_revision: str | None = None    # exact revision if the provider exposes one, else None
    finish_reason: str | None = None
    error: str | None = None
    elapsed_ms: int = 0
    http_status: int | None = None
    diagnostics: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.status not in STATUSES:
            raise ValueError("unknown provider status " + str(self.status))


class ModelPort(Protocol):
    provider_id: str

    def generate(self, prompt: bytes, config: dict, deadline_unix_ms: int | None = None) -> ProviderResponse: ...
