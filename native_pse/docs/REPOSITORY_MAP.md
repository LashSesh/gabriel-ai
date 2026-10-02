# Repository-Kartierung

Originalzustand: statische Manifest-/Quellkartierung, ergänzt um dynamische Tests der Engine-Hülle.
A = Core, B = Runtime, C = Supporting, D = Application, E = Legacy/ersetzt, F = Unknown außerhalb der Hülle.
Unknown-Dateien bleiben im Original erhalten. Dateihashes des gesamten Ausgangsbestands liegen im forensischen Verzeichnis.

| Paket / Originalpfad | Klasse | In Lieferung | Direkte interne Dependencies |
|---|---|---|---|
| `adapters/pse-adapter-airquality/Cargo.toml` | D | nein | pse-types, pse-core, pse-graph |
| `adapters/pse-adapter-binance/Cargo.toml` | D | nein | pse-types, pse-core, pse-graph |
| `adapters/pse-adapter-entsoe/Cargo.toml` | D | nein | pse-types, pse-core, pse-graph |
| `adapters/pse-adapter-il/Cargo.toml` | D | nein | pse-types, mef-core (optional), mef-ingestion (optional), mef-solvecoagula (optional), mef-tic (optional), mef-ledger (optional), mef-spiral (optional) |
| `adapters/pse-adapter-iot/Cargo.toml` | D | nein | pse-types, pse-core, pse-graph |
| `adapters/pse-adapter-kosmo/Cargo.toml` | D | nein | pse-types, pse-core, pse-graph, pse-adapter-il, kosmo-core, kosmo-pse-bridge |
| `adapters/pse-adapter-modelmon/Cargo.toml` | D | nein | pse-types, pse-core, pse-graph |
| `adapters/pse-adapter-seismo/Cargo.toml` | D | nein | pse-types, pse-core, pse-graph |
| `adapters/pse-adapter-syslog/Cargo.toml` | D | nein | pse-types, pse-core, pse-graph |
| `adapters/pse-adapter-tabular/Cargo.toml` | D | nein | pse-types, pse-core, pse-graph |
| `adapters/pse-adapter-vitals/Cargo.toml` | D | nein | pse-types, pse-core, pse-graph |
| `adapters/pse-adapter-weather/Cargo.toml` | D | nein | pse-types, pse-core, pse-graph |
| `bindings/python/Cargo.toml` | D | nein | pse-core, pse-types, pse-graph |
| `crates/kosmo-agent/Cargo.toml` | D | nein | kosmo-core, kosmo-pipeline, kosmo-pse-bridge, kosmo-synthesizer, kosmo-materialize, kosmo-intent |
| `crates/kosmo-cdk-core/Cargo.toml` | D | nein | kosmo-core |
| `crates/kosmo-coffindragger/Cargo.toml` | D | nein | kosmo-core, kosmo-cdk-core, kosmo-systemcube |
| `crates/kosmo-core/Cargo.toml` | D | nein | — |
| `crates/kosmo-foundry/Cargo.toml` | D | nein | kosmo-core |
| `crates/kosmo-hyphae/Cargo.toml` | D | nein | kosmo-core, kosmo-workbench |
| `crates/kosmo-intent/Cargo.toml` | D | nein | kosmo-core, kosmo-hyphae, kosmo-parseback, kosmo-sandbox |
| `crates/kosmo-intent-llm/Cargo.toml` | D | nein | kosmo-core, kosmo-intent, kosmo-llm |
| `crates/kosmo-kcube/Cargo.toml` | D | nein | kosmo-core |
| `crates/kosmo-llm/Cargo.toml` | D | nein | — |
| `crates/kosmo-materialize/Cargo.toml` | D | nein | kosmo-core, kosmo-synthesizer, kosmo-foundry |
| `crates/kosmo-operator/Cargo.toml` | D | nein | kosmo-core, kosmo-foundry, kosmo-parseback, kosmo-store |
| `crates/kosmo-parseback/Cargo.toml` | D | nein | kosmo-core |
| `crates/kosmo-pipeline/Cargo.toml` | D | nein | kosmo-core, kosmo-workbench, kosmo-hyphae, kosmo-systemcube, kosmo-store, kosmo-spectral, kosmo-pse-bridge |
| `crates/kosmo-pse-bridge/Cargo.toml` | D | nein | kosmo-core |
| `crates/kosmo-sandbox/Cargo.toml` | D | nein | kosmo-core |
| `crates/kosmo-spectral/Cargo.toml` | D | nein | kosmo-core |
| `crates/kosmo-store/Cargo.toml` | D | nein | kosmo-core, kosmo-hyphae |
| `crates/kosmo-synthesizer/Cargo.toml` | D | nein | kosmo-core, kosmo-hyphae, kosmo-pipeline, kosmo-pse-bridge |
| `crates/kosmo-synthesizer-llm/Cargo.toml` | D | nein | kosmo-core, kosmo-pipeline, kosmo-synthesizer, kosmo-pse-bridge |
| `crates/kosmo-systemcube/Cargo.toml` | D | nein | kosmo-core, kosmo-kcube |
| `crates/kosmo-wings/Cargo.toml` | D | nein | kosmo-core, kosmo-cdk-core, pse-metatron |
| `crates/kosmo-workbench/Cargo.toml` | D | nein | kosmo-core |
| `crates/phase-matrix/Cargo.toml` | D | nein | pse-traverse |
| `crates/pse/Cargo.toml` | D | nein | pse-types, pse-core, pse-graph, pse-extract, pse-cascade, pse-evidence, pse-registry, pse-topology, pse-scale, pse-navigator, pse-constraint, pse-swarm, pse-store, pse-capsule, pse-scheduler, pse-replay, pse-manifest, pse-pmhd, pse-memory, pse-metatron, pse-reasoning, pse-adapter-il |
| `crates/pse-capsule/Cargo.toml` | C | nein | pse-types, pse-manifest, pse-evidence, pse-registry |
| `crates/pse-cascade/Cargo.toml` | A | ja | pse-types, pse-metatron |
| `crates/pse-cli/Cargo.toml` | D | nein | kosmo-core, pse-types, pse-core, pse-evidence, pse-graph, pse-registry, pse-manifest, pse-capsule, pse-scheduler, pse-store, pse-memory, pse-topology, pse-scale, pse-pmhd, pse-navigator, pse-gateway, pse-constraint, pse-adapter-binance, pse-adapter-entsoe, pse-adapter-seismo, pse-adapter-weather, pse-adapter-airquality, pse-adapter-iot, pse-adapter-syslog, pse-adapter-vitals, pse-adapter-tabular, pse-adapter-modelmon, pse-audit, pse-net |
| `crates/pse-constitutional-interceptor/Cargo.toml` | D | nein | pse-nxalien-types |
| `crates/pse-constraint/Cargo.toml` | A | ja | pse-types, pse-graph |
| `crates/pse-core/Cargo.toml` | A | ja | pse-types, pse-graph, pse-extract, pse-cascade, pse-evidence, pse-replay, pse-constraint, pse-registry, pse-manifest, pse-scheduler, pse-topology, pse-scale, pse-navigator, pse-capsule, pse-swarm, pse-pmhd, pse-memory, pse-metatron, pse-net (optional), pse-net |
| `crates/pse-eval-matrix/Cargo.toml` | D | nein | pse-traverse |
| `crates/pse-eval-runner/Cargo.toml` | D | nein | pse-eval-matrix, pse-traverse |
| `crates/pse-evidence/Cargo.toml` | A | ja | pse-types |
| `crates/pse-exploratory/Cargo.toml` | D | nein | pse-nxalien-types |
| `crates/pse-extract/Cargo.toml` | A | ja | pse-types, pse-graph |
| `crates/pse-gateway/Cargo.toml` | D | nein | pse-types, pse-core, pse-evidence, pse-store, pse-navigator |
| `crates/pse-graph/Cargo.toml` | B | ja | pse-types |
| `crates/pse-manifest/Cargo.toml` | C | nein | pse-types, pse-evidence, pse-registry |
| `crates/pse-memory/Cargo.toml` | A | ja | pse-types, pse-metatron |
| `crates/pse-metatron/Cargo.toml` | C | ja | pse-types |
| `crates/pse-navigator/Cargo.toml` | C | ja | pse-topology |
| `crates/pse-net/Cargo.toml` | B | nein | pse-types |
| `crates/pse-nxalien-agent/Cargo.toml` | D | nein | pse-nxalien-types, pse-nxalien-core |
| `crates/pse-nxalien-core/Cargo.toml` | D | nein | pse-nxalien-types, pse-types |
| `crates/pse-nxalien-cube/Cargo.toml` | D | nein | pse-nxalien-types, pse-nxalien-core, pse-types |
| `crates/pse-nxalien-evolve/Cargo.toml` | D | nein | pse-nxalien-types, pse-nxalien-core, pse-nxalien-pse, pse-types, pse-graph, pse-constraint, pse-adapter-il |
| `crates/pse-nxalien-pse/Cargo.toml` | D | nein | pse-nxalien-types, pse-nxalien-core, pse-types, pse-graph |
| `crates/pse-nxalien-types/Cargo.toml` | D | nein | pse-types |
| `crates/pse-pmhd/Cargo.toml` | C | nein | pse-types |
| `crates/pse-reasoning/Cargo.toml` | D | nein | pse-adapter-il, pse-types |
| `crates/pse-registry/Cargo.toml` | C | nein | pse-types |
| `crates/pse-replay/Cargo.toml` | E | nein | pse-types, pse-evidence |
| `crates/pse-scale/Cargo.toml` | A | ja | pse-types, pse-graph, pse-topology |
| `crates/pse-scheduler/Cargo.toml` | B | nein | pse-types |
| `crates/pse-store/Cargo.toml` | C | nein | pse-types |
| `crates/pse-swarm/Cargo.toml` | B | nein | pse-types, pse-pmhd |
| `crates/pse-topology/Cargo.toml` | A | ja | pse-types, pse-graph |
| `crates/pse-traverse/Cargo.toml` | D | nein | pse-types, pse-core (optional), pse-graph (optional) |
| `crates/pse-types/Cargo.toml` | A | ja | — |
| `crates/pse-validation-runner/Cargo.toml` | D | nein | pse-traverse |
| `crates/pse-wasm/Cargo.toml` | D | nein | pse-types, pse-core, pse-graph, pse-extract, pse-cascade, pse-evidence, pse-registry, pse-topology, pse-constraint, pse-scale, pse-navigator, pse-scheduler, pse-replay, pse-manifest, pse-pmhd, pse-memory, pse-capsule, pse-swarm, pse-store, pse-adapter-tabular |
| `tools/kosmo-cdk/Cargo.toml` | D | nein | kosmo-core, kosmo-cdk-core, kosmo-coffindragger, kosmo-systemcube |
| `tools/kosmo-eval/Cargo.toml` | D | nein | kosmo-core, kosmo-hyphae, kosmo-pse-bridge, kosmo-foundry, kosmo-store, kosmo-parseback, kosmo-operator, kosmo-kcube, kosmo-systemcube, kosmo-pipeline, kosmo-workbench |
| `tools/kosmo-promote/Cargo.toml` | D | nein | kosmo-core, kosmo-pipeline, kosmo-pse-bridge, kosmo-store, pse-adapter-kosmo, pse-adapter-il, pse-core, pse-types, kosmo-hyphae |
| `tools/kosmo-run/Cargo.toml` | D | nein | kosmo-core, kosmo-foundry, kosmo-hyphae, kosmo-intent, kosmo-intent-llm, kosmo-kcube, kosmo-llm, kosmo-parseback, kosmo-pipeline, kosmo-sandbox, kosmo-store, kosmo-synthesizer, kosmo-synthesizer-llm, kosmo-agent, kosmo-pse-bridge, pse-adapter-kosmo, pse-traverse |
| `tools/kosmo-server/Cargo.toml` | D | nein | kosmo-core, kosmo-pipeline, kosmo-intent, kosmo-hyphae, kosmo-store, kosmo-pse-bridge, pse-adapter-kosmo, pse-adapter-il, pse-core, pse-types |
| `tools/kosmo-substrate/Cargo.toml` | D | nein | kosmo-core, kosmo-pipeline |
| `tools/kosmo-tui/Cargo.toml` | D | nein | kosmo-core, kosmo-pipeline, kosmo-intent, kosmo-pse-bridge, pse-adapter-kosmo, pse-core, pse-types |
| `tools/nxalien-cli/Cargo.toml` | D | nein | kosmo-core, pse-nxalien-types, pse-nxalien-core, pse-nxalien-cube, pse-nxalien-agent, pse-nxalien-pse, pse-nxalien-evolve, pse-exploratory |
| `tools/pse-audit/Cargo.toml` | D | nein | pse-types, pse-core, pse-graph, pse-evidence, pse-store |
| `tools/pse-bench-bbo/Cargo.toml` | D | nein | pse-navigator |
| `tools/pse-bench-cognitive/Cargo.toml` | D | nein | pse-traverse |
| `tools/pse-bench-gt/Cargo.toml` | D | nein | pse-core, pse-types, pse-graph, pse-adapter-seismo, pse-adapter-vitals, pse-adapter-binance, pse-cascade, pse-memory, pse-metatron |
| `tools/pse-demo/Cargo.toml` | D | nein | pse-core, pse-types, pse-graph, pse-bench-gt |
| `tools/pse-eval-matrix-cli/Cargo.toml` | D | nein | kosmo-core, pse-eval-matrix |
| `tools/pse-eval-runner-cli/Cargo.toml` | D | nein | pse-eval-matrix, pse-eval-runner |
| `tools/pse-llm-demo/Cargo.toml` | D | nein | pse-core, pse-types, pse-graph, pse-memory, pse-adapter-il |
| `tools/pse-metatron-cli/Cargo.toml` | D | nein | kosmo-core, pse-metatron |
| `tools/pse-paper-bench/Cargo.toml` | D | nein | pse-adapter-il, pse-constitutional-interceptor, pse-reasoning, pse-nxalien-types, pse-types, pse-bench-gt, pse-eval-matrix |
| `tools/pse-phase-matrix-cli/Cargo.toml` | D | nein | kosmo-core, phase-matrix |
| `tools/pse-server/Cargo.toml` | D | nein | kosmo-core, pse-core, pse-types, pse-graph, pse-adapter-il, pse-nxalien-types, pse-nxalien-evolve, pse-constitutional-interceptor, pse-exploratory, pse-reasoning |
| `tools/pse-traverse-cli/Cargo.toml` | D | nein | kosmo-core, pse-traverse, pse-types, pse-graph, pse-core |
| `tools/pse-traverse-cognition-cli/Cargo.toml` | D | nein | kosmo-core, pse-traverse |
| `tools/pse-traverse-horizon-cli/Cargo.toml` | D | nein | kosmo-core, pse-traverse |
| `tools/pse-traverse-lpcm-cli/Cargo.toml` | D | nein | kosmo-core, pse-traverse |
| `tools/pse-traverse-topology-cli/Cargo.toml` | D | nein | kosmo-core, pse-traverse |
| `tools/pse-validation-runner-cli/Cargo.toml` | D | nein | kosmo-core, pse-validation-runner, pse-traverse |
| `vendors/infinityledger/Cargo.toml` | F | nein | mef-knowledge, mef-schemas |
| `vendors/infinityledger/mef-acquisition/Cargo.toml` | F | nein | — |
| `vendors/infinityledger/mef-api/Cargo.toml` | F | nein | mef-spiral, mef-ledger, mef-hdag, mef-ingestion, mef-solvecoagula, mef-tic, mef-coupling, mef-audit, mef-storage, mef-vector-db, mef-core, mef-topology, mef-domains, mef-knowledge, mef-schemas |
| `vendors/infinityledger/mef-audit/Cargo.toml` | F | nein | — |
| `vendors/infinityledger/mef-bench/Cargo.toml` | F | nein | — |
| `vendors/infinityledger/mef-benchmarks/Cargo.toml` | F | nein | mef-spiral, mef-ledger, mef-core, mef-memory, mef-schemas |
| `vendors/infinityledger/mef-cli/Cargo.toml` | F | nein | mef-spiral, mef-solvecoagula, mef-tic, mef-ledger, mef-hdag, mef-ingestion, mef-storage |
| `vendors/infinityledger/mef-core/Cargo.toml` | F | nein | mef-ingestion, mef-solvecoagula, mef-tic, mef-ledger, mef-spiral |
| `vendors/infinityledger/mef-coupling/Cargo.toml` | F | nein | — |
| `vendors/infinityledger/mef-domains/Cargo.toml` | F | nein | mef-core, mef-topology, mef-hdag, mef-ledger, mef-tic |
| `vendors/infinityledger/mef-hdag/Cargo.toml` | F | nein | — |
| `vendors/infinityledger/mef-ingestion/Cargo.toml` | F | nein | — |
| `vendors/infinityledger/mef-knowledge/Cargo.toml` | F | nein | mef-schemas, mef-memory, mef-router |
| `vendors/infinityledger/mef-ledger/Cargo.toml` | F | nein | — |
| `vendors/infinityledger/mef-memory/Cargo.toml` | F | nein | mef-schemas |
| `vendors/infinityledger/mef-router/Cargo.toml` | F | nein | mef-schemas |
| `vendors/infinityledger/mef-schemas/Cargo.toml` | F | nein | — |
| `vendors/infinityledger/mef-solvecoagula/Cargo.toml` | F | nein | — |
| `vendors/infinityledger/mef-specs/Cargo.toml` | F | nein | — |
| `vendors/infinityledger/mef-spiral/Cargo.toml` | F | nein | — |
| `vendors/infinityledger/mef-storage/Cargo.toml` | F | nein | — |
| `vendors/infinityledger/mef-tic/Cargo.toml` | F | nein | — |
| `vendors/infinityledger/mef-topology/Cargo.toml` | F | nein | mef-core |
| `vendors/infinityledger/mef-vector-db/Cargo.toml` | F | nein | — |

## Nicht-Rust-Bereiche

| Bereich | Klasse und Befund |
|---|---|
| `web/`, `bindings/`, Docker, Produkt-Workflows | D; UI, Sprachbindung und Deployment |
| `docs/`, `specs/`, PDF-Spezifikationen, Statusdateien | C/F; Hinweise und Anforderungen, keine ausführbare Kernelabhängigkeit |
| `tests/integration/smoke_test.rs` | D; Produktintegration außerhalb der neuen Engine |
| `vendors/infinityledger` | F außerhalb der Kernelhülle; separate Ledger-/DB-Implementierung, keine rückwärtige Importkante aus dem Kern |
| `crates/pse-core/examples/bench_*` | C; historische Harnesses, nicht unmittelbar faire Gesamtleistungsnachweise |
| `.git` | nicht vorhanden; keine Commit-Historie verfügbar |

## Ausführungskanten statt bloßer Namen

`macro_step → ingest → adapter.canonicalize → SHA-256 verification`

`macro_step → graph.apply_observations → upsert_vertex/upsert_edge → embedding/clustering`

`macro_step → batch_data_helix / helix_pair / mandorla_real → compute_all_metrics → calibration/gate`

`macro_step → inverse_weave → reference operators → candidate JCS/hash → ordered selection`

`macro_step → PatternMemory.lookup / archive dominance → dual_consensus → optional falsify`

`macro_step → build_crystal_with_id → compute_topological_signature → multi_scale_tick → Metatron signature`

`macro_step → archive.append / memory.insert_crystal → morphogenic_update / intrinsic_step`

`Engine.fingerprint / explore → core query / navigator`; `operators → core topology_ops / CrystalAdapter`

Die Namen `Scheduler`, `Swarm`, `Store` und `Engine` in anderen Paketen begründen keine Aufnahme. Ihre tatsächlichen Abhängigkeitskanten sind oben sichtbar.
