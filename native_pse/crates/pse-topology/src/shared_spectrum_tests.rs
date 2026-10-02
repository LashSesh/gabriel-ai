//! Original signature body is kept here as an independent refactor oracle.
use super::*;

fn original_topological_signature(
    graph: &PersistentGraph,
    config: &TopologyConfig,
) -> TopologicalSignature {
    let n = graph.graph.node_count();
    let e = graph.graph.edge_count();

    // Betti numbers (existing logic)
    let betti_0 = count_components(graph);
    let n_u = n as u64;
    let e_u = e as u64;
    let betti_1 = (e_u + betti_0).saturating_sub(n_u);

    let (spectral_gap, cheeger_estimate, dtl_predicates, mean_propagation_time, kuramoto_coherence);

    if n > 500 {
        // Deterministic size bound: skip decomposition and unused Laplacian allocation.
        tracing::debug!(n, "isls-topology budget fallback");
        spectral_gap = 0.0;
        cheeger_estimate = 0.0;
        dtl_predicates = {
            let mut m = BTreeMap::new();
            m.insert("Connected".to_string(), betti_0 == 1);
            m
        };
        mean_propagation_time = 0.0;
        kuramoto_coherence = 0.0;
    } else {
        let laplacian = compute_laplacian(graph);
        let k = config.spectral_k_max.min(n);
        let spectral = spectral_decompose(&laplacian, k);
        spectral_gap = spectral.spectral_gap;
        cheeger_estimate = spectral.cheeger_estimate;
        dtl_predicates = dtl_evaluate(graph, &spectral);

        if n <= 100 {
            let ctqw = ctqw_propagate(&spectral, config);
            mean_propagation_time = if ctqw.mean_propagation_time.is_finite() {
                ctqw.mean_propagation_time
            } else {
                0.0
            };
        } else {
            mean_propagation_time = 0.0;
        }

        let mut kstate = init_kuramoto_state(graph);
        for _ in 0..config.kuramoto_steps.min(10) {
            kuramoto_step(&mut kstate, graph, config);
        }
        kuramoto_coherence = kstate.order_parameter;
    }

    TopologicalSignature {
        betti_numbers: vec![betti_0, betti_1, 0],
        spectral_gap,
        cheeger_estimate,
        kuramoto_coherence,
        mean_propagation_time,
        dtl_predicates,
    }
}

fn bits(values: &[f64]) -> Vec<u64> { values.iter().map(|x| x.to_bits()).collect() }
fn assert_signature(a: &TopologicalSignature, b: &TopologicalSignature) {
    assert_eq!(a.betti_numbers,b.betti_numbers);
    assert_eq!(a.dtl_predicates,b.dtl_predicates);
    assert_eq!(bits(&[a.spectral_gap,a.cheeger_estimate,a.kuramoto_coherence,a.mean_propagation_time]),bits(&[b.spectral_gap,b.cheeger_estimate,b.kuramoto_coherence,b.mean_propagation_time]));
}
fn assert_spectrum(a: &SpectralDecomposition,b: &SpectralDecomposition) {
    assert_eq!(a.truncation_rank,b.truncation_rank);
    assert_eq!(bits(&a.eigenvalues),bits(&b.eigenvalues));
    assert_eq!(a.eigenvectors.iter().map(|v| bits(v)).collect::<Vec<_>>(),b.eigenvectors.iter().map(|v| bits(v)).collect::<Vec<_>>());
    assert_eq!(bits(&a.fiedler_vector),bits(&b.fiedler_vector));
    assert_eq!(bits(&[a.spectral_gap,a.cheeger_estimate]),bits(&[b.spectral_gap,b.cheeger_estimate]));
}
#[test]
fn shared_spectrum_retains_identical_decomposition_and_signature() {
    for n in [0,1,3,7,32,101,501] {
        let mut graph=PersistentGraph::new();
        for i in 0..n { graph.upsert_vertex(i as u64,0.0); graph.embedding.get_mut(&(i as u64)).unwrap().omega=i as f64*0.173; }
        for i in 1..n { graph.upsert_edge((i-1) as u64,i as u64,0.0); }
        for k in [0,2,50] {
            let cfg=TopologyConfig {spectral_k_max:k,ctqw_time_steps:3,..Default::default()};
            let reference=original_topological_signature(&graph,&cfg);
            let ordinary=compute_topological_signature(&graph,&cfg);
            let (shared,spectrum)=compute_topological_signature_with_spectrum(&graph,&cfg);
            assert_signature(&reference,&ordinary);
            assert_signature(&reference,&shared);
            if n>500 { assert!(spectrum.is_none()); }
            else {
                let laplacian=compute_laplacian(&graph);
                let independent=spectral_decompose(&laplacian,cfg.spectral_k_max);
                assert_spectrum(&independent,&spectrum.unwrap());
            }
        }
    }
}
