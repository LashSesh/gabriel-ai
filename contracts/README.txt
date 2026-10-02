PROPOSED GABRIEL AI CONTRACTS

These files are companion specifications, not a runtime implementation. Every
acceptance case is NOT_EXECUTED. The synthetic examples show representation and
cross-link consistency only. No example log states that Gabriel executed tests.

Run: python tools/validate_spec.py
Install: python -m pip install -r contracts/validator-requirements.txt
Dependency: jsonschema 4.25.1 (and its pinned dependencies). Run from the project
root or any directory; the checker resolves its own project root. It writes
an honest execution record to evidence/spec_validation.json on success/failure.

Schemas use Draft 2020-12. Objects are closed. Safe integer fields have an upper
bound 2^53-1; the companion validator additionally rejects bool and floating JSON
tokens as integers. Duplicate object keys and non-finite JSON tokens reject.
Arbitrary Unicode and binary data are immutable artifact bytes; envelopes contain
only ASCII identifiers and artifact references. The example goal blob deliberately
contains non-ASCII UTF-8 to test that boundary. artifact-ref does not confer access.

Schema IDs under https://gabriel.invalid are local identifiers and are not fetched.
The checker uses a local schema registry. Every positive example has a manifest
entry. Object files in examples/objects are exact synthetic content, named by
SHA-256. Repeated-a digests in policy/verifier/schema fields are explicitly dummy
identities. The example zero currency ceiling authorizes no paid provider call.

Cross-record rules remain runtime responsibilities: grants and principal binding,
current expiry and revocation, content durability, transactional event ordering,
lease fencing, result identity, idempotency, checks before completion, budget
accounting, temporal source revisions and effect reconciliation. JSON Schema
cannot establish these. The checker exercises a limited subset for static examples.

Requirements R01..R12 map to work packages WP01..WP12 and acceptance designs
AT01..AT25. Work-package dependencies form a DAG; they are implementation gates,
not dates. G1 depends through WP08 plus relevant evaluation/release checks; the
WP10 PSE integration is optional for G1. WP11/WP12 include the mandatory G1
evaluation/release route without waiting for WP09 or WP10. Additional G2/G3
gates are explicit in work-packages.json; package completion alone does not
establish policy improvement.

TaskSpec has task_spec_revision. Run pins task_spec_ref and owns run_revision,
state and the pause_requested flag. Command carries expected_revision for the
named run; Event records run_revision. Pause is not an additional lifecycle
state. ExecutionResult outputs bind output_slot, artifact_ref and schema_digest;
future plan inputs name producer_node, output_slot and required_schema.
ModelRequest binds observation_ids and issue_frontier as well as exact evidence
bytes. Claim statuses are supported, contested, unresolved, out_of_scope and
invalid. Only a scoped verifier assessment may justify supported.

Budget.elapsed_ms is the run wall-clock deadline allowance, not an additive
resource. It is excluded from spent + reserved + demand accounting. Usage
elapsed_ms reports attempt latency and is not summed into that run deadline.

V1.1 adds a closed DomainPack manifest with six typed ports, coverage, profiles,
capability requirements, conventions and valid/invalid/out-of-scope fixture refs.
The example includes exact byte artifacts; its implementation descriptor is
explicitly NON_EXECUTABLE and NOT_IMPLEMENTED. The manifest is synthetic, not a
registered plugin or a passed domain task. A pack logical ID is not its byte
digest; registration binds the complete immutable manifest and validates every
referenced handler/profile/schema. Registration confers no capability grants.

AT19..AT25 are future product acceptance designs, all NOT_EXECUTED. The partial
reference kernel tests elsewhere do not execute these end-to-end acceptance
cases. Release-scoped acceptance lists distinguish G1 from domain portability
(AT23) and procedure/compaction promotion (AT25), preserving the G1 dependency
closure without WP09 or WP10.
