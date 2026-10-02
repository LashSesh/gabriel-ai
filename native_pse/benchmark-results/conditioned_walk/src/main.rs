//! Same-output comparison. Protocol and all workload choices are embedded at build time.
use pse_topology::conditioned_walk::{
    BackendChoice, Complex, ConditionedWalkPlan, PreparedState, WalkBackend,
};
use pse_topology::SparseLaplacian;
use serde_json::{json, Value};
use std::hint::black_box;
use std::time::Instant;

const PROTOCOL_TEXT: &str = include_str!("../protocol.json");

fn backend_name(backend: WalkBackend) -> &'static str {
    match backend {
        WalkBackend::CompleteGraph => "complete_graph",
        WalkBackend::Spectral => "spectral",
    }
}

fn graph(n: usize, family: &str, weight: f64) -> SparseLaplacian {
    let mut adjacency = Vec::new();
    let mut degree = vec![0.0; n];
    for i in 0..n {
        for j in 0..n {
            if i == j || (family == "path" && i.abs_diff(j) != 1) {
                continue;
            }
            let edge_weight = if family == "near_clique" && i.min(j) == 0 && i.max(j) == 1 {
                2.0 * weight
            } else {
                weight
            };
            adjacency.push((i, j, edge_weight));
            degree[i] += edge_weight;
        }
    }
    SparseLaplacian { n, adjacency, degree }
}

fn initial_state(n: usize) -> Vec<Complex<f64>> {
    let mut state: Vec<_> = (0..n)
        .map(|i| Complex::new(((17 * i + 3) % 29) as f64 - 14.0,
                             ((11 * i + 5) % 23) as f64 - 11.0))
        .collect();
    let norm = state.iter().map(|z| z.norm_sqr()).sum::<f64>().sqrt();
    for z in &mut state { *z /= norm; }
    state
}

// Noncryptographic, deterministic input identity; source SHA-256 is recorded by the runner.
fn input_fingerprint(lap: &SparseLaplacian, initial: &[Complex<f64>]) -> String {
    let mut value = 0xcbf29ce484222325u64;
    let mut absorb = |word: u64| {
        for byte in word.to_le_bytes() {
            value ^= byte as u64;
            value = value.wrapping_mul(0x100000001b3);
        }
    };
    absorb(lap.n as u64);
    for d in &lap.degree { absorb(d.to_bits()); }
    for &(i, j, w) in &lap.adjacency {
        absorb(i as u64); absorb(j as u64); absorb(w.to_bits());
    }
    for z in initial { absorb(z.re.to_bits()); absorb(z.im.to_bits()); }
    format!("fnv1a64:{value:016x}")
}

fn build_plan(lap: &SparseLaplacian, choice: BackendChoice) -> (ConditionedWalkPlan, u128) {
    let start = Instant::now();
    let result = ConditionedWalkPlan::new(black_box(lap), choice).expect("valid benchmark graph");
    black_box(&result);
    let elapsed = start.elapsed().as_nanos();
    (result, elapsed)
}

fn prepare_elapsed(plan: &ConditionedWalkPlan, initial: &[Complex<f64>]) -> u128 {
    let start = Instant::now();
    let state = plan.prepare_state(black_box(initial)).expect("valid initial state");
    black_box(&state);
    // Prepared-state destruction is outside this timing interval.
    start.elapsed().as_nanos()
}

fn query_batch(state: &PreparedState<'_>, times: &[f64], queries: usize) -> (u128, f64) {
    let mut checksum = 0.0;
    let start = Instant::now();
    for q in 0..queries {
        let output = state.state_at(black_box(times[q % times.len()])).expect("finite time");
        black_box(output.as_slice());
        let z = output[q % output.len()];
        checksum += z.re + 0.5 * z.im;
        // Drop the returned Vec on every iteration for both implementations.
    }
    let elapsed = start.elapsed().as_nanos();
    black_box(checksum);
    assert!(checksum.is_finite());
    (elapsed, checksum)
}

fn main() {
    let args: Vec<_> = std::env::args().collect();
    assert_eq!(args.len(), 3, "usage: benchmark --process-index N");
    assert_eq!(args[1], "--process-index");
    let process_index: usize = args[2].parse().expect("integer process index");
    let protocol: Value = serde_json::from_str(PROTOCOL_TEXT).unwrap();
    let batches = protocol["batches_per_process"].as_u64().unwrap() as usize;
    let warmup = protocol["warmup_queries_per_backend"].as_u64().unwrap() as usize;
    let absolute = protocol["component_absolute_tolerance"].as_f64().unwrap();
    let relative = protocol["component_relative_tolerance"].as_f64().unwrap();
    let norm_tolerance = protocol["norm_absolute_tolerance"].as_f64().unwrap();
    let checksum_absolute = protocol["checksum_absolute_tolerance"].as_f64().unwrap();
    let checksum_relative = protocol["checksum_relative_tolerance"].as_f64().unwrap();
    let times: Vec<_> = protocol["times"].as_array().unwrap().iter()
        .map(|t| t.as_f64().unwrap()).collect();
    let mut results = Vec::new();
    for (case_index, case) in protocol["cases"].as_array().unwrap().iter().enumerate() {
        let n = case["n"].as_u64().unwrap() as usize;
        let family = case["family"].as_str().unwrap();
        assert!(["clique", "near_clique", "path"].contains(&family));
        let weight = case["weight"].as_f64().unwrap();
        let queries = case["queries_per_batch"].as_u64().unwrap() as usize;
        assert!(queries >= times.len() && queries % times.len() == 0);
        let start = Instant::now();
        let lap = graph(n, family, weight);
        let graph_construction_ns = start.elapsed().as_nanos();
        let start = Instant::now();
        let initial = initial_state(n);
        let initial_generation_ns = start.elapsed().as_nanos();
        let initial_norm = initial.iter().map(|z| z.norm_sqr()).sum::<f64>();
        let fingerprint = input_fingerprint(&lap, &initial);

        // Warm constructor machinery before the five paired setup measurements.
        black_box(ConditionedWalkPlan::new(&lap, BackendChoice::Spectral).unwrap());
        black_box(ConditionedWalkPlan::new(&lap, BackendChoice::Auto).unwrap());
        let mut setup = Vec::new();
        let mut spectral_plan = None;
        let mut auto_plan = None;
        for batch in 0..batches {
            let spectral_first = (process_index + case_index + batch) % 2 == 0;
            let (s, a) = if spectral_first {
                let s = build_plan(&lap, BackendChoice::Spectral);
                let a = build_plan(&lap, BackendChoice::Auto);
                (s, a)
            } else {
                let a = build_plan(&lap, BackendChoice::Auto);
                let s = build_plan(&lap, BackendChoice::Spectral);
                (s, a)
            };
            setup.push(json!({"batch": batch, "spectral_first": spectral_first,
                              "spectral_ns": s.1, "auto_ns": a.1}));
            spectral_plan = Some(s.0);
            auto_plan = Some(a.0);
        }
        let spectral_plan = spectral_plan.unwrap();
        let auto_plan = auto_plan.unwrap();
        assert_eq!(spectral_plan.dimension(), n);
        assert_eq!(auto_plan.dimension(), n);
        assert_eq!(backend_name(spectral_plan.backend()), "spectral");
        assert_eq!(backend_name(auto_plan.backend()), case["expected_auto"].as_str().unwrap());

        black_box(spectral_plan.prepare_state(&initial).unwrap());
        black_box(auto_plan.prepare_state(&initial).unwrap());
        let mut preparation = Vec::new();
        for batch in 0..batches {
            let spectral_first = (process_index + case_index + batch) % 2 == 0;
            let (s, a) = if spectral_first {
                let s = prepare_elapsed(&spectral_plan, &initial);
                let a = prepare_elapsed(&auto_plan, &initial);
                (s, a)
            } else {
                let a = prepare_elapsed(&auto_plan, &initial);
                let s = prepare_elapsed(&spectral_plan, &initial);
                (s, a)
            };
            preparation.push(json!({"batch": batch, "spectral_first": spectral_first,
                                    "spectral_ns": s, "auto_ns": a}));
        }
        let spectral_state = spectral_plan.prepare_state(&initial).unwrap();
        let auto_state = auto_plan.prepare_state(&initial).unwrap();
        let start = Instant::now();
        let mut max_component_difference = 0.0f64;
        let mut max_component_tolerance_fraction = 0.0f64;
        let mut max_norm_error = 0.0f64;
        let mut checked_real_components = 0usize;
        let mut validation_states = Vec::new();
        for &time in &times {
            let s = spectral_state.state_at(time).unwrap();
            let a = auto_state.state_at(time).unwrap();
            assert_eq!(s.len(), n); assert_eq!(a.len(), n);
            let mut state_max_difference = 0.0f64;
            for (zs, za) in s.iter().zip(&a) {
                for (vs, va) in [(zs.re, za.re), (zs.im, za.im)] {
                    assert!(vs.is_finite() && va.is_finite());
                    let difference = (vs - va).abs();
                    let allowance = absolute + relative * vs.abs().max(va.abs());
                    assert!(difference <= allowance, "component equality failed at t={time}");
                    max_component_difference = max_component_difference.max(difference);
                    state_max_difference = state_max_difference.max(difference);
                    max_component_tolerance_fraction = max_component_tolerance_fraction.max(difference / allowance);
                    checked_real_components += 1;
                }
            }
            let spectral_norm = s.iter().map(|z| z.norm_sqr()).sum::<f64>();
            let auto_norm = a.iter().map(|z| z.norm_sqr()).sum::<f64>();
            for norm in [spectral_norm, auto_norm] {
                let error = (norm - initial_norm).abs();
                max_norm_error = max_norm_error.max(error);
                assert!(error <= norm_tolerance, "norm failed at t={time}");
            }
            validation_states.push(json!({"time": time, "spectral_norm_squared": spectral_norm,
                "auto_norm_squared": auto_norm, "max_component_difference": state_max_difference,
                "spectral": s.iter().map(|z| [z.re,z.im]).collect::<Vec<_>>(),
                "auto": a.iter().map(|z| [z.re,z.im]).collect::<Vec<_>>() }));
        }
        let validation_ns = start.elapsed().as_nanos();
        let start = Instant::now();
        black_box(query_batch(&spectral_state, &times, warmup));
        black_box(query_batch(&auto_state, &times, warmup));
        let warmup_ns = start.elapsed().as_nanos();
        let mut measurements = Vec::new();
        for batch in 0..batches {
            let spectral_first = (process_index + case_index + batch) % 2 == 0;
            let (s, a) = if spectral_first {
                let s = query_batch(&spectral_state, &times, queries);
                let a = query_batch(&auto_state, &times, queries);
                (s, a)
            } else {
                let a = query_batch(&auto_state, &times, queries);
                let s = query_batch(&spectral_state, &times, queries);
                (s, a)
            };
            assert!(s.0 > 0 && a.0 > 0);
            let checksum_allowance = checksum_absolute + checksum_relative * s.1.abs().max(a.1.abs());
            assert!((s.1 - a.1).abs() <= checksum_allowance, "timed checksums disagree");
            measurements.push(json!({"batch": batch, "spectral_first": spectral_first,
                "queries": queries, "spectral_ns": s.0, "auto_ns": a.0,
                "spectral_checksum": s.1, "auto_checksum": a.1}));
        }
        results.push(json!({"case": case, "input_fingerprint": fingerprint,
            "directed_adjacency_entries": lap.adjacency.len(),
            "graph_construction_ns": graph_construction_ns,
            "initial_generation_ns": initial_generation_ns,
            "initial_norm_squared": initial_norm,
            "auto_backend": backend_name(auto_plan.backend()),
            "spectral_backend": backend_name(spectral_plan.backend()),
            "plan_setup": setup, "state_preparation": preparation,
            "validation_ns": validation_ns, "warmup_ns": warmup_ns,
            "validation": {"checked_real_components": checked_real_components,
                "max_component_difference": max_component_difference,
                "max_component_tolerance_fraction": max_component_tolerance_fraction,
                "max_norm_error": max_norm_error, "states": validation_states},
            "query_measurements": measurements}));
    }
    println!("{}", serde_json::to_string(&json!({
        "schema": "gabriel.conditioned-walk.measurements.v1", "protocol": protocol,
        "process_index": process_index, "pid": std::process::id(), "cases": results,
        "scope": "Prepared state-vector queries only; not the existing all-pairs threshold scan or whole Gabriel engine."
    })).unwrap());
}
