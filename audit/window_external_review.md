# Independent read-only review of window certificates and owner integration

The review found no blocking mathematical or input-boundary defect in the two
source versions below. This is an independent source review with bounded
development probes, not formal verification or a complete security assessment.
No implementation source or earlier persistence evidence was changed by the
reviewer. The source hashes were rechecked when this note was written.

| Reviewed source | SHA-256 |
| --- | --- |
| `gabriel_runtime/window_certificate.py` | `b344b7282c8c28262236e680d68fe58bfda67ecc45073c3b8d38f0b11214925c` |
| `gabriel_runtime/graph_reachability.py` | `f26e368d59c8b50aeb0026322adf7d7ea54d6a25795cc4c19dcf38f73c97edf3` |

## Mathematical boundary

The represented matrix is validated as an equal-diagonal, uniform nonnegative
edge-weight clique, with at most 64 vertices. Finite binary64 source components
are decoded directly as exact dyadic rationals; normalization divides regional
quadratic expressions by the exact raw squared norm. This avoids binary64
overflow or underflow during source normalization and deliberately defines a
different model from the older observer's rounded source preparation.

For common diagonal `degree` and weight `w`, the two invariant subspaces have
eigenvalues `degree-(n-1)w` and `degree+w`. Their relative frequency is `n*w`;
the common diagonal offset contributes a global phase and does not change
regional mass. The reviewed sine coefficient has the correct sign for
`exp(-i*t*L)`. Stationary, empty-region, full-region, zero-frequency and exact
threshold-equality branches are consistent with the strict proposition
`exists t in [start,end]: mass(t) > threshold`.

Phase exclusion uses the outward possible integer range
`ceil(start_quotient.lower)` through `floor(end_quotient.upper)`. An empty range
therefore excludes all interior maxima. A certified critical index is selected
from the inward range `ceil(start_quotient.upper)` through
`floor(end_quotient.lower)`, and its outward time enclosure must lie entirely
inside the query window. No floating-point candidate search supplies coverage.
The rational peak margin follows from the positive difference between the
squared amplitude and the squared threshold gap; the dyadic replacement margin
is smaller and retains a strict witness inequality. Precision overlap leads to
`unknown`, not a tolerance-based decision.

The important evidence limit is that `critical_point.mass` bounds the exact
stationary witness within `time_enclosure`, not the mass at every time in that
enclosure. An independent serialized verifier must reconstruct the phase/index
relation and the algebraic peak inequality. Rational endpoint strings alone do
not prove their transcendental enclosures; those require the declared Arb
trust base or another validated arithmetic implementation. Public model-oracle
helpers also assume a model obtained from `prepare_model`, rather than an
arbitrarily constructed `HarmonicModel`.

Bounded development calls covered exact zero-time equality, negative windows,
a negative window near magnitude `1e300`, and a threshold `1-2^-8191`. The latter
two returned critical-point witnesses with strict exact margins. These were
inspection probes, not an independently archived certificate suite; the root's
serialized verifier is separate.

## Typing, caps and native boundary

No Boolean/integer coercion bypass, duplicate-entity acceptance, missing-source
coverage, threshold/window ordering bypass, or accumulated node/batch/window
cap bypass was found through the Store adapter. Payload validation precedes
native execution. Store transactions retain atomic rollback on native or
certificate failures, and identical command retries reuse the stored receipt.
The new schema and adapter names separate these certificates from the old point
observer; the package initializer does not import the new Flint dependency.

The native response checks exact entity-to-sensor identifiers, graph-byte
digest reconstruction, symmetry, bounded dimensions, and history counts.
However, degree construction remains trusted to the selected exporter rather
than recomputed from adjacency, and `engine.edges` is only type/range checked.
These limitations do not change the mathematical proposition about the exact
represented matrix that was actually supplied to the certifier.

The precision, input and output-integer limits bound the declared numerical
work; they are not an operating-system resource sandbox. In particular, native
stdout/stderr use temporary files, and the 4 MiB output check occurs after the
process exits. Those files can grow until the process ends or reaches its
30-second timeout. A resource-cap or arithmetic exception can reject a command;
the four certificate statuses do not promise to replace every invalid-input or
execution exception.

## Concurrency and identity limits

The module's reentrant lock serializes its own Arb context sections. Flint's
precision context is nevertheless visible across Python threads. In the
event-coordinated development probe, the main thread was inside
`ctx.workprec(512)` while a second thread held `ctx.workprec(32)`; the main
thread observed precision 32. The original command-tool stdout is retained in
`window_flint_context_probe_observed.txt`, with its provenance limitation, and
`window_flint_context_probe.py` provides a bounded reproducer. The saved
reproducer was not rerun during the manuscript/timing freeze.

Unrelated Flint callers that do not take this module's lock can therefore
change the effective precision and replay determinism. That observation does
not establish a false Arb bound or false certificate. Claims of resource
precision and deterministic replay require a controlled process-wide context,
or process isolation, rather than arbitrary concurrent Flint use.

Source and arithmetic identities hash on-disk files. They do not establish
that already-imported Python code equals a file modified between import and
adapter construction. Fresh interpreters and immutable source files during a
run remain assumptions. The arithmetic fingerprint covers the installed
package and bundled shared libraries, not every possible system-linked
dependency or the interpreter executable; `sys.version` is not a binary hash.
The identities are integrity references, not authentication or a sandbox.

Finally, a before/after comparison of the v1 source closure proves no edits
during that check. Historical v1 preservation requires comparison with the
saved original closure. The separate names and imports are structurally
consistent with that preservation, but do not replace the historical hash
comparison.
