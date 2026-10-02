//! Public-input sparse/acquisition macro-step benchmarks. Every setup step uses
//! the normal macro_step API. Shape validation and serialization are untimed.
use pse_core::{macro_step, GlobalState};
use pse_graph::{ObservationAdapter, ObserveError, PersistentGraph};
use pse_types::{content_address_raw, Config, MeasurementContext, Observation, ProvenanceEnvelope, SemanticCrystal};
use serde_json::{json,Value};
use std::hint::black_box;
use std::time::Instant;
const INPUTS:&str=include_str!("../inputs.json");
const PROTOCOL:&str=include_str!("../protocol.json");
struct SensorAdapter;
impl ObservationAdapter for SensorAdapter {
    fn source_id(&self)->&str { "sensor" }
    fn canonicalize(&self,raw:&[u8],ctx:&MeasurementContext)->Result<Observation,ObserveError> {
        let value:Value=serde_json::from_slice(raw).map_err(|e|ObserveError::Canonicalize(e.to_string()))?;
        Ok(Observation{timestamp:value["tick"].as_f64().unwrap(),source_id:format!("sensor-{}",value["entity"].as_u64().unwrap()),
          payload:raw.to_vec(),digest:content_address_raw(raw),context:ctx.clone(),provenance:ProvenanceEnvelope::default(),
          schema_version:"1".into(),phase_hint:Some(value["phase"].as_f64().unwrap())})
    }
}
fn configuration()->Config {
    let mut c=Config::default();
    c.thresholds.d=0.0;c.thresholds.q=0.0;c.thresholds.r=0.0;c.thresholds.g=0.0;
    c.thresholds.j=0.0;c.thresholds.p=0.0;c.thresholds.n=0.0;c.thresholds.k=0.0;
    c.consensus.consensus_threshold=0.0;c.consensus.mirror_consistency_eta=0.0;
    c.consensus.archive_dominance=2.0;c.consensus.memory_similarity_threshold=2.0;
    c.carrier.adaptive=true;c.extraction.convergence_tau=1.0;
    c.adaptation.split_threshold=3.0;c.adaptation.merge_distance=0.0;c
}
fn variant()->&'static str {
    if cfg!(feature="memoized-engine") {"memoized"}
    else if cfg!(feature="shared-engine") {"shared"}
    else if cfg!(feature="hoisted-engine") {"hoisted"} else {"indexed"}
}
fn cache_stats()->Value {
    #[cfg(feature="memoized-engine")]
    { let s=pse_metatron::memoized_signature::thread_cache_stats();
      json!({"hits":s.hits,"misses":s.misses,"bypasses":s.bypasses,"evictions":s.evictions,"entries":s.entries}) }
    #[cfg(not(feature="memoized-engine"))]
    {Value::Null}
}
fn clear_cache() {
    #[cfg(feature="memoized-engine")]
    pse_metatron::memoized_signature::clear_thread_cache();
}
include!("snapshot.rs");
#[derive(Clone)]
struct Step { batch:Vec<Vec<u8>>, vertices:usize, edges:usize }
struct Case {n:usize,workload:String,bootstrap:Vec<Step>,measured:Vec<Step>}
fn steps(value:&Value)->Vec<Step> {
    value.as_array().unwrap().iter().map(|s|Step{
      batch:s["batch"].as_array().unwrap().iter().map(|r|r.as_str().unwrap().as_bytes().to_vec()).collect(),
      vertices:s["vertices"].as_u64().unwrap() as usize,edges:s["edges"].as_u64().unwrap() as usize}).collect()
}
fn cases(inputs:&Value)->Vec<Case> {
    inputs["cases"].as_array().unwrap().iter().map(|v|Case{n:v["entities"].as_u64().unwrap() as usize,
      workload:v["workload"].as_str().unwrap().into(),bootstrap:steps(&v["bootstrap"]),measured:steps(&v["measured"])}).collect()
}
fn shape(s:&GlobalState,crystal:&SemanticCrystal,step:&Step,total_ticks:usize) {
    assert_eq!(s.commit_index,total_ticks as u64);
    assert_eq!(s.crystals_committed,total_ticks as u64,"every macro_step must commit");
    assert_eq!(s.archive.crystals().len(),total_ticks);
    assert_eq!(s.graph.graph.node_count(),step.vertices,"fixed public-input vertex set");
    assert_eq!(s.graph.graph.edge_count(),step.edges,"actual sparse/acquisition edge count");
    assert_eq!(crystal.region.len(),step.vertices,"controlled full-region extraction");
    if step.vertices<=7 {
        let signature=crystal.metatron_signature.as_ref().expect("eligible signature");
        assert_eq!(signature.n,step.vertices as u32);assert_eq!(signature.m,step.edges as u32);
    } else { assert!(crystal.metatron_signature.is_none(),"ineligible signature"); }
}
fn topology(s:&GlobalState,crystal:&SemanticCrystal)->Value {
    let adjacency=pse_core::metatron_attach::induced_adjacency(&s.graph,&crystal.region);
    let n=adjacency.len();let mut bits=String::new();let mut word=0u32;
    for j in 1..n { for i in 0..j {
        let present=adjacency[i][j]==1.0;bits.push(if present {'1'} else {'0'});
        if n<=7 && present {word|=1<<(j*(j-1)/2+i);}
    }}
    json!({"n":n,"region":crystal.region,"labelled_upper_bits_lsb_first":bits,
      "labelled_word":if n<=7 {json!(word)} else {Value::Null},
      "vertices":s.graph.graph.node_count(),"edges":s.graph.graph.edge_count()})
}
fn golden(cases:&[Case],c:&Config)->Value {
    let mut rows=Vec::new();
    for case in cases {
        clear_cache();let mut s=GlobalState::new(c);let mut traces=Vec::new();let mut ticks=0;
        for (stage,steps) in [("bootstrap",&case.bootstrap),("measured",&case.measured)] {
            if stage=="measured" && case.workload=="cold_acquisition" {clear_cache();}
            for step in steps {
                ticks+=1;
                let crystal=macro_step(&mut s,&step.batch,c,&SensorAdapter).unwrap().expect("must commit");
                shape(&s,&crystal,step,ticks);
                traces.push(json!({"stage":stage,"commits":s.crystals_committed,
                  "topology":topology(&s,&crystal),"state":selected_state(&s),"crystal":crystal}));
            }
        }
        rows.push(json!({"entities":case.n,"workload":case.workload,"traces":traces}));
    }
    json!({"schema":1,"selected_state_scope":"prior focused snapshot fields, not every GlobalState field",
      "crystals":"complete serialized SemanticCrystal values","cases":rows})
}
fn once(case:&Case,c:&Config)->Value {
    let mut s=GlobalState::new(c);
    for step in &case.bootstrap { black_box(macro_step(&mut s,&step.batch,c,&SensorAdapter).unwrap()); }
    assert_eq!(s.crystals_committed,case.bootstrap.len() as u64);
    if case.workload=="cold_acquisition" {clear_cache();}
    let before=cache_stats();
    let start=Instant::now();
    for step in &case.measured {black_box(macro_step(&mut s,black_box(&step.batch),black_box(c),&SensorAdapter).unwrap());}
    let elapsed=start.elapsed().as_nanos() as u64;
    let after=cache_stats();
    let expected=case.bootstrap.len()+case.measured.len();
    let crystals=s.archive.crystals();
    assert_eq!(s.crystals_committed,expected as u64);
    assert_eq!(crystals.len(),expected);
    for (crystal,step) in crystals[case.bootstrap.len()..].iter().zip(&case.measured) {
        assert_eq!(crystal.region.len(),case.n);
        if case.n<=7 {
            let sig=crystal.metatron_signature.as_ref().unwrap();
            assert_eq!(sig.n,case.n as u32);assert_eq!(sig.m,step.edges as u32);
        } else {assert!(crystal.metatron_signature.is_none());}
    }
    shape(&s,crystals.last().unwrap(),case.measured.last().unwrap(),expected);
    #[cfg(feature="memoized-engine")]
    {
        let hits=after["hits"].as_u64().unwrap()-before["hits"].as_u64().unwrap();
        let misses=after["misses"].as_u64().unwrap()-before["misses"].as_u64().unwrap();
        if case.n<=7 && case.workload=="cold_acquisition" {assert_eq!(hits,0);assert_eq!(misses,case.measured.len() as u64);}
        if case.n<=7 && case.workload=="repeated_path" {assert_eq!(hits,case.measured.len() as u64);assert_eq!(misses,0);}
        if case.n>7 {assert_eq!(hits+misses,0);}
    }
    json!({"entities":case.n,"workload":case.workload,"ticks":case.measured.len(),
      "measured_commits":s.crystals_committed-case.bootstrap.len() as u64,"bootstrap_commits":case.bootstrap.len(),
      "elapsed_ns":elapsed,"ns_per_tick":elapsed as f64/case.measured.len() as f64,
      "ticks_per_s":case.measured.len() as f64*1e9/elapsed as f64,
      "vertices":s.graph.graph.node_count(),"edges":s.graph.graph.edge_count(),
      "memo_cache_before":before,"memo_cache_after":after})
}
fn measure(cases:&[Case],protocol:&Value,c:&Config)->Value {
    for case in cases {black_box(once(case,c));}
    let repetitions=protocol["engine"]["inner_repetitions"].as_u64().unwrap();let mut rows=Vec::new();
    for repetition in 0..repetitions {for case in cases {let mut row=once(case,c);row["repetition"]=json!(repetition);rows.push(row);}}
    json!({"schema":1,"variant":variant(),"measurements":rows})
}
fn main() {
    let args:Vec<_>=std::env::args().collect();
    let inputs:Value=serde_json::from_str(INPUTS).unwrap();let protocol:Value=serde_json::from_str(PROTOCOL).unwrap();
    let c=configuration();let cases=cases(&inputs);
    let result=match args.get(1).map(String::as_str) {
        Some("configuration")=>serde_json::to_value(c).unwrap(),
        Some("golden")=>golden(&cases,&c),Some("engine")=>measure(&cases,&protocol,&c),
        _=>panic!("usage: phase-engine configuration|golden|engine"),
    };
    println!("{}",serde_json::to_string(&result).unwrap());
}
