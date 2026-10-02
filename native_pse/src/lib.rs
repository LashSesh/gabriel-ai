//! An embeddable Post-Symbolic Engine. Batches advance one ordered state machine.
//!
//! ```
//! use pse::{Config, Engine};
//! let mut engine = Engine::new(Config::default())?;
//! let step = engine.step(&[b"observation".to_vec()])?;
//! assert_eq!(step.tick, 1);
//! # Ok::<(), pse::Error>(())
//! ```
#![forbid(unsafe_code)]

/// Source-conditioned graph observations over immutable engine snapshots.
pub mod conditioned;

pub use pse_core::{ResonanceExplorationResult, ResonanceFingerprint};
pub use pse_evidence::{verify_crystal, VerifyError};
pub use pse_graph::{ObservationAdapter, ObserveError, PassthroughAdapter};
pub use pse_types::{Config, GateSnapshot, MeasurementContext, Observation, SemanticCrystal};

/// Optional operations on engine outputs, including feedback through CrystalAdapter.
pub mod operators {
    pub use pse_core::{
        bridge, compose, crystal_similarity, dual, interpolate, query, BridgeConfig, BridgeError,
        ComposeConfig, ComposeError, CrystalAdapter, QueryConfig,
    };
}

#[derive(Debug, thiserror::Error)]
pub enum Error {
    #[error("invalid configuration: {0}")]
    Configuration(String),
    #[error(transparent)]
    Execution(#[from] pse_core::EngineError),
    #[error("engine faulted after an execution error; reset and replay before continuing")]
    Faulted,
}

/// One attempted batch. An open gate is necessary but insufficient for a crystal.
pub struct Step {
    pub tick: u64,
    pub crystal: Option<SemanticCrystal>,
    /// None when warmup/cooldown returned before computing the gate.
    pub gate: Option<GateSnapshot>,
}

/// Read-only, inexpensive counters. History and archive are retained until reset/drop.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Statistics {
    pub ticks: u64,
    pub commits: u64,
    pub pattern_hits: u64,
    pub vertices: usize,
    pub edges: usize,
    pub observations: usize,
    pub faulted: bool,
}

/// One session, one caller at a time. Independent instances can run on caller-owned threads.
/// The adapter must be deterministic for deterministic replay.
pub struct Engine {
    state: pse_core::GlobalState,
    config: Config,
    adapter: Box<dyn ObservationAdapter>,
    faulted: bool,
}

impl Engine {
    /// Byte input with one source named `pse`. Use with_adapter for distinct entities/phases.
    pub fn new(config: Config) -> Result<Self, Error> {
        Self::with_adapter(config, PassthroughAdapter::new("pse"))
    }

    pub fn with_adapter(
        config: Config,
        adapter: impl ObservationAdapter + 'static,
    ) -> Result<Self, Error> {
        validate(&config)?;
        Ok(Self {
            state: pse_core::GlobalState::new(&config),
            config,
            adapter: Box::new(adapter),
            faulted: false,
        })
    }

    /// Process one batch synchronously. Err poisons this session, because the inherited
    /// state machine can already have advanced its tick before an adapter/persistence error.
    /// Reset and replay known-good inputs for recovery; no rollback is implied.
    pub fn step(&mut self, input: &[Vec<u8>]) -> Result<Step, Error> {
        if self.faulted {
            return Err(Error::Faulted);
        }
        self.state.last_gate = None;
        match pse_core::macro_step(&mut self.state, input, &self.config, self.adapter.as_ref()) {
            Ok(crystal) => Ok(Step {
                tick: self.state.commit_index,
                crystal,
                gate: self.state.last_gate.clone(),
            }),
            Err(error) => {
                self.faulted = true;
                Err(error.into())
            }
        }
    }

    /// Freeze the current observation graph for explicitly sourced CTQW queries.
    /// This does not advance the engine or replace its legacy commit statistics.
    /// A later step/reset does not change an already returned snapshot.
    pub fn conditioned_snapshot(
        &self,
        choice: conditioned::BackendChoice,
    ) -> Result<conditioned::ConditionedSnapshot, conditioned::ConditionedError> {
        if self.faulted {
            return Err(conditioned::ConditionedError::Faulted);
        }
        conditioned::ConditionedSnapshot::from_graph(
            &self.state.graph,
            self.state.commit_index,
            choice,
        )
    }

    pub fn statistics(&self) -> Statistics {
        Statistics {
            ticks: self.state.commit_index,
            commits: self.state.crystals_committed,
            pattern_hits: self.state.pattern_hits,
            vertices: self.state.graph.graph.node_count(),
            edges: self.state.graph.graph.edge_count(),
            observations: self.state.graph.history.len(),
            faulted: self.faulted,
        }
    }

    /// Immutable archive of outputs. A reset clears it.
    pub fn crystals(&self) -> &[SemanticCrystal] {
        self.state.archive.crystals()
    }
    pub fn config(&self) -> &Config {
        &self.config
    }

    /// Read the current topology, centroid, resonance and k nearest patterns.
    pub fn fingerprint(&self, k: usize) -> ResonanceFingerprint {
        pse_core::resonance_fingerprint(&self.state, &self.config, k)
    }

    /// Deterministically probe the current resonance landscape without changing state.
    pub fn explore(&self, steps: usize) -> ResonanceExplorationResult {
        pse_core::resonance_landscape_explorer(&self.state, &self.config, steps)
    }

    /// Load caller-trusted crystals into the similarity memory; this is a warm start,
    /// not restoration of graph, calibration, time or execution history.
    pub fn load_memory(&mut self, crystals: &[SemanticCrystal]) -> Result<usize, Error> {
        if self.faulted {
            return Err(Error::Faulted);
        }
        Ok(pse_core::load_memory_from_crystals(
            &mut self.state,
            crystals,
        ))
    }

    /// Clear all session state while preserving configuration and adapter.
    /// Stateful adapters must be reset/recreated by their owner for replay.
    pub fn reset(&mut self) {
        self.state = pse_core::GlobalState::new(&self.config);
        self.faulted = false;
    }
}

fn validate(config: &Config) -> Result<(), Error> {
    // Config currently contains no nullable fields; JSON maps nonfinite floats to null.
    fn finite(v: &serde_json::Value) -> bool {
        match v {
            serde_json::Value::Null => false,
            serde_json::Value::Array(a) => a.iter().all(finite),
            serde_json::Value::Object(o) => o.values().all(finite),
            _ => true,
        }
    }
    let value = serde_json::to_value(config).map_err(|e| Error::Configuration(e.to_string()))?;
    if !finite(&value) {
        return Err(Error::Configuration(
            "all numerical values must be finite".into(),
        ));
    }
    if !config.carrier.use_metatron_ladder && config.carrier.num_carriers == 0 {
        return Err(Error::Configuration(
            "at least one carrier is required".into(),
        ));
    }
    if config.calibration.enabled
        && (config.calibration.window == 0
            || !(0.0..1.0).contains(&config.calibration.target_pass_rate))
    {
        return Err(Error::Configuration(
            "calibration requires a positive window and rate in [0,1)".into(),
        ));
    }
    if config.persistence.max_vertices == 0 || config.temporal.dt2 <= 0.0 {
        return Err(Error::Configuration(
            "max_vertices and dt2 must be positive".into(),
        ));
    }
    Ok(())
}
