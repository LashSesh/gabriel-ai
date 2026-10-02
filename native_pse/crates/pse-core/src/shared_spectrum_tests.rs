//! Same-binary differential tests of the optional C16/C18 eigensystem reuse.
//! Graph setup is a test fixture; measured acquisition workloads live separately.

use super::*;
use pse_graph::derive_vertex_id;
use serde_json::{json, Value};

fn commit_config() -> Config {
    let mut c = Config::default();
    c.thresholds.d = 0.0;
    c.thresholds.q = 0.0;
    c.thresholds.r = 0.0;
    c.thresholds.g = 0.0;
    c.thresholds.j = 0.0;
    c.thresholds.p = 0.0;
    c.thresholds.n = 0.0;
    c.thresholds.k = 0.0;
    c.consensus.consensus_threshold = 0.0;
    c.consensus.mirror_consistency_eta = 0.0;
    c.consensus.archive_dominance = 2.0;
    c.consensus.memory_similarity_threshold = 2.0;
    c.carrier.adaptive = true;
    c.extraction.convergence_tau = 1.0;
    c.adaptation.split_threshold = 3.0;
    c.adaptation.merge_distance = 0.0;
    c
}

fn fixture(n: usize, shape: &str, c: &Config) -> GlobalState {
    let mut state = GlobalState::new(c);
    let ids: Vec<_> = (0..n)
        .map(|i| derive_vertex_id(&format!("fixture-{i}")))
        .collect();
    for &id in &ids {
        state.graph.upsert_vertex(id, 0.0);
    }
    for i in 0..n {
        for j in i + 1..n {
            let connected = match shape {
                "empty" => false,
                "path" => j == i + 1,
                "disconnected" => j == i + 1 && j != n / 2,
                "cycle" => j == i + 1 || (i == 0 && j == n - 1),
                "complete" => true,
                _ => panic!("unknown test graph"),
            };
            if connected {
                state.graph.upsert_edge(ids[i], ids[j], 0.0);
            }
        }
    }
    // Nonuniform positive weights exercise the weighted Laplacian. These do
    // not affect the Metatron input, which tests only undirected edge presence.
    if shape == "path" || shape == "disconnected" {
        for (index, edge) in state.graph.graph.edge_weights_mut().enumerate() {
            edge.weight = (index % 5 + 1) as f64 / 8.0;
        }
    }
    state
}

fn graph_snapshot(g: &PersistentGraph) -> Value {
    let nodes: Vec<_> = g.graph.node_weights().map(|v|
        (v.id, v.active, v.first_seen, v.last_seen, v.activation_count)).collect();
    let edges: Vec<_> = g.graph.raw_edges().iter().map(|e|
        (e.source().index(), e.target().index(), &e.weight)).collect();
    let ids: Vec<_> = g.id_map.iter().map(|(&v, i)| (v, i.index())).collect();
    let history: Vec<_> = g.history.iter().map(|r|
        (r.commit_index, r.digest, r.timestamp)).collect();
    let tensors: Vec<_> = g.tensor.iter().map(|(id, t)|
        (id, &t.snapshots, &t.timestamps)).collect();
    json!({"nodes": nodes, "edges": edges, "ids": ids,
        "embeddings": g.embedding, "history": history, "tensor": tensors,
        "hot": g.hot.data, "warm": g.warm.data, "warm_corrupted": g.warm.corrupted,
        "cold": g.cold.data, "tick": g.commit_index})
}

// This deliberately covers substantially more state than crystal IDs alone.
// PatternMemory private implementation details and the empty NullCenter are
// not serialized; public per-crystal entries and all exposed statistics are.
fn state_snapshot(s: &GlobalState) -> Value {
    let memory_entries: Vec<_> = s.archive.crystals().iter()
        .map(|c| s.memory.signature_for(&c.crystal_id)).collect();
    json!({
        "graph": graph_snapshot(&s.graph),
        "pipeline": {
            "candidates": format!("{:?}", s.candidates),
            "consensus": s.consensus.last_result, "morph": format!("{:?}", s.morph),
            "carrier": s.active_carrier, "ladder": s.phase_ladder, "h5": s.h5_state,
            "tick": s.commit_index, "engine": format!("{:?}", s.engine_state),
            "por": {
                "state": format!("{:?}", s.por_fsm.state),
                "stability_history": s.por_fsm.stability_history,
                "lock_tick": s.por_fsm.lock_tick, "verify_tick": s.por_fsm.verify_tick,
                "trace": s.por_fsm.get_trace()
            },
            "archive": s.archive.crystals(),
            "t2_bits": s.t2.to_bits(), "prev_embeddings": s.prev_embeddings,
            "constraint_count": s.last_constraint_count
        },
        "derived": {
            "gate_passed": s.last_gate_passed, "gate": s.last_gate,
            "adaptive": format!("{:?}", s.adaptive), "scale": format!("{:?}", s.scale_state),
            "pattern_hits": s.pattern_hits, "memory_stats": s.memory.stats(),
            "memory_entries": memory_entries, "memory_len": s.memory.len(),
            "canonical_classes": s.memory.canonical_classes_known(),
            "data_helix": s.last_data_helix, "navigator": s.navigator_state,
            "last_commit": s.last_crystal_commit, "commits": s.crystals_committed,
            "startup": s.startup_gate_samples, "background": format!("{:?}", s.background_model),
            "last_crystal_gate": s.last_crystal_gate
        }
    })
}

fn compare_step(
    reference: &mut GlobalState,
    shared: &mut GlobalState,
    batch: &[Vec<u8>],
    c: &Config,
    adapter: &dyn ObservationAdapter,
) -> Result<Option<SemanticCrystal>> {
    let a = macro_step_impl::<false>(reference, batch, c, adapter);
    let b = macro_step_impl::<true>(shared, batch, c, adapter);
    // Debug retains error variants/messages and finite float representations.
    assert_eq!(format!("{a:?}"), format!("{b:?}"), "complete result differs");
    if let (Ok(ca), Ok(cb)) = (&a, &b) {
        assert_eq!(serde_json::to_vec(ca).unwrap(), serde_json::to_vec(cb).unwrap(),
            "complete serialized crystals differ");
    }
    assert_eq!(serde_json::to_vec(&state_snapshot(reference)).unwrap(),
        serde_json::to_vec(&state_snapshot(shared)).unwrap(), "state differs");
    a
}

#[test]
fn shared_spectrum_matches_reference_small_and_sparse_commits() {
    let c = commit_config();
    for (n, shape) in [(0, "empty"), (1, "empty"), (3, "path"),
        (5, "disconnected"), (7, "complete"), (8, "cycle"), (32, "path")] {
        let mut reference = fixture(n, shape, &c);
        let mut shared = fixture(n, shape, &c);
        let adapter = PassthroughAdapter::new("fixture-0");
        for tick in 0..2 {
            let batch = if n == 0 { vec![] } else {
                vec![format!("finite UTF-8 observation {tick}").into_bytes()]
            };
            let crystal = compare_step(&mut reference, &mut shared, &batch, &c, &adapter)
                .expect("finite fixture must be accepted").expect("fixture must commit");
            assert_eq!(crystal.region.len(), n);
            assert_eq!(reference.graph.graph.node_count(), n);
            assert_eq!(shared.graph.graph.node_count(), n);
            assert_eq!(reference.crystals_committed, tick + 1);
            assert_eq!(crystal.metatron_signature.is_some(), (1..=7).contains(&n));
        }
    }
}

#[test]
fn shared_spectrum_matches_reference_size_boundaries_and_partial_solver() {
    let c = commit_config();
    // 100/101 cross CTQW's size gate. 199/200 cross the default k=50
    // partial-solver condition (k <= n/4). 500/501 cross C16/C18's size gate.
    // Known partial-solver inaccuracies are inherited by both modes.
    for n in [100, 101, 199, 200, 201, 500, 501] {
        let mut reference = fixture(n, "path", &c);
        let mut shared = fixture(n, "path", &c);
        let adapter = PassthroughAdapter::new("fixture-0");
        let crystal = compare_step(&mut reference, &mut shared,
            &[b"finite UTF-8 size-boundary observation".to_vec()], &c, &adapter)
            .expect("size fixture must be accepted").expect("size fixture must commit");
        assert_eq!(crystal.region.len(), n);
        assert_eq!(reference.graph.graph.node_count(), n);
        assert_eq!(shared.graph.graph.node_count(), n);
        if n > 500 {
            assert_eq!(format!("{:?}", shared.scale_state),
                format!("{:?}", pse_scale::MultiScaleState::default()),
                "large-graph path must continue skipping C18");
        }
    }
}

#[test]
fn shared_spectrum_preserves_rejection_cooldown_and_observation_errors() {
    let adapter = PassthroughAdapter::new("fixture-0");
    let batch = vec![b"finite UTF-8 gate observation".to_vec()];
    let mut c = commit_config();
    c.thresholds.d = 2.0;
    let mut reference = fixture(3, "path", &c);
    let mut shared = fixture(3, "path", &c);
    assert!(compare_step(&mut reference, &mut shared, &batch, &c, &adapter)
        .unwrap().is_none());

    c.thresholds.d = 0.0;
    c.consensus.crystal_cooldown_ticks = 2;
    let mut reference = fixture(3, "path", &c);
    let mut shared = fixture(3, "path", &c);
    assert!(compare_step(&mut reference, &mut shared, &batch, &c, &adapter)
        .unwrap().is_some());
    assert!(compare_step(&mut reference, &mut shared, &batch, &c, &adapter)
        .unwrap().is_none());

    c.persistence.max_vertices = 0;
    assert!(matches!(compare_step(&mut reference, &mut shared, &batch, &c, &adapter),
        Err(EngineError::Persist(_))));

    struct RejectAdapter;
    impl ObservationAdapter for RejectAdapter {
        fn source_id(&self) -> &str { "reject-test" }
        fn canonicalize(&self, _: &[u8], _: &MeasurementContext)
            -> std::result::Result<Observation, pse_graph::ObserveError> {
            Err(pse_graph::ObserveError::Canonicalize("controlled rejection".into()))
        }
    }
    assert!(matches!(compare_step(&mut reference, &mut shared, &batch, &c, &RejectAdapter),
        Err(EngineError::Observe(_))));
}
