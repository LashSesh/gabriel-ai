"""Model gateway: retained requests, retained raw responses, strict normalization.

Each request retains the exact prompt bytes, ordered evidence references,
tool-schema and output-schema identities, sampling configuration and the
observation frontier. Responses retain raw bytes, normalized output,
request identifier, finish reason, usage and timing. A partial response is
never parsed as a complete result; a timed-out request keeps unknown usage
as a conservative charge.
"""
from __future__ import annotations

import json
import time

from ..contracts.codec import CodecError, canonical, digest, dumps_utf8, loads, sha256_hex
from ..contracts.errors import Code, GabrielError
from ..contracts.schemas import schema_digest, validate
from ..workers.supervisor import ToolOutcome
from .http_providers import AnthropicProvider, OpenAICompatibleProvider, resolve_credential
from .scripted import ScriptedProvider

NORMALIZATION_PROFILE = "json-fenced-v1"


def provider_for_profile(profile: dict, store=None):
    validate(profile, "provider-profile")
    kind = profile["kind"]
    if kind == "scripted":
        if profile["script_ref"] is None or store is None:
            raise GabrielError(Code.INVALID_SCHEMA, "scripted provider needs a script artifact")
        provider = ScriptedProvider.from_bytes(store.get(profile["script_ref"]), profile["model_alias"])
        provider.provider_id = profile["provider_id"]
        return provider
    credential = resolve_credential(profile["credential_ref"])
    if kind == "openai_compat":
        return OpenAICompatibleProvider(profile, credential)
    if kind == "anthropic":
        return AnthropicProvider(profile, credential)
    raise GabrielError(Code.UNSUPPORTED, "unknown provider kind " + kind)


def strip_fence(text: str) -> tuple[str, list]:
    """Remove one surrounding Markdown code fence; report the loss."""
    loss = []
    stripped = text.strip()
    if stripped.startswith("```"):
        first_newline = stripped.find("\n")
        if first_newline != -1 and stripped.endswith("```"):
            stripped = stripped[first_newline + 1:-3].strip()
            loss.append("code fence removed")
    return stripped, loss


def normalize_json_output(text: str, schema_name: str) -> tuple[dict | None, list, str | None]:
    """Strict parse (duplicate keys and floats reject) and schema validation."""
    body, loss = strip_fence(text)
    try:
        value = loads(body.encode("utf8"), ascii_only=False)
    except CodecError as exc:
        return None, loss, "invalid JSON: " + str(exc)[:200]
    try:
        validate(value, schema_name, ascii_only=False)
    except GabrielError as exc:
        return None, loss, "schema violation: " + exc.message[:300]
    return value, loss, None


def build_model_request(*, request_id, task_id, run_id, provider_profile, role, prompt_ref, evidence_refs, observation_ids,
                        issue_frontier, output_schema_name, tool_schema_digest, sampling_config_ref, max_input_tokens, max_output_tokens):
    record = {"schema": "gabriel.model-request/1", "request_id": request_id, "task_id": task_id, "run_id": run_id,
              "provider_id": provider_profile["provider_id"], "model_alias": provider_profile["model_alias"],
              "model_revision": None, "prompt_ref": prompt_ref, "evidence_refs": list(evidence_refs),
              "tool_schema_digest": tool_schema_digest, "output_schema_digest": schema_digest(output_schema_name),
              "sampling_config_ref": sampling_config_ref, "max_input_tokens": max_input_tokens,
              "max_output_tokens": max_output_tokens, "role": role, "observation_ids": list(observation_ids),
              "issue_frontier": issue_frontier}
    return validate(record, "model-request")


class ModelGateway:
    def __init__(self, store, provider, profile: dict):
        self.store, self.provider, self.profile = store, provider, profile

    def generate(self, request: dict, prompt: bytes, *, output_schema_name: str, step_key: str | None, deadline_unix_ms=None) -> dict:
        """Call the provider once; return retained artifacts and the attempt outcome."""
        if sha256_hex(prompt) != request["prompt_ref"]["sha256"]:
            raise GabrielError(Code.INVALID_SCHEMA, "prompt bytes do not match the request's prompt reference")
        config = {"role": request["role"], "step_key": step_key, "max_output_tokens": request["max_output_tokens"]}
        response = self.provider.generate(prompt, config, deadline_unix_ms)
        tracer = getattr(self.store, "tracer", None)
        if tracer is not None:  # provider latency: identifiers, status and sizes only; never the prompt or the response
            tracer.record("provider", int(response.elapsed_ms or 0), status="ok" if response.status == "completed" else "failed",
                          task_id=request.get("task_id"), run_id=request.get("run_id"), step_id=step_key,
                          attributes={"provider_status": response.status, "role": request["role"], "prompt_bytes": len(prompt),
                                      "response_bytes": len(response.raw_bytes or b""), "input_tokens": response.input_tokens,
                                      "output_tokens": response.output_tokens, "http_status": response.http_status})
        raw_ref = self.store.put(response.raw_bytes, "application/json")
        status = response.status
        normalized, loss, problem = None, [], None
        if status == "completed":
            normalized, loss, problem = normalize_json_output(response.text or "", output_schema_name)
            if normalized is None:
                status = "invalid_output"
        usage_known = response.input_tokens is not None and response.output_tokens is not None
        tokens = (response.input_tokens or 0) + (response.output_tokens or 0)
        usage = {"model_tokens": tokens if usage_known else max(tokens, request["max_input_tokens"] + request["max_output_tokens"]),
                 "model_requests": 1, "tool_attempts": 0, "cpu_ms": 0, "elapsed_ms": response.elapsed_ms,
                 "artifact_bytes": len(response.raw_bytes) + len(prompt), "currency_micro_units": 0, "currency": "EUR",
                 "accounting_status": "confirmed" if usage_known else "conservative_pending_reconciliation"}
        envelope = {"request_ref": self.store.put(canonical(request), "application/json"), "raw_response_ref": raw_ref,
                    "status": status, "finish_reason": response.finish_reason, "provider_request_id": response.provider_request_id,
                    "model_revision": response.model_revision, "error": response.error or problem, "loss": loss,
                    "normalization_profile_id": NORMALIZATION_PROFILE, "http_status": response.http_status,
                    "usage_known": usage_known, "elapsed_ms": response.elapsed_ms}
        normalized_ref = self.store.put(dumps_utf8(normalized), "application/json; charset=utf-8") if normalized is not None else None
        return {"status": status, "usage": usage, "normalized": normalized, "normalized_ref": normalized_ref,
                "raw_response_ref": raw_ref, "envelope": envelope, "provider_request_id": response.provider_request_id,
                "model_revision": response.model_revision}


class ModelGenerateTool:
    """``model.generate`` capability: args name the request record, prompt bytes and output schema."""

    def __init__(self, provider_factory):
        self.provider_factory = provider_factory  # callable(profile, store) -> provider
        self._providers = {}  # one provider instance per profile within this process (scripted cursors persist)

    def _provider(self, profile, store):
        key = digest(profile)
        if key not in self._providers:
            self._providers[key] = self.provider_factory(profile, store)
        return self._providers[key]

    def __call__(self, intent, args, ctx):
        request = validate(loads(ctx.store.get(args["request_ref"])), "model-request")
        profile = validate(loads(ctx.store.get(args["provider_profile_ref"])), "provider-profile")
        if profile["provider_id"] != request["provider_id"]:
            raise GabrielError(Code.POLICY_DENIED, "request names another provider than the admitted profile")
        prompt = ctx.store.get(request["prompt_ref"])
        provider = self._provider(profile, ctx.store)
        gateway = ModelGateway(ctx.store, provider, profile)
        outcome = gateway.generate(request, prompt, output_schema_name=args["output_schema"], step_key=args.get("step_key"),
                                   deadline_unix_ms=ctx.deadline_unix_ms)
        descriptor = ctx.registry.tool(intent["capability_id"])[0]
        envelope_bytes = canonical(outcome["envelope"])
        outputs = [("model_output", dumps_utf8(outcome["normalized"]), "application/json; charset=utf-8", descriptor["output_schema_digest"]),
                   ("raw_response", ctx.store.get(outcome["raw_response_ref"]), "application/json", descriptor["output_schema_digest"]),
                   ("request", canonical(request), "application/json", descriptor["output_schema_digest"]),
                   ("envelope", envelope_bytes, "application/json", descriptor["output_schema_digest"])] if outcome["status"] == "completed" else [
                   ("raw_response", ctx.store.get(outcome["raw_response_ref"]), "application/json", descriptor["output_schema_digest"]),
                   ("envelope", envelope_bytes, "application/json", descriptor["output_schema_digest"])]
        return ToolOutcome(status=outcome["status"], exit_code=None, outputs=outputs, usage=outcome["usage"],
                           effect_outcome="not_applicable", provider_request_id=outcome["provider_request_id"])

    def reconcile(self, intent, attempt, ctx):
        # A provider call has no world state to query; its only effect is disclosure and spend,
        # which the conservative charge already retains. The attempt is treated as failed without
        # a usable result, so the node may be retried as a NEW request under its retry class.
        return "confirmed_failure", canonical({"reconciliation": "provider call without retained result; conservative charge retained"})
