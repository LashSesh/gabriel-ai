//! Differential tests against the source-frozen complete reference function.
use super::*;

fn assert_result_bits(reference: &CtqwResult, candidate: &CtqwResult) {
    for (label, a, b) in [
        ("transfer", &reference.transfer_probabilities, &candidate.transfer_probabilities),
        ("speed", &reference.propagation_speeds, &candidate.propagation_speeds),
    ] {
        assert_eq!(a.len(), b.len(), "{label} row count");
        for (i, (ar, br)) in a.iter().zip(b).enumerate() {
            assert_eq!(ar.len(), br.len(), "{label} row {i} width");
            for (j, (av, bv)) in ar.iter().zip(br).enumerate() {
                assert_eq!(av.to_bits(), bv.to_bits(), "{label}[{i}][{j}]: {av:?} != {bv:?}");
            }
        }
    }
    assert_eq!(reference.mean_propagation_time.to_bits(), candidate.mean_propagation_time.to_bits(), "mean propagation time");
}

fn compare(spectral: &SpectralDecomposition, cfg: &TopologyConfig) {
    let reference = ctqw_propagate_reference(spectral, cfg);
    assert_result_bits(&reference, &ctqw_propagate_hoisted(spectral, cfg));
    assert_result_bits(&reference, &ctqw_propagate(spectral, cfg));
}

fn synthetic(eigenvalues: Vec<f64>, eigenvectors: Vec<Vec<f64>>, rank: usize) -> SpectralDecomposition {
    SpectralDecomposition {
        eigenvalues,
        eigenvectors,
        spectral_gap: 0.0,
        cheeger_estimate: 0.0,
        fiedler_vector: Vec::new(),
        truncation_rank: rank,
    }
}

fn graph(n: usize, kind: usize) -> PersistentGraph {
    let mut g = PersistentGraph::new();
    for i in 0..n {
        g.upsert_vertex(i as u64, i as f64 / 3.0);
        g.embedding.get_mut(&(i as u64)).unwrap().omega = i as f64 * 0.173;
    }
    for i in 0..n {
        for j in (i + 1)..n {
            let include = match kind {
                0 => false,
                1 => j == i + 1,
                2 => i == 0,
                _ => true,
            };
            if include {
                g.upsert_edge(i as u64, j as u64, 0.0);
                if kind == 4 {
                    let idx = g.graph.find_edge(g.id_map[&(i as u64)], g.id_map[&(j as u64)]).unwrap();
                    g.graph.edge_weight_mut(idx).unwrap().weight = ((i * 13 + j * 7) % 11) as f64 / 7.0;
                    if (i + j) % 2 == 0 {
                        g.upsert_edge(j as u64, i as u64, 0.0);
                    }
                }
            }
        }
    }
    g
}

#[test]
fn ctqw_reference_body_is_source_frozen() {
    let source = include_str!("lib.rs");
    let start = source.find("pub fn ctqw_propagate_reference(").unwrap();
    let open = start + source[start..].find('{').unwrap();
    let close = open + source[open..].find("\n}\n").unwrap() + 2;
    let digest = pse_types::content_address_raw(source[open..close].as_bytes());
    let hex: String = digest.iter().map(|b| format!("{b:02x}")).collect();
    assert_eq!(hex, "a0d94fdef6254c04e80704b7ae9fe3c3d7454b797cf05b86603adbcf7dde11a4");
}

#[test]
fn ctqw_hoist_graph_spectra_all_fields_bitwise() {
    for n in [0, 1, 2, 3, 5, 7, 8, 16, 32] {
        for kind in 0..5 {
            let g = graph(n, kind);
            let lap = compute_laplacian(&g);
            for rank in [0, 1, 2, n] {
                let spectral = spectral_decompose(&lap, rank);
                for (steps, time, threshold) in [(0, 0.3, 0.5), (1, 1.1, 0.0), (3, 0.1, 0.2), (7, -0.7, 0.5), (100, 10.0, 1.1)] {
                    let cfg = TopologyConfig { ctqw_time_steps: steps, ctqw_time_max: time, ctqw_threshold: threshold, ..Default::default() };
                    compare(&spectral, &cfg);
                }
            }
        }
    }
}

#[test]
fn ctqw_hoist_seeded_synthetic_and_ragged_spectra_bitwise() {
    let mut seed = 0xC7_2026_0926_0001_u64;
    let mut next = || {
        seed ^= seed << 13;
        seed ^= seed >> 7;
        seed ^= seed << 17;
        (seed >> 11) as f64 / ((1_u64 << 53) as f64)
    };
    for case in 0..192 {
        let n = case % 9 + 1;
        let k = case % 7;
        let values = (0..k).map(|_| (next() - 0.5) * 100.0).collect();
        let mut vectors = Vec::new();
        // First row establishes n even when k = 0. Later rows may be ragged,
        // and absent eigenvector rows have the reference zero fallback.
        for mode in 0..(k.max(1)) {
            let len = if mode == 0 { n } else { case % (n + 1) };
            vectors.push((0..len).map(|_| (next() - 0.5) * 2.0).collect());
        }
        if case % 3 == 0 && vectors.len() > 1 { vectors.truncate(1); }
        let spectral = synthetic(values, vectors, k);
        let cfg = TopologyConfig { ctqw_time_steps: [0, 1, 3, 7, 100][case % 5], ctqw_time_max: (next() - 0.5) * 12.3, ctqw_threshold: (next() - 0.25) * 2.0, ..Default::default() };
        compare(&spectral, &cfg);
    }
}

#[test]
fn ctqw_hoist_threshold_adjacent_probabilities_bitwise() {
    let spectral = synthetic(vec![-0.0, 0.75, 2.3], vec![vec![0.2, -0.7, 0.6], vec![-0.8, 0.3, 0.1], vec![0.4, 0.9, -0.2]], 3);
    for time in [0.1, 0.3, 0.7, 1.1, 2.7, -0.0, -1.3] {
        let mut cfg = TopologyConfig { ctqw_time_steps: 1, ctqw_time_max: time, ..Default::default() };
        let output = ctqw_propagate_reference(&spectral, &cfg);
        for (j, row) in output.transfer_probabilities.iter().enumerate() {
            for (dest, &prob) in row.iter().enumerate() {
                if j == dest { continue; }
                for threshold in [prob.next_down(), prob, prob.next_up()] {
                    cfg.ctqw_threshold = threshold;
                    compare(&spectral, &cfg);
                }
            }
        }
    }
}

#[test]
fn ctqw_hoist_special_float_inputs_bitwise() {
    let quiet_nan = f64::from_bits(0x7ff8_0000_0000_0042);
    for value in [0.0, -0.0, f64::MIN_POSITIVE, f64::from_bits(1), 1.0e-250, 1.0e250, f64::INFINITY, f64::NEG_INFINITY, quiet_nan] {
        for time in [0.0, -0.0, 0.3, f64::INFINITY, quiet_nan] {
            let spectral = synthetic(vec![value, -0.0], vec![vec![1.0, value], vec![-0.0, 1.0]], 2);
            for steps in [0, 1, 3] {
                for threshold in [0.5, quiet_nan] {
                    let cfg = TopologyConfig { ctqw_time_steps: steps, ctqw_time_max: time, ctqw_threshold: threshold, ..Default::default() };
                    compare(&spectral, &cfg);
                }
            }
        }
    }
}

#[test]
fn ctqw_hoist_empty_shapes_and_invalid_rank_preserve_return_or_panic() {
    let cfg = TopologyConfig::default();
    for spectral in [synthetic(Vec::new(), Vec::new(), 17), synthetic(Vec::new(), vec![Vec::new()], 17), synthetic(Vec::new(), vec![vec![1.0]], 0)] {
        compare(&spectral, &cfg);
    }
    for n in [1, 3] {
        for steps in [0, 3] {
            let bad = synthetic(vec![0.0], vec![vec![1.0; n]], 2);
            let cfg = TopologyConfig { ctqw_time_steps: steps, ..Default::default() };
            assert!(std::panic::catch_unwind(|| ctqw_propagate_reference(&bad, &cfg)).is_err());
            assert!(std::panic::catch_unwind(|| ctqw_propagate_hoisted(&bad, &cfg)).is_err());
        }
    }
}

#[test]
fn ctqw_reference_fallback_preserves_exceptional_payload_and_sign_bits() {
    for nan in [f64::from_bits(0x7ff8_0000_0000_0042), f64::from_bits(0xfff8_0000_0000_0042)] {
        for site in 0..3 {
            let mut spectral = synthetic(vec![0.75, -0.0], vec![vec![1.0, 0.25], vec![-0.0, 1.0]], 2);
            let mut cfg = TopologyConfig { ctqw_time_steps: 3, ctqw_time_max: 0.3, ..Default::default() };
            match site {
                0 => spectral.eigenvalues[0] = nan,
                1 => spectral.eigenvectors[0][1] = nan,
                _ => cfg.ctqw_time_max = nan,
            }
            compare(&spectral, &cfg);
        }
    }
    // All supplied values are finite, but the unguarded products can overflow.
    for (lambda, component, time) in [(f64::MAX, 1.0, 2.0), (1.0, f64::MAX, 0.3), (1.0, 1.0, f64::from_bits(1))] {
        let spectral = synthetic(vec![lambda, -0.0], vec![vec![component, 1.0], vec![1.0, -0.0]], 2);
        let cfg = TopologyConfig { ctqw_time_steps: 3, ctqw_time_max: time, ..Default::default() };
        compare(&spectral, &cfg);
    }
}
