# PSE_PERFORMANCE

## Messaufbau

Gemessen wurde der enthaltene Rust-Kern in drei Zuständen: unveränderte Originalquellen in einer isolierten Original-Workspace-Hülle, reine Extraktion vor Algorithmusänderungen, optimierte eigenständige Engine. Derselbe Harness liegt in `benches/engine.rs`; Referenzquellen und eingefrorene ausführbare Vergleichsprogramme liegen außerhalb der Lieferung unter `_pse_forensics/`.

Hardware: Intel Core 3 100U, acht logische Prozessoren, 8.258.048.000 vom Betriebssystem gemeldete physische Speicherbytes. Windows 11 Build 26200, x86_64/MSVC; rustc 1.95.0, LLVM 22.1.2. Profil: `opt-level=3`, ThinLTO, eine Codegen-Unit, Debugsymbole, keine Overflow-Prüfungen, keine benutzerdefinierten RUSTFLAGS. Alle drei Vergleichsprogramme verwenden das Bench-Profil. Das alte Release-`panic=abort` wird in Test-/Bench-Builds von Cargo nicht angewendet. Maschinenlesbare Details: [environment.json](benchmark-results/environment.json), [hardware.json](benchmark-results/hardware.json), [Dependency-Versionen](docs/dependency-versions.json).

Die drei Programme wurden nacheinander ohne gleichzeitig laufenden Cargo-Build ausgeführt. Keine Kern-Affinität oder Fixierung von CPU-Takt/Energieprofil; Hintergrundlast und thermische Effekte bleiben möglich. Deshalb werden kleine Unterschiede nicht als belastbarer Gewinn bewertet.

## Workloads und Metriken

- Deterministisch vorgefertigte JSON-Beobachtungen mit echten getrennten `source_id`s, logischer Zeit und Phasenhinweis. Eingabeerzeugung liegt außerhalb der Zeitmessung; Adapter-JSON-Parsing, Payload-Kopien und Digestprüfung liegen innerhalb.
- `ingest`: Canonicalization, erneute SHA-256-Prüfung und Graphaktualisierung; kein Makro-Step.
- `gate`: vollständiger Makro-Step unter Standardkonfiguration. Bei mehreren Quellen kann das Gate öffnen und Constraint-/Konsensarbeit anfallen, obwohl kein Crystal emittiert wird. Dies ist **kein isolierter Gate-Mikrobenchmark**.
- `adaptive`: derselbe Ablauf mit Kalibrierung, kleinem Historienfenster und kurzer Aufwärmphase.
- `commit`: acht Quellen, 16 Ticks, explizit gelockerte Gate-/Konsens-/Memory-Schwellen. In jeder Wiederholung entstehen tatsächlich 16 Crystals. Kein Qualitäts- oder Sicherheitsnachweis für diese Benchmarkkonfiguration.
- Fünf Wiederholungen je Fall, jeweils neuer Enginezustand. Initiale Cache- und Codepfadaufwärmung findet vor Messbeginn statt. Mediane der fünf Durchsatzwerte und der jeweils fünf p50/p95/p99-Schätzungen. Latenz gilt für einen ganzen Tick/Batch, nicht für eine einzelne Nachricht.
- Der Commit-Fall enthält nur 16 Latenzwerte je Wiederholung; sein p95/p99 ist damit das jeweilige Maximum. Das ist keine ausreichend große Stichprobe für einen Produktions-Tail-Latency-Claim.
- Durchsatz in Beobachtungen/s, Ticks/s und Eingabebytes/s; Rohwerte enthalten Batchlänge, Graphgröße, Commitzahl und Laufzeit.
- Allokationen werden in einem separaten, nicht zeitlich bewerteten zweiten Durchlauf gezählt. Enthalten sind `alloc` und `realloc`; `allocated_bytes` ist kumuliertes Volumen, kein Netto-Heap. Engine-/Inputkonstruktion sind ausgeschlossen. Der System-Allocator bleibt erhalten; auch im Timingpfad kostet der instrumentierte Wrapper eine deaktivierte Zählerabfrage pro Allokation. Ergebnisse gelten für diesen gemeinsamen Harness.
- Windows-Prozesszähler liefern CPU-Zeit, aktuellen Working Set und Prozess-Peak. Diese umfassen auch Runtime, Eingabepuffer und globale Caches. Peak ist prozessweit kumulativ, kein isolierter Engine-Peak. CPU-Zeit hat hier 15,625-ms-Granularität; Nullwerte kurzer Samples bedeuten **unter Messauflösung**, nicht null CPU-Auslastung.
- Threadvergleich: ein, zwei und vier unabhängige Engines; enthält Threadstart, Join und abschließende vollständige Graphserialisierung/-hashes. Alle Endzustände müssen gleich sein. Keine Aussage zur Parallelisierbarkeit eines einzelnen Zustands.

Keine Hardware-Counter für Cache-Misses, Branch-Misses, Context-Switches oder einzelne CPU-Instruktionen erhoben. Keine Netzwerk-, Broker-, Platten-I/O-, Crash-Recovery- oder Cluster-Messung. Unter anderen Betriebssystemen markiert der portable Harness fehlende Prozesszähler mit `platform_counters=false`; dortige Nullfelder sind nicht als Messung zu interpretieren.

## Messergebnisse

Die folgenden Tabellen werden aus den JSON-Rohdaten erzeugt. „Allokationen/obs“ enthält alle Heap-Anforderungen im jeweiligen Verarbeitungspfad.

| Workload / Batch | Original obs/s | Extrahiert obs/s | Optimiert obs/s | Faktor zum Original | Allokationen/obs alt → neu |
|---|---:|---:|---:|---:|---:|
| ingest / 1 | 1,079,457 | 1,026,901 | 1,137,178 | 1.05× | 13.01 → 11.01 |
| ingest / 8 | 1,006,932 | 1,062,406 | 1,140,248 | 1.13× | 11.55 → 9.55 |
| gate / 1 | 704,531 | 700,135 | 708,785 | 1.01× | 16.01 → 14.01 |
| gate / 8 | 68,209 | 66,654 | 691,320 | 10.14× | 341.68 → 13.43 |
| gate / 32 | 45,100 | 44,980 | 364,517 | 8.08× | 340.66 → 11.47 |
| gate / 65 | 68,253 | 66,202 | 746,309 | 10.93× | 341.49 → 10.82 |
| adaptive / 8 | 314,019 | 341,669 | 726,628 | 2.31× | 49.24 → 11.44 |
| commit / 8 | 12,723 | 13,006 | 16,375 | 1.29× | 479.02 → 150.27 |

| Optimierter Workload / Batch | p50 / p95 / p99 pro Tick, µs | MiB/s Input | CPU, Kernäquivalente | Prozess-RSS, MiB |
|---|---:|---:|---:|---:|
| ingest / 1 | 0.80 / 0.90 / 1.50 | 69.00 | unter Auflösung | 18.06 |
| ingest / 8 | 6.50 / 7.40 / 16.60 | 68.16 | unter Auflösung | 17.92 |
| gate / 1 | 1.30 / 1.50 / 2.10 | 43.01 | unter Auflösung | 18.02 |
| gate / 8 | 10.90 / 12.60 / 24.90 | 41.32 | unter Auflösung | 17.84 |
| gate / 32 | 80.70 / 105.10 / 233.70 | 21.70 | unter Auflösung | 17.64 |
| gate / 65 | 77.90 / 137.60 / 195.60 | 44.75 | unter Auflösung | 20.26 |
| adaptive / 8 | 10.10 / 12.90 / 35.40 | 43.28 | unter Auflösung | 17.96 |
| commit / 8 | 456.90 / 848.70 / 848.70 | 0.96 | unter Auflösung | 17.38 |


## Optimierungen und Engpässe

1. **Konvergierte Referenzregionen:** Die alte Constraint-Suche erzeugte, serialisierte, hashte und deduplizierte Kandidaten, obwohl die anschließende Schleife wegen bereits niedriger Varianz gar nicht ausgeführt wurde. Der Referenzpfad prüft dieselbe Varianz in identischer BTree-Reihenfolge vorab und liefert dieselbe leere Constraint-Liste mit derselben Region. Die allgemeine Custom-Operator-Funktion behält ihre ursprünglichen Auswertungsaufrufe. Eine zusätzliche Differentialprobe vergleicht beide Pfade über 96 Konfigurationen konvergierter und nicht konvergierter Regionen.
2. **Graphnachbarschaften:** Für drei bis 64 Knoten ersetzt eine 512-Byte-Stackmaske wiederholte Kantensuchen bei der Clusterkoeffizientenberechnung. Nachbarmultiplizität, Selbstkanten und Float-Reihenfolge bleiben erhalten. Oberhalb der Grenze bleibt der ursprüngliche Suchpfad. Ein wiederverwendeter Nachbarvektor und direkte Iteration vermeiden temporäre Vektoren je Knoten/Batch. Edge-Upsert sucht bestehende Kanten einmal.
3. **Allokations-/Kopierkosten:** Canonicalization reserviert die bekannte Batchgröße; feste Kaskadenfolgen liegen auf dem Stack. Eine überflüssige Crystal-Kopie für Morphogenese und eine Punktwolkenkopie entfallen. Der bereits vorher leere Operator-Stack wird direkt als leerer Vektor erzeugt.
4. **Deterministische Topologiegrenze:** Keine Systemzeit entscheidet mehr über mathematische Ergebnisse. Bei mehr als 500 Knoten wird der unbenutzte Laplaceoperator vor dem ohnehin vorhandenen Fallback nicht mehr aufgebaut. Dies ist primär eine Korrektheitsänderung; kein gemessener Performanceclaim für große Graphen.

Die größten Gewinne gehören zu homogenen, bereits konvergierten synthetischen Regionen. Auf vielfältigen nicht konvergierten Daten bleibt Kandidatensuche notwendig. Im Commit-Pfad dominieren weiterhin Spektral-/Mehrskalenanalyse, kanonische Signaturen und Serialisierung. Der persistente Verlauf wächst weiter mit der Zahl der Beobachtungen. Die Optimierung verspricht keine pauschale Verzehnfachung für beliebige Daten.

## Historische Aussagen

`docs/OVERVIEW.md` des Ausgangsbestands nennt bis 2,07 Millionen Beobachtungen/s für Observe-only und bis 659.000/s für einen Gate-Pfad auf kleinen synthetischen Graphen. Diese Zahlen wurden nicht als Ausgangsmessung übernommen. `bench_core` erzeugt zwar mehrere JSON-`entity`-Werte, verwendet aber einen Passthrough-Adapter mit fester Quell-ID; die tatsächliche Graphgröße ist deshalb kritisch zu prüfen.

In den durchsuchten Quelltexten, Markdown-Dateien und Messartefaktnamen wurde kein belastbarer PSE/Kafka-Vergleich gefunden. Die gefundenen Durchsatzclaims betreffen keine äquivalente Kafka-Semantik mit Partitionierung, Netztransport, Persistenz und Replikation. Aus den hier vorliegenden Messungen folgt daher keine Kafka-Überlegenheit.

## Reproduktion und Prüfnachweise

```sh
cargo test --locked --workspace --release
cargo clippy --locked --workspace --all-targets -- -D warnings
cargo bench --locked --bench engine > optimized.json
# Vollständige Verhaltensfingerprints ohne Zeitmessung:
cargo bench --locked --bench engine -- golden
```

Die Originalfixture unter `tests/fixtures/original.json` stammt aus den Originalquellen und darf nicht einfach mit optimierten Ausgaben ersetzt werden, um Unterschiede verschwinden zu lassen. Die Vergleichstests enthalten echte, nicht leere Commitfolgen.

Prüfstand dieser Lieferung: 539 Originaltests vor der Änderung; 434 Tests inklusive Dokumentationsbeispielen in der endgültigen kleineren Hülle; keine Fehler. Clippy mit Warnungen als Fehler erfolgreich. Isolierter Release-Build samt Ausführung des Stream-Beispiels erfolgreich. Der neue Zeitbudget-Regressionstest scheitert erwartungsgemäß im Original und besteht in der Extraktion. Logs und alle Rohmessungen liegen in `benchmark-results/`.

## Skalierung unabhängiger Instanzen

| Instanzen | Original obs/s | Optimiert obs/s | Optimiert CPU-Zeit / Wall-Zeit |
|---|---:|---:|---:|
| 1 | 55,853 | 191,945 | 0.03125 s / 0.04268 s |
| 2 | 80,728 | 303,941 | 0.12500 s / 0.05391 s |
| 4 | 97,498 | 427,444 | 0.25000 s / 0.07666 s |

Eine Skalierungsmessung pro Stufe und Threadzahl; keine Konfidenzintervalle. Diese Zahlen enthalten bewusst mehr Arbeit als die obigen Tick-Latenzen.
