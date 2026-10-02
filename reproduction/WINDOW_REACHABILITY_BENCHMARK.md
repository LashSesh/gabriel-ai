# Frozen continuous-time verification study

This study evaluates a concrete computational task: certify whether the exact
represented Engine clique model exceeds a threshold anywhere in a closed time
window. It does not treat model intensities as calibrated external-event
probabilities or establish external predictive superiority.

The protocol is `results/window_reachability_protocol.json`, SHA256
`aa4d41d74c11e7d80654d3df1cbdc1eabbfa249e047e2adae8d384c547a763c2`.
It was frozen before generating inputs or running any measurements. The runner
enforces this hash. The separate freeze receipt records that ordering.

The primary cohort has 256 cases from actual one-batch Engine snapshots at
7, 13, 32 and 64 entities, two predetermined source seeds, two regions, four
threshold offsets and four time-window cohorts. Source values are deterministic
integers. Thresholds and windows are normalized to harmonic amplitude and
frequency to supply useful verification coverage; this is an explicitly
synthetic cohort, not a sampled external population. All Cartesian-product
cases are retained. Twenty-four stationary controls and four labeled stress
cases are excluded from primary selection and reported separately.

The mathematical contract uses the exact dyadics represented by source and
matrix input bits, exact real source normalization, and a strict exceedance
predicate. It is a separate model profile from the prior point observer's
rounded binary64 preparation. Exact rational thresholds are used for equality
controls. Generic nonclique matrices are outside this study's certificate scope.

## Matched methods

The analytic method uses Arb phase enclosures and possible extrema. Both
subdivision baselines use the same exact coefficients and Arb point oracle,
without solving for extrema. The uniform baseline has 256 endpoint-inclusive
nodes and stops on its first certified witness. The adaptive baseline samples
the midpoint of the unresolved interval with the highest certified upper bound.
Both use exact stationary/global-amplitude shortcuts and valid endpoint
Lipschitz and second-derivative interpolation bounds. Every attempted point
evaluation, including a precision retry, consumes the shared 256-call cap.
The precision schedule is 128, 256 and 512 bits. The generic bounds use
`K1=abs(omega)*Rup` and `K2=omega**2*Rup`, where `Rup` is a certified upward
dyadic bound on `sqrt(b*b+c*c)`.

For a cell of width `h`, with endpoint upper enclosures `u,v`, each reported
upper bound is the minimum of individually valid bounds:

```
u + K1*h
v + K1*h
(u + v + K1*h)/2
max(u,v) + K2*h*h/8
a + Rup
1
```

An exclusion by subdivision contains a complete gap-free interval cover, with
every upper bound at or below the threshold. A reachability result contains a
rational witness time and a point lower bound strictly above the threshold.
Stationary and global-amplitude exclusions carry exact algebraic evidence.
An unresolved budget-limited result is `unknown`, never `excluded`.

The primary acceptance criterion requires zero false certificates under
independent verification, at least 95% analytic resolution, resolution no lower
than either validated baseline, and lower matched complete-certificate-call
cost than the adaptive baseline. The timing test is frozen precisely in the
protocol: median worker ratio above one, with at least four of five worker
medians above one. A ten percentage-point resolution gain over uniform
subdivision is a secondary aspiration. Failed criteria are retained and reported.

## Reproduction

Use the newly built `engine_snapshot` executable and its explicit SHA256. The
runner requires the pinned project Python dependencies, including python-flint.
Use new output directories for generation and collection.

```sh
python reproduction/benchmark_window_reachability.py generate \
  --executable /absolute/path/to/engine_snapshot --sha256 EXPECTED_SHA256 \
  --output /absolute/path/to/new-window-inputs
python reproduction/benchmark_window_reachability.py evaluate \
  --inputs /absolute/path/to/new-window-inputs/inputs.json \
  --output /absolute/path/to/window-evaluation.json --run
python reproduction/benchmark_window_reachability.py collect \
  --inputs /absolute/path/to/new-window-inputs/inputs.json \
  --output /absolute/path/to/new-window-timings --run
python reproduction/benchmark_window_reachability.py report \
  --evaluation /absolute/path/to/window-evaluation.json \
  --timings /absolute/path/to/new-window-timings \
  --output /absolute/path/to/window-summary.json
```

Timing uses five fresh Python workers and three method-order rotations per
worker. Every timed call includes exact model preparation and all Arb work;
point-call counts alone do not establish a work advantage. Timings exclude
Engine snapshot generation, process startup, output serialization and durable
SQLite owner costs. They must not be described as full-owner or overall-system
speedups. Full certificate outputs are captured once; every timed result must
match the captured result digest. The reporting command deliberately leaves
the overall outcome unassessed until an independent certificate verifier has
been incorporated.
