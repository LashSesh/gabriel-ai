//! Bounded exact-JSON process bridge: the specified state readout of the engine over an
//! observation stream with declared phases and amplitudes (Gabriel ADR-19).
//!
//! Crystal commits and persistence decay are disabled, so the graph stays the pure
//! co-observation graph and every reported quantity is a declared function of the stream and
//! the profile: the per-vertex 5D embedding, the batch data helix, the active carrier (on a
//! half-turn grid of `carriers` phases) and its mandorla, the eight gate metrics and the gate
//! verdict against the declared thresholds. Input
//! must be compact, sorted-key JSON (one optional terminal newline). This trusted-code adapter
//! produces model readouts, not probabilities, detections of anything outside the model, or
//! crystal-commit evidence.
use pse_core::{macro_step, GlobalState};
use pse_fmath::{Fmath, ARITHMETIC_PROFILE};
use pse_graph::{ObservationAdapter, ObserveError};
use pse_types::{content_address_raw, CarrierInstance, Config, MandorlaState, MeasurementContext, Observation, TubusCoord};
use serde_json::{json, Value};
use std::collections::BTreeSet;
use std::io::{self, Read};

const SCHEMA: &str = "gabriel-engine-readout/v1";
const MAX_BYTES: usize = 4 * 1024 * 1024;
const MAX_NODES: usize = 64;
const MAX_BATCHES: usize = 128;
const MAX_CARRIERS: u64 = 64;
const TAU: f64 = std::f64::consts::TAU;

type Result<T> = std::result::Result<T, String>;

fn fields(value: &Value, names: &[&str]) -> Result<()> {
    let object = value.as_object().ok_or("expected JSON object")?;
    if object.len() != names.len() || names.iter().any(|name| !object.contains_key(*name)) {
        return Err(format!("fields must be exactly {names:?}"));
    }
    Ok(())
}
fn array(value: &Value) -> Result<&Vec<Value>> {
    value.as_array().ok_or("expected JSON array".into())
}
fn number(value: &Value) -> Result<f64> {
    let s = value.as_str().ok_or("binary64 must use bit-string encoding")?;
    if s.len() != 16 || !s.bytes().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b)) {
        return Err("binary64 requires sixteen lowercase hexadecimal bit digits".into());
    }
    let bits = u64::from_str_radix(s, 16).map_err(|_| "invalid binary64 bits")?;
    let value = f64::from_bits(bits);
    if !value.is_finite() {
        return Err("nonfinite binary64 value".into());
    }
    Ok(value)
}
fn bits(value: f64) -> Result<String> {
    if !value.is_finite() {
        return Err("nonfinite native output".into());
    }
    Ok(format!("{:016x}", value.to_bits()))
}
fn unit(value: &Value, name: &str) -> Result<f64> {
    let x = number(value)?;
    if !(0.0..=1.0).contains(&x) {
        return Err(format!("{name} must lie in [0,1]"));
    }
    Ok(x)
}
fn nonnegative(value: &Value, name: &str) -> Result<f64> {
    let x = number(value)?;
    if x < 0.0 {
        return Err(format!("{name} must be non-negative"));
    }
    Ok(x)
}
fn positive(value: &Value, name: &str) -> Result<f64> {
    let x = number(value)?;
    if x <= 0.0 {
        return Err(format!("{name} must be positive"));
    }
    Ok(x)
}
fn vertex(entity: usize) -> u64 {
    pse_graph::derive_vertex_id(&format!("sensor-{entity}"))
}

/// One declared observation: entity, phase in [0, 2π) and amplitude in [0, 1], both as bits.
struct Declared {
    entity: usize,
    phase: f64,
    amplitude: f64,
}

struct StreamAdapter;
impl ObservationAdapter for StreamAdapter {
    fn source_id(&self) -> &str {
        "gabriel-declared-stream-adapter/v1"
    }
    fn canonicalize(&self, raw: &[u8], context: &MeasurementContext) -> std::result::Result<Observation, ObserveError> {
        let v: Value = serde_json::from_slice(raw).map_err(|e| ObserveError::Canonicalize(e.to_string()))?;
        let i = v["entity"].as_u64().ok_or_else(|| ObserveError::Canonicalize("entity".into()))?;
        let tick = v["tick"].as_u64().ok_or_else(|| ObserveError::Canonicalize("tick".into()))?;
        let phase = number(&v["phase_bits"]).map_err(ObserveError::Canonicalize)?;
        let amplitude = number(&v["amplitude_bits"]).map_err(ObserveError::Canonicalize)?;
        Ok(Observation {
            timestamp: tick as f64,
            source_id: format!("sensor-{i}"),
            provenance: Default::default(),
            payload: raw.to_vec(),
            context: context.clone(),
            digest: content_address_raw(raw),
            schema_version: "1".into(),
            phase_hint: Some(phase),
            amplitude_hint: Some(amplitude),
        })
    }
}

fn batches(value: &Value) -> Result<Vec<Vec<Declared>>> {
    let entries = array(value)?;
    if entries.is_empty() || entries.len() > MAX_BATCHES {
        return Err("batch history exceeds bounds".into());
    }
    let mut all = BTreeSet::new();
    let mut out = Vec::with_capacity(entries.len());
    for batch in entries {
        let items = array(batch)?;
        if items.is_empty() || items.len() > MAX_NODES {
            return Err("batch exceeds bounds".into());
        }
        let mut seen = BTreeSet::new();
        let mut declared = Vec::with_capacity(items.len());
        for item in items {
            fields(item, &["entity", "phase_bits", "amplitude_bits"])?;
            let entity = item["entity"].as_u64().ok_or("entity must be an unsigned integer")?;
            if entity >= MAX_NODES as u64 {
                return Err("entity outside [0,63]".into());
            }
            if !seen.insert(entity) {
                return Err("duplicate entity".into());
            }
            let phase = number(&item["phase_bits"])?;
            if !(0.0..TAU).contains(&phase) {
                return Err("phase must lie in [0,2pi)".into());
            }
            let amplitude = unit(&item["amplitude_bits"], "amplitude")?;
            all.insert(entity);
            declared.push(Declared { entity: entity as usize, phase, amplitude });
        }
        out.push(declared);
    }
    if all.len() > MAX_NODES {
        return Err("total entity capacity exceeded".into());
    }
    Ok(out)
}

fn profile(value: &Value) -> Result<Config> {
    fields(value, &["carriers", "adaptive_carrier", "lambda_bits", "mu_r_bits", "eta_r_bits", "dt2_bits", "normalization", "thresholds"])?;
    let carriers = value["carriers"].as_u64().ok_or("carriers must be an unsigned integer")?;
    if !(1..=MAX_CARRIERS).contains(&carriers) {
        return Err("carriers outside [1,64]".into());
    }
    let adaptive = value["adaptive_carrier"].as_bool().ok_or("adaptive_carrier must be a boolean")?;
    let normalization = &value["normalization"];
    fields(normalization, &["mu_d", "mu_j", "lambda_r", "lambda_p", "lambda_seam", "gamma_d", "gamma_q", "gamma_r", "lambda_c", "lambda_e"])?;
    let thresholds = &value["thresholds"];
    fields(thresholds, &["d", "q", "r", "g", "j", "p", "n", "k"])?;
    let mut c = Config::default();
    // the reviewed profile: no persistence decay, no crystal commit, no calibration, no falsification
    c.persistence.lambda_decay = 0.0;
    c.consensus.min_crystal_tick = u64::MAX;
    c.calibration.enabled = false;
    c.falsification.enabled = false;
    c.carrier.num_carriers = carriers as usize;
    c.carrier.use_metatron_ladder = false;
    c.carrier.adaptive = adaptive;
    c.carrier.lambda = nonnegative(&value["lambda_bits"], "lambda")?;
    c.carrier.mu_r = nonnegative(&value["mu_r_bits"], "mu_r")?;
    c.carrier.eta_r = nonnegative(&value["eta_r_bits"], "eta_r")?;
    c.temporal.dt2 = positive(&value["dt2_bits"], "dt2")?;
    c.normalization.mu_d = positive(&normalization["mu_d"], "mu_d")?;
    c.normalization.mu_j = positive(&normalization["mu_j"], "mu_j")?;
    c.normalization.lambda_r = nonnegative(&normalization["lambda_r"], "lambda_r")?;
    c.normalization.lambda_p = nonnegative(&normalization["lambda_p"], "lambda_p")?;
    c.normalization.lambda_seam = nonnegative(&normalization["lambda_seam"], "lambda_seam")?;
    c.normalization.gamma_d = nonnegative(&normalization["gamma_d"], "gamma_d")?;
    c.normalization.gamma_q = nonnegative(&normalization["gamma_q"], "gamma_q")?;
    c.normalization.gamma_r = nonnegative(&normalization["gamma_r"], "gamma_r")?;
    c.normalization.lambda_c = nonnegative(&normalization["lambda_c"], "lambda_c")?;
    c.normalization.lambda_e = nonnegative(&normalization["lambda_e"], "lambda_e")?;
    c.thresholds.d = unit(&thresholds["d"], "threshold d")?;
    c.thresholds.q = unit(&thresholds["q"], "threshold q")?;
    c.thresholds.r = unit(&thresholds["r"], "threshold r")?;
    c.thresholds.g = unit(&thresholds["g"], "threshold g")?;
    c.thresholds.j = unit(&thresholds["j"], "threshold j")?;
    c.thresholds.p = unit(&thresholds["p"], "threshold p")?;
    c.thresholds.n = unit(&thresholds["n"], "threshold n")?;
    c.thresholds.k = unit(&thresholds["k"], "threshold k")?;
    Ok(c)
}

fn execute(job: Value) -> Result<Value> {
    fields(&job, &["schema", "batches", "profile"])?;
    if job["schema"] != SCHEMA {
        return Err("unsupported schema".into());
    }
    let stream = batches(&job["batches"])?;
    let config = profile(&job["profile"])?;
    let mut state = GlobalState::new(&config);
    // The readout profile's carrier grid spans a half turn (phases pi * i / n): the phase lock
    // (1 + cos 2(phi_data - phi_carrier)) / 2 is pi-periodic in the carrier phase and every
    // carrier already contains its antiphase partner, so a full-turn grid holds each carrier
    // twice and leaves the adaptive selection to last-bit rounding between the duplicates.
    state.phase_ladder = (0..config.carrier.num_carriers)
        .map(|i| {
            let phi = std::f64::consts::PI * i as f64 / config.carrier.num_carriers as f64;
            let alpha = TubusCoord { tau: 0.0, phi, r: 1.0 };
            let beta = TubusCoord { tau: 0.0, phi: (phi + std::f64::consts::PI) % TAU, r: 1.0 };
            let raw = (alpha.phi - beta.phi).abs();
            let delta_phi = raw.min(TAU - raw);
            let kappa = (-1.0 * delta_phi).dexp() * (-1.0 * alpha.r * alpha.r).dexp();
            CarrierInstance { helix_a: alpha, helix_b: beta, mandorla: MandorlaState { tau: 0.0, r: 1.0, delta_phi, kappa }, resonance: 0.0, offset: phi }
        })
        .collect();
    let mut ticks = Vec::with_capacity(stream.len());
    let mut observations = 0usize;
    for (index, batch) in stream.iter().enumerate() {
        let raw = batch
            .iter()
            .map(|o| {
                serde_json::to_vec(&json!({"entity": o.entity, "tick": index, "phase_bits": bits(o.phase)?, "amplitude_bits": bits(o.amplitude)?}))
                    .map_err(|e| e.to_string())
            })
            .collect::<Result<Vec<_>>>()?;
        observations += raw.len();
        let crystal = macro_step(&mut state, &raw, &config, &StreamAdapter).map_err(|e| e.to_string())?;
        if crystal.is_some() || state.crystals_committed != 0 {
            return Err("unexpected crystal commit under the readout profile".into());
        }
        let metrics = state.last_metrics.as_ref().ok_or("metrics unavailable after the step")?;
        let gate = metrics.gate_snapshot(&config.thresholds);
        let helix = state.last_data_helix.as_ref().ok_or("data helix unavailable after the step")?;
        let carrier = state.phase_ladder.get(state.active_carrier).ok_or("active carrier outside the ladder")?;
        let mut vertices = Vec::new();
        let mut embedding = Vec::new();
        for data in state.graph.graph.node_weights() {
            let entity = (0..MAX_NODES).find(|&i| vertex(i) == data.id).ok_or("unmapped native vertex")?;
            vertices.push(entity);
            let e = state.graph.embedding.get(&data.id).ok_or("vertex without embedding")?;
            embedding.push(json!([bits(e.p)?, bits(e.rho)?, bits(e.omega)?, bits(e.chi)?, bits(e.eta)?]));
        }
        ticks.push(json!({
            "tick": state.commit_index,
            "vertices": vertices,
            "edges": state.graph.graph.edge_count(),
            "helix": {"phi_bits": bits(helix.phi)?, "r_bits": bits(helix.r)?},
            "carrier": {"index": state.active_carrier, "phi_bits": bits(carrier.helix_a.phi)?,
                        "kappa_bits": bits(carrier.mandorla.kappa)?, "delta_phi_bits": bits(carrier.mandorla.delta_phi)?},
            "metrics": {"d": bits(gate.d)?, "q": bits(gate.q)?, "r": bits(gate.r)?, "g": bits(gate.g)?,
                        "j": bits(gate.j)?, "p": bits(gate.p)?, "n": bits(gate.n)?, "k": bits(gate.k)?},
            "kairos": gate.kairos,
            "embedding": embedding,
        }));
    }
    let bound = json!({"batches": job["batches"], "profile": job["profile"], "ticks": ticks});
    let identity = content_address_raw(&serde_json::to_vec(&bound).map_err(|e| e.to_string())?)
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect::<String>();
    Ok(json!({
        "schema": SCHEMA,
        "arithmetic": ARITHMETIC_PROFILE,
        "engine": {"ticks": state.commit_index, "commits": state.crystals_committed, "vertices": state.graph.graph.node_count(),
                   "edges": state.graph.graph.edge_count(), "observations": observations, "faulted": false},
        "identity": identity,
        "ticks": ticks,
    }))
}

fn main() {
    let mut input = Vec::new();
    if io::stdin().take(MAX_BYTES as u64 + 1).read_to_end(&mut input).is_err() || input.len() > MAX_BYTES {
        eprintln!("input exceeds {MAX_BYTES} bytes or is unreadable");
        std::process::exit(1);
    }
    let text = match std::str::from_utf8(&input) {
        Ok(text) => text.strip_suffix('\n').unwrap_or(text),
        Err(_) => {
            eprintln!("input is not UTF-8");
            std::process::exit(1);
        }
    };
    let job: Value = match serde_json::from_str(text) {
        Ok(job) => job,
        Err(e) => {
            eprintln!("invalid JSON: {e}");
            std::process::exit(1);
        }
    };
    if serde_json::to_string(&job).ok().as_deref() != Some(text) {
        eprintln!("input must be compact, sorted-key JSON");
        std::process::exit(1);
    }
    match execute(job) {
        Ok(output) => println!("{}", serde_json::to_string(&output).unwrap()),
        Err(message) => {
            eprintln!("{message}");
            std::process::exit(1);
        }
    }
}
