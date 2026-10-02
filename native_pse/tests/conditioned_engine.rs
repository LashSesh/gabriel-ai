#[allow(dead_code)]
#[path = "../benches/engine.rs"]
mod harness;

use pse::{Config, Engine, ObservationAdapter, ObserveError, MeasurementContext, Observation};
use pse::conditioned::{BackendChoice, Complex, ConditionedError, RegionBackend, RegionChoice,
                       WalkBackend, WalkError};

fn input(n: usize, ticks: usize) -> Vec<Vec<Vec<u8>>> { harness::batches(n, ticks) }
fn config() -> Config {
    let mut config = Config::default();
    config.persistence.lambda_decay = 0.0;
    config.consensus.min_crystal_tick = u64::MAX;
    config
}
fn engine(n: usize) -> Engine {
    let mut engine = Engine::with_adapter(config(), harness::SensorAdapter).unwrap();
    engine.step(&input(n, 1)[0]).unwrap();
    engine
}
fn source(n: usize) -> Vec<Complex<f64>> {
    (0..n).map(|i| Complex::new((3*i+1) as f64 / 11.0, (i as f64 - 2.0) / 7.0)).collect()
}
fn close(a: f64, b: f64) { assert!((a-b).abs() < 2e-10, "{a} != {b}"); }

#[test]
fn actual_ingestion_selects_clique_and_preserves_snapshot_after_step_and_reset() {
    let mut engine = engine(13);
    let snapshot = engine.conditioned_snapshot(BackendChoice::Auto).unwrap();
    assert_eq!(snapshot.backend(), WalkBackend::CompleteGraph);
    assert_eq!(snapshot.tick(), 1);
    assert_eq!(snapshot.vertex_ids().len(), 13);
    assert!(snapshot.laplacian().adjacency.iter().all(|e| e.2 == 0.5));
    let initial = source(13);
    let prepared = snapshot.prepare_state(&initial).unwrap();
    let before = prepared.state_at(0.4).unwrap();
    let old_identity = *snapshot.identity();
    engine.step(&input(13, 2)[1]).unwrap();
    let after = engine.conditioned_snapshot(BackendChoice::Auto).unwrap();
    assert_eq!(after.tick(), 2);
    assert_ne!(after.identity(), &old_identity);
    assert_eq!(after.laplacian().degree, snapshot.laplacian().degree);
    engine.reset();
    assert_eq!(snapshot.identity(), &old_identity);
    assert_eq!(prepared.state_at(0.4).unwrap(), before);
    assert!(matches!(engine.conditioned_snapshot(BackendChoice::Auto),
        Err(ConditionedError::Walk(WalkError::EmptyGraph))));
}

#[test]
fn snapshot_auto_spectral_and_fixed_region_agree_on_same_ingested_operator() {
    for n in [2, 7, 13, 32, 64] {
        let engine = engine(n);
        let auto = engine.conditioned_snapshot(BackendChoice::Auto).unwrap();
        let spectral = engine.conditioned_snapshot(BackendChoice::Spectral).unwrap();
        assert_eq!(auto.identity(), spectral.identity());
        let initial = source(n);
        let a = auto.prepare_state(&initial).unwrap();
        let b = spectral.prepare_state(&initial).unwrap();
        let targets: Vec<_> = auto.vertex_ids().iter().step_by(2).copied().collect();
        let direct = a.prepare_region(&targets, RegionChoice::Auto).unwrap();
        let full = a.prepare_region(&targets, RegionChoice::StateReadout).unwrap();
        assert_eq!(direct.backend(), RegionBackend::CompleteGraph);
        assert_eq!(full.backend(), RegionBackend::StateReadout);
        for time in [-0.3, 0.0, 0.03, 0.4, 3.0] {
            let ar = a.readout_at(time).unwrap();
            let br = b.readout_at(time).unwrap();
            close(ar.norm_ratio, 1.0);
            for (x, y) in ar.amplitudes.iter().zip(br.amplitudes) {
                close(x.re, y.re); close(x.im, y.im);
            }
            close(direct.mass_at(time).unwrap(), b.target_mass_at(time, &targets).unwrap());
            close(direct.mass_at(time).unwrap(), full.mass_at(time).unwrap());
        }
    }
}

#[test]
fn sparse_graph_from_pair_batches_uses_fallback_without_manual_graph_edits() {
    let mut engine = Engine::with_adapter(config(), harness::SensorAdapter).unwrap();
    let all = &input(7, 1)[0];
    for pair in all.windows(2) { engine.step(pair).unwrap(); }
    let snapshot = engine.conditioned_snapshot(BackendChoice::Auto).unwrap();
    assert_eq!(snapshot.backend(), WalkBackend::Spectral);
    let initial = source(7);
    let prepared = snapshot.prepare_state(&initial).unwrap();
    let targets = [snapshot.vertex_ids()[2], snapshot.vertex_ids()[4]];
    let region = prepared.prepare_region(&targets, RegionChoice::Auto).unwrap();
    assert_eq!(region.backend(), RegionBackend::StateReadout);
    close(region.mass_at(0.2).unwrap(), prepared.target_mass_at(0.2, &targets).unwrap());
}

#[test]
fn labelled_sources_and_target_sets_cannot_alias_or_silently_fill_missing_vertices() {
    let engine = engine(3);
    let snapshot = engine.conditioned_snapshot(BackendChoice::Auto).unwrap();
    let values = source(3);
    let mut named: Vec<_> = snapshot.vertex_ids().iter().copied().zip(values.clone()).collect();
    named.reverse();
    let prepared = snapshot.prepare_named_state(&named).unwrap();
    assert_eq!(prepared.state_at(0.0).unwrap(), snapshot.prepare_state(&values).unwrap().state_at(0.0).unwrap());
    let id = snapshot.vertex_ids()[0];
    assert!(matches!(prepared.prepare_region(&[id,id], RegionChoice::Auto),
        Err(ConditionedError::DuplicateVertex(_))));
    assert!(matches!(prepared.target_mass_at(0.0, &[0]), Err(ConditionedError::UnknownVertex(0))));
    assert!(matches!(snapshot.prepare_named_state(&named[..2]),
        Err(ConditionedError::Walk(WalkError::DimensionMismatch { .. }))));
    named[0].0 = named[1].0;
    assert!(matches!(snapshot.prepare_named_state(&named), Err(ConditionedError::DuplicateVertex(_))));
    assert!(matches!(snapshot.prepare_state(&vec![Complex::new(0.0,0.0);3]), Err(ConditionedError::ZeroSource)));
    assert!(matches!(prepared.target_mass_at(f64::NAN, &[]),
        Err(ConditionedError::Walk(WalkError::NonFiniteTime))));
    close(prepared.prepare_region(&[], RegionChoice::Auto).unwrap().mass_at(0.3).unwrap(),0.0);
    close(prepared.prepare_region(snapshot.vertex_ids(), RegionChoice::Auto).unwrap().mass_at(0.3).unwrap(),1.0);
}

#[test]
fn source_conditioning_preserves_stationary_controls_and_complex_interference_sign() {
    let engine = engine(2);
    let snapshot = engine.conditioned_snapshot(BackendChoice::Auto).unwrap();
    let target = [snapshot.vertex_ids()[0]];
    for initial in [vec![Complex::new(1.0,0.0);2],
                    vec![Complex::new(1.0,0.0),Complex::new(-1.0,0.0)]] {
        let prepared = snapshot.prepare_state(&initial).unwrap();
        let region = prepared.prepare_region(&target,RegionChoice::Auto).unwrap();
        close(region.mass_at(0.7).unwrap(),0.5);
    }
    let initial = [Complex::new(1.0,0.0),Complex::new(0.0,1.0)];
    let prepared = snapshot.prepare_state(&initial).unwrap();
    let region = prepared.prepare_region(&target,RegionChoice::Auto).unwrap();
    // L=.5[[1,-1],[-1,1]], exp(-itL)[1,i] gives p0=(1-sin t)/2.
    close(region.mass_at(0.7).unwrap(),(1.0-0.7_f64.sin())/2.0);
    close(region.mass_at(-0.7).unwrap(),(1.0+0.7_f64.sin())/2.0);
    let scaled = [Complex::new(0.0,3.0),Complex::new(-3.0,0.0)];
    let other = snapshot.prepare_state(&scaled).unwrap();
    close(other.target_mass_at(0.7,&target).unwrap(), region.mass_at(0.7).unwrap());
}

#[test]
fn querying_between_real_commits_does_not_change_crystal_bytes_or_statistics() {
    let mut config = harness::configuration("commit");
    config.persistence.lambda_decay = 0.0;
    let mut baseline = Engine::with_adapter(config.clone(),harness::SensorAdapter).unwrap();
    let mut observed = Engine::with_adapter(config,harness::SensorAdapter).unwrap();
    let mut commits = 0;
    for batch in input(8,6) {
        let a = baseline.step(&batch).unwrap();
        let b = observed.step(&batch).unwrap();
        assert_eq!(serde_json::to_vec(&a.crystal).unwrap(),serde_json::to_vec(&b.crystal).unwrap());
        if a.crystal.is_some() { commits += 1; }
        let before = observed.statistics();
        let snapshot = observed.conditioned_snapshot(BackendChoice::Auto).unwrap();
        let state = source(snapshot.vertex_ids().len());
        let prepared = snapshot.prepare_state(&state).unwrap();
        prepared.target_mass_at(0.2,&snapshot.vertex_ids()[..2]).unwrap();
        assert_eq!(before, observed.statistics());
        assert_eq!(baseline.statistics(), observed.statistics());
    }
    assert!(commits > 0);
    assert_eq!(serde_json::to_vec(baseline.crystals()).unwrap(),serde_json::to_vec(observed.crystals()).unwrap());
}

#[test]
fn faulted_engine_refuses_new_snapshots() {
    struct Reject;
    impl ObservationAdapter for Reject {
        fn source_id(&self)->&str { "reject" }
        fn canonicalize(&self,_:&[u8],_:&MeasurementContext)->Result<Observation,ObserveError> {
            Err(ObserveError::Canonicalize("intentional rejection".into()))
        }
    }
    let mut engine = Engine::with_adapter(config(),Reject).unwrap();
    assert!(engine.step(&[vec![1]]).is_err());
    assert!(matches!(engine.conditioned_snapshot(BackendChoice::Auto),Err(ConditionedError::Faulted)));
}

#[test]
fn normalized_observer_handles_subnormal_and_near_maximum_sources_before_evolution() {
    let engine = engine(2);
    let snapshot = engine.conditioned_snapshot(BackendChoice::Auto).unwrap();
    let target = [snapshot.vertex_ids()[1]];
    // Ingested L has w=.5; complete transfer occurs at t=pi.
    for magnitude in [f64::from_bits(1), f64::MIN_POSITIVE, 1.0, f64::MAX] {
        let initial = [Complex::new(magnitude,0.0),Complex::new(0.0,0.0)];
        let prepared = snapshot.prepare_state(&initial).unwrap();
        let direct = prepared.prepare_region(&target,RegionChoice::Auto).unwrap();
        let state = prepared.prepare_region(&target,RegionChoice::StateReadout).unwrap();
        close(direct.mass_at(std::f64::consts::PI).unwrap(),1.0);
        close(state.mass_at(std::f64::consts::PI).unwrap(),1.0);
        close(prepared.readout_at(std::f64::consts::PI).unwrap().norm_ratio,1.0);
        assert_eq!(prepared.source_scale(),magnitude);
        assert_eq!(prepared.scaled_source_squared_norm(),1.0);
    }
}
