"""Real providers over HTTP with the standard-library client.

Credentials are resolved by the supervisor from an environment reference
(``env:NAME``) immediately before the request and never enter artifacts,
prompts or logs. Rate limits, transport failures, invalid output,
truncation and refusals map to distinct response statuses; a timed-out
request reports unknown usage.
"""
from __future__ import annotations

import json
import os
import socket
import time
import urllib.error
import urllib.request

from ..contracts.errors import Code, GabrielError
from .port import ProviderResponse


def resolve_credential(credential_ref: str | None) -> str | None:
    if credential_ref is None:
        return None
    if not credential_ref.startswith("env:"):
        raise GabrielError(Code.POLICY_DENIED, "only env: credential references are supported")
    value = os.environ.get(credential_ref[4:])
    if not value:
        raise GabrielError(Code.WORKER_UNAVAILABLE, "credential is not configured: " + credential_ref)
    return value


def _post(url: str, headers: dict, body: dict, timeout_s: float):
    data = json.dumps(body).encode("utf8")
    request = urllib.request.Request(url, data=data, method="POST", headers=dict(headers, **{"Content-Type": "application/json"}))
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            raw = response.read()
            status = response.status
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        status = exc.code
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as exc:
        elapsed = int((time.monotonic() - started) * 1000)
        timed_out = isinstance(exc, (socket.timeout, TimeoutError)) or "timed out" in str(exc).lower()
        return None, None, elapsed, ("timed_out" if timed_out else "failed"), str(exc)[:300]
    elapsed = int((time.monotonic() - started) * 1000)
    return raw, status, elapsed, None, None


def _http_failure(raw, status, elapsed, kind, error):
    if kind is not None:
        return ProviderResponse(kind, json.dumps({"transport_error": error}).encode("utf8"), error=error, elapsed_ms=elapsed)
    if status == 429:
        return ProviderResponse("rate_limited", raw, error="HTTP 429", elapsed_ms=elapsed, http_status=status)
    if status in (408, 504):
        return ProviderResponse("timed_out", raw, error="HTTP %d" % status, elapsed_ms=elapsed, http_status=status)
    return ProviderResponse("failed", raw, error="HTTP %d" % status, elapsed_ms=elapsed, http_status=status)


class OpenAICompatibleProvider:
    """Chat Completions API shape (OpenAI and compatible local servers)."""

    def __init__(self, profile: dict, credential: str | None, endpoint: str | None = None):
        self.profile = profile
        self.provider_id = profile["provider_id"]
        self.credential = credential
        self.endpoint = (endpoint or profile.get("endpoint") or os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")

    def generate(self, prompt: bytes, config: dict, deadline_unix_ms=None) -> ProviderResponse:
        headers = {"Authorization": "Bearer " + self.credential} if self.credential else {}
        body = {"model": self.profile["model_alias"], "messages": [{"role": "user", "content": prompt.decode("utf8")}],
                "max_tokens": config.get("max_output_tokens", self.profile["max_output_tokens"]),
                "temperature": self.profile.get("temperature_milli", 0) / 1000}
        raw, status, elapsed, kind, error = _post(self.endpoint + "/chat/completions", headers, body,
                                                  self.profile.get("timeout_ms", 60000) / 1000)
        if kind is not None or status != 200:
            return _http_failure(raw, status, elapsed, kind, error)
        try:
            doc = json.loads(raw.decode("utf8"))
            choice = doc["choices"][0]
            text = choice["message"]["content"]
            finish = choice.get("finish_reason")
            usage = doc.get("usage") or {}
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            return ProviderResponse("invalid_output", raw, error="unparseable provider envelope: " + str(exc)[:200], elapsed_ms=elapsed, http_status=status)
        base = dict(input_tokens=usage.get("prompt_tokens"), output_tokens=usage.get("completion_tokens"),
                    provider_request_id=doc.get("id"), model_revision=doc.get("model"), finish_reason=finish, elapsed_ms=elapsed, http_status=status)
        if finish == "length":
            return ProviderResponse("truncated", raw, text=text, **base)
        if finish == "content_filter" or (choice["message"].get("refusal")):
            return ProviderResponse("provider_refusal", raw, text=text, error="provider refusal", **base)
        if not isinstance(text, str):
            return ProviderResponse("invalid_output", raw, error="missing content", **base)
        return ProviderResponse("completed", raw, text=text, **base)


class AnthropicProvider:
    """Anthropic Messages API."""

    def __init__(self, profile: dict, credential: str | None, endpoint: str | None = None):
        self.profile = profile
        self.provider_id = profile["provider_id"]
        self.credential = credential
        self.endpoint = (endpoint or profile.get("endpoint") or os.environ.get("ANTHROPIC_BASE_URL") or "https://api.anthropic.com").rstrip("/")

    def generate(self, prompt: bytes, config: dict, deadline_unix_ms=None) -> ProviderResponse:
        headers = {"anthropic-version": "2023-06-01"}
        if self.credential:
            headers["x-api-key"] = self.credential
        body = {"model": self.profile["model_alias"], "max_tokens": config.get("max_output_tokens", self.profile["max_output_tokens"]),
                "messages": [{"role": "user", "content": prompt.decode("utf8")}],
                "temperature": self.profile.get("temperature_milli", 0) / 1000}
        raw, status, elapsed, kind, error = _post(self.endpoint + "/v1/messages", headers, body,
                                                  self.profile.get("timeout_ms", 60000) / 1000)
        if kind is not None or status != 200:
            return _http_failure(raw, status, elapsed, kind, error)
        try:
            doc = json.loads(raw.decode("utf8"))
            text = "".join(block.get("text", "") for block in doc["content"] if block.get("type") == "text")
            stop = doc.get("stop_reason")
            usage = doc.get("usage") or {}
        except (ValueError, KeyError, TypeError) as exc:
            return ProviderResponse("invalid_output", raw, error="unparseable provider envelope: " + str(exc)[:200], elapsed_ms=elapsed, http_status=status)
        base = dict(input_tokens=usage.get("input_tokens"), output_tokens=usage.get("output_tokens"),
                    provider_request_id=doc.get("id"), model_revision=doc.get("model"), finish_reason=stop, elapsed_ms=elapsed, http_status=status)
        if stop == "max_tokens":
            return ProviderResponse("truncated", raw, text=text, **base)
        if stop == "refusal":
            return ProviderResponse("provider_refusal", raw, text=text, error="provider refusal", **base)
        return ProviderResponse("completed", raw, text=text, **base)
