# Mechanischer Quellenvergleich der nativen Cache-Erweiterung

Stand: 2026-09-26T19:18:41.018713+00:00. Vergleich mit dem zuvor ausgelieferten `Gabriel_Research_Project.zip`, vor dessen geplanter Neuerstellung. Geprüft wurden native `.rs`-, `.toml`- und `.lock`-Dateien sowie sämtliche Pythondateien unter `gabriel_runtime/`. Buildverzeichnisse und Manuskripte sind ausgeschlossen. Es wurden keine Builds oder Tests ausgeführt.

Ergebnis: **7 geänderte und 7 neue native Dateien**, keine entfernten Dateien. Darunter sind drei neue eingefrorene Benchmarkkopien. **Alle 10 Python-Laufzeitdateien sind bytegleich**; es gibt dort keine neuen oder entfernten Dateien.

## Geänderte Dateien

- `native_pse/Cargo.toml`: Feature-Weiterleitung; Releaseprofil von ThinLTO auf lto=false geändert.
- `native_pse/crates/pse-core/Cargo.toml`: Optionales Memoisierungsfeature.
- `native_pse/crates/pse-core/src/metatron_attach.rs`: Featureabhängige Auswahl der Signaturfunktion und Kommentare.
- `native_pse/crates/pse-metatron/Cargo.toml`: Optionales Memoisierungsfeature.
- `native_pse/crates/pse-metatron/src/indexed_signature.rs`: Extraktion gemeinsamer Validierung und Berechnung; Berechnungssuffix einschließlich Tests unverändert.
- `native_pse/crates/pse-metatron/src/lib.rs`: Bedingte Bereitstellung des Memoisierungsmoduls.
- `native_pse/crates/pse-types/src/lib.rs`: Ausschließlich Leerzeilen und Zeilen-/Dokumentationskommentare geändert.

## Neue Dateien

- `native_pse/benchmark-results/indexed_engine/Cargo.lock`.
- `native_pse/benchmark-results/indexed_engine/Cargo.toml`.
- `native_pse/benchmark-results/indexed_engine/executed/frozen_Cargo.lock` — eingefrorene Benchmarkkopie.
- `native_pse/benchmark-results/indexed_engine/executed/frozen_Cargo.toml` — eingefrorene Benchmarkkopie.
- `native_pse/benchmark-results/indexed_engine/executed/frozen_main.rs` — eingefrorene Benchmarkkopie.
- `native_pse/benchmark-results/indexed_engine/src/main.rs`.
- `native_pse/crates/pse-metatron/src/memoized_signature.rs`.

## Erhaltene Berechnungen und Grenzen

Die vollständigen Quelldateien `spectrum.rs`, `platonic.rs`, `embed.rs`, `complement.rs`, `group.rs`, `scan.rs` und `small_signature.rs` sind gegenüber dem Archiv bytegleich. Damit sind insbesondere die ursprünglichen Gleitkomma- und Teilgraphenroutinen sowie der gepackte Referenzpfad unverändert. In `indexed_signature.rs` ist zusätzlich der gesamte Suffix ab `let mut bits = 0;`, einschließlich Berechnung und nachfolgender Tests, bytegleich.

Das historische Fixture `native_pse/tests/fixtures/original.json` ist ebenfalls bytegleich. Das bestätigt seine unveränderte Aufbewahrung, nicht sein Bestehen in der aktuellen Umgebung. Die Änderung `lto=false` im Root-Manifest ist ausdrücklich eine zusätzliche Buildprofiländerung.

Der Vergleich belegt den Umfang der Quellenänderungen; er ersetzt weder Funktionsprüfungen noch einen Äquivalenzbeweis oder eine Leistungsmessung. Native Python-Benchmarkhelfer gehören nicht zum angeforderten Erweiterungssatz. Einzelhashes, Differenzstatistiken, Vergleichsumfang und die beiden übereinstimmenden Python-Manifesthashes stehen in `native_cache_source_review.json`.
