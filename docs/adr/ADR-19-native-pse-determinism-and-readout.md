# ADR-19: Native PSE determinism and the specified state readout

**Status:** accepted. **Affects:** `native_pse/crates/pse-fmath` (new), every engine crate that
evaluates a transcendental function, `native_pse/crates/pse-types` (`Observation.amplitude_hint`),
`native_pse/crates/pse-core` (`GlobalState.last_metrics`), `native_pse/examples/engine_readout.rs`,
`golden_trace.rs`, `golden_fixture.rs`, `native_pse/tests/differential.rs` and
`tests/fixtures/pure_libm.json`, `adapters/native_graph.py`, `domains/numerical/pack.py`,
`evaluation/fixtures/graph_readout.py`, `evaluation/corpus_domains.py`,
`scripts/pse_build_identity.py`, `scripts/pse_measure.py`.

## Context
ADR-18 made the engine a contained analytical worker for three readouts whose semantics were
already specified (walk masses, snapshot identities, exact window certificates). Everything
else the engine computes on its continuous state stayed quarantined: the eight gate metrics,
the crystal commit path, consensus, falsification and morphogenic graph mutation. The
inherited review gave two reasons that are independent of any single feature: the full engine
state was not known to be deterministic across platforms (23 of 78 digests of the
Windows-generated golden fixture differ on Linux, cause unresolved), and the features carried
names rather than propositions an independent reference could check. The decision of this
ADR is to remove both obstacles for the state itself, before any feature on top of it: first
determinism, then specification. What cannot be specified stays quarantined, with its reason.

## Decision 1: platform-independent arithmetic
- **The mismatch is explained.** A trace with a digest per state component per tick
  (`examples/golden_trace.rs`) reproduces the historical mismatch exactly (23 of 78 digests,
  one crystal digest; first differing tick 7 in every affected case; transient in gate-only
  runs, persistent through the adaptive calibrator's rolling history and through the archive
  where a crystal commits). Building the same engine against the host's glibc and against the
  pure-Rust `libm` crate gives 32 of 78 differing digests, the first of them in the data helix
  alone with every gate value identical; where gate values differ at all, `q`, `k` and `g`
  differ by one unit in the last place. Moving `sin` by one unit in the last place changes 73
  of 78 digests and six crystal digests. The whole-state digest is maximally sensitive to the
  last bit of transcendental functions, which C libraries round differently; the fixture does
  not record component values, so the specific Windows results cannot be reproduced here, but
  platform arithmetic is a sufficient explanation and nothing else in the audit (BTreeMap
  state, insertion-ordered graph indices, rayon only in index-ordered table builds, `mul_add`
  as the only fused operation) could produce it.
- **Every transcendental call goes through `pse-fmath`.** The trait `Fmath` (`dsin`, `dcos`,
  `dsin_cos`, `dexp`, `dln`, `dlog2`, `datan2`, `dtan`, `dtanh`, `dpowf`) delegates to the
  pure-Rust `libm` crate by default, so results depend on the locked crates and the Rust
  toolchain only; the `platform-libm` feature routes the same calls to the host C library and
  reproduces the glibc trace byte for byte (the swap is faithful); the `study-perturb-sin`
  feature exists for the sensitivity study only. Basic IEEE-754 operations are not wrapped.
- **A platform-independent golden fixture.** `tests/fixtures/pure_libm.json` records the
  same cases under the default build; its 16 seeded graph histories are identical to the
  Windows fixture's (they involve no transcendental function). The Windows fixture is retained
  unchanged behind an ignored test with its explanation, runnable on request. The whole Rust
  workspace passes under the new arithmetic. The observer's masses stay bit-identical to the
  retained functional journals on the automatic backends and move by at most one unit in the
  last place on `spectral_full`; snapshot identities and decisions are unchanged.
- **Not established:** identity of the pure-Rust results on a Windows or macOS host. The
  property holds by construction and has been executed on one platform; the build identity
  (`scripts/pse_build_identity.py`) now records the arithmetic profile and the locked `libm`.

## Decision 2: specification instead of names
- **Two additive engine changes.** `Observation.amplitude_hint` lets a declared stream carry a
  declared data-helix amplitude instead of the byte entropy of its JSON encoding (`None` keeps
  the inherited behaviour, so no fixture changes); `GlobalState.last_metrics` makes the metric
  set of every step readable regardless of the early returns of the commit path (never read by
  the engine itself). The golden fixture is unchanged by both.
- **A declared observation stream.** Per observation an entity, a phase in [0, 2pi) and an
  amplitude in [0, 1], as binary64 bits; a profile with the number of carriers, the adaptive
  carrier flag, `lambda`, `mu_r`, `eta_r`, `dt2`, the ten normalization coefficients and the
  eight thresholds. Caps: 64 entities, 128 batches, 64 carriers.
- **The readout profile.** The bridge `engine_readout` runs the engine with persistence decay
  and crystal commits disabled, so the graph stays the pure co-observation graph, on a
  **half-turn carrier grid** (phases `pi i / n`): the phase lock `(1 + cos 2(phi_data -
  phi_carrier)) / 2` is pi-periodic in the carrier phase and every carrier already contains its
  antiphase partner, so the inherited full-turn grid holds each carrier twice and leaves the
  adaptive selection between the duplicates to last-bit rounding. Per step the bridge reports
  the vertices in first-observation order, the edge count, the data helix, the active carrier
  with its mandorla, the eight metrics, the gate verdict and the per-vertex embedding, and an
  identity over the complete readout (batches, profile and every step).
- **The specification in words, and its reference.** `evaluation/fixtures/graph_readout.py`
  states every quantity as a function of the stream and the profile (co-observation edges from
  the smaller to the larger vertex identifier, activation counting, the five embedding
  coordinates, the circular-mean helix, carrier coherence and the real mandorla, the
  deformation metric with mean, p90 and churn, `q = kappa / kappa_c`, `j` from edges per
  vertex, the gate rule) and implements it in the standard library. The engine's readout equals
  the reference within 1e-12 on the fixture and on random streams with one to sixty-four
  carriers, adaptive and fixed (observed maximum deviation 9e-16). Carrier choices that are
  within 1e-12 of the maximal coherence are declared equivalent; the reference accepts an
  engine's choice among them and continues with it.
- **A finding of the specification.** Under this profile `r` and `p` are exactly 1 (the
  intrinsic state stays at the origin without commits), `n` is the constant
  `exp(-lambda_seam * pi)` (up to rounding) and `k` equals `lambda_c * q` with the default
  `lambda_e = 0`. Of the eight inherited gate quantities three vary: deformation `d`, coherence
  `q` and edge density `j`. The gate is a conjunction of three thresholds, not eight. This is
  stated rather than hidden behind the names.
- **Detections are schedule-admitted gate crossings.** `graph.detections` takes the same stream
  with a `{min_tick, cooldown}` schedule and returns the steps whose gate passes, whose tick is
  at least `min_tick` and which lie more than `cooldown` ticks after the previous detection;
  an empty list is a computed result. Each detection's identity is the digest of its complete
  content (readout identity, tick, vertices, metric bits, thresholds, schedule), which is what
  the inherited crystal identifier did not provide. The schedule is applied by the adapter and
  by the reference from the same per-step verdicts; the engine's own commit path is not used.
- **Validation independent of the engine.** The adapter re-checks the arithmetic profile (a
  `platform-libm` build is refused), zero commits and no fault, the history counts, the vertex
  order, the co-observation edge counts, the domains of helix, carrier, metrics and embedding,
  the gate rule against the declared thresholds and the readout identity; any deviation is
  `invalid_input`, never a success. Declared inputs outside their domains (a phase of 2pi, an
  amplitude above 1, zero carriers, a schedule beyond the batch cap, parameters) are refused
  before execution; a mismatched kind is `out_of_scope`.
- **What stays quarantined, and why.** The crystal commit path (Kairos gate followed by
  constraint extraction, pattern memory, seam check, dual consensus, optional falsification,
  topology signature, multi-scale tick, metatron signature, archive, morphogenic mutation,
  intrinsic step): its consensus scores are carrier-phase-shift heuristics with no proposition
  about the history; the proof-of-resonance state machine is never advanced; the Betti formula
  is wrong for filled simplices; morphogenic identifiers can collide and the mutation rewrites
  the observation graph in place; the crystal identifier does not cover its metadata. None of
  this is needed for the readout, and switching it on would reintroduce names without
  propositions. Whether a specified version of any of it is worth having is a question for a
  frozen protocol with held-out evidence, not for this ADR.

## Measurements (`evidence/pse/measurements.json`; medians of 7; shared cloud container, magnitudes only)

| Quantity | trusted_local | linux_namespace |
|----------|---------------|-----------------|
| Native readout process, fixture stream (4 entities, 4 steps) | 2.0 ms | |
| Native readout and detections at the caps (64 entities, 128 steps, 64 carriers; 671 KB wire) | 128 ms | |
| Identity validation (three executables, about 3.9 MiB, before and after) | 2.3 to 3.4 ms | |
| Stage one: the fresh worker process in the backend (readout, detections) | 93 ms, 91 ms | 239 ms, 239 ms |
| Job elapsed on the owner clock (readout, detections) | 104 ms, 100 ms | 250 ms, 249 ms |
| Total task latency through the owner (readout, detections) | 0.77 s, 0.77 s | 0.89 s, 0.88 s |
| The same task again: hit on the complete job key | 0.58 to 0.59 s | 0.62 s |

The other operations of ADR-18 measure as before (native process 1.6 to 7.5 ms, certificate
process 87 ms). At the caps the readout's per-step graph work (embedding and clustering over
up to 64 vertices for 128 steps) dominates the native time; process starts and the owner
pipeline still dominate the task latency.

## Consequences
- The numerical pack has eight operations; the snapshot schema knows the kinds
  `observation_stream` and `detection_query`; the graph corpus tier has ten tasks in five
  families with executed controls; frozen protocol digests are unchanged.
- The native worker binds three executables (`engine_observer`, `engine_snapshot`,
  `engine_readout`); jobs bound before this ADR carry the previous worker build and are refused
  at execution, as every build change is.
- No learning, memory, crystal, resonance, reasoning or advantage claim follows from this ADR.
  The readout is a deterministic, specified, independently referenced function of a declared
  stream. A later use of it as a feature channel of the system's own observation history
  would be evaluated under the promotion rule (ADR-15) and a frozen protocol, like every other
  policy input.
