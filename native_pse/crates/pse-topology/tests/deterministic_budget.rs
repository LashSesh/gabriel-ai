use pse_graph::PersistentGraph;
use pse_topology::{compute_topological_signature, TopologyConfig};

#[test]
fn wall_clock_budget_cannot_change_a_topological_result() {
    let mut graph = PersistentGraph::new();
    graph.upsert_edge(1, 2, 0.0);
    graph.upsert_edge(2, 3, 0.0);
    let zero = compute_topological_signature(
        &graph,
        &TopologyConfig {
            budget_ms: 0,
            ..Default::default()
        },
    );
    let unlimited = compute_topological_signature(
        &graph,
        &TopologyConfig {
            budget_ms: u64::MAX,
            ..Default::default()
        },
    );
    assert!(unlimited.mean_propagation_time > 0.0);
    assert_eq!(
        zero.mean_propagation_time.to_bits(),
        unlimited.mean_propagation_time.to_bits()
    );
    assert_eq!(
        zero.spectral_gap.to_bits(),
        unlimited.spectral_gap.to_bits()
    );
    assert_eq!(
        zero.kuramoto_coherence.to_bits(),
        unlimited.kuramoto_coherence.to_bits()
    );
    assert_eq!(zero.dtl_predicates, unlimited.dtl_predicates);
}
