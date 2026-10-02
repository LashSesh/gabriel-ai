# Dynamic whole-engine workload design (read-only source inspection)

Project: `recovered/project/Gabriel/native_pse`. No native sources were edited. No build, simulation, timing, or fixture was executed for this note. The recommendations below require execution and guards before reporting results.

## Actual graph semantics

- `crates/pse-graph/src/lib.rs`, `PersistentGraph::apply_observations` (approximately lines 348–448), creates a clique over the unique source IDs in each batch when at most 64 unique sources occur. Therefore the previous all-source-per-tick JSON batches necessarily produce complete K3, K5, K7 throughout.
- A batch containing exactly one observation/source adds a vertex but no edge. Two distinct source observations add exactly their pair. UTF-8 JSON payloads avoid the independent binary edge-list branch (payload length >=16 and invalid UTF-8).
- Edges persist. Positive `lambda_decay` changes weights, not their presence. Normal macro-step ingestion does not delete edges. Signature attachment treats an edge in either direction as a unit undirected connection and disregards weights/self-loops.
- No persistence/observation configuration switches clique construction to kNN. The kNN API in `pse-navigator` is separate and does not occur in the normal `macro_step` path.
- Normal morphogenic updates can add synthetic vertices via split/merge. Constraint extraction can shrink the returned region. Both must be controlled, explicitly reported, and asserted if the experiment is to mean fixed n.

## Recommended minimal public-input fixture

Reuse the existing SensorAdapter and UTF-8 JSON format. For each n in {3,5,7,8}, create a fresh `GlobalState` and send n singleton macro-step batches, one source at a time. This is an untimed bootstrap made entirely through the normal API. Then send two-source batches in a deterministic edge order, one previously absent pair at each step. Each measured macro-step follows the entire commit path. This generates edge counts 1,...,n(n-1)/2 on exactly n nodes. A path-first order `(0,1),(1,2),...,(n-2,n-1)` followed by remaining pairs in lexicographic order begins disconnected, becomes a sparse tree, then densifies. These are synthetic acquisition episodes, not arbitrary graph rewrites.

Use the prior force-commit configuration (all eight thresholds zero; consensus and mirror-consistency thresholds zero; dominance and memory-similarity thresholds 2; carrier adaptive true), adding:

```
c.extraction.convergence_tau = 1.0;
c.adaptation.split_threshold = 3.0;
c.adaptation.merge_distance = 0.0;
```

Reason for extraction setting: `apply_observations` clamps potential p to [0,1]. The extractor uses population variance of p, bounded by 1/4, and the default fast path therefore returns every current vertex with an empty constraint program. This deliberately controls region selection and its cost; do not imply typical/default extraction work was exercised.

Reason for adaptation settings: embeddings and their attractor centroid lie in [0,1]^5. Euclidean distance is at most sqrt(5). The pressure recursion starts at zero and is `p_t = (distance_t + p_(t-1))/2`, hence stays at most sqrt(5), below 3. Splits are disabled on these bounded inputs without infinity values. Merge condition is strict distance < merge_distance; finite nonnegative distances never pass zero. No inactive vertices then arise. A large persistence `max_vertices` should remain unchanged: its guard uses current IDs plus batch length, not just newly introduced IDs.

Assertions must verify actual successful commits; graph vertex count; exact edge-count progression; full region length n; and attached signature present with n for 1<=n<=7, absent for n=8. Check these per tick outside timers or through a separate golden run. Graph presence should be collected independently from the actual induced adjacency, not inferred from a requested scenario name. Compare complete serialized crystals and the same selected-state scope as previous measurements across variants.

## Cache scope and useful controls

A changing graph does not automatically create misses after a repeated trajectory has warmed the thread-local cache. Record cache statistics and complete `(n,labelled_edge_bits)` distinct-input counts, including bootstrap. A single fixed-n monotone episode has at most 1+n(n-1)/2 topology states (22 for n=7). Its repetition can become almost entirely hits.

Three honest regimes:

1. **Sparse repeated input:** bootstrap n vertices, add path edges, then issue 16 fixed existing-pair or singleton observations. All measured signatures retain the same path topology even though weights, embeddings, timestamps and memory evolve. Measures cache reuse in a sparse whole-engine workload.
2. **Cold acquisition:** bootstrap through the public API, clear only the memoizer before the measured pair-addition episode (outside the timer), and report this explicit artificial cache condition. Every subsequently added edge changes the full key, so fixed-n signatures are first uses during that episode. Reset the cache for each new episode. This isolates miss overhead; it is not a claim about a warm long-lived thread.
3. **Mixed acquisition episodes:** pre-generate 32 or 64 seeded permutations of the full pair list and use a new engine for each episode. This provides many distinct intermediate labelled graphs without modifying native source or using direct graph mutation. n=7 can exceed the 256-entry cache across episodes; n=3 has only eight possible fixed-n input graphs, so cannot serve as a broad miss workload. Freeze exact batches, enumerate actual distinct keys, and count hits/misses/evictions rather than assume a cache regime. All-source-ID sets remain identical so differing vertex names do not fabricate different signature keys.

Comparisons should keep exactly the same workload, seed, phase inputs, full configuration, and reset policy for every variant. Report ticks/s or ns/committed macro-step as the primary metric; total observations differ between singleton bootstrap and two-source acquisition. Include bootstrap timing only as a separately defined full-episode result, not silently in some variants. n=8 is an attached-signature-ineligible control only after bootstrap; its n<=7 bootstrap commits are still signature eligible and should be excluded from that specific control timer.

## Larger concrete optimization candidate (unmeasured)

`crates/pse-core/src/lib.rs`, C16 block (~859–879) calls `pse_topology::compute_topological_signature`. For n<=500 this constructs a weighted Laplacian and calls `spectral_decompose` with `min(default_k_max,n)`. Immediately following C18 (~883–911) reconstructs the same Laplacian and spectral decomposition on the unchanged graph, passing `default_k_max=50`. `spectral_decompose` itself clamps k to n, so the effective inputs and order are identical. A helper that exposes/reuses the just-computed spectral decomposition can remove one Laplacian build and eigen-decomposition per committing tick on this path, without a cross-tick cache or graph-key assumption.

Important semantic boundary: C16 evolves its Kuramoto state for up to ten RK4 steps; C18 intentionally initializes an unevolved Kuramoto state. Do not reuse the evolved Kuramoto object for C18. Keep topology fields and all arithmetic evaluation order unchanged, and confirm full crystal/state outputs for empty/singleton, sparse/disconnected/dense, repeated eigenvalue, and larger size controls. The known approximate spectral issues are inherited and not fixed by computation reuse. This observation establishes duplicate work, not a measured bottleneck or a speedup magnitude.
