# PSE_API

## Integration

`pse = { path = ".../pse" }` bindet die vollständige Bibliothek ein. Sie benötigt keine Datei-/Netzwerkzugriffe und keinen Executor. Die Kopie enthält ihre eigene Workspace-Wurzel und Lockdatei. Als abhängige Bibliothek gilt die Lockdatei des einbettenden Projekts; für reproduzierbare Anwendungen diese ebenfalls festschreiben.

```rust
use pse::{Config, Engine};

let mut engine = Engine::new(Config::preset_streaming())?;
let batch = vec![b"source payload".to_vec()];
let step = engine.step(&batch)?;
if let Some(crystal) = step.crystal {
    // Eine eigene Persistenz-/Transportentscheidung des Aufrufers.
}
# Ok::<(), pse::Error>(())
```

## Öffentliche Oberfläche

| Aufruf | Bedeutung |
|---|---|
| `Engine::new(Config)` | validierter Zustand, Byteadapter mit Quell-ID `pse` |
| `Engine::with_adapter(Config, adapter)` | eigene kanonische Quellen, Zeitstempel und Phasen |
| `step(&[Vec<u8>]) -> Result<Step, Error>` | synchroner, geordneter Batch; `Step { tick, crystal, gate }` |
| `statistics()` | Ticks, Commits, Pattern-Hits, Graphgröße, Beobachtungszahl, Fehlerstatus |
| `crystals()` | unveränderlicher Zugriff auf das Session-Archiv |
| `config()` | unveränderliche Konfiguration |
| `load_memory(&[SemanticCrystal])` | caller-trusted Muster laden; kein Zustandscheckpoint |
| `reset()` | Session leeren, Konfiguration und Adapter erhalten |
| `fingerprint(k)` | Topologie, Resonanz und nächste Muster lesen |
| `explore(steps)` | vorhandenen Resonanzraum deterministisch untersuchen |
| `operators::{compose, dual, bridge, interpolate, query, ...}` | erhaltene Operationen auf Crystal-Ausgaben |
| `verify_crystal(crystal, pinned_versions)` | übernommene Integritäts-/Konsensprüfung mit unten beschriebenem Umfang |

## Adapter und Inputs

`ObservationAdapter: Send + Sync` bietet `source_id` und `canonicalize(raw, context)`. Eine `Observation` enthält logischen Zeitstempel, tatsächliche Quell-ID, Payload, Provenienz, Kontext, SHA-256-Digest, Schemaversion und optionalen `phase_hint`. Der Digest muss SHA-256 der zurückgegebenen Payloadbytes sein. Der Kern berechnet ihn erneut; eine falsche Angabe ist ein Fehler.

Der Standardadapter erzeugt eine einzige Entität, auch wenn JSON-Payloads unterschiedliche `entity`-Felder enthalten. Die Engine interpretiert solche Felder nicht automatisch. Ein vollständiges mehrquelliges Beispiel befindet sich als `SensorAdapter` in `benches/engine.rs`; es wird zugleich in Differentialtests verwendet.

Ein Adapter muss die fachlich gültige Beobachtung liefern: insbesondere endliche Zeit-/Phasenwerte, deterministische Canonicalization und reproduzierbare Provenienz. Stateful Adapter müssen beim Replay ebenfalls zurückgesetzt werden. Nicht-UTF-8-Payloads mit mindestens 16 Bytes besitzen eine übernommene Spezialsemantik: 16-Byte-Blöcke werden als zwei little-endian `u64`-Kantenendpunkte interpretiert. Für beliebige Binärdaten muss der Adapter daher eine geeignete deterministische Kodierung wählen, wenn keine Graphkanten gemeint sind.

## Lifecycle, Fehler und Replay

`new → step* → reset oder Drop`. Der Aufrufer kontrolliert Batchgrößen, Speicherlebensdauer und Parallelität. Kein intern gestarteter Hintergrunddienst. Unterschiedliche Batchgrenzen können unterschiedliche Resultate liefern.

`Ok(None)` auf der Crystal-Ebene ist eine normale Entscheidung: geschlossenes Gate, zu wenig Neuheit, bestehendes Muster oder abgelehnter Konsens. `Error::Configuration` entsteht vor Zustandserzeugung. `Error::Execution` meldet Adapter-/Persistenzfehler; anschließend liefert `step` `Error::Faulted`. Der Tick kann beim ersten Fehler bereits erhöht sein. Nach `reset` kann eine bekannte gültige Eingabefolge erneut abgespielt werden. `reset` setzt den Adapter selbst nicht zurück.

Für Replay eine neue Engine mit identischer Konfiguration und identischem Adapter auf die identische geordnete Folge einschließlich Batchgrenzen anwenden. Volle Crystal-Serialisierungen vergleichen, nicht ausschließlich `crystal_id`. `load_memory` verändert Musterentscheidungen und gehört daher zur Replay-Ausgangslage; es stellt weder Graph noch adaptive Historie wieder her.

## Konfiguration und Garantien

`Config::default()` ist konservativ. `preset_streaming()` aktiviert adaptive Gates und Trägerauswahl. Bestehende Presets bleiben verfügbar; insbesondere senkt `preset_anomaly_detection()` Konsensschwellen. Ein Erfolg mit gelockerten Schwellen ist keine stärkere Sicherheitsgarantie. Der Benchmark verwendet eine ausdrücklich gelockerte Commit-Konfiguration, um den vollständigen Emissionspfad unabhängig von Domänentuning zu messen.

`verify_crystal` prüft den historischen Crystal-Core-Hash, Evidence-Ketten, bekannte Versionsbindungen, Gateflag, Konsenswerte und PoR-Zeitordnung. Es bindet **nicht alle Crystal-Felder kryptographisch** und verwendet beim MCI weiterhin 0,8. Deshalb kann ein mit explizit niedrigeren Konsensschwellen erzeugter Crystal die historische Prüfung nicht bestehen. Diese Funktion eignet sich nicht als vollständige Authentizitätsprüfung von fremden Crystals. Für stärkere Anforderungen muss der Integrator vollständige kanonische Ausgaben authentifizieren und die gewünschte fachliche Policy prüfen.

Keine veränderlichen Graphinternas in der Fassade. Kein automatisches Persistieren, keine versteckten Netzwerkzugriffe, keine garantierte Begrenzung der Historiengröße. Die präzisen Determinismus- und Speichereigenschaften stehen in [PSE_ARCHITECTURE.md](PSE_ARCHITECTURE.md).
