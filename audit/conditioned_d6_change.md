# D6 auxiliary group correction

## Scope and construction

Only `native_pse/crates/pse-metatron/src/group.rs` was changed. The S7 generator, permutation matrix, conjugation, C6 generator, and rotation implementations are unchanged. This correction concerns the public auxiliary hexagon group API; the current S7 graph-signature implementations do not call `generate_d6`.

Previously, six rotations were followed by reflections through each of six vertices. Opposite vertices define the same axis, so the returned 12 entries contained only nine distinct permutations and were not closed under composition.

The corrected ordering is `r^0, ..., r^5, r^0 s, ..., r^5 s`, where `r` is one positive vertex rotation and `s` reflects through nodes 2 and 5. Permutations are one-based point images, and `r^k s` applies `s` first. This includes three vertex-axis and three edge-axis reflections and preserves the `ScanResult<Vec<Vec<usize>>>` return type. The first six entries remain unchanged; callers persisting reflection indices must account for the changed final six entries.

`hexagon_reflection` now uses exact integer arithmetic on the six cyclic vertex indices: `i -> 2a - i (mod 6)`. All valid axes retain their geometric meaning. Invalid axes outside `2..=7` now return `ScanError::InvalidIndex { index, n: 7 }`; previously they silently aliased the axis through node 2. This is an intentional input-contract tightening.

## Verification status

Five Rust regression tests were added in the same source file:

- 12 distinct bijections and the fixed centre;
- all 144 products, identity, and two-sided inverses;
- deterministic ordering, `r^6 = e`, `s^2 = e`, and `s r s = r^-1`;
- preservation of all hexagon edges and exactly three reflections of each axis type;
- opposite-vertex axes and rejected indices `0`, `1`, `8`, `usize::MAX`.

The existing count test remains. This agent did not compile or run Rust tests; the coordinating agent runs the serialized project test command and records its result separately. An independent Python integer-formula check was executed successfully for uniqueness, bijectivity, fixed centre, all 144 products, the dihedral relation, and the two axis types. That check validates the mathematical construction and is not claimed as execution of the Rust implementation.

## Source hashes

SHA-256 before: `ca44f1648ab00d770bf6de70c52ec62ee964ac14785a4f9511e1f36e292271b7`

SHA-256 after: `b8274e4e02bec6dc2884a87df0480b3c87a73907fb3384002aff0a69ff712947`

These hashes refer only to `native_pse/crates/pse-metatron/src/group.rs` at this edit boundary. Later formatting or other authorized edits require a refreshed hash.
