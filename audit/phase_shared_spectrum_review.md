# Optional shared-spectrum core integration audit

## Scope and change

The new `shared-spectrum` feature is off by default. Root and `pse-core` forward it to `pse-topology`. `phase-hoist` forwarding was also added, independently. Public `macro_step` keeps its arguments and return type, delegating to a private const-generic implementation. This permits reference and shared execution in one test binary; only feature-selected mode is reached through the public function.

With sharing disabled, C16 computes the topological signature and C18 independently reconstructs the Laplacian/decomposition exactly as before. With sharing enabled, C16 calls `compute_topological_signature_with_spectrum`, retaining the eigensystem that was already computed, and C18 moves it instead of recomputing it. No cross-step cache or equivalence hash is used.

## Input and gate audit

1. Both C16 and C18 observe `&state.graph` after crystal construction and before archival/morphogenic updates. Between their spectral computations the original program only copies topological scalar fields into the crystal. These copies cannot mutate the graph.
2. Both use `TopologyConfig::default()`. C16 passes `min(spectral_k_max,n)` and C18 passes `spectral_k_max`; `spectral_decompose` immediately applies `min(k_max,n)` again, yielding the same effective argument.
3. The Laplacian construction, eigensolver branch, arithmetic order, and all fields in the resulting decomposition are unchanged. n=0 and n=1 return the same explicit special cases. The optional helper returns Some exactly when n<=500; C18 has the same n<=500 gate. For n>500 the helper returns None and C18 remains skipped.
4. Earlier observation/persistence failures, gate rejection, cooldown, memory shortcuts and consensus rejection return before either block. Sharing introduces no new work on those paths.
5. C18 continues calling `init_kuramoto_state` afresh. It does not reuse C16's evolved Kuramoto state. Spectral reuse is not a spectral accuracy correction.
6. Removing work can change scheduler timing. `multi_scale_tick` retains inherited wall-clock budget checks. Equality of complete multiscale outputs is conditional on those checks taking the same branches; in particular, tests cannot establish universal wall-clock independence. The optimization does not alter the checks or limits.
7. The assertion that a spectrum exists inside the shared n<=500 C18 branch follows from the helper's return contract. Tests exercise both sides of this bound. No fallback hides violation of that contract.

## Added but not agent-executed tests

`crates/pse-core/src/shared_spectrum_tests.rs` contains three feature-gated same-binary differential tests. They invoke private reference and shared implementations, compare full returned crystals as Debug and serialized JSON bytes, and compare broad state snapshots including graph/tensors/history/storage, archive, carriers, intrinsic state, morph state, scale state, gates, memory public entries/statistics, PoR fields and startup fields. This is an explicit selected snapshot, not serialization of private PatternMemory implementation internals.

- Two committed steps each for n=0,1,3,5,7,8,32 with empty, path, disconnected, complete and cycle fixtures.
- A committed step at each n=100,101,199,200,201,500,501: CTQW size threshold, the default k=50 full/partial decomposition threshold at n=200, and the C16/C18 threshold.
- Gate rejection, a successful commit followed by cooldown rejection, persistence-capacity failure and controlled adapter failure.

No builds or timings were performed by this agent. Root execution must resolve actual compiler/test outcomes before claiming these tests pass. The topology agent separately prepared an old-body oracle and eigensystem comparisons including n32/k2, where the inherited partial-solver issue can occur.
