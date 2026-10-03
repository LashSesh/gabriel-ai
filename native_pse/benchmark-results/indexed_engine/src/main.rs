//! Controlled same-tree engine and same-binary complete-signature measurements.
//! All inputs are checked-in bytes. Configuration and input/state construction,
//! golden serialization, output serialization, and process launch are untimed.
use pse_core::{macro_step, GlobalState};
use pse_graph::{ObservationAdapter, ObserveError, PersistentGraph};
use pse_types::{content_address_raw, Config, MeasurementContext, Observation, ProvenanceEnvelope};
use serde_json::{json, Value};
use std::hint::black_box;
use std::time::Instant;

const INPUTS: &str = include_str!("../inputs.json");
const PROTOCOL: &str = include_str!("../protocol.json");

struct SensorAdapter;
impl ObservationAdapter for SensorAdapter {
    fn source_id(&self) -> &str { "sensor" }
    fn canonicalize(&self, raw: &[u8], ctx: &MeasurementContext) -> Result<Observation, ObserveError> {
        let value: Value = serde_json::from_slice(raw)
            .map_err(|e| ObserveError::Canonicalize(e.to_string()))?;
        Ok(Observation {
            timestamp: value["tick"].as_f64().unwrap(),
            source_id: format!("sensor-{}", value["entity"].as_u64().unwrap()),
            payload: raw.to_vec(), digest: content_address_raw(raw), context: ctx.clone(),
            provenance: ProvenanceEnvelope::default(), schema_version: "1".into(),
            phase_hint: Some(value["phase"].as_f64().unwrap()), amplitude_hint: None,
        })
    }
}

fn configuration() -> Config {
    let mut c = Config::default();
    c.thresholds.d = 0.0; c.thresholds.q = 0.0; c.thresholds.r = 0.0;
    c.thresholds.g = 0.0; c.thresholds.j = 0.0; c.thresholds.p = 0.0;
    c.thresholds.n = 0.0; c.thresholds.k = 0.0;
    c.consensus.consensus_threshold = 0.0;
    c.consensus.mirror_consistency_eta = 0.0;
    c.consensus.archive_dominance = 2.0;
    c.consensus.memory_similarity_threshold = 2.0;
    c.carrier.adaptive = true;
    c
}

fn variant() -> &'static str {
    if cfg!(feature = "memoized-engine") { "memoized" }
    else if cfg!(feature = "indexed-engine") { "indexed" } else { "packed" }
}

fn cache_stats() -> Value {
    #[cfg(feature = "memoized-engine")]
    {
        let stats = pse_metatron::memoized_signature::thread_cache_stats();
        json!({"hits":stats.hits,"misses":stats.misses,"bypasses":stats.bypasses,
            "evictions":stats.evictions,"entries":stats.entries})
    }
    #[cfg(not(feature = "memoized-engine"))]
    { Value::Null }
}

fn input_for(inputs: &Value, entities: usize) -> Vec<Vec<Vec<u8>>> {
    let case = inputs["engine"].as_array().unwrap().iter()
        .find(|c| c["entities"].as_u64() == Some(entities as u64)).unwrap();
    case["batches"].as_array().unwrap().iter().map(|batch| {
        batch.as_array().unwrap().iter().map(|raw| raw.as_str().unwrap().as_bytes().to_vec()).collect()
    }).collect()
}

// The intentionally selected scope matches the prior focused-engine snapshot.
// This is not a serialization of every private/internal field of GlobalState.
fn graph_snapshot(g: &PersistentGraph) -> Value {
    let nodes: Vec<_> = g.graph.node_weights().map(|v|
        (v.id, v.active, v.first_seen, v.last_seen, v.activation_count)).collect();
    let edges: Vec<_> = g.graph.raw_edges().iter().map(|e|
        (e.source().index(), e.target().index(), &e.weight)).collect();
    let history: Vec<_> = g.history.iter().map(|r|
        (r.commit_index, r.digest, r.timestamp)).collect();
    let tensor: Vec<_> = g.tensor.iter().map(|(id, t)|
        (id, &t.snapshots, &t.timestamps)).collect();
    json!({"nodes":nodes,"edges":edges,"embedding":g.embedding,"history":history,
        "tensor":tensor,"hot":g.hot.data,"warm":g.warm.data,"cold":g.cold.data,
        "tick":g.commit_index})
}

fn selected_state(s: &GlobalState) -> Value {
    json!({"graph":graph_snapshot(&s.graph),"gate":s.last_gate,"h5":s.h5_state,
        "prev":s.prev_embeddings,"phase":s.phase_ladder,"active":s.active_carrier,
        "helix":s.last_data_helix,"t2":s.t2,"tick":s.commit_index,
        "status":format!("{:?}",s.engine_state),"consensus":s.consensus.last_result,
        "archive":s.archive.crystals(),"pattern_hits":s.pattern_hits,
        "constraints":s.last_constraint_count,"scale":format!("{:?}",s.scale_state),
        "morph":format!("{:?}",s.morph),"adaptive":format!("{:?}",s.adaptive)})
}

fn assert_shape(s: &GlobalState, entities: usize, ticks: usize) {
    assert_eq!(s.commit_index, ticks as u64);
    assert_eq!(s.crystals_committed, ticks as u64, "every tick must actually commit");
    assert_eq!(s.archive.crystals().len(), ticks);
    for crystal in s.archive.crystals() {
        assert_eq!(crystal.region.len(), entities);
        if entities <= 7 {
            assert_eq!(crystal.metatron_signature.as_ref().unwrap().n, entities as u32);
        } else {
            assert!(crystal.metatron_signature.is_none());
        }
    }
}

fn engine_golden(inputs: &Value, c: &Config) -> Value {
    let mut cases = Vec::new();
    for entities in [3, 5, 7, 8] {
        let mut s = GlobalState::new(c);
        let mut traces = Vec::new();
        for batch in input_for(inputs, entities) {
            let crystal = macro_step(&mut s, &batch, c, &SensorAdapter).unwrap();
            assert!(crystal.is_some());
            traces.push(json!({"state":selected_state(&s),"crystal":crystal,
                "commits":s.crystals_committed}));
        }
        assert_shape(&s, entities, 8);
        cases.push(json!({"entities":entities,"traces":traces}));
    }
    json!({"schema":1,"selected_state_scope":"prior focused snapshot fields",
        "crystals":"complete serialized SemanticCrystal values","cases":cases})
}

fn engine_once(entities: usize, input: &[Vec<Vec<u8>>], c: &Config) -> Value {
    let mut s = GlobalState::new(c);
    let mut latencies = Vec::with_capacity(input.len());
    let stats_before = cache_stats();
    let start = Instant::now();
    for batch in input {
        let tick_start = Instant::now();
        black_box(macro_step(&mut s, black_box(batch), black_box(c), &SensorAdapter).unwrap());
        latencies.push(tick_start.elapsed().as_nanos() as u64);
    }
    let elapsed = start.elapsed().as_nanos() as u64;
    assert_shape(&s, entities, input.len());
    json!({"entities":entities,"ticks":input.len(),"commits":s.crystals_committed,
        "observations":entities*input.len(),"elapsed_ns":elapsed,"tick_ns":latencies,
        "obs_per_s":entities as f64*input.len() as f64*1e9/elapsed as f64,
        "vertices":s.graph.graph.node_count(),"edges":s.graph.graph.edge_count(),
        "memo_cache_before":stats_before,"memo_cache_after":cache_stats()})
}

fn engine_measure(inputs: &Value, protocol: &Value, c: &Config) -> Value {
    let cases: Vec<_> = [3,5,7,8].into_iter().map(|n| (n,input_for(inputs,n))).collect();
    // Explicitly untimed complete-engine warmup; every recorded repetition still
    // creates a new GlobalState, while process-global data/cache pages are warm.
    for (n, batches) in &cases { black_box(engine_once(*n,batches,c)); }
    let repetitions = protocol["engine"]["inner_repetitions"].as_u64().unwrap();
    let mut records = Vec::new();
    for repetition in 0..repetitions {
        for (n, batches) in &cases {
            let mut row = engine_once(*n,batches,c);
            row["repetition"] = json!(repetition);
            records.push(row);
        }
    }
    json!({"schema":1,"variant":variant(),"measurements":records})
}

fn first_macrostep(inputs: &Value, entities: usize, c: &Config) -> Value {
    let input = input_for(inputs, entities);
    let mut s = GlobalState::new(c);
    // This is the first and only macro_step in this process. Input/config/state
    // construction and process launch are outside this interval.
    let start = Instant::now();
    let crystal = black_box(macro_step(&mut s, black_box(&input[0]), black_box(c), &SensorAdapter).unwrap());
    let elapsed = start.elapsed().as_nanos() as u64;
    assert!(crystal.is_some());
    assert_shape(&s, entities, 1);
    json!({"schema":1,"variant":variant(),"entities":entities,"ticks":1,
        "commits":s.crystals_committed,"elapsed_ns":elapsed,"memo_cache_after":cache_stats(),
        "scope":"first macro_step only; process launch/input/config/state construction excluded"})
}

#[cfg(any(feature = "indexed-engine", feature = "memoized-engine"))]
mod micro {
    use super::*;
    use pse_metatron::bitgraph::bits_to_adjacency;
    use pse_types::{canonical_bytes, MetatronTopologySignature};
    type SignatureFn = fn(Vec<Vec<f64>>) -> pse_metatron::ScanResult<MetatronTopologySignature>;

    fn signature_fn(variant: &str) -> SignatureFn {
        match variant {
            "packed" => pse_metatron::small_signature::compute_small_signature,
            "indexed" => pse_metatron::indexed_signature::compute_indexed_signature,
            #[cfg(feature = "memoized-engine")]
            "memoized" => pse_metatron::memoized_signature::compute_memoized_signature,
            _ => panic!("unknown signature variant"),
        }
    }

    pub fn golden(inputs: &Value, variant: &str) -> Value {
        let compute = signature_fn(variant);
        let mut cases = Vec::new();
        for case in inputs["micro"].as_array().unwrap() {
            let n = case["n"].as_u64().unwrap() as usize;
            let words = std::iter::once(case["fixed_word"].as_u64().unwrap() as u32)
                .chain(case["changing_words"].as_array().unwrap().iter().map(|v| v.as_u64().unwrap() as u32))
                .chain(case["collision_words"].as_array().unwrap().iter().map(|v| v.as_u64().unwrap() as u32));
            let signatures: Vec<_> = words.map(|word| {
                let bytes = canonical_bytes(&compute(bits_to_adjacency(word,n)).unwrap());
                // Full canonical bytes, not a field subset, tolerance or digest.
                json!({"word":word,"canonical_bytes":bytes})
            }).collect();
            cases.push(json!({"n":n,"signatures":signatures}));
        }
        json!({"schema":1,"cases":cases})
    }

    fn one_pass(graphs: &[Vec<Vec<f64>>], variant: &str) -> Value {
        let compute = signature_fn(variant);
        // The public APIs consume adjacency matrices. Clone all 512 owned
        // inputs before starting the clock; validation inside each API remains timed.
        let owned = graphs.to_vec();
        let before = cache_stats();
        let start = Instant::now();
        for graph in owned { black_box(compute(black_box(graph)).unwrap()); }
        let elapsed = start.elapsed().as_nanos() as u64;
        json!({"elapsed_ns":elapsed,"memo_cache_before":before,"memo_cache_after":cache_stats()})
    }

    fn workloads(case: &Value, calls: usize) -> Vec<(&'static str, Vec<Vec<Vec<f64>>>)> {
        let n = case["n"].as_u64().unwrap() as usize;
        let fixed = vec![bits_to_adjacency(case["fixed_word"].as_u64().unwrap() as u32,n);calls];
        let mut result = vec![("fixed",fixed)];
        for (name,key) in [("changing","changing_words"),("collision","collision_words")] {
            let graphs: Vec<_> = case[key].as_array().unwrap().iter()
                .map(|v| bits_to_adjacency(v.as_u64().unwrap() as u32,n)).collect();
            if !graphs.is_empty() { assert_eq!(graphs.len(),calls); result.push((name,graphs)); }
        }
        result
    }

    #[cfg(feature = "memoized-engine")]
    pub fn diagnostics(inputs: &Value, protocol: &Value) -> Value {
        let calls = protocol["micro"]["calls_per_pass"].as_u64().unwrap() as usize;
        let compute = signature_fn("memoized");
        let mut records = Vec::new();
        for case in inputs["micro"].as_array().unwrap() {
            for (workload,graphs) in workloads(case,calls) {
                pse_metatron::memoized_signature::clear_thread_cache();
                for graph in &graphs { black_box(compute(graph.clone()).unwrap()); }
                let before = cache_stats();
                for graph in &graphs { black_box(compute(graph.clone()).unwrap()); }
                let after = cache_stats();
                let hits = after["hits"].as_u64().unwrap()-before["hits"].as_u64().unwrap();
                let misses = after["misses"].as_u64().unwrap()-before["misses"].as_u64().unwrap();
                let evictions = after["evictions"].as_u64().unwrap()-before["evictions"].as_u64().unwrap();
                if workload == "collision" {
                    assert_eq!(hits,0); assert_eq!(misses,calls as u64); assert_eq!(evictions,calls as u64);
                }
                records.push(json!({"n":case["n"],"workload":workload,"calls":calls,
                    "second_pass_hits":hits,"second_pass_misses":misses,"second_pass_evictions":evictions,
                    "before":before,"after":after,"timed":false}));
            }
        }
        json!({"schema":1,"records":records})
    }

    pub fn measure(inputs: &Value, protocol: &Value) -> Value {
        let mut records = Vec::new();
        let calls = protocol["micro"]["calls_per_pass"].as_u64().unwrap() as usize;
        for case in inputs["micro"].as_array().unwrap() {
            let n = case["n"].as_u64().unwrap() as usize;
            for (workload, graphs) in workloads(case,calls) {
                for comparison in protocol["comparisons"].as_array().unwrap() {
                    #[cfg(feature = "memoized-engine")]
                    pse_metatron::memoized_signature::clear_thread_cache();
                    for variant in comparison["variants"].as_array().unwrap() {
                        black_box(one_pass(&graphs,variant.as_str().unwrap()));
                    }
                    for (pair, order) in comparison["micro_orders"].as_array().unwrap().iter().enumerate() {
                        for variant in order.as_array().unwrap() {
                            let variant = variant.as_str().unwrap();
                            let mut row = one_pass(&graphs,variant);
                            let ns = row["elapsed_ns"].as_u64().unwrap();
                            row["comparison"] = comparison["name"].clone();
                            row["n"] = json!(n); row["workload"] = json!(workload);
                            row["pair"] = json!(pair); row["variant"] = json!(variant);
                            row["calls"] = json!(calls); row["ns_per_call"] = json!(ns as f64/calls as f64);
                            records.push(row);
                        }
                    }
                }
            }
        }
        json!({"schema":1,"same_binary":true,"measurements":records})
    }
}

fn main() {
    let args: Vec<_> = std::env::args().collect();
    let inputs: Value = serde_json::from_str(INPUTS).unwrap();
    let protocol: Value = serde_json::from_str(PROTOCOL).unwrap();
    let c = configuration();
    let result = match args.get(1).map(String::as_str) {
        Some("configuration") => json!(c),
        Some("golden") => engine_golden(&inputs,&c),
        Some("engine") => engine_measure(&inputs,&protocol,&c),
        Some("first") => first_macrostep(&inputs,args[2].parse().unwrap(),&c),
        #[cfg(any(feature = "indexed-engine", feature = "memoized-engine"))]
        Some("micro-golden") => micro::golden(&inputs,&args[2]),
        #[cfg(any(feature = "indexed-engine", feature = "memoized-engine"))]
        Some("micro") => micro::measure(&inputs,&protocol),
        #[cfg(feature = "memoized-engine")]
        Some("micro-diagnostics") => micro::diagnostics(&inputs,&protocol),
        _ => panic!("usage: configuration | golden | engine | first N | micro-golden packed/indexed | micro"),
    };
    println!("{}",serde_json::to_string(&result).unwrap());
}
