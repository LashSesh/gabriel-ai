# ADR-12: Retained reducer inputs beside the event chain

**Status:** accepted. **Affects:** journal layout (`events.inputs_text`, `events.inputs_hash`, `meta.inputs_head`), anchors, checkpoints.

## Context
The reducer is pure: trusted owner time, grant state, approvals, catalog identity and
artifact-verification results arrive as validated inputs. Recorded replay must re-run the
reducer over exactly those inputs, and must check the historical authorization decision rather
than today's expiry. The closed `gabriel.event/1` envelope has a single `payload_ref` and no
field for these inputs.

## Decision
Every event row retains the canonical bytes of its reducer inputs and a running hash
`inputs_hash = sha256(previous_inputs_head || inputs_text)`. The event hash chain is unchanged
(`sha256("gabriel.event/1:" || canonical envelope)`). Anchors (`gabriel.anchor/1`) and
checkpoints bind both heads. Catalog descriptors are not serialized per event; their digest is
retained and the live catalog must match it at open and at replay.

## Consequences
Replay recomputes every projection digest from retained payload bytes and retained inputs
without calling any port; a changed catalog, reducer or schema registry is refused at open. The
inputs chain is an additional integrity commitment, not part of the public event schema.
