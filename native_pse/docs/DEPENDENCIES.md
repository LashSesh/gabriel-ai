# Dependency-Audit

Alle internen Abhängigkeiten sind in PSE_ARCHITECTURE.md und der Paketkartierung begründet. Die Tabelle unten enthält jede aufgelöste externe Dependency der eigenständigen Cargo-Hülle, einschließlich plattformabhängiger transitiver Pakete. Die Anzahl ist keine Zahl gleichzeitig geladener DLLs.

| Dependency | Rolle / Notwendigkeit | Eingehende Abhängigkeiten |
|---|---|---|
| `approx 0.5.1` | **transitiv erforderlich**: durch die rechts genannten festgeschriebenen Dependencies eingebunden; keine zusätzliche direkte Engine-Anforderung | nalgebra, simba |
| `autocfg 1.5.0` | **transitiv erforderlich**: durch die rechts genannten festgeschriebenen Dependencies eingebunden; keine zusätzliche direkte Engine-Anforderung | matrixmultiply, num-traits |
| `block-buffer 0.12.0` | **transitiv erforderlich**: durch die rechts genannten festgeschriebenen Dependencies eingebunden; keine zusätzliche direkte Engine-Anforderung | digest |
| `bytemuck 1.25.0` | **transitiv erforderlich**: durch die rechts genannten festgeschriebenen Dependencies eingebunden; keine zusätzliche direkte Engine-Anforderung | safe_arch, wide |
| `cfg-if 1.0.4` | **transitiv erforderlich**: durch die rechts genannten festgeschriebenen Dependencies eingebunden; keine zusätzliche direkte Engine-Anforderung | sha2 |
| `const-oid 0.10.2` | **transitiv erforderlich**: durch die rechts genannten festgeschriebenen Dependencies eingebunden; keine zusätzliche direkte Engine-Anforderung | digest |
| `cpufeatures 0.3.0` | **transitiv erforderlich**: durch die rechts genannten festgeschriebenen Dependencies eingebunden; keine zusätzliche direkte Engine-Anforderung | sha2 |
| `crossbeam-deque 0.8.6` | **transitiv erforderlich**: durch die rechts genannten festgeschriebenen Dependencies eingebunden; keine zusätzliche direkte Engine-Anforderung | rayon-core |
| `crossbeam-epoch 0.9.18` | **transitiv erforderlich**: durch die rechts genannten festgeschriebenen Dependencies eingebunden; keine zusätzliche direkte Engine-Anforderung | crossbeam-deque |
| `crossbeam-utils 0.8.21` | **transitiv erforderlich**: durch die rechts genannten festgeschriebenen Dependencies eingebunden; keine zusätzliche direkte Engine-Anforderung | crossbeam-deque, crossbeam-epoch, rayon-core |
| `crypto-common 0.2.1` | **transitiv erforderlich**: durch die rechts genannten festgeschriebenen Dependencies eingebunden; keine zusätzliche direkte Engine-Anforderung | digest |
| `digest 0.11.3` | **transitiv erforderlich**: durch die rechts genannten festgeschriebenen Dependencies eingebunden; keine zusätzliche direkte Engine-Anforderung | sha2 |
| `either 1.15.0` | **transitiv erforderlich**: durch die rechts genannten festgeschriebenen Dependencies eingebunden; keine zusätzliche direkte Engine-Anforderung | rayon |
| `equivalent 1.0.2` | **transitiv erforderlich**: durch die rechts genannten festgeschriebenen Dependencies eingebunden; keine zusätzliche direkte Engine-Anforderung | indexmap |
| `fixedbitset 0.5.7` | **transitiv erforderlich**: durch die rechts genannten festgeschriebenen Dependencies eingebunden; keine zusätzliche direkte Engine-Anforderung | petgraph |
| `foldhash 0.1.5` | **transitiv erforderlich**: durch die rechts genannten festgeschriebenen Dependencies eingebunden; keine zusätzliche direkte Engine-Anforderung | hashbrown |
| `glam 0.30.10` | **transitiv erforderlich**: durch die rechts genannten festgeschriebenen Dependencies eingebunden; keine zusätzliche direkte Engine-Anforderung | nalgebra |
| `glam 0.31.1` | **transitiv erforderlich**: durch die rechts genannten festgeschriebenen Dependencies eingebunden; keine zusätzliche direkte Engine-Anforderung | nalgebra |
| `glam 0.32.1` | **transitiv erforderlich**: durch die rechts genannten festgeschriebenen Dependencies eingebunden; keine zusätzliche direkte Engine-Anforderung | nalgebra |
| `glam 0.33.1` | **transitiv erforderlich**: durch die rechts genannten festgeschriebenen Dependencies eingebunden; keine zusätzliche direkte Engine-Anforderung | nalgebra |
| `hashbrown 0.15.5` | **transitiv erforderlich**: durch die rechts genannten festgeschriebenen Dependencies eingebunden; keine zusätzliche direkte Engine-Anforderung | petgraph |
| `hashbrown 0.17.0` | **transitiv erforderlich**: durch die rechts genannten festgeschriebenen Dependencies eingebunden; keine zusätzliche direkte Engine-Anforderung | indexmap |
| `hybrid-array 0.4.11` | **transitiv erforderlich**: durch die rechts genannten festgeschriebenen Dependencies eingebunden; keine zusätzliche direkte Engine-Anforderung | block-buffer, crypto-common |
| `indexmap 2.14.0` | **transitiv erforderlich**: durch die rechts genannten festgeschriebenen Dependencies eingebunden; keine zusätzliche direkte Engine-Anforderung | petgraph |
| `itoa 1.0.18` | **transitiv erforderlich**: durch die rechts genannten festgeschriebenen Dependencies eingebunden; keine zusätzliche direkte Engine-Anforderung | serde_json |
| `libc 0.2.186` | **transitiv erforderlich**: durch die rechts genannten festgeschriebenen Dependencies eingebunden; keine zusätzliche direkte Engine-Anforderung | cpufeatures |
| `matrixmultiply 0.3.10` | **transitiv erforderlich**: durch die rechts genannten festgeschriebenen Dependencies eingebunden; keine zusätzliche direkte Engine-Anforderung | nalgebra |
| `memchr 2.8.0` | **transitiv erforderlich**: durch die rechts genannten festgeschriebenen Dependencies eingebunden; keine zusätzliche direkte Engine-Anforderung | serde_json |
| `nalgebra 0.35.0` | **fundamental / Performance**: Eigenwertzerlegung und feste Matrizen in Topologie und Kanonisierung | pse-metatron, pse-topology |
| `nalgebra-macros 0.3.0` | **transitiv erforderlich**: durch die rechts genannten festgeschriebenen Dependencies eingebunden; keine zusätzliche direkte Engine-Anforderung | nalgebra |
| `num-bigint 0.4.6` | **transitiv erforderlich**: durch die rechts genannten festgeschriebenen Dependencies eingebunden; keine zusätzliche direkte Engine-Anforderung | num-rational |
| `num-complex 0.4.6` | **transitiv erforderlich**: durch die rechts genannten festgeschriebenen Dependencies eingebunden; keine zusätzliche direkte Engine-Anforderung | nalgebra, simba |
| `num-integer 0.1.46` | **transitiv erforderlich**: durch die rechts genannten festgeschriebenen Dependencies eingebunden; keine zusätzliche direkte Engine-Anforderung | num-bigint, num-rational |
| `num-rational 0.4.2` | **transitiv erforderlich**: durch die rechts genannten festgeschriebenen Dependencies eingebunden; keine zusätzliche direkte Engine-Anforderung | nalgebra |
| `num-traits 0.2.19` | **transitiv erforderlich**: durch die rechts genannten festgeschriebenen Dependencies eingebunden; keine zusätzliche direkte Engine-Anforderung | approx, nalgebra, num-bigint, num-complex, num-integer, num-rational, ordered-float, simba |
| `once_cell 1.21.4` | **transitiv erforderlich**: durch die rechts genannten festgeschriebenen Dependencies eingebunden; keine zusätzliche direkte Engine-Anforderung | tracing-core |
| `ordered-float 5.3.0` | **Kompatibilität**: IntrinsicTime/TickSize-Typen im übernommenen Modell; keine neue HashMap-Semantik | pse-types |
| `petgraph 0.8.3` | **fundamental**: gerichtetes Graphlayout und Nachbarschaftsoperationen; Austausch wäre eine eigene Semantik-/Performancearbeit | pse-graph |
| `pin-project-lite 0.2.17` | **transitiv erforderlich**: durch die rechts genannten festgeschriebenen Dependencies eingebunden; keine zusätzliche direkte Engine-Anforderung | tracing |
| `proc-macro2 1.0.106` | **transitiv erforderlich**: durch die rechts genannten festgeschriebenen Dependencies eingebunden; keine zusätzliche direkte Engine-Anforderung | nalgebra-macros, quote, serde_derive, syn, thiserror-impl, tracing-attributes |
| `quote 1.0.45` | **transitiv erforderlich**: durch die rechts genannten festgeschriebenen Dependencies eingebunden; keine zusätzliche direkte Engine-Anforderung | nalgebra-macros, serde_derive, syn, thiserror-impl, tracing-attributes |
| `rand 0.8.6` | **transitiv erforderlich**: durch die rechts genannten festgeschriebenen Dependencies eingebunden; keine zusätzliche direkte Engine-Anforderung | ordered-float |
| `rand_core 0.6.4` | **transitiv erforderlich**: durch die rechts genannten festgeschriebenen Dependencies eingebunden; keine zusätzliche direkte Engine-Anforderung | rand |
| `rawpointer 0.2.1` | **transitiv erforderlich**: durch die rechts genannten festgeschriebenen Dependencies eingebunden; keine zusätzliche direkte Engine-Anforderung | matrixmultiply |
| `rayon 1.12.0` | **Performance / Supporting**: parallele Katalogenumeration der bestehenden PatternMemory-Unterstützung; nicht im normalen Makro-Step | pse-metatron |
| `rayon-core 1.13.0` | **transitiv erforderlich**: durch die rechts genannten festgeschriebenen Dependencies eingebunden; keine zusätzliche direkte Engine-Anforderung | rayon |
| `ryu-js 0.2.2` | **transitiv erforderlich**: durch die rechts genannten festgeschriebenen Dependencies eingebunden; keine zusätzliche direkte Engine-Anforderung | serde_jcs |
| `safe_arch 1.0.0` | **transitiv erforderlich**: durch die rechts genannten festgeschriebenen Dependencies eingebunden; keine zusätzliche direkte Engine-Anforderung | wide |
| `serde 1.0.228` | **fundamental**: Datenmodell, Replay und kanonische Serialisierung | ordered-float, petgraph, pse-cascade, pse-core, pse-evidence, pse-extract, pse-memory, pse-metatron, pse-navigator, pse-scale, pse-topology, pse-types, rand, rand_core, serde_jcs, serde_json |
| `serde_core 1.0.228` | **transitiv erforderlich**: durch die rechts genannten festgeschriebenen Dependencies eingebunden; keine zusätzliche direkte Engine-Anforderung | serde, serde_json |
| `serde_derive 1.0.228` | **transitiv erforderlich**: durch die rechts genannten festgeschriebenen Dependencies eingebunden; keine zusätzliche direkte Engine-Anforderung | serde, serde_core |
| `serde_jcs 0.2.0` | **fundamental**: kanonische Bytes als Bestandteil bestehender Inhaltsadressen | pse-metatron, pse-types |
| `serde_json 1.0.150` | **fundamental**: JSON-Adapter, Strukturserialisierung und gespeicherte Typen | pse, pse-core, pse-metatron, pse-navigator, pse-scale, pse-types, serde_jcs |
| `sha2 0.11.0` | **fundamental**: Digestprüfung, Crystal-IDs und kanonische Graphhashes | pse-memory, pse-metatron, pse-types |
| `simba 0.10.0` | **transitiv erforderlich**: durch die rechts genannten festgeschriebenen Dependencies eingebunden; keine zusätzliche direkte Engine-Anforderung | nalgebra |
| `syn 2.0.117` | **transitiv erforderlich**: durch die rechts genannten festgeschriebenen Dependencies eingebunden; keine zusätzliche direkte Engine-Anforderung | nalgebra-macros, serde_derive, thiserror-impl, tracing-attributes |
| `thiserror 2.0.18` | **Convenience**: typisierte Fehler und Display/Error-Implementierungen; kein Laufzeitframework | pse, pse-cascade, pse-constraint, pse-core, pse-evidence, pse-extract, pse-graph, pse-metatron |
| `thiserror-impl 2.0.18` | **transitiv erforderlich**: durch die rechts genannten festgeschriebenen Dependencies eingebunden; keine zusätzliche direkte Engine-Anforderung | thiserror |
| `tracing 0.1.44` | **Supporting**: erhaltene deaktivierbare Diagnostik; kein Subscriber und keine Logging-Runtime eingebaut | pse-core, pse-extract, pse-topology |
| `tracing-attributes 0.1.31` | **transitiv erforderlich**: durch die rechts genannten festgeschriebenen Dependencies eingebunden; keine zusätzliche direkte Engine-Anforderung | tracing |
| `tracing-core 0.1.36` | **transitiv erforderlich**: durch die rechts genannten festgeschriebenen Dependencies eingebunden; keine zusätzliche direkte Engine-Anforderung | tracing |
| `typenum 1.20.0` | **transitiv erforderlich**: durch die rechts genannten festgeschriebenen Dependencies eingebunden; keine zusätzliche direkte Engine-Anforderung | hybrid-array, nalgebra |
| `unicode-ident 1.0.24` | **transitiv erforderlich**: durch die rechts genannten festgeschriebenen Dependencies eingebunden; keine zusätzliche direkte Engine-Anforderung | proc-macro2, syn |
| `wide 1.5.0` | **transitiv erforderlich**: durch die rechts genannten festgeschriebenen Dependencies eingebunden; keine zusätzliche direkte Engine-Anforderung | simba |
| `zmij 1.0.21` | **transitiv erforderlich**: durch die rechts genannten festgeschriebenen Dependencies eingebunden; keine zusätzliche direkte Engine-Anforderung | serde_json |

## Entfernte Abhängigkeiten

Tokio, HTTP/WebSocket-Stacks, SQLite, Reqwest, AES-GCM/HKDF-Kapseln, Chrono und Produkt-/Ledger-Pakete sind nicht Teil der neuen direkten Engine-Hülle. Serde, SHA-256, Petgraph und Nalgebra wurden nicht durch ungemessene Eigenimplementierungen ersetzt.

Rayon lässt sich nur gemeinsam mit dem separaten Katalogteil der internen PatternMemory-Unterstützung abtrennen. Dieser Teil wurde konservativ erhalten; die laufende Beobachtungspipeline nutzt keinen Rayon-Pool. Thiserror ist ersetzbare Quelltext-Convenience, bringt aber keine pro-Operation-Frameworkkosten mit.
