# ADR-23 witness: erosion of the association history (linux_namespace)

Produced 2026-10-04T13:50:01.365154+00:00 on Linux-6.18.44-fc-v64-x86_64-with-glibc2.39; `engine_observer` a8e1f6d7db2ef7ab; provider scripted (fixture deliverables).

| step | state | view | policy revision | association status | annex in prompt | erosion |
|---|---|---|---|---|---|---|
| history | succeeded | associative | 0 | no_history | yes (rank 1, 0 milli) | 0/0 claims, removed {} |
| summary_associative | succeeded | associative | 0 | computed | yes (rank 2, 230 milli) | 1/1 claims, removed {} |
| summary_annex_withdrawn | failed | associative | 1 | eroded | no (revoked, superseded) | 0/2 claims, removed {'revoked': 2} |

| reproduction | service | CLI exit | retained -> recomputed status |
|---|---|---|---|
| summary_associative | reproduced (differences []) | 0 | computed -> computed |
| summary_annex_withdrawn | reproduced (differences []) | 0 | eroded -> eroded |

| check | result |
|---|---|
| history_established_a_supported_claim | passed |
| associative_view_carried_the_annex | passed |
| withdrawal_recorded_in_the_chain_by_the_run | passed |
| history_eroded_after_the_withdrawal | passed |
| annex_absent_from_the_prompt | passed |
| no_key_outside_the_candidates_named | passed |
| both_manifests_reproduce_from_the_chain | passed |
| earlier_manifest_reproduces_at_its_own_revision | passed |
| owner_replay_passed | passed |
| memory_chain_verified | passed |

Status: **passed**. Owner replay passed; memory chain passed (91 entries); 1 revocation record(s) in the chain.

Retained: `witness.json` (every value above with the retrieval manifest digests), `manifest-<step>.json` (the three retrieval manifests as retained).
The workspace under `work/` is not committed.
