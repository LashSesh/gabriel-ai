# Independent review: conditioned continuous-time walk

Status: source, test-design, mathematical-method, benchmark-design, and executed-record review complete. The reviewer made no production-source changes and ran no builds or timings; the additional calculations below inspect retained outputs.

## Reviewed boundary

`native_pse/crates/pse-topology/src/conditioned_walk.rs` provides a separately invoked, prepared-state API for the full complex vector `exp(-i t L) psi`. Its intended output differs from the existing all-pairs CTQW statistics. Exporting this module does not in itself accelerate existing PSE consumers or establish any decision-quality improvement.

## Mathematical and input contract

The constructor rejects empty graphs, dimension errors, self-loops, duplicate directed entries, nonfinite or negative weights/degrees, asymmetric entries, and degrees that differ from the declared neighbour-index summation order. Every generic spectral plan retains all n eigenpairs. No truncated basis is described as complete state evolution. Prepared states borrow their immutable plan, preventing a state prepared for one plan from being queried through another plan.

For the special case, every off-diagonal entry must be exactly equal, and every diagonal entry must equal the same stored d. Recognition additionally requires d to equal the rounded product `(n-1)*w`. This stricter condition can reject a mathematically uniform weighted clique when repeated floating-point summation differs from multiplication; it sends that valid graph to the full spectral backend instead of approximating the graph.

The stored matrix is `L=(d+w)I-w 11^T`. Its uniform and orthogonal subspaces therefore have eigenvalues `d-(n-1)w` and `d+w`. The implementation retains the small uniform-space eigenvalue using fused multiply-add instead of silently assigning it zero. This matters because the stored floating-point diagonal need not produce an exactly zero real row sum. The projection formula and the sign `exp(-itL)` are correct for this represented matrix, up to floating-point evaluation.

The API returns the original state at zero time and for the zero matrix. It does not normalize either input or output. It rejects nonfinite times and nonfinite intermediate/output values. Rejection of intermediate overflow is documented even when symbolic cancellation could yield a finite result.

## Accuracy scope

Exact recognition is a graph-membership condition; it is not a floating-point error certificate. In particular, the rounded nonconstant eigenvalue, multiplication by very large time, oscillatory argument reduction, cancellation, subnormal amplitudes, and spectral-solver conditioning remain numerical limitations. Finite output alone does not bound the evolution error. The generic backend checks solver completion and finite eigenpairs, not a certified orthogonality or eigenpair-residual bound. Consequently results must be reported with their tested matrix, time, state, and tolerance ranges. Bitwise equivalence to the generic eigensolver is neither expected nor necessary for this separate API.

## Benchmark protocol review

The declared protocol compares Auto and forced Spectral on the same graph, prepared initial complex state, and full returned vector. Plan construction, state preparation, and repeated queries are separated. Timed queries include allocation, validation inside the API, the returned vector, checksum consumption, and destruction; correctness checks, warmup, setup, and serialization are excluded. Alternated paired order and process-level ratios make the interpretation explicit.

The predeclared 16-time cycle includes one zero-time query. Thus one sixteenth of timed queries exercise the identity shortcut in both variants. The protocol's fresh-process observed ranges are descriptive ranges, not confidence intervals. Synthetic clique advantages apply to the new query operation and its restricted graph class. They cannot be described as overall Gabriel speedups.

The executable benchmark source matches these boundaries. It validates all distinct complex outputs componentwise before timing, checks output norms, compares timed checksums, keeps the original normalized deterministic input fixed, and passes the entire returned slice through `black_box` before consuming a varying component. Both methods include output-vector destruction in each timed loop. Neither graph construction nor spectral preparation is silently charged to only one query variant. The reported warmed setup intervals time construction but not final destruction; these are setup measurements, not an end-to-end workload metric.

## Tests and derivation reviewed

The test source includes a matrix-power Taylor reference for non-clique graphs, which is independent of the eigensolver and clique projector formula. Its small matrices and time range keep the fixed 100-term truncation far below the asserted floating-point tolerance. Further cases cover complex unnormalized inputs, degenerate/disconnected spectra, inverse evolution, the exponent sign, zero graphs/states, signed-zero preservation at zero time, exact near-clique rejection, nonbinary degree/product fallback, input ordering, and malformed or overflowing inputs.

A deliberately long-time uniform-source test exposes the small represented-matrix uniform-space phase rather than losing it behind a small absolute tolerance. It verifies that particular mode and does not certify arbitrary long-time vector evolution. The tests' norm checks apply to their ordinary-scale states; the API avoids silently computing or normalizing an overflowing state norm.

The manuscript method draft's two-projector proposition and proof are correct. Its bound `|t*delta| ||P psi||` for dropping the uniform-space phase follows from `|exp(-i t delta)-1| <= |t delta|`. The draft expressly excludes machine-certified error enclosures, arbitrary long-time accuracy, and bitwise agreement with a generic eigensolver. These qualifications match the implementation.

## Executed records and independent checks

The reviewer verified the six stdout/stderr SHA-256 values for the three retained native validation commands and independently recomputed their test totals from stdout. The workspace run has 481 passed tests, no failures, one ignored doc test, and one explicitly filtered historical fixture. All 15 conditioned-walk tests are present and pass. The first attempt to target the historical fixture selected zero tests; the corrected root-package command selected one test, failed with exit code 101, and filtered two unrelated tests. The zero-test attempt is retained and is not evidence that the fixture passed. This phase therefore does not have an unqualified passing historical fixture gate.

For the benchmark, the reviewer independently verified all 11 individual command records, 22 raw stream hashes and byte counts, 76 measured/current source hashes, the executable hash, and seven distinct process IDs. All three measurement phases' median, minimum, and maximum process ratios were independently recomputed from the seven original process outputs and agree exactly with the retained summary. The six specialized clique workloads have query median ratios from 3.4207 to 63.8788; the five generic-backend controls have ratios from 1.0064 to 1.0297. These are the stated synthetic prepared-query measurements, not application gains.

The reviewer separately reconstructed the initial states and two-projector evolution for all 96 first-process specialized-clique frames and compared both saved backend vectors. Maximum complex-component error was approximately `1.1604e-12`. The root report also supplies an independently implemented SciPy matrix-exponential comparison over all 176 first-process frames, including generic controls; its retained maximum error is approximately `2.4103e-12`. That separate numerical report and its reconstruction/checksum logic were inspected, but the reviewer did not rerun its SciPy calculation. Neither comparison is a rigorous roundoff enclosure.

### Aggregate-index anomaly

The observed `executed/commands.json` contains ten records. It is exactly the prefix of the eleven original individual command records and omits only `process_6`. The existing `integrity.json` reports eleven captures. All eleven individual records and all twenty-two matching streams actually exist, and their hashes and successful return statuses verify independently. The aggregate's SHA-256 is `44c483aafa216ad473001ae613fb37c6722b3eebdfa63ff52cbe5cdd5df2dc8f`.

This is an unresolved metadata discrepancy; its cause has not been established. The observed aggregate must remain unchanged. The explicitly labelled `results/native_conditioned_commands_derived.json` is acceptable as a separate complete index because every record is copied from, linked to, and hash-bound to an existing original individual record. The reviewer verified all eleven such associations. It introduces no inferred commands, timings, or outputs. Numerical measurements need not be discarded solely because this aggregate index is stale, but it would be incorrect to claim that the original aggregate is complete or that every metadata consistency check passed without qualification.

## Conclusion

No blocking defect was found for the separately invoked, numerically qualified API and the reported synthetic comparison. The existing historical fixture failure and the aggregate-index discrepancy must stay visible in the audit record. The earlier QSO repository's 31 tests do not validate this new Gabriel module; validation rests on the new implementation tests and the preserved outputs described above.
