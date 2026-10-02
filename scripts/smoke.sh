#!/usr/bin/env bash
# Independent G1 smoke workflow: clean install, doctor, create and run the seeded task with the
# scripted provider, export, audit, backup and restore. Exit status is non-zero on any failure.
# Usage: scripts/smoke.sh [workdir]   (default: a fresh temporary directory)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="${1:-$(mktemp -d -t gabriel-smoke-XXXXXX)}"
BACKEND="${GABRIEL_SMOKE_BACKEND:-linux_namespace}"
PY="${PYTHON:-python3}"
echo "smoke workdir: $WORK (backend $BACKEND)"
"$PY" -m venv "$WORK/venv"
"$WORK/venv/bin/python" -m pip install --quiet "$ROOT"
GABRIEL="$WORK/venv/bin/gabriel"
EXTRA=()
if [ "$BACKEND" = "trusted_local" ]; then EXTRA=(--allow-trusted-local); fi
"$GABRIEL" init --workspace "$WORK/ws" --backend "$BACKEND" "${EXTRA[@]}"
"$GABRIEL" doctor --workspace "$WORK/ws" --selftest || { echo "doctor reported problems"; [ "$BACKEND" = "trusted_local" ] || exit 3; }
"$WORK/venv/bin/python" - "$WORK" <<'EOF'
import json, sys
from pathlib import Path
from gabriel_agent.evaluation.fixtures import parser_bug as fixture
work = Path(sys.argv[1])
repo = work / "repo"
base = fixture.build_repo(repo)
oracle = fixture.write_oracle(work / "oracle_kvparse.py")
spec = fixture.task_spec(repo, base, oracle, {"kind": "scripted", "script": fixture.script(), "max_input_tokens": 60000})
(work / "task.json").write_text(json.dumps(spec))
EOF
TASK_ID=$("$GABRIEL" task create --workspace "$WORK/ws" --spec "$WORK/task.json" | "$WORK/venv/bin/python" -c 'import json,sys; print(json.load(sys.stdin)["task_id"])')
"$GABRIEL" task run "$TASK_ID" --workspace "$WORK/ws" > "$WORK/run.json"
"$WORK/venv/bin/python" -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d["state"]=="succeeded", d["state"]; print("run state", d["state"])' "$WORK/run.json"
"$GABRIEL" task export "$TASK_ID" --workspace "$WORK/ws" --out "$WORK/delivery" > /dev/null
"$GABRIEL" audit --workspace "$WORK/ws" --anchor "$WORK/delivery/anchor.json" > /dev/null
"$GABRIEL" backup --workspace "$WORK/ws" --out "$WORK/backup" > /dev/null
"$GABRIEL" restore --from "$WORK/backup" --workspace "$WORK/restored" > "$WORK/restore.json"
"$WORK/venv/bin/python" -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d["status"]=="passed"; print("restore", d["status"], "events", d["replay"]["events"])' "$WORK/restore.json"
"$GABRIEL" release-manifest --workspace "$WORK/ws" --out "$WORK/release-manifest.json" --root "$ROOT" > /dev/null
echo "smoke passed: $WORK"
