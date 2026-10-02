# Mathematical review of the generated eight-expert stream

Read-only design review. No existing model source or result was changed. This note verifies the proposed stale-gradient decomposition and specifies its exact scope; it does not claim execution of the new pipeline.

## 1. Convex loss and boundary assumptions

Fix one horizon/lane and one chosen as-of replay. Enumerate its eligible, matured forecasts in the declared replay order. Each original issue j freezes a bank `(Q_jk,E_jk)` and original issued simplex weights `u_j`. Assume:

- a finite nonempty bank, `0 < Q_jk <= E_jk < infinity`;
- `u_j` lies in the closed probability simplex `Delta_K`;
- the selected current outcome `y_j` is finite;
- beta lies strictly between 0 and 1;
- the original bank and issued weights are immutable; corrections change selected outcomes/current replay, not these stored values.

Set `a_jk=Q_jk/E_jk` and `b_jk=1/E_jk`. The realized transformed FZ0 loss is

`f_j(w) = -log(b_j·w) + a_j·w + max(y_j b_j·w - a_j·w,0)/beta - 1`.

This is finite and convex on the **closed** simplex. Indeed `b_j·w >= min_k b_jk > 0`, including at vertices and faces. No strictly positive individual weight or interior comparator assumption is needed. Compactness makes all gradients on this particular finite bank finite in exact arithmetic, although no uniform across-time bound follows without additional limits on expert values and outcomes.

A subgradient at `u_j` is

`g_j = -b_j/(b_j·u_j) + a_j + zeta_j (y_j b_j-a_j)/beta`,

where `zeta_j=1` for a positive hinge argument, `0` for a negative argument, and any value in `[0,1]` at equality. Choosing zero at equality matches the current implementation.

Define the centered gradient `h_j = g_j - mean(g_j)*1`. For any simplex points x,z, `h_j·(x-z)=g_j·(x-z)`. Also `Proj_Delta(v-eta*g_j)=Proj_Delta(v-eta*h_j)` in exact Euclidean projection, since adding a common coordinate shift leaves the simplex projection unchanged.

## 2. Valid replay update and regret decomposition

Let `v_1` be the replay's initial simplex state (uniform in the planned implementation). The current replay update uses the subgradient at the **original issued** weights, but applies it to the **current replay** state:

`G_j = G_(j-1) + ||h_j||^2`, `eta_j = c/sqrt(G_j)`,

`v_(j+1) = Proj_Delta(v_j - eta_j h_j)`,

with `G_0=0`, `c>0`. Skip the update when `G_j=0`. Do not silently replace `v_j` by `u_j` in the projection: that would be a different recurrence when corrections or delayed overlapping issues make them unequal.

For any fixed comparator `w* in Delta_K`, convexity gives

`f_j(u_j)-f_j(w*) <= h_j·(u_j-w*)`

`= h_j·(u_j-v_j) + h_j·(v_j-w*)`.

The Euclidean projection inequality supplies, for eta_j>0,

`h_j·(v_j-w*) <= [||v_j-w*||^2-||v_(j+1)-w*||^2]/(2 eta_j) + eta_j ||h_j||^2/2`.

For a general positive step sequence this yields the exact distance-weighted telescoping bound

`sum_j [f_j(u_j)-f_j(w*)] <= ||v_1-w*||^2/(2 eta_1)`

`+ (1/2) sum_(j=2)^n (1/eta_j-1/eta_(j-1)) ||v_j-w*||^2`

`- ||v_(n+1)-w*||^2/(2 eta_n)`

`+ (1/2) sum_j eta_j ||h_j||^2 + sum_j h_j·(u_j-v_j)`.

For cumulative G and constant c, eta is nonincreasing. Since the simplex's squared Euclidean diameter is at most 2, the proposed simpler bound is valid:

**`sum_j [f_j(u_j)-f_j(w*)] <= 1/eta_n + (1/2) sum_j eta_j ||h_j||^2 + R_n`,**

where **`R_n = sum_j h_j·(u_j-v_j)`**.

More generally replace `1/eta_n` by `D^2/(2 eta_n)` for a domain of diameter D. The initial state need not be uniform for this diameter bound; uniformity merely fixes the implemented initial condition. It may allow a comparator-dependent tighter first term, but is unnecessary for validity.

With `G_0=0`, the standard inequality

`sum_j (G_j-G_(j-1))/sqrt(G_j) <= 2 sqrt(G_n)`

gives

**`sum_j [f_j(u_j)-f_j(w*)] <= (c+c^(-1))*sqrt(G_n) + R_n`.**

This is a standard convexity/projection decomposition specialized to the stored-issue runtime. It is not a new universal delayed-learning theorem.

### Zero gradients

If the **centered** gradient is zero, then convexity implies `f_j(u_j)-f_j(w*) <= 0` for every simplex comparator. Such a round can be dropped from the upper-bound calculation, and its R term is zero. Reindex the proof on nonzero-gradient rounds; if there are none, total regret is nonpositive and the bound is zero. If G is already positive, including a zero-gradient round with unchanged eta and v is equivalent. Never write `1/eta_n` when every eta is zero.

### Signed residual and conservative bound

`R_n` is a **signed** issuance-versus-replay term. It need not be nonnegative and must not be described as a norm penalty unless an upper bound is used. A simple nonnegative bound is

`R_n <= sum_j ||h_j|| ||u_j-v_j|| <= sqrt(2) sum_j ||h_j||`.

The latter can be linear and gives no useful no-regret conclusion by itself. Reporting the measured signed term and its norm upper bound separately is informative. Cauchy–Schwarz also gives

`R_n <= sqrt(G_n * sum_j ||u_j-v_j||^2)`.

Vanishing average regret would require both `sqrt(G_n)/n -> 0` and a suitable sublinear upper bound on R_n; it does not follow merely from finite inputs or a clipped proposal.

### Recovery of the old on-time bound

If the replay is uncorrected and, in every lane, each prior issued forecast matures and is updated before that lane's next issue, then induction gives `u_j=v_j`. Consequently R_n=0 and the old cumulative AdaGrad-style realized-path bound is recovered. Fixed h-step horizons, contiguous source origins, h lanes and updates before same-index issuance suffice for the old implementation. Arbitrary delayed receipts, overlapping outstanding issues within a lane, corrections or different ordering can break this equality. The residual is precisely the term required rather than a claim that the old bound still applies unchanged.

## 3. Meaning of a fixed as-of replay

The functions f_j in the bound are those formed from the **original issued expert rows** and the **selected current outcome revisions** at one declared snapshot. Each matured target occurs once in that replay. A later snapshot may use a different revised y_j, a different eligible set, and therefore different replay gradients and current weights. The theorem applies again to that snapshot's sequence; it does not sum the same corrected target as multiple independent losses and does not rewrite previously published forecasts or historical score reports.

The comparator is a fixed simplex mixture over the actual stored expert rows. It is not a counterfactual market strategy that would generate different expert forecasts, receive different data, place different trades or alter its environment. Adaptive expert-bank generation is compatible with a realized-path bound after conditioning on the stored rows; it does not turn the comparison into a population or causal policy-performance guarantee.

If old targets become unscorable under corrected nonfinite values, the implementation must have an explicit rejection/hold policy. A numerical failure cannot be silently omitted while keeping an unchanged regret claim over all targets. The theorem requires finite admitted loss/gradient arithmetic in its mathematical model.

## 4. Severity-bank and raw-prefix semantics

The two severity experts must retain each original **fast-base quantile**, not the final pooled Q, when calculating their response `1+(y-Q_fast)_+/(beta Q_fast)`. Original severity ES outputs also remain in each immutable issued bank. A raw endpoint correction can change current base forecasts and current severity state for future issues, while the gradient for an old aggregate issue still uses the bank originally emitted at that issue.

The existing severity recurrence is one maturity-ordered accumulator per horizon stream, whereas the cumulative aggregate has horizon lanes. Preserve and name these distinct clocks; do not inadvertently create a severity accumulator per lane and call it the unchanged expert. Completed target order, first-maturity order and actual receipt order coincide only under the on-time reference schedule.

Changing a past raw rate can affect two h-step endpoint returns directly and many later normalized scenarios indirectly through the fading variance. A clean bounded implementation may reconstruct the whole available prefix. An incremental implementation must carry this dependency, not update only the two changed raw-return entries.

## 5. Quantized proposal invariant

Given a positive emitted E, nonnegative model budget B and exposure cap N, and lot size delta>0, let

`k = floor(min(N/delta, B/(delta E)))`, `z=delta*k`.

If these operations use exact rationals—including `Fraction.from_float(E)` for the stored binary64 E—then z is the largest nonnegative grid exposure with `z <= N` and `z E <= B`. Proof: the two inequalities are equivalent to `k <= N/delta` and `k <= B/(delta E)`; the largest feasible integer is the floor of their minimum. An independent check should verify feasibility and that k+1 violates at least one cap. If a separate maximum integer count is imposed for representation, include it in the minimum and next-lot statement.

This invariant concerns the declared **modeled** tail quantity, not the unknown true conditional ES or a realized loss bound. With E in log-percentage units, units of B must match exposure times that modeled loss quantity. A per-proposal cap is not a total portfolio/open-position cap. No orders or reservations should be inferred from a read-only proposal.

## 6. Causality and immutable outputs

Generated predictions/proposals must be deterministic functions of the bound contract and the committed data/feedback prefix. Equal accepted prefixes produce equal outputs; suffix changes cannot alter an already stored issue. Current-information corrections may legitimately affect **future** forecasts and current replay state, but should not rerun past generation as if the corrected observations were then available.

This is computational nonanticipation under declared timestamps and accepted records. It does not authenticate physical publication times, establish historical vintages, or prove that an externally supplied initial checkpoint was produced without lookahead. Synthetic and current-vintage historical demonstrations retain their corresponding provenance labels.

## 7. Numerical verification required

The inequalities above are exact-arithmetic statements. Binary64 projection and gradient calculations may show small constraint/bound residuals. The implementation should retain all issued/current weights, centered gradients, G, eta, selected revision identities, per-target scores and R contributions, and check:

1. finite Q/E/y/gradients/G and positive ordered emitted pairs;
2. simplex feasibility within a declared numerical tolerance;
3. update equality to an independently implemented simplex projection;
4. per-round convexity/projection inequalities against vertices and fixed selected comparators;
5. total regret <= reported bound plus a documented numerical tolerance;
6. R=0 within tolerance for an on-time uncorrected reference, and nonzero explicitly accounted residual after a controlled correction or delay;
7. exact rational proposal inequalities independently of floating-point scoring;
8. unchanged earlier issue records after corrections and restart.

A finite test grid does not prove every floating-point run satisfies the exact bound. No directed-rounding claim should accompany these numerical checks unless such a verifier is actually implemented and executed.

## 8. Analytic necessity witness for the mismatch term

The proposed two-expert example is valid in the **same FZ0 family**. Take fixed banks `Q=(1/2,1/4)`, `E=(1,1/2)`, outcome y=0, issued point `u_j=e_1` for every j, comparator `w*=e_2`, initial replay `v_1=(1/2,1/2)`, and c=1/10. Then `a=(1/2,1/2)`, `b=(1,2)` and the hinge is inactive everywhere on the simplex:

`f(w)=-log(w_1+2w_2)-1/2`.

At each issued point `g=(-1/2,-3/2)` and `h=(1/2,-1/2)`, so `||h||^2=1/2`. At n=200,

`sum[f(u_j)-f(w*)]=200 log(2) = approximately 138.629436 > 101`

while the incorrectly reused zero-mismatch bound is

`(c+c^(-1))*sqrt(G_n)=(1/10+10)*sqrt(100)=101`.

Thus the issued-loss bound **cannot omit the mismatch term** for arbitrary stale issued points. This is an artificial stale-evaluation history, not an assertion that the generated raw-price runtime produces constant e1 issues from a uniform initial replay. It is a valid counterexample to the broader incorrectly generalized theorem; it is not a market experiment.

For this example `h·(u_j-v_j)=v_(j,2)`, hence every term is nonnegative. The replay reaches e2 after its 18th update; an illustrative binary64 evaluation with the existing simplex projection gave `R_200=196.3545832106219` and corrected simplified bound `297.3545832106219`. These latter figures are numerical illustrations, not needed for the analytic contradiction. The analytic necessity is already established by `200 log(2)>101`.

## 9. Review of integrated theory and actual stream implementation

Subsequently read `tmp/gabriel_pipeline/theory.tex` in full and all 363 lines of the first `gabriel_runtime/stream.py`. The implemented recurrence conforms to the theorem: `_learner` evaluates gradients at frozen original weights/banks, centers them, accumulates their squared norm by origin modulo horizon, and projects the **current** replay state. Its two raw severity accumulators are pooled across the horizon stream, not accidentally made per-lane. Original fast quantiles determine severity responses. Corrections preserve issue records and first-maturity positions. The integrated proof handles zero centered gradients and limits the comparison to a fixed as-of bank/outcome sequence correctly.

The actual proposal uses N as a **maximum integer number of units**, and E in log-percentage points: `k=min(N,floor(100 B/(delta Ehat)))`. The integrated theory states this convention accurately, and `_proposal` uses `Fraction(es)` for the exact stored binary64 value. The percentage factor and N convention are internally consistent. Earlier notes above used N as an exposure cap for the generic derivation; the integrated version deliberately uses the implementation's integer cap instead.

### Clock boundary requiring explicit scope language

The new adapter's causal guarantee is relative to **owner ingestion**, not a guarantee that the target event occurs after the issue's owner timestamp. A delayed origin may have `event_at=310` but be ingested and issued at owner time 1000. The next target may have `event_at=311`, `received_at=1001`, and owner time 1001. Both records satisfy the implemented contract, though the target's event time precedes issue time 1000. The target value was unavailable to the owner, so prefix nonanticipation remains true. Calling every such case strictly future-event forecasting would be too strong.

Recommended text: the profile predicts future **observation indexes** under receipt availability; with delayed acquisition, a target can already have occurred but remain unreceived at issue. No positive event-time lead is guaranteed. Alternatively a future-event-only variant needs its own explicit target-timing gate and treatment of already-issued predictions whose arriving target time violates that condition. No code change is necessary if the intended claim is the former, receipt-causal interpretation.

Because new indexes are contiguous and ingested in order, absolute receipt delays by themselves do not reorder target feedback relative to later same-lane issuance. Without corrections, u=v still holds on this profile's ordinary admissible sequence. General arbitrary delayed-feedback or out-of-order new-index buffering is not implemented. The integrated theory correctly centers its operational mismatch discussion on corrections and explicitly excludes arbitrary out-of-order buffering; experiments and final descriptions should preserve that scope.

No further consequential proof/implementation mismatch was found in this inspection. This is a source review, not a new execution of the stream verification suite.
