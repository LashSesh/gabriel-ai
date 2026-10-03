//! Complete public-Engine graph-observation tasks with three matched scalar consumers.
use pse::{Config, Engine, MeasurementContext, Observation, ObservationAdapter, ObserveError};
use pse::conditioned::{BackendChoice, Complex, ConditionedSnapshot, RegionChoice, RegionBackend, WalkBackend};
use pse_graph::derive_vertex_id;
use pse_types::{content_address_raw, ProvenanceEnvelope, VertexId};
use serde_json::{json, Value};
use std::hint::black_box;
use std::collections::BTreeMap;
use std::time::Instant;

const PROTOCOL: &str = include_str!("../protocol.json");
const VARIANTS: [&str; 3] = ["spectral_full", "auto_full", "auto_region"];

struct SensorAdapter;
impl ObservationAdapter for SensorAdapter {
    fn source_id(&self) -> &str { "sensor" }
    fn canonicalize(&self, raw: &[u8], context: &MeasurementContext) -> Result<Observation, ObserveError> {
        let value: Value = serde_json::from_slice(raw).map_err(|e| ObserveError::Canonicalize(e.to_string()))?;
        Ok(Observation {
            timestamp: value["tick"].as_u64().unwrap() as f64,
            source_id: format!("sensor-{}", value["entity"].as_u64().unwrap()),
            payload: raw.to_vec(), digest: content_address_raw(raw), context: context.clone(),
            provenance: ProvenanceEnvelope::default(), schema_version: "1".into(), phase_hint: Some(0.0), amplitude_hint: None,
        })
    }
}
fn configuration() -> Config {
    let mut config = Config::default();
    config.persistence.lambda_decay = 0.0;
    config.consensus.min_crystal_tick = u64::MAX;
    config
}
fn backend_name(x: WalkBackend) -> &'static str {
    match x { WalkBackend::CompleteGraph => "complete_graph", WalkBackend::Spectral => "spectral" }
}
fn region_name(x: RegionBackend) -> &'static str {
    match x { RegionBackend::CompleteGraph => "complete_graph", RegionBackend::StateReadout => "state_readout" }
}
fn batches(case: &Value, reverse: bool) -> Vec<Vec<Vec<u8>>> {
    let n = case["n"].as_u64().unwrap() as usize;
    let entities: Vec<Vec<usize>> = match case["family"].as_str().unwrap() {
        "clique" => vec![(0..n).collect()],
        "path" => (0..n - 1).map(|i| vec![i, i + 1]).collect(),
        "near_clique" => vec![(0..n - 1).collect(), (0..n - 2).chain([n - 1]).collect()],
        _ => panic!("unknown graph family"),
    };
    entities.into_iter().enumerate().map(|(tick, mut ids)| {
        if reverse { ids.reverse(); }
        ids.into_iter().map(|entity| serde_json::to_vec(&json!({"entity": entity, "tick": tick, "phase": 0.0})).unwrap()).collect()
    }).collect()
}
fn engine(config: &Config, input: &[Vec<Vec<u8>>]) -> Engine {
    let mut engine = Engine::with_adapter(config.clone(), SensorAdapter).unwrap();
    for batch in input {
        let step = engine.step(black_box(batch)).unwrap();
        assert!(step.crystal.is_none(), "read-only graph fixture must not crystallize");
    }
    engine
}
fn source_id(i: usize) -> VertexId { derive_vertex_id(&format!("sensor-{i}")) }
fn source(snapshot: &ConditionedSnapshot, name: &str) -> Vec<Complex<f64>> {
    let n = snapshot.vertex_ids().len();
    let mut by_source: Vec<Complex<f64>> = (0..n).map(|i| match name {
        "primary" => Complex::new(((17*i+3)%29) as f64 - 14.0, ((11*i+5)%23) as f64 - 11.0),
        "uniform" => Complex::new(1.0, 0.0),
        "one_hot" => Complex::new(if i == 0 { 1.0 } else { 0.0 }, 0.0),
        "real_zero_mean" => Complex::new(if i == 0 { 1.0 } else if i == 1 { -1.0 } else { 0.0 }, 0.0),
        _ => panic!("unknown source"),
    }).collect();
    let norm = by_source.iter().map(|z| z.norm_sqr()).sum::<f64>().sqrt();
    for value in &mut by_source { *value /= norm; }
    let named:BTreeMap<_,_>=by_source.into_iter().enumerate().map(|(i,z)|(source_id(i),z)).collect();
    snapshot.vertex_ids().iter().map(|id| named[id]).collect()
}
fn targets(n: usize) -> Vec<VertexId> { (0..n).filter(|i| i % 2 == 0).map(source_id).collect() }
fn normalized(initial:&[Complex<f64>])->Vec<Complex<f64>> {
    let scale=initial.iter().fold(0.0_f64, |s,z|s.max(z.re.abs()).max(z.im.abs()));
    let scaled:Vec<_>=initial.iter().map(|z|Complex::new(z.re/scale,z.im/scale)).collect();
    let norm=scaled.iter().map(|z|z.norm_sqr()).sum::<f64>().sqrt();
    scaled.iter().map(|z|*z/norm).collect()
}
fn threshold(snapshot: &ConditionedSnapshot, state: &[Complex<f64>], targets: &[VertexId]) -> f64 {
    let norm = state.iter().map(|z| z.norm_sqr()).sum::<f64>();
    state.iter().zip(snapshot.vertex_ids()).filter(|(_, id)| targets.contains(id))
        .map(|(z, _)| z.norm_sqr() / norm).sum()
}
fn action(mass: f64, threshold: f64, deadband: f64) -> &'static str {
    if mass > threshold + deadband { "above" }
    else if mass < threshold - deadband { "below" }
    else { "abstain" }
}
fn close(a: f64, b: f64, absolute: f64, relative: f64) {
    assert!(a.is_finite() && b.is_finite());
    assert!((a-b).abs() <= absolute + relative*a.abs().max(b.abs()), "{a} versus {b}");
}
fn vector(z: &[Complex<f64>]) -> Vec<[f64; 2]> { z.iter().map(|x| [x.re, x.im]).collect() }
fn shape(snapshot: &ConditionedSnapshot, case: &Value) {
    let n = case["n"].as_u64().unwrap() as usize;
    let lap = snapshot.laplacian();
    assert_eq!(lap.n, n);
    let expected_edges = match case["family"].as_str().unwrap() {
        "clique" => n*(n-1)/2, "path" => n-1, "near_clique" => n*(n-1)/2-1, _ => unreachable!(),
    };
    assert_eq!(lap.adjacency.len(), 2*expected_edges);
    assert!(lap.adjacency.iter().all(|&(i,j,w)| i != j && w == 0.5));
}
fn actual_choice(variant: &str) -> BackendChoice {
    if variant == "spectral_full" { BackendChoice::Spectral } else { BackendChoice::Auto }
}
fn region_choice(variant: &str) -> RegionChoice {
    if variant == "auto_region" { RegionChoice::Auto } else { RegionChoice::StateReadout }
}

fn query_time(protocol:&Value, index:usize)->f64 {
    let base=protocol["query_times"].as_array().unwrap();
    let denominator=protocol["query_offsets_denominator"].as_u64().unwrap() as f64;
    base[index%base.len()].as_f64().unwrap()+(index/base.len()) as f64/denominator
}
fn golden(case: &Value, config: &Config, protocol: &Value) -> Value {
    let input = batches(case, false);
    let origin_engine = engine(config, &input);
    let spectral = origin_engine.conditioned_snapshot(BackendChoice::Spectral).unwrap();
    let auto = origin_engine.conditioned_snapshot(BackendChoice::Auto).unwrap();
    shape(&auto, case);
    assert_eq!(backend_name(auto.backend()), case["expected_auto"].as_str().unwrap());
    assert_eq!(spectral.identity(), auto.identity());
    assert_eq!(spectral.vertex_ids(), auto.vertex_ids());
    let initial = source(&auto, "primary");
    let ids = targets(initial.len());
    let cutoff = threshold(&auto, &initial, &ids);
    let unit_source = normalized(&initial);
    let sp = spectral.prepare_state(&initial).unwrap();
    let ap = auto.prepare_state(&initial).unwrap();
    let sr = sp.prepare_region(&ids, RegionChoice::StateReadout).unwrap();
    let ar = ap.prepare_region(&ids, RegionChoice::StateReadout).unwrap();
    let dr = ap.prepare_region(&ids, RegionChoice::Auto).unwrap();
    let times: Vec<f64> = std::iter::once(0.0).chain((0..protocol["golden_query_count"].as_u64().unwrap() as usize).map(|i|query_time(protocol,i))).collect();
    let diagnostic_times: Vec<f64> = std::iter::once(0.0).chain(protocol["query_times"].as_array().unwrap().iter().map(|t| t.as_f64().unwrap())).collect();
    let abs = protocol["component_absolute_tolerance"].as_f64().unwrap();
    let rel = protocol["component_relative_tolerance"].as_f64().unwrap();
    let mtol = protocol["mass_absolute_tolerance"].as_f64().unwrap();
    let ntol = protocol["norm_absolute_tolerance"].as_f64().unwrap();
    let deadband = protocol["deadband"].as_f64().unwrap();
    let mut states = Vec::new();
    for &time in &times {
        let s = sp.readout_at(time).unwrap();
        let a = ap.readout_at(time).unwrap();
        for (x,y) in s.amplitudes.iter().zip(&a.amplitudes) { close(x.re,y.re,abs,rel); close(x.im,y.im,abs,rel); }
        for (&x,&y) in s.normalized_intensities.iter().zip(&a.normalized_intensities) { close(x,y,mtol,0.0); }
        close(s.norm_ratio,1.0,ntol,0.0); close(a.norm_ratio,1.0,ntol,0.0);
        if time == 0.0 {
            assert_eq!(vector(&s.amplitudes), vector(&unit_source));
            assert_eq!(vector(&a.amplitudes), vector(&unit_source));
        }
        let masses = [sr.mass_at(time).unwrap(), ar.mass_at(time).unwrap(), dr.mass_at(time).unwrap()];
        close(masses[0],masses[1],mtol,0.0); close(masses[0],masses[2],mtol,0.0);
        let decisions: Vec<_> = masses.iter().map(|&m| action(m,cutoff,deadband)).collect();
        assert!(decisions.iter().all(|x| *x==decisions[0]));
        states.push(json!({"time":time,"spectral_amplitudes":vector(&s.amplitudes),"auto_amplitudes":vector(&a.amplitudes),
            "spectral_normalized_intensities":s.normalized_intensities,"auto_normalized_intensities":a.normalized_intensities,
            "spectral_norm_ratio":s.norm_ratio,"auto_norm_ratio":a.norm_ratio,
            "spectral_full":masses[0],"auto_full":masses[1],"auto_region":masses[2],
            "actions":{"spectral_full":decisions[0],"auto_full":decisions[1],"auto_region":decisions[2]}}));
    }
    let mut diagnostics = serde_json::Map::new();
    for source_name in ["uniform","one_hot","real_zero_mean"] {
        let initial = source(&auto, source_name);
        let prepared = auto.prepare_state(&initial).unwrap();
        let first = prepared.readout_at(0.0).unwrap();
        let first_norm = initial.iter().map(|z|z.norm_sqr()).sum::<f64>();
        let mut rows = Vec::new();
        let is_clique = case["family"]=="clique";
        for &time in &diagnostic_times {
            let output = prepared.readout_at(time).unwrap();
            close(output.norm_ratio,1.0,ntol,0.0);
            if source_name=="uniform" || (is_clique && source_name=="real_zero_mean") {
                for (&a,&b) in output.normalized_intensities.iter().zip(&first.normalized_intensities) { close(a,b,mtol,0.0); }
            }
            if is_clique && source_name=="one_hot" {
                let values: Vec<_> = auto.vertex_ids().iter().zip(&output.normalized_intensities).filter(|(id,_)| **id!=source_id(0)).map(|(_,p)|*p).collect();
                for &p in &values { close(p,values[0],mtol,0.0); }
            }
            rows.push(json!({"time":time,"amplitudes":vector(&output.amplitudes),"normalized_intensities":output.normalized_intensities,"norm_ratio":output.norm_ratio}));
        }
        diagnostics.insert(source_name.into(),json!({"source":vector(&initial),"initial_norm":first_norm,"states":rows}));
    }
    // Change ingestion source order; source and target identities stay fixed.
    let permuted_input = batches(case,true);
    let permuted_engine = engine(config,&permuted_input);
    let permuted = permuted_engine.conditioned_snapshot(BackendChoice::Auto).unwrap();
    let perm_initial = source(&permuted,"primary");
    let perm_prepared = permuted.prepare_state(&perm_initial).unwrap();
    let mut perm_states=Vec::new();
    for (time, original) in diagnostic_times.iter().zip(&states) {
        let output=perm_prepared.readout_at(*time).unwrap();
        for (j,id) in permuted.vertex_ids().iter().enumerate() {
            let i=auto.vertex_ids().iter().position(|x|x==id).unwrap();
            close(output.amplitudes[j].re,original["auto_amplitudes"][i][0].as_f64().unwrap(),abs,rel);
            close(output.amplitudes[j].im,original["auto_amplitudes"][i][1].as_f64().unwrap(),abs,rel);
        }
        perm_states.push(json!({"time":time,"amplitudes":vector(&output.amplitudes),"normalized_intensities":output.normalized_intensities,"norm_ratio":output.norm_ratio}));
    }
    diagnostics.insert("permutation".into(),json!({"batches":permuted_input.iter().map(|batch|batch.iter().map(|raw|std::str::from_utf8(raw).unwrap()).collect::<Vec<_>>()).collect::<Vec<_>>(),"vertex_ids":permuted.vertex_ids(),"source":vector(&perm_initial),"states":perm_states}));
    let lap=auto.laplacian();
    json!({"case":case,"batches":input.iter().map(|batch|batch.iter().map(|raw|std::str::from_utf8(raw).unwrap()).collect::<Vec<_>>()).collect::<Vec<_>>(),
        "vertex_ids":auto.vertex_ids(),"snapshot_tick":auto.tick(),"snapshot_identity":auto.identity(),
        "laplacian":{"n":lap.n,"degree":lap.degree,"adjacency":lap.adjacency},"source":vector(&initial),
        "unit_source":vector(&unit_source),"target_ids":ids,"threshold":cutoff,"auto_backend":backend_name(auto.backend()),"region_backend":region_name(dr.backend()),
        "states":states,"diagnostics":diagnostics})
}
fn once(case:&Value, config:&Config, input:&[Vec<Vec<u8>>], protocol:&Value, count:usize, variant:&str)->Value {
    let total_start=Instant::now();
    let (ingest_ns,snapshot_ns,preparation_ns,query_ns,masses,actions,tick,vertices,edges,backend,region_backend,cutoff)={
        let start=Instant::now();
        let engine=engine(config,input);
        let ingest_ns=start.elapsed().as_nanos() as u64;
        let start=Instant::now();
        let snapshot=engine.conditioned_snapshot(actual_choice(variant)).unwrap();
        let snapshot_ns=start.elapsed().as_nanos() as u64;
        let start=Instant::now();
        let initial=source(&snapshot,"primary");
        let ids=targets(initial.len());
        let cutoff=threshold(&snapshot,&initial,&ids);
        let prepared=snapshot.prepare_state(&initial).unwrap();
        let region=prepared.prepare_region(&ids,region_choice(variant)).unwrap();
        let preparation_ns=start.elapsed().as_nanos() as u64;
        let deadband=protocol["deadband"].as_f64().unwrap();
        let start=Instant::now();
        let mut masses=Vec::with_capacity(count);
        let mut actions=Vec::with_capacity(count);
        for i in 0..count {
            let mass=region.mass_at(black_box(query_time(protocol,i))).unwrap();
            actions.push(action(mass,cutoff,deadband));masses.push(mass);
        }
        black_box((&masses,&actions));
        let query_ns=start.elapsed().as_nanos() as u64;
        let stats=engine.statistics();
        assert_eq!(stats.commits,0);assert_eq!(stats.vertices,case["n"].as_u64().unwrap() as usize);
        (ingest_ns,snapshot_ns,preparation_ns,query_ns,masses,actions,snapshot.tick(),stats.vertices,stats.edges,
         backend_name(snapshot.backend()),region_name(region.backend()),cutoff)
        // All Engine/snapshot/prepared-state/region/source temporaries drop here.
    };
    let total_ns=total_start.elapsed().as_nanos() as u64;
    json!({"total_ns":total_ns,"ingest_ns":ingest_ns,"snapshot_ns":snapshot_ns,
        "preparation_ns":preparation_ns,"query_ns":query_ns,"masses":masses,"actions":actions,
        "tick":tick,"vertices":vertices,"edges":edges,"backend":backend,"region_backend":region_backend,"threshold":cutoff})
}
fn measurements(protocol:&Value, process_index:usize, pilot:bool)->Value {
    let config=configuration();let mut rows=Vec::new();
    for (ci,case) in protocol["cases"].as_array().unwrap().iter().enumerate() {
        let input=batches(case,false);
        for (qi,q) in protocol["query_counts"].as_array().unwrap().iter().enumerate() {
            let count=q.as_u64().unwrap() as usize;
            if !pilot {for variant in VARIANTS {black_box(once(case,&config,&input,protocol,count,variant));}}
            let batches=if pilot {1} else {protocol["batches_per_process"].as_u64().unwrap() as usize};
            let mut samples=Vec::new();
            for batch in 0..batches {
                let rotation=(process_index+ci+qi+batch)%3;
                let mut order:Vec<_>=(0..3).map(|i|VARIANTS[(i+rotation)%3]).collect();
                if (process_index+batch)%2==1 {order.reverse();}
                let mut sample=serde_json::Map::new();
                sample.insert("batch".into(),json!(batch));sample.insert("order".into(),json!(order));
                for variant in order {sample.insert(variant.into(),once(case,&config,&input,protocol,count,variant));}
                for variant in ["auto_full","auto_region"] {
                    for (a,b) in sample["spectral_full"]["masses"].as_array().unwrap().iter().zip(sample[variant]["masses"].as_array().unwrap()) {
                        close(a.as_f64().unwrap(),b.as_f64().unwrap(),protocol["mass_absolute_tolerance"].as_f64().unwrap(),0.0);
                    }
                    assert_eq!(sample["spectral_full"]["actions"],sample[variant]["actions"]);
                }
                samples.push(Value::Object(sample));
            }
            rows.push(json!({"case":case,"query_count":count,"measurements":samples}));
        }
    }
    json!({"schema":"gabriel.conditioned-engine.measurements.v1","protocol":protocol,"process_index":process_index,"pid":std::process::id(),"pilot":pilot,"cases":rows})
}
fn main() {
    let args:Vec<_>=std::env::args().collect();
    let protocol:Value=serde_json::from_str(PROTOCOL).unwrap();
    let value=match args.get(1).map(String::as_str) {
        Some("golden")=>json!({"schema":"gabriel.conditioned-engine.golden.v1","protocol":protocol,"configuration":configuration(),
            "cases":protocol["cases"].as_array().unwrap().iter().map(|c|golden(c,&configuration(),&protocol)).collect::<Vec<_>>()}),
        Some("pilot")=>measurements(&protocol,0,true),
        Some("measure")=>{assert_eq!(args.get(2).map(String::as_str),Some("--process-index"));measurements(&protocol,args[3].parse().unwrap(),false)},
        _=>panic!("usage: benchmark golden|pilot|measure --process-index N"),
    };
    println!("{}",serde_json::to_string(&value).unwrap());
}
