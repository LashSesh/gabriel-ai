# Optional conditioned continuous-time graph walk

`pse_topology::conditioned_walk` is an explicit, additive API for the complete
complex state

\[
\psi(t)=\exp(-itL)\psi_0,\qquad L=D-A.
\]

The caller selects an initial state and can query it at many times. The existing
all-pairs CTQW statistics, default aliases, thresholds, and commit pipeline do
not use this API. The explicit native engine observer described below does. Its outputs are complex amplitudes, not legacy propagation
statistics or predictions. It is a classical numerical calculation, not a
quantum-hardware backend.

## Interface

```rust
use pse_topology::conditioned_walk::{
    BackendChoice, ConditionedWalkPlan, Complex,
};
use pse_topology::SparseLaplacian;

let graph = SparseLaplacian {
    n: 2,
    degree: vec![1.0, 1.0],
    adjacency: vec![(0, 1, 1.0), (1, 0, 1.0)],
};
let plan = ConditionedWalkPlan::new(&graph, BackendChoice::Auto)?;
let state = [Complex::new(1.0, 0.0), Complex::new(0.0, 0.0)];
let prepared = plan.prepare_state(&state)?;
let amplitudes = prepared.state_at(0.25)?;
# Ok::<(), pse_topology::conditioned_walk::WalkError>(())
```

`BackendChoice::Auto` recognizes a strict complete-graph special case, otherwise
uses a full eigendecomposition. `BackendChoice::Spectral` forces that same full
spectral implementation on every accepted graph and provides a matched baseline.
`plan.dimension()` and `plan.backend()` expose the actual choice; the latter is
`WalkBackend::CompleteGraph` or `WalkBackend::Spectral`.

The immutable plan owns its matrix representation, not the caller's graph. A
`PreparedState` borrows the plan and owns the original initial vector and its
state-specific mean or spectral overlaps. Mutating the original graph or state
after construction does not change the prepared calculation. No implicit graph
update, state update, truncation, normalization, stochastic process, or fallback
to a different dynamical model occurs.

## Accepted graph and state contract

- `n >= 1`, and the degree vector has exactly `n` entries.
- Degrees and weights are finite and nonnegative. Self-loops are rejected.
- Every supplied ordered pair `(i,j)` is unique and has an explicitly supplied,
  exactly equal reverse `(j,i)`. This also applies to explicit zero entries.
  Missing pairs represent zero weight. Negative zero equals positive zero.
- Each supplied degree must exactly equal the finite floating-point sum of its
  incident weights in increasing neighbour-index order. Adjacency input order
  does not affect this test. The API does not repair or tolerance-adjust degrees.
- Each initial state has exactly `n` finite complex entries. It need not have
  norm one; zero states and arbitrary finite norms are permitted. Squared norms
  are not computed during input validation, so a finite state is not rejected
  merely because its squared norm would overflow.
- Times may be positive, negative, or zero and must be finite. `t=0` returns the
  supplied finite state bit for bit after successful preparation. Singleton and
  edgeless graphs are supported.

The sign convention is the **positive** Laplacian with `exp(-itL)`. If weights
are dimensionless, time is dimensionless. If weights are angular frequencies,
time is in the corresponding reciprocal unit. Uniform nonnegative coupling is
encoded in the weights and degrees. There is no separate hidden coupling or
physical unit conversion; zero coupling gives an edgeless operator. This is not
the negative-Laplacian sign convention used in the inspected QSO Hamiltonian.

The current `compute_laplacian` producer accumulates incident edges in an order
compatible with increasing neighbour index, but external producers must satisfy
the declared contract themselves. Negative or invalid values previously clipped
by an upstream producer cannot be recovered or diagnosed by this API.

## Uniform complete-graph specialization

With `n` vertices, off-diagonal weight `w`, and a common stored diagonal `d`,
the actual matrix represented by these stored numbers has

\[
L=(d+w)I-w\mathbf1\mathbf1^\top,
\quad P=\mathbf1\mathbf1^\top/n.
\]

Its two eigenvalues are `lambda0 = d-(n-1)w` and `lambda1 = d+w`, yielding

\[
\psi(t)=e^{-it\lambda_0}P\psi_0+
 e^{-it\lambda_1}(I-P)\psi_0.
\]

For ideal arithmetic with `d=(n-1)w`, these reduce to zero and `nw`. The API
recognizes this case only when every stored off-diagonal weight is exactly equal,
all degrees are equal, and the stored degree also equals the rounded product
`(n-1)*w`. No approximate geometry or near-clique receives this specialization.
A valid uniform graph whose repeated degree sum differs from that product goes
through the full spectral backend. For example, `n=13,w=1.7` exercises that guard.

Even when the rounded-product check passes, the real number represented by `d`
can differ slightly from the exact real product of the stored binary64 weight.
`lambda0` is therefore computed by one fused multiply-add and is retained in the
evolution. Silently fixing this residual eigenvalue to zero would change the
actual matrix, which can become visible at large times. `lambda1` is computed
by floating-point addition. An edgeless Auto plan returns its initial state at
all finite times.

## Cost and numerical scope

Both choices validate and construct the dense matrix once in `O(n²+E)` time and
`O(n²)` temporary space. This makes construction comparable across backends and
avoids repeatedly searching the sparse edge list for each dense entry.

| Operation | Recognized complete graph | Full spectral backend |
|---|---:|---:|
| Plan construction | O(n²+E) | O(n²+E+n³) |
| Stored plan | O(1) beyond scalar metadata | O(n²) |
| Prepare one state | O(n) | O(n²) |
| Query its full state at one time | O(n) | O(n²) |
| Prepared state storage | O(n) | O(n) |

The spectral backend uses all `n` eigenpairs from nalgebra's `SymmetricEigen`;
no legacy truncated decomposition is inherited. It uses convergence tolerance
`f64::EPSILON` and iteration cap `max(1024,128*n)` (saturating multiplication),
then verifies finite eigenvalues and vectors. The implementation does not certify
eigenvector residuals or orthogonality; the independent numerical tests are
accuracy evidence for their tested cases, not a universal error bound.

The complete-graph formula is algebraically exact for the stated two-subspace
model. Its Rust implementation uses binary64 arithmetic and ordinary library
trigonometric functions. It is neither bitwise equivalent to a dense
eigendecomposition nor a rigorous rounding certificate. At very large times,
eigenvalue rounding amplified by time and trigonometric argument reduction can
lose accuracy. Very small entries can underflow; cancellation can increase
relative error. Finite outputs alone do not establish an accuracy guarantee.

Nonfinite intermediate phases, overlaps, means, eigenvalues, or final components
produce errors. An intermediate overflow is an error even when hypothetical
later cancellation would make the exact final result finite. A preparation error
occurs before any time query, including a prospective `t=0` query. No silent
renormalization or replacement kernel masks these errors.

## Verification and performance interpretation

The separate `conditioned_walk_tests.rs` covers independent matrix-power and
clique formulas, complex unnormalized states, sign, norm and inverse evolution,
degeneracy, zero time, singleton/edgeless cases, degree rounding, duplicate and
asymmetric entries, malformed dimensions, and overflow boundaries. Test presence
alone does not claim execution; the accompanying recorded command outputs state
what was actually run.

A fair performance comparison uses identical graphs, initial states, times,
complete complex outputs, and validation, separating plan construction, state
preparation, and repeated queries. An improvement here applies to this optional
conditioned query, not automatically to Gabriel's existing all-pairs engine,
decision quality, or end-to-end workload.

## Native engine observer

`pse::Engine::conditioned_snapshot(choice)` binds the calculation to the
engine's actual observation graph. This is an explicit read-only observer call
between steps. It does not replace the all-pairs statistic used by `Engine::step`.
The native engine observer and the lower-level arbitrary-norm walk have distinct
source contracts, as specified below.

```rust
use pse::conditioned::{BackendChoice, Complex, RegionChoice};
// `engine` has already ingested observations through Engine::step.
let snapshot = engine.conditioned_snapshot(BackendChoice::Auto)?;
let labels = snapshot.vertex_ids();
let initial: Vec<_> = labels.iter().enumerate()
    .map(|(i, _)| Complex::new(if i == 0 { 1.0 } else { 0.0 }, 0.0))
    .collect();
let prepared = snapshot.prepare_state(&initial)?;
let targets = &labels[..1];
let region = prepared.prepare_region(targets, RegionChoice::Auto)?;
let mass = region.mass_at(0.25)?;
```

The returned object owns its Laplacian and plan. `tick()` gives the attempted
engine batch count at capture; `vertex_ids()` gives the dense matrix order;
`laplacian()` exposes an immutable reference to the represented operator.
`identity()` is a SHA-256 identifier of the versioned sign/model convention,
tick, ordered labels, degree bits and lexicographically ordered adjacency bits.
All integer fields and binary64 bit patterns use fixed-width little-endian
encoding, with explicit vector lengths. The identity is independent of backend
selection, but intentionally depends on vertex order and tick. It is neither a
graph-isomorphism identity nor a digest of all engine state, nor authentication.

Snapshot capture rejects a faulted engine, an empty graph, inconsistent or
nonbijective vertex maps, and negative/nonfinite original directed edge weights.
The original weights are checked before the existing projection could clip
negative values. A fixed limit of `MAX_CONDITIONED_VERTICES = 512` is checked
before dense allocation. The projection includes inactive vertices, ignores
self-loops, sums parallel directed weights, and forms `(W+W^T)/2`; these are
explicit inherited graph semantics, not a directed causal transport model.
No graph mutation, input normalization or weight repair is applied to the engine.

A snapshot remains usable after later steps, failures or reset. Its tick and
identity remain those of capture. A caller needing the current graph must create
a fresh snapshot; there is no hidden refresh or alias to mutable graph state.
The engine's gate, archives, statistics and crystal bytes are unaffected by the
observer. Observing a nonempty graph does not assert that any crystal was committed.

### Source and readout contract

`prepare_state` accepts one finite complex value in snapshot order for every
vertex. `prepare_named_state` accepts the same complete source labelled by
`VertexId`, in arbitrary input order. Unknown, duplicate and missing labels are
rejected; a missing source component is never silently replaced by zero.
Both methods reject the all-zero source and **normalize before propagation**:
first divide by the largest absolute real or imaginary component, then divide
by the resulting Euclidean norm. Thus an ordinary source and its smallest
representable nonzero or near-maximum finite rescaling have a usable normalized
observer representation. Very small relative components may still underflow in
binary64. This procedure is part of the observer model, not a change to the
lower-level `ConditionedWalkPlan`.

`PreparedConditionedState::state_at(t)` returns the normalized state's complex
amplitudes, not the original source magnitude. `source_scale()` and
`scaled_source_squared_norm()` retain a factored description of the original
norm without requiring its square to be representable. They should not be
blindly multiplied when a finite product is required.

`readout_at(t)` returns normalized amplitudes, per-vertex intensities divided by
the stored initial normalized squared norm, and their sum `norm_ratio`. There is
no renormalization by the evolved output norm and no clamp to `[0,1]`; observed
norm drift remains visible. These intensities are coordinates of the stated
coherent graph model, not empirical event probabilities. Relative phase matters:
a coherent source assembled from square roots of weights generally differs from
a classical mixture of independently evolved basis sources.

`target_mass_at(t, targets)` sums the normalized intensities over unique valid
vertex identifiers. Targets are summed in snapshot index order, independently
of input target order. Empty targets give zero, and the entire graph ideally
gives one. Invalid time, overflow and numerical failures are reported as errors.
A tiny binary64 excursion outside the ideal unit interval is returned visibly.

### Fixed-region scalar query

`prepare_region(targets, RegionChoice::Auto)` validates a fixed target set once.
If the underlying snapshot selected `WalkBackend::CompleteGraph`, it stores
three coefficients for the exact-real formula

\[
 m_A(t)=c_0+c_c\cos(nwt)+c_s\sin(nwt).
\]

For normalized input `a`, mean `mu`, residual `b_i=a_i-mu`, and initial squared
norm `N`, the coefficients are

\[
 c_0=(|A||\mu|^2+\sum_{i\in A}|b_i|^2)/N,\quad
 c_c=2\Re\sum_{i\in A}\bar\mu b_i/N,\quad
 c_s=2\Im\sum_{i\in A}\bar\mu b_i/N.
\]

The represented matrix's constant-subspace residual eigenvalue contributes
only a common phase, which cancels in this scalar readout. No full state vector
is allocated for `PreparedRegion::mass_at(t)` on this path. Region setup is
linear after target validation; the subsequent scalar query takes constant
work and storage independent of graph size. The captured snapshot still stores
its labelled Laplacian, so the observer as a whole does not have constant memory.

`RegionChoice::StateReadout` forces evolution of the full normalized state and
then sums the same region, using the already selected snapshot backend. General
graphs always use this path. `PreparedRegion::backend()` reports either
`RegionBackend::CompleteGraph` or `RegionBackend::StateReadout`. A matched scalar
task can therefore compare forced spectral state evolution, automatic full-state
evolution, and the automatic fixed-region formula with identical output meaning.
The original full-state benchmark cannot supply timing claims for this observer.

Zero time and zero frequency return the cached initial region mass. Other times
use the equivalent anchored form `m(0)-2*c_c*sin(nwt/2)^2+c_s*sin(nwt)` to reduce
near-zero cancellation, with ordinary binary64 coefficients and trigonometry. Cancellation,
large-time argument reduction and different evaluation orders can differ from
full-state evaluation; no universal error enclosure is claimed. A numerical
deadband used by a downstream decision is an operational tolerance, not a
statistical confidence interval or a rounding certificate.

Two negative controls matter for interpretation. A spatially constant source is
stationary in intensity on an ideal Laplacian. A zero-mean source on a uniform
complete graph also has stationary intensity because it occupies one eigenspace.
Neither yields temporal discrimination merely by running more time queries.
