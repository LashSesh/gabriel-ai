# Gabriel AI agent application (`gabriel_agent`)

The agent application described in `Gabriel_AI_Blueprint.zip` now lives beside the recovered
research runtime: `src/gabriel_agent/` (install with `pip install -e ".[dev]"`, entry point
`gabriel`). It implements work packages WP01–WP12 of the blueprint: exact contracts, a
content-addressed object store, a single SQLite journal owner with a pure reducer and recorded
replay, scoped grants and vector reservations, a Linux-namespace tool sandbox with a
dispatch-marker supervisor, a model gateway (scripted, OpenAI-compatible, Anthropic), the
domain-independent goal/evidence kernel, and a software domain pack that repairs a repository
in an isolated worktree with independent acceptance checks.

- Status, executed evidence and the release assessment (G1 established on the development host
  with four real-provider runs and the Linux-namespace containment self-test): `docs/IMPLEMENTATION_STATUS.md`
- How to install, configure a task and run it: `docs/RUNBOOK.md`
- Frozen matched evaluation (WP11): three executed protocols with gpt-4.1-mini, failure analyses
  and the advantage-gate assessment (not passed): `docs/EVALUATION_PROTOCOL.md`, `evidence/wp11/`
- G1 release report, backup/restore and license (Apache-2.0, `LICENSE`) (WP12): `docs/RELEASE_G1.md`
- G2 domain portability (WP09 memory, WP10 document and numerical packs, AT23 evidence):
  `docs/RELEASE_G2.md`, `evidence/wp10/`
- G3 route (hard corpus with executed traps, progress channels, reference recurrent map, readout
  router, episodic retrieval, held-out promotion): `docs/RELEASE_G3.md`, `evidence/wp13/`
- Protocol 5 (advantage gate on the document and numerical families with declared ablations of
  provenance-aware retrieval and the revision rule; two pilots, held-out families):
  `docs/EVALUATION_PROTOCOL.md`, `docs/RELEASE_G2.md`, `evidence/wp14/`
- Operations (explicit versioned migrations with catalog epochs, startup validation, clean
  shutdown, telemetry spans, operational metrics, artifact garbage collection):
  `docs/RUNBOOK.md` (Operations), `docs/adr/ADR-17-operations.md`, `evidence/ops/`
- Native PSE graph worker (the reviewed Rust engine as a contained analytical worker of the
  numerical pack: conditioned snapshots, regional masses and exact window certificates with
  complete bindings, references independent of the engine, a graph corpus tier and separate
  measurements of cold start, identity validation, query and task latency):
  `docs/adr/ADR-18-native-pse-graph-worker.md`, `docs/RUNBOOK.md` (Native PSE graph worker),
  `evidence/pse/`
- Native PSE determinism and specified readout (platform-independent arithmetic that explains
  the historical golden-fixture mismatch; the engine's continuous state as a specified,
  independently referenced readout over declared observation streams with schedule-admitted
  detections; the inherited crystal path stays quarantined with reasons):
  `docs/adr/ADR-19-native-pse-determinism-and-readout.md`, `evidence/pse/determinism/`
- Associative memory layer (verified runs establish supported claims; the engine's walk over the
  co-citation graph re-ranks a budgeted retrieval as a declared view that never adds a source;
  corpus tier `association` with history tasks and protocol 6 as a scoped mechanism test: under
  protocol 6b the walk carried the required source in every needed run including the held-out
  family, 10/10 against 0/10 for the provenance view, and cost two of six unneeded runs, above
  the declared harm bound; run 6 is retained with its corpus defect and the amendment):
  `docs/adr/ADR-20-associative-memory-layer.md`, `docs/EVALUATION_PROTOCOL.md`, `evidence/wp15/`
- Association provenance in the prompt (the manifest keeps why every carried source is there;
  the prompt lists carried sources apart with the seed and the verified run that cited them
  together; under protocol 7 that kept every needed outcome, brought the unneeded family to the
  provenance view's level with no forbidden first attempt against 6/6 for the unlabeled control,
  and the associative view became the document pack's default as declared):
  `docs/adr/ADR-21-association-provenance-in-the-prompt.md`, `evidence/wp15/run7/`
- G3 on the association distribution (domain-declared progress channels: the document pack
  states committed facts of the latest verification, among them whether an unmet claim's source
  was in the prompt; a readout trained on 48 retained decisions met the declared held-out
  criterion under protocol 8, equal verified success at 2836 against 5425 tokens, was promoted
  by the memory's rule and ships pinned as the document pack's default routing policy; the
  claim is bounded to one fact, one provider and one constructed distribution):
  `docs/adr/ADR-22-domain-declared-channels-g3.md`, `docs/RELEASE_G3.md`, `evidence/wp15/run8b-eval/`
- Second provider (protocol 9 repeated the association tier with gpt-5-mini under a declaration
  frozen before the run: the associative view 10/10 against 0/10 on the needed families, the
  labeled presentation with no forbidden first attempt against 4/10 unlabeled, the promoted
  readout with fixed weights equal to the rule at less than half the tokens with every hopeless
  repair stopped; scope: two providers of one vendor): `docs/EVALUATION_PROTOCOL.md`,
  `evidence/wp15/run9/`
- Erosion of the association history (the walk runs over the retrieval's own candidates and
  nothing else: a withdrawn or unauthorized source leaves the history, the record says what
  eroded and why, claims are read as of the frontier from the chain, and every retained
  retrieval manifest recomputes from the chain at its own frontier and access policy revision;
  witnessed through the owner in `linux_namespace`): `docs/adr/ADR-23-association-erosion.md`,
  `evidence/wp16/`
- Contract extensions: `docs/adr/ADR-10-hold-records.md`, `ADR-11`, `ADR-12`, `ADR-13` (DomainPack
  ports), `ADR-14` (memory chain), `ADR-15` (readout router), `ADR-16` (document and numerical
  advantage gate with declared memory ablations), `ADR-17` (operations), `ADR-18` (native PSE
  graph worker), `ADR-19` (native PSE determinism and specified readout), `ADR-20` (associative
  memory layer), `ADR-21` (association provenance in the prompt), `ADR-22` (domain-declared
  progress channels and G3 on the association distribution), `ADR-23` (erosion of the
  association history and reproducible retrieval manifests)
- Evidence (test log, environment, baseline rerun, spec validation): `evidence/`
- The blueprint's own machine-readable contracts and validator: `contracts/`, `tools/validate_spec.py`

The legacy `python -m gabriel_runtime` interface below is unchanged and remains the diagnostic
entry point for the recovered analytical runtime.

---

# Gabriel: Contractive Dynamics, Temporal Memory and Selective Observation

Sebastian Klemm

Research materials for the accompanying manuscript: a sparse recurrent architecture
with bounded activities, local correlation traces, event and elapsed-time memory,
and conditional decisions from incomplete observations. The decision infrastructure
includes exact rational finite-scenario risk calculations, absolute action constraints
and selective retrieval of current records. Gabriel cells name the local recurrent units.

## Exact preparation shared across window queries

The optional `native-graph-reachability-strict-batch/v1` profile prepares one
exact harmonic model for every atomic multi-window observation. It preserves
the scalar profile's complete certificate bytes, all original content-identity
check sites, native full-history replay and the unchanged transactional Store.
It does not cache models across commands. Existing journals keep their original
profile; no silent registry migration occurs.

Use `gabriel_runtime.batched_reachability.make_profile("strict_batch", executable,
sha256)` to obtain `(Store, adapter_name, adapter)`. The same factory accepts
`"legacy_scalar"` for the unchanged reference. See
`gabriel_runtime/BATCHED_REACHABILITY.md` and `WINDOW_BATCH.md` for the full
interface and assumptions. The standalone helper's window cap is 256; the owner
retains its cumulative cap of 32 windows per bound contract.

```bash
python reproduction/check_window_batch.py --help
python reproduction/check_batched_reachability.py --help
python reproduction/benchmark_epoch_owner.py --help
python reproduction/verify_batched_owner.py --help
```

The frozen two-profile experiment uses 32 synthetic primary tasks and eight
unsupported-graph controls, with three fresh serial workers and complete
creation-to-closure timing. `results/epoch_owner_protocol.json` defines both the
broad and the separately scoped demanding-workload criteria. Its exact inputs,
source freeze, measured summary and independent checks accompany the project.
The filename `epoch` identifies the experiment archive; the delivered profile
retains every old identity-check boundary. It does not coalesce those checks.
Reproduction requires the pinned numerical packages and the bundled executable's
matching bytes. Restore executable permission after extraction where necessary,
and keep live SQLite databases under `/tmp`, outside automatic workspace mirroring.

## Owner execution

The main CLI accepts `--owner reference|fast|replay`; `reference` remains the default.
The separate graph-observer entrypoint described below uses the original reference owner.
The `fast` owner reduces redundant canonical JSON materialization for the same
trusted adapters operating on JSON values. It preserves the journal format,
adapter fingerprints, one-transaction command boundary and complete semantic
replay on open. Owner choice is independent of `--profile`.
Stores can alternate owners without migration; their adapter profile must still
match the immutable registry binding.

```bash
python -m gabriel_runtime incremental-demo --out fast-run --owner fast
python -m gabriel_runtime audit fast-run/owner.sqlite --profile incremental --owner reference --anchor fast-run/anchor.json
python -m gabriel_runtime inspect fast-run/owner.sqlite --profile incremental --owner fast --contract stream
python reproduction/check_fast_owner_cli.py
```

`gabriel_runtime/FAST_OWNER.md` describes the execution contract and its scope.
The CLI comparison exercises both owners across all three profiles, exact demo
journals and anchors, cross-owner updates and retries, and failed submissions.
This execution choice does not change the forecasting model or predictive policy.

## Incremental execution

The incremental profile preserves the reference stream's domain states and outputs while reusing derived variance and feedback work. Its execution fingerprint is explicit; an existing reference-profile store remains bound to its original profile.

```bash
python -m gabriel_runtime incremental-demo --out incremental-run
python -m gabriel_runtime audit incremental-run/owner.sqlite --profile incremental --anchor incremental-run/anchor.json
python reproduction/check_incremental.py
python reproduction/check_incremental_cli.py
```

Schemas, cache dependencies and scope are in `gabriel_runtime/INCREMENTAL.md`. The verification includes exact state/result comparisons, revisions, cache disposal, rewind/fork behavior and historical arithmetic failures. The separate synthetic efficiency study retains its input prices, protocol, raw timings and operation counts. Reproduce its measurements in a quiet environment with:

```bash
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 python reproduction/benchmark_incremental.py --run
python reproduction/plot_incremental.py
```

These shell environment assignments use POSIX syntax. The recorded execution uses the pinned Python environment; dependency installation is separate. Timing reproduction is descriptive and can vary across systems. Full-history array construction, canonicalization and journaling remain; the optimization changes execution work, not the predictive policy.

## Integrated runtime

The `stream` profile generates an eight-expert risk forecast from received positive
scalar observations and learns when its target observation arrives. Corrections
replay current learning against the originally issued banks and weights; published
forecasts and read-only model-budget proposals stay immutable.

```bash
python -m gabriel_runtime stream-demo --out stream-run
python -m gabriel_runtime audit stream-run/owner.sqlite --profile stream --anchor stream-run/anchor.json
python -m gabriel_runtime inspect stream-run/owner.sqlite --profile stream --contract stream
python reproduction/check_stream.py
python reproduction/replay_stream_history.py
```

The exact profile is documented in `gabriel_runtime/STREAM.md`. Its horizon counts
new observations, not calendar time. For delayed ingestion the next unreceived
target may already have occurred outside the store; mature records explicitly
report that temporal relationship. The proposal limits a declared log-loss proxy
for one issue, not realized losses or a portfolio's total commitments. It executes
no order. The source and numerical parameters are fixed in the contract.

The original two-adapter profile remains the default, with the same bound
implementation files. Use `--profile stream` explicitly for stores created with
the extended registry; registry profiles are never guessed from untrusted code.


The original profile supplies one transactional owner for finite
observation and target-maturity feedback. From the project directory:

```bash
python -m gabriel_runtime demo --out local-run --with-conflict
python -m gabriel_runtime audit local-run/owner.sqlite --anchor local-run/anchor.json
python -m gabriel_runtime inspect local-run/owner.sqlite --contract risk
python reproduction/check_runtime.py
python reproduction/replay_runtime_history.py
```

The demo uses synthetic inputs, saves the original commands, SQLite database,
semantic journal, terminal anchor and result summary, and refuses to overwrite an
existing store. `python -m gabriel_runtime --help` lists command submission,
inspection, export and audit. Exact schemas and restrictions are in
`gabriel_runtime/CONTRACT.md`. Historical-import statements are explicitly marked;
no API call places a trade or controls an XR device.

The smaller `Gabriel_Runtime.zip` distribution contains this same runtime, its
eight local dependency modules, the synthetic integration checks and pinned
NumPy/SciPy requirements. It does not include the historical financial data or the
historical replay drivers. The complete research ZIP remains the full reproducible
manuscript and benchmark distribution. Extraction scope and upstream test evidence
are recorded in `RUNTIME_PROVENANCE.md` and `audit/`.


## Optional native graph analysis

`native_pse/` contains the reviewed PSE source and an equivalent packed implementation of its bounded small-graph signature. Begin with [`native_pse/GABRIEL_REVIEW.md`](native_pse/GABRIEL_REVIEW.md). The original supplied archive, focused source review, actual counterexamples and current measurements are retained. The explicit graph-observer profile now connects the native Engine to the existing Python SQLite owner. The financial reducers and their prediction policies remain unchanged.

Current Linux builds retain an unresolved mismatch with one supplied historical fixture. The current workspace run passes 492 tests, with one documentation test ignored and that fixture explicitly filtered; its separately executed failure is retained. The earlier 433/438-test runs remain historical evidence; the fixture was not replaced to conceal this result. Inherited heuristic, spectrum and topology limitations also remain visible. The bounded signature optimization has separate exact tests and a matched benchmark; its large eligible-path gains do not apply to ordinary ingestion or durable Gabriel processing.

The full project includes source, lockfiles and portable reconstruction commands. Rust 1.95.0 and the declared Cargo dependencies are external build requirements. The compact Python runtime does not need them. Historical documents and Windows measurements inside the native tree retain their original provenance; historical extraction results are under `native_pse/benchmark-results/gabriel/`; the current Engine observer and durable-owner results are described below.

## Engine observations through the durable Gabriel owner

The `Engine::conditioned_snapshot` API freezes the labelled graph actually produced
by native ingestion. A normalized, explicitly supplied complex source and a target
region define a graph observation. The three matched paths are `spectral_full`,
`auto_full` and `auto_region`; the last evaluates eligible complete-graph region
mass directly from prepared scalar coefficients. Generic graphs retain the full
state calculation. The selected threshold and deadband are a decision rule, not
calibrated confidence or a certified floating-point enclosure.

`gabriel_runtime.graph_observer.GraphObserverAdapter` registers this native observer
with the existing `Store`. Accepted batches and issued query results are retained
in the same atomic SQLite journal, with source/executable fingerprints, exact
retry identity and semantic replay. This is an operational integration into Gabriel.
It does not change the financial routes or demonstrate general predictive superiority.
The full-history, fresh-process reference bridge deliberately exposes process,
serialization, hashing and durable-transaction costs. It uses the original owner;
no earlier `FastStore` speedup is attributed to these measurements.

Measured outcomes use identical graph tasks and scalar outputs:

- Native execution: 2,520 complete Engine tasks and 229,320 timed scalar queries
  across seven fresh processes. At 256 query times, eligible complete-graph total
  task speedups are **2.034–3.114×** against `spectral_full`, including ingestion,
  snapshot and source/region preparation. These are larger task scopes than the
  historical isolated query benchmark, so their ratios must not be multiplied.
- Durable execution: 360 complete create-to-close tasks across five fresh Python
  workers, including actual native subprocesses and SQLite EXTRA transactions.
  For 64-node complete graphs with 256 query times, the median paired speedup is
  **1.0577×**, with worker medians spanning 1.0220–1.0728×. Other tested cases are
  approximately unchanged. Integration overhead absorbs most of the kernel gain.
- Independent recomputation checks every captured scalar output, all timing
  summaries, 2,056 native full states and 1,024 durable reference states against
  SciPy. The largest native complex-component error is below 7.059e-13; region
  mass error is below 3.302e-13. These are observed numerical errors, not certified
  roundoff bounds. The native workspace passes 492 tests with one ignored
  documentation test and one filtered historical fixture; that fixture still
  fails when selected separately.

The captured directory also contains 32 unexpected SQLite residues. Their stored
records match valid prefixes of captured command sequences, but they do not match
the recorded completed databases. They remain preserved and explicitly excluded
from completed-database evidence; the cause is undetermined. One intentionally
retained final database matches its captured hash and passes anchored semantic
replay. Details are in `results/graph_observer_owner_checks.json` and
`RUNTIME_PROVENANCE.md`.

See `gabriel_runtime/GRAPH_OBSERVER.md` for the wire contract, hard caps of 64 nodes,
128 batches and 256 query times, and the distinction between owner receipt time
and graph batch time. For the bundled measured Linux x86-64 executable:

```sh
GABRIEL_OBSERVER="$PWD/native_pse/benchmark-results/graph_observer_owner/executable/engine_observer_linux_x86_64.bin"
GABRIEL_OBSERVER_SHA=629b13f23fad4a4e8142eb7345e5bb2ca36dce508fb364758d76050d096300b1
chmod +x "$GABRIEL_OBSERVER"
sha256sum "$GABRIEL_OBSERVER"
python -m gabriel_runtime.graph_observer demo "$PWD/graph-observer-demo" \
  --executable "$GABRIEL_OBSERVER" --sha256 "$GABRIEL_OBSERVER_SHA"
python -m gabriel_runtime.graph_observer audit "$PWD/graph-observer-demo" \
  --executable "$GABRIEL_OBSERVER" --sha256 "$GABRIEL_OBSERVER_SHA"
python reproduction/check_graph_observer_owner.py \
  --executable "$GABRIEL_OBSERVER" --sha256 "$GABRIEL_OBSERVER_SHA" \
  --output "$PWD/graph-observer-checks" --skip-timings
python reproduction/report_engine_observer_results.py
python reproduction/report_graph_observer_owner_results.py \
  --executed native_pse/benchmark-results/graph_observer_owner/executed \
  --executable "$GABRIEL_OBSERVER"
```

Use new output directories. Compare `sha256sum` with the declared hash before
execution. `chmod` may be needed after ZIP extraction; it does not change file
bytes. The executable must run in a compatible Linux environment. Exact replay
is supported in the same numerical environment; matching source and executable
bytes do not promise identical scalar math across other platforms or libraries.
A rebuilt executable may have a different fingerprint, so creating a new journal
is distinct from replaying an archived journal with its original executable.

To repeat the measurements, independently of report regeneration:

```sh
python native_pse/benchmark-results/conditioned_engine/reproduce.py \
  --output "$PWD/new-native-engine-measurements"
python reproduction/benchmark_graph_observer_owner.py collect \
  --executable "$GABRIEL_OBSERVER" --sha256 "$GABRIEL_OBSERVER_SHA" \
  --output "$PWD/new-durable-owner-measurements"
```

The native runner requires Rust 1.95.0 and the locked dependency cache, with
no LTO, one codegen unit and one build job. Compilers, Cargo dependencies and the
Python numerical packages are external installation requirements. Frozen
protocols, executable/build provenance and raw process streams are included in
`native_pse/benchmark-results/conditioned_engine/` and
`native_pse/benchmark-results/graph_observer_owner/`.

## Contents

- `main.tex`, `references.bib`, `main.bbl`: manuscript and bibliography.
- `reproduction/`: model implementations, input generators, benchmarks and verification programs.
- `data/`: original train/test files for four public classification datasets, the unchanged ECB reference-rate archive and CSV, attribution and provenance.
- `results/`: experimental protocols, fitted models, inputs, predictions, acquisition paths,
  exact certificates, numerical checks and generated manuscript tables.
- `figures/`: vector figures and raster previews used in the manuscript.
- `REFERENCES.tsv`: bibliographic source checks, access scope and access dates for all 88 cited works.
- `requirements.txt`: pinned Python dependencies.
- `SHA256SUMS.txt`: SHA-256 checksums for every other packaged file.
- `build_release.py`: rebuilds the distribution and checks ZIP integrity.

The manuscript PDF is a separate file. All project-specific inputs required to
build it and reproduce the studies are contained in this archive. Standard Python
packages and a LaTeX distribution are installed separately as described below.

## Scientific scope

The joint activity/trace contraction condition is sufficient, not necessary.
Local execution assumes fair updates and bounded message age. Event-index storage,
ordered fading memory and damped phase banks implement different temporal contracts.
State budgets count mathematical real coordinates, not Python storage bytes.

The four external classification datasets are RacketSports, BasicMotions, NATOPS
and Epilepsy. Performance and acquisition cost depend on the task and observation
mask. Epilepsy contains movement by healthy participants and seizure-mimicking
activity; it is not clinical EEG. The experiments do not establish general
classification superiority or an optimal universal state dimension.

Acquisition retrieves values from an immutable buffered record. Input-box bounds
preserve a fixed model's decision when their assumptions hold; this is separate
from correctness against external class labels. The nonlinear observer's continuous
box pipeline uses float64 enclosures with explicit numerical tolerances. Arb
validates the identified point decisions and the standalone linear temporal banks'
continuous-box decisions. These scopes must not be interchanged.

The finite-history and annular orientation studies are exact, synthetic mechanism
studies. Under one arbitrary persistent report error, the annular adaptive policy
uses 12--17 of 24 reports; every universally sufficient fixed query set contains
all 24 coordinates. The complete 102400-case catalogue is included for each policy.
The five-query continuation is optimal after the specified two-ring prefix; global
optimality over all possible adaptive prefixes is not claimed. The implemented
EC2 baseline attains the same query counts. An invalid model or error budget can
invalidate a decision, as the supplied counterexamples demonstrate.

The financial adapter is a synthetic, exhaustive mechanism study: 64 distinct current
books appear twice with an irrelevant tag. Exact convex-mixture CVaR witnesses and
the common acceptable-action rule are independently verified. Risk modeling and
decision-region determination are established methods, specialized here to an
immutable-record contract. The primary optimal worst acquisition cost is 9 versus
10 for minimum static full-book recovery. Reversed query order also attains 9 and
has a better uniform mean. This finite-book study reports no market return, live trade or Aladdin performance
comparison. The separate ECB study below evaluates historical risk forecasts. A second
industrial adapter uses the same action engine.

## Reproduce only the risk and action studies

The core new modules use the Python standard library and exact `Fraction` arithmetic.
The optional linear-program diagnostic uses SciPy; plotting uses Matplotlib.
From the project directory:

```bash
python reproduction/check_portfolio_risk.py
python reproduction/check_decision_regions.py
python reproduction/benchmark_portfolio.py
python reproduction/verify_portfolio_outputs.py
python reproduction/summarize_portfolio.py
```

These commands generate `portfolio_risk_checks.json`, `decision_region_checks.json`,
`portfolio_results.json`, `portfolio_verification.json`, the summary tables and the
acquisition figure. The verification program does not call the risk optimizer.
The frozen protocol digest is enforced by `portfolio_adapter.py`.

## Versioned risk forecasts and budgeted acquisition

The budgeted planner minimizes mean acquisition cost under an explicit pathwise
cap. Its primary synthetic mean is 45/8=5.625 at unchanged worst cost 9. Versioned
event/receipt snapshots and exact risk-change bounds support conditional renewal
of action certificates; a failed sufficient gate requests recomputation.

The empirical financial study uses the unchanged official ECB reference-rate
archive. Development is 2010--2019; testing is 2020--2025. Four currencies and two
horizons yield 61,400 reported forecast pairs. The fixed two-scale variance filter
beats raw historical simulation on mean FZ0 in 8/8 comparisons, but the fast
single-scale filter beats that combination in 6/8. Calibration discrepancies
remain. Reference rates are informational, not executable quotes; this current
snapshot does not recreate historical publication vintages. There is no trading
or investment-performance claim. ECB inputs retain their own terms, documented
in `data/ECB_ATTRIBUTION.md`.

Run only this extension from the project root:

```bash
python reproduction/check_budgeted_regions.py
python reproduction/benchmark_budgeted_regions.py
python reproduction/verify_budgeted_regions.py
python reproduction/summarize_budgeted_regions.py
python reproduction/check_sequential_contract.py
python reproduction/benchmark_ecb_risk.py
python reproduction/verify_ecb_risk.py
python reproduction/summarize_ecb_risk.py
python reproduction/forecast_ecb_snapshot.py
python reproduction/check_ecb_snapshot.py
```

The snapshot driver defaults to 23 December 2025 and produces 8 model-bound risk
forecast records from the retained data prefix. Use `--date YYYY-MM-DD` to choose
another available origin. It uses the primary fixed equal-weight filter;
binding a forecast to its data/model identity is separate from proving numerical
rounding or action acceptability. All new forecast and selection outputs are
checked by an independent extended-precision implementation.

## Environment

The experiments used Python 3.12.14 and the versions pinned in `requirements.txt`:
NumPy 2.3.5, SciPy 1.17.0, Matplotlib 3.10.8 and python-flint 0.9.0.

```bash
python -m pip install -r requirements.txt
```

For comparable CPU execution, set `OPENBLAS_NUM_THREADS=1` and `OMP_NUM_THREADS=1`
using the syntax of your shell before running the programs. All dataset files are
included; reproduction needs no network access after dependency installation.
Execution time depends on the selected study, hardware and numerical libraries.

## Outcome maturity and adaptive calibration

The new feedback interface retains immutable issued forecasts and one active
score per matured target. Both event completion and receipt availability are
required. Revisions replace a score and replay the learner; they do not add an
independent training observation. The accepted-operation prefix disambiguates
operations with identical timestamps.

The clipped log-scale controller uses exact rational state and signed projection
accounting, conditional on binary64 forecast comparisons. It targets breach
frequency, not joint VaR/ES score or conditional calibration. In the retrospective
2020--2025 comparison the primary rule improves frequency discrepancy in 5/8
contracts and joint score in 2/8. On the previously unused short 2026 extension,
it improves frequency discrepancy in 2/8 and joint score in 0/8. All candidates,
static controls and negative findings are retained. The seven models share 1480
extension targets (10360 reported forecast pairs), not independent samples.

Run this extension from the project root:

```bash
python reproduction/check_maturity_ledger.py
python reproduction/check_calibration_accounting.py
python reproduction/benchmark_adaptive_risk.py
python reproduction/verify_adaptive_risk.py
python reproduction/summarize_adaptive_risk.py
python reproduction/replay_adaptive_maturity.py
python reproduction/check_severity_objective.py
python reproduction/check_severity_correction.py
python reproduction/benchmark_severity_risk.py
python reproduction/summarize_severity_risk.py
python reproduction/verify_severity_risk.py
python reproduction/replay_severity_maturity.py
python reproduction/check_aggregation_math.py
python reproduction/check_aggregate_summary.py
python reproduction/screen_aggregate_development.py
python reproduction/benchmark_aggregate_risk.py
python reproduction/summarize_aggregate_risk.py
python reproduction/verify_aggregate_risk.py
python reproduction/diagnose_aggregate_risk.py
python reproduction/verify_aggregate_diagnostics.py
python reproduction/verify_forgetting.py
python reproduction/verify_forgetting_summary.py
python reproduction/benchmark_forgetting_market.py
```

`adaptive_risk_protocol.json` fixes the source, parameter grid and period roles.
The independent verifier reuses the previously checked parent forecasts and
reconstructs every new adaptive/static pair. `replay_adaptive_maturity.py` checks
all 1480 extension targets against the generic ledger using raw rate endpoints
and explicit per-lane checkpoints. Its eight endpoint corrections are synthetic
mechanism tests; source files and issued forecasts remain unchanged.

## Build the manuscript

From the project directory, with pdfLaTeX, BibTeX and latexmk available:

```bash
python reproduction/check_portfolio_risk.py
python reproduction/check_decision_regions.py
python reproduction/benchmark_portfolio.py
python reproduction/verify_portfolio_outputs.py
python reproduction/summarize_portfolio.py
python reproduction/check_budgeted_regions.py
python reproduction/benchmark_budgeted_regions.py
python reproduction/verify_budgeted_regions.py
python reproduction/summarize_budgeted_regions.py
python reproduction/check_sequential_contract.py
python reproduction/benchmark_ecb_risk.py
python reproduction/verify_ecb_risk.py
python reproduction/summarize_ecb_risk.py
python reproduction/forecast_ecb_snapshot.py
python reproduction/check_ecb_snapshot.py
python reproduction/check_maturity_ledger.py
python reproduction/check_calibration_accounting.py
python reproduction/benchmark_adaptive_risk.py
python reproduction/verify_adaptive_risk.py
python reproduction/summarize_adaptive_risk.py
python reproduction/replay_adaptive_maturity.py
python reproduction/check_severity_objective.py
python reproduction/check_severity_correction.py
python reproduction/benchmark_severity_risk.py
python reproduction/summarize_severity_risk.py
python reproduction/verify_severity_risk.py
python reproduction/replay_severity_maturity.py
python reproduction/check_aggregation_math.py
python reproduction/check_aggregate_summary.py
python reproduction/screen_aggregate_development.py
python reproduction/benchmark_aggregate_risk.py
python reproduction/summarize_aggregate_risk.py
python reproduction/verify_aggregate_risk.py
python reproduction/diagnose_aggregate_risk.py
python reproduction/verify_aggregate_diagnostics.py
python reproduction/verify_forgetting.py
python reproduction/verify_forgetting_summary.py
python reproduction/benchmark_forgetting_market.py
latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex
```

Alternatively, run `pdflatex main.tex`, `bibtex main`, and then
`pdflatex main.tex` twice. Figures, generated tables and bibliography inputs are
included; no external manuscript files are required. Paragraph indentation is
zero and paragraph spacing is provided by `parskip`.

## Check the delivered archive and saved evidence

On systems with GNU coreutils, verify the unpacked files before running programs:

```bash
sha256sum --check SHA256SUMS.txt
```

The following programs independently replay three principal evidence sets without
retraining the full collection of models:

```bash
python reproduction/verify_orientation.py
python reproduction/verify_robust_orientation.py
python reproduction/verify_phase_outputs.py
```

Other study-specific `check_*.py` and `verify_*.py` programs appear in the complete
sequence below. Point and box validation involving Arb requires python-flint.
Selected phase comparisons can be repeated at higher precision with
`python reproduction/verify_phase_outputs.py --precision 160`.
An unresolved numerical comparison does not issue a certificate.

Programs write their corresponding result files. Use a fresh extracted copy when
rerunning studies so that the delivered outputs and checksum manifest remain
available for comparison. Runtime fields and PDF timestamps may change;
byte equality is not a general criterion for numerical reproducibility.

## Complete reproduction sequence

Run these commands from the project directory in the order shown. The sequence
regenerates the scientific studies and builds the manuscript from their outputs.
Protocols, seeds, initial states, splits and tolerances are recorded in the code
and the corresponding `results/*protocol.json` and verification files. Original
and reduced finite-domain studies, negative results and deliberate model violations
are retained. Some comparisons were designed after inspecting earlier cohorts;
that distinction is documented in the manuscript and saved protocols.

```bash
python reproduction/run_experiments.py
python reproduction/memory_extension.py
python reproduction/check_composition.py
python reproduction/check_async.py
python reproduction/make_figures.py
python reproduction/check_multitime.py
python reproduction/benchmark_multitime.py --cohort discovery
python reproduction/benchmark_multitime.py --cohort routing
python reproduction/verify_multitime_outputs.py
python reproduction/plot_multitime.py
python reproduction/check_partial.py
python reproduction/benchmark_partial.py
python reproduction/verify_partial_outputs.py
python reproduction/plot_partial.py
python reproduction/check_scalable.py
python reproduction/benchmark_external.py
python reproduction/verify_external_outputs.py
python reproduction/check_delayed.py
python reproduction/plot_external.py
python reproduction/check_observer.py
python reproduction/benchmark_observer.py
python reproduction/verify_observer_outputs.py
python reproduction/summarize_observer.py
python reproduction/probe_relaxed.py
python reproduction/check_relaxed.py
python reproduction/benchmark_relaxed.py
python reproduction/verify_relaxed_outputs.py
python reproduction/check_validated.py
python reproduction/benchmark_witnesses.py
python reproduction/benchmark_blocks.py
python reproduction/benchmark_block_control.py
python reproduction/verify_decision_records.py
python reproduction/summarize_decisions.py
python reproduction/check_prefix.py
python reproduction/benchmark_prefix.py
python reproduction/verify_prefix_outputs.py
python reproduction/summarize_prefix.py
python reproduction/check_domain.py
python reproduction/benchmark_domain.py
python reproduction/verify_domain_outputs.py
python reproduction/summarize_domain.py
python reproduction/check_phase.py
python reproduction/benchmark_phase.py
python reproduction/verify_phase_outputs.py
python reproduction/summarize_phase.py
python reproduction/benchmark_orientation.py
python reproduction/verify_orientation.py
python reproduction/summarize_orientation.py
python reproduction/benchmark_robust_orientation.py
python reproduction/verify_robust_orientation.py
python reproduction/summarize_robust_orientation.py
python reproduction/check_portfolio_risk.py
python reproduction/check_decision_regions.py
python reproduction/benchmark_portfolio.py
python reproduction/verify_portfolio_outputs.py
python reproduction/summarize_portfolio.py
python reproduction/check_budgeted_regions.py
python reproduction/benchmark_budgeted_regions.py
python reproduction/verify_budgeted_regions.py
python reproduction/summarize_budgeted_regions.py
python reproduction/check_sequential_contract.py
python reproduction/benchmark_ecb_risk.py
python reproduction/verify_ecb_risk.py
python reproduction/summarize_ecb_risk.py
python reproduction/forecast_ecb_snapshot.py
python reproduction/check_ecb_snapshot.py
python reproduction/check_maturity_ledger.py
python reproduction/check_calibration_accounting.py
python reproduction/benchmark_adaptive_risk.py
python reproduction/verify_adaptive_risk.py
python reproduction/summarize_adaptive_risk.py
python reproduction/replay_adaptive_maturity.py
python reproduction/check_severity_objective.py
python reproduction/check_severity_correction.py
python reproduction/benchmark_severity_risk.py
python reproduction/summarize_severity_risk.py
python reproduction/verify_severity_risk.py
python reproduction/replay_severity_maturity.py
python reproduction/check_aggregation_math.py
python reproduction/check_aggregate_summary.py
python reproduction/screen_aggregate_development.py
python reproduction/benchmark_aggregate_risk.py
python reproduction/summarize_aggregate_risk.py
python reproduction/verify_aggregate_risk.py
python reproduction/diagnose_aggregate_risk.py
python reproduction/verify_aggregate_diagnostics.py
python reproduction/verify_forgetting.py
python reproduction/verify_forgetting_summary.py
python reproduction/benchmark_forgetting_market.py
latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex
```

After building `main.pdf`, `python build_release.py` recreates the publication ZIP
and copies the PDF beside it. This packaging step checks every NPZ container and
the resulting ZIP, and regenerates the checksum manifest.

## Severity adaptation

The severity adapter maintains an **uncapped** discounted sufficient statistic
and caps only the emitted ES/VaR ratio. Its reciprocal-ratio objective is convex;
the retained state gives an exact real-arithmetic historical minimizer, not a
future calibration guarantee. All severity market comparisons, including 2026, are
retrospective because those outcomes were already examined. The separate frozen
known-law study has five cases, 32 replications and two receipt latencies. Latency
five delays an individual synthetic outcome and does not aggregate five losses.
Every replication's metrics and full replicate-zero traces are retained; seeds
and code reconstruct the other full traces. Run the severity commands above
to reproduce this study and its maturity/correction checks. Arithmetic is binary64
with separately documented verification tolerances. Older training runs were not
reexecuted for this extension.

## Convex joint-risk aggregation

The joint-risk layer mixes `(Q/E, 1/E)` on a simplex. Its Jensen identity proves
an outcome-wise advantage over randomized expert selection with the same weights.
It does not promise to beat the best deterministic expert. A frozen positively
regularized empirical objective has a unique proximal fixed point; the actual
numerical fitting routine uses SLSQP and is checked against a convex lower bound.
Online simplex updates use separate maturity lanes and centered gradients.

`results/aggregate_risk_protocol.json` and its `.sha256` seal freeze the primary
method before any new-currency evaluation. USD/GBP/JPY/CHF through 2019 selected
`adagrad_c0p1`; the screen now writes a separately named replay result and cannot
overwrite the frozen original. AUD/CAD/NOK/SEK are previously unevaluated asset
columns from the same source and calendar, not an independent future replication.
The 1,721 shared origins give 13,768 primary contract cases. The overall superiority
gate **fails**: mean primary-minus-score differences are +0.001956 versus fitted
arithmetic pooling, -0.013787 versus uniform arithmetic pooling, +0.005058 versus
development-selected experts and -0.004231 versus fitted transformed pooling.
All four comparisons, all 16 methods, both circular block lengths (20,60), 5,000
shared draws per length and excluded final one-step origins remain available.
These bootstrap limits are approximate historical diagnostics.

The independent verifier reconstructs rates/tails, forecast banks, 102,768 online
updates, static-fit objectives and dual witnesses, every metric, causal selection
checks and all stored bootstrap draws. Generic algebra and synthetic controller
checks supplement this replay. They do not provide directed-rounding certification
of floating-point financial forecasts. Previous sections' training runs are
preserved and were not rerun as part of this aggregation extension.

## Forgetting gradient history

Four distinct rules now share the same transformed pooling and maturity clock:
cumulative gradient energy, exponentially discounted energy, an exact finite norm
window, and periodic resetting of both weights and energy. Forgetting norm history
alone does not erase the dependence of current weights on past observations.
A valid nonmonotone-step regret bound retains positive variation of inverse step
sizes. The restart synchronization statement is conditional on an unchanged expert
bank and aligned reset clock.

The known-law study contains seven laws, 32 replications, two receipt latencies and
22 settings (19 screened settings plus three matched-step diagnostic controls).
At c=0.1, discount125 reduces changing-law conditional excess score from 0.48136 to
0.38686, but its old-market development score is slightly worse. Smaller step
multipliers improve that market criterion while failing the original controlled
response/stationary conditions. No setting passes the complete selection rule;
the operating candidate remains cumulative c=0.1. NZD/SGD/KRW/ZAR were not loaded
or evaluated. The transfer script records this nonexecution before any rate read.

Independent extended-precision replay reconstructs all 9,856 synthetic cases,
59,136 scalar metric values, 882 stored trace arrays, 176 old-market records and
370 paired intervals. These checks are not directed-rounding certificates.

To regenerate the complete study without overwriting frozen original evidence:

```bash
python reproduction/reproduce_forgetting.py
```

This creates a sibling `Gabriel_Forgetting_Replay` project with all required local
inputs and isolated generated outputs. It runs the three benchmark stages,
summary and two independent verifiers, then compares the main scalar results and
selection against the original. The wrapper itself is supplied; the individual
programs were executed and checked in this research run. Use the verification
commands above for a read/recompute audit of the included outputs.

The initial aligned-switch execution was superseded before its numerical outcomes
were examined. The retained v2 protocol uses nonmatching change times. The staged
search and this development amendment are recorded explicitly in the protocol
files. A trace archive was rebuilt from the same seeds and recurrence after a
technical serialization failure; `forgetting_archive_rebuild.json` records its
current container hash. Independent replay checks its values against the scalar
results. The frozen scientific selection records remain unchanged.

## Data attribution and rights

The unchanged UEA time-series files are distributed by the TSML Archive Maintainers
under Creative Commons Attribution 4.0 International. `data/ATTRIBUTION.md` gives
original collectors, source DOIs, license links, split details and preprocessing.
The recorded file checksums identify the exact inputs used. These notices apply
to the external datasets; they do not assign a license to the author's manuscript
or software. The license selected for the public deposit governs the original
materials within its stated scope. Python and LaTeX dependencies are not bundled
and retain their respective licenses.

## Complete replay and finite orbit data

`--owner replay` inherits live operations from `fast` and recomputes every
transition on open, comparing stored derived text directly with freshly
regenerated canonical text. See `gabriel_runtime/REPLAY.md`.

```bash
python reproduction/check_replay_owner.py
python reproduction/check_replay_owner_cli.py
python reproduction/benchmark_replay_owner.py --prepare
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 python reproduction/benchmark_replay_owner.py --run registers
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 python reproduction/benchmark_replay_owner.py --run h1
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 python reproduction/benchmark_replay_owner.py --run h5
python reproduction/benchmark_replay_owner.py --summarize
python reproduction/report_replay_results.py
```

The independent finite-index checker has been compiled and executed using C++17.
Its complete table certificate and fault tests are in
`native_pse/benchmark-results/indexed/results/verification_report.json`.
The optional Rust `indexed-signature` consumer and exact-input
`memoized-signature` cache have been compiled, tested and measured. The full
workspace run passes 449 tests with one documentation test ignored and the
preserved historical fixture explicitly filtered; its unfiltered failure
remains recorded. Packed remains the default. The new matched no-LTO builds
improve warm whole-engine throughput by 1.18–1.66× for indexed versus packed
execution in the repeated complete-graph workloads with 3/5/7 sources. The cache
adds workload-dependent reuse and incurs first-call/miss costs. These results
do not change the Python runtime or prediction quality.
See `native_pse/INDEXED_SIGNATURE.md` for activation and verification commands.
The full benchmark wrapper was executed; its frozen protocol, exact equality
gates, raw measurement records and executable/source hashes are in
`native_pse/benchmark-results/indexed_engine/executed/`. Regenerate the manuscript
tables with `python reproduction/report_native_indexed_results.py`.
The release profile now disables LTO after local ThinLTO undefined-symbol
failures. The new experiments use the same profile for every compared variant
and do not combine ratios with the earlier ThinLTO experiments.

## Sparse native engine: guarded phase and spectrum reuse

The optional `phase-hoist` and `shared-spectrum` features remove repeated mode
phases and the immediately repeated C16/C18 eigendecomposition. Exceptional or
overflow-risk CTQW inputs use the unchanged reference body. The recorded phase/spectrum-study
all-feature workspace run passes 461 tests, with one documentation test ignored
and the same historical fixture explicitly filtered; its final-source unfiltered
failure is retained. Strict CTQW comparisons cover 1,500 parameter cases. Feature
defaults remain unchanged; activation is documented in
`native_pse/SPECTRAL_REUSE.md`.

Four matched Rust 1.95.0 builds produce identical 19,658,993-byte serialized
complete-crystal/selected-state goldens on 233 public-input steps. Thirty timed
processes execute 43,560 committed macrosteps across sparse repeated paths and
monotone edge acquisition at 3, 5, 7, 8 and 16 vertices. Phase reuse gives median
whole-macrostep throughput ratios of 1.216–5.871 against the indexed reference
build. Within-step spectrum reuse adds smaller median ratios of 1.020–1.106;
several pair ranges include one. Signature caching helps repeated eligible
paths, while reset acquisition gives ratios close to one. These are controlled
synthetic extraction/morphology configurations, not default-workload, Python
owner or prediction-accuracy results. Timing ranges are retained in the paper.

Rebuild and measure into a NEW directory with
`python native_pse/benchmark-results/phase_engine/reproduce.py --output /absolute/new/output`.
The delivered measurement is in `native_pse/benchmark-results/phase_engine/executed/`.
`python reproduction/report_native_phase_results.py` independently verifies all
44 original individual command records, 88 original captured streams, source
hashes, actual induced graphs, cache counters and all 30 ratio summaries, then
regenerates the manuscript tables. It performs no new timings.

One aggregate command index retained only the first 43 entries. All 44 original
individual records and their streams are present and agree with redundant
original-byte captures. The original aggregate remains unchanged and flagged;
`results/native_phase_command_index.json` is an explicitly derived complete
index linked to those original files and hashes. The cause of the aggregate
persistence discrepancy is undetermined. No timing value or missing raw output
was reconstructed. Earlier indexed-study provenance issues remain separately
documented rather than being relabelled as part of this run.

## Targeted persistence verification

A targeted follow-up replays all 32 affected command sequences into new retained
stores. Both workspace batches initially reproduce every final receipt and
SQLite image byte-for-byte and pass immediate reopening. Later checks find
2/32 and 5/32 images at earlier valid prefixes, including a batch without
concurrent workspace operations. The same unchanged verification outside the
workspace passes all 32 after-batch and subsequent fresh-execution checks.
This is an observed storage-location contrast; the mechanism remains unresolved.
The checks generate no new performance claim. Unrestricted persistence reliability
in the benchmark environment is not established. All three runs are sealed in
`audit/engine_observer_residue_replay_{failed,isolated_failed,outside_passed}.zip`;
`audit/engine_observer_persistence_location_check.json` records their hashes,
comparison and final outside-workspace checks. The executable reproduction is
`reproduction/check_engine_observer_residue_replay.py --help`; choose a new output
directory and retain both success and failure results.

## Historical conditioned graph-state queries and D6 correction

The explicit `pse_topology::conditioned_walk` API now provides immutable graph plans and prepared complex states. Auto recognizes a strict uniformly weighted complete-graph case; Spectral forces the same general full-eigensystem calculation. The existing all-pairs threshold code and default features are unchanged. See `native_pse/CONDITIONED_WALK.md` for validation, time/sign conventions, finite-precision boundaries and an executable API example.

Validation at that measured revision: **481 passed, one ignored documentation test, one explicitly filtered historical fixture**. The separately selected historical fixture still fails. Twenty new tests cover the conditioned API and the D6 correction. The initial targeted command against the wrong package selected zero tests and is retained and labelled as such. No fixture was replaced.

Seven fresh processes execute eleven frozen cases and 4,802,560 timed state queries in total. Median eligible query ratios range from 3.421 to 63.879 against the forced full-spectral backend for the same vector output. The five fallback controls lie near one, with all observed ranges including one. These are API kernel ratios, not whole-engine or forecast-quality gains. Setup, preparation and query costs remain separate. The frozen 16-time cycle includes one zero-time query.

Independent reporting checks 94,976 real-component pairs and 176 first-process reference states with SciPy. Maximum complex-component discrepancy against SciPy is 2.411e-12. All 11 original command records and 22 output streams validate. The original aggregate index contains only 10 records; its cause is undetermined. A separately labelled derived index references all 11 originals. Source guards cover 76 files, now preserved exactly in `audit/native_conditioned_measured_sources.zip`. These kernel timings belong to that historical source snapshot. The prior 77-source spectral study remains bound to `audit/native_phase_measured_sources.zip`; its prior timing results are not reattributed to the current tree.

```sh
python native_pse/benchmark-results/conditioned_walk/reproduce.py --output /absolute/new/output
python reproduction/report_native_conditioned_results.py
```

The benchmark runner refuses to overwrite an existing output directory. The independent reporter reads the included executed observations by default; use its `--executed` argument for a new run. NumPy and SciPy versions are recorded in `results/native_conditioned_checks.json`. Compiler/Cargo dependencies are declared and locked, not vendored.

## Certified continuous-time windows

Gabriel now exposes `native-graph-reachability/v1`, an opt-in native/Store path
for the strict model predicate `exists t in [start,end]: regional_mass(t) > h`.
It returns a checked crossing witness, whole-window exclusion, bounded unknown,
or explicit out-of-scope result for unsupported graphs. Invalid inputs reject
the atomic command. This profile normalizes exact raw binary64 dyadics over the
reals; it does not certify the older observer's rounded instruction sequence.
The mathematical profile is an exact equal-diagonal uniform weighted clique,
with at most 64 nodes, 128 retained batches and a cumulative cap of 32 issued windows per bound contract (configurable downward).

The complete English manuscript contains the derivation, finite resource
contract, validated subdivision controls, protocol, results and limitations.
The canonical measured outcome is
`results/window_reachability_study/verified_timing_audit.json`:
all 256 primary cases resolved identically, but the prespecified timing-superiority
criterion **failed** (median adaptive/analytic ratio 0.9924174). The independent
checker validates 850 decisions and 2 abstentions across 852 method/case records,
plus 26 separate edge cases. No new financial prediction or general superiority
is established.

Install the pinned `requirements.txt`. For just the new module, python-flint 0.9.0
is required. Use a fresh interpreter, frozen source files and no unrelated
concurrent changes to Flint's process-global precision context.

```sh
python reproduction/check_window_certificate.py --output /tmp/window_checks.json
python reproduction/verify_window_reachability.py \
  --inputs results/window_reachability_study/inputs.json \
  --evaluation results/window_reachability_study/evaluation_final.json \
  --output /tmp/window_verification.json
python reproduction/verify_reachability_owner.py \
  --archive audit/reachability_owner_closed.zip \
  --output /tmp/owner_verification.json
python audit/report_window_reachability_timing.py
python reproduction/report_window_tables.py
```

The native bridge's declared build is `cargo build --locked --release --example
engine_snapshot` from `native_pse`, with `CARGO_PROFILE_RELEASE_LTO=false`,
`CARGO_PROFILE_RELEASE_CODEGEN_UNITS=1`, `CARGO_PROFILE_RELEASE_OPT_LEVEL=3`,
`CARGO_PROFILE_RELEASE_DEBUG=false`, `CARGO_PROFILE_RELEASE_STRIP=symbols` and
Rust 1.95.0. `--offline` was used in the executed build against an existing cache;
a clean machine must acquire the locked dependencies first. Compiler and crates
are not bundled. The measured Linux executable and build records are in
`native_pse/benchmark-results/window_reachability/executable/`; its SHA-256 is
`f47f01b1f14c53184ccd5abdf22e01865d750a7b513f7acd6ec1e1a6a833aa93`.

```sh
SNAPSHOT_BIN="$PWD/native_pse/benchmark-results/window_reachability/executable/engine_snapshot_linux_x86_64.bin"
SNAPSHOT_SHA=f47f01b1f14c53184ccd5abdf22e01865d750a7b513f7acd6ec1e1a6a833aa93
chmod +x "$SNAPSHOT_BIN"
python reproduction/check_graph_reachability.py \
  --executable "$SNAPSHOT_BIN" --sha256 "$SNAPSHOT_SHA" \
  --output /tmp/new_gabriel_window_check
python reproduction/benchmark_reachability_owner.py \
  --executable "$SNAPSHOT_BIN" --sha256 "$SNAPSHOT_SHA" \
  --output /tmp/new_gabriel_window_owner_run
```

The last command performs new timings; output paths must not already exist.
The delivered 24 complete tasks have medians 332–531 ms, with certificate-call
shares 0.45–8.90%. No alternative owner was timed. Exact source, executable and
arithmetic-package fingerprints are mandatory; a different installation may
reject the historical journal. A new build can produce its own fresh evidence.
The preceding v1 point observer's 69 fingerprinted sources and three original
backend replay anchors remain preserved.

`reproduction/benchmark_window_reachability.py --help` exposes separate generate,
evaluate, collect and report operations. The final measured sources are frozen;
the older `evaluation.json` and archived old source variants are explicitly
pre-cap/pre-fairness evidence. `evaluation_final.json` is used for current claims.
The baseline fairness amendment occurred after untimed semantic outcomes and
before any performance data; it did not change cases, statuses or acceptance.

## Storage boundary controls

The new 60 paced/burst live controls did not reproduce the historical prefix
regressions. A deliberately injected replacement was detected in 3/3 positive
controls. The environment exposes automatic writable workspace synchronization;
its causal role in the historical failures remains unknown. Both inspected
locations share an overlay with `fsync=volatile`, so success does not establish
physical power-loss durability. See `audit/persistence_boundary_review.md`.

Keep live databases outside automatic mirroring; publish only closed, verified
and sealed snapshots with separately retained final journal heads/event counts.
The new owner archive was checked again after closure. `/tmp` is the current
execution location, not a persistent deployment recommendation. Source hashes
and independent anchors provide integrity checks, not authentication. No earlier
failed residue was deleted, relabelled or treated as a final-state witness.
