# ADR-13: DomainPack ports and shared worktree tooling

**Status:** accepted. **Affects:** `agent/runner.py`, `agent/workspace.py`, `domains/base.py`, every pack.

## Context
The G1 slice was built with the runner importing the software pack directly: plan
materialization, prompt building, proposal normalization, tool argument binding and verifier
selection were software functions called by name. Requirement R11 and AT23 need one core that
serves repository repair, document amendment and numerical transformation without branching on
a domain name.

## Decision
`domains/base.py` defines the `DomainPack` contract the core calls: `compile_task`,
`reference_plan_proposal`, generic `materialize_plan` (parameterized by the pack's output
slots, retry classes and reservations), `load_snapshot`, `build_prompt` (returning the selected
observation ids), `normalize_proposal`, `node_args`, `target_for` and `verifier_id`. A task
binding names its pack by namespace; the workspace resolves it through a registry of packs
(`build_packs`), and the runner only ever calls pack methods. One `ToolRegistry` holds every
pack's tools and verifiers, so the catalog digest a workspace pins covers all of them.

File-level operations on a git worktree (apply operations with identity preconditions, review
of scope, base commit, protected files and secrets) are domain-neutral and are shared: the
document pack registers them under its own capability ids with the same implementation
classes. Each pack keeps its own observation schema and tool ids; `compile_generic` is the
loss-preserving compilation shared by packs without a baseline-run notion.

## Consequences
Existing workspaces are invalidated at open (the catalog changed), as documented. Adding a
domain means adding a pack, its schemas and fixtures; the owner, reducer, scheduler and
supervisor stay untouched. The evaluation harness still calls the software pack's module
functions directly; they delegate to the same implementations.
