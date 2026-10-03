#[allow(dead_code)]
#[path = "../benches/engine.rs"]
mod harness;

/// Historical fixture, generated on Windows with that platform's C libm. Its 78 engine-state
/// digests include quantities computed through transcendental functions (data helix, phase
/// ladder, gate metrics), whose last-bit results differ between C libraries; one unit in the
/// last place of `sin` alone changes 73 of the 78 digests (Gabriel determinism study,
/// evidence/pse/determinism). The fixture is retained unchanged and compared only on request:
/// `cargo test --release -- --ignored full_state_matches_original_golden_fixture`.
#[test]
#[ignore = "platform-bound historical fixture (Windows C libm); see the platform-independent fixture below"]
fn full_state_matches_original_golden_fixture() {
    let expected: serde_json::Value =
        serde_json::from_str(include_str!("fixtures/original.json")).unwrap();
    assert_eq!(harness::golden(), expected);
}

/// Platform-independent fixture: the same cases under the pure-Rust libm arithmetic of
/// `pse-fmath` (the default build), which depends on the locked crates only and not on the
/// host's C library. Regenerate with `cargo run --release --example golden_fixture` after an
/// intentional model change and record the reason.
#[test]
#[cfg_attr(feature = "platform-libm", ignore = "the platform-libm feature reproduces the host C library, not the fixture")]
fn full_state_matches_platform_independent_golden_fixture() {
    let expected: serde_json::Value =
        serde_json::from_str(include_str!("fixtures/pure_libm.json")).unwrap();
    assert_eq!(pse_fmath::ARITHMETIC_PROFILE, "pure-rust-libm");
    let actual = harness::golden();
    assert_eq!(actual["engine"], expected["engine"]);
    assert_eq!(actual["graphs"], expected["graphs"]);
}

#[test]
fn real_commits_replay_and_parallel_instances_match_full_bytes() {
    fn run() -> Vec<Vec<u8>> {
        let mut engine =
            pse::Engine::with_adapter(harness::configuration("commit"), harness::SensorAdapter)
                .unwrap();
        let mut outputs = Vec::new();
        for batch in harness::batches(8, 6) {
            if let Some(c) = engine.step(&batch).unwrap().crystal {
                outputs.push(serde_json::to_vec(&c).unwrap());
            }
        }
        assert!(!outputs.is_empty(), "replay must exercise real commits");
        assert_eq!(outputs.len(), engine.crystals().len());
        outputs
    }
    let expected = run();
    let handles: Vec<_> = (0..4).map(|_| std::thread::spawn(run)).collect();
    for h in handles {
        assert_eq!(expected, h.join().unwrap());
    }
}

#[test]
fn cooldown_does_not_report_a_previous_ticks_gate() {
    let mut engine =
        pse::Engine::with_adapter(harness::configuration("cooldown"), harness::SensorAdapter)
            .unwrap();
    let mut checked = false;
    for batch in harness::batches(8, 9) {
        let step = engine.step(&batch).unwrap();
        if step.tick < 3 || step.tick == 5 {
            assert!(step.gate.is_none());
            checked = true;
        }
    }
    assert!(checked);
}
