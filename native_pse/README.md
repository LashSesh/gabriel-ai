# PSE — Post-Symbolic Engine

Eigenständige Rust-Bibliothek für die deterministische Verarbeitung von Beobachtungsbatches zu topologischen Zuständen und Semantic Crystals. Kein Server, keine Datenbank, kein Agent-Framework.

```sh
cargo build --locked --release
cargo test --locked --workspace
cargo bench --locked --bench engine
cargo run --locked --release --example stream
```

Diese Befehle werden **in diesem Verzeichnis** ausgeführt. Der Ordner lässt sich einschließlich `crates/`, `Cargo.toml`, `Cargo.lock` und `LICENSE` an einen beliebigen Ort kopieren. Der übergeordnete Quellbestand ist keine Build-Abhängigkeit. Rust 1.89 oder neuer; tatsächlich geprüft mit Rust 1.95.0 auf Windows x86-64/MSVC. Ein Linker und einmaliger Zugriff auf die festgeschriebenen Cargo-Abhängigkeiten werden benötigt.

```toml
[dependencies]
pse = { path = "path/to/pse" }
```

```rust
use pse::{Config, Engine};

fn main() -> Result<(), pse::Error> {
    let mut engine = Engine::new(Config::preset_streaming())?;
    let result = engine.step(&[b"sample".to_vec()])?;
    println!("tick={}, committed={}", result.tick, result.crystal.is_some());
    Ok(())
}
```

Der Standardadapter behandelt alle Bytes als dieselbe Quelle. Für mehrere Entitäten, logische Zeitstempel und semantische Phasen dient `ObservationAdapter`. Die Standard-Gates sind konservativ; aus einem einzelnen Batch muss kein Crystal entstehen. Die Engine ist ein topologischer Analyse- und Zustandskern; ihre Ingestion-Zahlen sind kein Vergleich mit einem persistenten Nachrichtenbroker.

Dokumentation:

- [Architektur und Invarianten](PSE_ARCHITECTURE.md)
- [Extraktion, Grenze und Befunde](PSE_EXTRACTION_REPORT.md)
- [Messverfahren und Ergebnisse](PSE_PERFORMANCE.md)
- [Einbettung und API](PSE_API.md)
- [Vollständige Paketkartierung](docs/REPOSITORY_MAP.md)

Die Tests enthalten unveränderte übernommene Kerneltests, Gegenproben für Fehlerpfade sowie vollständige Ausgaben und Zustandsfingerprints aus der Originalimplementierung. Die große Differentialprobe enthält bewusst teure kanonische Graphanalysen und kann im Debug-Build mehrere Minuten benötigen.
