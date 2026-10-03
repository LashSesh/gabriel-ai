//! Exact, bounded snapshot export for the opt-in reachability profile.
//! Replays public Engine ingestion in a fresh process; performs no certification.
use pse::{Config, Engine, MeasurementContext, Observation, ObservationAdapter, ObserveError};
use pse::conditioned::BackendChoice;
use pse_types::content_address_raw;
use serde_json::{json, Value};
use std::collections::BTreeSet;
use std::io::{self, Read};

const SCHEMA: &str = "gabriel-engine-snapshot/v1";
const MODEL: &str = "exp(-itL);L=D-A;(W+W^T)/2;inactive-included;selfloops-ignored";
const MAX_BYTES: usize = 4 * 1024 * 1024;
const MAX_NODES: usize = 64;
const MAX_BATCHES: usize = 128;
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
    let id = value.as_u64().ok_or("entity must be an unsigned integer")?;
    if id >= MAX_NODES as u64 { return Err("entity outside [0,63]".into()); }
    Ok(id as usize)
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
        let value: Value = serde_json::from_slice(raw)
            .map_err(|e| ObserveError::Canonicalize(e.to_string()))?;
        let id = value["entity"].as_u64().ok_or_else(|| ObserveError::Canonicalize("entity".into()))?;
        let tick = value["tick"].as_u64().ok_or_else(|| ObserveError::Canonicalize("tick".into()))?;
        Ok(Observation { timestamp: tick as f64, source_id: format!("sensor-{id}"),
            provenance: Default::default(), payload: raw.to_vec(), context: context.clone(),
            digest: content_address_raw(raw), schema_version: "1".into(), phase_hint: Some(0.0), amplitude_hint: None })
    }
}
fn execute(job: Value) -> Result<Value> {
    fields(&job, &["schema", "batches"])?;
    if job["schema"] != SCHEMA { return Err("unsupported schema".into()); }
    let batches = array(&job["batches"])?;
    if batches.is_empty() || batches.len() > MAX_BATCHES {
        return Err("batch history exceeds bounds".into());
    }
    let mut all_entities = BTreeSet::new();
    let mut checked = Vec::new();
    for batch in batches {
        let batch = array(batch)?;
        if batch.is_empty() || batch.len() > MAX_NODES { return Err("batch entity count outside bounds".into()); }
        let values = batch.iter().map(entity).collect::<Result<Vec<_>>>()?;
        if values.iter().copied().collect::<BTreeSet<_>>().len() != values.len() {
            return Err("duplicate entity".into());
        }
        all_entities.extend(&values);
        checked.push(values);
    }
    if all_entities.len() > MAX_NODES { return Err("total entity capacity exceeded".into()); }
    let mut config = Config::default();
    config.persistence.lambda_decay = 0.0;
    config.consensus.min_crystal_tick = u64::MAX;
    let mut engine = Engine::with_adapter(config, SensorAdapter).map_err(|e| e.to_string())?;
    for (tick, batch) in checked.iter().enumerate() {
        let raw = batch.iter().map(|id| serde_json::to_vec(&json!({"entity":id,"tick":tick,"phase":0.0}))
            .map_err(|e| e.to_string())).collect::<Result<Vec<_>>>()?;
        engine.step(&raw).map_err(|e| e.to_string())?;
    }
    let snapshot = engine.conditioned_snapshot(BackendChoice::Auto).map_err(|e| e.to_string())?;
    let identity = snapshot.identity().iter().map(|b| format!("{b:02x}")).collect::<String>();
    let vertices = snapshot.vertex_ids().iter().map(|&id| {
        let entity = all_entities.iter().find(|&&i| vertex(i) == id).copied().ok_or("unmapped native vertex")?;
        Ok(json!({"entity":entity,"vertex_id":id.to_string()}))
    }).collect::<Result<Vec<_>>>()?;
    let laplacian = snapshot.laplacian();
    let degrees = laplacian.degree.iter().map(|&x| bits(x)).collect::<Result<Vec<_>>>()?;
    let mut edges = laplacian.adjacency.clone();
    edges.sort_by_key(|&(i,j,_)| (i,j));
    let adjacency = edges.iter().map(|&(i,j,w)| {
        Ok(json!({"from":i,"to":j,"weight_bits":bits(w)?}))
    }).collect::<Result<Vec<_>>>()?;
    let stats = engine.statistics();
    Ok(json!({"schema":SCHEMA,
        "engine":{"ticks":stats.ticks,"commits":stats.commits,"vertices":stats.vertices,
                  "edges":stats.edges,"observations":stats.observations,"faulted":stats.faulted},
        "snapshot":{"identity":identity,"tick":snapshot.tick(),"vertices":vertices,
                    "degree_bits":degrees,"adjacency":adjacency,"model":MODEL}}))
}
fn main() {
    let result = (|| -> Result<Value> {
        if std::env::args().len() != 1 { return Err("accepts JSON on stdin; no arguments".into()); }
        let mut raw = Vec::new();
        io::stdin().take((MAX_BYTES+1) as u64).read_to_end(&mut raw).map_err(|e| e.to_string())?;
        if raw.len() > MAX_BYTES { return Err("input byte cap exceeded".into()); }
        let text = std::str::from_utf8(&raw).map_err(|e| e.to_string())?;
        let text = text.strip_suffix('\n').unwrap_or(text);
        if !text.is_ascii() { return Err("ASCII JSON required".into()); }
        let job: Value = serde_json::from_str(text).map_err(|e| e.to_string())?;
        if serde_json::to_string(&job).map_err(|e| e.to_string())? != text {
            return Err("compact sorted-key canonical JSON required; duplicate keys forbidden".into());
        }
        execute(job)
    })();
    match result {
        Ok(value) => println!("{}", serde_json::to_string(&value).expect("finite exact JSON")),
        Err(error) => { eprintln!("{error}"); std::process::exit(2); }
    }
}
