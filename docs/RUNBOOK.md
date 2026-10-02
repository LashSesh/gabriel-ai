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

## Document and numerical tasks (WP10)
A task spec names its domain; the same `task create` / `task run` lifecycle applies. A document
task declares its sources (never editable) and targets; the model must cite every statement
as `[[cite:<observation_id> "exact quote"]]`, and the independent oracle lists the required
claims with the source each must be cited from:
```json
{"domain": "document", "goal": "Amend doc/summary.md ...", "repository": "/path/to/repo", "base_commit": "<40-hex>",
 "allowed_paths": ["doc/"], "targets": ["doc/summary.md"],
 "sources": [{"path": "sources/policy.md", "source_id": "policy", "revision": 1, "event_kind": "timeless_document"}],
 "checks": [{"check_id": "citations", "kind": "document/citations_bound", "independent": true},
            {"check_id": "claims", "kind": "document/required_claims", "independent": true,
             "oracle_files": [{"path": "oracle/required_claims.json", "source": "/outside/required_claims.json"}]}]}
```
A numerical task binds one declared operation of `gabriel_agent.adapters.analytical`
(`units.convert`, `series.resample_mean`, `graph.small_signature`) to an observed dataset; the
job runs in a fresh contained worker and the oracle is the expected output with units and
tolerance:
```json
{"domain": "numerical", "goal": "Convert data/series.json to kelvin ...", "repository": "/path/to/repo", "base_commit": "<40-hex>",
 "allowed_paths": ["out/"],
 "checks": [{"check_id": "reference", "kind": "numerical/reference_contract", "independent": true,
             "oracle_files": [{"path": "oracle/expected.json", "source": "/outside/expected.json"}]}]}
```
Verdicts `out_of_scope`, `invalid_input` and `unknown` are retained domain verdicts; only a
`computed` result that meets the reference contract can pass. Fixtures for both domains:
`src/gabriel_agent/evaluation/fixtures/document_amendment.py`, `numerical_series.py`;
`scripts/at23_three_domains.py` runs all three domains through one workspace.

## Memory (WP09)
Every workspace keeps `memory.sqlite`, an append-only evidence index with its own hash chain
(`docs/adr/ADR-14-memory-chain.md`). The document pack ingests declared sources as versioned
observations and retrieves them as of the run's frontier; `backup`/`restore` include the index
and verify every referenced byte. The Python API (`workspace.memory`) offers `ingest`,
`effective`, `retrieve`, `assert_claim`/`assess`, `revoke`/`retract`, `record_outcome`,
`effective_support`, `promote`, `compact` and `verify`.

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

## Backup, restore and release metadata
```bash
gabriel backup --workspace ./workspace --out ./backup            # SQLite online backup + referenced objects + anchor
gabriel restore --from ./backup --workspace ./restored             # verifies objects, anchor and replay; no secret restored
gabriel release-manifest --workspace ./workspace --out release.json --root . --selftest   # doctor report includes the jail self-test
scripts/smoke.sh                                                  # clean venv install, doctor --selftest, task, export, audit, backup, restore
```

## Evaluation (WP11)
```bash
gabriel eval corpus-check                                          # executes the corpus invariants
gabriel eval freeze --provider provider.json --out protocol.json --repetitions 2 --backend linux_namespace \
    --systems provider_only,simple_loop,gabriel,gabriel_no_repair,gabriel_reference_plan \
    --held-out-families <family never run before> --note "<provenance>"
gabriel eval run --protocol protocol.json --out ./eval-run --provider provider.json --workers 3
gabriel eval report --run ./eval-run
scripts/eval_final_diffs.py ./eval-run                             # retain the verified worktree content per unit
```
`provider.json` is a provider spec such as `{"kind": "openai_compat", "model": "gpt-4.1-mini",
"credential_ref": "env:OPENAI_API_KEY", "temperature_milli": 0}`. The run refuses a protocol
whose digest or corpus changed after freezing. See `docs/EVALUATION_PROTOCOL.md`.

## Evidence manifests
```bash
GABRIEL_CONTAINMENT_TESTS=1 python -m pytest tests -vv -rs | tee evidence/test_results.txt
scripts/evidence_manifest.py                                       # evidence/test_run.json, evidence/work_packages.json
```

## Privileged self-tests
```bash
GABRIEL_CONTAINMENT_TESTS=1 python -m pytest -q -m containment
GABRIEL_LIVE_PROVIDER=1 GABRIEL_LIVE_KIND=openai_compat GABRIEL_LIVE_MODEL=gpt-4.1-mini \
  GABRIEL_LIVE_CREDENTIAL=env:OPENAI_API_KEY GABRIEL_LIVE_EVIDENCE_DIR=./evidence/live \
  python -m pytest -q -m live_provider
```
Both are opt-in: the first creates namespaces, mounts a tmpfs root and pivots into it; the
second spends provider credit. Both were executed on the development host; results are in
`evidence/test_results.txt`, `evidence/doctor_linux_namespace_selftest.json` and
`evidence/live/summary.json`.

## Catalog identity
A workspace journal pins the capability catalog (tool descriptors with implementation
fingerprints). After changing any tool implementation, `Workspace.open` refuses the old journal
with `UNSUPPORTED: capability catalog differs`; create a new workspace. An explicit, replayed
migration is future work.
