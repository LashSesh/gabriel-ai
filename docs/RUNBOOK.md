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
A source may carry `"object_id"` (revisions of one document share it, so the memory's revision
rule applies across files), `"access": "revoked"` with a `"revocation_reason"` (the source is
ingested for audit and revoked before any retrieval, so it is never cited), and the task may
declare `"retrieval_view"`: `provenance` (the default: effective revision, authorized and
available sources), `all_revisions` or `plain`. The last two are declared evaluation ablations
(ADR-16), not modes for production tasks.

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

The corpus has four tiers: `standard` and `hard` (repository repair), `document` (source-grounded
amendments with revisions, revoked sources and conflicts) and `numerical` (declared transforms
with reference values). `gabriel eval corpus-check --tier document|numerical` executes the
positive and negative deliverable controls of those tiers. Protocol 5 (ADR-16) compares the
matched baselines with the production arm and the memory ablations on them:
```bash
gabriel eval corpus-check --tier document && gabriel eval corpus-check --tier numerical
gabriel eval freeze --provider provider.json --out protocol5.json --repetitions 2 --backend linux_namespace \
    --tiers document,numerical --systems provider_only,simple_loop,gabriel_reference_plan,gabriel_plain_sources,gabriel_all_revisions \
    --held-out-families conflict,graph --criterion "<declared before the run>" --note "<provenance>"
```
The view ablations run on document tasks only; the harness skips them elsewhere.

## Routing policies and the G3 route
A task may pin a routing policy (`"policy": {...}` in the task spec, a `gabriel.router-policy/1`
record): at a failed verification the pinned policy chooses between a bounded repair and a
documented stop from the versioned progress channels, and it may retrieve past episodes into
the worker prompt. Without a pin a task gets its pack's default policy: the document pack
ships the readout promoted under protocol 8 (`domains/document/policies/readout-channels-v2.json`,
provenance beside it; ADR-22), every other pack the rule-based policy (always repair within the
admitted limits, no episodes). Every decision is retained with its channels; every terminal run
records an outcome label and an episode in the workspace memory (ADR-15).
```bash
gabriel eval corpus-check --tier hard                                          # trap invariants of the hard tier
gabriel eval freeze ... --tiers hard --tasks mf-money,... --systems gabriel     # training run (rule-based)
scripts/policy_route.py train --run ./run4a --out ./policies                   # readouts, decision loss, episode seed
gabriel eval freeze ... --tiers hard --systems provider_only,simple_loop,gabriel,gabriel_policy,gabriel_episodes \
    --policy ./policies/policy-channels.json --episode-seed ./policies/episode_seed.json \
    --held-out-families stateful --criterion "<declared held-out criterion>"
scripts/policy_route.py promote --train-out ./policies --eval-run ./run4b --held-out stateful --out ./promotion
```
Since ADR-22 a domain pack may declare progress channels of its own (the document pack:
`required_missing`, `required_uncited`, `forbidden_present`, `expected_source_absent`,
`citations_unbound`, `carried_sources`, read from the retained verification evidence and the
retrieval manifest); they are appended to the generic channels, the record's
`channel_schema_id` names the layout, and a readout is bound to the layout it was trained on.
Protocol 8 ran the route on the association tier (`evidence/wp15/`):
```bash
gabriel eval freeze ... --tiers association --tasks da-fee,dc-fee,du-fee,... --repetitions 3 \
    --systems gabriel_associative,gabriel_associative_unlabeled                       # 8a: training decisions (rule-based)
scripts/policy_route.py train --run ./run8a-train --out ./policies8 --episodes 0 \
    --systems gabriel_associative,gabriel_associative_unlabeled                       # readouts bound to the document layout
gabriel eval freeze ... --tiers association --tasks <all da-/dc-/du- tasks> \
    --systems gabriel_associative,gabriel_policy,gabriel_reference_plan --policy ./policies8/policy-channels.json \
    --held-out-families association-needed-held-out,association-needed-cold-held-out,association-unneeded-held-out \
    --criterion "<declared>"                                                          # 8b: evaluation with the frozen candidate
scripts/policy_route.py promote --train-out ./policies8 --eval-run ./run8b-eval --baseline gabriel_associative \
    --treatment gabriel_policy --held-out association-needed-held-out,association-needed-cold-held-out,association-unneeded-held-out \
    --out ./promotion8
scripts/eval_decision_analysis.py ./run8b-eval                                       # every unit's routing decisions beside its provider statuses
```

## Operations (ADR-17)
```bash
gabriel doctor --workspace ./workspace [--deep]       # startup validation: format and codec versions, registered identities and
                                                      # migrations, referenced objects present (bytes with --deep), artifact root,
                                                      # expired leases as reconciliation work
gabriel migrate --workspace ./workspace --reason "<why the code changed>" [--backup DIR]
gabriel metrics --workspace ./workspace [--run RUN_ID] # verified success, independent checks, unknown effects, retries, budget
                                                      # overruns, holds and recovery time, time to first useful artifact,
                                                      # resource use, cold/warm path, telemetry totals
gabriel trace RUN_ID --workspace ./workspace [--summary]   # spans: queue wait, provider, tool execution, verification,
                                                           # journal commit, artifact I/O counters
gabriel gc --workspace ./workspace [--apply] [--grace-seconds N]   # dry run by default
```
A workspace whose journal registered other catalog, schema registry or reducer identities than
the running code refuses to open and names the migration. `migrate` takes a coherent backup
first, replays every retained event under the running code (events of earlier epochs with the
catalog retained for them) and records the migration only when every projection digest and
chain hash is reproduced; otherwise it is refused, the backup stays and the journal is untouched.
Journals created before catalog records existed can be migrated only when the running code
still reproduces them (a changed verifier implementation refuses); they stay readable with the
code identity recorded in their release manifest. Telemetry is written to
`<workspace>/telemetry/spans.jsonl` as best effort: a span that cannot be written is counted as
dropped and never affects the journal, and spans carry identifiers, kinds, durations and
counters only. `gabriel task run` stops cleanly on SIGTERM/SIGINT: it records the scheduling
pause at the next boundary and exits 3; `task resume` and `task run` continue from the journal.
Garbage collection keeps the transitive closure of everything the journal (events, retained
inputs, payloads), the memory chain, the checkpoints, the catalog and migration records name,
including references nested inside JSON artifacts; objects outside it and older than the grace
period are orphans. After `--apply` the replay and the memory chain are re-verified.

## Native PSE graph worker (ADR-18)
```bash
cargo build --locked --release --manifest-path native_pse/Cargo.toml --example engine_observer --example engine_snapshot
                                                      # executables: native_pse/target/release/examples/{engine_observer,engine_snapshot}
export GABRIEL_NATIVE_PSE_DIR=/elsewhere/examples      # optional: executables outside the build tree
.venv/bin/python -m pip install python-flint           # stage two (exact window certificates); numpy and scipy only for the test references
gabriel eval corpus-check --tier graph                 # six graph tasks with executed controls
python scripts/pse_measure.py --output evidence/pse/measurements.json --backends trusted_local,linux_namespace
```
The numerical pack declares three native operations beside the standard-library ones:
`graph.snapshot` on an `observation_batches` dataset, `graph.region_mass` on a `graph_query`
and `graph.window_reachability` on a `graph_window_query` (binary64 values as 16-digit bit
strings; see `src/gabriel_agent/evaluation/fixtures/graph_walk.py` for the dataset forms). A
job installs the worker file and both executables into the worktree, runs them inside the
backend with the executable digests checked before and after every native process, and removes
everything but the output. Window certificates are computed afterwards in a dedicated host
process; a job is `computed` only when every window is decided (`reachable` or `excluded`),
`out_of_scope` when the represented graph is not a uniform clique, `unknown` when the precision
ladder is exhausted or the arithmetic is unavailable; none of these leaves an output. Without
the executables a native proposal is refused at normalization (no substitute worker). Evidence:
`evidence/pse/` (build identity, equivalence with the retained functional journals,
measurements, graph tier check) and `tests/test_native_pse.py`.

Since ADR-19 the engine's transcendental arithmetic is platform-independent by construction
(`pse-fmath`, pure-Rust libm; the historical Windows golden fixture is explained by last-bit
differences between C libraries and is compared only on request), and two further operations
expose the engine's continuous state as a specified readout over a declared observation stream
(`observation_stream`: per observation an entity, a phase in [0, 2pi) and an amplitude in
[0, 1]; a profile with carriers, coherence parameters, normalization and thresholds):
`graph.state_readout` (embedding, data helix, active carrier, gate metrics d, q, r, g, j, p, n,
k and gate verdict per step, with an identity over the complete readout) and
`graph.detections` on a `detection_query` (the gate crossings admitted by a declared
`{min_tick, cooldown}` schedule, each with an identity over its complete content; an empty
list is a computed result). `src/gabriel_agent/evaluation/fixtures/graph_readout.py` states
the specification and implements it independently in the standard library.
```bash
cargo build --locked --release --manifest-path native_pse/Cargo.toml --example engine_observer --example engine_snapshot --example engine_readout
.venv/bin/python scripts/pse_build_identity.py --output evidence/pse/build_identity.json   # digests of the executables, lockfile and bound sources
(cd native_pse && cargo test --workspace --release --locked)                               # includes the platform-independent golden fixture
(cd native_pse && cargo run --release --example golden_fixture > /tmp/fixture.json)        # regenerate after an intentional model change only
(cd native_pse && cargo test --release -- --ignored full_state_matches_original_golden_fixture)   # the historical Windows fixture, on request
```

## Associative memory layer (ADR-20)
A succeeded document run records what it established as supported claims (the target's
content, supported by the observations its citations resolved to). The document pack's view
`associative` (task field `retrieval_view`) is the provenance view re-ranked by the native
engine's walk over the co-citation graph of those claims: authorization, revision rule,
revocation and frontier apply first, the lexically matching sources seed the walk, every
candidate's score is the larger of its lexical score and its walk mass, and the retrieval
manifest retains the association record (profile, status, executable digest, batches digest,
entities, seeds, snapshot identity, masses). Without history or executables the record says so
and the retrieval stays lexical. Since ADR-21 the record also carries `links` (for every
carried source: the seeds it was cited together with, the claims and the tasks of the verified
runs that cited them together) and every item keeps its lexical score; the associative view
lists carried sources under their own heading with that reason and tells the worker that an
associated source is available, not required. The view `associative_unlabeled` is the declared
ablation with the ADR-20 presentation. Since protocol 7 met its declared rules the associative
view is the document pack's default (`retrieval_view` omitted); `provenance`, `plain`,
`all_revisions` and `associative_unlabeled` remain declarable per task. The corpus tier
`association` and protocols 6 and 7 test the mechanism and its presentation (`evidence/wp15/`):
```bash
gabriel eval corpus-check --tier association                       # fifteen tasks, history tasks included in the digest
gabriel eval freeze --provider provider.json --out protocol6.json --repetitions 2 --backend linux_namespace \
  --systems provider_only,simple_loop,gabriel_reference_plan,gabriel_associative --tiers association \
  --held-out-families association-needed-held-out
gabriel eval run --protocol protocol6.json --out ./run6 --provider provider.json --workers 3
gabriel eval report --run ./run6
scripts/eval_final_diffs.py ./run6                                 # final worktree diffs as evidence
scripts/eval_retrieval_analysis.py ./run6                          # what each Gabriel retrieval carried (ranks, seeds, prompt)
gabriel eval freeze --provider provider.json --out protocol7.json --repetitions 2 --backend linux_namespace \
  --systems gabriel_reference_plan,gabriel_associative,gabriel_associative_unlabeled --tiers association \
  --held-out-families association-needed-held-out                  # ADR-21: the labeling against its unlabeled control
```
The corpus check executes the tier's precondition under the memory service's own scorer (the
visible source outranks every distractor, every distractor outranks the hidden source); run 6
of the protocol was lost to distractors that tied with the visible source before that invariant
existed, and is retained with the amendment (`evidence/wp15/protocol6_declaration.md`).

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
