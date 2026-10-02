# PSE_EXTRACTION_REPORT

## Ausgangslage und forensische Methode

Der entpackte Quellbestand umfasst 1.115 inventarisierte Dateien und 125 Rust-Pakete einschließlich des separaten vendorten Subsystems. Es gibt kein `.git`-Verzeichnis; Commits oder gelöschte historische Varianten konnten daher nicht rekonstruiert werden. Dateigrößen und SHA-256-Hashes wurden vor Änderungen gesichert.

Untersucht wurden sämtliche Cargo-Manifeste, interne und externe Abhängigkeitskanten, alle Rust-Quellpfade, Aufrufstellen des Makro-Steps und seine ausgeführten Komponenten, Runtime-/Concurrency-/FFI-Merkmale, Tests, Benchmarks, Dokumentation und Artefaktnamen. Die Paketkartierung ist eine vollständige statische Klassifikation; sie ist keine Behauptung, jede Funktion der ausgeschlossenen Anwendungen dynamisch ausgeführt zu haben.

Die Auswahl folgt dem tatsächlichen Ablauf `ObservationAdapter → ingest → PersistentGraph::apply_observations → macro_step → inverse_weave → dual_consensus → build_crystal_with_id → Topologie/Multiscale/Metatron → Archiv/Memory → morphogenic_update`. Rückwärtige Aufrufstellen liegen in Domänenadaptern, Python/WASM-Bindings, Gateway, CLI, Traversal-Brücke und Produktwerkzeugen. Keiner dieser Aufrufer ist eine notwendige Abhängigkeit dieses Ablaufs.

Besonders wichtig: `crates/pse` war eine breite Sammelfassade einschließlich SQLite und Infinity-Ledger. Sie definiert nicht die minimale Engine-Grenze. `pse-scheduler` ist im untersuchten Makro-Step nicht aufgerufen. Träger- und Zustandsfortschaltung liegen synchron im Kern. `pse-net` ist eine optionale Transportbrücke; der lokale Kernel benötigt sie nicht.

## Klassifikation und geschlossene Grenze

Die vollständige A–F-Zuordnung je Paket steht in [docs/REPOSITORY_MAP.md](docs/REPOSITORY_MAP.md), maschinenlesbare Daten in [docs/packages.json](docs/packages.json).

- **A/Core:** Orchestrierung, gemeinsames Datenmodell, Constraint-Suche, Kaskade, Morphogenese, Topologie, Multiscale, Evidence und Memory.
- **B/Runtime:** Graph-/Historienhaltung; außerhalb der Hülle auch optionale Transport- und Scheduling-Infrastruktur.
- **C/Supporting:** kanonische Graphsignaturen, Katalogunterstützung und Navigator. Tatsächlich benötigte Unterstützung bleibt erhalten.
- **D/Application:** `kosmo-*`, Domänenadapter, NxAlien, Traversal-/Eval-/PhaseMatrix-Schichten, Server/CLIs, Bindings und Weboberfläche.
- **E/Legacy innerhalb der Extraktionsgrenze:** unaufgerufener `DomainAdapter`, doppelte `EngineFilter`-Fassade und alte Replay-Hilfen mit unzureichender Aussagekraft; ersetzt oder nicht übernommen.
- **F/Unknown:** eigenständige vendorte Komponenten und nicht zur ausgeführten Hülle gehörende Artefakte bleiben im Ausgangsbestand erhalten. Keine Unknown-Komponente wurde dort gelöscht.

Die ursprüngliche manifestseitige Hülle von `pse-core`, einschließlich Entwicklungs- und optionaler Abhängigkeiten, umfasst 20 interne Pakete. Die eigenständige Hülle enthält zwölf implementierende Pakete und eine neue öffentliche Fassade. Alle Pfadabhängigkeiten bleiben innerhalb `pse/`. Das ist eine nachvollziehbar geschlossene Funktionsgrenze, kein mathematischer Beweis eines global minimalen Quelltextes.

## Übernommen

Der Rust-Kern, sämtliche lokalen mathematischen Schritte, adaptive Kalibrierung, optionale Falsifikation, Speicherung von Verlauf und Crystals im Arbeitsspeicher, cross-session PatternMemory, kanonische Metatron-Signaturen, Multiscale, Resonanzabfrage/-erkundung sowie Crystal-Komposition, Dualisierung, Interpolation und Rückführung. Zugehörige Unit-/Integrationstests bleiben erhalten, soweit sie die übernommene Hülle betreffen.

Die bestehende Sprache, Float-Verfahren, Datenmodelle, Hashverfahren und beobachteten Batch-/Tick-Semantiken bleiben erhalten. Keine neue Sprache, FFI-Schnittstelle oder Netzwerkarchitektur.

## Nicht übernommen beziehungsweise ersetzt

| Bestandteil im Ursprung | Entscheidung und Evidenz |
|---|---|
| breite `pse`-Sammelfassade | ersetzt durch `Engine`, `Step`, Konfiguration, Fehler und Ausgabeoperationen |
| `pse-store`, SQLite, HTTP/WebSocket, CLI, WASM/Python | eigenständige Integrationsschichten; kein Rückwärtspfad aus dem Kernel |
| `pse-net` und `swarm`-Feature-Brücken | externe, zeitabhängige Eingänge und Transport; aus lokaler Engine entfernt |
| `pse-capsule`, Manifest, Registry, Scheduler, PMHD, Swarm | im `pse-core`-Manifest, aber keine lokalen produktiven Aufrufe im analysierten Kern; viele nur in `bench_full` |
| `pse-replay` | hashte denselben Descriptor zweimal bzw. verglich nur IDs; vollständige Replay-/Zustandsprüfungen ersetzen diesen Nachweis |
| `DomainAdapter` | keine Aufrufstelle im Kernel; die tatsächlich genutzte Grenze heißt `ObservationAdapter` |
| `EngineFilter` | doppelte Wrapperlogik; neue Fassade mit definierten Fehlern, Reset und aktuellen Gate-Snapshots |
| Metatron `analysis`, `export`, `scaffold` | Forschungsauswertung/Dateiexport bzw. ungenutzter Wrapper; keine eingehenden Aufrufe aus der Hülle |
| Metatron `closure/` | zusätzliche Pipeline für NCTCS/PhaseMatrix/Stitch/TPT/Eval-Artefakte; keine Engine-Aufrufkante |
| Chrono sowie weitere ungenutzte direkte Dependencies | keine Quellreferenz in benötigter Hülle; entfernt |
| alte Produktmetadaten und Compliance-Behauptungen | entfernt; Lizenz und Urhebervermerk bleiben erhalten |

Der Originalbestand wurde nicht aufgeräumt oder gelöscht. Die eigenständige Lieferung ist ausschließlich `pse/`; `_pse_forensics/` enthält die überprüfbare Referenz, Arbeitsprotokolle und Vergleichsbinaries und gehört nicht zur Bibliothek.

## Bewusste Semantikänderungen

Die einzige beabsichtigte Änderung im mathematischen Ausführungspfad ist die Entfernung zeitabhängiger Topologie-Abbrüche. Ein Regressionstest scheitert im Original reproduzierbar: `budget_ms=0` ergibt andere Propagationswerte als ein großzügiges Budget. In der neuen Engine entscheidet feste Arbeitsmenge; das Konfigurationsfeld bleibt aus Kompatibilitätsgründen wirkungslos. Normale, rechtzeitig abgeschlossene Originalfälle bleiben die Golden-Referenz.

Die neue Fassade validiert Konfigurationen vor Allokation des Zustands, meldet bei frühen Rückgaben keinen veralteten Gate-Snapshot und sperrt nach einem Ausführungsfehler bis `reset`. Bestehende Kern-Fehler können bereits einen Tick oder Teilzustand verändert haben; diese Grenze wird nicht als Transaktion ausgegeben.

## Überprüfung und offene Befunde

539 Originaltests bestanden vor Optimierungen. Zusätzlich sichern Original-Goldens vollständige Crystal-Inhalte, Graphknoten/-kanten, Einbettungen, Payloadhistorien, Tensorzustände, Gates, Träger, Morphogenese, Kalibrierung und Multiscale. Enthalten sind echte Commits, Falsifikation, Cooldown, Metatron-Träger, 64/65-Knoten-Grenze und 16 deterministisch erzeugte binäre Graphfolgen. Die reine Extraktion stimmt mit diesen Goldens überein.

Bekannte Originalgrenzen wurden sichtbar dokumentiert: unbeschränkte Historien, ungefähre Kapazitätsprüfung, partielle Crystal-ID-Bindung, feste `mci >= 0.8` in `verify_crystal` trotz konfigurierbarer Emissionsschwelle, ungenutzte Retention-/Window-/Descriptor-Felder und die Bedingung `!num_carriers == 0` im Migrationsmetrikpfad. Letztere ist bitweises NOT und keine korrekte Nichtnullprüfung; sie wurde hier zur Verhaltenserhaltung nicht stillschweigend geändert. Eine weitere fachliche Korrektur würde gesonderte Semantiktests und neue Vergleichsmessungen benötigen.

Die API behauptet daher weder vollständige kryptographische Attestierung noch eine allgemeine Echtzeit-, Sicherheits- oder clusterweite Determinismusgarantie. Die empirisch geprüften Eigenschaften und Messgrenzen stehen in den Architektur- und Performancedokumenten.
