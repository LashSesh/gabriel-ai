"""AT11 real-provider run (opt in). Requires GABRIEL_LIVE_PROVIDER=1 and a configured credential.

Example:
  GABRIEL_LIVE_PROVIDER=1 GABRIEL_LIVE_KIND=openai_compat GABRIEL_LIVE_MODEL=gpt-4.1-mini \
  GABRIEL_LIVE_CREDENTIAL=env:OPENAI_API_KEY python -m pytest -q -m live_provider
The containment backend is taken from GABRIEL_LIVE_BACKEND (default linux_namespace; trusted_local
only runs the fixture repository, whose content is this project's own).
"""
import json
import os
from pathlib import Path

import pytest

from gabriel_agent.agent import Workspace, TaskRunner, export_task
from gabriel_agent.contracts import loads
from gabriel_agent.evaluation.fixtures import parser_bug as fixture


@pytest.mark.live_provider
def test_real_provider_repairs_seeded_bug(tmp_path):
    kind = os.environ.get("GABRIEL_LIVE_KIND", "openai_compat")
    backend = os.environ.get("GABRIEL_LIVE_BACKEND", "linux_namespace")
    ws = Workspace.create(tmp_path / "ws", backend=backend, allow_trusted_local=(backend == "trusted_local"))
    repo = tmp_path / "repo"
    base = fixture.build_repo(repo)
    oracle = fixture.write_oracle(tmp_path / "oracle_kvparse.py")
    provider = {"kind": kind, "model": os.environ.get("GABRIEL_LIVE_MODEL", "gpt-4.1-mini"),
                "credential_ref": os.environ.get("GABRIEL_LIVE_CREDENTIAL", "env:OPENAI_API_KEY"),
                "endpoint": os.environ.get("GABRIEL_LIVE_ENDPOINT"), "max_input_tokens": 60000, "max_output_tokens": 4000,
                "provider_id": "live-" + kind}
    spec = fixture.task_spec(repo, base, oracle, provider)
    created = ws.create_task(spec)
    summary = TaskRunner(ws, created["task_id"]).run()
    evidence_dir = Path(os.environ.get("GABRIEL_LIVE_EVIDENCE_DIR", tmp_path / "evidence"))
    evidence_dir.mkdir(parents=True, exist_ok=True)
    projection = ws.owner.projection(summary["run_id"])
    requests = []
    for attempt in projection["attempts"].values():
        if attempt["capability_id"] == "model.generate" and attempt["result_ref"]:
            result = loads(ws.store.get(attempt["result_ref"]))
            for output in result["outputs"]:
                if output["output_slot"] == "envelope":
                    requests.append(loads(ws.store.get(output["artifact_ref"])))
    (evidence_dir / "live_provider_run.json").write_text(json.dumps({"summary": summary, "model_envelopes": requests, "base_commit": base,
                                                                    "replay": ws.owner.replay()}, indent=2, default=str))
    export_task(ws, created["task_id"], evidence_dir / "delivery")
    assert summary["port_calls"] >= 2 and requests and all(r["model_revision"] for r in requests)
    assert summary["state"] in ("succeeded", "failed", "blocked")
    if summary["state"] != "succeeded":
        pytest.fail("real-provider run did not succeed; evidence retained at " + str(evidence_dir))
