# Incremental execution of the stream contract

`IncrementalStreamRiskAdapter` is an alternate execution implementation of the
existing `stream-risk/v1` financial contract. It keeps the same initialization,
command, state, result, and view schemas. Forecast generation, immutable issued
records, correction semantics, exact rational proposals, rejection conditions,
and source/issue limits remain defined by `stream.py` and `STREAM.md`.

```python
from gabriel_runtime.incremental import IncrementalStreamRiskAdapter, incremental_registry

adapter = IncrementalStreamRiskAdapter()
# initialize/apply/view have exactly the reference adapter's signatures.
# Use incremental_registry() with the unchanged transactional Store.
adapter.reset_metrics()
# ... run transitions ...
print(adapter.metrics())
adapter.clear_cache()
```

The registry retains the adapter identifier `stream-risk/v1`, but the bound
fingerprint includes `execution: bounded-incremental/v1` and the source hash of
`incremental.py`. The explicit CLI execution profile is `incremental`; a database
created under `stream` must still be opened under `stream`. Selecting a different
profile is not a store migration. Domain states and results are compared for
canonical-byte equality; execution fingerprints and complete owner logs differ.

## Source and feedback dependencies

One ephemeral variance cache retains at most 1024 source values, their one-step
losses, and the two variance recurrences. Its key is the sequence of actual
binary64 source values. Appending an observation performs one new variance
recurrence after initialization. A historical correction preserves the common
source prefix and repeats the affected variance suffix in its original order.
A correction within the first 61 prices recomputes the initial 60-loss mean.
Rewinds and forks use only the verified common prefix.

Only the six base-expert scenario rows for the current origin are passed to the
tail calculation. Each row still has 250 scenarios. Full retained-history
validity checks remain: finite variance states, positive historical variance
mixtures, and finite raw and standardized scenarios in every historical eligible
window. In particular, an invalid old scenario cannot become acceptable merely
because it left the current window. The two severity experts and the aggregate
are constructed by the inherited reference transition.

One ephemeral feedback cache retains at most 512 mature contributions and their
numerical checkpoints. Each dependency key serializes the actual issue record,
maturity record, and both current endpoint records. It does not treat a stored
issue digest or source digest as authority. A key includes issue-time weights,
expert banks, target indexes, clocks, and the latest endpoint values. Changing
any included field prevents inappropriate reuse, even if a caller leaves the
stored digest unchanged.

An issue gradient is evaluated at its immutable issued bank and issued weights.
Thus changing one source value at index `s` can change mature losses only for
issues with origin `s` or target `s`. There are at most two such issues at a fixed
horizon, and both lie in lane `s % h`. Their severity responses and gradients are
recomputed. The aggregate update repeats only the affected lane suffix; other
lanes retain their unchanged checkpoints. The global two-scalar severity fold
repeats its suffix from the earliest changed contribution. All operations retain
the reference order. The algebraic real-arithmetic severity correction formula
is deliberately not substituted for the binary64 recurrence.

A normal append matures at most one target because new indexes are contiguous
and each origin issues at most once. Its new feedback extends the existing fold.
Unchanged mature gradients are reused rather than reevaluated. General cache
misses, rewinds, or interleaving unrelated contracts can require more work; no
cache-hit assumption changes the output contract.

## Why replay is preserved

Before the earliest changed dependency, the inputs and deterministic operations
are identical, so the saved checkpoint equals a fresh reference fold. A cached
contribution uses only fields proven unchanged by its dependency key. Repeating
all affected recurrence steps from that checkpoint therefore reproduces the
reference path by induction. For an unaffected lane, no changed input or prior
lane state enters its update. Reusing that lane's checkpoint is the same
induction restricted to its projected subsequence.

The variance argument is analogous, with the 60-loss mean as the initial state.
The current tail row equals the final row consumed by the original transition;
retained global validity checks preserve historical rejection conditions.
Numerical byte equality is additionally checked on the supplied environment.
The implementation does not promise portable byte equality across arbitrary
NumPy, SciPy, hardware, or floating-point implementations; the execution
fingerprint retains the environment versions used by the reference contract.

## Cache authority and diagnostics

Caches are not serialized into a domain state, receipt, or journal. Losing them
changes work, not meaning. A failed outer command may leave completed derived
work in memory, but subsequent reuse still requires matching actual dependencies.
Returned mutable views and arrays do not alias private cached values. A cache
entry is replaced only after its local numerical fold is complete. No externally
supplied cache import or trusted checkpoint interface exists.

The maximum additional numerical cache is linear in source count and in mature
feedback count times the fixed lane/expert dimensions. There is one cache per
adapter instance for variance and one for feedback; there is no unbounded cache
indexed by source identity. `clear_cache()` discards both. `reset_metrics()`
resets only counters. `metrics()` returns a fresh dictionary:

| Counter | Meaning |
|---|---|
| `variance_steps` | One initial mean or one two-filter EWMA recurrence computed |
| `forecast_scenario_rows` | Rows submitted to base tail evaluation; ordinarily six per forecast attempt |
| `gradient_evaluations` | Calls to the transformed score-gradient routine |
| `projections` | Executed simplex-projection updates |
| `severity_steps` | Mature rounds on which both severity recurrences are computed |
| `cache_reuses` | Variance or learner invocations reusing verified prior numerical work |
| `cache_resets` | Explicit cache clearing, or an existing numerical cache lacking a reusable initial prefix |

Counters are cumulative diagnostics, including work attempted before a rejected
outer command. They are not accepted-observation counts or elapsed-time claims.
Calls to private helpers outside the bounded scalar stream profile may delegate
to the reference implementation and are outside the instrumented profile.

## Remaining cost and scope

The implementation reduces repeated numerical work. It still constructs source
arrays, checks historical validity, serializes dependency keys, copies public
state, emits the complete active-feedback view, and lets the unchanged owner
canonicalize and journal complete results. These operations remain linear in
retained history. Old corrections can still require long recurrence suffixes.
A fresh audit executes the full retained command history. The bounded reference
limits remain 1024 source indexes, 2048 accepted records, and 512 issues; this
profile does not establish unlimited streaming, distributed execution, production
storage qualification, or new predictive accuracy.

The learner policy is unchanged. In particular, revising an outcome does not
turn its immutable issued weight into the revised replay weight. The existing
fixed-replay comparison continues to require its signed mismatch term. A
separate learner evaluated at reconstructed weights would define another policy
and another performance measure, not an optimization of this execution profile.
