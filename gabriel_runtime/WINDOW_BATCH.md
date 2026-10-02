# Prepared continuous-time window certificates

`window_batch.py` adds immutable exact-model preparation to the existing
`window_certificate.py` implementation. It changes the cost of answering several
queries for one represented graph, raw source and target region. It does not
expand the supported graph class or alter any certificate's mathematical claim.

## Contract

```python
from gabriel_runtime.window_batch import (
    prepare_window_model, certify_prepared, certify_windows,
)

prepared = prepare_window_model(snapshot, source, targets)
certificate = certify_prepared(prepared, start_bits, end_bits, threshold_bits)
certificates = certify_windows(
    snapshot, source, targets,
    [{"start_bits": start_bits, "end_bits": end_bits}],
    threshold_bits,
)
```

`prepare_window_model` derives the same exact rational harmonic model once.
Its local return object retains an immutable `HarmonicModel`, the original
SHA-256 input binding, and an immutable serialized model payload. It holds no
caller-owned list or dictionary. Each certificate and `model_payload()` result
contains newly allocated mutable JSON structures; modifying one cannot alter
another or the prepared state through the public API.

The input binding covers ordered entity identities, all represented Laplacian
bits, canonical entity-ordered source records, and canonical entity-ordered
region membership. Optional snapshot metadata remains outside the mathematical
binding, as in the original implementation. Reordering source records or targets
without changing those mathematical inputs preserves the binding. Distinct bit
patterns, including signed zero, retain their original binding semantics.

`certify_prepared` performs the original exact query and precision-ladder
validation before applying the original decision procedure. It returns exactly
the same per-query v1 certificate, including evidence, serialization order,
precision attempts and numerical-work counters. Those counters describe the
query's point and phase evaluations; they have never counted graph preparation.
No certificate is reused from another window. Repeated queries remain separate
outputs with separate numerical work.

`certify_prepared_many` accepts 1–256 dictionaries containing exactly
`start_bits`, `end_bits` and `threshold_bits`. `certify_windows` accepts 1–256
ordered `start_bits`/`end_bits` windows with a shared threshold. Neither writes
external state. An invalid query raises an exception and returns no partial
batch. The Engine owner adapter retains its separate, lower limit of 32 windows.

A valid non-clique graph can be prepared as `out_of_scope`; every valid window
then receives the original per-window out-of-scope certificate. Malformed graph
or source input is rejected at preparation. Preparation is eager: if both the
model and query are invalid, the first error can differ from the original
single-call API's query-first order. Both APIs reject the request. No equivalence
of error precedence is claimed across this deliberately explicit preparation
boundary.

## Source preservation and trust boundary

The original module remains byte-identical. The new implementation copies its
query-validation and decision bodies, replacing only the call to `prepare_model`
and the construction of a mutable model payload. An AST equivalence check covers
all unchanged statements. Preparation checks the full original source file
against the recorded frozen SHA-256 value. The existing arithmetic lock continues
to protect Arb precision contexts across concurrent certificate calls.

A prepared object is a local Python capability, not a transport format or a
cryptographic security boundary against arbitrary code inside the interpreter.
Python reflection can bypass ordinary immutability. Native executable, source
closure, arithmetic dependencies and persisted replay remain the owner adapter's
responsibility. The batch optimization does not relax those checks.

## Executed functional checks

`python reproduction/check_window_batch.py` writes
`results/epoch_batch/functional_checks.json`. It compares all 284 cases from the
preceding reachability study and all 21 saved adversarial cases with freshly
executed original certificates. Additional checks cover alternate precision
ladders, stationary and unsupported models, unknown results, huge phase arguments,
invalid queries, malformed sources, preparation and output alias isolation,
ordinary immutability, rejected forged instances, batch limits and four-thread
agreement under the existing Arb lock.

The check establishes full-certificate equivalence on those executed cases and
source equivalence of the decision body. Independent mathematical verification
of the inherited certificates remains supplied by the existing full-matrix and
reachability-verifier material. Functional comparison is not a speed measurement.
