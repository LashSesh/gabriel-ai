"""AT09 model response boundaries with the scripted provider and local fake HTTP endpoints."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from gabriel_agent.artifacts import ObjectStore
from gabriel_agent.contracts import GabrielError, canonical, loads
from gabriel_agent.contracts.schemas import schema_digest
from gabriel_agent.models import (ScriptedProvider, ModelGateway, build_model_request, OpenAICompatibleProvider,
                                  AnthropicProvider, resolve_credential)
from gabriel_agent.models.gateway import normalize_json_output

PROFILE = {"schema": "gabriel.provider-profile/1", "provider_id": "scripted-fixture", "kind": "scripted", "model_alias": "fixture-v1",
           "endpoint": None, "credential_ref": None, "max_input_tokens": 4000, "max_output_tokens": 1000, "temperature_milli": 0,
           "timeout_ms": 1000, "script_ref": None, "data_classes": ["synthetic"], "max_retries": 1}

PLAN = {"nodes": [{"node_id": "n1", "capability_id": "software.observe", "depends_on": [], "check_ids": ["output-valid"],
                   "purpose": "observe", "args": {}}], "rationale": "fixture"}


def request_for(store, prompt):
    return build_model_request(request_id="req-1", task_id="task-01", run_id="run-01", provider_profile=PROFILE, role="planner",
                               prompt_ref=store.put(prompt, "text/plain; charset=utf-8"), evidence_refs=[], observation_ids=[],
                               issue_frontier=3, output_schema_name="plan-proposal", tool_schema_digest="a" * 64,
                               sampling_config_ref=store.put(canonical({"temperature_milli": 0}), "application/json"),
                               max_input_tokens=4000, max_output_tokens=1000)


def test_scripted_statuses_map_to_distinct_outcomes(tmp_path):
    store = ObjectStore.create(tmp_path / "s")
    script = {"by_role": {"planner": [{"kind": "text", "value": PLAN, "usage": {"input_tokens": 10, "output_tokens": 20}},
                                       {"kind": "truncated", "text": '{"nodes": ['}, {"kind": "invalid_json"},
                                       {"kind": "refusal"}, {"kind": "rate_limit"}, {"kind": "timeout"}, {"kind": "transport_error"},
                                       {"kind": "text", "value": {"nodes": []}}]}}
    provider = ScriptedProvider(script)
    gateway = ModelGateway(store, provider, PROFILE)
    prompt = "plan please ü".encode("utf8")
    request = request_for(store, prompt)
    expected = ["completed", "truncated", "invalid_output", "provider_refusal", "rate_limited", "timed_out", "failed", "invalid_output"]
    seen = []
    for _ in expected:
        outcome = gateway.generate(request, prompt, output_schema_name="plan-proposal", step_key=None)
        seen.append(outcome["status"])
        assert store.get(outcome["raw_response_ref"])  # raw bytes retained for every status
        if outcome["status"] in ("rate_limited", "timed_out", "failed"):
            assert outcome["usage"]["accounting_status"] == "conservative_pending_reconciliation"
            assert outcome["usage"]["model_tokens"] == 5000  # conservative ceiling charge
        else:
            assert outcome["usage"]["accounting_status"] == "confirmed"
    assert seen == expected
    first = provider.calls[0]
    assert first["prompt_sha256"] == request["prompt_ref"]["sha256"] and first["role"] == "planner"
    assert request["output_schema_digest"] == schema_digest("plan-proposal")
    with pytest.raises(GabrielError):
        gateway.generate(request, b"other prompt bytes", output_schema_name="plan-proposal", step_key=None)


def test_normalization_rejects_partial_and_wrapped_output():
    value, loss, problem = normalize_json_output("```json\n" + json.dumps(PLAN) + "\n```", "plan-proposal")
    assert value == PLAN and loss == ["code fence removed"] and problem is None
    assert normalize_json_output('{"nodes": [', "plan-proposal")[2].startswith("invalid JSON")
    assert normalize_json_output('{"nodes": [], "rationale": "x"}', "plan-proposal")[2].startswith("schema violation")
    assert normalize_json_output('{"nodes": [], "nodes": [], "rationale": "x"}', "plan-proposal")[2].startswith("invalid JSON")
    assert normalize_json_output(json.dumps(dict(PLAN, extra=1)), "plan-proposal")[2].startswith("schema violation")


class _Handler(BaseHTTPRequestHandler):
    responses = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))
        _Handler.received.append({"path": self.path, "auth": self.headers.get("Authorization"), "key": self.headers.get("x-api-key"), "body": body})
        status, payload = _Handler.responses.pop(0)
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args):
        pass


@pytest.fixture
def fake_server():
    _Handler.received = []
    try:
        server = HTTPServer(("127.0.0.1", 0), _Handler)
    except OSError as exc:
        pytest.skip("loopback sockets unavailable: " + str(exc))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield "http://127.0.0.1:%d" % server.server_port
    server.shutdown()


def test_openai_compatible_status_mapping(fake_server, monkeypatch):
    monkeypatch.setenv("FAKE_KEY", "secret-token")
    profile = dict(PROFILE, provider_id="openai-fixture", kind="openai_compat", model_alias="gpt-fixture", endpoint=fake_server + "/v1",
                   credential_ref="env:FAKE_KEY")
    provider = OpenAICompatibleProvider(profile, resolve_credential("env:FAKE_KEY"))
    _Handler.responses = [
        (200, {"id": "chatcmpl-1", "model": "gpt-fixture-2026-01-01", "choices": [{"message": {"content": "{\"a\":1}"}, "finish_reason": "stop"}],
               "usage": {"prompt_tokens": 7, "completion_tokens": 3}}),
        (200, {"id": "chatcmpl-2", "model": "m", "choices": [{"message": {"content": "{\"a\":"}, "finish_reason": "length"}], "usage": {}}),
        (200, {"id": "chatcmpl-3", "model": "m", "choices": [{"message": {"content": None, "refusal": "no"}, "finish_reason": "content_filter"}]}),
        (429, {"error": {"type": "rate_limit_error"}}),
        (500, {"error": "boom"}),
        (200, {"unexpected": True}),
    ]
    statuses = [provider.generate(b"hi", {}).status for _ in range(6)]
    assert statuses == ["completed", "truncated", "provider_refusal", "rate_limited", "failed", "invalid_output"]
    first = _Handler.received[0]
    assert first["auth"] == "Bearer secret-token" and first["path"] == "/v1/chat/completions"
    assert first["body"]["messages"][0]["content"] == "hi" and first["body"]["model"] == "gpt-fixture"
    r = provider.generate(b"x", {}) if False else None
    _Handler.responses = [(200, {"id": "r", "model": "exact-rev", "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}})]
    response = provider.generate(b"x", {})
    assert response.model_revision == "exact-rev" and response.provider_request_id == "r" and response.input_tokens == 1
    truncated = OpenAICompatibleProvider(profile, "k", endpoint="http://127.0.0.1:1")  # closed port: transport failure, usage unknown
    response = truncated.generate(b"x", {})
    assert response.status in ("failed", "timed_out") and response.input_tokens is None


def test_anthropic_status_mapping(fake_server):
    profile = dict(PROFILE, provider_id="anthropic-fixture", kind="anthropic", model_alias="claude-fixture", endpoint=fake_server, credential_ref=None)
    provider = AnthropicProvider(profile, "key-1")
    _Handler.responses = [
        (200, {"id": "msg_1", "model": "claude-fixture-20260101", "content": [{"type": "text", "text": "{\"a\":1}"}], "stop_reason": "end_turn",
               "usage": {"input_tokens": 5, "output_tokens": 2}}),
        (200, {"id": "msg_2", "model": "m", "content": [{"type": "text", "text": "{\"a\":"}], "stop_reason": "max_tokens", "usage": {}}),
        (200, {"id": "msg_3", "model": "m", "content": [], "stop_reason": "refusal", "usage": {}}),
        (429, {"type": "error", "error": {"type": "rate_limit_error"}}),
    ]
    statuses = [provider.generate(b"hi", {}).status for _ in range(4)]
    assert statuses == ["completed", "truncated", "provider_refusal", "rate_limited"]
    assert _Handler.received[0]["key"] == "key-1" and _Handler.received[0]["path"] == "/v1/messages"


def test_credential_resolution_never_reads_other_sources(monkeypatch):
    monkeypatch.delenv("GABRIEL_MISSING", raising=False)
    with pytest.raises(GabrielError):
        resolve_credential("env:GABRIEL_MISSING")
    with pytest.raises(GabrielError):
        resolve_credential("file:/etc/passwd")
    assert resolve_credential(None) is None
