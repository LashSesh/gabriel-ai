# Review of the owner and bounded native execution additions

Reviewed the current `main.tex` sections `sec:fastowner`, `sec:packedgraph`, `sec:fastownerprotocol`, `sec:fastownerresults`, `sec:nativepseresults`, the new abstract/discussion/conclusion statements, the native implementation and the retained native benchmark summaries. Review used source and existing output reads and independent arithmetic aggregation of saved timing samples; no test or timed workload was rerun. The final owner timing table and prose were subsequently reviewed against `results/fast_owner_benchmark.json` and its human-readable summary, as recorded below.

## Mathematical and claim assessment

The typed-copy proposition is now correctly restricted to values, exact types, list and dictionary order and mutable-container isolation. Scalar identity, interning, allocation effects, unstable inputs and abnormal resource/storage execution are explicitly excluded from the owner proposition. The induction matches `FastStore`: the reused pre-state text is validated first, the post-state text is computed locally, and the inherited audit reconstructs the same records. Original adapter algorithms, synchronization and transaction boundaries remain unchanged. No outstanding mathematical objection to this scoped proposition was found.

The packed-orbit proof correctly handles inverse permutation conventions and explains why upper-triangle row-major bits must be ordered with the earliest entry most significant. Full S7 enumeration preserves the padded matrix orbit, stabilizer and canonical convention. Original graph spectra and fixed subgraph fields use the unchanged functions on the original embedding. The code's embedding is a 13-by-13 zero-padded matrix with a seven-slot group action; the manuscript's fixed-padded-matrix description is accurate, although specifying 13-by-13 would make the convention completely explicit. The inherited cross-size hash collision is correctly retained as a limitation.

The native refinement is separated from complete-engine equivalence. Existing multiscale elapsed-time branches mean an execution speed change can influence arbitrary whole-engine schedules. The manuscript explicitly states this and limits executed comparisons to their defined observable projections. It does not infer hidden memory equality or deterministic whole-engine behavior from equal signatures. This is the correct boundary.

## Native result checks

The table's three eligible paired median speed ratios and ranges match the supplied `summary.json`: 3094.5549259 [2710.8549538, 3445.3213423], 1222.6821561 [1031.6825875, 1285.0103203], and 513.3702291 [500.3866398, 536.5887578]. The ineligible eight-source comparison is 1.02172796 [0.93278964, 1.02462333]. Allocation columns match the archived measurements. The manuscript distinguishes these throughput ratios from the medians of per-run median tick latencies and does not combine them with Python timing factors.

The existing harness's paired median throughput ratio range 0.988--1.063 agrees with the eight archived control groups. Three outer pairs of five fresh-state inner repetitions are reported descriptively, without confidence intervals or production-tail claims. Eight sources do not enter the optimization and give the relevant branch control. Relaxed synthetic commit thresholds, fixed inputs, missing Linux CPU/RSS counters and unmatched historical environments are clearly stated.

The 1099 exhaustive labelled graphs, 48 seeded larger graphs, nine complete-signature comparisons, 433 versus 438 filtered workspace passes and ignored doctest counts match the retained metadata. The historical discrepancy remains 23 of 78 state hashes and one crystal hash, with unfiltered failure and unresolved cause explicitly reported. The current 32 projected snapshots include complete returned crystals but not all hidden engine fields; the text correctly says so. No missing broad superiority qualification was found in abstract or conclusion.

## Initial corrections, subsequently resolved

1. In the architectural discussion, replace `source and allocation identity remain outside the adapter data contract` with `Python object identity and allocation behavior remain outside the adapter data contract`. Source identity is bound by the registry fingerprint; the present phrase could incorrectly suggest that those source checks were dropped.
2. `native_pse/GABRIEL_REVIEW.md` still says **all** files under `benchmark-results/` are inherited and that new measurements reside only in enclosing results/audit. New files now exist under `benchmark-results/gabriel/`. Describe that subdirectory explicitly as new measurements and reserve the inherited statement for the original files.
3. Optional editorial clarity: specify the legacy 13-by-13 zero padding in `sec:packedgraph`, and simplify its first sentence's repeated conjunctions. This is not a correctness blocker.

The two executed inherited-code counterexamples are confirmed by the build agent's retained diagnostics: complete-32 partial Lanczos reports zero instead of the analytical symmetrized gap 16, and the bounded clustering request produces four clusters under maximum two. These are appropriately confined to inherited limitations; they neither invalidate nor validate the independent packed-signature proof.

All three initial wording/clarity recommendations above were applied and inspected in the final source. The discussion now distinguishes Python object identity from source fingerprints, the native README identifies the new measurement directory, and the packed-graph description specifies 13-by-13 padding. No additional scientific branch or broad optional test expansion is indicated.


## Final owner timing review

The final `sec:fastownerresults` table and prose agree with the archived samples. Independent aggregation recomputed 33 register, transition, view and reopening group medians directly from raw paired durations and confirmed their stored summaries. The six table rows near 800 observations match the raw separate medians and paired reference/fast ratios to the displayed precision. The text correctly distinguishes a median of paired ratios from a ratio of separate medians.

- Integer-register trial averages are 0.322327 versus 0.244875 ms (32 registers), 0.688338 versus 0.432032 ms (256), and 3.460666 versus 1.793600 ms (2048). Their paired medians are 1.342773, 1.604767 and 1.915071. Each is a median of seven per-trial averages of 100 individually committed submissions, with command construction and checking excluded. The manuscript describes exactly that scope.
- The 18 stream transition groups have median paired ratios from 1.337285413 to 1.499349182. Across their 126 paired observations, extrema are 1.117045662 and 1.991422079. One of 42 view pairs has a ratio below one; the minimum is 0.873328561. The exception is explicitly retained rather than suppressed.
- The unprofiled path's cumulative sums are 80.206748769 versus 56.392624736 seconds for horizon one and 79.207102559 versus 55.700001948 seconds for horizon five. Direct arithmetic gives reductions 29.690923019% and 29.678021101%. The manuscript correctly says these are 863 selected durable submit calls (821 source appends plus 42 corrections), not elapsed time for all surrounding verification, views, audits or opens.
- Reopening values at 800 observations round to 68.812 versus 56.808 seconds and 65.695 versus 56.082 seconds. Each is one pair with a fresh adapter and warm filesystem, as stated. The five-pair design applies only to 360 observations.
- Summing raw verification counters gives 4133 receipt comparisons, 160 state/meta checks, 7543 journal-row comparisons and five API exports. These can include repeated reads of earlier journal rows; they are correctly reported as comparisons rather than distinct independent records. The separately labelled warmup is excluded.
- Profile call counts in the summary and retained output are treated as diagnostic counts, not total validation work or instruction counts. New structural-copy recursion is not incorrectly hidden inside a claim that all validation calls disappeared.

The paper retains single-environment, correlated-trial and unchanged-numerical-adapter qualifications. No owner ratio is multiplied by a native ratio or by the preceding incremental-adapter ratio. The recorded improvement is execution cost, not predictive accuracy or a production throughput guarantee. Abstract and conclusion remain consistent with that scope. The new figure caption describes separate medians and observed ranges; visual rendering is left to the root's publication QA.

Final status: no remaining correction identified in the reviewed scientific text or numerical table. The earlier provenance and identity wording corrections are resolved. Publication rendering, compilation and package checks remain the root's separate validation steps; this review does not claim those steps were performed here.
