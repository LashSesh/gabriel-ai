# ADR-17: Operations, observability and release discipline

**Status:** accepted. **Affects:** `state/owner.py`, `agent/workspace.py`, `agent/runner.py`, `agent/gc.py`,
`agent/backup.py`, `workers/supervisor.py`, `models/gateway.py`, `artifacts/store.py`, `telemetry.py`, `interfaces/cli.py`.

## Context
The blueprint's operations section asks for startup validation (schema versions, storage
integrity, registry compatibility, artifact roots, outstanding leases as reconciliation work),
a clean shutdown contract, telemetry with task/run/step/attempt identifiers that separates queue
time, provider latency, tool execution, verification, journal commit and artifact I/O with audit
events authoritative even if the exporter fails, operational metrics beyond cache hit ratios,
explicit versioned database migrations with backup and restore checks that never rewrite an old
journal to match a new reducer, and artifact garbage collection that respects retained event
references, checkpoints, exports and active attempts. Until this ADR a tool-module change made
every existing workspace unopenable ("explicit migration required") with no migration command,
and nothing of the rest existed.

## Decision
- **Catalog epochs and explicit migration.** The owner retains the content of the catalog it
  registers (`catalog_records`, from creation and at every migration) and records migrations
  (`migrations` table, `gabriel.migration/1`: from and to identities, the sequence, the backup
  manifest digest, the number of replayed events, the reason). Recorded replay checks every
  event's retained catalog digest against the epoch in force at its sequence and re-reduces the
  event with the catalog retained for that epoch. `Workspace.migrate` (CLI `migrate`) opens a
  mismatched journal in migration mode, takes a coherent backup, runs the equivalence replay
  under the running code and records the migration only when every projection digest and chain
  hash is reproduced; a failure refuses the migration, keeps the backup and leaves the journal
  untouched. A journal created before catalog records existed has no retained catalog for its
  first epoch, so it migrates only when the running code reproduces it as is (a changed verifier
  implementation refuses, because assessments bind the verifier fingerprint); it stays readable
  with the code identity its release manifest records. The two refused migrations of retained
  evidence workspaces (`evidence/ops/migration_at23.json`, `migration_run5_dr-notice.json`) show
  that rule applied.
- **Startup validation.** `Workspace.startup_validation` (in `doctor`, bytes with `--deep`)
  reports format and codec versions, registered identities and migrations, referenced objects
  missing or corrupt, the artifact root, the memory anchor and expired attempt leases as
  reconciliation work that is never repeated automatically.
- **Clean shutdown.** `TaskRunner.request_stop` (SIGTERM/SIGINT in the main thread) admits no new
  attempt, records the scheduling pause at the next loop boundary and leaves the run resumable
  from the journal (`task run` exits 3). An attempt in flight completes first because dispatch is
  synchronous; a forced stop is the recovery contract of AT05 and AT24.
- **Telemetry.** `telemetry.Tracer` writes JSONL spans (`gabriel.span/1`) with a per-thread
  stack for parent identities: `run`, `queue_wait` (dispatch entry to external I/O),
  `tool_execution`, `provider`, `verification`, `journal_commit`, with artifact I/O counters on
  the innermost span. The owner and the store reach the tracer through attributes; a failed
  write is counted as dropped and never raised. Spans hold identifiers, kinds, durations,
  statuses and counters: never prompt bytes, artifact content or credentials.
- **Metrics.** `Workspace.metrics` derives per run from the journal: declared success,
  independent checks passed and failed, unknown effects, retries, budget overruns, holds and
  recovery time, time to first useful artifact (first accepted proposal), total time, resource
  use, cold or warm path (a reused cached job result), plus telemetry totals.
- **Garbage collection.** `agent/gc.py` computes the transitive closure of every artifact named
  by the journal (payload references, retained inputs), the memory chain (entries, observations,
  cache manifests, summaries), checkpoints, catalog and migration records, following references
  nested in JSON artifacts; objects outside the closure and older than the grace period are
  orphans. Dry run by default; `--apply` removes them and re-verifies replay and memory chain.
  Building the closure exposed that the proposal envelope (`gabriel.proposal-envelope/1`) was
  retained but referenced by nothing; it is now an input reference of the propose node's
  assessment.

## Consequences
Code changes no longer strand workspaces created from now on: the catalog of every epoch is
retained and a migration is an explicit, backed-up, verified and recorded step. Earlier
workspaces keep their rule. Operators get the quantities the blueprint names from the journal
itself, and traces that separate where time goes without touching the audit path.
