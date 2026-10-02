# Engine-bound conditioned observation: mathematical contract and limits

This note derives the observer contract independently of the implementation. It
does not assert novelty for unitary evolution, orthogonal projectors, or the
complete-graph spectrum. Source inspection covered `native_pse/src/lib.rs`,
`pse-topology/src/lib.rs`, `conditioned_walk.rs`, and `pse-core/src/query.rs`.

## 1. What can be integrated without changing the old model

The inherited topological consumer computes `mean_propagation_time` from an
all-pairs threshold scan. Its spectral routine can truncate eigenpairs and clip
small negative eigenvalues. A full-spectrum action on one vector is a different
function. It cannot silently replace that statistic.

A separate engine-bound observation may instead freeze the current graph, its
ordered vertex identifiers and its engine tick, construct the validated operator
L, prepare an explicitly supplied nonzero complex source, and return its complete
evolved field and regional intensities. An immutable snapshot identifies which
graph is being observed even after further engine steps. Automatic and forced
spectral backends can implement this same observation contract. Timings of a
complete step/snapshot/query/readout workload then measure a complete new
observation task, rather than the old ingestion task alone.

The source projection `compute_laplacian` first replaces each directed edge
weight by its nonnegative part, accumulates parallel/opposite edges, then assigns
half the accumulated weight to both directions. Degrees are the corresponding
weighted sums. Thus the observer retains neither directed orientation nor the
negative part of a signed exposure. All retained graph vertices participate;
any restriction to an active subset would need its own explicit contract.

## 2. Regional observation

Let L be a finite real symmetric matrix, U(t)=exp(-itL), psi != 0, and A a set
of vertex coordinates. Set N=||psi||_2^2 and

    r_A(t) = ||R_A U(t) psi||_2^2 / N,

where R_A is the coordinate projector. Exact arithmetic gives 0 <= r_A <= 1,
r_empty=0, r_all=1, and additivity over disjoint sets. Simultaneously permuting
L, psi and A preserves the answer. Multiplying psi by any nonzero complex scalar
also preserves it. A single coherent source is not a classical source mixture:

    |U sqrt(p)|^2 != |U|^2 p

in general, and relative source phases affect the former. With the two-vertex
unit-weight Laplacian, t=pi/4, psi=(1,i)/sqrt(2), the coherent probabilities are
(0,1), whereas the incoherent mixture p=(1/2,1/2) remains (1/2,1/2).

For numerical norm evaluation, let s be the maximum absolute real/imaginary
source component and use N_s=sum |psi_i/s|^2. Then 1 <= N_s <= 2n. Dividing
output intensities by this input norm, rather than their observed sum, exposes
norm drift. A reported norm ratio is a diagnostic, not a certified error bound.
Scaling only the readout cannot undo underflow or overflow that occurred while
evolving the original amplitudes. Neither clipping a probability to [0,1] nor
renormalizing an erroneous output establishes numerical correctness.

If a normalized exact state phi and approximation phi_hat satisfy
||phi_hat-phi|| <= epsilon, then

    | ||R_A phi_hat||^2 - ||R_A phi||^2 | <= 2 epsilon + epsilon^2.

Proof: expand the difference with e=phi_hat-phi and apply Cauchy--Schwarz and
||R_A||<=1. An empirically observed reference discrepancy is not itself a bound
on all future queries. Threshold decisions with a declared numerical abstention
band remain engineering decisions unless their error budget is certified.

## 3. Exact clique readout and its representational ceiling

Let P=11^T/n and L=delta P+rho(I-P), with real delta,rho. For a uniform weighted
clique represented by diagonal d and off-diagonal -w, delta=d-(n-1)w and
rho=d+w. Define mu=(sum psi_i)/n, theta=(rho-delta)t, and

    a_A = sum_{i in A}|psi_i|^2,
    z_A = mu sum_{i in A} conjugate(psi_i).

Then

    N r_A(t) = a_A
      + 2(1-cos(theta)) (|A||mu|^2 - Re(z_A))
      - 2 sin(theta) Im(z_A).

Proof: U psi = exp(-it rho)[psi+(exp(i theta)-1)mu 1]. Expand each squared
component and sum over A. The global phase disappears. This formula is valid
for complex sources; the minus sign on the sine term is essential.

Consequences:

* For fixed A, the three coefficients can be prepared in O(n); repeated scalar
  time queries then require O(1) work. A benchmark that requires only r_A must
  not present full-vector propagation as its only possible baseline.
* The matrix of vertex intensities sampled at any number of times has real
  rank at most three. If the source is real up to a global phase, the sine
  coefficient vanishes and rank is at most two. This is an exact structural
  statement; numerical rank checks only corroborate it on finite examples.
* If mu=0, all intensities are constant on the clique. A uniform source is
  also constant in intensity; for an exact row-sum-zero Laplacian it is fixed
  on every graph. Multiple time queries cannot remove these blind spots.
* A basis source on a clique distinguishes its own vertex from the remaining
  n-1 vertices, which all have identical intensity. D6 geometry and S7
  enumeration cannot restore a distinction absent from this operator.

For an incoherent distribution p, B_ij=|U_ij|^2 gives

    B p = (1-beta) p + beta mean(p) 1,
    beta = 4 sin^2(theta/2)/n.

Here beta can exceed one for n=2,3; B nevertheless remains nonnegative and
doubly stochastic. For n>=4 this is a convex mixture. At n=128 the uniform
mixture coefficient never exceeds 0.03125. Off-diagonal transfer probabilities
are at most 4/n^2. In particular the inherited default threshold 0.5 is never
reached off the diagonal on an exact full-spectrum clique with n>=3; its
threshold-time fallback is therefore constant. This last statement does not
imply bitwise equivalence to truncated or numerically perturbed old outputs.

## 4. Relation to the research objective

The user objective is a system with demonstrated task advantage. The present
operator is one possible computational component. Faster exact observation is
a valid computational result; it does not establish better prediction or risk
decisions. A fixed invertible transformation U preserves the information in its
complete complex input. Taking squared magnitudes discards information. Better
performance of a restricted downstream learner is possible but must be measured
against appropriate task baselines with the same available information.

Unitary evolution is distance preserving and has no asymptotically attracting
isolated state on the complete state space. A strategic target called a fixed
point must not be confused with a dynamical attractor of this operator. Adding
damping, state estimation or feedback would change the mathematical model and
require a separate stability and task-performance analysis.

The independent executable `reproduction/check_engine_observer_math.py` checks
the regional formula against SciPy matrix exponentials, coherent/incoherent
distinction, permutation/phase/scaling invariance, stationary-source controls,
and finite sampled-rank examples. Its data are synthetic. It neither executes
the Rust engine nor estimates a market or predictive advantage.
