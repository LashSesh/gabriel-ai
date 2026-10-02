use pse::{
    Config, Engine, Error, MeasurementContext, Observation, ObservationAdapter, ObserveError,
};

struct Failing;
impl ObservationAdapter for Failing {
    fn source_id(&self) -> &str {
        "failing"
    }
    fn canonicalize(&self, _: &[u8], _: &MeasurementContext) -> Result<Observation, ObserveError> {
        Err(ObserveError::Canonicalize("test failure".into()))
    }
}

#[test]
fn invalid_config_is_an_error_before_state_allocation() {
    let mut c = Config::default();
    c.carrier.num_carriers = 0;
    assert!(matches!(Engine::new(c), Err(Error::Configuration(_))));
    let mut c = Config::default();
    c.temporal.dt2 = f64::NAN;
    assert!(matches!(Engine::new(c), Err(Error::Configuration(_))));
    let mut c = Config::default();
    c.calibration.enabled = true;
    c.calibration.window = 0;
    assert!(matches!(Engine::new(c), Err(Error::Configuration(_))));
    assert!(Engine::new(Config::preset_streaming()).is_ok());
    assert!(Engine::new(Config::preset_planning()).is_ok());
    assert!(Engine::new(Config::preset_anomaly_detection()).is_ok());
}

#[test]
fn failed_step_requires_explicit_recovery() {
    let mut e = Engine::with_adapter(Config::default(), Failing).unwrap();
    assert!(matches!(e.step(&[vec![1]]), Err(Error::Execution(_))));
    assert_eq!(e.statistics().ticks, 1);
    assert!(e.statistics().faulted);
    assert!(matches!(e.step(&[]), Err(Error::Faulted)));
    assert_eq!(e.statistics().ticks, 1);
    e.reset();
    assert!(!e.statistics().faulted);
    assert_eq!(e.statistics().ticks, 0);
    assert!(e.step(&[]).is_ok());
}

#[test]
fn rejected_ticks_and_reset_are_reproducible() {
    let mut e = Engine::new(Config::default()).unwrap();
    for _ in 0..2 {
        for tick in 1..=10 {
            let s = e.step(&[b"stable bytes".to_vec()]).unwrap();
            assert_eq!(s.tick, tick);
            if !s.gate.as_ref().unwrap().kairos {
                assert!(s.crystal.is_none());
            }
        }
        assert_eq!(e.statistics().observations, 10);
        e.reset();
    }
}

#[test]
fn digest_mismatch_is_not_trusted() {
    struct Corrupt;
    impl ObservationAdapter for Corrupt {
        fn source_id(&self) -> &str {
            "corrupt"
        }
        fn canonicalize(
            &self,
            raw: &[u8],
            ctx: &MeasurementContext,
        ) -> Result<Observation, ObserveError> {
            let mut o = pse::PassthroughAdapter::new("corrupt").canonicalize(raw, ctx)?;
            o.digest[0] ^= 1;
            Ok(o)
        }
    }
    let mut e = Engine::with_adapter(Config::default(), Corrupt).unwrap();
    assert!(matches!(e.step(&[vec![1]]), Err(Error::Execution(_))));
    assert_eq!(e.statistics().observations, 0);
}
