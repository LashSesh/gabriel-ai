# Complete semantic replay by expected-byte comparison

`ReplayStore` is selected with `--owner replay`. It inherits live submissions,
reads and exports from `FastStore`. The reference owner remains the default and
the v1 SQLite journal needs no migration. Owner choice is independent of the
fixed adapter profile.

Every command is independently decoded and validated, and every transition is
recomputed on opening or auditing. Derived record, receipt, configuration and
terminal state text must equal canonical text generated during that replay.
For canonical encoder C and strict decoder L, the reference conditions
`C(L(s)) == s` and `C(L(s)) == C(y)` are equivalent to `s == C(y)` when y is a
fresh valid interchange value. No stored receipt supplies reconstructed state.

The newest canonical state string per contract is retained only within an audit
to avoid recomputing the next pre-state digest. It is not a trusted checkpoint
and is discarded after the audit. The aggregate `canonical(bindings)` check is
retained: separate valid states do not guarantee a valid complete binding object
under the depth-64 domain. Registry, budgets, order, metadata and external anchors
are checked with the same rules. Rejection timing and messages may differ.

The equivalence argument requires deterministic value-based trusted adapters,
stable inputs, the declared database schema, the same numerical environment and
normal resource availability. It does not cover object-identity-dependent code,
malicious executable adapters or physical power-loss guarantees.

Executed verification is in `results/replay_owner_checks.json` and
`results/replay_owner_cli_checks.json`: exact receipts, every stored SQL field,
53 deliberately corrupted databases, nested aggregate boundaries, complete
re-execution, cross-owner continuation, retries and concurrent head admission.
Live durability code is unchanged; new physical-crash tests are not claimed.
The frozen opening benchmark and all individual timings are in
`results/replay_benchmark*.json`. No forecast model or score changes.
