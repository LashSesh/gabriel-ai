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

