# Gabriel agent runbook

## Install
```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"            # core + tests; numerical extras: pip install -e ".[numerical]"
```
The core needs Python 3.11+, `jsonschema==4.25.1`, git and (for the supported containment
backend) util-linux `unshare` and `setpriv` on Linux. Nothing in the core imports NumPy, the
PSE build products or the legacy `gabriel_runtime`.

## Workspace
```bash
gabriel init --workspace ./workspace                      # linux_namespace backend (default)
gabriel init --workspace ./ws-local --backend trusted_local --allow-trusted-local   # trusted mode only
gabriel doctor --workspace ./workspace                     # non-mutating probes
gabriel doctor --workspace ./workspace --selftest          # runs a jailed process (mount/pivot_root/caps/no-net)
```
`doctor` exits 3 while the jail self-test has not been executed on the host: untrusted
repository code must not be run before that self-test passes. `trusted_local` is an explicitly
separate mode without a filesystem, network or credential boundary.

## Task specification (`task.json`)
```json
{
  "goal": "Fix the kvparse parser bug: parse_pairs must return {} for empty input ...",
  "repository": "/path/to/repo",
  "base_commit": "<40-hex commit>",
  "allowed_paths": ["src/"],
  "checks": [
    {"check_id": "unit", "kind": "software/test_passed", "argv": ["python3", "-m", "unittest", "discover", "-s", "tests"],
     "timeout_ms": 60000, "role": "baseline_and_acceptance"},
    {"check_id": "oracle", "kind": "software/test_passed", "argv": ["python3", "-m", "unittest", "oracle_kvparse"],
     "independent": true, "role": "acceptance_only",
     "oracle_files": [{"path": "oracle_kvparse.py", "source": "/path/outside/repo/oracle_kvparse.py"}]}
  ],
  "provider": {"kind": "openai_compat", "model": "gpt-4.1-mini", "credential_ref": "env:OPENAI_API_KEY"},
  "budget": {"model_tokens_total": 200000, "model_requests": 12},
  "accept_without_independent_oracle": false
}
```
Compilation adds the structural mandatory checks `scope`, `base-commit`, `checks-intact`,
`no-secrets`, the non-mandatory `output-valid`, and a `baseline:<id>` run for every
`baseline_and_acceptance` test check. A goal without an independent oracle is refused unless
`accept_without_independent_oracle` is true; the behavioral claim is then listed under
"claims requiring user review" in the export. Unknown check kinds reject.

Providers: `scripted` (`"script": {...}` or a file path), `openai_compat` (`endpoint` default
`$OPENAI_BASE_URL` or `https://api.openai.com/v1`), `anthropic` (`endpoint` default
`$ANTHROPIC_BASE_URL` or `https://api.anthropic.com`). Credentials are always `env:NAME`
references resolved by the supervisor right before a request.

## Lifecycle
```bash
gabriel task create --workspace ./workspace --spec task.json      # compiles, grants, admits, pins a worktree
gabriel task run TASK_ID --workspace ./workspace                   # re-entrant; restart resumes from the journal
gabriel task status TASK_ID --workspace ./workspace
gabriel task pause TASK_ID --workspace ./workspace                 # scheduling flag, not a state
gabriel task resume TASK_ID --workspace ./workspace
gabriel task cancel TASK_ID --workspace ./workspace                # terminal; unresolved effects stay visible
gabriel task inspect TASK_ID --workspace ./workspace --evidence
gabriel task export TASK_ID --workspace ./workspace --out ./delivery
gabriel audit --workspace ./workspace --anchor ./delivery/anchor.json
gabriel replay RUN_ID --workspace ./workspace --recorded
```
`task run` returns 0 only for `succeeded`. Blocked and waiting runs report their hold
(`reason_code`, `missing_prerequisite`, `wakeup_condition`) in `status`.

## Privileged self-tests
```bash
GABRIEL_CONTAINMENT_TESTS=1 python -m pytest -q -m containment
GABRIEL_LIVE_PROVIDER=1 GABRIEL_LIVE_KIND=openai_compat GABRIEL_LIVE_MODEL=gpt-4.1-mini \
  GABRIEL_LIVE_CREDENTIAL=env:OPENAI_API_KEY GABRIEL_LIVE_EVIDENCE_DIR=./evidence/live \
  python -m pytest -q -m live_provider
```
Both are opt-in: the first creates namespaces, mounts a tmpfs root and pivots into it; the
second spends provider credit. Their results are the missing G1 evidence (see
`docs/IMPLEMENTATION_STATUS.md`).
