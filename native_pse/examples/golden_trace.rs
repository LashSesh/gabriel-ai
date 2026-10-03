//! Golden trace with per-component state digests (ADR-19 determinism study).
//!
//! Prints the same whole-state digests as `benches/engine.rs golden` (so the output can be
//! compared with `tests/fixtures/original.json`) and, in addition, a digest per state component
//! for every tick, so that two executions (another platform, another arithmetic, a perturbed
//! transcendental function) can be localized to the component and tick where they first differ.
#![allow(dead_code)]
#[path = "../benches/engine.rs"]
mod harness;

use pse_core::{macro_step, GlobalState};
use pse_graph::PersistentGraph;
use pse_types::content_address_raw;
use serde_json::{json, Value};

fn hash(value: &Value) -> String {
    content_address_raw(&serde_json::to_vec(value).unwrap())
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
}

/// Identical to the harness's private `graph_snapshot` (kept verbatim so the whole-state digest
/// equals the golden fixture's).
fn graph_snapshot(g: &PersistentGraph) -> Value {
    let nodes: Vec<_> = g
        .graph
        .node_weights()
        .map(|v| (v.id, v.active, v.first_seen, v.last_seen, v.activation_count))
        .collect();
    let edges: Vec<_> = g
        .graph
        .raw_edges()
        .iter()
        .map(|e| (e.source().index(), e.target().index(), &e.weight))
        .collect();
    let history: Vec<_> = g.history.iter().map(|r| (r.commit_index, r.digest, r.timestamp)).collect();
    let tensor: Vec<_> = g.tensor.iter().map(|(id, t)| (id, &t.snapshots, &t.timestamps)).collect();
    json!({"nodes":nodes,"edges":edges,"embedding":g.embedding,"history":history,
        "tensor":tensor,"hot":g.hot.data,"warm":g.warm.data,"cold":g.cold.data,
        "tick":g.commit_index})
}

fn main() {
    let mut cases = Vec::new();
    for (mode, entities, ticks) in [
        ("gate", 1, 12),
        ("gate", 8, 12),
        ("gate", 64, 3),
        ("gate", 65, 3),
        ("commit", 8, 6),
        ("commit", 3, 3),
        ("adaptive", 8, 24),
        ("falsify", 8, 3),
        ("cooldown", 8, 9),
        ("metatron", 8, 3),
    ] {
        let c = harness::configuration(mode);
        let mut s = GlobalState::new(&c);
        let mut traces = Vec::new();
        for batch in harness::batches(entities, ticks) {
            let crystal = macro_step(&mut s, &batch, &c, &harness::SensorAdapter).unwrap();
            let components = json!({
                "graph": graph_snapshot(&s.graph),
                "gate": s.last_gate, "h5": s.h5_state, "prev": s.prev_embeddings, "phase": s.phase_ladder,
                "active": s.active_carrier, "helix": s.last_data_helix, "t2": s.t2, "tick": s.commit_index,
                "status": format!("{:?}", s.engine_state), "consensus": s.consensus.last_result,
                "archive": s.archive.crystals(), "pattern_hits": s.pattern_hits, "constraints": s.last_constraint_count,
                "scale": format!("{:?}", s.scale_state), "morph": format!("{:?}", s.morph), "adaptive": format!("{:?}", s.adaptive)});
            let mut digests = serde_json::Map::new();
            for (name, value) in components.as_object().unwrap() {
                digests.insert(name.clone(), Value::String(hash(value)));
            }
            traces.push(json!({"state": hash(&components), "crystal": crystal.as_ref().map(|c| hash(&json!(c))),
                "tick": s.commit_index, "commits": s.crystals_committed, "components": digests,
                "gate_values": s.last_gate.as_ref().map(|g| json!({"d": g.d, "q": g.q, "r": g.r, "g": g.g, "j": g.j, "p": g.p, "n": g.n, "k": g.k, "kairos": g.kairos})),
                "h5": s.h5_state}));
        }
        cases.push(json!({"mode": mode, "entities": entities, "traces": traces}));
    }
    println!("{}", serde_json::to_string_pretty(&json!({"schema": "gabriel-golden-trace/1", "engine": cases})).unwrap());
}
