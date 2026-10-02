# Final mathematical and manuscript review

Scope: static review of `main.tex`, sections `sec:engineobserver` and
`sec:engineobserverprotocol`, their immediately preceding boundary, and the
corresponding observer/readout and experiment definitions. The review reads
`native_pse/src/conditioned.rs`, the native task harness, the graph-observer
owner adapter, and the owner task harness. It changes no measured source.

## Conclusion

The regional-response proposition and proof are correct. The sign of the sine
term is correct for complex inputs. The rank bound applies to intensity
features at arbitrarily many sampling times; it makes no claim that changing
the source or graph leaves the same feature span. The discussion correctly
separates a strategic task objective from a nonexistent unitary attracting
state. The non-clique fallback and complete-task versus query-only distinction
are represented faithfully.

The new observer normalizes before propagation using the maximum real or
imaginary component and then a bounded Euclidean norm. Thus the previously
identified subnormal-source mismatch between the full-state and direct-region
paths is addressed in the current source. The lower-level arbitrary-norm API
remains separate. This review did not execute the Rust suite again; executed
validation remains in its own captured logs.

The exact response formula, simultaneous relabelling invariance, source-phase
invariance, coherent/incoherent distinction and stated error inequality are
sound. Numerical division by the stored normalized source norm is described;
there is no undocumented output-sum normalization. The direct frequency `n*w`
and separately rounded state phases need not be bitwise equal, as the text
now states. The measured finite-time checks are not promoted to universal
error enclosures.

The near-clique controls really omit one undirected pair and retain weight
0.5 on each represented edge. Their generation and dispatch are checked by the
harness and independently reconstructed by the reporter. The clique proof is
not extended to them. The source projection rejects invalid raw weights before
the legacy nonnegative symmetrization. It remains an undirected model, not a
model of directed or signed financial exposures.

The native protocol counts, unique-time grid, source construction, scalar
output contract, preparation intervals and owner experiment task count match
the inspected definitions. No external outcome label enters this task.

## Corrections reported to the integrating author

1. A stale sentence immediately before `sec:engineobserver` says the new
   state-query API does not participate in current owner replay. This conflicts
   with the newly implemented owner adapter and must be replaced by an explicit
   cross-reference to the integration. The D6 helper remains separate.
2. The native harness serializes the third status as `abstain`; the durable
   adapter serializes it as `ambiguous`. Both implement the stated unresolved
   interval, including its endpoints. The manuscript should name these two wire
   labels rather than imply that `unresolved` is their shared serialized value.
   Equality of reported statuses is checked within each experiment.
3. The public owner adapter accepts a deadband of zero. Its general contract
   should say nonnegative deadband, with threshold and deadband in [0,1]; the
   measured protocol correctly uses the positive value 1e-7.
4. To avoid attributing a linear bound to identifier lookup and validation,
   qualify the coefficient-cost statement as applying after target coordinates
   have been resolved. The algebraic linear preparation claim is correct.

These are documentation repairs; no change to a measured implementation or
numerical conclusion is required. Main manuscript edits were left to the root
agent to avoid simultaneous mutation of `main.tex`.
