# Strict batch independent review

Scope: the additive prepared-window model, its native Engine/Store adapter,
the certificate-preservation proposition, and the frozen two-profile complete
owner experiment. This is an internal technical review, not external peer review.

## Findings and resolution

1. **The owner boundary is preserved.** After normalizing qualified references
   and isolating the certificate-producing expression, the complete new `apply`
   abstract syntax tree equals the old transition. Constructor and identity-guard
   syntax also match after qualifier normalization. Native invocation and input
   validation are inherited unchanged. The old 72-file production closure is
   retained and the strict profile adds exactly its two production modules.
   Actual execution and replay traces independently confirmed every original
   guard call; batching does not remove integrity observations.
2. **Equivalence is an issue/certificate claim.** Complete issue bytes agree;
   adapter fingerprints, profile labels and resulting journal heads differ.
   Every journal must therefore replay with its own profile. The manuscript
   and protocol make this distinction explicitly.
3. **Preparation is immutable through the supported local API.** Detached
   tuples, rational values and the serialized payload prevent caller-input and
   returned-output aliasing. Reflective Python can bypass ordinary object
   protections; the module and manuscript correctly exclude an in-process
   adversary from this immutability claim. No cross-command cache is present.
4. **Malformed local capabilities required normalized rejection.** An early
   inspection identified direct `_seal` access on an uninitialized object as a
   possible `AttributeError`. The implementation uses `getattr(..., None)` and
   rejects it with `ValueError`; the producer's completed checks and a fresh
   explicit probe confirm the corrected behavior. This was resolved before the
   frozen benchmark.
5. **Invalid standalone requests are not exception-order equivalent.** Eager
   model preparation can report a different first error when both model and
   query are invalid. The mathematical proposition is restricted to valid
   inputs, this difference is documented, and the owner retains full payload
   validation and atomic rejection. No partial issue is committed.
6. **The optimization does not establish a new mathematical decision rule.**
   Its contribution is reusable exact preparation with complete certificate
   equivalence and actual owner integration. Per-query numerical counters remain
   unchanged; model-preparation work and the additional reference-source hash
   are separate costs. The manuscript cost decomposition reflects this.
7. **Guard coverage needed a phase-specific completion.** The main functional
   checker covered seven atomic failures and identical retries. Fresh strict
   profile conflicting-id, stale-head, wrong-anchor and valid-prefix rollback
   controls were requested because they appear in the frozen acceptance
   protocol. They are supplied separately by
   `reproduction/check_batch_protocol_guards.py`. Its completed execution record
   `results/epoch_batch/protocol_guards.json` reports all seven negative controls
   passing, unchanged rejected database bytes and final anchored semantic replay.
   The valid prefix is accepted without an external anchor, then rejected with
   the retained final anchors. This execution record is separate from the
   independent archive verification reported below.

## Executed independent checks

`reproduction/verify_batched_owner.py` imports neither the experiment collector
nor its aggregation code. Its own fixture generator reconstructs all 40 task
inputs. It recomputes complete certificates with the frozen scalar reference and
uses the unchanged earlier mathematical verifier for a separate numerical path:
quadrature-derived coefficients and complex projector evolution. Arb remains a
shared arithmetic dependency; this is not a proof-assistant verification.

- Two additional owners each executed two successive observations with changed
  sources and target sets; full issues, actual guard traces and fresh own-profile
  semantic replay agreed.
- All 745 files in the sealed experiment archive passed manifest and byte checks.
- All 76 frozen source/protocol/collector identities matched the delivered files.
- All 240 measured database files passed independent SQL integrity, journal
  hash-chain, final reducer-state and receipt reconstruction.
- All 3,336 emitted certificates matched complete independently recomputed scalar
  bytes. The 424 supported fixture-window certificates passed 12,459 assertions
  in the separate mathematical verifier. Generic fixtures additionally exhibited
  failure of the exact uniform-clique matrix condition.
- All 240 databases underwent an **additional actual native semantic replay**
  from private temporary copies, with saved external head/event anchors. Every
  closed database retained its original bytes.
- Published per-task times, paired ratios, subgroups and both prespecified speed
  gates were independently recomputed from the raw records.

Machine-readable evidence:
`results/epoch_owner_study/independent_verification.json`.

Archive SHA-256:
`d2ca7978215127e6716aeaf666c47d913542d852b8844cd1b5de531b97fa3c9c`.

Verifier SHA-256:
`57e1ad0b06e9c763cf6336f7e010b138c94de9953f6a90b3b1fd7827914b241a`.

## Interpretation retained after review

The all-primary median paired scalar/batch ratio is
1.0213144699872245 over 96 pairs. Its prespecified gate **fails**; the n=13
subgroup median is also below one. The separately predeclared demanding subgroup
(n in {32,64}, windows in {16,32}) has median ratio 1.2661148583170005 over
24 pairs and passes its workload-specific gate. Individual demanding cases can
still regress (minimum paired ratio 0.8888946738655784).

The evidence supports a bounded synthetic complete-task engineering benefit.
It does not establish uniformly faster execution, generic-graph support, a
predictive improvement, an external financial advantage, physical power-loss
durability, authenticated executable trust, or general superiority of Gabriel.
No blocking defect was found in the new preservation proposition or its stated
resource and trust qualifications.
