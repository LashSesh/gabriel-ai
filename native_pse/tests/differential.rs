#[allow(dead_code)]
#[path = "../benches/engine.rs"]
mod harness;

#[test]
fn full_state_matches_original_golden_fixture() {
    let expected: serde_json::Value =
        serde_json::from_str(include_str!("fixtures/original.json")).unwrap();
    assert_eq!(harness::golden(), expected);
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
