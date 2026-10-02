use super::*;

fn graph(n: usize, weights: impl Fn(usize, usize) -> f64) -> SparseLaplacian {
    let mut degree = vec![0.0; n];
    let mut adjacency = Vec::new();
    for i in 0..n {
        for j in 0..n {
            if i != j {
                let w = weights(i, j);
                degree[i] += w;
                if w != 0.0 {
                    adjacency.push((i, j, w));
                }
            }
        }
    }
    SparseLaplacian { n, degree, adjacency }
}

fn clique(n: usize, weight: f64) -> SparseLaplacian {
    graph(n, |_, _| weight)
}

fn initial(n: usize) -> Vec<Complex<f64>> {
    (0..n).map(|i| Complex::new((i as f64 * 1.7).sin() + 0.3, (i as f64 * 0.8).cos() - 0.2)).collect()
}

fn close(actual: &[Complex<f64>], expected: &[Complex<f64>], tolerance: f64) {
    assert_eq!(actual.len(), expected.len());
    for (i, (&a, &b)) in actual.iter().zip(expected).enumerate() {
        assert!((a - b).norm() <= tolerance * (1.0 + b.norm()), "component {i}: {a:?} vs {b:?}");
    }
}

// Independent matrix-power reference: no eigenvectors and no clique shortcut.
fn taylor_state(graph: &SparseLaplacian, state: &[Complex<f64>], time: f64) -> Vec<Complex<f64>> {
    let mut term = state.to_vec();
    let mut answer = state.to_vec();
    for order in 1..=100 {
        let mut next: Vec<_> = term.iter().zip(&graph.degree).map(|(&x, &d)| x * d).collect();
        for &(i, j, weight) in &graph.adjacency {
            next[i] -= term[j] * weight;
        }
        let factor = Complex::new(0.0, -time / order as f64);
        for i in 0..graph.n {
            term[i] = next[i] * factor;
            answer[i] += term[i];
        }
    }
    answer
}

#[test]
fn both_backends_match_independent_clique_formula_with_complex_unnormalized_states() {
    for n in [1, 2, 3, 7, 13, 32] {
        for w in [0.0, 0.25, 1.0] {
            let g = clique(n, w);
            let state = initial(n);
            let mean: Complex<f64> = state.iter().copied().sum::<Complex<f64>>() / n as f64;
            for choice in [BackendChoice::Auto, BackendChoice::Spectral] {
                let plan = ConditionedWalkPlan::new(&g, choice).unwrap();
                assert_eq!(plan.dimension(), n);
                assert_eq!(plan.backend(), if choice == BackendChoice::Auto { WalkBackend::CompleteGraph } else { WalkBackend::Spectral });
                let prepared = plan.prepare_state(&state).unwrap();
                for time in [-2.0, -0.1, 0.0, 0.03, 1.0] {
                    let angle = -time * n as f64 * w;
                    let rotating = Complex::new(angle.cos(), angle.sin());
                    let expected: Vec<_> = state.iter().map(|&x| mean + rotating * (x - mean)).collect();
                    close(&prepared.state_at(time).unwrap(), &expected, 2e-12);
                }
            }
        }
    }
}

#[test]
fn arbitrary_graphs_match_matrix_power_reference() {
    let graphs = [
        graph(7, |i, j| if i.abs_diff(j) == 1 { 0.3 } else { 0.0 }),
        graph(6, |i, j| if (i + j) % 3 == 0 { 0.25 } else { 0.0 }),
        graph(5, |i, j| (i + j + 1) as f64 * 0.125),
    ];
    for g in &graphs {
        let state = initial(g.n);
        for choice in [BackendChoice::Auto, BackendChoice::Spectral] {
            let plan = ConditionedWalkPlan::new(g, choice).unwrap();
            assert_eq!(plan.backend(), WalkBackend::Spectral);
            let prepared = plan.prepare_state(&state).unwrap();
            for time in [-0.25, 0.03, 0.4] {
                close(&prepared.state_at(time).unwrap(), &taylor_state(g, &state, time), 2e-12);
            }
        }
    }
}

#[test]
fn two_vertex_sign_is_positive_laplacian_negative_time_exponent() {
    for choice in [BackendChoice::Auto, BackendChoice::Spectral] {
        let plan = ConditionedWalkPlan::new(&clique(2, 1.0), choice).unwrap();
        let state = [Complex::new(1.0, 0.0), Complex::new(0.0, 0.0)];
        let result = plan.prepare_state(&state).unwrap().state_at(std::f64::consts::FRAC_PI_4).unwrap();
        close(&result, &[Complex::new(0.5, -0.5), Complex::new(0.5, 0.5)], 1e-14);
    }
}

#[test]
fn full_spectrum_preserves_norm_degenerate_spaces_and_inverse_evolution() {
    for g in [clique(13, 1.0), graph(8, |i, j| if i / 2 == j / 2 { 0.5 } else { 0.0 })] {
        let original = initial(g.n);
        let norm: f64 = original.iter().map(|x| x.norm_sqr()).sum();
        for choice in [BackendChoice::Auto, BackendChoice::Spectral] {
            let plan = ConditionedWalkPlan::new(&g, choice).unwrap();
            let evolved = plan.prepare_state(&original).unwrap().state_at(2.25).unwrap();
            let evolved_norm: f64 = evolved.iter().map(|x| x.norm_sqr()).sum();
            assert!((norm - evolved_norm).abs() < 1e-11 * norm);
            let returned = plan.prepare_state(&evolved).unwrap().state_at(-2.25).unwrap();
            close(&returned, &original, 3e-12);
        }
    }
}

#[test]
fn time_zero_returns_exact_input_bits_including_signed_zero() {
    let original = [Complex::new(-0.0, 0.0), Complex::new(2.25, -1.3)];
    for choice in [BackendChoice::Auto, BackendChoice::Spectral] {
        let plan = ConditionedWalkPlan::new(&clique(2, 0.25), choice).unwrap();
        let prepared = plan.prepare_state(&original).unwrap();
        for t in [0.0, -0.0] {
            let result = prepared.state_at(t).unwrap();
            for (a, b) in result.iter().zip(original) {
                assert_eq!(a.re.to_bits(), b.re.to_bits());
                assert_eq!(a.im.to_bits(), b.im.to_bits());
            }
        }
    }
}

#[test]
fn edgeless_singleton_and_zero_state_are_supported_without_normalization() {
    for n in [1, 2, 13] {
        for choice in [BackendChoice::Auto, BackendChoice::Spectral] {
            let plan = ConditionedWalkPlan::new(&clique(n, 0.0), choice).unwrap();
            let state = initial(n);
            close(&plan.prepare_state(&state).unwrap().state_at(1e100).unwrap(), &state, 1e-14);
            let zero = vec![Complex::new(0.0, 0.0); n];
            assert_eq!(plan.prepare_state(&zero).unwrap().state_at(3.0).unwrap(), zero);
        }
    }
}

#[test]
fn near_clique_and_nonbinary_degree_mismatch_do_not_use_clique_formula() {
    let g = graph(7, |i, j| if i.min(j) == 0 && i.max(j) == 1 { 1.0 + f64::EPSILON } else { 1.0 });
    assert_eq!(ConditionedWalkPlan::new(&g, BackendChoice::Auto).unwrap().backend(), WalkBackend::Spectral);
    let g = clique(13, 1.7);
    assert_ne!(g.degree[0], 12.0 * 1.7);
    let plan = ConditionedWalkPlan::new(&g, BackendChoice::Auto).unwrap();
    assert_eq!(plan.backend(), WalkBackend::Spectral);
    let state = initial(13);
    close(&plan.prepare_state(&state).unwrap().state_at(0.03).unwrap(), &taylor_state(&g, &state, 0.03), 3e-12);
}

#[test]
fn clique_retains_rounded_diagonal_constant_space_phase() {
    // This clique passes the strict rounded-product guard, yet exact real
    // d-3w is nonzero for its stored binary64 entries. A large t exposes it.
    let g = clique(4, 0.1);
    assert_eq!(g.degree[0], 3.0 * 0.1);
    let residual = (-3.0_f64).mul_add(0.1, g.degree[0]);
    assert_ne!(residual, 0.0);
    let plan = ConditionedWalkPlan::new(&g, BackendChoice::Auto).unwrap();
    assert_eq!(plan.backend(), WalkBackend::CompleteGraph);
    let state = vec![Complex::new(1.0, 0.0); 4];
    let time = 1.0 / residual;
    let expected = vec![Complex::new(1.0_f64.cos(), -1.0_f64.sin()); 4];
    close(&plan.prepare_state(&state).unwrap().state_at(time).unwrap(), &expected, 1e-14);
}

#[test]
fn rejects_empty_wrong_dimensions_bad_indices_self_loops_and_degrees() {
    assert!(matches!(ConditionedWalkPlan::new(&clique(0, 1.0), BackendChoice::Auto), Err(WalkError::EmptyGraph)));
    let mut g = clique(2, 1.0);
    g.degree.pop();
    assert!(matches!(ConditionedWalkPlan::new(&g, BackendChoice::Auto), Err(WalkError::DimensionMismatch { .. })));
    for edge in [(0, 2, 1.0), (0, 0, 1.0)] {
        let mut g = clique(2, 1.0);
        g.adjacency.push(edge);
        assert!(matches!(ConditionedWalkPlan::new(&g, BackendChoice::Auto), Err(WalkError::InvalidEdge { .. })));
    }
    for bad in [-1.0, f64::NAN, f64::INFINITY] {
        let mut g = clique(2, 1.0);
        g.degree[0] = bad;
        assert!(matches!(ConditionedWalkPlan::new(&g, BackendChoice::Auto), Err(WalkError::InvalidDegree { .. })));
    }
}

#[test]
fn rejects_duplicates_asymmetry_nonfinite_negative_weights_and_inconsistent_degree() {
    let mut g = clique(2, 1.0);
    g.adjacency.push((0, 1, 1.0));
    assert!(matches!(ConditionedWalkPlan::new(&g, BackendChoice::Auto), Err(WalkError::DuplicateEdge { .. })));
    let mut g = clique(2, 1.0);
    g.adjacency.pop();
    assert!(matches!(ConditionedWalkPlan::new(&g, BackendChoice::Auto), Err(WalkError::AsymmetricEdge { .. })));
    let mut g = clique(2, 1.0);
    g.adjacency[0].2 = 1.1;
    assert!(matches!(ConditionedWalkPlan::new(&g, BackendChoice::Auto), Err(WalkError::AsymmetricEdge { .. })));
    for bad in [-1.0, f64::NAN, f64::INFINITY] {
        let mut g = clique(2, 1.0);
        g.adjacency[0].2 = bad;
        assert!(matches!(ConditionedWalkPlan::new(&g, BackendChoice::Auto), Err(WalkError::InvalidEdge { .. })));
    }
    let mut g = clique(2, 1.0);
    g.degree[0] += f64::EPSILON;
    assert!(matches!(ConditionedWalkPlan::new(&g, BackendChoice::Auto), Err(WalkError::InconsistentDegree { .. })));
}

#[test]
fn explicit_zero_edges_still_obey_uniqueness_and_reverse_entry_contract() {
    let mut g = clique(2, 0.0);
    g.adjacency.push((0, 1, 0.0));
    assert!(matches!(ConditionedWalkPlan::new(&g, BackendChoice::Auto), Err(WalkError::AsymmetricEdge { .. })));
    g.adjacency.push((1, 0, -0.0));
    assert_eq!(ConditionedWalkPlan::new(&g, BackendChoice::Auto).unwrap().backend(), WalkBackend::CompleteGraph);
    g.adjacency.push((0, 1, 0.0));
    assert!(matches!(ConditionedWalkPlan::new(&g, BackendChoice::Auto), Err(WalkError::DuplicateEdge { .. })));
}

#[test]
fn edge_input_order_does_not_change_validation_or_result() {
    let mut g = graph(5, |i, j| (i + j + 1) as f64 * 0.1);
    let state = initial(5);
    let first = ConditionedWalkPlan::new(&g, BackendChoice::Auto).unwrap();
    g.adjacency.reverse();
    let second = ConditionedWalkPlan::new(&g, BackendChoice::Auto).unwrap();
    assert_eq!(first.prepare_state(&state).unwrap().state_at(0.3).unwrap(), second.prepare_state(&state).unwrap().state_at(0.3).unwrap());
}

#[test]
fn rejects_bad_states_and_nonfinite_times() {
    let plan = ConditionedWalkPlan::new(&clique(2, 1.0), BackendChoice::Auto).unwrap();
    assert!(matches!(plan.prepare_state(&[]), Err(WalkError::DimensionMismatch { .. })));
    for bad in [f64::NAN, f64::INFINITY, f64::NEG_INFINITY] {
        assert!(matches!(plan.prepare_state(&[Complex::new(bad, 0.0), Complex::new(0.0, 0.0)]), Err(WalkError::NonFiniteState { .. })));
        let state = initial(2);
        assert_eq!(plan.prepare_state(&state).unwrap().state_at(bad), Err(WalkError::NonFiniteTime));
    }
}

#[test]
fn overflow_is_reported_for_degree_phase_and_state_arithmetic() {
    let mut g = clique(3, f64::MAX);
    g.degree.fill(f64::MAX);
    assert!(matches!(ConditionedWalkPlan::new(&g, BackendChoice::Auto), Err(WalkError::NumericalOverflow)));
    let plan = ConditionedWalkPlan::new(&clique(2, f64::MAX * 0.25), BackendChoice::Auto).unwrap();
    let state = initial(2);
    assert_eq!(plan.prepare_state(&state).unwrap().state_at(4.0), Err(WalkError::NumericalOverflow));
    let plan = ConditionedWalkPlan::new(&clique(3, 1.0), BackendChoice::Auto).unwrap();
    let state = [Complex::new(-f64::MAX, 0.0), Complex::new(f64::MAX, 0.0), Complex::new(f64::MAX, 0.0)];
    assert_eq!(plan.prepare_state(&state).unwrap().state_at(0.5), Err(WalkError::NumericalOverflow));
}

#[test]
fn zero_time_can_return_large_finite_states_without_norm_overflow() {
    let plan = ConditionedWalkPlan::new(&clique(2, 0.25), BackendChoice::Auto).unwrap();
    let state = [Complex::new(f64::MAX, 0.0), Complex::new(f64::MAX, 0.0)];
    assert_eq!(plan.prepare_state(&state).unwrap().state_at(0.0).unwrap(), state);
}
