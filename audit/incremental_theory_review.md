# Independent review: correction-aware cached execution

Status: design-level proof and adversarial dependency review, based on the frozen
`gabriel_runtime/stream.py` and unchanged `ecb_risk.py`, `aggregate_risk.py`,
`severity_risk.py`, and `engine.py`. No new implementation or benchmark is claimed
in this note. The bounded financial stream remains the semantic reference.

## 1. Exact equivalence target

Fix the same numerical environment, immutable configuration, accepted source
records, owner operation times, and arithmetic order. Let R be the existing
reference reducer. A cached reducer C is a refinement if a projection P removing
only acceleration metadata satisfies P(C(S,e)) = R(P(S),e), including acceptance,
rejection, native-duplicate behavior, result/view fields, and immutable issue
records. After initialization, induction over operations gives equality of all
projected trajectories. Rejected operations and retries require separate cases;
an uncommitted speculative computation must not change later results.

Binary64 byte identity is stronger than real-arithmetic equivalence and is
conditional on operation order, array layout/reduction behavior, dependencies,
and execution environment. An algebraically equivalent parallel reduction or
scalar replacement of a vector kernel is not sufficient. If cached state or a
registry fingerprint changes, global journal heads and materialized state hashes
need not equal the reference's. State the result as projected semantic equality;
compare actual issue digests and domain outputs separately.

## 2. Dependency graph for one accepted source correction

The source is x[0],...,x[n-1]; the corrected slot is s and the fixed horizon is h.

- One-step return r[t] = 100 log(x[t]/x[t-1]) changes only at t=s and t=s+1,
  restricted to valid t>=1.
- The initial variance v[60] is the existing mean of r[1:61]^2. If a changed
  return is in this seed, recompute that original reduction and every recurrence
  afterward. For s=0 this includes r[1], not a nonexistent r[0]. Otherwise start
  at the earliest changed recurrence index greater than 60 and retain the
  previous variance. Subsequent EWMA states can all change.
- Horizon return y[t] = 100 log(x[t]/x[t-h]) changes only at endpoint indexes
  t=s and t=s+h, restricted to t>=h. Distinguish these from issue origin indexes.
- Standardized scenarios z[t] = y[t]/sqrt(h*v_mix[t-h]) inherit every changed
  variance denominator, even where their numerator is unchanged. A last-window
  computation therefore needs correct historical variance states, not merely
  the last window's prices.
- Existing issue j at origin i_j uses outcome endpoints i_j and i_j+h. Its
  current feedback loss changes only when i_j=s or i_j=s-h. At most two issued
  targets are affected, possibly fewer if unavailable, unissued, or pending.
  Both affected origins have lane s mod h.
- The bank, issued weights, fast quantile, issuance metadata, proposal, and issue
  digest are immutable. A source correction must not regenerate those banks.
  Consequently all other current gradient and severity-response contributions
  remain unchanged, although replay states downstream may change.

The dependency claim is about numerical inputs. A new revision with unchanged
`rate_hex` still changes receipt history, revision counts and the source identity
bound to subsequent issues. It cannot be discarded as an entire semantic no-op.

## 3. Contributions versus stateful folds

A target contribution consists of its current endpoint loss, severity response,
gradient at the original issued bank and weights, centered gradient, and squared
norm. Its numerical dependency key must contain (or bind): exact endpoint value
bytes; the original issue bank and weights; the original fast quantile; confidence,
algorithm and numeric-environment identity. A forecast ID or origin index alone
is insufficient. A digest is an acceleration identity under its stated collision
assumption, not an independent proof of numerical correctness.

Metadata in the feedback record additionally depends on first-maturity position,
owner time, target event time and issue time. Numeric contributions may be reused
without reusing stale metadata. Holding an endpoint value fixed while changing a
receipt or revision does not imply all output bytes are fixed.

The aggregate fold has per-lane state (weights, cumulative gradient energy).
Because the corrected contributions belong to one lane, only that lane's suffix
from its first affected mature target must be replayed. All unchanged lanes keep
identical sequential folds. But every downstream pre-weight, post-weight, step,
accumulator and staleness diagnostic in the affected lane may change.

The two severity accumulators share the global first-maturity order across all
lanes. Replay their suffix from the earliest affected target, even though only
one aggregate lane is affected. The two temporal dependency graphs are different.

Every resumed fold needs a checkpoint strictly before its earliest altered
contribution. Checkpoints after that boundary must be replaced. Reuse after a
verified convergence of complete exact state is possible but unnecessary. Equal
weights alone do not imply equal cumulative energy or equal future updates.

## 4. Sequential arithmetic is part of the witness

Maintain the original loss division then logarithm. Replacing log(right/left)
with log(right)-log(left) changes rounding and accepts some inputs the reference
rejects due to ratio overflow/underflow. Preserve its current rejection semantics.

Maintain the original variance initialization reduction and EWMA multiplication
and addition order. Maintain centered gradients and gradient norms using the
reference function and row layout. Replaying an unchanged suffix preserves byte
identity by induction if all inputs and entering state bytes agree.

Do not use the real-arithmetic severity correction identity
m' = m + (1-lambda)*lambda^(n-j)*(R'_j-R_j) as a bitwise shortcut: floating-point
reassociation and cancellation can differ from the original sequential replay.
Do not update a cumulative energy by subtracting an old squared norm and adding
its replacement if exact byte preservation is required. Replay that lane's suffix
from a preceding identical checkpoint instead.

Computing only the newest historical-simulation scenario row can preserve the
reference output if the exact same horizon returns, standardized values, tail
routine, row order, quantile selection, mean reduction and scaling operations are
used. This requires executed equality checks; algebra alone does not establish
NumPy reduction identity for differently shaped arrays.

## 5. Availability and acceptance semantics

The reference checks variance positivity over its entire retained history, not
only current variance or the current scenario window. A zero initial seed can
keep forecasts unavailable after later movements. The optimized path must retain
this global predicate. An old-source correction may restore or break it.

Warmup begins at origin 60+h+250-1. Issuance capacity is checked before forecasting.
Corrections do not trigger a historical or current-origin issue. A cache must not
introduce extra validation failures by eagerly evaluating computations the
reference does not require at that operation. Preserve warmup, duplicate and
capacity short-circuit behavior.

Pending targets have no active contribution. Arrival of their endpoint supplies
first maturity; a source-declared earlier receipt does not retroactively move
that position. Corrections preserve first-maturity order. A cache indexed only by
source index must not silently recalculate that order.

## 6. Adversarial cache cases

Essential tests beyond an ordinary append stream:

1. s in {0,1,59,60,61}; newest slot; slot not at any issued endpoint; pending
   endpoint; both possible affected targets present; h=1 and h=5.
2. Equal-value revisions: numeric state unchanged, source identities and revision
   metadata updated. A changed value later restored must still follow lineage.
3. Early correction whose direct horizon returns lie outside the current window
   but whose variance effect changes the current forecast.
4. Flat initial seed, subsequent motion, correction restoring positivity, and a
   correction creating zero seed. Match reference availability, not just values.
5. Multiple contracts with equal indexes and different source IDs, configs,
   horizons, expert banks or endpoint values through one adapter instance.
6. Cold rebuild, close/reopen, interleaved contracts, branching direct-reducer
   calls, and failure after cache computation but before owner commit.
7. Mutation of returned objects or supplied prior state: cached objects must not
   alias caller-owned lists/dictionaries.
8. Same weights but changed cumulative energy; changed severity with unchanged
   weights; stale feedback metadata with identical gradient; exact hinge equality.
9. Canonical native duplicates and owner retries; conflicting revision reuse;
   nonfinite derived ratio; late receipt with target_after_issue=false.
10. Warmup and capacity short circuits, and minimum/maximum permitted source and
    accepted-record counts. Do not test only histories that emit at every origin.

A useful cache invalidation oracle is the unchanged reference's canonical domain
output after every accepted operation, plus rejection equivalence and unchanged
historical issue bytes after every correction. Independent full recomputation
should verify cached numerical arrays, not merely invoke the same incremental
helper under another name.

## 7. Honest complexity claims

Let n be retained source length, J matured targets, K expert count, W scenario
window, E base-filter count, and h fixed. Count mathematical operations separately
from wire serialization and persistent-owner work.

The reference reconstructs the full learner on every transition/view, costing
O(J*K*log K) with the current sorted simplex projection. Its newest forecast calls
an all-prefix batch generator, processing all eligible rows and their W-scenario
windows. Ignoring library partition constants, its numerical work scales with
O(E*n*W) per new observation, plus full variance recurrences. Repeated appends
therefore create quadratic numerical work in retained length.

An exact cache can process an ordinary new observation using O(E*W + K*log K)
new numerical work at fixed horizon, ignoring validation, source hashes, metadata,
serialization and memory copying. It needs historical information for correction
and audit; this is not a constant-memory claim.

A correction can require O(n-s) variance suffix work and O(J-j) severity replay;
its affected aggregate lane can require O((J-j)/h*K*log K) fold work. Early,
frequent corrections can recover quadratic cumulative work. No general sublinear
correction bound follows from only two changed outcome contributions.

The current owner clones/canonicalizes the full retained state and full result;
issues and active feedback grow with history. Source digests also bind the full
latest prefix. Thus even with constant append numerical work, serialized bytes,
state copying, materialization and per-transition audit comparisons remain at
least linear in retained semantic content. Cumulative ordinary owner work and
stored repeated receipt content can remain quadratic. Replay starts cold and
must re-execute every accepted operation; caches can reduce its numerical work
without making complete semantic audit independent of history.

Report numerical-kernel timings, direct adapter timings, and full owner timings
separately, on exactly the same accepted histories and outputs. Pair warmed/cold
runs and include correction-heavy cases. Operation counters can support a
mechanistic explanation but are not wall-clock speedups. Finite speedups are
conditional on the stated Python/dependency versions and benchmark machine.

## Conclusion

The defensible result is an execution refinement: fewer repeated numerical
computations at identical observable decisions on the tested bounded profile,
with a dependency proof for all valid operation histories under the specified
arithmetic assumptions. It does not change forecast quality, the source model,
the original statistical evidence, or the owner's storage scalability.

## Review of manuscript draft `theory.tex`

Reviewed the initial Section `sec:incremental` draft. The correction-locality
statement and proof are valid for fixed immutable issues and fixed first-maturity
order. Its two affected origins and lane identity are correct. The full-history
positive-variance guard is correctly stated. Sequential severity versus lane-local
aggregation is accurately separated.

The sufficient-cache proposition is a useful conditional refinement theorem,
not implementation verification. Three precision improvements are recommended:

- Require retained completed node results to remain unmodified. Correct input
  identity alone does not protect an aliased cached array that the caller mutates.
  Inputs/results should be immutable values in the proposition, or copied and
  compared as such by the implementation.
- For machine primitives, 'same inputs' means the exact typed machine values,
  including shape/order and signed-zero bits where they affect the primitive,
  in the fixed execution environment. Mathematical equality of scalar values
  alone is insufficient for an unrestricted bitwise theorem.
- Include control predicates and failure results among observables, or explicitly
  restrict the proposition to successful demanded evaluations and state that
  rejection/short-circuit equivalence is separately checked. An optimized evaluator
  must not demand an invalid primitive on a branch the reference never evaluates.

The row count 6*p*(p+1)/2 versus 6*p is correct for one append-only contract starting
at its first eligible origin when all those origins invoke generation and emit.
It counts scenario rows, not variance updates, copying, or `tail` function calls
(the latter are six per generator invocation in both implementations). The
m*(m+1)/2 versus m gradient count is correct for the stipulated pattern with one
new maturity per considered transition and no extra views or cache misses. It is
not the count for every possible stream delivery, particularly post-capacity
appends without new maturity, native duplicates, corrections, or explicit views.
The draft labels these limits adequately; retain them in the results caption.

No correction to the locality proof or the stipulated operation counts is needed.
The sufficient criterion should remain conditional, and the implemented cache's
actual key/value invariants need code-level and adversarial verification before
claiming that it satisfies the criterion on every accepted input.

## Read-only implementation review

Reviewed `incremental.py` with SHA256
`587a39b94df8121bee18820fc466b38a20f87352e69892c3e1446368d6686b36`, including the
full-history y/z finite guard. No concrete semantic blocker was found in the
reviewed valid owner-state paths.

Verified by inspection:

- Variance tokens inspect every actual price byte. Common-prefix reuse handles
  append, same-prefix rewind and divergent source branches. A correction inside
  the seed recomputes it; a later correction starts at its first changed loss.
- Learner context covers the complete config, and each contribution token covers
  actual maturity, issue and endpoint fields rather than trusting supplied digests.
- Common checkpoints copy weights and accumulators. A changed suffix marks both
  the old and new affected lanes, which handles divergent/reordered direct folds;
  unchanged lane checkpoint reuse has unchanged within-lane predecessors.
- The severity suffix is replayed globally, with reference operation order.
- Cache-only arrays are copied on storage/return; public results are canonical
  copies. Cached feedback/contribution/checkpoint references are not exposed as
  caller-mutable objects by the inspected methods.
- Failure before owner commit cannot authorize cache reuse: future calls compare
  their actual inputs again. Clearing caches cannot alter protocol state.
- Inherited apply/forecast preserve source validation, warmup, issuance-capacity,
  duplicate handling, immutable issues, and positive-variance history predicates.
  The new y/z guards preserve validity of discarded historical scenario rows.

Executed a focused independent variance test: 660 exact byte comparisons over
30 generated price histories, 14 append/rewind lengths and 8 correction positions
including indexes0,1,59,60,61. All passed on NumPy2.3.5. The reproducible reviewer
script is `check_variance_cache_review.py`; parameters, source hashes and output
are in `variance_cache_review.json`. This test does not replace the separate full
transition and rejection verifier.

Important actual-complexity qualification: the present implementation still
constructs full-prefix horizon returns, mixed variance arrays and standardized
arrays for each forecast. Its append numerical work therefore includes O(E*n),
even though its tail reductions use only E current rows and its warm EWMA requires
one new step. Prefix tokens, full contribution tokens, list prefixes and output
copies add further linear work. The earlier O(E*W+K*log K) discussion describes a
possible fully dependency-indexed numerical cache, not this implementation's
actual complete append cost. The manuscript should name the retained prefix-array
work explicitly alongside owner serialization and hashing.
