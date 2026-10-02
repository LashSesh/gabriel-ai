# Raw-price forecasting profile

`stream-risk/v1` is an explicit extension of the Gabriel owner. It accepts one positive numerical source series, produces risk forecasts from the accepted price prefix, learns when target observations arrive, and emits an exact model-based quantity proposal. The proposal has no effect executor. This profile uses the same persistent owner described in `CONTRACT.md`; it does not change the default two-adapter registry.

```python
from gabriel_runtime import Store
from gabriel_runtime.stream import extended_registry

with Store.create("stream.sqlite", extended_registry()) as store:
    receipt = store.submit({
        "id": "bind-stream", "contract": "stream", "op": "bind", "at": 0,
        "expected_head": store.head,
        "payload": {"adapter": "stream-risk/v1", "config": {
            "source_id": "synthetic-example", "horizon": 1,
            "risk_budget": "10", "unit_exposure": "100", "max_units": 100
        }}
    })
```

The command-line interface selects the registry explicitly with `--profile stream`. The dedicated `stream-demo` command generates synthetic positive dyadic prices, performs a correction and issues another forecast. A legacy store must still be opened with its originally bound registry. The runtime never guesses a registry from an untrusted journal or imports user-selected code.

## Frozen configuration and algorithm

Configuration has exactly `{source_id, horizon, risk_budget, unit_exposure, max_units}`.

- `source_id`: nonempty ASCII text, at most 128 characters.
- `horizon`: exact integer 1 or 5, in **source observation intervals**.
- `risk_budget`: nonnegative canonical reduced rational string, at most 128 characters.
- `unit_exposure`: strictly positive canonical reduced rational string, at most 128 characters.
- `max_units`: exact integer from 0 through 1,000,000.

Booleans cannot substitute for integers. Canonical rational strings include `"0"`, `"10"` and `"3/2"`; strings such as `"10.0"` or `"6/4"` are not accepted as canonical rationals. The configuration is immutable within a contract. Risk budget and unit exposure must have compatible caller-declared monetary units; the runtime does not authenticate this interpretation.

The prediction algorithm is fixed:

| Component | Parameters |
|---|---|
| Variance initialization | First 60 one-interval squared log losses |
| Variance half-lives | 20 and 120 observations |
| Historical scenario window | 250 observations |
| Upper tail probability | 1/40; confidence 39/40 |
| Base experts | Raw historical simulation and filtered simulation at fast weights 0, 1/4, 1/2, 3/4, 1 |
| Additional ES experts | Issued fast quantile multiplied by a severity ratio with half-life 125 or 500 completed issued targets |
| Severity initial state | Raw ratio 1.5; only the emitted ratio is clipped to [1,20] |
| Aggregation | Common simplex weights in `(Q/E, 1/E)` coordinates |
| Online update | Centered score gradient, cumulative squared norm, scale 0.1, Euclidean simplex projection |
| Lane assignment | Origin source index modulo horizon |
| Initial aggregate state | Uniform weights over eight experts; zero squared-gradient accumulators |

The six base forecasts call the unchanged `ecb_risk.forecast_candidates`. The pool and projection call unchanged functions in `aggregate_risk`. The correction-aware severity fold uses the same transition formula as `severity_risk.replay_severity`, applied to the quantile actually issued for each completed target. Severity half-lives count completed issued targets across lanes; aggregate gradient accumulators are separate by lane. Static fitting, optimizer selection, data downloads and the reserved currency columns are not part of this adapter.

This profile begins learning at its own first eligible issued origin. It does not import the separate historical experiment's first-2010 learned checkpoint. Equality comparisons must use the same initialization and accepted source prefix. All forecast and learner arithmetic is binary64. Exact serialization of the resulting values is not an outward-rounded numerical certificate.

## Source record operation

The only domain operation is `record`, with exactly:

```json
{"index":0,"event_at":0,"received_at":0,"revision":0,"rate_hex":"0x1.9000000000000p+6"}
```

`rate_hex` must be a finite positive canonical `float.hex()` string. Counters and clocks are exact nonnegative integers. These three temporal quantities are distinct:

1. `index` is the consecutive source-observation slot. New slots start at zero and advance by one without gaps.
2. `event_at` is the declared occurrence time. It strictly increases between new slots. A revision keeps the original slot and event time.
3. `received_at` is the source-declared receipt time. New accepted source versions cannot regress in this clock. It satisfies `event_at <= received_at <=` the enclosing owner command's `at`.

The owner `at` records availability within this computational owner, on the declared common timestamp clock. Source indices are not compared with timestamps. A forecast target is slot `origin_index + horizon`; its event timestamp becomes known when that slot arrives.

A new slot starts at revision zero. A correction to an existing slot advances its revision by exactly one. Identical canonical content for an already accepted `(index, revision)` is a native no-op. Conflicting reuse is rejected. Different owner commands carrying an identical native source record can consume owner budget while creating no new source version, forecast or feedback. Identical owner-command retries preserve the original owner receipt as described in `CONTRACT.md`.

New slots are retained even when no forecast is available. For horizon 1, the earliest eligible origin is index 310, requiring 311 observations; for horizon 5 it is index 314, requiring 315. The adapter reports `unavailable` with reason `warmup`, `zero_variance_history`, `nonpositive_or_unordered_base_forecast`, or `issuance_capacity` as appropriate. It does not replace an invalid forecast with an epsilon or a fabricated zero. A zero initial variance can leave the unchanged legacy forecast generator unavailable even after subsequent movement, because that generator checks positivity throughout the retained variance history. There is no automatic reseeding or recovery rule for this case.

Nonfinite derived return, variance, gradient, accumulator or forecast arithmetic rejects the entire operation before owner commit. Individually finite positive rates can still produce division overflow or underflow before a logarithm; these are also rejected. Such a rejection leaves the accepted source prefix and all issued outputs unchanged.

## Prediction and target timing

Every issued record and current view carries:

```text
prediction_basis = "next_unreceived_observation"
```

This means the forecast uses only the accepted receipt prefix. It does **not** assert that the target event lies in the physical future. For example, if origin slot 310 with event time 310 is ingested at owner time 1000, slot 311 can have occurred at event time 311 while still being absent from this owner. A later estimate of that unreceived observation is receipt-causal, but is not a forecast made before the target event.

When an issued target becomes available, its feedback explicitly records `target_event_at` and `target_after_issue`, the exact comparison `target_event_at > issued_at`. Ordinary timely input makes this true; delayed ingestion can make it false. Neither case authenticates a source timestamp. `first_matured_at` is the owner time at which the target slot first became available in the accepted operation stream. An earlier source-declared receipt cannot make a target retroactively available to an earlier owner state.

## Immutable issuance and correction replay

Each new slot first matures any issued target whose endpoint is now available. The adapter then reconstructs current feedback from all completed issues, ordered by `(first_matured_at, target_index, issue_position)`. Corrections preserve this position.

For each completed issue, its current loss uses the latest accepted versions of its two endpoint prices. Its severity response uses the immutable fast quantile stored at issuance. Its aggregate gradient uses the immutable eight-expert bank and immutable simplex weights stored at issuance. That centered gradient is then applied to the current reconstructed lane state using cumulative squared gradient norms and the existing simplex projection.

The distinction matters after a correction: the reconstructed state just before an update can differ from the weights at which that update's gradient was evaluated. `staleness_l2_hex` records the Euclidean norm of this difference. The unchanged no-correction online guarantee cannot simply be asserted for this path; any bound must account for the discrepancy. The package supplies explicit records suitable for that check.

After completed-target feedback, a new slot can produce its current six base experts, two severity experts and pooled forecast. A correction to an old slot never issues a retrospective forecast at that old origin. It changes current learner state and the raw prefix used by subsequent new-slot forecasts. All older issued forecasts, proposals, source digests and issuance digests remain unchanged. In particular, the adapter never silently regenerates historical expert banks from corrected prices and presents them as the banks actually issued.

Each immutable issue has exactly:

```text
forecast_id, prediction_basis,
origin_index, target_index, origin_event_at, issued_at, receipt_cutoff,
source_digest, expert_order, expert_var_hex, expert_es_hex,
issued_weights_hex, issued_accumulator_hex, fast_q_hex,
severity_raw_ratio_hex, var_hex, es_hex, proposal, digest
```

The source digest binds the latest selected version of every accepted slot at issuance. The issue digest binds the complete record excluding its own `digest` field. Expert order is the existing eight-name `aggregate_risk.EXPERTS` order. The arrays have eight expert values and eight weights; severity raw ratios have two values. No historical issue is overwritten by a correction or later model output.

## Read-only quantity proposal

For the issued binary64 ES value `E`, let `e = Fraction(E)` be its exact dyadic value, `u` the rational unit exposure, and `b` the rational budget. The proposal selects the largest integer `n` from zero through `max_units` satisfying

```text
n * u * e / 100 <= b.
```

All operations in this comparison are exact rational arithmetic on the **stored model output**. The proxy is scaled upper log loss. It is not a bound on realized loss, a guarantee of ES calibration, executable profit and loss, portfolio optimization, or a market order.

Proposal fields are exactly:

```text
kind = "read_only_log_loss_proxy"
units, unit_exposure, risk_budget, es_exact, proxy_loss,
next_unit_proxy_loss, max_units, budget_satisfied, maximum_feasible
```

Rational fields are canonical strings. `next_unit_proxy_loss` is retained even when `units == max_units`; in that case the next unit is excluded by the configured quantity cap, not necessarily by the budget. Budget satisfaction and maximality are arithmetic facts about this finite choice and the supplied ES, not empirical risk certificates. No external action follows from a proposal.

## Results, state and resource scope

`apply` returns candidate state and `{accepted, issued, view}`. `issued` is either the new immutable record or null. A current view contains exactly:

```text
semantic_profile = "stream-risk/v1"
arithmetic = "binary64"
prediction_basis = "next_unreceived_observation"
source_id, horizon, source_count, revision_count, issued_count,
pending_count, status, reason, last_issued_digest, learner
```

`revision_count` counts **all accepted source-version records, including each initial revision-zero record**. It is not the number of corrections alone. `pending_count` counts issued targets whose endpoint slot has not yet arrived. Initial status is `empty`; successful new forecast issuance is `issued`; unavailable new-slot forecasts are `unavailable`; a correction reports `revised` with reason `current_learner_replayed`.

Learner fields are `severity_raw_ratio_hex`, `lane_weights_hex`, `lane_accumulators_hex` and `active_feedback`. Every active-feedback record contains:

```text
forecast_id, first_matured_at, target_index, target_event_at,
target_after_issue, lane, loss_hex, gradient_hex, centered_gradient_hex,
gradient_norm_squared_hex, step_hex, pre_weights_hex, post_weights_hex,
accumulator_before_hex, accumulator_after_hex, staleness_l2_hex
```

No pending outcome enters those records or the learner update. The JSON state stores `config`, accepted `receipts`, immutable `issued`, separate `maturity` metadata, `last_status` and `last_reason`. No mutable latest-price cache is treated as independent evidence.

Fixed profile capacities are 1,024 source slots, 2,048 accepted source versions and 512 issued forecasts. After the issuance capacity is exhausted, admissible observations can still be retained and previous targets matured, but no additional forecast is issued. Owner event and byte budgets remain independently enforced. The adapter reconstructs current learner state and the needed raw prefix; it is a bounded reference implementation with potentially quadratic cumulative replay work, not a high-throughput, memory-constant or hard real-time service.

Implementation fingerprints include the stream adapter, shared owner/canonicalizer, relevant adapter helper code, unchanged forecasting/aggregation/severity source files, NumPy and SciPy versions, and fixed parameters. The current environment and mathematical model remain part of reproducibility assumptions. No physical validation, generalized predictive superiority, authenticated real-time backtest, or market deployment follows from matching the historical batch algorithm.
