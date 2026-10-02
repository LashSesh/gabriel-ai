"""Deterministic scripted provider for lifecycle tests and fixtures.

A script maps a step key (plan node id) or a role to an ordered list of
responses. Each response declares its kind: text, truncated, invalid_json,
refusal, rate_limit, timeout or transport_error. Every call is recorded
with the prompt digest so tests can verify the exact request bytes.
"""
from __future__ import annotations

import hashlib
import json
import re
import time

from .port import ProviderResponse


class ScriptedProvider:
    provider_id = "scripted-fixture"

    def __init__(self, script: dict, model_alias: str = "fixture-v1"):
        self.script = script
        self.model_alias = model_alias
        self.cursors = {}
        self.calls = []

    @classmethod
    def from_bytes(cls, raw: bytes, model_alias="fixture-v1"):
        return cls(json.loads(raw.decode("utf8")), model_alias)

    def _next(self, key):
        steps = self.script.get("by_step", {}).get(key)
        source = "by_step:" + key if steps is not None else None
        if steps is None:
            return None, None
        index = self.cursors.get(source, 0)
        if index >= len(steps):
            index = len(steps) - 1  # repeat the last scripted response
        self.cursors[source] = index + 1
        return steps[index], source

    def generate(self, prompt: bytes, config: dict, deadline_unix_ms=None) -> ProviderResponse:
        started = time.monotonic()
        step_key = config.get("step_key")
        role = config.get("role", "worker")
        step, source = self._next(step_key) if step_key else (None, None)
        if step is None:
            steps = self.script.get("by_role", {}).get(role, [])
            source = "by_role:" + role
            index = self.cursors.get(source, 0)
            if not steps:
                step = {"kind": "failed", "error": "no scripted response for role " + role}
            else:
                if index >= len(steps):
                    index = len(steps) - 1
                step = steps[index]
                self.cursors[source] = index + 1
        self.calls.append({"prompt_sha256": hashlib.sha256(prompt).hexdigest(), "prompt_bytes": len(prompt),
                           "role": role, "step_key": step_key, "source": source, "kind": step.get("kind", "text")})
        kind = step.get("kind", "text")
        usage = step.get("usage", {})
        text = step.get("text")
        if "value" in step:
            text = json.dumps(step["value"], ensure_ascii=False)
            if kind == "value":
                kind = "text"
        if kind == "echo_reference":
            # Return the reference plan that the planner prompt carries verbatim; the owner still validates it.
            decoded = prompt.decode("utf8", "replace")
            start, end = decoded.find("<<<REFERENCE_PLAN>>>"), decoded.find("<<<END_REFERENCE_PLAN>>>")
            text = decoded[start + len("<<<REFERENCE_PLAN>>>"):end].strip() if start != -1 and end != -1 else "{}"
            kind = "text"
        if kind == "template":
            # Placeholders {{obs:<source_id>}} resolve to the observation id the prompt lists for
            # that source ("=== source <id> revision <n> observation <obs> ..."): identities that
            # only exist at run time can still be scripted deterministically.
            decoded = prompt.decode("utf8", "replace")
            ids = {}
            for m in re.finditer(r"=== source (\S+) revision (\d+) observation (\S+) ", decoded):
                ids[m.group(1)] = m.group(3)                        # {{obs:<source_id>}}: the last listed revision
                ids["%s@%s" % (m.group(1), m.group(2))] = m.group(3)  # {{obs:<source_id>@<revision>}}
            for m in re.finditer(r"=== file (\S+) observation (\S+) ", decoded):
                ids["file:" + m.group(1)] = m.group(2)              # {{obs:file:<path>}} (plain source view)
            # {{sha:<path>}} resolves to the digest the prompt lists for a target or source file, so a
            # scripted repair round can name the identity of the file as it stands after an earlier edit.
            shas = {m.group(1): m.group(2) for m in re.finditer(r"^  (\S+) ([0-9a-f]{64}) \d+$", decoded, re.MULTILINE)}
            text = re.sub(r"\{\{obs:([^}]+)\}\}", lambda m: ids.get(m.group(1), "obs-unresolved-" + m.group(1)), text or "")
            text = re.sub(r"\{\{sha:([^}]+)\}\}", lambda m: shas.get(m.group(1), "0" * 64), text)
            kind = "text"
        elapsed = int((time.monotonic() - started) * 1000)
        common = dict(input_tokens=usage.get("input_tokens", len(prompt) // 4), output_tokens=usage.get("output_tokens"),
                      provider_request_id="scripted-%d" % len(self.calls), model_revision=self.model_alias, elapsed_ms=elapsed)
        if kind == "text":
            out_tokens = common["output_tokens"] if common["output_tokens"] is not None else len(text or "") // 4
            return ProviderResponse("completed", json.dumps({"scripted": True, "text": text}, ensure_ascii=False).encode("utf8"),
                                    text=text, finish_reason="stop", **dict(common, output_tokens=out_tokens))
        if kind == "truncated":
            return ProviderResponse("truncated", json.dumps({"scripted": True, "text": text, "finish_reason": "length"}).encode("utf8"),
                                    text=text, finish_reason="length", **dict(common, output_tokens=common["output_tokens"] or 0))
        if kind == "invalid_json":
            bad = step.get("text", "{not json")
            return ProviderResponse("completed", json.dumps({"scripted": True, "text": bad}).encode("utf8"), text=bad,
                                    finish_reason="stop", **dict(common, output_tokens=common["output_tokens"] or 0))
        if kind == "refusal":
            return ProviderResponse("provider_refusal", b'{"scripted":true,"refusal":true}', text=None, finish_reason="refusal",
                                    error="provider refused the request", **dict(common, output_tokens=0))
        if kind == "rate_limit":
            return ProviderResponse("rate_limited", b'{"scripted":true,"error":{"type":"rate_limit_error"}}', error="rate limited",
                                    http_status=429, **dict(common, input_tokens=None, output_tokens=None))
        if kind == "timeout":
            return ProviderResponse("timed_out", b'{"scripted":true,"error":"timeout"}', error="transport timeout; usage unknown",
                                    **dict(common, input_tokens=None, output_tokens=None))
        if kind == "transport_error":
            return ProviderResponse("failed", b'{"scripted":true,"error":"connection reset"}', error="connection reset",
                                    **dict(common, input_tokens=None, output_tokens=None))
        return ProviderResponse("failed", json.dumps({"scripted": True, "error": step.get("error", "unknown kind")}).encode("utf8"),
                                error=step.get("error", "unknown scripted kind"), **dict(common, input_tokens=None, output_tokens=None))
