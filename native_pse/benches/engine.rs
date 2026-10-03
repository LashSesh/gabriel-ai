//! Identical harness for original, extracted and optimized implementations.
//! Run `... golden` for behavioral fingerprints; otherwise emits JSON measurements.
use pse_core::{macro_step, GlobalState};
use pse_graph::{ingest, ObservationAdapter, ObserveError, PersistentGraph};
use pse_types::{content_address_raw, Config, MeasurementContext, Observation, ProvenanceEnvelope};
use serde_json::{json, Value};
use std::alloc::{GlobalAlloc, Layout, System};
use std::hint::black_box;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering::Relaxed};
use std::time::Instant;

struct CountingAllocator;
static COUNT: AtomicBool = AtomicBool::new(false);
static ALLOCS: AtomicU64 = AtomicU64::new(0);
static BYTES: AtomicU64 = AtomicU64::new(0);
// Instrumentation only: each operation delegates with the identical layout to System.
unsafe impl GlobalAlloc for CountingAllocator {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        if COUNT.load(Relaxed) {
            ALLOCS.fetch_add(1, Relaxed);
            BYTES.fetch_add(layout.size() as u64, Relaxed);
        }
        unsafe { System.alloc(layout) }
    }
    unsafe fn dealloc(&self, ptr: *mut u8, layout: Layout) {
        unsafe { System.dealloc(ptr, layout) }
    }
    unsafe fn realloc(&self, ptr: *mut u8, layout: Layout, size: usize) -> *mut u8 {
        if COUNT.load(Relaxed) {
            ALLOCS.fetch_add(1, Relaxed);
            BYTES.fetch_add(size as u64, Relaxed);
        }
        unsafe { System.realloc(ptr, layout, size) }
    }
}
#[global_allocator]
static ALLOCATOR: CountingAllocator = CountingAllocator;

pub struct SensorAdapter;
impl ObservationAdapter for SensorAdapter {
    fn source_id(&self) -> &str {
        "sensor"
    }
    fn canonicalize(
        &self,
        raw: &[u8],
        ctx: &MeasurementContext,
    ) -> Result<Observation, ObserveError> {
        let value: Value =
            serde_json::from_slice(raw).map_err(|e| ObserveError::Canonicalize(e.to_string()))?;
        Ok(Observation {
            timestamp: value["tick"].as_f64().unwrap(),
            source_id: format!("sensor-{}", value["entity"].as_u64().unwrap()),
            payload: raw.to_vec(),
            digest: content_address_raw(raw),
            context: ctx.clone(),
            provenance: ProvenanceEnvelope::default(),
            schema_version: "1".into(),
            phase_hint: Some(value["phase"].as_f64().unwrap()), amplitude_hint: None,
        })
    }
}

pub fn batches(entities: usize, ticks: usize) -> Vec<Vec<Vec<u8>>> {
    (0..ticks)
        .map(|tick| {
            (0..entities)
                .map(|entity| {
                    serde_json::to_vec(&json!({"entity": entity, "tick": tick,
            "phase": (tick % 11) as f64 * 0.02,
            "value": ((tick * 17 + entity * 31) % 101) as f64 / 101.0}))
                    .unwrap()
                })
                .collect()
        })
        .collect()
}

pub fn configuration(mode: &str) -> Config {
    let mut c = Config::default();
    if matches!(mode, "commit" | "falsify" | "cooldown" | "metatron") {
        // Exercise the actual commit path without silently counting rejected ticks.
        c.thresholds.d = 0.0;
        c.thresholds.q = 0.0;
        c.thresholds.r = 0.0;
        c.thresholds.g = 0.0;
        c.thresholds.j = 0.0;
        c.thresholds.p = 0.0;
        c.thresholds.n = 0.0;
        c.thresholds.k = 0.0;
        c.consensus.consensus_threshold = 0.0;
        c.consensus.mirror_consistency_eta = 0.0;
        c.consensus.archive_dominance = 2.0;
        c.consensus.memory_similarity_threshold = 2.0;
        c.carrier.adaptive = true;
    }
    if mode == "adaptive" {
        c.calibration.enabled = true;
        c.calibration.window = 16;
        c.calibration.warmup_ticks = 4;
    }
    if mode == "falsify" {
        c.falsification.enabled = true;
        c.falsification.k = 3;
        c.falsification.gate_on_fail = false;
    }
    if mode == "cooldown" {
        c.consensus.min_crystal_tick = 3;
        c.consensus.crystal_cooldown_ticks = 2;
        c.consensus.startup_crystal_count = 2;
    }
    if mode == "metatron" {
        c.carrier.use_metatron_ladder = true;
    }
    c
}

fn hash(value: &Value) -> String {
    content_address_raw(&serde_json::to_vec(value).unwrap())
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
}

fn graph_snapshot(g: &PersistentGraph) -> Value {
    let nodes: Vec<_> = g
        .graph
        .node_weights()
        .map(|v| {
            (
                v.id,
                v.active,
                v.first_seen,
                v.last_seen,
                v.activation_count,
            )
        })
        .collect();
    let edges: Vec<_> = g
        .graph
        .raw_edges()
        .iter()
        .map(|e| (e.source().index(), e.target().index(), &e.weight))
        .collect();
    let history: Vec<_> = g
        .history
        .iter()
        .map(|r| (r.commit_index, r.digest, r.timestamp))
        .collect();
    let tensor: Vec<_> = g
        .tensor
        .iter()
        .map(|(id, t)| (id, &t.snapshots, &t.timestamps))
        .collect();
    json!({"nodes":nodes,"edges":edges,"embedding":g.embedding,"history":history,
        "tensor":tensor,"hot":g.hot.data,"warm":g.warm.data,"cold":g.cold.data,
        "tick":g.commit_index})
}

pub fn golden() -> Value {
    let mut cases = Vec::new();
    for (mode, entities, ticks) in [
        ("gate", 1, 12),
        ("gate", 8, 12),
        ("gate", 64, 3),
        ("gate", 65, 3),
        ("commit", 8, 6),
        ("commit", 3, 3),
        ("adaptive", 8, 24),
        ("falsify", 8, 3),
        ("cooldown", 8, 9),
        ("metatron", 8, 3),
    ] {
        let c = configuration(mode);
        let mut s = GlobalState::new(&c);
        let mut traces = Vec::new();
        for batch in batches(entities, ticks) {
            let crystal = macro_step(&mut s, &batch, &c, &SensorAdapter).unwrap();
            let state = json!({"graph":graph_snapshot(&s.graph),"gate":s.last_gate,
                "h5":s.h5_state,"prev":s.prev_embeddings,"phase":s.phase_ladder,
                "active":s.active_carrier,"helix":s.last_data_helix,"t2":s.t2,
                "tick":s.commit_index,"status":format!("{:?}",s.engine_state),
                "consensus":s.consensus.last_result,"archive":s.archive.crystals(),
                "pattern_hits":s.pattern_hits,"constraints":s.last_constraint_count,
                "scale":format!("{:?}",s.scale_state),"morph":format!("{:?}",s.morph),
                "adaptive":format!("{:?}",s.adaptive)});
            traces.push(
                json!({"state":hash(&state),"crystal":crystal.as_ref().map(|c|hash(&json!(c))),
                "tick":s.commit_index,"commits":s.crystals_committed}),
            );
        }
        cases.push(json!({"mode":mode,"entities":entities,"traces":traces}));
    }
    // Seeded binary graph histories: duplicate edges, self loops, sparse/dense boundaries.
    let mut graph_cases = Vec::new();
    for seed in 1..=16u64 {
        let mut x = seed;
        let mut g = PersistentGraph::new();
        let mut traces = Vec::new();
        for tick in 0..8 {
            let mut raw = Vec::new();
            for _ in 0..6 {
                x ^= x << 13;
                x ^= x >> 7;
                x ^= x << 17;
                raw.extend_from_slice(&(0xff00 + x % 13).to_le_bytes());
                raw.extend_from_slice(&(0xff00 + (x >> 8) % 13).to_le_bytes());
            }
            let adapter = pse_graph::PassthroughAdapter::new(format!("seed-{}", tick % 3));
            let obs = ingest(&adapter, &raw, &MeasurementContext::default()).unwrap();
            g.apply_observations(&[obs.clone(), obs], &Config::default().persistence)
                .unwrap();
            traces.push(hash(&graph_snapshot(&g)));
        }
        graph_cases.push(json!({"seed":seed,"traces":traces}));
    }
    json!({"schema":1,"engine":cases,"graphs":graph_cases})
}

#[cfg(windows)]
fn process_metrics() -> (f64, usize, usize) {
    #[repr(C)]
    #[derive(Default)]
    struct FileTime {
        low: u32,
        high: u32,
    }
    #[repr(C)]
    #[derive(Default)]
    struct Memory {
        cb: u32,
        faults: u32,
        peak: usize,
        working: usize,
        paged_peak: usize,
        paged: usize,
        nonpaged_peak: usize,
        nonpaged: usize,
        pagefile: usize,
        pagefile_peak: usize,
    }
    #[link(name = "kernel32")]
    extern "system" {
        fn GetCurrentProcess() -> *mut std::ffi::c_void;
        fn GetProcessTimes(
            p: *mut std::ffi::c_void,
            c: *mut FileTime,
            e: *mut FileTime,
            k: *mut FileTime,
            u: *mut FileTime,
        ) -> i32;
        fn K32GetProcessMemoryInfo(p: *mut std::ffi::c_void, m: *mut Memory, size: u32) -> i32;
    }
    let (mut c, mut e, mut k, mut u) = (
        FileTime::default(),
        FileTime::default(),
        FileTime::default(),
        FileTime::default(),
    );
    let mut m = Memory {
        cb: std::mem::size_of::<Memory>() as u32,
        ..Memory::default()
    };
    // Read-only process counters, correctly sized repr(C) structures, valid pointers.
    unsafe {
        let p = GetCurrentProcess();
        assert_ne!(GetProcessTimes(p, &mut c, &mut e, &mut k, &mut u), 0);
        assert_ne!(K32GetProcessMemoryInfo(p, &mut m, m.cb), 0);
    }
    let time = |t: FileTime| ((t.high as u64) << 32 | t.low as u64) as f64 * 1e-7;
    (time(k) + time(u), m.working, m.peak)
}
#[cfg(not(windows))]
fn process_metrics() -> (f64, usize, usize) {
    (0.0, 0, 0)
}

fn run(mode: &str, entities: usize, ticks: usize) -> Value {
    let input = batches(entities, ticks);
    let bytes: usize = input.iter().flatten().map(Vec::len).sum();
    let c = configuration(mode);
    let mut state = GlobalState::new(&c);
    let mut latencies = Vec::with_capacity(ticks);
    let cpu_before = process_metrics().0;
    let start = Instant::now();
    for batch in &input {
        let t = Instant::now();
        if mode == "ingest" {
            let obs: Vec<_> = batch
                .iter()
                .map(|raw| ingest(&SensorAdapter, raw, &MeasurementContext::default()).unwrap())
                .collect();
            state
                .graph
                .apply_observations(&obs, &c.persistence)
                .unwrap();
        } else {
            black_box(macro_step(&mut state, batch, &c, &SensorAdapter).unwrap());
        }
        latencies.push(t.elapsed().as_nanos() as u64);
    }
    let elapsed = start.elapsed().as_secs_f64();
    let (cpu, rss, peak) = process_metrics();
    latencies.sort_unstable();
    let quantile = |q: f64| latencies[((ticks as f64 * q).ceil() as usize).saturating_sub(1)];
    let commits = state.crystals_committed;
    let nodes = state.graph.graph.node_count();
    let edges = state.graph.graph.edge_count();
    drop(state);
    // Separate untimed allocation pass; includes processing, excludes engine/input construction.
    let mut state = GlobalState::new(&c);
    ALLOCS.store(0, Relaxed);
    BYTES.store(0, Relaxed);
    COUNT.store(true, Relaxed);
    for batch in &input {
        if mode == "ingest" {
            let obs: Vec<_> = batch
                .iter()
                .map(|raw| ingest(&SensorAdapter, raw, &MeasurementContext::default()).unwrap())
                .collect();
            state
                .graph
                .apply_observations(&obs, &c.persistence)
                .unwrap();
        } else {
            black_box(macro_step(&mut state, batch, &c, &SensorAdapter).unwrap());
        }
    }
    COUNT.store(false, Relaxed);
    json!({"mode":mode,"entities":entities,"ticks":ticks,"observations":entities*ticks,
        "bytes":bytes,"seconds":elapsed,"obs_per_s":(entities*ticks) as f64/elapsed,
        "ticks_per_s":ticks as f64/elapsed,"bytes_per_s":bytes as f64/elapsed,
        "p50_ns":quantile(0.5),"p95_ns":quantile(0.95),"p99_ns":quantile(0.99),
        "cpu_seconds":cpu-cpu_before,"cpu_cores":(cpu-cpu_before)/elapsed,
        "rss_bytes":rss,"process_peak_rss_bytes":peak,"commits":commits,"nodes":nodes,"edges":edges,
        "allocations":ALLOCS.load(Relaxed),"allocated_bytes":BYTES.load(Relaxed)})
}

fn scaling(workers: usize) -> Value {
    let input = batches(8, 256);
    let c = configuration("gate");
    let barrier = std::sync::Barrier::new(workers);
    let cpu_before = process_metrics().0;
    let start = Instant::now();
    let hashes: Vec<_> = std::thread::scope(|scope| {
        let handles: Vec<_> = (0..workers)
            .map(|_| {
                let (input, c, barrier) = (&input, &c, &barrier);
                scope.spawn(move || {
                    let mut s = GlobalState::new(c);
                    barrier.wait();
                    for _ in 0..4 {
                        for batch in input {
                            black_box(macro_step(&mut s, batch, c, &SensorAdapter).unwrap());
                        }
                    }
                    hash(&graph_snapshot(&s.graph))
                })
            })
            .collect();
        handles.into_iter().map(|h| h.join().unwrap()).collect()
    });
    let elapsed = start.elapsed().as_secs_f64();
    assert!(hashes.iter().all(|h| h == &hashes[0]));
    json!({"workers":workers,"seconds":elapsed,"obs_per_s":(workers*8*1024) as f64/elapsed,
        "cpu_seconds":process_metrics().0-cpu_before,"equal_states":true,
        "scope":"independent engines; includes spawn, join and final state hashing"})
}

fn main() {
    if std::env::args().nth(1).as_deref() == Some("golden") {
        println!("{}", serde_json::to_string_pretty(&golden()).unwrap());
        return;
    }
    // Warm initialization and code paths outside measurement. Also proves a nonempty commit workload.
    let warm = run("commit", 3, 2);
    assert!(warm["commits"].as_u64().unwrap() > 0);
    let mut measurements = Vec::new();
    for _ in 0..5 {
        for (mode, entities, ticks) in [
            ("ingest", 1, 4096),
            ("ingest", 8, 512),
            ("gate", 1, 4096),
            ("gate", 8, 512),
            ("gate", 32, 64),
            ("gate", 65, 128),
            ("adaptive", 8, 256),
            ("commit", 8, 16),
        ] {
            measurements.push(run(mode, entities, ticks));
        }
    }
    let scaling: Vec<_> = [1, 2, 4].into_iter().map(scaling).collect();
    println!("{}",serde_json::to_string_pretty(&json!({"schema":1,"measurements":measurements,
        "scaling":scaling,"logical_cpus":std::thread::available_parallelism().map(|n|n.get()).unwrap_or(1),
        "platform_counters":cfg!(windows)})).unwrap());
}
