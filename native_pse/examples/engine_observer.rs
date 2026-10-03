//! Bounded exact-JSON process bridge for Gabriel's existing SQLite owner.
//! Input must be compact, sorted-key JSON (one optional terminal newline).
//! This trusted-code adapter produces graph model observations, not calibrated
//! probabilities, financial forecasts or crystal-commit evidence.
use pse::{Config, Engine, MeasurementContext, Observation, ObservationAdapter, ObserveError};
use pse::conditioned::{BackendChoice, Complex, RegionChoice, RegionBackend, WalkBackend};
use pse_types::content_address_raw;
use serde_json::{json, Value};
use std::collections::BTreeSet;
use std::io::{self, Read};

const SCHEMA: &str = "gabriel-engine-observer/v1";
const MAX_BYTES: usize = 4 * 1024 * 1024;
const MAX_NODES: usize = 64;
const MAX_BATCHES: usize = 128;
const MAX_QUERIES: usize = 256;

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
fn entity(value: &Value) -> Result<usize> {
    let value = value.as_u64().ok_or("entity must be an unsigned integer")?;
    if value >= MAX_NODES as u64 { return Err("entity outside [0,63]".into()); }
    Ok(value as usize)
}
fn entities(value: &Value, nonempty: bool) -> Result<Vec<usize>> {
    let entries = array(value)?;
    if entries.len() > MAX_NODES || (nonempty && entries.is_empty()) {
        return Err("entity list exceeds bounds".into());
    }
    let values = entries.iter().map(entity).collect::<Result<Vec<_>>>()?;
    if values.iter().copied().collect::<BTreeSet<_>>().len() != values.len() {
        return Err("duplicate entity".into());
    }
    Ok(values)
}
fn number(value: &Value) -> Result<f64> {
    let s = value.as_str().ok_or("binary64 must use bit-string encoding")?;
    if s.len() != 16 || !s.bytes().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b)) {
        return Err("binary64 requires sixteen lowercase hexadecimal bit digits".into());
    }
    let bits = u64::from_str_radix(s, 16).map_err(|_| "invalid binary64 bits")?;
    let value = f64::from_bits(bits);
    if !value.is_finite() { return Err("nonfinite binary64 value".into()); }
    Ok(value)
}
fn bits(value: f64) -> Result<String> {
    if !value.is_finite() { return Err("nonfinite native output".into()); }
    Ok(format!("{:016x}", value.to_bits()))
}
fn vertex(entity: usize) -> u64 {
    pse_graph::derive_vertex_id(&format!("sensor-{entity}"))
}
struct SensorAdapter;
impl ObservationAdapter for SensorAdapter {
    fn source_id(&self) -> &str { "gabriel-synthetic-sensor-adapter/v1" }
    fn canonicalize(&self, raw: &[u8], context: &MeasurementContext)
        -> std::result::Result<Observation, ObserveError> {
        let v: Value = serde_json::from_slice(raw)
            .map_err(|e| ObserveError::Canonicalize(e.to_string()))?;
        let i = v["entity"].as_u64().ok_or_else(|| ObserveError::Canonicalize("entity".into()))?;
        let tick = v["tick"].as_u64().ok_or_else(|| ObserveError::Canonicalize("tick".into()))?;
        Ok(Observation { timestamp: tick as f64, source_id: format!("sensor-{i}"),
            provenance: Default::default(), payload: raw.to_vec(), context: context.clone(),
            digest: content_address_raw(raw), schema_version: "1".into(), phase_hint: Some(0.0), amplitude_hint: None })
    }
}
fn execute(job: Value) -> Result<Value> {
    fields(&job, &["schema", "backend", "batches", "queries"])?;
    if job["schema"] != SCHEMA { return Err("unsupported schema".into()); }
    let backend = job["backend"].as_str().ok_or("backend must be a string")?;
    let (walk_choice, region_choice) = match backend {
        "spectral_full" => (BackendChoice::Spectral, RegionChoice::StateReadout),
        "auto_full" => (BackendChoice::Auto, RegionChoice::StateReadout),
        "auto_region" => (BackendChoice::Auto, RegionChoice::Auto),
        _ => return Err("unknown backend".into()),
    };
    let batches = array(&job["batches"])?;
    if batches.is_empty() || batches.len() > MAX_BATCHES { return Err("batch history exceeds bounds".into()); }
    let mut all_entities = BTreeSet::new();
    let mut checked_batches = Vec::new();
    for batch in batches {
        let values = entities(batch, true)?;
        all_entities.extend(&values);
        checked_batches.push(values);
    }
    if all_entities.len() > MAX_NODES { return Err("total entity capacity exceeded".into()); }
    let queries = array(&job["queries"])?;
    if queries.len() > MAX_QUERIES { return Err("query capacity exceeded".into()); }
    let mut query_times = 0usize;
    for query in queries {
        fields(query, &["source", "targets", "times_bits", "threshold_bits", "deadband_bits"])?;
        let source = array(&query["source"])?;
        if source.len() != all_entities.len() { return Err("source must cover every current entity".into()); }
        let mut seen = BTreeSet::new();
        let mut nonzero = false;
        for entry in source {
            fields(entry, &["entity", "re_bits", "im_bits"])?;
            let id = entity(&entry["entity"])?;
            if !all_entities.contains(&id) || !seen.insert(id) { return Err("unknown or duplicate source entity".into()); }
            let re = number(&entry["re_bits"])?;
            let im = number(&entry["im_bits"])?;
            nonzero |= re != 0.0 || im != 0.0;
        }
        if !nonzero { return Err("zero source".into()); }
        for target in entities(&query["targets"], false)? {
            if !all_entities.contains(&target) { return Err("unknown target".into()); }
        }
        let times = array(&query["times_bits"])?;
        if times.is_empty() { return Err("query requires at least one time".into()); }
        query_times = query_times.checked_add(times.len()).ok_or("query count overflow")?;
        if query_times > MAX_QUERIES { return Err("total query capacity exceeded".into()); }
        for time in times { number(time)?; }
        let threshold = number(&query["threshold_bits"])?;
        let deadband = number(&query["deadband_bits"])?;
        if !(0.0..=1.0).contains(&threshold) || !(0.0..=1.0).contains(&deadband) {
            return Err("threshold and decision deadband must lie in [0,1]".into());
        }
    }
    let mut config = Config::default();
    config.persistence.lambda_decay = 0.0;
    config.consensus.min_crystal_tick = u64::MAX;
    let mut engine = Engine::with_adapter(config, SensorAdapter).map_err(|e| e.to_string())?;
    for (tick, batch) in checked_batches.iter().enumerate() {
        let raw = batch.iter().map(|i| serde_json::to_vec(&json!({"entity":i,"tick":tick,"phase":0.0}))
            .map_err(|e|e.to_string())).collect::<Result<Vec<_>>>()?;
        engine.step(&raw).map_err(|e| e.to_string())?;
    }
    let snapshot = engine.conditioned_snapshot(walk_choice).map_err(|e|e.to_string())?;
    let identity = snapshot.identity().iter().map(|b|format!("{b:02x}")).collect::<String>();
    let walk_backend = match snapshot.backend() { WalkBackend::CompleteGraph => "complete_graph", WalkBackend::Spectral => "spectral" };
    let mut answers = Vec::new();
    for query in queries {
        let named = array(&query["source"] )?.iter().map(|s|Ok((vertex(entity(&s["entity"])?),
                Complex::new(number(&s["re_bits"] )?, number(&s["im_bits"] )?))))
            .collect::<Result<Vec<_>>>()?;
        let targets = entities(&query["targets"], false)?.into_iter().map(vertex).collect::<Vec<_>>();
        let prepared = snapshot.prepare_named_state(&named).map_err(|e|e.to_string())?;
        let region = prepared.prepare_region(&targets, region_choice).map_err(|e|e.to_string())?;
        let region_backend = match region.backend() {
            RegionBackend::CompleteGraph => "complete_graph_region",
            RegionBackend::StateReadout => "state_readout",
        };
        let threshold = number(&query["threshold_bits"])?;
        let deadband = number(&query["deadband_bits"])?;
        let mut values = Vec::new();
        for time_bits in array(&query["times_bits"])? {
            let mass = region.mass_at(number(time_bits)?).map_err(|e|e.to_string())?;
            let decision = if mass > threshold + deadband { "above" }
                else if mass < threshold - deadband { "below" } else { "ambiguous" };
            values.push(json!({"time_bits":time_bits,"mass_bits":bits(mass)?,"decision":decision}));
        }
        answers.push(json!({"region_backend":region_backend,"values":values}));
    }
    let stats = engine.statistics();
    let labelled = snapshot.vertex_ids().iter().map(|&id| {
        let entity = all_entities.iter().find(|&&i| vertex(i)==id).copied().ok_or("unmapped native vertex")?;
        Ok(json!({"entity":entity,"vertex_id":id.to_string()}))
    }).collect::<Result<Vec<_>>>()?;
    Ok(json!({"schema":SCHEMA,"backend":backend,
        "engine":{"ticks":stats.ticks,"commits":stats.commits,"vertices":stats.vertices,
                  "edges":stats.edges,"observations":stats.observations,"faulted":stats.faulted},
        "snapshot":{"identity":identity,"tick":snapshot.tick(),"vertices":labelled,
                    "walk_backend":walk_backend,"model":"exp(-itL);L=D-A;(W+W^T)/2;inactive-included;selfloops-ignored"},
        "query_results":answers}))
}
fn main() {
    let result = (|| -> Result<Value> {
        if std::env::args().len()!=1 {return Err("accepts JSON on stdin; no arguments".into());}
        let mut raw=Vec::new();
        io::stdin().take((MAX_BYTES+1) as u64).read_to_end(&mut raw).map_err(|e|e.to_string())?;
        if raw.len()>MAX_BYTES {return Err("input byte cap exceeded".into());}
        let text=std::str::from_utf8(&raw).map_err(|e|e.to_string())?;
        let text=text.strip_suffix('\n').unwrap_or(text);
        if !text.is_ascii() {return Err("ASCII JSON required".into());}
        let job:Value=serde_json::from_str(text).map_err(|e|e.to_string())?;
        if serde_json::to_string(&job).map_err(|e|e.to_string())? != text {
            return Err("compact sorted-key canonical JSON required; duplicate keys forbidden".into());
        }
        execute(job)
    })();
    match result {
        Ok(value) => println!("{}",serde_json::to_string(&value).expect("finite exact JSON")),
        Err(error) => { eprintln!("{error}"); std::process::exit(2); }
    }
}
